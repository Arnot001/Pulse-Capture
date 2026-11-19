# Voice Studio V2 preview

This preview adds local microphone/imported narration and OpenVoice V2 conversion to the existing Voiceover Studio. Keep the complete application folder together. Use a separate preview folder rather than replacing an existing Pulse Capture installation.

## Prerequisites

- Windows 10 or 11, 64-bit. Verification used Windows 11 and Python 3.13.15.
- Python 3.13 x64 for the separate conversion environment. Python and FFmpeg are also needed for running from source; the tested application build bundles FFmpeg/FFprobe.
- FFmpeg with the `rubberband` filter for independent pitch and speed controls.
- PyAudioWPatch from `requirements-audio.txt` for microphone recording and editor sound. The packaged application collects it when present in the build environment.
- Internet access during the explicit one-time runtime setup; conversion itself is local and needs no API key or recurring API payment.

Run `setup-voice-studio.py` with Python from a clean checkout of the V2 branch. Its default destination is the current user's Local AppData `Pulse Capture/voice-runtime` folder. The optional `--root` argument chooses a separate runtime; set `PULSE_VOICE_RUNTIME` to that absolute folder when launching Pulse Capture. The installer creates its own Python environment, pins CPU Torch/NumPy, and downloads the pinned MIT-licensed OpenVoice source, converter and ten stock speaker embeddings.

An existing completed runtime is not overwritten. An interrupted setup has no completed installation marker; correct its reported error and rerun setup against that incomplete folder. For replacing an existing installation, choose a new empty runtime folder and change the application override after verification. No recording, profile or reaction-library migration is needed.

Exact PowerShell installation/update commands are supplied in the chat, not in this document.

## Using the preview

1. Open a video in Quick Edit and select **AI VOICEOVER** to open Voice Studio.
2. Select **CHANGE MY VOICE**, choose a named microphone and record, or import a local recording. Recording does not start automatically. Pause/resume controls recording; spoken pauses remain in the take. Retakes create new originals.
3. Select an installed stock voice or import a permitted OpenVoice V2 speaker manifest. Press **TRANSFORM · LOCAL**. Conversion can take longer than the recording on CPU.
4. Compare **A · ORIGINAL** and **B · RESULT**. Use **PREVIEW SETTINGS** after changing speed, pitch, volume or processing options. Normalisation, noise reduction and edge trimming are optional. Edge trimming changes the beginning/end timing; it does not remove interior dramatic pauses.
5. Use **AT PLAYHEAD** or enter an output start time, adjust voice volume/background gain, then **ADD / REPLACE**. This version supports one narration cue. Export through Quick Edit's existing MP4 export.
6. **SAVE AS** writes a separate WAV copy. Saved originals remain in the private voiceover library. Imported audio is copied there before conversion; conversion outputs and their reproducibility metadata are separate files.

Stock labels describe the model provider's language/accent references. Conversion does not translate the words or promise a new accent. Gender and age are unclassified where the provider supplies no verified metadata. Voice presentation/category filters also support appropriately labelled user embeddings. Raw RVC checkpoints are not compatible with this OpenVoice importer.

## API credit counter

The footer is a **local estimate**, not a live OpenAI balance. **OPEN BILLING** opens the official account page. **SET BALANCE** records the USD amount you read there and reconciles the requests already present in this computer's Pulse libraries.

Subsequent Auto Edit GPT calls use their recorded token counts and recorded pricing to estimate spend. Cached reuse does not create another charge. Speech WAV responses do not include billed token usage, so new speech attempts show **billing check needed**, rather than subtracting a fabricated charge. Interrupted or corrupt request records also remain unpriced until you reconcile them against billing.

This counter does not track other computers/apps, credit expiration, top-ups, delayed charges or separate API accounts. It does not enforce a spending limit. No billing credential is requested or saved, and opening or refreshing the counter makes no API request. Existing paid generation still requires its own confirmation.

## Acceptance and current limits

Ten stock embeddings are available, with no bundled audition recordings. Try several on your own performance and decide whether the voice identity, intelligibility, laughter and expressive delivery are suitable. Matching durations and waveform pauses are useful checks but do not establish convincing acting or emotional fidelity.

The separate continuous-preview work remains isolated. This preview uses the existing V1 narration mixing/export architecture. See `VOICE_STUDIO_V2_VERIFICATION.md` for the precise tested revision, results and release status.

## Sources checked 19 November 2026

- [OpenVoice V2 model card and MIT licence](https://huggingface.co/myshell-ai/OpenVoiceV2)
- [OpenAI speech model rates](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
- [OpenAI Costs API: administrator credentials and organization spending](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)
- [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations): the existing speech endpoint/model retires on 6 January 2027. Its replacement uses a different API workflow; this release does not silently substitute it.
