from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ui.app import choose_quick_edit_path


class QuickEditEntryTests(unittest.TestCase):
    def test_existing_latest_is_suggested_but_another_video_can_be_chosen(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'latest.mp4'
            path.write_bytes(b'video')
            selected = Path(folder) / 'another.mp4'
            selected.write_bytes(b'video')
            with patch('ui.app.filedialog.askopenfilename', return_value=str(selected)) as picker:
                self.assertEqual(choose_quick_edit_path(None, path, folder), selected)
                picker.assert_called_once()
                self.assertEqual(picker.call_args.kwargs['initialfile'], path.name)
                self.assertEqual(picker.call_args.kwargs['initialdir'], str(path.parent))

    def test_fresh_start_can_choose_existing_mp4(self):
        with TemporaryDirectory() as folder:
            selected = Path(folder) / 'older capture.mp4'
            selected.write_bytes(b'video')
            with patch('ui.app.filedialog.askopenfilename', return_value=str(selected)) as picker:
                self.assertEqual(choose_quick_edit_path(None, None, folder), selected)
                kwargs = picker.call_args.kwargs
                self.assertEqual(kwargs['initialdir'], str(folder))
                self.assertEqual(kwargs['title'], 'Choose a video to edit')

    def test_stale_latest_path_falls_back_to_picker_and_cancel_is_safe(self):
        with TemporaryDirectory() as folder:
            missing = Path(folder) / 'missing.mp4'
            with patch('ui.app.filedialog.askopenfilename', return_value=''):
                self.assertIsNone(choose_quick_edit_path(None, missing, folder))


if __name__ == '__main__':
    unittest.main()
