"""Opt-in, bounded search for openly licensed audio via the public Openverse API.

No scraping, browser automation, site challenges, or third-party API keys.
Licences are *indexed assertions*, not verified permissions.
"""
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen


API = "https://api.openverse.org/v1/audio/"
MAX_AUDIO_BYTES = 12 * 1024 * 1024
SUPPORTED_LICENCES = frozenset(("cc0", "pdm", "by"))
HOSTS = ("freesound.org", "wikimedia.org", "archive.org", "jamendo.com", "ccmixter.org")
SUFFIXES = (".mp3", ".wav")
USER_AGENT = "PulseCapture/0.2 (interactive Openverse audio search)"


def search_phrase(value):
    if type(value) is not str or not 2 <= len(value.strip()) <= 100:
        raise ValueError("Enter a sound phrase of 2–100 characters.")
    phrase = " ".join(value.split())
    if any(ord(char) < 32 for char in phrase):
        raise ValueError("Enter ordinary search text.")
    return phrase


def audio_url(value):
    """Restrict downloads to public HTTPS media hosts and audio extensions."""
    if type(value) is not str or len(value) > 2048:
        raise ValueError("Invalid audio URL.")
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username is not None or
            parsed.password is not None or parsed.port not in (None, 443) or
            not any(hostname == host or hostname.endswith("." + host) for host in HOSTS)):
        raise ValueError("Audio host not supported for in-app preview.")
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError("Only MP3/WAV previews are supported.")
    return suffix


def parse_results(data):
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Openverse returned an unexpected result.")
    results = []
    for item in data["results"][:30]:
        if not isinstance(item, dict):
            continue
        licence = str(item.get("license") or "").lower().strip()
        if licence not in SUPPORTED_LICENCES:
            continue
        media = item.get("url")
        try:
            suffix = audio_url(media)
        except (ValueError, TypeError):
            continue
        duration = item.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 20000:
            continue
        size = item.get("filesize")
        if isinstance(size, int) and size > MAX_AUDIO_BYTES:
            continue
        title = str(item.get("title") or "Unnamed reaction").strip()[:80]
        if not title:
            continue
        source = str(item.get("foreign_landing_url") or "")
        if not source.startswith("https://"):
            source = ""
        result = dict(id=str(item.get("id") or "")[:100], name=title,
                      creator=str(item.get("creator") or "Unknown")[:120],
                      license=licence.upper(), license_url=str(item.get("license_url") or "")[:1000],
                      source=source[:1000], audio=media, suffix=suffix,
                      attribution=str(item.get("attribution") or "")[:1600])
        if result["id"]:
            results.append(result)
    return results[:15]


def search_openverse(phrase, opener=urlopen):
    phrase = search_phrase(phrase)
    url = API + "?" + urlencode(dict(q=phrase, page_size=20, license_type="commercial"))
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with opener(request, timeout=12) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Openverse results were too large.")
    return parse_results(json.loads(raw))


class _RestrictedRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        audio_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_audio(result, destination, opener=None, cancelled=None):
    """Fetch just the manually selected preview; never prefetch search results."""
    url = result["audio"]
    suffix = audio_url(url)
    destination = Path(destination)
    if destination.suffix.lower() != suffix:
        raise ValueError("Audio destination extension must match.")
    if cancelled is not None and cancelled.is_set():
        raise ValueError("Audio request cancelled.")
    client = opener or build_opener(_RestrictedRedirect()).open
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "audio/*"})
    part = destination.with_name(destination.name + ".part")
    try:
        with client(request, timeout=15) as response:
            # Verify the destination even if a custom handler followed redirects.
            final = getattr(response, "url", url)
            audio_url(final)
            if response.headers.get("Content-Type", "").lower().startswith("text/"):
                raise ValueError("Source returned a page, not audio.")
            amount = response.headers.get("Content-Length")
            if amount and int(amount) > MAX_AUDIO_BYTES:
                raise ValueError("Preview exceeds 12 MB.")
            total = 0
            with part.open("wb") as stream:
                while True:
                    if cancelled is not None and cancelled.is_set():
                        raise ValueError("Audio request cancelled.")
                    chunk = response.read(min(65536, MAX_AUDIO_BYTES + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise ValueError("Preview exceeds 12 MB.")
                    stream.write(chunk)
        if not total:
            raise ValueError("Empty audio preview.")
        part.replace(destination)
        return destination
    finally:
        part.unlink(missing_ok=True)
