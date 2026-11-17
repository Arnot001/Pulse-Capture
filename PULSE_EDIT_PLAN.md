# Pulse Edit Plan v1

The backward-compatible [v2 extension](PULSE_EDIT_PLAN_V2.md) adds local sound
effects, colour emoji/GIF overlays, caption typography and configurable freezes.
The contract below describes v1 and remains supported unchanged.

Import an externally authored JSON recipe without an API key. Auto Edit now has
**IMPORT PULSE PLAN** and **NEW PLAN / SOURCE ID**. The latter generates a starter
recipe with the exact fingerprint and metadata of the open recording. Share that
source block with the person or tool writing the recipe; Pulse does not upload it.

1. Open the original recording in Quick Edit → Auto Edit.
2. Import the JSON. Inspect/edit it in **Edit JSON recipe**, then **VALIDATE**.
3. **Validated timeline** lists output times, shots, title cards, captions and scripts.
4. **RENDER PREVIEW** verifies the source hash, renders the sequence locally and opens Quick Edit.
5. Play/scrub the review. **TEXT → TIMED CAPTIONS** edits captions using output timestamps.
   The ordinary trim, cut, music, branding, privacy and export tools still work.
6. **EDIT PULSE PLAN** changes shots, title cards or transitions. Rendering again creates
   a new version from the recipe. Quick Edit adjustments are specific to the previous
   rendered version and are not reverse-translated into JSON.
7. **EXPORT VIDEO** creates a new MP4 beside the original recording, or in your chosen
   destination. Review manually. Nothing is automatically published.

Recipe assembly is a preparation step in the existing Auto Editor/FFmpeg pipeline.
Source segments reuse `build_export_command`, `EditOptions`, trims, zoom and speed
filters. The assembled review is a new source for the existing Quick Edit preview,
caption tools and `ExportJob`; it does not replace the recording or introduce another
playback/export engine. Title cards and sequence order remain first-class recipe
elements; the timeline inspector is not a drag-and-drop multitrack editor.

## Example

[`examples/pulse-plan-v1.json`](examples/pulse-plan-v1.json) is a complete example.
Its source block describes a generated fixture, not your recording. To generate your
own fixture and an exactly matching importable plan:

```powershell
py -3 examples/generate_pulse_demo.py "$env:TEMP\PulsePlanDemo"
```

Use a new folder name on each run. The script uses the bundled `vendor` FFmpeg tools
or tools on PATH; `--ffmpeg` and `--ffprobe` override them. It installs nothing.
Open the generated `pulse-demo.mp4`, then import the generated `pulse-plan.json`.

## Closed JSON contract

Unknown fields, unsupported named effects, duplicate keys, non-finite numbers,
control characters and malformed input are rejected. Maximum JSON size: 256 KB.
No commands, FFmpeg expressions, file paths, asset URLs or output destinations are
accepted from a recipe. Text is passed through UTF-8 files with `expansion=none`.

| Field | Contract |
| --- | --- |
| `format`, `version` | Exactly `"pulse-edit-plan"`, integer `1` |
| `title` | Non-empty plain text, at most 90 characters |
| `style` | Optional `News/Preview`, `Gaming`, or `Comedy / Roast` |
| `notes` | Optional plain text, at most 4,000 characters; informational only |
| `source` | Required `name`, lowercase `sha256`, `duration`, `width`, `height`, `fps` |
| `output` | Required `width:1080`, `height:1920`, `fps:30`, `framing`, `background:"dark"` |
| `timeline` | 1–32 elements; at least one shot/freeze; complete output ≤180 seconds |
| `captions` | Required array, up to 80 output-time cues; an empty array is valid |

The selected open recording is the only source. Metadata is checked while validating;
SHA-256 is checked before and after assembly. Reordering/repetition are intentional
and never mutate the source. Duration metadata tolerance is 50 ms; fps tolerance is
0.001. Frame references are optional cross-checks against nominal source fps, not
an optical or VFR frame-analysis feature. Source times use half-open `[start,end)`
ranges. Exact requested output durations must be multiples of 1/30 second.

### Framing

`framing` accepts `full_frame` or `crop_to_fill`. Full Frame fits the complete picture
onto a clean dark portrait canvas, preserving aspect ratio. Wide footage is centred;
top hooks and bottom punchlines occupy the reserved spaces. Explicit punch-ins zoom
the footage when requested, so those shots intentionally omit surrounding detail.

News/Preview and Comedy / Roast candidates default to Full Frame in Auto Edit.
Quick Edit also exposes **Shorts Full Frame** and **Shorts Crop to Fill** as separate
format choices. Moving-crop tracking is not needed for Full Frame. Manual Crop to
Fill retains its existing crop-keyframe controls. Source-anchored privacy and zoom
guides account for the fitted picture's position inside the portrait canvas.

### Timeline elements

Every element has `kind`. Optional common fields:

* `at`: assert its calculated output start; inconsistent positions are rejected.
* `role`: `shot`, `setup`, `reveal`, `replay`, `punchline`, or `outro`.
* `commentary`: at most 2,000 characters of script, retained in `voiceover-script.txt`.
  This is **not synthesized narration**.
* `transition`: incoming transition object with `type` and `duration`.

| Kind | Required fields | Optional fields |
| --- | --- | --- |
| `shot` | Source `start`, `end` | `start_frame`, `end_frame`, `speed`, `volume`, `zoom` |
| `freeze` | `source_time`, output `duration` | `zoom` |
| `title` | `text`, output `duration` | `font_size` (24–120 px; default 64), `animation` |

Shots may appear in any order and repeat. Speed: 0.5, 1, 1.5, 2, 3 or 4, with
pitch-preserving audio retiming. Source volume: 0–2 (default 1); 0 creates deliberate
silence. Split a shot to restrict volume or zoom to a precise interval. `zoom` is
`{"factor":1.5,"x":0.5,"y":0.5}`: factor 1.25, 1.5 or 2; source-normalized focus
coordinates 0–1. A freeze holds the selected first decoded frame and is silent.

Title animations: `none`, `fade` (default), `slide`, `typewriter`, `pop`. Titles use
the dark canvas, up to three lines / 160 characters; font size must fit the safe area.
The generated starter uses a one-second opener. Keep openings around 0.5–1.5 seconds.
Closing cards use the same title element, or a freeze with an output-timed caption.

Transitions: `cut` with duration 0, `dissolve`, `fade_black`. Non-cut durations must
be positive, ≤1 second and ≤half of each adjacent element. They overlap the elements,
reducing total duration by that amount. The first element cannot have a non-cut
transition. Example: two 2-second shots with a 0.2-second incoming dissolve run
from 0–2 and 1.8–3.8. Audio crossfades over the same output interval. Fade-through-black
has its black midpoint halfway through the requested interval.

### Captions and claims

Each cue requires `start`, `end`, `text`, `zone` (`top` or `bottom`) and `basis`.
Times refer to the assembled output, including cards and transition overlaps.
Text is up to three lines / 160 characters and must fit the canvas. Both zones may
be active together; authors should avoid overlapping text in the same zone.

* `observation`: describes what is visible.
* `joke`: comedic exaggeration, not a verified bug claim.
* `verified`: requires an `evidence` note. Pulse preserves the author's assertion;
  it does not independently fact-check it.
* `unverified`: retained in the recipe/inspector but withheld from rendered captions.

`evidence` is optional plain text up to 500 characters, required for `verified`.
Plain commentary/scripts do not automatically become on-screen text or audio.

## First-version limits

Unsupported recipe instructions are rejected, never silently approximated:

* Multiple source files, moving crop instructions in imported recipes, custom
  output sizes/codecs/frame rates, blurred picture extensions, image-backed cards.
* Quick-zoom/glitch/whip-pan/motion-blur transitions, circles/arrows, animated
  callout shapes, optical flow, scene/object morphing and automatic loop matching.
* Timeline-bound imported narration, sound-effect cues, music stings and automatic
  commentary ducking. Use the existing Music tool for an ordinary local soundtrack;
  narration generation and the dedicated audio-cue timeline are not implemented.

Text callouts use timed captions. Punch-in zoom is supported per shot/freeze, not as
a transition. Typewriter text recentres as characters are revealed. Assembly performs
local intermediate encodes; long recipes with many transitions can take time and
consume cache disk space. Review media and recipes are retained in the application's
`auto-edit/pulse-plans` cache. Cancelled/failed assembly cleans only its newly allocated
temporary directory. Saved plans use exclusive creation; exports use the existing
reservation/validation/publish mechanism and never overwrite a recording or export.

## Verification

See [`PULSE_PLAN_VERIFICATION.md`](PULSE_PLAN_VERIFICATION.md) for the tested build,
actual results, real Windows status, changed-file rationale and installation commands.
