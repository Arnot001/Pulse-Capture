# Privacy Tracks — v0.6 development verification

13 October 2026. Continued from `32a75d2` on `codex/cut-sections-v06`.
The approved CUT implementation is preserved. This is development work only:
no main merge, release tag, or visible-version change.

## Model and render contract

`Privacy` holds an immutable tuple of `PrivacyMask(mode, rect, start, end)`.
Rectangles and times use the original source. Each mask validates its mode,
rectangle, finite times, source bounds and minimum one-frame interval.
Intervals are Start-inclusive and End-exclusive. Overlaps are allowed; list
insertion order is stable and defines sequential processing, with unique filter
labels for each mask. Nothing is silently sorted, merged or deleted.

For each kept source segment, intersect the mask interval and translate the
surviving piece by the duration of earlier kept segments. The helper can divide
by speed for final-output consumers. Privacy filters themselves run BEFORE
speed, so their time gates use joined kept seconds without that division.
Trim -> existing CUT trim/concat -> crop/pad -> sequential privacy -> zoom ->
text -> branding -> speed/fades remains the export pipeline.

Cut 10–15 plus privacy 20–25 becomes joined 15–20. Privacy 8–18 becomes two
adjacent surviving pieces 8–10 and 10–13. No removed-time gap is synthesized.
At 3x, joined 15–20 appears at output 5–6.667. Excluded masks stay saved in the
editor; fully cropped or removed masks do not render. Source files are untouched.

Preview resolves active effects against the source frame requested, including
scrubbing outside trim or inside a removed section. Playback still uses CUT's
existing skip mapping. Zoom/fade clocks continue using kept output duration.

## User workflow

Privacy has Blur/Pixelate, source Start/End, Use Playhead buttons, a scrollable
mask list, Add Privacy Mask, Update, Remove, Clear All and New. Draw first or set
times first. Drawing previews a draft immediately; Add stores a new row, Update
replaces the selected row. New clears the draft for a new rectangle. Export
blocks unapplied drafts with an explicit Add/Update/New explanation.

Selecting a row loads that mask without altering other rows. Millisecond display
formatting preserves unchanged full-precision timestamps. The selected cyan
EDIT GUIDE remains editable outside its active interval; it is never exported.
Other active masks have subtle outlines. The Privacy editing view temporarily
omits zoom/fades; saved settings are preserved and other tools show saved output.
Thin cyan source-time strips sit below the timeline; CUT remains red and unchanged.

## Verification

Final full-suite and package results are recorded after completion below.
Focused source UI checks passed at 760x700, including requested control sizes,
scrolling, busy states, selection preservation and cut-skipping playback.
The actual minimum-size editor was visually inspected using Computer Use;
all Privacy controls, the three-row list, timeline and export actions fit.

Real checkerboard exports verify multiple Blur, multiple Pixelate, mixed and
spatial/time overlaps, trim/cuts, all six speeds, audio/silent inputs, active and
inactive pixels, source hashes and cleanup. Combined exports include shifted
Vertical crop, masks, Full Clip Zoom In, text, branding, 1x/3x/4x and both fades.
Synthetic flash/tone checks verify A/V onset alignment after cuts and speed.

One new stress comparison initially failed because the existing CFR speed
conversion sampled the preceding output frame. Diagnosis matched the same
checkerboard geometry within one output frame. The combined comparison keeps
the original pixel tolerance and explicitly bounds frame sampling to that one
frame; ordinary privacy timing checks independently verify effect presence.
No older tests were weakened or removed. Single-mask fixtures were migrated to
one full-source-duration mask and explicit Add/Update actions.

## Limits and manual acceptance

Preview is silent and sampled. Timing is limited by encoded frame sampling.
Masks are stationary within their individual intervals, with no tracking or
keyframed movement. Mask state remains session-only, as with other editor edits.
Very large mask counts and long-file performance are not exhaustively tested.
Please try the packaged Privacy workflow on a real recording before release,
particularly overlapping masks near cut boundaries and your usual display DPI.

Local logs remain ignored under `build/v06-privacy-verification/`.
