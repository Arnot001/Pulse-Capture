# Reaction-first meme finder — PC test candidate

The earlier internal finder worked but returned too many generic, long and musical
clips. This branch makes a small, focused improvement without changing providers,
source files, installed data, the sound mixing pipeline, or any licence checks.

Changes:
- Quick in-app searches: **SHOUTS, LAUGHS, SHOCK, NOPE, FAIL, BOOM**.
- Short (0.4–5.5-second) voice-like recordings rank ahead of longer tracks.
- Recognised reaction/voice tags receive a relevance boost; music/remix titles
  rank lower. Full manual phrase search still works independently.
- Sound duration is visible in the search list and detail pane.
- No extra API requests are issued for ranking or presets; all content still
  comes from the same Openverse search, with the existing manual preview/import
  flow and unverified-rights labels.
- Results are **not** verified viral memes. More expressive real human recordings
  need genuinely better source material or independently recorded/cleared audio.

## Safe PC verification

Close Pulse Capture before running the block below. It checks that the current
working branch is clean and a direct ancestor of the candidate, tests detached,
restores the working branch, and does **not** install the candidate if tests fail.

```powershell
& {
    $ErrorActionPreference = "Stop"
    Set-Location "$env:USERPROFILE\Desktop\Pulse-Capture"
    $original = "pc/quick-edit-choose-video-20261117"
    $candidate = "origin/feature/reaction-first-finder-20261118"

    if ((git branch --show-current).Trim() -ne $original) { throw "Wrong branch: stopping." }
    if (git status --porcelain) { throw "Uncommitted changes: stopping." }

    git fetch origin "refs/heads/feature/reaction-first-finder-20261118:refs/remotes/origin/feature/reaction-first-finder-20261118"
    if ($LASTEXITCODE -ne 0) { throw "Fetch failed." }
    git merge-base --is-ancestor HEAD $candidate
    if ($LASTEXITCODE -ne 0) { throw "Branches diverged: stopping." }

    $before = (git rev-parse --short HEAD).Trim()
    git branch "backup/pc-before-reaction-search-$before"
    if ($LASTEXITCODE -ne 0) { throw "Backup failed." }

    $oldPath = $env:PATH
    $oldUi = [Environment]::GetEnvironmentVariable("PULSE_RUN_UI_TESTS")
    $oldRender = [Environment]::GetEnvironmentVariable("PULSE_RUN_FFMPEG_TESTS")
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        $binary = Get-ChildItem "$env:USERPROFILE\Desktop\Pulse-Capture\vendor" -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($binary) { $env:PATH = "$($binary.DirectoryName);$env:PATH" }
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "FFmpeg not found." }

    $entered = $false
    try {
        git switch --detach $candidate
        if ($LASTEXITCODE -ne 0) { throw "Could not enter candidate." }
        $entered = $true
        $env:PULSE_RUN_UI_TESTS = "1"
        $env:PULSE_RUN_FFMPEG_TESTS = "1"
        py -3 -m unittest tests.test_meme_catalog tests.test_meme_finder_ui tests.test_soundboard -v
        if ($LASTEXITCODE -ne 0) { throw "Candidate tests failed. No installation." }
        Write-Host "REACTION-FIRST WINDOWS TESTS PASSED" -ForegroundColor Green
    } finally {
        if ($entered) {
            git switch $original
            if ($LASTEXITCODE -ne 0) { throw "Could not restore working branch." }
        }
        $env:PATH = $oldPath
        $env:PULSE_RUN_UI_TESTS = $oldUi
        $env:PULSE_RUN_FFMPEG_TESTS = $oldRender
    }
}
```

Once the PC tests pass, repeat the clean-branch and ancestor checks and use
`git merge --ff-only origin/feature/reaction-first-finder-20261118` to install.
Do not force or reset; preserve all recordings, profiles and imported files.

Manual smoke test after merge: Quick Edit → SOUND FX → FIND MEME SOUNDS.
Choose LAUGHS then SHOCK, inspect durations, audition one actual sound, import
only with rights review, and verify cue insertion and export.
