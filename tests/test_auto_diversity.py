from dataclasses import replace
from pathlib import Path
import threading
import unittest

from editor.auto_analysis import AutoCancelled, local_plan
from editor.auto_plan import AutoOptions, editor_state, overlap_seconds, validate_plan
from editor.auto_selection import source_ranges
from editor.models import MediaInfo


def evidence(events=(15,55,95,135,175,215,255,295,335),width=13,duration=360,black=True):
    samples=[]
    for i in range(round(duration*2)):
        at=i/2
        event=next((n for n,a in enumerate(events) if a<=at<a+width),None)
        samples.append(dict(time=at,motion=.22+(event%3)*.035 if event is not None else .001,
                            scene=.35 if at in events else 0,brightness=.4 if event is not None else .01 if black else .2,
                            focus_x=.5,audio=0))
    return dict(step=.5,samples=samples,scenes=sorted(t for a in events for t in (a,a+width) if t<duration))


class AutoDiversityTests(unittest.TestCase):
    media=MediaInfo(Path('source.mp4'),360,640,360,30,False)

    def test_six_minutes_three_novel_mixed_candidates(self):
        for style in ('Gaming','News/Preview','Comedy / Roast'):
            options=AutoOptions(style=style,minimum=27,maximum=30)
            plan=local_plan(evidence(),self.media,options)
            self.assertEqual(len(plan['shorts']),3)
            for short in plan['shorts']:
                self.assertTrue(3<=len(short['shots'])<=6)
                self.assertGreater(short['shots'][-1]['start']-short['shots'][0]['start'],120)
                self.assertTrue(all(s['end']-s['start']>=3 for s in short['shots']))
                trim,cuts,_=editor_state(short,self.media,style=style)
                self.assertTrue(27<=cuts.kept_duration(trim)<=30)
                for shot in short['shots']:
                    self.assertTrue(any(a<=shot['start'] and shot['end']<=a+13 for a in (15,55,95,135,175,215,255,295,335)))
            for i,a in enumerate(plan['shorts']):
                for b in plan['shorts'][:i]:self.assertLess(overlap_seconds(a,b),3)
            validate_plan(plan,self.media,options)

    def test_quality_beats_coverage_and_single_scene_stays_continuous(self):
        plan=local_plan(evidence((145,),width=32,black=False),self.media,AutoOptions())
        self.assertEqual(len(plan['shorts']),1)
        self.assertEqual(len(plan['shorts'][0]['shots']),1)
        self.assertIn('Continuous edit',plan['shorts'][0]['rationale'])
        shot=plan['shorts'][0]['shots'][0]
        self.assertGreaterEqual(shot['start'],144)
        self.assertLessEqual(shot['end'],178)

    def test_exact_duration_short_source_and_no_padding(self):
        media=replace(self.media,duration=8)
        plan=local_plan(evidence((0,),width=8,duration=8),media,AutoOptions(minimum=8,maximum=8))
        self.assertEqual(len(plan['shorts']),1)
        self.assertEqual(sum(s['end']-s['start'] for s in plan['shorts'][0]['shots']),8)
        with self.assertRaisesRegex(ValueError,'shorter'):
            local_plan(evidence(),media,AutoOptions())
        with self.assertRaisesRegex(ValueError,'suitable'):
            local_plan(evidence((),black=True),self.media,AutoOptions())

    def test_old_cached_samples_transcript_and_cancel(self):
        analysis=evidence();analysis.pop('step')
        transcript=[dict(start=a,end=a+9.5,text='A complete informative speech phrase.') for a in (15,55,95,135,175,215,255,295,335)]
        plan=local_plan(analysis,self.media,AutoOptions(),transcript)
        self.assertEqual(plan,local_plan(analysis,self.media,AutoOptions(),transcript))
        _,_,edits=editor_state(plan['shorts'][0],self.media,transcript,style='News/Preview')
        self.assertTrue(edits.text.captions)
        cancel=threading.Event();cancel.set()
        with self.assertRaises(AutoCancelled):local_plan(analysis,self.media,AutoOptions(),cancel=cancel)

    def test_source_card_ranges_merge_adjacent_crop_spans(self):
        self.assertEqual(source_ranges([dict(start=25,end=29),dict(start=29,end=32),dict(start=130,end=137),dict(start=275,end=282)]),
                         '0:25–0:32 + 2:10–2:17 + 4:35–4:42')


if __name__=='__main__':unittest.main()
