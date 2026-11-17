# Media library verification — 17 November 2026

Base: `781a187` (`feature/canvas-reactions-20261117`).
Feature branch: `feature/media-library-20261117`.

## Complete regression suite

`python -m unittest discover -s tests -v` with both
`PULSE_RUN_UI_TESTS=1` and `PULSE_RUN_FFMPEG_TESTS=1`:

**324 tests passed, no skips, in 375.144 seconds.**

After the final batch-close cancellation adjustment, the library unit and Tk
checks were rerun: **8 tests passed in 4.821 seconds**.

Test libraries and music caches were redirected to disposable writable folders.
The installed user library, profiles, recordings and active PC checkout were not
used for mutations. The active PC checkout remains at `781a187` on
`pc/canvas-reactions-20261117` with a clean working tree.

## Actual media verification

- All **163 sound effects** rendered to distinct stereo 48 kHz / 16-bit PCM.
  Every waveform was non-silent, matched its declared duration and stayed below
  clipping. Lowest RMS: 0.03073; highest peak: 0.81998 of full scale.
- All **64 bundled GIFs** decoded successfully through FFmpeg to more than two
  distinct animation frames. Frame timing, canvas bounds, durations, file hashes
  and licence records were checked. The generated contact sheet was inspected.
- An actual MP4 combines a rotated animated facepalm with original rimshot and
  dog-bark cues. Frames change over time; decoded preview/export pixels agree
  within the established compression tolerance. Audio is present at cue times.
- A two-frequency music fixture verifies that trimming selects the intended
  tone, looping repeats only that section, and non-looping selection ends with
  silence. Measured music amplitude falls during source audio and recovers after
  it. Preview seeking and final-export fades agree.
- Batch tests cover duplicate content, bundled GIF deduplication, mixed successful
  and failed files, metadata/category preservation and cancellation between files.
- Tk tests exercise lazy thumbnails, animated previews, nonblocking sound
  audition, close during audition, browser-link dispatch, music licence records,
  exact clipboard credits, saved-library reopening and export-busy guards.
- Existing minimum-size Music layout, emoji/GIF drag-resize-rotate controls,
  sound ducking, caption themes, source protection and v1/v2 plan tests pass.

## Reproducible evidence

`scripts/verify_sound_pack.py` produces `sound-pack-audit.json` with a SHA-256,
duration, RMS and peak for every rendered effect, plus a sixteen-effect audition
WAV and its cue times. `scripts/media_pack_inventory.py` produces the licence
inventory and optional visual contact sheet. `PULSE_VERIFICATION_DIR` retains the
integration test's `media-pack-demo.mp4`.

These checks establish valid, distinct media and working rendering. Perceived
sound quality and the choice of reaction remain creative judgements; the pack
uses original synthesis and vector animation rather than recorded animals,
borrowed meme clips or licensed stock recordings.

Dialogue ducking detects source-audio level, not individual speakers. Other loud
source sounds can trigger it. A standalone music audition has no dialogue input;
use the existing editor sound playback to preview the complete mix.
