# Roast Studio — JSON-powered comedy edits

## Why this is a separate module

**Quick Edit → ROAST STUDIO · JSON** is a dedicated entry point for receiving
an externally prepared GTA/gameplay roast edit. It reuses the existing
Pulse Edit Plan v2 and FFmpeg review/export engine. It is **not** a new renderer,
a substitute for Auto Edit, or a tool that silently edits videos in place.

Previous Pulse Plan imports rejected plans for a different **filename**, **duration**
or **SHA-256**. That protection remains intact for ordinary plans. Roast Studio
instead creates a **new source-bound copy in memory** after checking the exact
video opened in Quick Edit and explicitly asking permission if content or metadata
differs. The original JSON, video, clips, profiles and reaction libraries remain
untouched.

## User flow

1. Open the actual MP4 in Quick Edit.
2. Click **ROAST STUDIO · JSON**.
3. Click **CHOOSE JSON EDIT** and pick a `pulse-edit-plan` version **2** JSON.
4. Leave **SOURCE OFFSET** at `0` if the joke's scene is at the same time in
   both files. For a trimmed copy, enter the change in source time in seconds:
   if a scene at **185 seconds** in the recipe occurs at **5 seconds** in the
   opened video, use **-180**.
5. Click **BUILD & REVIEW ROAST**. The app hashes the actual opened recording.
   If its bytes or metadata don't match the reference, it **requires** an
   explicit warning/confirmation. This is NOT automatic scene recognition.
6. A validated, source-bound plan opens in the existing plan editor and starts
   a new review render. Inspect the complete result and manually **EXPORT VIDEO**.

### Content safeguards

- The JSON cannot name arbitrary input files, shell commands, external audio
  downloads or output paths. Input is always the MP4 selected in Quick Edit.
- An optional manual source offset shifts source-side `shot.start`,
  `shot.end` and `freeze.source_time` only; **caption, SFX and emoji/GIF
  cues remain aligned to the assembled output timeline**.
- All captions are locked to **comedy_bands**. Pulse's existing typography
  validation enforces safe top/bottom band fit and mobile-readable text.
  Existing canvas emoji/GIF placements move into the bottom band as well.
- Impossible source-time requests fail with a helpful error; values are never
  stretched, normalized or guessed. Wrong footage can still contain unrelated
  visual moments even when times fit. Always check the preview.
- Missing reaction assets fail validation. No copyrighted meme voice is
  synthesized, downloaded or falsely substituted with a different effect.
  Existing locally imported and permission-checked IDs continue working.
- Ordinary strict **IMPORT PULSE PLAN** remains unchanged.
- Everything uses existing FFmpeg assembly, audio sync, edit station and
  manual export. Nothing publishes automatically.

## Testing status

Focused Windows Actions job **Roast Studio focused checks** ran compileall plus
`tests.test_roast_recipe`, `tests.test_pulse_plan` and
`tests.test_comedy_bands` successfully on commit `0f1fd96`.

**Real Windows Tk user-flow testing and the live GTA clip render are not yet
verified**. Keep the candidate separate from stable until the PC tests and
manual video review pass.

## PC validation

The candidate must pass the real Windows Tk import-and-render UI test
(`tests.test_roast_studio_ui`) before it is installed as a stable release.

All PowerShell installation, testing and launching commands are provided
**in chat only**; this repository does not distribute PC setup commands.
