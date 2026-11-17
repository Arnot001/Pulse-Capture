# Pulse Capture media library

Based on `feature/canvas-reactions-20261117`, commit `781a187`.

The existing Quick Edit panels now include **163 sound effects**, **64 animated
GIF reactions**, the existing **12 emoji** and **6 Pulse music compositions**.
No runtime Python packages or new editing engine are required.

## Sound effects and reactions

Open **SOUND FX**, **EMOJIS** or **GIFS / REACTIONS**. Search matches names, IDs and
categories. Sound categories are Comedy, Reactions, Memes, Cinematic, Failures,
Animals, Transitions and Suspense. GIF categories describe their subjects:
Faces, Comedy, Skulls & Ghosts, Questions & Hearts, Explosions, Alarms, Animals
and Big Reactions.

Select an item to preview it; **STOP** stops the audition or GIF animation.
Sound synthesis and FFmpeg auditions run outside the UI thread. Only visible
list thumbnails and the selected GIF's current frame are decoded.

**IMPORT FILES** accepts multiple WAV/MP3 effects or GIFs in one operation.
The batch reports new files, duplicates and failed files independently. Duplicate
file content reuses its existing asset ID and preserves its existing metadata.
A bundled GIF imported again is recognised as the bundled asset.

Use Ctrl/Shift to select multiple assets, then **SET CATEGORY** or **FAVOURITE**.
Custom categories are stored in library preferences without rewriting bundled
media. Select a single item to insert a timed cue. Volume, timing, background
gain and fades remain in the same controls. **POSITION ON VIDEO** retains drag,
corner resize, rotation and Escape-to-cancel.

All added sound designs are original arrangements of transients, resonances,
noise textures and pitched elements. Animal effects are stylised synthetic
calls. The Memes category uses original editorial sounds, not copied meme clips.
The existing 19 sound IDs and their cached audio are unchanged.

## YouTube music and local tracks

1. In **MUSIC**, choose **BROWSE YOUTUBE AUDIO LIBRARY**. This opens the official
   Audio Library in the default browser; sign in there if required.
2. Download a track from YouTube, then use **IMPORT MP3 / WAV** in Pulse Capture.
3. Open **LIBRARY / PREVIEW / CREDITS**. Enter the track name, artist, source,
   licence type and the exact required attribution supplied with the track.
4. Choose **SAVE TRACK** to preserve an owned library copy and its licence record.
   The original downloaded file remains unchanged. Saved tracks are available
   from the dropdown in this sheet on later sessions.
5. For attribution-required tracks, **COPY YOUTUBE DESCRIPTION CREDIT** copies
   the supplied text verbatim. Pulse does not invent or infer licence terms.

New imports default to **Unspecified — verify rights**. A Creative Commons
Attribution record requires credit text. The official instructions explain
[where to find and copy the track's attribution](https://support.google.com/youtube/answer/3376882?hl=en-GB).
Pulse Capture does not search, scrape, download or rip online music.

**Track start / end** select the part of the music file to use. **APPLY MIX**
applies the trim and optional **Duck music under source dialogue** setting.
Looping repeats that selected part; with Loop off, the remaining video is padded
with silence. Enter both endpoints when looping a section with a nonzero start.
The Music panel still controls volumes, looping and fades. **PREVIEW 12s**
auditions the selected track section without requiring the optional editor audio
package. Use the existing video playback with sound to hear the complete mix.

Ducking follows the level of source audio with a short attack and smooth release;
other loud source sounds can also trigger it. It changes the music bed, not the
source dialogue or cue timing. Source-audio detection is inactive for silent
video. Preview and export share the music trim/fade/ducking filters.

## Storage and compatibility

- Shipped GIFs and thumbnails live in `assets/reactions`; no library download is
  needed. New sounds are generated on first use and cached in the existing
  reaction library. Browsing does not generate the sound pack.
- Reaction imports and favourites stay in the existing reaction library.
- Saved music copies and licence records use a new `library` subfolder of the
  existing music cache. Existing cache files are not migrated or replaced.
- Profiles, recordings, exports, existing user assets and installation settings
  are not changed by checking out this feature branch.
- v1/v2 Pulse Edit Plans keep their existing schema. New media uses ordinary
  local asset IDs and existing sound/visual cue fields. Older plans continue to
  work; plans using new IDs need this pack on the rendering PC.
- The media inventory is `assets/media_manifest.json`. Original-media terms and
  the bundled DejaVu font licence are included in `assets/licenses`.

## Development verification

Run the complete suite with `PULSE_RUN_UI_TESTS=1` and
`PULSE_RUN_FFMPEG_TESTS=1`, with FFmpeg/FFprobe on PATH. Set
`PULSE_REACTION_LIBRARY` and `PULSE_MUSIC_CACHE` to disposable writable locations
for tests. Optional `PULSE_VERIFICATION_DIR` retains an actual pack export.

`scripts/generate_reaction_pack.py` reproducibly authors the GIFs (Pillow is an
authoring-only dependency). `scripts/media_pack_inventory.py` rebuilds the licence
inventory and optionally writes a contact sheet to the directory given as its
first argument. Neither script needs to run in the installed application.

`scripts/verify_sound_pack.py <output-folder>` renders every sound into temporary
storage, checks unique PCM content, duration, silence and clipping, and saves a
16-effect audition WAV plus its timing and waveform-health report.

## Feature branch for the PC checkout

The published branch is `feature/media-library-20261117`. The active PC checkout
is left unchanged. To try this branch later, close Pulse Capture, ensure the
checkout has no uncommitted code changes, then run:

```powershell
cd C:\Users\lenno\Desktop\Pulse-Capture
git fetch origin feature/media-library-20261117
git switch -c pc/media-library-20261117 --track origin/feature/media-library-20261117
python pulse_capture.py
```

This uses the existing Python, FFmpeg and user-data locations. There is no
reinstallation, profile migration or recording conversion step.
