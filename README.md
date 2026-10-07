# PULSE // CAPTURE v0.1

A small Windows screen recorder with a dark Pulse interface. Choose a source,
record, stop, and get a local MP4. No watermark, editor, account, or cloud.

## Run

Requires Windows 10/11 and Python 3.11+ with Tcl/Tk. There are no third-party
Python runtime dependencies. Install FFmpeg and FFprobe from a Windows build
with `gdigrab`, `dshow`, `libx264`, and AAC support. Both binaries must be on PATH
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
   virtual desktop. Window lists visible, non-minimized windows and records the
   selected handle. Area opens a desktop overlay: drag a rectangle, or press Esc
   to cancel. Reverse drags and monitors with negative coordinates are supported.
2. Select microphone/input and system-audio devices when available. Uncheck an
   input for silent capture. **Refresh devices** re-enumerates connected hardware.
3. Choose Standard (H.264 CRF 23) or High (CRF 18), and 30 or 60 FPS.
4. Press **Start recording**. “Starting” means FFmpeg is opening devices;
   “Recording” appears only after FFmpeg reports encoded frames.
5. Press **Stop recording**. Pulse waits for FFmpeg to finalize the MP4, checks
   video frames, duration, and requested audio, then shows **Saved**.
6. **Open folder** opens the recording destination in Explorer.

Recordings default to `%USERPROFILE%\Videos\Pulse Capture`.
Preferences are stored at `%LOCALAPPDATA%\Pulse Capture\settings.json`.
An advanced `output_folder` preference can set a different directory.
The optional global **Ctrl+Shift+R** shortcut works while Pulse is in the
background. A conflict with another app is shown explicitly; the shortcut is
off by default. Closing Pulse during capture requests a clean stop first.

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
tests/                        Automated headless tests
assets/branding/               Pulse icon and design notes
vendor/                       Optional FFmpeg/FFprobe binaries
```

The capture layer never imports Tkinter. UI changes do not require altering
FFmpeg command construction or recording orchestration. Worker threads communicate
through queues; only the main thread manipulates Tk widgets.

## Test and build

```powershell
python -m unittest discover -v
.\build.ps1 -InstallBuildTools
```

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
