# v0.5 Motion upgrade — implementation and verification

> Historical implementation checkpoint from 9 October 2026. The user approved
> the packaged build for release on 12 October 2026. The uncommitted/version/
> approval statements below describe that earlier checkpoint; see
> [v0.5.0 release verification](V05_RELEASE_VERIFICATION.md) for final status.

9 October 2026. Branch `codex/editor-polish-v05`, HEAD `60200d8`.
This report covers the animated-zoom and 3x/4x continuation after the earlier
zoom-result toggle, including the revised timings and Full Clip option. All changes remain local and uncommitted for user testing.
No push, merge, tag, release-note update or version bump was performed.
The footer remains v0.4.0 as requested.

## User workflow

Motion has four compact rows within the existing 126-pixel tool area:
Zoom Off/On and amount; Static/Zoom In and Fast/Medium/Slow/Full Clip; Clip Speed; and
View Zoom Result / Edit Zoom Focus with a short hint. Minimum window size
remains 760 x 700. Static is the default; Zoom remains off initially.

Zoom-motion controls are disabled unless Zoom In and Zoom On are selected.
Clip Speed offers only 0.5x, 1.0x, 1.5x, 2.0x, 3.0x and 4.0x.

Focus editing retains the current format's usable unzoomed frame and cyan
focus target. Fades are temporarily omitted from this editing preview so a
fade boundary cannot hide the area being selected. Saved fade settings are
unchanged. Result mode hides/disables focus interaction.

View Zoom Result in Zoom In mode starts the existing silent preview from trim
start. It uses the same Play/Pause/Stop controls and the same single worker.
Scrubbing samples the animation at that source position. Pause freezes the
requested position, resume continues, Stop returns to trim start, and trim end
stops playback. Switching back to focus preserves every edit setting.
Static mode retains the existing fixed crop/scale output and result behavior.

## Exact animation math and timing

Let s be clip speed, L be source trim duration, F be source frame rate and t
be output elapsed time. Preview calculates t = clamp(position-trim.start,0,L)/s.
The export zoom filter uses its trim-relative input timestamp divided by s.

Nominal zoom durations are Fast = 0.6 s, Medium = 1.5 s, Slow = 3.5 s.
Full Clip uses the exact trimmed output duration L/s. The effective duration is:

    D = L/s                                      # Full Clip
    D = min(nominal_duration, max(1/F, L/s - 1/F)) # Fixed presets
    p = clamp(t/D, 0, 1)
    ease = p*p*(3 - 2*p)
    z = 1 + (selected_factor - 1)*ease

Motion starts at exactly 1x and reaches exactly the selected amount at t=D.
Full Clip never uses the fixed presets' one-frame subtraction or timing cap;
12 seconds of source trim at 3x means exactly 4 output seconds of animation.
The fixed presets hold their final zoom after the animation finishes.
Clip speed does not change the nominal output-time duration. Short clips use
a shorter animation so it can finish by the last output frame where possible.
A one-frame clip is safe but cannot visibly show an entire motion.
Encoded frames sample the curve at frame timestamps; no extra frame is added
beyond the trim boundary. At the source-file endpoint, preview decodes the last
available source frame while using the exact requested animation time, so
Full Clip reaches its precise target when the playhead reaches trim end.

For post-format dimensions W,H, the ideal viewport is W/z by H/z. The source
focus is translated by the crop origin, then the viewport is clamped:

    x = clamp(focus_x*source_width - crop_x - W/(2*z), 0, W-W/z)
    y = clamp(focus_y*source_height - crop_y - H/(2*z), 0, H-H/z)

FFmpeg zoompan quantizes this viewport to source pixels and scales to the
unchanged even output dimensions. No borders are introduced by zoom; Original
keeps the existing one-pixel padding policy for odd source edges.

Semantic render order remains trim -> format crop/padding -> privacy -> zoom
-> text -> branding -> clip speed -> fades -> H.264/AAC.
Animated export resets timestamps and normalizes to the source's reported
frame rate before zoompan, which emits one frame per input frame at that rate.
This makes zoompan timestamps predictable, including variable-rate inputs.
Speed conversion still occurs after text and branding. Export duration and
fade timing use L/s. Preview uses the same zoom expression with a fixed sampled
time; fades are evaluated at that output timestamp, then timestamps reset for
the single image. Unaffected previews retain their existing filter graph.

Reference for FFmpeg's input-time variable:
https://ffmpeg.org/pipermail/ffmpeg-cvslog/2020-June/122864.html

## Audio

Tempo stages remain within 0.5..2.0: 3x uses atempo=1.5,atempo=2;
4x uses atempo=2,atempo=2. Other presets use their corresponding single stage
(1x needs none). This changes tempo while retaining natural pitch, followed by
output-time audio fades. Existing first-track audio preservation and silent
input handling remain intact.

## Files changed for this continuation

- editor/polish.py: modes, speed presets, output-time animation math/filter,
  conservative tempo chains and geometry helpers.
- editor/polish_tools.py: compact controls, enable states, animated-result
  playback start and mode synchronization.
- editor/editor_window.py: pass trim to preview, freeze pause position, keep
  focus placement visible at fade boundaries.
- editor/preview.py: carry trim through the existing request queue and sample
  output-time zoom/fades through the shared renderer.
- editor/transforms.py: shared animated zoom and sampled fade handling.
- editor/ffmpeg_export.py: safe audio tempo chains.
- tests/test_editor_polish.py: replace the formerly-invalid 3x case with 5x.
- tests/test_editor_motion.py: 11 pure tests, including exact Full Clip duration,
  start/mid/end geometry, all requested speeds, tiny clips and EOF preview.
- tests/test_editor_motion_integration.py: 4 new real-export tests.
- tests/test_editor_motion_ui.py: 5 new Tk tests.
- V05_MOTION_VERIFICATION.md: this report.

The earlier uncommitted changes in editor/privacy_preview.py,
tests/test_editor_polish_ui.py and V05_ZOOM_VERIFICATION.md are preserved.
The recorder, branding paths and window picker are unchanged by this upgrade.

## Final verification

Full suite: **147 tests passed, zero skipped, 218.570 seconds**.

    $env:PULSE_RUN_UI_TESTS='1'
    $env:PULSE_RUN_FFMPEG_TESTS='1'
    python -m unittest discover -v

New pure checks cover every speed and tempo chain, invalid states, unchanged
Static geometry/filter, start/middle/end geometry, progress clamping, four-edge
focus, shifted crops, every format, odd dimensions, independent output-time
motion durations, one-frame safety, speed-adjusted fades and trim-relative preview.

New real exports cover every format, every clip speed, all three zoom amounts
and all four motion options, edge focus, shifted crop, audio/silence, odd source dimensions
and one-frame trims. At start/middle/end, sampled animated preview and decoded
export agree within a mean RGB error threshold of 14/255.

Full Clip preview/export agreement was checked at 0.5x, 1x, 3x and 4x,
using actual encoded frame timestamps for start/middle/last-frame comparison.
Exact duration-boundary geometry is verified separately. Pause/resume/Stop,
focus/result interaction, state preservation and the compact panel were also
checked with Full Clip selected.

The mandatory combined Full Clip export ran at BOTH 3x and 4x with trim, Vertical,
shifted crop, Pixelate, caption, Pulse branding, animated Zoom In, chosen focus,
both fades and audio. Validation checked dimensions, expected duration, audio
presence, complete decode, source SHA-256 and absence of partial/lock debris.
Preview/export comparison also passed for this full combination including fades.
A synthetic synchronized flash/tone source checked audible onset within 70 ms
of its expected time, flash/tone alignment within 90 ms, and stream duration
agreement within 120 ms. A 440 Hz tone remained within 25 Hz after acceleration.
These are targeted synthetic checks, not a claim about every recording or audio type.

New Tk checks cover mode/motion-speed enable states, 3x/4x buttons and playback
clock, result autoplay, pause/resume, Stop and trim-end stop, focus/result markers,
complete edit-state preservation including fades, scrubbing, tool switching,
worker reuse and full requested control size at the minimum window. Earlier
transport, crop, startup/file-picker, cancellation and recorder tests also passed.

Reviewed the updated source-editor screenshot at 760 x 700 with all four
motion options visible in the requested order. No tool-area increase or
preview-area reduction was needed; the strict layout test passes.

## Packaged build and remaining approval

The requested build completed successfully:

    powershell -ExecutionPolicy Bypass -File ".\build.ps1" -BundleFFmpeg

The rebuilt dist/Pulse Capture/Pulse Capture.exe launched, reached input idle
and showed a responding PULSE // CAPTURE window. Bundled FFmpeg/FFprobe and
Pulse branding were present; both bundled executables passed smoke checks.
The app is left running for real-user testing. Keep its entire folder together.

The full editor walkthrough was exercised through source Tk integration tests;
the packaged check covers startup and resources. Native manual packaged editing
could not be performed because the Computer Use helper failed to initialize:
helper_unknown_error: setup refresh had errors. Manual approval of the new
packaged build is still required before the future version bump/commit/push/
merge/tag. No manual packaged walkthrough is claimed.

Preview remains silent and sampled; it is not full-frame-rate video playback.
No animation keyframes, tracking, zoom out or other requested exclusions were added.
README/release/version changes remain deferred until the user's final approval.

Current ignored evidence: build/v05-full-clip-verification/full-suite.log,
build.log, package-launch.json and full-clip-minimum.png.
Earlier Motion evidence is preserved in build/v05-motion-verification/.
