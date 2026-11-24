"""Continuous edited preview: one decoder per kept section, bounded frame queue.

The source seek is input-side. Effect clocks retain their original kept/output
times, so seeking does not restart a caption, zoom, fade or reaction animation.
Workers never call Tk. Cancellation owns only the active FFmpeg child.
"""
from collections import deque
from dataclasses import dataclass
import subprocess
import tempfile
import threading

from branding import watermark_path
from capture.ffmpeg_backend import process_options
from .preview import Frame
from .reactions import add_visuals
from .text_overlay import TextResources
from .transforms import video_filters


FPS = 30
MAX_FRAMES = 30


def preview_size(media, edits, width, height, maximum=480):
    w,h=edits.encoded_size(media)
    scale=min(max(2,width)/w,max(2,height)/h,maximum/max(w,h),1)
    return max(2,int(w*scale)//2*2),max(2,int(h*scale)//2*2)


def playback_command(ffmpeg, media, start, end, trim, cuts, edits, width, height, resources):
    """Share export effects, but seek directly to this remaining source section."""
    offset=cuts.source_elapsed(start,trim)
    args=[str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin',
          '-ss',f'{start:.9f}','-t',f'{end-start:.9f}','-i',str(media.path)]
    if edits.branding.enabled:args+=['-i',str(watermark_path())]
    filters,complex_graph=video_filters(media,edits,watermark_path(),resources,
        cuts.kept_duration(trim),trim=trim,cuts=cuts,clock_offset=offset,source_offset=start)
    graph=[filters] if complex_graph else [f'[0:v:0]{filters}[v]']
    out_w,out_h=edits.encoded_size(media)
    from .imported_media import add_media
    current=add_media(args,graph,'v',edits.media_clips,out_w,out_h,offset=offset/edits.speed)
    current=add_visuals(args,graph,current,edits.overlays,out_w,out_h,bands=edits.bands(media))
    graph.append(f'[{current}]setpts=PTS-STARTPTS,format=yuv420p,scale={width}:{height}:flags=bilinear,setsar=1[playback]')
    return args+['-filter_complex_threads','1','-filter_complex',';'.join(graph),
        '-map','[playback]','-an','-t',f'{(end-start)/edits.speed:.9f}',
        '-r',str(FPS),'-fps_mode','cfr','-pix_fmt','rgb24','-c:v','rawvideo','-f','rawvideo','pipe:1']


@dataclass(frozen=True)
class PlaybackFrame:
    time: float
    frame: Frame


class PlaybackPreview:
    def __init__(self, ffmpeg, media):
        self.ffmpeg,self.media=ffmpeg,media
        self._condition=threading.Condition()
        self._pending=None
        self._process=None
        self._generation=0
        self._closed=False
        self._frames=deque()
        self.error=''
        self.finished=False
        self.process_count=0
        self._thread=threading.Thread(target=self._run,daemon=True,name='Pulse continuous video')
        self._thread.start()

    def _cancel_locked(self):
        self._generation+=1
        if self._process is not None and self._process.poll() is None:
            try:self._process.terminate()
            except OSError:pass
        self._frames.clear()
        self._condition.notify_all()

    def play(self, token, position, width, height, edits, trim, cuts, maximum=480):
        with self._condition:
            if self._closed:return
            self._cancel_locked()
            self.error='';self.finished=False
            self._pending=(self._generation,token,position,width,height,edits,trim,cuts,maximum)
            self._condition.notify_all()

    def stop(self):
        with self._condition:
            self._pending=None
            self._cancel_locked()

    def close(self):
        with self._condition:
            self._closed=True
            self._pending=None
            self._cancel_locked()

    def take_due(self, output_time):
        """Keep a future frame; discard late frames only against the audio clock."""
        with self._condition:
            result=None
            while self._frames and self._frames[0].time<=output_time+1e-7:
                result=self._frames.popleft().frame
            self._condition.notify_all()
            return result

    def _current(self, generation):
        return not self._closed and generation==self._generation

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda:self._closed or self._pending is not None)
                if self._closed:return
                request=self._pending;self._pending=None
            generation,token,position,width,height,edits,trim,cuts,maximum=request
            try:
                width,height=preview_size(self.media,edits,width,height,maximum)
                with TextResources(edits.text) as resources:
                    for segment in cuts.kept_segments(trim):
                        start=max(position,segment.start)
                        if segment.end<=start:continue
                        if not self._current(generation):break
                        self._decode(generation,token,start,segment.end,trim,cuts,edits,width,height,resources)
            except Exception as exc:
                with self._condition:
                    if self._current(generation):self.error=str(exc)
            finally:
                with self._condition:
                    if self._current(generation):self.finished=True

    def _decode(self,generation,token,start,end,trim,cuts,edits,width,height,resources):
        command=playback_command(self.ffmpeg,self.media,start,end,trim,cuts,edits,width,height,resources)
        process=None
        # A bounded-on-read temporary log avoids a full stderr pipe stalling decoding.
        with tempfile.TemporaryFile() as errors:
            try:
                with self._condition:
                    if not self._current(generation):return
                    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                             stderr=errors,**process_options())
                    self._process=process;self.process_count+=1
                count=0;size=width*height*3
                offset=cuts.source_elapsed(start,trim)/edits.speed
                header=f'P6\n{width} {height}\n255\n'.encode('ascii')
                while self._current(generation):
                    data=process.stdout.read(size)
                    if not data:break
                    if len(data)!=size:raise RuntimeError('Preview decoder returned an incomplete frame.')
                    at=offset+count/FPS;count+=1
                    frame=PlaybackFrame(at,Frame(token,min(end,start+(count-1)/FPS*edits.speed),
                        header+data,source_view=False,edits=edits))
                    with self._condition:
                        self._condition.wait_for(lambda:not self._current(generation) or len(self._frames)<MAX_FRAMES)
                        if not self._current(generation):return
                        self._frames.append(frame)
                if self._current(generation):
                    code=process.wait(timeout=5)
                    if code:
                        errors.seek(0)
                        raise RuntimeError('Continuous preview failed: '+errors.read(2000).decode('utf-8','replace'))
                    if not count:raise RuntimeError('Continuous preview returned no video frames.')
            finally:
                if process:
                    if process.poll() is None:process.kill()
                    process.wait(timeout=5)
                    process.stdout.close()
                with self._condition:
                    if self._process is process:self._process=None
