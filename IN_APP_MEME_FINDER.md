# In-app Meme Finder (Openverse) — candidate verification

This candidate changes **FIND MEME SOUNDS** to open a native Pulse Capture window. Search,
browse source/creator/rights, preview individual clips, then explicitly import to the
existing reaction library. Search and preview stay inside the app. SOURCE / RIGHTS opens the
original attribution page on request.

The finder currently searches **Openverse audio**, not Myinstants, Vlipsy or iMyFone:
- Myinstants and Vlipsy do not currently offer an unrestricted search API suitable for this
  use; Vlipsy's November 2026 terms say public API access is halted, and usage requires permission.
- Openverse indexes third-party CC0, public-domain and CC BY audio. A search index does not
  verify copyright ownership or licence applicability; all imported clips remain **Unverified**
  until independently reviewed, and CC BY may require attribution.
- Original human recordings are not bundled. Specific famous meme clips may not appear.
- Nothing is published, purchased, scraped or downloaded in bulk.

API and security guardrails: opt-in search, ≤20 entries requested per search, 12-second timeout
for search, preview downloads only when selected, HTTPS allowlist for known audio hosting
domains, strict WAV/MP3 extensions, ≤12 MB per download, redirects checked, cancellation
and dedicated temporary files. All imports use the existing 48-kHz audio library. Openverse
is credited as independent and not endorsing Pulse Capture.

## Testing (PC; no new installation)

The branch is **draft and not yet Windows verified**. To test, close Pulse Capture and
run this complete PowerShell block. It checks clean Git state, makes a local backup
branch, enters the remote candidate only temporarily, runs tests, then returns to
your original branch even if tests fail. No reset, clean or media deletion.

```powershell
& {
  $ErrorActionPreference = 'Stop'
  $pc = "$env:USERPROFILE\Desktop\Pulse-Capture"
  Set-Location $pc
  $original = (git branch --show-current).Trim()
  if ($LASTEXITCODE -ne 0 -or $original -ne 'pc/quick-edit-choose-video-20261117') {
    throw 'Unexpected PC branch. Stopping.'
  }
  $dirty = git status --porcelain
  if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Preserve local changes first.' }
  $current = (git rev-parse --short HEAD).Trim()
  git branch "backup/pc-before-meme-finder-$current"
  if ($LASTEXITCODE -ne 0) { throw 'Backup failed.' }
  git fetch origin 'refs/heads/feature/in-app-meme-finder-openverse-20261118:refs/remotes/origin/feature/in-app-meme-finder-openverse-20261118'
  if ($LASTEXITCODE -ne 0) { throw 'Fetch failed.' }
  git merge-base --is-ancestor HEAD origin/feature/in-app-meme-finder-openverse-20261118
  if ($LASTEXITCODE -ne 0) { throw 'Branches diverged; no changes made.' }

  git switch --detach origin/feature/in-app-meme-finder-openverse-20261118
  if ($LASTEXITCODE -ne 0) { throw 'Could not enter test branch.' }
  $result = 1
  try {
    py -3 -m unittest tests.test_meme_catalog tests.test_soundboard tests.test_meme_finder_ui -v
    $result = $LASTEXITCODE
  } finally {
    git switch $original
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore original branch; investigate without reset.' }
  }
  if ($result -ne 0) { throw 'Focused tests failed. Stable PC branch was restored.' }
  Write-Host 'FOCUSED TESTS PASSED. PC BRANCH RESTORED.' -ForegroundColor Green
}
```

**Then** opt into the real Tk test with `PULSE_RUN_UI_TESTS=1` and the vendor FFmpeg
directory on PATH, using the same temporary-switch pattern. Ensure WAV/MP3 previews
are audible, the source and licence are visible, and the imported clip appears in
SOUND FX and can be placed on the timeline. Report tested/skipped counts explicitly.

Only after PC verification should the candidate be fast-forward merged into the existing
PC branch. No user-owned media, profiles, recordings or history should be removed.
