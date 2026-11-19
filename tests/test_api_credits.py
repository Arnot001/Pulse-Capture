"""Credit reconciliation must not invent balances or count cached output twice."""
import json
from pathlib import Path
import tempfile
import unittest

from editor.api_credits import CreditCounter


class CreditCounterTests(unittest.TestCase):
    def test_unset_balance_is_not_reported_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(CreditCounter(tmp).summary()['remaining_estimate_usd'])

    def test_reconcile_then_count_new_gpt_usage_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter = CreditCounter(tmp)
            counter.reconcile(5)
            job = Path(tmp)/'auto-edit/jobs/test-job'
            job.mkdir(parents=True)
            (job/'usage.json').write_text(json.dumps({'status':'completed',
                'measured_usage':{'input_tokens':1000,'output_tokens':1000},
                'quote':{'pricing':{'input_usd_per_million':.75,'output_usd_per_million':4.5}}}))
            first = counter.summary()
            self.assertAlmostEqual(first['remaining_estimate_usd'], 5-.00525)
            self.assertEqual(first['requests_since_check'], 1)
            self.assertEqual(CreditCounter(tmp).summary(), first)
            counter.reconcile(4.99)
            self.assertEqual(counter.summary()['requests_since_check'], 0)
            self.assertEqual(counter.summary()['remaining_estimate_usd'], 4.99)

    def test_paid_speech_and_interrupted_charges_require_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter = CreditCounter(tmp)
            counter.reconcile(10)
            voices = Path(tmp)/'voiceovers'
            voices.mkdir()
            (voices/'test.attempt').write_text('One paid attempt')
            (voices/'converted-local.json').write_text('{}')
            result = counter.summary()
            self.assertIsNone(result['remaining_estimate_usd'])
            self.assertEqual(result['unpriced_requests'], 1)
            self.assertEqual(result['last_balance_usd'], 10)
            counter.reconcile(9.98)
            self.assertEqual(counter.summary()['remaining_estimate_usd'], 9.98)
            (voices/'test.wav').write_bytes(b'cached')
            self.assertEqual(counter.summary()['requests_since_check'], 0)

    def test_invalid_balance_and_corrupt_usage_never_claim_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter = CreditCounter(tmp)
            for amount in (-1, float('nan'), float('inf'), True):
                with self.assertRaises(ValueError):
                    counter.reconcile(amount)
            counter.reconcile(0)
            job = Path(tmp)/'auto-edit/jobs/broken'
            job.mkdir(parents=True)
            (job/'usage.json').write_text('{invalid')
            self.assertEqual(counter.summary()['unpriced_requests'], 1)
            self.assertIsNone(counter.summary()['remaining_estimate_usd'])


if __name__ == '__main__':
    unittest.main()
