"""Auto Edit batch orchestration never overwrites or bypasses manual approval."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from editor.auto_plan import AutoSuggestion
from editor.auto_tools import AutoTools


class FakeWindow:
    def __init__(self):
        self.exporter = SimpleNamespace(busy=False)
        self.closing = False
        self.exports = 0
        self.pending = []
        self._last_callback = None

    def export(self):
        self.exports += 1
        self.exporter.busy = True

    def after(self, milliseconds, callback):
        self.pending.append(callback)


class AutoBatchTests(unittest.TestCase):
    def setUp(self):
        # Construct without Tk widgets to test the state machine headlessly.
        self.window = FakeWindow()
        self.auto = AutoTools.__new__(AutoTools)
        self.auto.window = self.window
        self.auto.suggestions = (
            AutoSuggestion(0, 28, .8, 'Scene and audio activity'),
            AutoSuggestion(50, 78, .6, 'Frequent visual changes'),
        )
        self.auto.busy = False
        self.auto._closed = False
        self.auto.batch = None
        self.auto.batch_ok = 0
        self.auto.message = MagicMock()
        self.auto.refresh = MagicMock()
        self.auto.apply = MagicMock(return_value=True)

    def test_decline_batch_makes_no_changes(self):
        with patch('editor.auto_tools.messagebox.askyesno', return_value=False):
            self.auto.export_all()
        self.assertIsNone(self.auto.batch)
        self.assertEqual(self.window.exports, 0)

    def test_approved_batch_waits_for_each_export(self):
        with patch('editor.auto_tools.messagebox.askyesno', return_value=True):
            self.auto.export_all()
        self.assertEqual(self.window.exports, 1)
        self.auto.apply.assert_called_with(0, confirm=False)
        self.assertEqual(self.auto.batch, [1])

        self.window.exporter.busy = False
        self.auto.export_completed(SimpleNamespace(kind='saved'))
        self.assertEqual(self.window.exports, 1)
        self.window.pending.pop(0)()
        self.assertEqual(self.window.exports, 2)
        self.auto.apply.assert_called_with(1, confirm=False)

        self.window.exporter.busy = False
        self.auto.export_completed(SimpleNamespace(kind='saved'))
        self.window.pending.pop(0)()
        self.assertEqual(self.auto.batch_ok, 2)
        self.assertIsNone(self.auto.batch)

    def test_failed_export_aborts_remaining_shorts(self):
        with patch('editor.auto_tools.messagebox.askyesno', return_value=True):
            self.auto.export_all()
        self.window.exporter.busy = False
        self.auto.export_completed(SimpleNamespace(kind='error', message='Encoder failed'))
        self.assertIsNone(self.auto.batch)
        self.assertEqual(self.window.exports, 1)


if __name__ == '__main__':
    unittest.main()
