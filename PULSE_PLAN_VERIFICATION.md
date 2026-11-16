# Pulse Plan implementation handover — 16 November 2026

Feature branch: `feature/pulse-edit-plan-20261116`.
Base: `fix/wasapi-mute-safe-stop-20261116`, commit
`41aca5bd9416495e7c9dc5494e2965ffdec251df`.

Publication status: the GitHub upload was rejected by automatic approval review
because it considered publishing staged changes to the public repository insufficiently
authorized. The implementation is saved on the local feature branch; no remote
feature branch or PR was created. The pull commands below apply only after publication.

Implemented: local JSON import/edit/validation; source fingerprint checks; reordered
and repeated shots; Full Frame and Crop to Fill; opening/closing cards with five
animations; editable output-time captions; freeze, speed, punch-in and volume;
hard cut, dissolve and symmetric fade-through-black; commentary script retention.
See `PULSE_EDIT_PLAN.md` for the full contract and explicit unsupported features.

## Changed files and reasons

* `editor/auto_plan.py`: dispatch strict external validation and editor-state conversion;
  retain legacy validation and add style-dependent Full Frame defaults.
* `editor/pulse_plan.py`: versioned closed contract, bounded JSON parsing, source
  identity checks, timeline calculations and conversion to existing caption state.
* `editor/pulse_job.py`: cancellable assembly, cleanup and decoded A/V checks.
* `editor/ffmpeg_export.py`: reuse existing segment export; normalized joins, cards,
  freezes and named transitions with synchronized audio.
* `editor/pulse_tools.py`, `auto_tools.py`, `editor_window.py`, `caption_tools.py`:
  import/source-ID buttons, editable recipes, timeline inspection, review windows
  and output-time caption editing.
* `editor/transforms.py`, `privacy_preview.py`: Full Frame layout shared by preview
  and export, with correctly mapped privacy/zoom interaction.
* `editor/auto_analysis.py`, `auto_job.py`: Comedy / Roast preset and style propagation.
* `tests/test_pulse_plan*.py`: validation, actual decoded video/audio and Tk workflows.
* Existing format/overlay tests: account for encoded Shorts dimensions and padded
  coordinates rather than assuming every format exports the source-sized canvas.
* `examples/` and documentation: complete JSON example and local fixture generator.

Capture/WASAPI modules, recording settings and dependencies are unchanged.

## Verification status

Windows, Python 3.13.17, bundled FFmpeg 9.0.2. Python compilation and `git diff --check`
pass. New unit checks pass. Real FFmpeg checks pass for all five title animations,
reordered/replayed shot audio frequencies, audio coverage, freeze-frame stability and
silence, source preservation, top/bottom caption pixels, full-width picture edges,
slow motion, source volume, punch-in, dissolves, black-transition midpoint and cleanup.
Updated actual-pixel privacy checks pass for every format.

The first complete run executed 292 tests and exposed five failures in old pixel-test
coordinate assumptions and fade-black timing. These were corrected and the affected
checks passed. A final complete regression run was started; consult the accompanying
local `final-tests.log` for its final status rather than treating the initial run as passing.

Two additional Tk tests passed using a copy of the real Windows recording
`PulseCapture_2026-11-16_171919.mp4` (1600×900, 30 fps, 382.8 s): full-frame interaction
mapping and import → render → playback → caption update → export → reopen recipe.
The original and verification copy have identical SHA-256 fingerprints after testing.
Desktop visual automation could enumerate the editor but could not capture its window
(`window capture timed out`) or obtain click geometry. Thus automated real-recording
GUI verification passed; a human-style visual desktop walkthrough remains unverified.

## Reproduce

```powershell
$env:PATH = "$PWD\vendor;$env:PATH"
$env:PULSE_RUN_FFMPEG_TESTS = '1'
$env:PULSE_RUN_UI_TESTS = '1'
py -3 -m unittest discover -s tests -v
```

To repeat the real-recording Tk check, set `PULSE_REAL_RECORDING` to a local MP4 and
run `py -3 -m unittest tests.test_pulse_plan_ui -v`. Tests use a temporary copy.

## Pull onto the existing PC installation

After the feature branch is available on origin, run these in PowerShell. Git will
stop on conflicting local changes; do not discard recordings or local modifications.

```powershell
Set-Location 'C:\Users\lenno\Desktop\Pulse-Capture'
git status --short
git fetch origin 'refs/heads/feature/pulse-edit-plan-20261116:refs/remotes/origin/feature/pulse-edit-plan-20261116'
git switch feature/pulse-edit-plan-20261116
git pull --ff-only origin feature/pulse-edit-plan-20261116
.\launch.ps1
```

No additional dependencies or API key are required. The feature branch is for manual
review; no merge, deployment or publishing is performed automatically.
