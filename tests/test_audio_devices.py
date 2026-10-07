import unittest
from capture.audio_devices import parse_devices, classify


class AudioTests(unittest.TestCase):
    def test_modern_output_and_aliases(self):
        log = '''[dshow @ 1] "Camera" (video)
[dshow @ 1]   Alternative name "camera-alias"
[dshow @ 1] "Microphone (USB)" (audio)
[dshow @ 1]   Alternative name "mic-alias"
[dshow @ 1] "Stereo Mix (Realtek)" (audio)
[dshow @ 1]   Alternative name "mix-alias"'''
        devices = parse_devices(log)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].identifier, 'mic-alias')
        self.assertEqual(devices[1].kind, 'loopback')

    def test_legacy_output(self):
        log = '''[dshow @ x] DirectShow video devices
[dshow @ x] "Camera"
[dshow @ x] DirectShow audio devices
[dshow @ x] "Mic"
[dshow @ x] Alternative name "unique"'''
        self.assertEqual(parse_devices(log)[0].identifier, 'unique')
        self.assertEqual(len(parse_devices(log)), 1)

    def test_unknown_inputs_are_not_faked_loopback(self):
        self.assertEqual(classify('Speakers (Realtek)'), 'input')
        self.assertEqual(classify('CABLE Output'), 'input')
        self.assertEqual(parse_devices('Error opening input dummy'), ())

    def test_duplicate_names_keep_distinct_aliases(self):
        devices = parse_devices('[dshow @ x] "Mic" (audio)\n[dshow @ x] Alternative name "one"\n'
                                '[dshow @ x] "Mic" (audio)\n[dshow @ x] Alternative name "two"')
        self.assertEqual(len(devices), 2)
