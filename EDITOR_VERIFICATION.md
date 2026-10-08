# Quick Edit Milestone 3 — v0.4.0 verification

8 October 2026. Base: v0.3 main merge `419a2c2`.
Branch: `codex/text-blur-pixelate`. Work is deliberately uncommitted;
no push, merge, or tag was performed for this milestone.

## Implemented

One optional text overlay: Off/On, Small/Medium/Large, Top/Centre/Bottom,
light text on a dark box, up to three explicit lines and 160 characters.
Long lines shrink within the output margins; unreadably small text is rejected.

One rectangular privacy mask: Blur/Pixelate, draw, move, corner resize, arrow-key
adjustment, and Clear Mask. Text and privacy apply across the entire exported
trim. Recorder internals, saved filenames, window picker, and branding assets
are unchanged. Only the recorder's visible version label changes.

## Render order and coordinate contract

Input seek/trim → aspect crop → even-edge padding → privacy → text → branding
→ H.264/AAC MP4. Silent sources remain silent. Both preview and export use the
same filter builder. Crop mode alone shows the original source for reframing.

Privacy state uses original source pixels. Visible mask = intersection(source
mask, source crop), then subtract the crop origin for rendered coordinates.
Creating/editing a mask maps the displayed output pixels back through that
same crop origin. Original's optional one-pixel padding is accounted for.
Changing format/crop never moves the saved source rectangle. Entirely cropped-out
masks are omitted with a UI explanation. Repositioning/resizing a clipped mask
edits its visible part. Invalid/zero rectangles cannot reach FFmpeg.

Privacy processing uses 4:4:4 intermediate pixels to preserve odd coordinate
placements, then the usual 4:2:0 encode. Blur uses a fixed Gaussian blur;
pixelation downsamples the region then restores its size with nearest-neighbour
scaling. No detection or tracking is performed.

Text stays in an owned temporary UTF-8 file, with drawtext expansion disabled.
Paths are escaped for both FFmpeg parsers; subprocesses use argument lists and
no shell interpolation. System font paths are resolved at runtime; font files
are never shipped. Worker cleanup removes temporary text after child exit.

## Automated checks performed

- Normal suite: 104 tests, 88 passed and 16 opt-in tests skipped.
- Full suite: **104 passed, zero skipped**, with both opt-ins enabled; 75.031 s.
- Existing recorder, audio, settings, filename, trim, format, branding,
  cancellation, and window-picker tests remain passing.
- New pure checks: text sizes/positions and literal symbols/Unicode; disabled,
  empty, invalid and too-long text; font lookup/failure and temporary cleanup;
  mask bounds, reverse drags, invalid/zero sizes, all formats, shifted crops,
  clipped/out-of-view masks, pipeline order, separate arguments, audio/silence,
  and validation before process launch.

Commands:

```powershell
python -m unittest discover -v
$env:PULSE_RUN_UI_TESTS = '1'
$env:PULSE_RUN_FFMPEG_TESTS = '1'
python -m unittest discover -v
```

## Real FFmpeg checks performed

- Text only; blur only; pixelate only.
- Landscape + blur; vertical + text + branding; square + privacy.
- Trim + vertical + privacy + text + branding, in both Blur and Pixelate modes.
- Every combination above with audio and with silent input; durations,
  dimensions, audio presence, full decode, progress, and source SHA-256 checked.
- Pixel-level checkerboard tests for both privacy modes under Original,
  Landscape, Vertical, Square, and manually shifted crops. Detail is suppressed
  inside the mapped rectangle while a separate area remains unchanged within
  compression tolerance. Native-size preview pixels match exported pixels.
- One-pixel clipped masks and entirely cropped-out masks exported successfully.
- Top/Centre/Bottom rendered text pixel placement. Apostrophes, brackets, percent
  signs, literal `%{n}`, backslashes, Unicode, and punctuation in both text and
  temporary parent-directory names rendered successfully.
- Actual FFmpeg cancellation with all overlays; partial/lock/text cleanup;
  launch failure cleanup; asynchronous preview temporary text cleanup.
- All pre-existing v0.3 real exports, watermark corner/size pixel checks, and
  trim/audio/source-preservation checks ran in the full suite too.

## Tk checks and screenshots

Seven Tk tests passed on the current Windows machine, using the application's
DPI setup. They exercise all six tool panels, 760 × 700 layout, text visibility
and invalid-input recovery, crop/brand regression, mask drawing/moving/resizing,
shifted crops and format changes, clear, clipped-edge selection, cancelled drag
on window resize, combined UI export, and close-during-export cancellation.
No Tk callback errors were reported. Timeline height stays at least 65 pixels.

Reviewed actual rendered screenshots in `build/m3-verification/`:
`privacy.png`, `text.png`, and `text-minimum.png`. The first two show the combined
vertical crop + pixelation + caption + branding; the last confirms the minimum
window retains its tool controls, timeline labels, and export actions.
These screenshots and `full-suite.log` are local ignored QA artifacts.

## Packaging check

The existing `build.ps1` completed successfully with PyInstaller 6.20.0.
The resulting `dist/Pulse Capture/Pulse Capture.exe` launched, reached input idle,
and exposed a responding `PULSE // CAPTURE` window, then was closed by the smoke
test. All four new editor modules are present in the packaged archive, the
Pulse branding PNG is included, and zero `.ttf` files were bundled. The package
uses the existing locally installed FFmpeg/FFprobe arrangement. The full editor
interaction suite runs against source; the packaged check covers startup and
resource/module inclusion, not a second complete packaged editing workflow.
Local evidence: `build/m3-verification/build.log` and `package-launch.json`.

## Files in this milestone

Modified: `README.md`, `EDITOR_VERIFICATION.md`, `ui/app.py`,
`editor/editor_window.py`, `editor/transforms.py`, `editor/ffmpeg_export.py`,
`editor/export_job.py`, `editor/preview.py`.

Added: `editor/text_overlay.py`, `editor/privacy.py`, `editor/privacy_preview.py`,
`editor/overlay_tools.py`, `tests/test_editor_overlays.py`,
`tests/test_editor_overlays_integration.py`, `tests/test_editor_overlays_ui.py`.

## Limits and deferred items

One text overlay and one stationary rectangle per clip. No timing, layers,
keyframes, tracking, automatic privacy/face detection, multiple overlays,
subtitles, transcription, zoom, speed, fades, music, transitions, or Pulse Promo.
Preview remains silent and sampled rather than full-speed audiovisual playback.
Inspect the whole clip when information moves; a stationary blur/pixelation box
does not promise automatic or irreversible redaction of every kind of content.
Font glyph coverage is system-dependent, including emoji and CJK characters.
Long-file performance, all DPI/monitor combinations, and fresh recorder hardware
acceptance tests were not exhaustively repeated in this milestone.
