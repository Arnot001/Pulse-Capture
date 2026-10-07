from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from capture.filenames import reserve


class FilenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.now = datetime(2026, 10, 7, 18, 12, 45)

    def test_expected_name(self):
        r = reserve(self.folder, self.now)
        self.assertEqual(r.final.name, 'PulseCapture_2026-10-07_181245.mp4')
        r.release()

    def test_parallel_sessions_never_share_paths(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: reserve(self.folder, self.now), range(20)))
        self.assertEqual(len({r.final for r in results}), 20)
        for r in results:
            r.release()

    def test_existing_files_and_partials_are_preserved(self):
        first = reserve(self.folder, self.now)
        first.partial.write_bytes(b'partial')
        first.release()
        second = reserve(self.folder, self.now)
        self.assertNotEqual(first.final, second.final)
        second.partial.write_bytes(b'video')
        second.publish()
        second.release()
        self.assertEqual(second.final.read_bytes(), b'video')
        self.assertEqual(first.partial.read_bytes(), b'partial')

    def test_publish_cannot_replace_a_racing_destination(self):
        r = reserve(self.folder, self.now)
        r.partial.write_bytes(b'new')
        r.final.write_bytes(b'existing')
        with self.assertRaises(OSError):
            r.publish()
        self.assertEqual(r.final.read_bytes(), b'existing')
        r.release()
