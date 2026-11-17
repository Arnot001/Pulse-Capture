# Pulse Edit Plan v2 — checkpoint

v2 extends the existing assembly, Quick Edit preview and export pipeline. All valid
v1 plans retain their original interpretation. Recording/WASAPI code is unchanged.
See [the v1 contract](PULSE_EDIT_PLAN.md) for source identity, timeline, framing,
caption evidence and transition rules, which still apply.

## Use

Open Quick Edit. **SOUND FX**, **EMOJIS**, **GIFS / REACTIONS** and **EFFECTS** are
beside the source name. Sound/visual dialogs provide library search, categories,
favourites/recent items, previews, insertion and timed cue update/replacement/removal.
Yellow timeline markers indicate cue starts. Cue times are output seconds after
trim, cuts and speed. Editing those operations does not automatically retime cues;
adjust cues or validation will reject cues outside the new duration.

**TEXT → TIMED CAPTIONS** provides Comedy Bold, Cinematic, Meme / Reaction and Clean
News themes, with size, outline, shadow, colour, highlighting, alignment and animation.
Existing v1 captions retain their original style until explicitly changed.

The Effects picker edits the Pulse recipe. Apply/remove an effect or undo, then
**RENDER PREVIEW**. The picker is not a separate timeline or playback engine.
Re-rendering a recipe still creates a new Quick Edit candidate; manual Quick Edit
changes are not automatically written back into the recipe.

## Closed v2 fields

Set `version` to integer `2`. Additional top-level fields are optional:

| Field | Default / contract |
| --- | --- |
| `caption_theme` | `Comedy Bold`; also `Cinematic`, `Meme / Reaction`, `Clean News` |
| `freeze_duration` | 1.8 seconds, positive multiples of 1/30 second; explicit freeze `duration` overrides it |
| `sfx` | Up to 64 output-time sound cues |
| `overlays` | Up to 24 visual cues, at most six simultaneously |

In v2 only, a freeze may omit `duration`. A shot/freeze may have `effect`:
`punch_zoom`, `shake`, `scratch`, or `glitch`. The latter three interrupt the first
0.2–0.35 seconds. Punch zoom uses a centred 1.5× zoom over five output frames.
Existing `zoom` selects a source focus and factor; `dissolve`/`fade_black` retain
their original transition rules. Replay is an explicit repeated shot.

### Sound cues

Required: `asset_id`, `at`. Optional: `volume` (0–2, default .75), `duck_source`
(0–1, default 1), `duration` (.01–20 seconds), `fade_in` (0–1, default .005),
`fade_out` (0–1, default .03). Duck gain applies to the combined source/music bus:
1 leaves it unchanged, .35 retains 35%, 0 mutes. Overlapping ducks choose the
strongest reduction. Cues are mixed after source retiming, using sample delays,
30 ms duck ramps and a latency-compensated limiter. Tails end at output end.

`silence.pause` deliberately mutes the background bus for `duration` (default 1.8)
without extending video. Other SFX may still play during it. Silence inside a
freeze is already provided by assembly.

Built-in IDs:

```
comedy.boing comedy.pop comedy.squeak comedy.slide_whistle
reaction.record_scratch reaction.awkward_sting reaction.buzzer
cinematic.bass_impact cinematic.boom cinematic.riser
transition.whoosh transition.reverse_whoosh transition.glitch
reveal.ding reveal.cash reveal.sparkle reveal.discovery
failure.trombone failure.descending
```

These are original synthesized PCM sounds, cached on first use. Imported WAV/MP3
assets are validated and normalized to local stereo 48 kHz WAVs. No downloads,
accounts, API keys or third-party samples are used.

### Visual cues

Required: `kind` (`emoji` or `gif`), `asset_id`, `start`, `end`.
Optional: `position` (`top_left`, `top_right`, `bottom_left`, `bottom_right`, `centre`;
default `bottom_right`), `scale` (.05–.6 of the shorter output edge, default .2),
`loop` (boolean, default true), `opacity` (0–1), `rotation` (-180–180 degrees),
`animation` (`none`, `fade`, `pop`, `bounce`, `shake`, `spin`). Optional normalized
`x` and `y` must be supplied together; they position the rotated bounding box in
the available canvas. Defaults use mobile safe zones. Bounds are clamped to frame.

Built-in colour artwork IDs: `emoji.skull`, `emoji.laugh`, `emoji.cry`,
`emoji.shock`, `emoji.heart`, `emoji.star`, `emoji.dog`, `emoji.cat`, `emoji.bulb`,
`emoji.fire`, `emoji.alert`, `emoji.siren`. These are original Pulse PNG artworks,
not Windows font glyphs. Non-looping GIFs disappear after one cycle or at `end`,
whichever is earlier. Animated appearances also fade out before their end.

GIF imports: at most 20 MB, 1024 px per dimension, 300 frames, 15 seconds and
64 million total canvas pixels. GIF blocks/dimensions are inspected before decode;
FFprobe/FFmpeg validation has time and allocation bounds. Audio imports: at most
20 MB / 20 seconds. Imported IDs are `import.<content hash>`; importing identical
bytes reuses the asset. The library never deletes the user's source file.

### Caption typography

Each v2 caption accepts optional `typography`: `theme`, `font_size` (integer
40–120; comedy default 88), `outline`/`shadow` (integer 0–10), `colour` and
`highlight_colour` (`#RRGGBB`), `highlight` (a phrase present in the text),
`alignment` (`left`, `centre`, `right`), `animation` (`none`, `fade`, `pop`, `shake`).
Theme defaults are applied first, then explicit fields. Text wraps within the safe
area before reducing size; captions too long to remain readable are rejected.
Styled captions use bundled DejaVu Sans Bold and FFmpeg's ASS/libass filter.
Preview and export use the same renderer. ASS markup is not accepted from plans;
braces/backslashes in plain text are displayed as their full-width equivalents.

## Reproducible example

`examples/pulse-plan-v2.json` demonstrates captions, a long freeze, SFX, emoji and
a locally imported GIF. Its fingerprint and GIF ID describe a generated fixture,
not an arbitrary recording. Generate matching assets and a fresh plan:

```powershell
python -X utf8 examples/generate_comedy_demo.py "$env:TEMP\PulseComedyDemo-20261117"
```

Use a new folder name. Open `pulse-demo.mp4`, then import `pulse-plan-v2.json`.
The generator registers its original animated siren GIF in the local library.

Library assets/preferences live in `%LOCALAPPDATA%\Pulse Capture\reactions`.
`PULSE_REACTION_LIBRARY` overrides this location for isolated tests. SAVE/LOAD CUES
stores source identity plus trim/cut/speed settings to prevent applying output
times to a different selection. A plan contains safe IDs only: transfer/import the
same user-owned GIF/audio on another computer before using those IDs there.

## Current limits

This is a checkpoint, not a fully signed-off release. See COMEDY_V2_CHECKPOINT.md.
Animated WebP, optical flow and morphing are not supported. Dynamic punch zoom is
centred; arbitrary animated focus paths are not part of v2. Freeze/replay insertion
does not shift existing output cues. Preview remains the editor's sampled-frame
preview, not full-frame-rate playback. GIF imports and first SFX generation may
take a moment. Library assets/favourites persist; standalone cue projects must be
saved explicitly. No publishing or upload is performed.
