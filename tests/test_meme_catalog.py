"""Offline tests for bounded in-app Openverse sound discovery and downloads."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from editor.meme_catalog import (
    MAX_AUDIO_BYTES, audio_url, fetch_audio, parse_results,
    search_openverse, search_phrase,
)


class FakeResponse:
    def __init__(self, body, url, headers=None):
        self.data = io.BytesIO(body)
        self.url = url
        self.headers = headers or {"Content-Type": "audio/mpeg"}
    def read(self, count=-1):
        return self.data.read(count)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.data.close()


def entry(license="cc0", url="https://cdn.freesound.org/previews/123/123.mp3", **extra):
    value = dict(id="sounds-123", title="Aw hell nah!", creator="Test Creator",
                 license=license, license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                 foreign_landing_url="https://freesound.org/people/test/sounds/123/",
                 url=url, duration=1800, filesize=1234,
                 attribution="Test Creator - CC0")
    value.update(extra)
    return value


class MemeCatalogTests(unittest.TestCase):
    def test_search_is_manual_bounded_and_encoded(self):
        seen = []
        def stub(request, timeout):
            seen.append((request.full_url, timeout))
            return FakeResponse(json.dumps({"results": [entry()]}).encode(), request.full_url)
        result = search_openverse("AW HELL NAH & nope", opener=stub)
        self.assertEqual(result[0]["name"], "Aw hell nah!")
        self.assertEqual(parse_qs(urlsplit(seen[0][0]).query)["q"], ["AW HELL NAH & nope"])
        self.assertEqual(parse_qs(urlsplit(seen[0][0]).query)["license_type"], ["commercial"])
        self.assertEqual(seen[0][1], 12)
        for bad in ("", "x", "z" * 101, None):
            with self.assertRaises(ValueError):
                search_phrase(bad)

    def test_results_reject_noncommercial_oversize_untrusted_and_long_clips(self):
        data = {"results": [
            entry(),
            entry(id="by", license="by", title="Funny scream"),
            entry(id="music", license="by-nc"),
            entry(id="web", url="https://internal.example/clip.mp3"),
            entry(id="long", duration=24000),
            entry(id="huge", filesize=MAX_AUDIO_BYTES + 1),
            entry(id="wrong", url="https://freesound.org/player.html"),
        ]}
        results = parse_results(data)
        self.assertEqual([x["id"] for x in results], ["sounds-123", "by"])
        self.assertEqual(results[0]["license"], "CC0")
        self.assertEqual(results[1]["license"], "BY")
        with self.assertRaises(ValueError):
            parse_results({"results": {}})

    def test_remote_audio_host_is_constrained(self):
        for valid in ("https://cdn.freesound.org/sound.mp3",
                      "https://upload.wikimedia.org/example.wav",
                      "https://ia801.us.archive.org/sfx.mp3"):
            self.assertIn(audio_url(valid), (".mp3", ".wav"))
        for invalid in ("http://cdn.freesound.org/sound.mp3",
                        "https://example.com/sound.mp3",
                        "https://freesound.org.evil.invalid/sound.mp3",
                        "https://127.0.0.1/sound.mp3",
                        "file:///C:/private.mp3",
                        "https://cdn.freesound.org/video.html",
                        "https://example.com@127.0.0.1/sound.mp3",
                        "https://cdn.freesound.org:8080/sound.mp3"):
            with self.assertRaises(ValueError, msg=invalid):
                audio_url(invalid)

    def test_download_only_selected_media_and_uses_temp_atomic_replace(self):
        item = parse_results({"results": [entry()]})[0]
        seen = []
        def stub(request, timeout):
            seen.append(request.full_url)
            return FakeResponse(b"synthetic mp3 fixture", item["audio"],
                                {"Content-Type": "audio/mpeg",
                                 "Content-Length": "21"})
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "example.mp3"
            fetch_audio(item, path, opener=stub)
            self.assertEqual(path.read_bytes(), b"synthetic mp3 fixture")
            self.assertEqual(seen, [item["audio"]])
            self.assertFalse((Path(root) / "example.mp3.part").exists())

    def test_large_responses_and_cancelled_requests_fail_closed(self):
        item = parse_results({"results": [entry()]})[0]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "test.mp3"
            with self.assertRaisesRegex(ValueError, "12 MB"):
                fetch_audio(item, path, opener=lambda *_args, **_kw:
                    FakeResponse(b"test", item["audio"],
                                 {"Content-Length": str(MAX_AUDIO_BYTES + 1)}))
            self.assertFalse(path.exists())
            self.assertFalse(path.with_name(path.name + ".part").exists())
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaisesRegex(ValueError, "cancelled"):
                fetch_audio(item, path, cancelled=cancelled)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
