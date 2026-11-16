"""Cancelable Pulse assembly using the editor's existing FFmpeg export pipeline."""
import json
from pathlib import Path
import tempfile

from capture.ffmpeg_backend import validate_output, validate_audio_coverage
from .auto_analysis import check_cancel, run_local
from .auto_plan import editor_state, validate_plan
from .ffmpeg_export import build_plan_segment_command, build_plan_join_command
from .media import probe_media
from .pulse_plan import verify_source, timeline_positions
from .text_overlay import TextOverlay, TextResources


def assemble_plan(backend, media, plan, root, cancel, progress=lambda message: None):
    """Return a unique review folder and assembled media. Never publish an export.

    Keep the validated recipe beside the review media, with captions still
    editable in Quick Edit. No paths, commands or filters come from the JSON.
    """
    validate_plan(plan, media)
    progress('Verifying source identity…')
    verify_source(plan, media, cancel)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='pulse-plan-', dir=root))
    # Only clean files created in this new private directory on failure.
    complete = False
    try:
        positions = timeline_positions(plan)
        with tempfile.TemporaryDirectory(prefix='segments-', dir=folder) as temporary:
            scratch = Path(temporary)
            assembled = None
            for index, item in enumerate(plan['timeline']):
                check_cancel(cancel)
                progress(f'Rendering element {index+1}/{len(plan["timeline"])} · {item["kind"]}…')
                segment = scratch / f'element-{index}.mp4'
                text = (TextOverlay(True, item['text'], position='Centre', safe_area=True)
                        if item['kind'] == 'title' else TextOverlay())
                with TextResources(text) as resources:
                    command = build_plan_segment_command(backend.ffmpeg, media, item, segment,
                                                         plan['output']['framing'], resources)
                    run_local(command, cancel, 1800)
                if assembled is None:
                    assembled = segment
                else:
                    joined = scratch / f'joined-{index}.mp4'
                    run_local(build_plan_join_command(backend.ffmpeg, assembled, segment, joined,
                              positions[index-1][1], item.get('transition', {}), positions[index][1]), cancel, 1800)
                    assembled.unlink()
                    segment.unlink()
                    assembled = joined
            progress('Checking assembled picture, duration and synchronized audio…')
            info = validate_output(backend.ffprobe, assembled, True)
            validate_audio_coverage(info)
            result = probe_media(backend.ffprobe, assembled)
            editor_state(plan, media, assembled_media=result)
            run_local([str(backend.ffmpeg), '-v', 'error', '-nostdin', '-xerror', '-i', str(assembled),
                       '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], cancel, 600)
            # Catch a recording replaced or still being written during assembly.
            verify_source(plan, media, cancel)
            review = folder / 'review.mp4'
            assembled.rename(review)
        (folder / 'pulse-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        scripts = [f'{a:.3f}–{b:.3f}s · {item.get("role", item["kind"])}\n{item["commentary"]}'
                   for item, (a, b) in zip(plan['timeline'], positions) if item.get('commentary')]
        if scripts:
            (folder / 'voiceover-script.txt').write_text(
                'SCRIPT ONLY — no narration audio has been generated.\n\n'+'\n\n'.join(scripts), encoding='utf-8')
        complete = True
        return folder, probe_media(backend.ffprobe, review)
    finally:
        if not complete:
            # The directory is newly allocated here, never supplied by a plan.
            import shutil
            shutil.rmtree(folder)
