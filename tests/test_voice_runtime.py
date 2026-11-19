"""Install detection and integrity checks without downloads or model dependencies."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from editor.voice_conversion import (MODEL_REV, SOURCE_REV, REQUIRED_FILES,
                                     available, runtime_python, verify_runtime)


class RuntimeTests(unittest.TestCase):
    def fixture(self, root):
        python = runtime_python(root)
        python.parent.mkdir(parents=True)
        python.write_bytes(b'test executable placeholder')
        hashes = {}
        for name in REQUIRED_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
            hashes[name] = hashlib.sha256(b'fixture').hexdigest()
        manifest = {'source_revision':SOURCE_REV, 'model_revision':MODEL_REV, 'sha256':hashes}
        (root/'installed.json').write_text(json.dumps(manifest))
        return manifest

    def test_partial_corrupt_or_wrong_revision_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(available(root))
            manifest = self.fixture(root)
            self.assertTrue(available(root))
            verify_runtime(root)
            marker = root/'installed.json'
            marker.write_text('{broken')
            self.assertFalse(available(root))
            manifest['model_revision'] = 'wrong'
            marker.write_text(json.dumps(manifest))
            self.assertFalse(available(root))
            manifest['model_revision'] = MODEL_REV
            manifest['sha256'] = {}
            marker.write_text(json.dumps(manifest))
            self.assertFalse(available(root))

    def test_missing_and_changed_runtime_files_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            file = root/REQUIRED_FILES[0]
            file.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                verify_runtime(root)
            file.unlink()
            self.assertFalse(available(root))
            with self.assertRaisesRegex(ValueError, 'missing'):
                verify_runtime(root)


if __name__ == '__main__':
    unittest.main()
