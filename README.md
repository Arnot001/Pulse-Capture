# PULSE // CAPTURE v0.4.0

A small Windows screen recorder with a dark Pulse interface. Choose a source,
record, trim, reframe, add text or a privacy box in Quick Edit, and export a local MP4. Optional Pulse watermark; no account or cloud.

## Run

Requires Windows 10/11 and Python 3.11+ with Tcl/Tk. There are no third-party
Python runtime dependencies. Install FFmpeg and FFprobe from a Windows build
with `gdigrab`, `dshow`, `libx264`, AAC, `drawtext`, and `gblur` support. Both binaries must be on PATH
or in this project's `vendor` folder. FFmpeg 9.0.2 was verified on the build PC.

```powershell
python -m pip install -r requirements.txt
python pulse_capture.py
```

For explicit binary locations, set `PULSE_FFMPEG` and optionally `PULSE_FFPROBE`
to absolute executable paths. FFprobe is otherwise found beside FFmpeg or on PATH.
Missing or incompatible binaries produce a visible error and disable recording.

## Capture

1. Choose **Full screen**, **Window**, or **Area**. Full screen records the entire
   virtual desktop. Window lists visible windows (including minimized apps labelled “restore first”) and records the
   selected handle. Area opens a desktop overlay: drag a rectangle, or press Esc
   to cancel. Reverse drags and monitors with negative coordinates are supported.
2. Select microphone/input and system-audio devices when available. Uncheck an
   input for silent capture. **Refresh devices** re-enumerates connected hardware.
3. Choose Standard (H.264 CRF 23) or High (CRF 18), and 30 or 60 FPS.
4. Optionally enable the **Pulse watermark** and choose one of four corners. It is
   off by default and is burned directly into the saved MP4 when enabled.
5. Press **Start recording**. “Starting” means FFmpeg is opening devices;
   “Recording” appears only after FFmpeg reports encoded frames.
6. Press **Stop recording**. Pulse waits for FFmpeg to finalize the MP4, checks
   video frames, duration, and requested audio, then shows **Saved**.
7. After saving, choose **Quick Edit** to trim the recording, or **Open folder** to view it in Explorer.

Recordings default to `%USERPROFILE%\Videos\Pulse Capture`.
Preferences are stored at `%LOCALAPPDATA%\Pulse Capture\settings.json`.
An advanced `output_folder` preference can set a different directory.
The optional global **Ctrl+Shift+R** shortcut works while Pulse is in the
background. A conflict with another app is shown explicitly; the shortcut is
off by default. Closing Pulse during capture requests a clean stop first.

## Quick Edit — Milestone 3

After a successful recording, click **Quick Edit**. A separate Pulse window opens
the new video; the recording engine is unchanged.

1. Click the timeline to scrub through the recording. The white line is the
   playhead; cyan handles mark the section to keep.
2. Drag the cyan handles, enter **Start** and **End**, or choose **Use playhead**.
   Times accept seconds (`12.5`), minutes (`1:23.500`), or hours (`1:02:03`).
   **Reset** restores the full clip. Invalid ranges display a clear explanation.
3. **Preview trim** plays an approximate, low-frame-rate, silent visual preview
   of the selection. This is a lightweight frame preview, not full audiovisual
   playback. The original audio remains in the export when the source has audio.
4. Choose **Format**: **Original**, **16:9 Landscape**, **9:16 Vertical**, or
   **1:1 Square**. The preview shows the result without stretching or upscaling.
5. Choose **Crop** to see the full source with a cyan crop frame. Drag inside
   the frame to reposition it; arrow keys fine-tune after clicking it.
   **Centre crop** recentres it. **View result** shows the finished composition.
   Selecting a different format starts a centred crop; **Original** restores the
   full frame. Changing the trim does not change the crop.
6. Optionally choose **Brand**, switch **On**, and pick a corner and
   **Small / Medium / Large**. The rendered preview shows the new Pulse logo.
   Branding starts **Off** in every editor session. It adds a new overlay;
   a logo already burned into a recording cannot be removed or repositioned.
7. Choose **Text**, enter a caption, and switch **On**. Pick **Small / Medium /
   Large** and **Top / Centre / Bottom**. Text is light with a subtle dark box.
   Use Enter for up to three lines; the limit is 160 characters. Long lines
   shrink to fit. If the result would be too small, shorten the text or add a
   line break. Switch **Off** to remove it from the result without losing it.
8. Choose **Privacy**, select **Blur** or **Pixelate**, then drag a box over the
   rendered preview. Drag inside to move it, or drag a corner to resize it.
   Arrow keys fine-tune the selected box. **Clear mask** removes it; drawing
   outside the existing box replaces it. The effect updates after releasing
   the mouse. One fixed box applies throughout the clip: check every part before
   sharing, especially if private information moves.
9. Click **Export video**. Rendering runs in the background with real progress
   and a **Cancel export** action. The MP4 is validated before “Exported” appears.
10. **Open folder** opens the exported file's location. **Change folder** chooses
   another destination for this editor session.

Exports use `original-name_trimmed.mp4`, then `_001`, `_002`, and so on. The
original and existing exports are never overwritten. By default the new copy
is saved beside the source. Cancelling removes this export's temporary file;
closing the editor or application cancels an active export before closing.

Original keeps the source dimensions (padding an odd edge by one pixel where
H.264 requires it). The other formats crop to the largest exact-ratio rectangle
with even dimensions: there is no stretching or upscaling. This can remove a few
extra edge pixels to keep the ratio exact. Crops move in two-pixel steps.
All formats preserve original speed and the first audio track when present.
Exports re-encode to H.264/AAC for cuts between keyframes; cut boundaries are
limited by the source frame spacing. Processing order is trim, crop, even-edge
padding, privacy blur/pixelation, text, then optional Pulse branding. Preview and export share the same filters.

Brand sizes are proportional to the shorter output edge (12%, 18%, 25%) with a
small inset and subtle opacity. The recorder and editor share the existing
bundled Pulse asset path, including in PyInstaller builds. There is no reliable
recording metadata for burned-in branding, so Quick Edit never enables a second
logo automatically. Existing source branding stays in the source pixels and may
be partly or fully cropped out by an aspect change.

Only the selected tool panel is shown. Preview remains a lightweight, silent,
low-frame-rate preview; Crop displays the source and framing guide, while Trim,
Format, Brand, Text, and Privacy show the rendered result. Privacy also shows a
selection outline and resize handles; those guides are not exported. All six
panels preserve the 760 × 700 minimum window layout and full timeline height.

Privacy rectangles are stored in original source pixels. After a format change
or a moved crop, the renderer intersects that rectangle with the visible crop
and subtracts the crop origin. The same mapping positions the preview guide.
The box therefore remains over the same original content. If entirely outside
the current crop it is not rendered; the Privacy panel explains this. Restore
Original to see it again, or draw a new box in the current crop to replace it.
Moving/resizing a partly clipped box edits its visible portion.

Text and privacy both apply throughout the exported trim. Text uses a temporary
UTF-8 file with literal expansion disabled, not interpolated shell/filter text.
Arguments remain separate subprocess arguments. Temporary text is removed after
preview/export, errors, and cancellation. Standard Windows Segoe UI is resolved
from the system Fonts folder, with Arial/Tahoma fallbacks; no fonts are copied
or bundled. Unicode input is accepted; available glyphs depend on the selected
system font (some emoji/CJK glyphs may be unavailable). A missing font produces
an actionable error; Text Off keeps the rest of the editor usable.

Deferred: timed text/masks, multiple overlays, moving/tracked masks, automatic
privacy detection, face detection, subtitles, transcription, effects, zoom,
speed, fades, mute/volume, and Pulse Promo. These controls are not exposed.

## Audio availability

FFmpeg enumerates DirectShow audio inputs. Regular inputs appear under
**Mic / Input**; recognized loopback names such as Stereo Mix, What U Hear,
or virtual-audio-capturer appear under **System audio**. Device aliases retain
distinct identities for identically named microphones.

This version does **not** implement a WASAPI loopback bridge. If Windows exposes
no recognizable DirectShow loopback source, System audio is explicitly disabled.
Screen capture and microphone recording remain usable. Enable a suitable source
in Windows if your audio driver supports it, then refresh devices. Virtual cable
inputs with unknown routing remain regular inputs; Pulse does not claim they
contain system sound. Localized loopback names may also appear as regular inputs.

Enumeration means a device was reported, not that it is currently usable or
audible. Device-open failures, permission denial, disconnected hardware, and
FFmpeg errors are displayed. Both audio sources are mixed to one stereo AAC
track when selected. Check Windows desktop-app microphone access if opening a
microphone fails. Pulse does not fabricate device availability or audio content.

## Recording behavior and limits

- The optional watermark uses the bundled Pulse branding asset at a subtle opacity
  and small fixed size, with a 24 px edge inset. The setting and corner are remembered.
- The cursor is included. The recorder itself is visible in full-screen capture;
  minimize it and use the optional shortcut when needed.
- Keep a target window restored and visible. GDI capture is not guaranteed for
  minimized, protected, hardware-overlay, or exclusive full-screen content.
  A window may produce stale/black images for these surfaces. Validation checks
  media structure, not whether every captured pixel matches the intended app.
- 60 FPS is the requested output rate; actual smoothness depends on CPU load,
  desktop size, and GDI performance. Odd dimensions are padded by one pixel
  where needed for H.264 compatibility. HDR/color-managed capture is not supported.
- Filename format: `PulseCapture_2026-10-07_181245.mp4`, then `_001`, `_002`, etc.
  Atomic lock files reserve names across running instances. FFmpeg uses no-
  overwrite mode; final publishing also refuses to replace existing files.
- In-progress recordings use `.partial.mp4`. Failed or interrupted nonempty files
  are retained for inspection; they may be unplayable. They are never labeled
  saved. A forced app/process termination can leave a `.lock`; subsequent
  recordings skip it. Delete stale locks only when no recording uses them.
- Normal stop has a 30-second finalization timeout; a stalled process is terminated
  and its partial file retained. Long recordings or slow drives can need more time;
  `Recorder` accepts a configurable timeout for embedding/custom builds.
- Settings writes are atomic. Invalid settings fall back to safe defaults.

## Project structure

```text
pulse_capture.py              Entry point / DPI setup
branding.py                   Shared source / packaged branding paths
settings.py                   Settings and destination defaults
ui/theme.py                   Reusable Pulse design system
ui/app.py                     App shell and Screen 1
ui/region_overlay.py          Interactive Tk area selector
capture/models.py             UI-independent recording configuration
capture/ffmpeg_backend.py     Discovery, command construction, validation
capture/audio_devices.py      DirectShow enumeration and classification
capture/recorder.py            Threaded process lifecycle and state events
capture/filenames.py           Collision-safe reservations and publication
capture/window_picker.py      Native Windows/DPI helpers and enumeration
capture/region_picker.py      Pure region geometry
capture/hotkey.py              Optional global Windows shortcut
editor/models.py              Editing state and time validation
editor/transforms.py          Combined edit state and shared filter graph
editor/text_overlay.py        Text validation, sizing, font and UTF-8 resources
editor/privacy.py             Source-anchored mask geometry and privacy filters
editor/privacy_preview.py     Visual mask drawing, moving, and resizing
editor/overlay_tools.py       Focused Text and Privacy panels
editor/crop_preview.py        Visual crop overlay and source-coordinate dragging
editor/media.py               Local video metadata loading
editor/preview.py             Background, bounded-size frame previews
editor/timeline.py            Trim handles and playhead
editor/editor_window.py       Separate Quick Edit interface
editor/ffmpeg_export.py       Combined trim / crop / overlays command construction
editor/export_job.py          Progress, cancellation, and validated export
editor/filenames.py           Non-overwriting edited-copy reservations
tests/                        Automated headless tests
assets/branding/               Pulse icon and design notes
vendor/                       Optional FFmpeg/FFprobe binaries
```

The capture layer never imports Tkinter. UI changes do not require altering
FFmpeg command construction or recording orchestration. Worker threads communicate
through queues; only the main thread manipulates Tk widgets.

The editor uses independent state and background services. The recorder UI passes
only the saved path and backend executables to the editor. Neither preview nor
export logic imports Tkinter; the editor UI alone renders frames on the main thread.

## Test and build

```powershell
python -m unittest discover -v
.\build.ps1 -InstallBuildTools
```

Optional real FFmpeg tests export all formats with audio/silence, render every
watermark corner and size, render literal Unicode text, check privacy pixels
after every crop, compare preview/export, verify temporary text cleanup and
cancellation, decode results, and verify source preservation:

```powershell
$env:PULSE_RUN_FFMPEG_TESTS = '1'
python -m unittest discover -v
```

For the actual Tk editor checks (opens test windows on Windows):

```powershell
$env:PULSE_RUN_UI_TESTS = '1'
python -m unittest discover -v
```

See `EDITOR_VERIFICATION.md` for Milestone 3 checks and remaining coverage.

The application is produced at `dist\Pulse Capture\Pulse Capture.exe`.
Keep its complete folder together, including `_internal`. This windowed build
opens without a terminal. The default build uses locally installed FFmpeg.

To include your own binaries:

```powershell
.\build.ps1 -BundleFFmpeg -FFmpegDirectory 'C:\Tools\ffmpeg\bin'
```

The build runs tests first and stops on failure. See `THIRD_PARTY_NOTICES.md`
before distributing a build containing third-party binaries.

Automated tests cover command construction, invalid options, audio parsing,
settings recovery, concurrent filename reservations, and process success/failure
transitions. Actual hardware/desktop checks must be performed on Windows.

Manual acceptance: try each capture source, reverse-drag an area, cancel the
overlay, move between differently scaled monitors, restore/minimize target
windows, test each audio source and both together where available, unplug a
device, enable the shortcut, close during recording, and play the saved MP4.

Technical references: [FFmpeg capture devices](https://ffmpeg.org/ffmpeg-devices.html),
[FFmpeg command/progress options](https://ffmpeg.org/ffmpeg.html).
