"""Generate an importable v2 comedy fixture with an original transparent GIF."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.media import probe_media
from editor.pulse_plan import validate_pulse_plan
from editor.reaction_library import ReactionLibrary, ASSETS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='A new folder, never an existing recording folder')
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or 'vendor/ffmpeg.exe')
    parser.add_argument('--ffprobe', default=shutil.which('ffprobe') or 'vendor/ffprobe.exe')
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name('generate_pulse_demo.py')), str(args.folder),
                    '--ffmpeg', args.ffmpeg, '--ffprobe', args.ffprobe], check=True)
    gif = args.folder/'pulse-siren.gif'
    subprocess.run([args.ffmpeg, '-v', 'error', '-nostdin', '-n', '-loop', '1', '-i',
                    str(ASSETS/'emoji'/'emoji.siren.png'), '-filter_complex',
                    "trim=duration=1,fps=10,rotate='.4*sin(t*12)':c=none,split[a][b];"
                    '[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse=alpha_threshold=128',
                    '-t', '1', '-loop', '0', str(gif)], check=True)
    gif_id = ReactionLibrary().import_file(gif, 'gif', args.ffmpeg, args.ffprobe)
    plan = json.loads((args.folder/'pulse-plan.json').read_text(encoding='utf-8'))
    plan.update(version=2, caption_theme='Comedy Bold', freeze_duration=1.8)
    for item in plan['timeline']:
        item.pop('at', None)
        if item['kind'] == 'freeze':
            item.pop('duration')
            item['effect'] = 'punch_zoom'
    plan['captions'] = [dict(start=1,end=2,text='WATCH CLOSELY',zone='top',basis='observation'),
                        dict(start=3,end=4.8,text='THAT WAS PERSONAL',zone='top',basis='joke',
                             typography=dict(highlight='PERSONAL',font_size=88,animation='pop'))]
    plan['sfx'] = [dict(asset_id='reaction.record_scratch',at=2,volume=.65,duck_source=.35),
                   dict(asset_id='comedy.boing',at=3,volume=.75,duck_source=.35),
                   dict(asset_id='reveal.ding',at=3.2,volume=.5)]
    plan['overlays'] = [dict(kind='emoji',asset_id='emoji.skull',start=3,end=4.8,
                            position='bottom_left',scale=.2,animation='pop'),
                       dict(kind='gif',asset_id=gif_id,start=3,end=4.8,position='bottom_right',
                            scale=.25,loop=True,opacity=1)]
    media = probe_media(args.ffprobe,args.folder/'pulse-demo.mp4')
    validate_pulse_plan(plan,media)
    path = args.folder/'pulse-plan-v2.json'
    with path.open('x',encoding='utf-8') as stream:
        json.dump(plan,stream,ensure_ascii=False,indent=2)
    print(f'Import {path} with pulse-demo.mp4 open. Local GIF asset: {gif_id}')


if __name__ == '__main__':
    main()
