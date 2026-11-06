"""Episode-map story-only nodes: positive controls, durable intent, no replay."""
import copy
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from pc_backend import TapNotSent
from task_blockers import TaskAttention


def frame(control='观看故事',stage=3):
    image=runner.np.full((900,1600,3),22,runner.np.uint8)
    color=tuple(map(int,runner.cv2.cvtColor(runner.np.uint8([[[95,220,220]]]),runner.cv2.COLOR_HSV2BGR)[0,0]))
    runner.cv2.circle(image,(68,292),50,color,6)
    words=[('Episode 4',156,44),('第4章 命运交错之处',188,137),
           (f'{stage}. 为了委托而委托',238,292),('4. 被扰乱的计划',192,416),(control,1391,827)]
    results=[([[x-45,y-12],[x+45,y-12],[x+45,y+12],[x-45,y+12]],text,.999) for text,x,y in words]
    return runner.Frame(image,results)


def fake_runner(f):
    r=runner.Runner.__new__(runner.Runner);r.frame=f;r.ticket=None;r.last_mode=None
    r.mode_since=time.time();r.battle_seen=0;r.last_gesture=0;r.unknown_gestures=0
    r.cfg={'start_policy':'current_screen','max_battle_seconds':1800}
    r.s={'completed':{},'attempted':{},'active':None,'victories':0}
    r.save=Mock();r.evidence=Mock(return_value='offline.png');r.action=Mock();r.back=Mock()
    return r


class StoryOnlyNodeTests(unittest.TestCase):
    def step(self,r):
        with patch.object(runner,'event'),patch.object(runner,'ROOT',Path('no-live-story-node-test')):
            return r.step(r.frame)

    def test_exact_story_control_is_a_mainline_map_but_generic_story_text_is_not(self):
        self.assertEqual(runner.classify(frame()),'map')
        self.assertEqual(runner.mainline_map_control(frame())['kind'],'story_only')
        self.assertEqual(runner.classify(frame('故事')),'unknown')
        self.assertEqual(runner.classify(frame('观看故事',stage=30)),'map')

    def test_attempt_and_active_are_saved_before_the_only_story_click(self):
        r=fake_runner(frame());snapshots=[]
        r.action.side_effect=lambda *a,**k:snapshots.append(copy.deepcopy(r.s))
        keep,_=self.step(r)
        self.assertTrue(keep);self.assertEqual(r.action.call_args.args[0],'观看故事（仅一次）')
        self.assertIn('E4-C4-S3',snapshots[0]['attempted'])
        self.assertEqual(snapshots[0]['active']['entry_kind'],'story_only')
        self.assertEqual(snapshots[0]['active']['cost'],0)
        self.assertEqual(snapshots[0]['active']['evidence'],'offline.png')
        self.assertEqual(r.s['entry_dispatches']['E4-C4-S3'][0]['status'],'sent')

    def test_existing_or_uncertain_story_attempt_is_never_replayed(self):
        r=fake_runner(frame());r.s['attempted']['E4-C4-S3']={'entry_kind':'story_only'}
        with self.assertRaises(TaskAttention) as caught:self.step(r)
        self.assertEqual(caught.exception.code,'current_stage_unresolved');r.action.assert_not_called()

    def test_explicit_not_sent_story_click_can_be_sent_once_after_continue(self):
        r=fake_runner(frame());r.action.side_effect=TapNotSent('zero button down')
        with self.assertRaises(TaskAttention) as caught:self.step(r)
        self.assertEqual(caught.exception.code,'entry_not_sent');self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['entry_dispatches']['E4-C4-S3'][0]['status'],'not_sent')
        original=copy.deepcopy(r.s['attempted']['E4-C4-S3'])
        r.action.side_effect=None;self.step(r)
        self.assertEqual(r.s['attempted']['E4-C4-S3'],original)
        self.assertEqual([x['status'] for x in r.s['entry_dispatches']['E4-C4-S3']],['not_sent','sent'])

    def test_returned_map_requires_the_original_story_node_clear_badge(self):
        r=fake_runner(frame('准备战斗'));r.s['attempted']['E4-C4-S3']={'entry_kind':'story_only'}
        r.s['active']={'key':'E4-C4-S3','episode':4,'chapter':4,'stage':3,
                       'entry_kind':'story_only','start_epoch':time.time()-30}
        target={'key':'E4-C4-S4','episode':4,'chapter':4,'stage':4,'name':'被扰乱的计划','verified_epoch':time.time()}
        rows=[{'stage':3,'completion':'cleared','locked':False},
              {'stage':4,'completion':'unconfirmed','locked':False,'lock_score':.2,'x':192,'y':416}]
        r.map_ticket=Mock(return_value=(target,rows,'未通关蓝色当前节点'))
        self.step(r)
        self.assertIn('E4-C4-S3',r.s['completed']);self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['completed']['E4-C4-S3']['proof'],'返回地图后，纯剧情节点出现绿色已通关勾')
        self.assertEqual(r.action.call_args.args[0],'未通关验证通过，准备战斗')

    def test_recent_battle_entry_transient_map_keeps_active_and_never_resends(self):
        r=fake_runner(frame('准备战斗'));d=r.map_ticket(r.frame)[0]
        r.s['active']={**d,'start_epoch':time.time(),'cost':8}
        r.s['attempted'][d['key']]=dict(r.s['active']);before=copy.deepcopy(r.s['active'])
        keep,_=self.step(r);self.assertTrue(keep)
        self.assertEqual(r.s['active'],before);r.action.assert_not_called();self.assertNotIn('unresolved_entries',r.s)
        r.s['active']['start_epoch']=time.time()-16;keep,_=self.step(r)
        self.assertFalse(keep);self.assertIsNotNone(r.s['active']);r.action.assert_not_called()

    def test_unchanged_map_after_sent_story_click_waits_then_requires_attention(self):
        r=fake_runner(frame());ticket=r.map_ticket(r.frame)[0]
        r.s['attempted'][ticket['key']]={'entry_kind':'story_only'}
        r.s['active']={**ticket,'entry_kind':'story_only','start_epoch':time.time()}
        self.step(r);r.action.assert_not_called()
        r.s['active']['start_epoch']=time.time()-21
        with self.assertRaises(TaskAttention) as caught:self.step(r)
        self.assertEqual(caught.exception.code,'story_result');r.action.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
