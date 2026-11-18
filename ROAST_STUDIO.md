# Roast Studio — JSON-powered comedy edits

## Why this is a separate module

**Quick Edit → ROAST STUDIO · JSON** is a dedicated entry point for receiving
an externally prepared GTA/gameplay roast edit. It reuses the existing
Pulse Edit Plan v2 and FFmpeg review/export engine. It is **not** a new renderer,
a substitute for Auto Edit, or a tool that silently edits videos in place.

Previous Pulse Plan imports rejected plans for a different **filename**, **duration**
or **SHA-256**. That protection remains intact for ordinary plans. Roast Studio
instead creates a **new source-bound copy in memory** after checking the exact
video opened in Quick Edit and explicitly asking permission if content or metadata
differs. The original JSON, video, clips, profiles and reaction libraries remain
untouched.

## User flow

1. Open the actual MP4 in Quick Edit.
2. Click **ROAST STUDIO · JSON**.
3. Click **CHOOSE JSON EDIT** and pick a `pulse-edit-plan` version **2** JSON.
4. Leave **SOURCE OFFSET** at `0` if the joke's scene is at the same time in
   both files. For a trimmed copy, enter the change in source time in seconds:
   if a scene at **185 seconds** in the recipe occurs at **5 seconds** in the
   opened video, use **-180**.
5. Click **BUILD & REVIEW ROAST**. The app hashes the actual opened recording.
   If its bytes or metadata don't match the reference, it **requires** an
   explicit warning/confirmation. This is NOT automatic scene recognition.
6. A validated, source-bound plan opens in the existing plan editor and starts
   a new review render. Inspect the complete result and manually **EXPORT VIDEO**.

### Content safeguards

- The JSON cannot name arbitrary input files, shell commands, external audio
  downloads or output paths. Input is always the MP4 selected in Quick Edit.
- An optional manual source offset shifts source-side `shot.start`,
  `shot.end` and `freeze.source_time` only; **caption, SFX and emoji/GIF
  cues remain aligned to the assembled output timeline**.
- All captions are locked to **comedy_bands**. Pulse's existing typography
  validation enforces safe top/bottom band fit and mobile-readable text.
  Existing canvas emoji/GIF placements move into the bottom band as well.
- Impossible source-time requests fail with a helpful error; values are never
  stretched, normalized or guessed. Wrong footage can still contain unrelated
  visual moments even when times fit. Always check the preview.
- Missing reaction assets fail validation. No copyrighted meme voice is
  synthesized, downloaded or falsely substituted with a different effect.
  Existing locally imported and permission-checked IDs continue working.
- Ordinary strict **IMPORT PULSE PLAN** remains unchanged.
- Everything uses existing FFmpeg assembly, audio sync, edit station and
  manual export. Nothing publishes automatically.

## Testing status

Focused Windows Actions job **Roast Studio focused checks** ran compileall plus
`tests.test_roast_recipe`, `tests.test_pulse_plan` and
`tests.test_comedy_bands` successfully on commit `0f1fd96`.

**Real Windows Tk user-flow testing and the live GTA clip render are not yet
verified**. Keep the candidate separate from stable until the PC tests and
manual video review pass.

## Guarded PC verification and installation

**Close Pulse Capture** and save any unsaved edit settings first. Execute the
whole PowerShell block, not individual lines. This creates a local backup
branch, tests the candidate without overwriting anything, returns to the PC
branch, then fast-forwards the existing installation only after the tests
pass. No ZIP files, resets, cleans or duplicate directories.

```powershell
& {
    $ErrorActionPreference = "Stop"
    $pc = "$env:USERPROFILE\Desktop\Pulse-Capture"
    Set-Location $pc

    $original = "pc/quick-edit-choose-video-20261117"
    $candidate = "origin/feature/roast-studio-json-source-bind-20261118"
    if ((git branch --show-current).Trim() -ne $original) {
        throw "Wrong PC branch. Nothing changed."
    }
    if (git status --porcelain) {
        throw "Uncommitted edits. Preserve them before updating."
    }

    git fetch origin "refs/heads/feature/roast-studio-json-source-bind-20261118:refs/remotes/origin/feature/roast-studio-json-source-bind-20261118"
    if ($LASTEXITCODE -ne 0) { throw "Fetch failed." }
    git merge-base --is-ancestor HEAD $candidate
    if ($LASTEXITCODE -ne 0) { throw "Branches diverged. No force merge." }

    $previous = (git rev-parse --short HEAD).Trim()
    $backup = "backup/pc-before-roast-studio-$previous"
    if (-not (git branch --list $backup)) {
        git branch $backup
        if ($LASTEXITCODE -ne 0) { throw "Backup failed." }
    }

    $oldPath = $env:PATH
    $oldUI = $env:PULSE_RUN_UI_TESTS
    $entered = $false

    try {
        if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            $exe = Get-ChildItem "$pc\vendor" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($exe) { $env:PATH = "$($exe.DirectoryName);$env:PATH" }
        }
        if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or
            -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
            throw "FFmpeg and FFprobe are required for the real UI test."
        }

        git switch --detach $candidate
        if ($LASTEXITCODE -ne 0) { throw "Could not open test branch." }
        $entered = $true

        py -3 -m unittest tests.test_roast_recipe tests.test_pulse_plan tests.test_comedy_bands -v
        if ($LASTEXITCODE -ne 0) { throw "Pure tests failed. Stable branch remains intact." }

        $env:PULSE_RUN_UI_TESTS = "1"
        py -3 -m unittest tests.test_roast_studio_ui -v
        if ($LASTEXITCODE -ne 0) { throw "Windows UI test failed. No install." }

        Write-Host "ROAST STUDIO CANDIDATE TESTS PASSED" -ForegroundColor Green
    } finally {
        if ($entered) {
            git switch $original
            if ($LASTEXITCODE -ne 0) { throw "Could not restore stable branch." }
        }
        $env:PATH = $oldPath
        if ($null -eq $oldUI) {
            Remove-Item Env:PULSE_RUN_UI_TESTS -ErrorAction SilentlyContinue
        } else {
            $env:PULSE_RUN_UI_TESTS = $oldUI
        }
    }

    git merge --ff-only $candidate
    if ($LASTEXITCODE -ne 0) { throw "Fast-forward installation failed." }
    git log -1 --oneline
    Write-Host "ROAST STUDIO INSTALLED IN THE ORIGINAL FOLDER" -ForegroundColor Green
}
```

After installation launch from the same PC folder with
`py -3 pulse_capture.py` or a verified shortcut to that checkout.
Open the original GTA recording first, then select one of the supplied
JSON roast recipes. If the source differs, approve binding **only after**
confirming the scene is really at the intended timestamp.
