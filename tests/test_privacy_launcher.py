"""Privacy integration is independent of Capture recorder and editor."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from capture import privacy_launcher as privacy


class PrivacyLauncherTests(unittest.TestCase):
    def test_uses_bundled_assets_location(self):
        with TemporaryDirectory() as directory, patch.object(privacy, 'asset_root', return_value=Path(directory)):
            self.assertEqual(privacy.privacy_script_path(),
                             Path(directory) / 'assets' / 'privacy' / 'Pulse-Privacy-Screen.ps1')

    def test_reuses_open_privacy_process(self):
        existing = Mock()
        existing.poll.return_value = None
        with patch.object(privacy.sys, 'platform', 'win32'), patch.object(privacy.subprocess, 'Popen') as popen:
            process, started = privacy.launch_privacy_screen(existing)
        self.assertIs(process, existing)
        self.assertFalse(started)
        popen.assert_not_called()

    def test_missing_script_fails_without_spawning(self):
        with TemporaryDirectory() as directory, patch.object(privacy.sys, 'platform', 'win32'), \
             patch.object(privacy, 'privacy_script_path', return_value=Path(directory) / 'missing.ps1'), \
             patch.object(privacy.subprocess, 'Popen') as popen:
            with self.assertRaises(FileNotFoundError):
                privacy.launch_privacy_screen()
        popen.assert_not_called()

    def test_launch_does_not_wait_or_modify_capture_state(self):
        with TemporaryDirectory() as directory:
            script = Path(directory) / 'Pulse-Privacy-Screen.ps1'
            script.write_text('# test', encoding='utf-8')
            executable = Path(directory) / 'powershell.exe'
            fake = Mock()
            with patch.object(privacy.sys, 'platform', 'win32'), \
                 patch.object(privacy, 'privacy_script_path', return_value=script), \
                 patch.object(privacy, 'find_powershell', return_value=executable), \
                 patch.object(privacy.subprocess, 'Popen', return_value=fake) as popen:
                process, started = privacy.launch_privacy_screen()
            self.assertIs(process, fake)
            self.assertTrue(started)
            args, kw = popen.call_args
            self.assertEqual(args[0][-2:], ['-File', str(script)])
            self.assertIn('-STA', args[0])
            self.assertEqual(kw['cwd'], str(script.parent))

    def test_unsupported_platform_is_rejected(self):
        with patch.object(privacy.sys, 'platform', 'linux'):
            with self.assertRaises(RuntimeError):
                privacy.launch_privacy_screen()


if __name__ == '__main__':
    unittest.main()