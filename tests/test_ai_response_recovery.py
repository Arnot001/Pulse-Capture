"""Offline tests only: no API transmission, no keys, no extra paid attempts."""
import copy
import json
import unittest
from unittest.mock import Mock, patch
from editor.auto_ai import request_plan
from editor.auto_plan import recover_timestamp_rounding
from tests import test_auto_edit as fixture


class ResponseRecoveryTests(unittest.TestCase):
    setUp=fixture.BudgetTests.setUp
    call=fixture.BudgetTests.call

    def response_for(self, plan):
        response=copy.deepcopy(self.response)
        response['output'][0]['content'][0]['text']=json.dumps(plan)
        return response

    def test_rounding_is_bounded_revalidated_and_does_not_mutate_raw(self):
        short=fixture.candidate(0,10)
        short['shots'].append(dict(short['shots'][0],start=9.9995,end=25))
        plan=dict(shorts=[short]);original=copy.deepcopy(plan)
        fixed,changes=recover_timestamp_rounding(plan,self.media,self.options)
        self.assertEqual(plan,original)
        self.assertEqual(fixed['shorts'][0]['shots'][1]['start'],10)
        self.assertEqual(len(changes),1)
        short['shots'][1]['start']=9.9
        with self.assertRaises(ValueError):recover_timestamp_rounding(plan,self.media,self.options)
        short['shots'][1]['start']=0
        with self.assertRaises(ValueError):recover_timestamp_rounding(plan,self.media,self.options)

    def test_source_end_and_caption_boundary_rounding(self):
        short=fixture.candidate(95,120.0005)
        short['captions']=[dict(start=117,end=120.0005,text='A reaction',basis='observed')]
        fixed,changes=recover_timestamp_rounding(dict(shorts=[short]),self.media,self.options)
        self.assertEqual(fixed['shorts'][0]['shots'][0]['end'],120)
        self.assertEqual(fixed['shorts'][0]['captions'][0]['end'],120)
        self.assertEqual(len(changes),2)
        short['shots'][0]['end']=121
        with self.assertRaises(ValueError):recover_timestamp_rounding(dict(shorts=[short]),self.media,self.options)

    def test_rejected_raw_response_and_cost_survive_retry_without_sender(self):
        short=fixture.candidate(0,10)
        short['shots'].append(dict(short['shots'][0],start=9,end=25))
        response=self.response_for(dict(shorts=[short]));sender=Mock(return_value=response)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'Raw response saved'):self.call(sender)
        sender.assert_called_once()
        job=self.folder/'job'
        raw=json.loads((job/'ai-response.json').read_text(encoding='utf-8'))
        self.assertEqual(raw['response'],response)
        usage=json.loads((job/'usage.json').read_text(encoding='utf-8'))
        self.assertEqual(usage['status'],'validation_failed')
        self.assertGreater(usage['measured_cost_gbp'],0)
        self.assertTrue((job/'paid-request.lock').exists())

    def test_restart_recovers_preserved_response_without_key_or_second_charge(self):
        short=fixture.candidate(0,10)
        short['shots'].append(dict(short['shots'][0],start=9.9995,end=25))
        response=self.response_for(dict(shorts=[short]));sender=Mock(return_value=response)
        with patch('editor.auto_ai.recover_timestamp_rounding',side_effect=ValueError('Older validation rejected rounding')):
            with self.assertRaises(ValueError):self.call(sender)
        job=self.folder/'job';raw=(job/'ai-response.json').read_bytes();lock=(job/'paid-request.lock').read_bytes()
        plan,usage,cached=request_plan(self.request,self.quote,self.pricing,self.media,self.options,[],job,self.cancel,'',sender=sender)
        self.assertTrue(cached);sender.assert_called_once()
        self.assertEqual(plan['shorts'][0]['shots'][1]['start'],10)
        self.assertEqual(len(usage['timestamp_corrections']),1)
        self.assertEqual((job/'ai-response.json').read_bytes(),raw)
        self.assertEqual((job/'paid-request.lock').read_bytes(),lock)

    def test_nan_and_repaired_but_too_short_remain_rejected(self):
        plan=dict(shorts=[fixture.candidate(0,19.998)])
        plan['shorts'][0]['shots'][0]['start']=-.0005
        with self.assertRaises(ValueError):recover_timestamp_rounding(plan,self.media,self.options)
        plan['shorts'][0]['shots'][0]['start']=float('nan')
        with self.assertRaises(ValueError):recover_timestamp_rounding(plan,self.media,self.options)


if __name__=='__main__':unittest.main()
