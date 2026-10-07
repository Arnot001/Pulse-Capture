import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from settings import Settings, load, save


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'prefs' / 'settings.json'

    def test_missing_defaults(self):
        self.assertEqual(load(self.path), Settings())

    def test_round_trip_and_unicode(self):
        value = Settings(fps=60, quality='High', mic_device='Mikrofon — USB', hotkey=True,
                         watermark=True, watermark_position='Top left')
        save(value, self.path)
        self.assertEqual(load(self.path), value)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_invalid_types_and_corruption(self):
        self.path.parent.mkdir()
        for raw in ('{', '[]', '{"fps": 120, "microphone": "yes", "quality": "Ultra"}',
                    '{"watermark": "yes", "watermark_position": "Center"}',
                    '{"version": 200}'):
            self.path.write_text(raw, encoding='utf-8')
            self.assertEqual(load(self.path), Settings())

    def test_unknown_fields_are_ignored(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({'fps': 60, 'unknown': 'value'}))
        self.assertEqual(load(self.path).fps, 60)
