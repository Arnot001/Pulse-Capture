import copy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock

from editor.auto_ai import Pricing, build_request, request_plan
from editor.auto_analysis import local_plan, read_transcript
from editor.auto_plan import AutoOptions, editor_state, validate_plan
from editor.cuts import CutPlan, CutRange
from editor.models import MediaInfo, TrimRange
from editor.text_overlay import Caption, TextOverlay, TextResources, caption_intervals, text_filter
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command


def candidate(start=0, end=25):
    return {'title': 'A moving subject', 'description': 'Visible motion only.', 'rationale': 'A clear opening and continuous action.',
            'verification': [], 'shots': [{'start': start, 'end': end, 'focus_x': .3, 'focus_y': .5,
                                          'end_focus_x': .7, 'end_focus_y': .5}],
            'captions': [{'start': start, 'end': start+3, 'text': 'Follow the movement', 'basis': 'observed'}]}


class AutoPlanTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 120, 1280, 720, 30, True)
        self.options = AutoOptions()
        self.plan = {'shorts': [candidate(0, 25), candidate(40, 65), candidate(80, 105)]}

    def test_three_distinct_candidates_translate_to_existing_editor(self):
        validate_plan(self.plan, self.media, self.options)
        trim, cuts, edits = editor_state(self.plan['shorts'][0], self.media)
        self.assertEqual(trim, TrimRange(0, 25))
        self.assertEqual(cuts.kept_duration(trim), 25)
        self.assertEqual(edits.encoded_size(self.media), (1080, 1920))
        self.assertEqual(len(edits.crop_motion.keyframes), 2)
        self.assertTrue(edits.text.safe_area)
        self.assertNotEqual(edits.crop_motion.keyframes[0].x, edits.crop_motion.keyframes[-1].x)

    def test_rejects_unsafe_unstructured_or_impossible_plans(self):
        mutations = [lambda p: p.update(command='ffmpeg'),
                     lambda p: p['shorts'][0]['shots'][0].update(start=-1),
                     lambda p: p['shorts'][0]['shots'][0].update(end=200),
                     lambda p: p['shorts'][0]['shots'][0].update(end=10),
                     lambda p: p['shorts'][0]['shots'][0].update(focus_x=float('nan')),
                     lambda p: p['shorts'][0]['shots'][0].update(start=True),
                     lambda p: p['shorts'][0]['shots'][0].update(end_focus_y=2),
                     lambda p: p['shorts'][0]['captions'][0].update(end=60),
                     lambda p: p['shorts'][0]['captions'][0].update(basis='confirmed'),
                     lambda p: p['shorts'][0]['captions'][0].update(basis='verify'),
                     lambda p: p['shorts'].append(candidate(100, 120)),
                     lambda p: p['shorts'].__setitem__(1, candidate(0, 25))]
        for mutate in mutations:
            plan = copy.deepcopy(self.plan)
            mutate(plan)
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_plan(plan, self.media, self.options)

    def test_unverified_claims_do_not_render(self):
        short = candidate()
        short['captions'][0]['basis'] = 'verify'
        short['verification'] = ['Verify the source before making this claim.']
        validate_plan({'shorts': [short]}, self.media, self.options)
        _, _, edits = editor_state(short, self.media)
        self.assertEqual(edits.text.captions, ())

    def test_multishot_plan_keeps_source_time_and_audio_concat(self):
        short = candidate()
        short['shots'][0]['end'] = 10
        second = dict(short['shots'][0], start=30, end=45)
        short['shots'].append(second)
        validate_plan({'shorts': [short]}, self.media, self.options)
        trim, cuts, edits = editor_state(short, self.media)
        self.assertEqual(cuts.ranges, (CutRange(10, 30),))
        self.assertEqual(cuts.kept_duration(trim), 25)
        with TextResources(edits.text) as resources:
            cmd = build_export_command('ffmpeg', self.media, trim, 'output.mp4', edits, text_resources=resources, cuts=cuts)
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertIn('concat=n=2:v=1:a=1', graph)

    def test_local_scoring_retains_silent_visual_activity_and_diversity(self):
        samples = [{'time': i, 'motion': .4 if 40 <= i <= 70 else .1, 'scene': .3 if i % 20 == 0 else 0,
                    'brightness': .4, 'focus_x': .5, 'audio': 0} for i in range(120)]
        analysis = {'samples': samples, 'scenes': [20, 40, 60, 80, 100]}
        plan = local_plan(analysis, self.media, self.options)
        self.assertEqual(len(plan['shorts']), 3)
        validate_plan(plan, self.media, self.options)
        self.assertTrue(any(s['start'] < 70 and s['end'] > 40 for s in plan['shorts'][0]['shots']))

    def test_short_source_returns_clear_error_not_padded_or_repeated_footage(self):
        with self.assertRaisesRegex(ValueError, 'shorter'):
            local_plan({'samples': [], 'scenes': []}, replace(self.media, duration=10), self.options)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.media = MediaInfo(self.folder/'source.mp4', 120, 1280, 720, 30, True)
        self.options, self.pricing = AutoOptions(count=1), Pricing()
        self.cancel = threading.Event()
        (self.folder/'frame.jpg').write_bytes(b'\xff\xd8fixture')
        self.analysis = {'duration': 120, 'samples': [], 'scenes': [], 'frames': [{'time': 2, 'file': 'frame.jpg'}]}
        self.request, self.quote = build_request(self.analysis, self.folder, [], self.options, self.pricing)
        self.response = {'status': 'completed', 'usage': {'input_tokens': 2000, 'output_tokens': 1000},
                         'output': [{'type': 'message', 'content': [{'type': 'output_text',
                                      'text': json.dumps({'shorts': [candidate()]})}]}]}

    def call(self, sender, **kwargs):
        return request_plan(self.request, kwargs.get('quote', self.quote), kwargs.get('pricing', self.pricing),
                            self.media, self.options, [], self.folder/'job', self.cancel, 'test-key', sender=sender)

    def test_cost_reserves_images_output_and_text_and_records_actual_tokens(self):
        self.assertEqual(self.quote['image_tokens_upper'], 8192)
        self.assertGreater(self.quote['reserved_upper_gbp'], self.quote['estimated_gbp'])
        sender = Mock(return_value=self.response)
        plan, usage, cached = self.call(sender)
        self.assertFalse(cached)
        self.assertEqual(usage['measured_usage'], {'input_tokens': 2000, 'output_tokens': 1000})
        self.assertAlmostEqual(usage['measured_cost_gbp'], .0048)
        _, _, cached = self.call(sender)
        self.assertTrue(cached)
        self.assertEqual(sender.call_count, 1)
        self.assertNotIn('test-key', (self.folder/'job'/'usage.json').read_text())

    def test_insufficient_budget_makes_no_paid_request(self):
        sender = Mock()
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.call(sender, pricing=replace(self.pricing, budget_gbp=.001))
        sender.assert_not_called()

    def test_timeout_reservation_survives_restart_and_blocks_retries(self):
        sender = Mock(side_effect=TimeoutError('network'))
        with self.assertRaises(TimeoutError):
            self.call(sender)
        with self.assertRaisesRegex(ValueError, 'already made or reserved'):
            self.call(sender)
        self.assertEqual(sender.call_count, 1)
        ledger = json.loads((self.folder/'job'/'usage.json').read_text())
        self.assertIsNone(ledger['measured_cost_gbp'])
        self.assertGreater(ledger['reserved_gbp'], 0)

    def test_refusal_invalid_json_and_incomplete_results_record_charge(self):
        for response in ({'status': 'incomplete'}, {'status': 'completed', 'output': []},
                         {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]}):
            with TemporaryDirectory() as folder:
                response['usage'] = {'input_tokens': 123, 'output_tokens': 456}
                with self.assertRaises(ValueError):
                    request_plan(self.request, self.quote, self.pricing, self.media, self.options, [], folder,
                                 self.cancel, 'key', sender=Mock(return_value=response))
                ledger = json.loads((Path(folder)/'usage.json').read_text())
                self.assertGreater(ledger['measured_cost_gbp'], 0)

    def test_nan_negative_or_excessive_pricing_rejected(self):
        for kwargs in ({'budget_gbp': .51}, {'usd_to_gbp': float('nan')}, {'input_usd_per_million': 0},
                       {'image_tokens_upper': 200}, {'output_usd_per_million': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(self.pricing, **kwargs).validate()


class TimedCaptionTests(unittest.TestCase):
    def test_caption_timing_survives_trim_cuts_speed_and_preview(self):
        media = MediaInfo(Path('source.mp4'), 30, 1280, 720, 30, True)
        trim, cuts = TrimRange(5, 25), CutPlan((CutRange(10, 15),))
        cue = Caption(8, 18, "Literal [words] %{n}\nsecond line")
        self.assertEqual(caption_intervals(cue, trim, cuts), [(3, 5), (5, 8)])
        text = TextOverlay(captions=(cue,), safe_area=True)
        with TextResources(text) as resources:
            filters = text_filter(400, 700, text, resources, trim, cuts)
            self.assertIn('gte(t,3.000000000)*lt(t,5.000000000)', filters)
            self.assertNotIn(cue.text, filters)
            self.assertEqual(text_filter(400, 700, text, resources, trim, cuts, 20), 'null')
            self.assertIn('drawtext', text_filter(400, 700, text, resources, trim, cuts, 9))
            paths = resources.caption_paths[:]
        self.assertTrue(all(not p.exists() for p in paths))

    def test_srt_unicode_split_and_source_bounds(self):
        with TemporaryDirectory() as folder:
            source = Path(folder)/'source.mp4'
            source.with_suffix('.srt').write_text('1\n00:00:01,000 --> 00:00:04,000\nCafé and a moving subject.\n', encoding='utf-8')
            transcript, _ = read_transcript(source, 10)
            self.assertEqual(transcript[0]['text'], 'Café and a moving subject.')
            with self.assertRaises(ValueError):
                read_transcript(source, 2)
