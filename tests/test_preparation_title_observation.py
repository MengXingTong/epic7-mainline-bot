"""Known preparation title gaps observe fresh frames, never latch or retry entry."""
import copy
import json
import sys
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from entry_journal import reserve_entry, finish_dispatch
from task_blockers import TaskAttention
from test_map_layout import frame, fake_runner
from test_team_preparation import preparation, prepared_runner


class PreparationTitleObservationTests(unittest.TestCase):
    def support(self, name='?'):
        f=frame([('准备战斗',148,42),('选择辅助英雄',500,125),
                 ('选择队伍',1357,831),('盼望路口',1215,120),
                 (name,1190,171),('无记录',1515,173)])
        r=prepared_runner(f)
        r.ticket.update(name='对峙',key='E4-C9-S7',episode=4,chapter=9,stage=7,phase='map')
        return r

    def step(self,r):
        r.stop=Mock(side_effect=AssertionError('Missing title must not latch/mark defeat'))
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-title-observation-test')):
            return r.step(r.frame)

    def title(self,r,text):
        word=next(w for w in r.frame.words if 1140<w['x']<1560 and 145<w['y']<195 and w['text']!='无记录')
        word['text']=text

    def test_support_loading_gap_then_current_title_progresses_without_resume(self):
        r=self.support();before=copy.deepcopy(r.s);ticket=copy.deepcopy(r.ticket)
        self.assertTrue(self.step(r)[0]);r.action.assert_not_called();r.back.assert_not_called()
        self.assertEqual(r.observation_wait['code'],'preparation_title')
        self.assertEqual(r.ticket,ticket);self.assertEqual(r.s['attempted'],before['attempted'])
        self.title(r,'对峙');self.assertTrue(self.step(r)[0])
        self.assertIsNone(r.observation_wait);self.assertEqual(r.ticket['phase'],'support')
        self.assertEqual(r.action.call_args.args[0],'选择当前队伍')
        self.assertEqual(r.s['attempted'],before['attempted']);self.assertEqual(r.s['completed'],{})
        self.assertNotIn('entry_dispatches',r.s)

    def test_team_gap_then_current_title_can_send_only_original_first_entry(self):
        r=prepared_runner(preparation());self.title(r,'?')
        stamp=r.ticket['verified_epoch']
        self.assertTrue(self.step(r)[0]);r.action.assert_not_called();r.back.assert_not_called()
        self.assertEqual(r.observation_wait['code'],'preparation_title')
        self.assertEqual(r.ticket['verified_epoch'],stamp);self.assertIsNone(r.s['active'])
        self.title(r,'新关卡');self.assertTrue(self.step(r)[0])
        self.assertEqual(r.s['active']['key'],'E1-C1-S2')
        self.assertEqual(len(r.s['entry_dispatches']['E1-C1-S2']),1)
        self.assertEqual(r.s['entry_dispatches']['E1-C1-S2'][0]['status'],'sent')
        r.action.reset_mock();self.step(r);r.action.assert_not_called()

    def test_missing_or_genuinely_different_title_never_authorizes_input(self):
        for scene in ('support','team'):
            for title in ('?', '', '完全不同关卡'):
                with self.subTest(scene=scene,title=title):
                    r=self.support() if scene=='support' else prepared_runner(preparation())
                    self.title(r,title);ticket=copy.deepcopy(r.ticket)
                    for _ in range(3):self.assertTrue(self.step(r)[0])
                    r.action.assert_not_called();r.back.assert_not_called();r.stop.assert_not_called()
                    self.assertEqual(r.ticket,ticket);self.assertEqual(r.s['completed'],{})
                    self.assertNotIn('entry_dispatches',r.s);self.assertFalse(r.s.get('terminal'))
                    self.assertNotIn('attention',r.s);self.assertNotIn('stage_outcomes',r.s)

    def test_expired_or_missing_map_proof_returns_for_reverification_without_entry(self):
        for scene in ('support','team'):
            for mode in ('expired','missing','phase'):
                with self.subTest(scene=scene,mode=mode):
                    r=self.support('对峙') if scene=='support' else prepared_runner(preparation())
                    if mode=='expired':r.ticket['verified_epoch']=time.time()-121
                    elif mode=='missing':r.ticket=None
                    else:r.ticket['phase']='unverified'
                    self.assertTrue(self.step(r)[0]);r.action.assert_not_called()
                    r.back.assert_called_once();self.assertIsNone(r.ticket)
                    self.assertNotIn('entry_dispatches',r.s)

    def test_existing_active_entry_is_observed_not_resent_after_title_recovers(self):
        r=prepared_runner(preparation());key=r.ticket['key'];entry=dict(r.ticket,start_epoch=1.)
        dispatch=reserve_entry(r.s,key,entry);finish_dispatch(dispatch,'sent');r.s['active']=entry
        before=copy.deepcopy(r.s)
        for title in ('?','新关卡'):
            self.title(r,title);self.step(r)
        r.action.assert_not_called();r.back.assert_not_called()
        self.assertEqual(r.s['attempted'],before['attempted'])
        self.assertEqual(r.s['entry_dispatches'],before['entry_dispatches'])
        self.assertEqual(r.s['completed'],{})

    def test_resource_guard_still_preempts_missing_title(self):
        r=self.support();r.frame.words.extend(frame([('行动力不足',800,400)]).words)
        with patch('runner.classify',return_value='resource_stop'):
            with self.assertRaises(TaskAttention) as caught:self.step(r)
        self.assertEqual(caught.exception.code,'resource');r.action.assert_not_called();r.back.assert_not_called()

    def test_observation_evidence_persistence_failure_propagates_before_input(self):
        r=self.support();r.save.side_effect=OSError('disk full')
        with self.assertRaises(OSError):self.step(r)
        r.action.assert_not_called();r.back.assert_not_called()

    def test_saved_stall_frame_does_not_authorize_input_and_fresh_frame_matches(self):
        root=Path(__file__).resolve().parents[1]
        old=new=root/'.local/support-title-stall-20261109'
        if not all((p/name).is_file() for p,name in ((old,'stalled.png'),(old,'stalled-ocr.json'),(new,'current.png'),(new,'current-ocr.json'))):
            self.skipTest('Private read-only stall frames are not distributed')
        def load(p,image,ocr):
            import numpy as np
            im=runner.cv2.imdecode(np.frombuffer((p/image).read_bytes(),np.uint8),runner.cv2.IMREAD_COLOR)
            data=json.loads((p/ocr).read_text(encoding='utf-8'))
            f=runner.Frame(im,[]);f.words=data['words'];f.text='\n'.join(w['text'] for w in f.words);f.clean=runner.norm(f.text)
            return f
        r=self.support();r.frame=load(old,'stalled.png','stalled-ocr.json')
        self.assertFalse(r.title_matches(r.frame))
        self.assertEqual(runner.classify(r.frame),'support');self.step(r);r.action.assert_not_called()
        r.frame=load(new,'current.png','current-ocr.json');self.assertTrue(r.title_matches(r.frame))
        self.step(r);self.assertEqual(r.action.call_args.args[0],'选择当前队伍')


if __name__=='__main__':unittest.main()
