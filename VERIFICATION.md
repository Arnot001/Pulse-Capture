# Verification — 7 October 2026

Test environment: Windows 11, Python 3.13.15, Tk 8.6, FFmpeg 9.0.2,
PyInstaller 6.20.0. The code targets Python 3.11 or newer.

## Automated checks

32 tests passed: capture command construction, argument validation, audio
enumeration and aliases, region geometry, corrupted settings recovery, atomic
settings writes, concurrent filename reservations, no-overwrite publication,
recording startup/stop/error states, startup and finalization timeouts, partial
file retention, and FFprobe output validation.

## Real Windows capture checks

All of the following used the installed FFmpeg capture backend, stopped cleanly,
passed FFprobe validation, and decoded without FFmpeg reporting an error:

| Source | Settings | Result |
| --- | --- | --- |
| Area | 601 × 401, Standard, 30 FPS | Valid H.264 MP4, padded to 602 × 402 |
| Window handle | High, 60 FPS | Valid H.264 MP4 with 60 FPS stream |
| Full desktop | Standard, 30 FPS | Valid 1920 × 1080 H.264 MP4 |
| Window + microphone | Standard, 30 FPS | Valid H.264 video and AAC audio tracks |

The real UI Start/Stop path was exercised, with screenshots inspected in ready
and recording states. Closing during recording finalized a validated MP4 and
closed the app. Reverse area dragging and Escape cancellation were exercised.
Global shortcut registration, conflict handling, message dispatch, and cleanup
were checked against the Windows API.

## Remaining hardware coverage

The build PC exposed a Realtek microphone input and no recognized DirectShow
loopback source. The UI correctly disabled system audio. Two-input mixing is
covered by command tests but was not recorded against actual loopback hardware.
Multi-monitor mixed-DPI behavior, protected video, HDR, other audio drivers,
long recordings, and Windows 10 were not verified on this machine.

Test recordings and temporary profiles were kept outside the delivered project;
they did not alter the user's normal Videos destination or saved preferences.
