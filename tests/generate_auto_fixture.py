"""Generate a 127-second owned test film, real Windows TTS, silence and transitions.

Run from the repository: python -m tests.generate_auto_fixture --output auto-edit-output
No downloaded footage, music or remote services. Truth metadata is NOT input to Auto Edit.
"""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import wave

from capture.ffmpeg_backend import discover, process_options
from editor.auto_analysis import atomic_json, run_local
from editor.text_overlay import TextOverlay, TextResources, filter_path

SCENES = [
    ('CITY DRIVE', '263c65', '55d9ff', '.50+.18*sin(t*.32)',
     ['The blue car is crossing the city. Follow it as it moves past the buildings.',
      'Watch the car change direction. The camera should keep the whole vehicle in view.']),
    ('DESERT RACE', '8b592d', 'ffe052', '.24+.52*t/22',
     ['Now the yellow racer heads across the desert. Its movement is faster than the city car.',
      'The racer is moving toward the right edge. A centred crop could lose the action.']),
    ('HARBOUR TURN', '245c65', 'ff9770', '.76-.52*t/22',
     ['An orange boat enters the harbour from the right. Keep an eye on the turn.',
      'The boat is heading back to the left. This is a different scene with a different subject.']),
    ('SILENT FLIGHT', '553777', 'a9ffb0', '.5+.25*sin(t*.35)', []),
    ('NIGHT CHASE', '28344d', 'ff72c4', '.5+.25*sin(t*.50)',
     ['The pink vehicle moves through the night scene. This part has the quickest changes of direction.',
      'Listen for this sentence while the vehicle is visible. The speech and picture must stay together.']),
    ('FINISH LINE', '306248', 'f0e9dc', '.3+.4*t/22',
     ['The final runner approaches the finish line. This is the last scene in the test film.',
      'The movement slows as the runner finishes. Leave enough time for the ending to make sense.'])]


def generate(backend, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output/'pulse-auto-test-127s.mp4'
    if source.exists():
        raise ValueError('Fixture already exists; choose a new output folder to preserve it.')
    work = output/'fixture-parts'
    work.mkdir(exist_ok=True)
    speech = [{'file': f'speech-{i}-{j}.wav', 'text': sentence, 'start': i*21+2+j*10}
              for i, scene in enumerate(SCENES) for j, sentence in enumerate(scene[4])]
    atomic_json(work/'speech.json', speech)
    script = work/'synthesise.ps1'
    script.write_text('''param([string]$Folder)
$ErrorActionPreference = 'Stop'
$speaker = New-Object -ComObject SAPI.SpVoice
$speaker.Rate = 0
$lines = Get-Content -LiteralPath (Join-Path $Folder 'speech.json') -Raw | ConvertFrom-Json
foreach ($line in $lines) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Format.Type = 34
    $stream.Open((Join-Path $Folder $line.file), 3, $false)
    try {
        $speaker.AudioOutputStream = $stream
        [void]$speaker.Speak($line.text)
    } finally { $stream.Close() }
}
''', encoding='utf-8')
    if not all((work/line['file']).is_file() and (work/line['file']).stat().st_size > 128 for line in speech):
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                                 '-Folder', str(work)], capture_output=True, text=True, **process_options())
        if result.returncode:
            raise RuntimeError(result.stderr)
    rate, length = 44100, 127
    pcm = bytearray(rate*length*2)
    for line in speech:
        with wave.open(str(work/line['file']), 'rb') as file:
            assert file.getframerate() == rate and file.getnchannels() == 1 and file.getsampwidth() == 2
            data = file.readframes(file.getnframes())
        line['end'] = line['start']+len(data)/2/rate
        offset = round(line['start']*rate)*2
        pcm[offset:offset+len(data)] = data
    audio_path = work/'speech-and-silence.wav'
    with wave.open(str(audio_path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    cancel = threading.Event()
    parts = []
    for index, (title, background, subject, movement, _) in enumerate(SCENES):
        print(f'Generating scene {index+1}: {title}', flush=True)
        part = work/f'scene-{index}.mp4'
        with TextResources(TextOverlay(True, title)) as title_res, TextResources(TextOverlay(True, f'{index+1}')) as subject_res:
            filters = [f'drawgrid=width=160:height=120:thickness=2:color=white@0.12',
                       f'drawbox=x=0:y=480:w=iw:h=240:color=black@0.18:t=fill',
                       f'drawtext=fontfile={filter_path(title_res.font)}:textfile={filter_path(title_res.path)}:'
                       f'expansion=none:fontsize=34:fontcolor=white:x=45:y=45',
                       f'drawtext=fontfile={filter_path(subject_res.font)}:textfile={filter_path(subject_res.path)}:'
                       f"expansion=none:fontsize=88:fontcolor=black:x=w*({movement})-text_w/2:y=300:"
                       f'box=1:boxcolor=0x{subject}:boxborderw=35',
                       f"drawtext=fontfile={filter_path(title_res.font)}:text='%{{pts\\:hms}}':fontsize=22:fontcolor=white:x=40:y=h-45"]
            run_local([str(backend.ffmpeg), '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
                       f'color=c=0x{background}:s=1280x720:r=30:d=22', '-vf', ','.join(filters),
                       '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', str(part)], cancel)
        parts.append(part)
    print('Joining hard cuts, dissolves and a wipe; adding speech with silent intervals.', flush=True)
    command = [str(backend.ffmpeg), '-v', 'error', '-nostdin', '-n', '-filter_complex_threads', '1']
    for part in parts:
        command += ['-i', str(part)]
    command += ['-i', str(audio_path)]
    graph, current = [], '0:v'
    for index in range(1, 6):
        transition = ('fade', 'wipeleft', 'fade', 'slideright', 'fade')[index-1]
        graph.append(f'[{current}][{index}:v]xfade=transition={transition}:duration=1:offset={21*index}[v{index}]')
        current = f'v{index}'
    command += ['-filter_complex', ';'.join(graph), '-map', f'[{current}]', '-map', '6:a:0',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-t', '127', '-movflags', '+faststart', str(source)]
    run_local(command, cancel, 900)
    truth = {'source': str(source), 'duration': 127, 'speech': speech,
             'scenes': [{'start': i*21, 'end': i*21+22, 'title': s[0], 'subject_x': s[3],
                         'subject_color': s[2], 'subject_y': .5} for i, s in enumerate(SCENES)],
             'provenance': 'Locally generated graphics and Windows installed text-to-speech. No third-party footage or music.'}
    atomic_json(output/'fixture-truth.json', truth)
    print(source, flush=True)
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='auto-edit-output')
    args = parser.parse_args()
    generate(discover(), args.output)
