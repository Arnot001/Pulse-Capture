# Pulse Capture v0.5.0 release verification

12 October 2026. Release prepared from the existing `codex/editor-polish-v05`
working tree, including all previously uncommitted Motion and focus/result work.
The user approved the current packaged build for release. No feature work was
added during finalization; the Capture footer and README now identify v0.5.0.
The project has no separate canonical version constant.

## Included features

- Trim, Play / Pause / Stop, and existing-MP4 Quick Edit after startup.
- Original, Landscape, Vertical and Square formats with visual crop repositioning.
- Optional Pulse branding, text and a stationary Blur / Pixelate privacy mask.
- Static zoom and eased Zoom In at 1.25x, 1.5x or 2x, with a draggable focus
  target and View Zoom Result / Edit Zoom Focus workflow.
- Fast 0.6s, Medium 1.5s, Slow 3.5s and Full Clip zoom in output time.
- Clip speed 0.5x, 1x, 1.5x, 2x, 3x and 4x; chained audio tempo at 3x/4x.
- Fade In / Fade Out and the editable Pulse Promo preset.
- Background export progress/cancellation, source preservation and safe filenames.

## Release checks

- Full suite: **147 passed, zero failures, zero skips**, in **179.993 seconds**.
  Both opt-ins were enabled after the footer and README changes:

  ```powershell
  $env:PULSE_RUN_UI_TESTS='1'
  $env:PULSE_RUN_FFMPEG_TESTS='1'
  python -m unittest discover -v
  ```

- Bundled release build succeeded:

  ```powershell
  powershell -ExecutionPolicy Bypass -File ".\build.ps1" -BundleFFmpeg
  ```

  The build script also ran its normal default suite: 111 passed and 36
  explicitly opt-in tests skipped. Those same 36 tests passed in the separate
  full run above; there are no unexplained skips.
- `dist/Pulse Capture/Pulse Capture.exe` launched, reached input idle and
  exposed a responding `PULSE // CAPTURE` window. It remains open for the user.
- Inspected the packaged `ui.app` code object: footer is
  `PULSE UTILITIES / v0.5.0`. Packaged README matches the source README.
- Bundled FFmpeg and FFprobe 9.0.2 passed smoke checks; Pulse branding is present.
- Reviewed all pending source/test/doc changes and the retained branch history.
  No build/dist files are tracked; no temporary exports or test debris are
  included. `git diff --check` passed.

Ignored local evidence: `build/v05-release-verification/full-suite.log`,
`build.log` and `package-launch.json`. The final report update only records these
results; it does not change the tested application code or packaged README.

## Scope and retained evidence

The detailed implementation reports remain in `V05_MOTION_VERIFICATION.md`
and `V05_ZOOM_VERIFICATION.md`; their original counts and approval notes are
historical. `EDITOR_VERIFICATION.md` and `VERIFICATION.md` retain earlier
milestone and hardware results.

Preview remains silent and sampled. Full editor interactions are checked by
source Tk tests; packaged verification checks startup and bundled resources.
The earlier Computer Use initialization failure prevented an automated manual
packaged walkthrough; user release approval supersedes the approval gate.
Fresh hardware, all DPI/monitor combinations and long recordings are not claimed
as newly verified by this release run.

Generated packages, logs, screenshots, caches and test media remain ignored.
