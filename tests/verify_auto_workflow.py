"""Real generated-fixture acceptance exercise; writes retained outputs and measurements."""
import argparse
import json
import math
from pathlib import Path
import threading

from capture.ffmpeg_backend import discover
from editor.auto_ai import Pricing
from editor.auto_analysis import atomic_json, fingerprint, run_local
from editor.auto_job import AutoJob
from editor.auto_plan import AutoOptions, editor_state, overlap_seconds
from editor.export_job import ExportJob
from editor.media import probe_media
from editor.preview import preview_command
from editor.text_overlay import TextResources


def verify(source, output, ai=False):
    backend = discover()
    media = probe_media(backend.ffprobe, source)
    cancel = threading.Event()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprint(source, cancel)
    job = AutoJob(backend, media, AutoOptions(), Pricing(), output/'cache')
    job.prepare(cancel, lambda text: print(text, flush=True))
    if ai:
        import os
        payload, plan_path = job.ai(cancel, os.environ.get('OPENAI_API_KEY', ''))
    else:
        payload, plan_path = job.local(cancel)
    print(f'{payload["mode"]}: {len(payload["plan"]["shorts"])} candidates; {job.quote}', flush=True)
    if len(payload['plan']['shorts']) != 3:
        raise AssertionError('The generated fixture should yield three distinct Shorts.')
    rows = []
    for index, short in enumerate(payload['plan']['shorts']):
        trim, cuts, edits = editor_state(short, media, job.transcript)
        export = ExportJob(backend, verify_short=True)
        export.start(media, trim, output, edits, cuts)
        if not export.wait(600):
            export.cancel()
            export.wait(30)
            raise AssertionError('Export timed out.')
        events = []
        while not export.events.empty():
            events.append(export.events.get())
        event = events[-1]
        if event.kind != 'saved':
            raise AssertionError(event.message)
        print(f'Exported and fully decoded: {event.path}', flush=True)
        # Save representative actual preview frames for visual comparison.
        samples = []
        sample_times = [trim.start+.5, trim.start+2.5, (trim.start+trim.end)/2, trim.end-1]
        if edits.text.captions:
            sample_times.append((edits.text.captions[0].start+edits.text.captions[0].end)/2)
        with TextResources(edits.text) as resources:
            for n, at in enumerate(sample_times):
                frame = run_local(preview_command(backend.ffmpeg, media, at, 360, 640, edits, False,
                                                  resources, trim, cuts), cancel, 30)
                target = output/f'short-{index+1}-preview-{n+1}.ppm'
                target.write_bytes(frame)
                samples.append(str(target))
        # Independent fixture-only geometric check, excluding scene transitions.
        visible, total = 0, 0
        for n in range(int(cuts.kept_duration(trim)*2)):
            at = cuts.source_from_elapsed(n/2+.1, trim)
            scene = min(5, int(at/21))
            local = at-scene*21
            if local < 1 or local > 20:
                continue
            x = (.50+.18*math.sin(local*.32), .24+.52*local/22, .76-.52*local/22,
                 .5+.25*math.sin(local*.35), .5+.25*math.sin(local*.50), .3+.4*local/22)[scene]*1280
            crop = edits.crop_at(media, at)
            total += 1
            visible += crop.x <= x-75 and x+75 <= crop.x+crop.width
        audio_sync = audio_alignment(backend, media, event.path, trim, cuts, cancel)
        rows.append({'output': str(event.path), 'duration': cuts.kept_duration(trim), 'title': short['title'],
                     'shots': short['shots'], 'speech_captions': len(edits.text.captions),
                     'fixture_subject_fully_visible_fraction': visible/max(1, total),
                     'audio_alignment': audio_sync, 'preview_frames': samples,
                     'full_decode_verified': True})
    unchanged = fingerprint(source, cancel) == before
    if not unchanged:
        raise AssertionError('Source changed.')
    overlap = [overlap_seconds(a, b) for i, a in enumerate(payload['plan']['shorts']) for b in payload['plan']['shorts'][:i]]
    report = {'mode': payload['mode'], 'source': str(source), 'source_duration': media.duration,
              'source_preserved': unchanged, 'plan': str(plan_path), 'quote': job.quote,
              'usage': payload['usage'], 'transcript_note': job.transcript_note,
              'candidate_overlap_seconds': overlap, 'shorts': rows,
              'ai_quality_tested': ai, 'real_gta_footage_tested': False}
    atomic_json(output/'verification.json', report)
    print(json.dumps(report, indent=2), flush=True)
    return report


def audio_alignment(backend, media, output, trim, cuts, cancel):
    import numpy as np
    command = [str(backend.ffmpeg), '-v', 'error', '-nostdin', '-i', str(media.path)]
    segments = cuts.kept_segments(trim)
    graph = [f'[0:a:0]atrim=start={s.start}:end={s.end},asetpts=PTS-STARTPTS[a{i}]' for i, s in enumerate(segments)]
    if len(segments) > 1:
        graph.append(''.join(f'[a{i}]' for i in range(len(segments)))+f'concat=n={len(segments)}:v=0:a=1[reference]')
        label = '[reference]'
    else:
        label = '[a0]'
    reference = run_local(command+['-filter_complex', ';'.join(graph), '-map', label,
                                  '-ac', '1', '-ar', '8000', '-f', 'f32le', 'pipe:1'], cancel)
    actual = run_local([str(backend.ffmpeg), '-v', 'error', '-nostdin', '-i', str(output),
                        '-map', '0:a:0', '-ac', '1', '-ar', '8000', '-f', 'f32le', 'pipe:1'], cancel)
    a, b = np.frombuffer(reference, dtype='<f4'), np.frombuffer(actual, dtype='<f4')
    length = min(len(a), len(b))
    a, b = a[:length], b[:length]
    if float(np.linalg.norm(a)) < 1e-5:
        return {'silent': True, 'lag_ms': 0, 'correlation': None}
    # FFT cross-correlation checks the actual encoded waveform, not only metadata.
    size = 1 << (2*length-1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(b, size)*np.conj(np.fft.rfft(a, size)), size)
    lags = np.arange(-1600, 1601)
    best = int(lags[np.argmax(corr[lags % size])])
    normalized = float(corr[best % size]/(np.linalg.norm(a)*np.linalg.norm(b)))
    if abs(best/8) > 50 or normalized < .95:
        raise AssertionError(f'Audio mismatch: lag {best/8}ms, correlation {normalized}')
    return {'silent': False, 'lag_ms': best/8, 'correlation': normalized}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='auto-edit-output/pulse-auto-test-127s.mp4')
    parser.add_argument('--output', default='auto-edit-output/verified')
    parser.add_argument('--ai', action='store_true')
    args = parser.parse_args()
    verify(Path(args.source).resolve(), args.output, args.ai)
