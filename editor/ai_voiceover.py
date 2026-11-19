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
    """Measure decoded PCM frames, not the untrusted RIFF header's declared size.

    Streaming Speech responses may put 0xFFFFFFFF in the RIFF/data length
    fields until stream completion. wave.getnframes() then claims hours of
    audio although only seconds exist in the actual file.
    """
    try:
        path = Path(path)
        if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
            raise ValueError("Speech WAV is empty or too large.")
        with wave.open(str(path), "rb") as wav:
            if (wav.getcomptype() != "NONE" or wav.getnchannels() not in (1, 2)
                    or wav.getsampwidth() not in (1, 2, 3, 4)
                    or not 8000 <= wav.getframerate() <= 96000):
                raise ValueError("Unsupported speech WAV format.")
            frame_width = wav.getnchannels() * wav.getsampwidth()
            frame_limit = int(wav.getframerate() * 90) + 1
            # Actual file size bounds the read even with placeholder chunk sizes.
            data = wav.readframes(min(frame_limit, path.stat().st_size // frame_width + 1))
            if len(data) % frame_width or not data:
                raise ValueError("Speech WAV has incomplete PCM samples.")
            frames = len(data) // frame_width
            if frames > int(wav.getframerate() * 90):
                raise ValueError("Generated speech exceeded 90 seconds.")
            return frames / wav.getframerate()
    except (EOFError, wave.Error, OSError) as exc:
        raise ValueError("OpenAI did not return a readable WAV recording.") from exc


def normalize_wav(source, destination):
    """Write a standard RIFF WAV with the real PCM length for FFmpeg and Windows."""
    length = valid_wav(source)
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        frame_width = reader.getnchannels() * reader.getsampwidth()
        frames = reader.readframes(min(
            int(reader.getframerate() * 90) + 1,
            Path(source).stat().st_size // frame_width + 1))
        with wave.open(str(destination), "wb") as writer:
            writer.setnchannels(params.nchannels)
            writer.setsampwidth(params.sampwidth)
            writer.setframerate(params.framerate)
            writer.writeframes(frames)
    return length


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
    received = folder / (ident + ".received.wav")
    if received.is_file():
        # Retry local WAV finalization only, without sending another paid request.
        fd, tempname = tempfile.mkstemp(prefix="speech-recovery-", suffix=".wav", dir=folder)
        os.close(fd)
        try:
            length = normalize_wav(received, tempname)
            os.replace(tempname, wav_path)
            received.unlink(missing_ok=True)
            metadata.write_text(json.dumps({
                "model": MODEL, "voice": request.voice, "style": request.style,
                "transcript": request.text, "duration_seconds": length,
                "ai_generated": True,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return wav_path, True
        finally:
            Path(tempname).unlink(missing_ok=True)
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
    # Save returned bytes durably before decoding: a successful paid request
    # must never be discarded because of a local WAV metadata/validation bug.
    received = folder / (ident + ".received.wav")
    with received.open("xb") as handle:
        handle.write(blob)
    fd, tempname = tempfile.mkstemp(prefix="speech-normalized-", suffix=".wav", dir=folder)
    os.close(fd)
    try:
        length = normalize_wav(received, tempname)
        os.replace(tempname, wav_path)
        received.unlink(missing_ok=True)
        # Store transcript and settings only; never persist the API key.
        metadata.write_text(json.dumps({
            "model": MODEL, "voice": request.voice, "style": request.style,
            "transcript": request.text, "duration_seconds": length,
            "ai_generated": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return wav_path, False
    except (ValueError, OSError) as exc:
        raise ValueError(
            f"Audio was received but could not be finalized: {exc}. "
            f"The paid response is preserved at {received}; do not retry.") from exc
    finally:
        Path(tempname).unlink(missing_ok=True)
