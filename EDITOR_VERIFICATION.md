# Quick Edit Milestone 1 — verification

8 October 2026. Base: main at watermark merge `5aa2abe`.
Local feature branch: `codex/quick-edit`. App version: 0.2.0.

## What works

- Quick Edit opens the newly saved recording in a separate Pulse window.
- Asynchronous video loading, real frame preview, scrubbing, draggable trim
  handles, Start/End entries, Use playhead, Reset, and approximate silent preview.
- H.264/AAC MP4 trim export with real progress, cancellation, validation, a
  selectable output folder, and collision-safe edited-copy names.
- Original videos remain untouched. Existing burned-in branding is preserved.
- Editor/export shutdown is coordinated with closing the recording app.

## Checks performed

- Existing recorder/watermark tests plus editor and window-picker tests.
- Real FFmpeg audio and silent clips: trim duration, decoding, preview extraction,
  and source SHA-256 preservation. Run with `PULSE_RUN_FFMPEG_TESTS=1`.
- Real watermarked GDI recording through the existing UI, then Quick Edit,
  preview/scrub, rejected invalid range, valid Start/End trim, export, and FFprobe
  validation. Source bytes remained identical.
- UI export cancellation and parent-window close during an active export.
- Visual inspection of the actual Tk editor and successful export state.

## Window picker investigation

The current machine enumerated ChatGPT, Chrome, and Visual Studio Code; the
earlier report of only shell windows was not reproduced. The old picker omitted
minimized apps. It now includes those with a restore-first label and excludes
the desktop shell. Starting a recording still requires restoring the target.
This is not a claim that every Windows app or protected surface is capturable.

## Not included yet

Aspect/social presets, crop, editable branding, text, blur/pixelation, zoom,
mute/volume, speed, fades, Pulse Promo, full-speed audio preview, and loading
older files from a file picker. Tests for those future features are deferred
until their implementations exist. The logo asset is unchanged.

The lightweight preview deliberately samples frames and has no audio playback.
Export retains audio and original dimensions/speed. Long-file performance,
mixed-DPI multiple monitors, and all Windows 10/11/device combinations are not
fully covered by these local checks.
