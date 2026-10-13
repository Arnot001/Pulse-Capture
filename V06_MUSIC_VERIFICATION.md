# Pulse Capture v0.6 Music — development verification

13 October 2026. Music development is isolated on `codex/v06-music-library`,
branched from the approved CUT + timed Privacy checkpoint `efdc20e`.

No main merge, release tag, or visible-version change is part of this work.

## Scope

Quick Edit now has a **Music** panel with:

- Music Off / On
- six original Pulse instrumental choices
- soundtrack volume
- original/source-audio volume
- Loop
- soundtrack Fade In / Fade Out
- user MP3/WAV import

Built-in tracks:

- Pulse // Night — dark tech — 96 BPM
- Pulse // Drive — energetic — 124 BPM
- Pulse // Focus — minimal — 88 BPM
- Pulse // Lift — upbeat — 118 BPM
- Pulse // Horizon — cinematic — 76 BPM
- Pulse // Circuit — clean tech — 110 BPM

The built-ins now use Pulse Music Engine v2: deterministic local synthesis from `editor/music.py` with track-specific 12-bar arrangements, A/B harmony, fills, motifs, transitions, stereo movement and lightweight mastering. They contain no third-party recordings, loops, stems, or downloaded samples.
Generated WAVs are cached under `%LOCALAPPDATA%\Pulse Capture\music` unless
`PULSE_MUSIC_CACHE` is set.

## Audio contract

CUT and clip speed continue to transform the source video/audio first.

The soundtrack then occupies **final output time**:
- removed CUT ranges do not create gaps in music
- clip speed does not change soundtrack pitch/tempo
- Loop repeats music to the output duration
- Loop Off pads silence when a track ends early
- soundtrack and original audio have independent volume
- source audio keeps existing speed/fade behavior
- soundtrack has independent fade-in/out
- silent source videos gain an AAC audio track when Music is enabled

Source + soundtrack are mixed without FFmpeg amix normalization so the user's
volume choices remain meaningful. A compensated limiter protects clipping without
intentionally shifting A/V timing.

The editor remains a silent frame preview for now. The transport note explicitly
states when music will be added on export.

## Original-source safety

Music is non-destructive. Source MP4s and imported MP3/WAV files are never
rewritten. Built-in cache WAVs are separate generated files. Export reservation,
validation and cancellation behavior remain in the existing export job.

## Automated coverage added

Pure tests cover:
- library/default state
- v2 arrangement sections and unique track palettes
- v2 cache slugs so old simple cached WAVs are not reused
- deterministic but distinct generated audio across all six built-ins
- invalid track/import/volume values
- deterministic WAV generation
- independent source/music volumes
- Loop On and Loop Off
- music fade-in/out
- branding input indexing
- CUT + clip-speed final duration
- Music Off legacy silent behavior

Real FFmpeg tests cover:
- generating/caching a real built-in v2 track and exporting it
- adding music to silent video
- mixing music with source audio
- short non-loop music padded to video duration
- combined CUT + speed + Privacy + Full Clip zoom + Text + Branding + fades
- output A/V duration agreement
- original-source hash preservation
- partial/lock cleanup

Tk tests cover:
- Music enable/disable
- all six built-in choices
- source/music volume controls
- Loop and fades
- MP3/WAV import selection
- 760x700 panel fit
- export busy/disabled states
- preserving unrelated edit state

## Verification still required on the Windows build PC

Run the complete opt-in suite:

```powershell
$env:PULSE_RUN_UI_TESTS='1'
$env:PULSE_RUN_FFMPEG_TESTS='1'
python -m unittest discover -v
```

Then build and launch:

```powershell
powershell -ExecutionPolicy Bypass -File ".\build.ps1" -BundleFFmpeg
Start-Process ".\dist\Pulse Capture\Pulse Capture.exe"
```

Record the exact passing test count and build result here after execution.

Manual acceptance should audition every built-in track. Engine v2 is the richer second-pass arrangement system; code-level correctness still does not replace listening for musical quality, narration balance, looping feel, or taste.

Also check:
- Music Off retains source audio exactly as expected
- silent source + Music produces audio
- source + Music balance at 20% / 100%
- Loop On over a clip longer than the built-in loop
- Loop Off over a clip longer than the chosen/imported track
- CUT + 3x/4x video while music continues naturally
- imported MP3 and WAV
- 760x700 Music panel and ten-tab strip

Do not merge or release until the user approves the soundtrack workflow and
auditions the built-in tracks.
