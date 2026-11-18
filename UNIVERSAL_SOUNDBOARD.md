# Universal reaction soundboard

This feature starts from the PC's `b62714b` checkpoint, including the video-picker,
Auto Edit diversity, media library, voice fallback and portrait letterbox fixes.
The recorder, audio capture, installation and saved media locations are unchanged.

## Using it

Open **REACTION AUDIO / SOUND FX** in Quick Edit. Imported recordings appear ahead
of synthesized effects. Search by name, spoken words, creator, tags or aliases.
For example, an “OH HELL NAH” recording is also discoverable through “nope” and
“disbelief”. Reaction category filters supplement existing custom categories;
favourites and recent items remain available. Selecting a result previews it.

**FIND MEME SOUNDS** opens a normal external search page for the entered phrase.
Review a source's permissions, obtain a WAV/MP3 yourself, then use **IMPORT FILES**.
No crawling, scraping, automatic downloading, PDH integration or platform account
is involved. Batch importing, per-file errors and content-based deduplication use
the existing persistent library. Imports clear old search filters so new files
are visible immediately.

**DETAILS / LICENCE** stores exact attribution, source, creator, transcript, aliases
and tags. Rights status is an explicit user declaration: Unverified, Original
recording, or Licensed / permission-cleared. Embedded licence text never upgrades
an import's status. Unverified clips remain usable locally, with a publication
rights reminder beside the selected clip. Bundled credits stay read-only.

New audio imports receive a fixed gain targeting RMS 0.18, with at most 12 dB
boost and a 0.90 sample peak ceiling. Near-silence is not boosted. This preserves
dynamics and adds no time shift. Both preview and export read the same stored
48 kHz stereo PCM. Original source files and existing library WAVs are untouched.
The applied gain is recorded as `import_gain_db`; existing cue volume, fades,
duration and source/music ducking remain available.

## Reviewed suggestions

**SUGGEST REACTION** matches existing captions to imported local recordings using
phrases, aliases and reaction categories. It works in Auto Edit candidates and
assembled Pulse Edit Plans through their existing Quick Edit window. It selects
a clip, fills the existing cue controls and moves the playhead to the proposed
time. Preview it and press **INSERT AT PLAYHEAD** to accept. No cue is inserted by
the suggestion action itself. Existing SAVE CUES and Pulse v2 SFX records use the
same asset IDs and output clock; no plan schema changes are needed.

Suggestions avoid previously used clips, leave spacing between reactions, skip
Windows voices and synthesized effects, and use complete clips of up to four
seconds. Available Auto Edit speech intervals are protected. Without a transcript,
audible footage is treated conservatively as protected; Pulse freezes and title
cards can provide silent gaps. Cuts, trims and speed are mapped before placement.
If no matching clip or safe gap exists, the soundboard says so explicitly.

Windows voice creation remains an explicit optional action. New generated voices
retain their origin even after renaming or recategorisation. Older voice imports
are recognised by their existing Voices category or Voice prefix.

## Limits of this checkpoint

No third-party human meme recordings are bundled or downloaded. The expressive
audio comes from recordings and permission-cleared files the user imports. The
163 original effects and existing GIF pack remain available; synthesized tones
are not presented as human reactions.

Suggestions match text, not visual humour or plot. They reuse captions already
provided by Auto Edit, a Pulse plan or the user. Turning on Comedy Layout alone
still does not write new jokes. Automatic visual joke writing and coordinated
freeze/zoom proposals remain further work. No API calls or publishing are added.
Unknown speech can intentionally produce no suggestions; manual insertion remains
available. Rights declarations are saved information, not independent verification.

## Updating the existing PC folder

Close Pulse Capture first. These commands keep the current PC branch, reject a
dirty checkout, and allow only a fast-forward update. They do not reset, clean,
reinstall or remove any files. A failed check stops the update.

```powershell
Set-Location -LiteralPath 'C:\Users\lenno\Desktop\Pulse-Capture'
$changes = git status --porcelain
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Stop: preserve local changes before updating.' }
git fetch origin feature/universal-soundboard-20261118
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed; nothing updated.' }
git merge --ff-only origin/feature/universal-soundboard-20261118
if ($LASTEXITCODE -ne 0) { throw 'Branches differ; stop here for review. Do not reset or force the merge.' }
```

Launch Pulse Capture using the existing shortcut. Imported media remains in its
existing persistent library outside the code checkout.

For the laptop use its existing folder instead:
`C:\Users\lenno\OneDrive\Desktop\Pulse-Capture-source\Pulse-Capture`.
The same clean-tree and fast-forward checks apply. A laptop with extra local
commits may reject the update; preserve those commits for review rather than
overwriting them. Updating code does not copy the PC's imported audio to the laptop.

## Verification

`tests/test_soundboard.py` exercises phrase/alias matching, explicit rights,
encoded external discovery, distinct suggestions, speech protection and time
mapping. Its opt-in Windows test imports synthetic WAV and MP3 files through the
actual dialog, plays a real Windows audition, edits metadata, accepts a suggestion,
inserts after a cut at 2x speed and exports through the actual editor.

The audio integration test decodes the MP4 and measures reaction onset, duration,
background ducking and agreement with the seeked audio preview. It also checks
duplicate imports, damaged-input errors and metadata retention when restoring a
missing library file. Tests use temporary synthetic audio, not copyrighted clips.

Run with `PULSE_RUN_UI_TESTS=1` and `PULSE_RUN_FFMPEG_TESTS=1` and the existing vendor
FFmpeg directory on PATH. `PULSE_VERIFICATION_DIR` optionally retains the Windows
demo MP4. The release verification record reports the actual regression result.
