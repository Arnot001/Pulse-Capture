"""Generate local test footage and a matching, importable plan. No downloads."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.auto_plan import validate_plan
from editor.media import probe_media
from editor.pulse_plan import source_identity, starter_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='New folder for fixture and plan')
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or 'vendor/ffmpeg.exe')
    parser.add_argument('--ffprobe', default=shutil.which('ffprobe') or 'vendor/ffprobe.exe')
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=False)
    source = args.folder/'pulse-demo.mp4'
    subprocess.run([args.ffmpeg, '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                    'testsrc2=size=640x360:rate=30,drawbox=x=0:y=0:w=30:h=360:c=red:t=fill,'
                    'drawbox=x=610:y=0:w=30:h=360:c=blue:t=fill',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '6',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
    media = probe_media(args.ffprobe, source)
    plan = starter_plan(media, source_identity(media, threading.Event()))
    plan['title'] = 'The disappearing pocket'
    plan['style'] = 'Comedy / Roast'
    plan['notes'] = 'Fixture demonstration, not a claim about gameplay. Review all footage before publishing.'
    plan['timeline'] = [
        dict(kind='title', text='POCKET MAGIC?', duration=1, font_size=60, animation='slide', at=0),
        dict(kind='shot', start=0, end=1, start_frame=0, end_frame=30, role='setup', at=1,
             commentary='Nothing visible yet. Script only; record narration separately.'),
        dict(kind='shot', start=4, end=5, role='reveal', at=2),
        dict(kind='freeze', source_time=4.5, duration=1, role='punchline', at=3),
        dict(kind='shot', start=0, end=1, speed=.5, volume=.7, role='replay', at=3.8,
             zoom=dict(factor=1.5, x=.5, y=.5), transition=dict(type='dissolve', duration=.2)),
        dict(kind='title', text='CHECK THE\nPOCKETS.', duration=1, font_size=72, animation='pop', at=5.8)
    ]
    plan['captions'] = [dict(start=1, end=2, text='First moment', zone='top', basis='observation'),
                         dict(start=3, end=4, text='Inventory:\napparently infinite.', zone='bottom', basis='joke')]
    validate_plan(plan, media)
    path = args.folder/'pulse-plan.json'
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Open {source} in Quick Edit, then Auto Edit > IMPORT PULSE PLAN > {path}')


if __name__ == '__main__':
    main()
