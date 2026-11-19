# Voice Studio V2 — verification snapshot (19 November 2026)

**Development branch:** `feature/voice-studio-v2-20261119`  
**Draft PR:** #15 (targets `feature/ai-voiceover-studio-20261119`)  
**Scope:** recorded/imported voice, CPU OpenVoice V2 speech-to-speech conversion, voice catalogue, processing controls and output-clock narration. No code from the separate smooth-preview branch has been merged.

## Verified on GitHub Actions

The Windows focused workflow `Voice Studio V2 focused regression` completed successfully: **28 tests, OK**. It covers the existing text-to-speech guards, narration validation, local recording/asset/catalogue controls, actual FFmpeg narration rendering and preview, editor audio-preview and reaction compatibility tests.

These tests do not validate the subjective perceived gender, accent, fidelity or expressive quality of each voice, nor do they simulate the entire Tk GUI or install the OpenVoice model from scratch.

## Prior local handover evidence (not repeated by this CI)

- Prior broad run: **392 tests OK, 55 skipped**, before final V2 edits
- Focused voiceover/V2 run: **19 passed**
- UI/render: **11 passed**
- Opt-in local CPU neural conversion: **3 passed**; a synthetic 11.19-second performance was reportedly converted in ~31 seconds, preserving timing and an inserted pause
- One explicit five-second microphone test was approved by the user and completed; its approval does **not** authorize further live microphone tests
- Broader Windows UI rerun was stopped by the user, so it must **not** be described as passed

## Outstanding

1. Rerun broader Windows UI suite using private `LOCALAPPDATA` and `PULSE_REACTION_LIBRARY` roots
2. Verify packaged PyInstaller worker and fresh CPU model setup independently
3. Listen to actual output for voice quality, emotion, laughter and comedy timing
4. Keep paid OpenAI requests behind per-request confirmation; no paid requests are needed for local voice conversion
5. Stock OpenVoice speakers have no verified male/female/age classification and no redistributable preview samples are bundled
6. One narration cue is supported by the current Quick Edit architecture; a visual multitrack timeline is not part of V2
7. Review any required integration with the dirty, separate smooth-preview worktree before merging

**Status: draft / not cleared for release.** Keep all recordings, credentials, private libraries and model weights outside Git.
