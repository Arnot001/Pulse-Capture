"""Bounded OpenAI speech generation. One explicit paid attempt per unique script/settings.

Generated WAVs live under LOCALAPPDATA/Pulse Capture/voiceovers, never in Git.
The API key is taken from the process environment, never persisted.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
import wave

MODEL = "gpt-4o-mini-tts"
# OpenAI marks /v1/audio/speech and this model deprecated on 2027-01-06.
# Replace this transport with Realtime before that date; do not silently swap APIs.
SHUTDOWN_DATE = "2027-01-06"
VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable",
          "marin", "cedar", "nova", "onyx", "sage", "shimmer", "verse")
MAX_CHARACTERS = 700
MAX_FILE_BYTES = 12 * 1024 * 1024

STYLES = {
    "Dry British": "Narrate in a natural British English accent, with subtle deadpan sarcasm, believable pauses and conversational delivery. Do not alter the written words.",
    "Documentary": "Narrate like a thoughtful British nature documentary presenter, serious and understated, with natural pauses. Do not alter the written words.",
    "Excited": "Energetic and surprised commentary, with lively phrasing and natural human intonation, not robotic shouting. Do not alter the written words.",
    "Neutral": "Clear natural narration at a moderate pace with realistic intonation. Do not alter the written words.",
}


def library_root():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Pulse Capture" / "voiceovers"


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    voice: str = "marin"
    style: str = "Dry British"

    def validate(self):
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > MAX_CHARACTERS:
            raise ValueError(f"Speech must contain 1–{MAX_CHARACTERS} characters.")
        if any(ord(c) < 32 and c not in "\n\t" for c in self.text):
            raise ValueError("Speech contains unsupported control characters.")
        if self.voice not in VOICES or self.style not in STYLES:
            raise ValueError("Choose a supported voice and narration style.")

    @property
    def identity(self):
        self.validate()
        payload = json.dumps([MODEL, self.text, self.voice, self.style], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def payload(self):
        self.validate()
        return {
            "model": MODEL,
            "voice": self.voice,
            "input": self.text,
            "instructions": STYLES[self.style],
            "response_format": "wav",
        }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_audio(payload, api_key):
    """Return bounded WAV bytes. No automatic retries or logging of credentials."""
    if not api_key or not api_key.strip():
        raise ValueError("OPENAI_API_KEY is missing. No request sent.")
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": "Bearer " + api_key.strip(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=100) as response:
            if response.status != 200 or response.headers.get("Content-Type", "").split(";")[0].strip().lower() not in ("audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"):
                raise RuntimeError("The service did not return audio; an attempt may have been charged.")
            blob = response.read(MAX_FILE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI speech request returned HTTP {exc.code}; no automatic retry.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("Speech request was interrupted. Charge uncertain; no automatic retry.") from None
    if not blob or len(blob) > MAX_FILE_BYTES:
        raise RuntimeError("Audio response missing or exceeded the safe size limit.")
    return blob


def valid_wav(path):
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnchannels() not in (1, 2) or wav.getframerate() < 8000 or wav.getnframes() < 1:
                raise ValueError("Unusable speech audio.")
            length = wav.getnframes() / wav.getframerate()
            if length > 90:
                raise ValueError("Generated speech exceeded 90 seconds.")
            return length
    except (EOFError, wave.Error, OSError) as exc:
        raise ValueError("OpenAI did not return a valid WAV recording.") from exc


def generate(request, *, approval=False, api_key=None, root=None, sender=request_audio):
    """Generate only on explicit approval; return (wav_path, cached).

    The .attempt marker persists after network failure; avoid accidental repeat charges.
    For retries use different text/settings and explicitly approve a new request.
    """
    request.validate()
    folder = Path(root) if root else library_root()
    ident = request.identity
    wav_path = folder / (ident + ".wav")
    metadata = folder / (ident + ".json")
    marker = folder / (ident + ".attempt")
    if wav_path.is_file():
        valid_wav(wav_path)
        return wav_path, True
    if not approval:
        raise ValueError("Confirm the paid request in Voiceover Studio before generating.")
    if not (api_key or os.environ.get("OPENAI_API_KEY", "")).strip():
        raise ValueError("Set OPENAI_API_KEY on your PC; no request sent.")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8") as handle:
            handle.write("One approved attempt. Do not automatically retry.\n")
    except FileExistsError:
        raise ValueError("This narration already had one API attempt. No automatic paid retry.") from None
    blob = sender(request.payload(), api_key or os.environ["OPENAI_API_KEY"])
    fd, tempname = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        length = valid_wav(tempname)
        os.replace(tempname, wav_path)
        # Save a useful human-readable transcript and settings, not the API key.
        metadata.write_text(json.dumps({
            "model": MODEL, "voice": request.voice, "style": request.style,
            "transcript": request.text, "duration_seconds": length,
            "ai_generated": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return wav_path, False
    finally:
        Path(tempname).unlink(missing_ok=True)
