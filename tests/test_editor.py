from concurrent.futures import ThreadPoolExecutor
import io
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from capture.ffmpeg_backend import Backend
from editor.models import MediaInfo, TrimRange, parse_time, format_time
from editor.ffmpeg_export import build_export_command
from editor.filenames import reserve_export
from editor.preview import preview_command
from editor.export_job import ExportJob


class EditorModelTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('recording.mp4'), 120, 1920, 1080, 30, True)

    def test_time_inputs(self):
        for text, value in [('3.250', 3.25), ('1:03.125', 63.125), ('1:02:03', 3723), (' 0 ', 0)]:
            with self.subTest(text=text):
                self.assertEqual(parse_time(text), value)
        self.assertEqual(parse_time(format_time(3723.125)), 3723.125)

    def test_invalid_time_inputs(self):
        for text in ('', '-1', 'NaN', 'inf', '1:60', '0:99:00', '1.5:02', '1:2:3:4', 'test'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_time(text)

    def test_invalid_trim_ranges(self):
        for trim in (TrimRange(-1, 5), TrimRange(3, 3), TrimRange(5, 3), TrimRange(0, 121),
                     TrimRange(math.nan, 5), TrimRange(0, math.inf), TrimRange(0, .001)):
            with self.subTest(trim=trim), self.assertRaises(ValueError):
                trim.validate(self.media)

    def test_full_length_and_one_frame_valid(self):
        TrimRange(0, 120).validate(self.media)
        TrimRange(1, 1 + 1/30).validate(self.media)
        self.assertEqual(TrimRange(2.5, 6).duration, 3.5)

    def test_command_reencodes_exact_trim_and_retains_audio(self):
        command = build_export_command('ffmpeg', self.media, TrimRange(2.5, 7), 'new.mp4')
        self.assertLess(command.index('-ss'), command.index('-i'))
        self.assertEqual(command[command.index('-ss')+1], '2.500000')
        self.assertEqual(command[command.index('-t')+1], '4.500000')
        self.assertIn('0:a:0', command)
        self.assertIn('libx264', command)
        self.assertNotIn('copy', command)
        self.assertIn('-n', command)
        self.assertNotIn('-y', command)

    def test_silent_input_does_not_invent_audio(self):
        media = MediaInfo(Path('silent.mp4'), 5, 801, 601, 30, False)
        command = build_export_command('ffmpeg', media, TrimRange(0, 2), 'edit.mp4')
        self.assertIn('-an', command)
        self.assertNotIn('0:a:0', command)
        self.assertIn('pad=ceil(iw/2)*2:ceil(ih/2)*2', command)

    def test_source_cannot_be_output(self):
        with self.assertRaises(ValueError):
            build_export_command('ffmpeg', self.media, TrimRange(0, 1), self.media.path)

    def test_paths_remain_single_arguments(self):
        media = MediaInfo(Path('Folder with spaces/演示 & clip.mp4'), 5, 640, 360, 30, False)
        command = build_export_command('ffmpeg', media, TrimRange(0, 2), 'output name.mp4')
        self.assertEqual(command[command.index('-i')+1], str(media.path))
        self.assertEqual(command[-1], 'output name.mp4')

    def test_preview_seeks_before_eof_and_has_bounded_dimensions(self):
        command = preview_command('ffmpeg', self.media, 120, 8000, 8000)
        self.assertLess(float(command[command.index('-ss')+1]), 120)
        self.assertIn('scale=1280:720:force_original_aspect_ratio=decrease,setsar=1', command)
        self.assertIn('ppm', command)


class ExportFilenameTests(unittest.TestCase):
    def test_original_and_existing_exports_are_preserved(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'recording.mp4'
            source.write_bytes(b'original')
            a = reserve_export(source)
            a.partial.write_bytes(b'edit')
            a.publish()
            a.release()
            b = reserve_export(source)
            self.assertNotEqual(a.final, b.final)
            self.assertEqual(source.read_bytes(), b'original')
            self.assertEqual(a.final.read_bytes(), b'edit')
            b.release()

    def test_concurrent_reservations_are_unique(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'recording.mp4'
            with ThreadPoolExecutor(max_workers=6) as pool:
                paths = list(pool.map(lambda _: reserve_export(source), range(12)))
            self.assertEqual(len({p.final for p in paths}), 12)
            for path in paths:
                path.release()


class ExportProcess:
    def __init__(self, command, exit_code=0, hold=False, **kwargs):
        Path(command[-1]).write_bytes(b'fake video')
        self.returncode = None if hold else exit_code
        self.stdout = io.StringIO('out_time_us=1000000\nprogress=end\n')
        self.stderr = io.StringIO('export failed' if exit_code else '')
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    kill = terminate

    def wait(self, timeout=None):
        return self.returncode


class ExportJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        source = self.folder / 'source.mp4'
        source.write_bytes(b'original')
        self.media = MediaInfo(source, 5, 640, 360, 30, True)
        self.trim = TrimRange(1, 3)
        self.backend = Backend('ffmpeg', 'ffprobe', True)

    def job(self, **kwargs):
        return ExportJob(self.backend, popen=kwargs.get('popen', ExportProcess),
                         validator=kwargs.get('validator', lambda *args: {'format': {'duration': '2'}}))

    def result(self, job):
        self.assertTrue(job.wait(4))
        events = []
        while not job.events.empty():
            events.append(job.events.get())
        return events[-1]

    def test_only_validated_export_is_published(self):
        job = self.job()
        job.start(self.media, self.trim)
        result = self.result(job)
        self.assertEqual(result.kind, 'saved')
        self.assertTrue(result.path.is_file())
        self.assertEqual(self.media.path.read_bytes(), b'original')
        self.assertFalse(list(self.folder.glob('*.lock')))

    def test_nonzero_exit_is_not_saved(self):
        job = self.job(popen=lambda c, **k: ExportProcess(c, exit_code=1, **k))
        job.start(self.media, self.trim)
        self.assertEqual(self.result(job).kind, 'error')
        self.assertEqual(list(self.folder.iterdir()), [self.media.path])

    def test_wrong_duration_is_not_saved(self):
        job = self.job(validator=lambda *a: {'format': {'duration': '5'}})
        job.start(self.media, self.trim)
        self.assertEqual(self.result(job).kind, 'error')

    def test_validation_error_is_not_saved(self):
        def invalid(*_):
            raise RuntimeError('Missing audio')
        job = self.job(validator=invalid)
        job.start(self.media, self.trim)
        self.assertEqual(self.result(job).kind, 'error')

    def test_cancel_terminates_child_and_cleans_own_files(self):
        children = []
        def hold(command, **kwargs):
            child = ExportProcess(command, hold=True, **kwargs)
            children.append(child)
            return child
        job = self.job(popen=hold)
        job.start(self.media, self.trim)
        deadline = time.monotonic()+2
        while not children and time.monotonic()<deadline:
            time.sleep(.01)
        with self.assertRaises(RuntimeError):
            job.start(self.media, self.trim)
        job.cancel()
        self.assertEqual(self.result(job).kind, 'cancelled')
        self.assertTrue(children[0].terminated)
        self.assertEqual(list(self.folder.iterdir()), [self.media.path])

    def test_launch_failure_cleans_reservation(self):
        def fail(*a, **k):
            raise FileNotFoundError('FFmpeg missing')
        job = self.job(popen=fail)
        job.start(self.media, self.trim)
        self.assertEqual(self.result(job).kind, 'error')
        self.assertEqual(list(self.folder.iterdir()), [self.media.path])
