# Soundboard verification — 18 November 2026

Base: PC checkpoint `b62714b`. Feature: `feature/universal-soundboard-20261118`.

## Test results

The complete regression suite ran on Windows with both real FFmpeg and Tk tests
enabled: **355 run, 354 passed, 1 failed, 0 skipped**, in 465.688 seconds.

The failure was a stale pre-existing video-picker expectation:
`test_existing_latest_recording_opens_without_dialog`. The installed picker was
deliberately changed in `042bf97` to always offer a choice of video. The test was
updated to assert that the latest file is suggested but another file can be chosen.
No production picker or recorder code was changed.

After that correction and final soundboard refinements, the affected suites were
rerun: **19 passed, 0 failed, 0 skipped**, in 12.171 seconds. These include the
soundboard, media-library UI, optional voice generator and Quick Edit entry tests.
The entire expensive render suite was not rerun a second time.

Commands:

```text
python -m unittest discover -s tests -v
python -m unittest tests.test_soundboard tests.test_media_library_ui tests.test_voice_tools tests.test_quick_edit_entry -v
```

Both runs used `PULSE_RUN_UI_TESTS=1`, `PULSE_RUN_FFMPEG_TESTS=1`, Python 3.13 and the
PC's existing vendor FFmpeg. Regression media and libraries were isolated from
user recordings and imported assets. The full run also printed a nonfatal Tk
queued-callback warning during an existing comedy UI test; that test passed.

## Actual preview/export evidence

- The real Windows reaction dialog imported generated WAV and MP3 fixtures,
  detected the duplicate WAV, searched aliases, saved metadata and favourites,
  selected a suggestion without applying it, and inserted it after user acceptance.
- Windows `winsound.PlaySound` was called without mocking on a decoded audition
  WAV and returned successfully. This verifies the playback path, not a human
  listening assessment or physical speaker output.
- The real editor exported a 2.5-second H.264/AAC MP4 after a source cut and 2x
  speed, with the imported reaction at output second 1 and the existing caption.
  The retained artifact is `soundboard-windows-demo.mp4` in the local verification
  folder. FFprobe confirmed 640×360 video and 48 kHz AAC. A frame at 1.2 seconds
  was inspected and shows the caption over the source test pattern.
- Independent decoded-audio checks verify silence before the cue, reaction energy
  during the cue, correct output duration, source ducking and matching reaction
  levels between seeked preview and exported audio (within 0.015 amplitude).
- Missing assets and corrupted input produce errors without insertion; duplicate
  imports and restoration of a missing library file retain metadata. TTS origin
  remains recognisable after recategorisation, and recordings sort ahead of TTS.
- The existing soundboard buttons were measured as fully mapped and unclipped at
  the 760×620 minimum size. Desktop screenshot inspection was not available for
  the isolated test window; this was a Tk geometry check.

The test audio is synthetic. No human meme pack, copyrighted clip, download or
automatic publishing was used. No new third-party licence records are necessary.

## Safety and remaining work

The installed PC checkout remained clean at `b62714b` on its existing branch.
Profiles, recordings and user media were not migrated, removed or overwritten.
The laptop checkpoint `22a4b49` is an ancestor of this base, but its current local
working tree was not inspected. Use the guarded update steps in
[UNIVERSAL_SOUNDBOARD.md](UNIVERSAL_SOUNDBOARD.md).

Human reaction clips must be imported by the user. Suggestions currently match
existing captions and protect known/unknown speech conservatively. Generating new
visual jokes and coordinated freeze/zoom suggestions remains outside this first
soundboard checkpoint. Existing Auto Edit budget and v1/v2 plan schemas are unchanged.
