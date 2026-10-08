import ctypes
from unittest.mock import Mock, patch
import unittest
from capture.window_picker import list_windows, validate_window


@unittest.skipUnless(hasattr(ctypes, 'WINFUNCTYPE'), 'Windows enumeration contract')
class WindowPickerTests(unittest.TestCase):
    def test_minimized_apps_are_listed_and_desktop_shell_is_excluded(self):
        u = Mock()
        titles = {1: 'Browser', 2: 'Editor', 3: 'Program Manager', 4: 'Pulse'}
        u.IsWindowVisible.return_value = True
        u.IsIconic.side_effect = lambda hwnd: hwnd == 2
        u.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: setattr(pid._obj, 'value', 99 if hwnd == 4 else 10)
        u.GetWindowTextLengthW.side_effect = lambda hwnd: len(titles[hwnd])
        u.GetWindowTextW.side_effect = lambda hwnd, buf, size: setattr(buf, 'value', titles[hwnd])
        u.GetClassNameW.side_effect = lambda hwnd, buf, size: setattr(buf, 'value', 'Progman' if hwnd == 3 else 'AppWindow')
        u.EnumWindows.side_effect = lambda visit, _: [visit(hwnd, 0) for hwnd in titles]
        with patch('capture.window_picker.user32', return_value=u), patch('capture.window_picker.os.getpid', return_value=99):
            windows = list_windows()
        self.assertEqual([w.title for w in windows], ['Browser', 'Editor'])
        self.assertTrue(windows[1].minimized)

    def test_minimized_target_still_requires_restore(self):
        u = Mock()
        u.IsWindow.return_value = u.IsWindowVisible.return_value = u.IsIconic.return_value = True
        with patch('capture.window_picker.user32', return_value=u), self.assertRaisesRegex(ValueError, 'Restore'):
            validate_window(123)
