# v0.5 Motion zoom preview verification

> Historical implementation checkpoint from 9 October 2026. The user approved
> the packaged build for release on 12 October 2026. The uncommitted/version/
> approval statements below describe that earlier checkpoint; see
> [v0.5.0 release verification](V05_RELEASE_VERIFICATION.md) for final status.

9 October 2026. Branch: `codex/editor-polish-v05`; base commit `60200d8`.
Changes are uncommitted for user approval. No push, merge, tag, or version-label
change was performed; the footer remains v0.4.0.

## Behavior

Previously, Motion always removed zoom from preview requests to allow focus
placement. Viewing the zoom required switching to another tool.

Motion now offers **VIEW ZOOM RESULT**, which changes to **EDIT ZOOM FOCUS**.
Both views stay on Motion. The toggle is preview-only and does not modify
EditOptions, trim, focus, factor, speed, format/crop, text, privacy, branding,
fades, or export behavior. Zoom Off disables the button and resets to focus
mode. Switching tools preserves the selected preview mode. Other tools keep
their existing preview behavior.

Focus mode shows the existing unzoomed framing with the cyan target. Result
mode includes the actual zoom transform and disables focus interaction. When
returning to focus mode, the target cannot be used on a stale zoomed frame.
The existing debounced request path and single Preview worker are reused.
Turning the preview toggle while playing pauses the preview.

Motion row spacing is slightly tighter to fit the complete new button in the
existing panel. The preview area and minimum window size are unchanged.

## Files changed

- `editor/polish_tools.py`: mode state, button, hints, disabled states and focus guard.
- `editor/editor_window.py`: conditional preview zoom omission, button refresh
  after loading/export and clearing the target on preview errors.
- `editor/privacy_preview.py`: track displayed zoom state to block stale-frame interaction.
- `tests/test_editor_polish_ui.py`: four new tests and stronger layout assertions.
- `V05_ZOOM_VERIFICATION.md`: this report.

Transform and export implementation files are unchanged.

## Verification performed

Complete final suite: **127 passed, zero skipped, 131.654 seconds**.

```powershell
$env:PULSE_RUN_UI_TESTS='1'
$env:PULSE_RUN_FFMPEG_TESTS='1'
python -m unittest discover -v
```

The four new tests cover:

1. Visible control, initial/Off/On state, harmless Off callbacks, reset on Off,
   and export-busy disable/re-enable behavior.
2. Actual focus clicking/dragging; result/focus transitions; preservation of
   all edit state and trim; disabled result-mode gestures; stale-frame guard;
   exact preview request state; and a combined vertical crop + privacy + text
   + branding + zoom + speed export, with rendered-preview/export pixel comparison.
3. All three zoom factors; switching Motion/Format/Crop; rapid repeated toggles;
   the same worker throughout; and no overlapping preview FFmpeg children.
4. Minimum-size result layout and Play/Pause/Stop behavior across mode changes.

The all-eight-panels test also checks requested versus actual button/hint size,
so a widget clipped by Tk packing cannot pass solely by staying within its
parent's bounds. This caught and prevents recurrence of the initial clipped
button discovered during screenshot review.

The full suite also includes the three existing startup/file-picker tests,
all existing recorder/window-picker tests, real audio/silent exports, zoom
preview/export comparisons, speed/fades, source preservation and cancellation.

Reviewed final source-editor screenshots at 760 x 700 and 980 x 850:
`build/v05-zoom-verification/motion-focus-minimum.png`,
`motion-result-minimum.png`, and `motion-result.png`.
The new button is fully visible (26 pixels actual and requested height), and
the timeline and export controls remain accessible.

## Package

The requested command completed successfully:

```powershell
powershell -ExecutionPolicy Bypass -File ".\build.ps1" -BundleFFmpeg
```

`dist/Pulse Capture/Pulse Capture.exe` launched and reached input idle with a
responding `PULSE // CAPTURE` window. Bundled FFmpeg, FFprobe and the branding
asset were found. The application was left running for user review.
Keep the complete `dist/Pulse Capture` folder together.

Evidence is in the ignored `build/v05-zoom-verification/` folder:
`full-suite-final.log`, `build-final.log`, `package-launch.json` and screenshots.
The build's own default suite intentionally skips opt-in tests; the separate
full suite above enabled both opt-ins and had no skips.

## Remaining verification

The source Tk interaction tests and rendered screenshots were verified; the
packaged app received a startup/resource smoke check. A manual packaged-editor
walkthrough remains for real-user approval: the Computer Use helper failed to
initialize with `helper_unknown_error: setup refresh had errors`.
No manual packaged interaction is claimed. No failures remain in the checks
that ran. No animation, tracking, keyframes or extra editing features were added.
