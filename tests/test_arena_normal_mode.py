"""Free quick-to-normal arena mode recovery; synthetic observations and inputs."""
import copy
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw

from arena_core import classify
from arena_journal import ArenaJournal
from arena_vision import apply, normal_mode_toggle
from arena_worker import read_observation
from task_blockers import TaskAttention
import test_arena_progression as p


def quick(cost='1/12', name='NPC A'):
    o=p.team(cost, name)
    o.tokens=[t for t in o.tokens if t.text!='战斗开始']
    o.tokens.extend([p.token('快速对战',.66,.92),
        p.token('本日快速对战剩余次数',.43,.90),p.token('9/10',.43,.95)])
    o.visuals.add('arena_normal_mode_toggle')
    return o


def tile_image(rays=True):
    image=Image.new('RGB',(1600,900),(35,35,35));d=ImageDraw.Draw(image)
    x,y=1157,790
    d.rounded_rectangle((x,y,x+72,y+76),radius=7,fill=(250,250,250))
    d.polygon([(x+30,y+11),(x+45,y+11),(x+34,y+31),(x+45,y+31),
               (x+21,y+61),(x+28,y+40),(x+21,y+40)],fill=(15,15,15))
    if rays:
        for a,b,c,e in [(15,15,25,22),(47,16,55,24),(51,29,59,36),
                        (50,41,58,48),(44,53,52,60)]:
            d.rectangle((x+a,y+b,x+c,y+e),fill=(15,15,15))
    return image


class NormalModeRecognitionTests(unittest.TestCase):
    def test_quick_is_only_adjacent_free_mode_target(self):
        r=classify(quick())
        self.assertEqual((r.scene,r.cost,r.stock),('arena_quick_team',1,12))
        self.assertEqual(r.target.text,'切换普通战斗')
        self.assertEqual(r.target.source,'arena_normal_mode_toggle')
        self.assertGreater(r.target.center[0]/1600,.72)
        self.assertEqual(classify(p.team()).scene,'arena_team')

    def test_each_required_anchor_and_tile_is_mandatory(self):
        for label in ('新手竞技场','快速对战','NPC对战','NPC A','1/12',
                      '本日快速对战剩余次数','9/10'):
            with self.subTest(label=label):
                o=quick();o.tokens=[t for t in o.tokens if t.text!=label]
                self.assertEqual(classify(o).scene,'arena_unknown')
        o=quick();o.visuals.clear()
        self.assertEqual(classify(o).scene,'arena_unknown')

    def test_weak_moved_duplicate_controls_and_invalid_daily_counts_are_unknown(self):
        for label in ('快速对战','本日快速对战剩余次数','9/10','1/12'):
            for change in ('weak','moved','duplicate'):
                with self.subTest(label=label,change=change):
                    o=quick();t=next(t for t in o.tokens if t.text==label)
                    o.tokens.remove(t)
                    if change=='weak':o.tokens.append(p.token(label,t.center[0]/1600,t.center[1]/900,.979))
                    elif change=='moved':o.tokens.append(p.token(label,.5,.5))
                    else:o.tokens.extend([t,copy.deepcopy(t)])
                    self.assertEqual(classify(o).scene,'arena_unknown')
        for value in ('11/10','1/0','9','-1/10'):
            o=quick();o.tokens=[t for t in o.tokens if t.text!='9/10']+[p.token(value,.43,.95)]
            self.assertEqual(classify(o).scene,'arena_unknown')
        o=quick();o.tokens.append(p.token('战斗开始',.66,.92))
        self.assertEqual(classify(o).scene,'arena_unknown')

    def test_conflicting_weak_moved_or_duplicate_start_labels_do_not_authorize_either_mode(self):
        for label in ('战斗开始','快速对战'):
            for kind in ('weak','moved','duplicate'):
                o=quick() if label=='战斗开始' else p.team()
                if kind=='weak':o.tokens.append(p.token(label,.66,.92,.97))
                elif kind=='moved':o.tokens.append(p.token(label,.5,.5))
                else:o.tokens.extend([p.token(label,.66,.92),p.token(label,.66,.92)])
                self.assertEqual(classify(o).scene,'arena_unknown')

    def test_free_switch_does_not_require_quick_battle_daily_quota(self):
        o=quick();o.tokens=[t for t in o.tokens if t.text!='9/10']+[p.token('0/10',.43,.95)]
        self.assertEqual(classify(o).scene,'arena_quick_team')

    def test_unknown_modal_and_resource_defeat_priority_remain(self):
        for text in ('确认','取消','点击关闭'):
            o=quick();o.tokens.append(p.token(text,.5,.5))
            self.assertEqual(classify(o).scene,'arena_unknown')
        o=quick();o.visuals.add('arena_notice_modal')
        self.assertEqual(classify(o).scene,'arena_unknown')
        for text in ('购买挑战书','挑战书不足','复活','战斗失败'):
            o=quick();o.tokens.append(p.token(text,.5,.5))
            with self.assertRaises(TaskAttention):classify(o)
        for cost in ('2/12','1/0'):
            with self.assertRaises(TaskAttention):classify(quick(cost))

    def test_native_tile_shape_not_just_a_white_square(self):
        image=tile_image();self.assertTrue(normal_mode_toggle(image))
        self.assertIn('arena_normal_mode_toggle',apply(image,quick()).visuals)
        self.assertFalse(normal_mode_toggle(tile_image(False)))
        for color in ((250,250,250),(15,15,15),(180,180,180)):
            other=Image.new('RGB',(1600,900),(35,35,35));d=ImageDraw.Draw(other)
            d.rectangle((1157,790,1229,866),fill=color)
            self.assertFalse(normal_mode_toggle(other))
        other=Image.new('RGB',(1600,900));other.paste(image,(100,0))
        self.assertFalse(normal_mode_toggle(other))

    def test_weak_cost_uses_original_frame_fixed_field_without_lowering_threshold(self):
        o=quick();t=next(t for t in o.tokens if t.text=='1/12')
        o.tokens.remove(t);o.tokens.append(p.token('1/12',.58,.92,.91))
        base=[[[[t.x,t.y],[t.x+t.w,t.y],[t.x+t.w,t.y+t.h],[t.x,t.y+t.h]],t.text,t.score] for t in o.tokens]
        box=[[1,1],[10,1],[10,10],[1,10]]
        for second,score,ok in [('1/12',.999,True),('1/11',.999,False),('1/12',.979,False)]:
            ocr=Mock(side_effect=[(base,None),([[box,'1/12',.999]],None),([[box,second,score]],None)])
            obs=read_observation(tile_image(),ocr,1)
            self.assertEqual(next(t for t in obs.tokens if t.source=='ocr' and t.text=='1/12').score,.91)
            self.assertEqual(classify(obs).scene,'arena_quick_team' if ok else 'arena_unknown')


class NormalModeLedgerTests(unittest.TestCase):
    def test_switch_preserves_quota_and_cannot_be_an_entry_or_reused(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',9);r=classify(quick());e=dict(captured_at=1)
            before=copy.deepcopy(j.state)
            with self.assertRaises(ValueError):j.intent('entry',r,e,'w')
            ident=j.intent('normal_mode',r,e,'w');j.sent(ident,'sent')
            for key in ('attempted','entry_dispatches','completed','active','runs','last_cleared'):
                self.assertEqual(j.state[key],before[key])
            self.assertTrue(j.state['actions'][-1]['free_ui_only'])
            self.assertTrue(j.normal_mode_pending())
            self.assertFalse(j.normal_mode_context(r,'w'))
            with self.assertRaises(ValueError):j.intent('normal_mode',r,dict(captured_at=2),'w')
            self.assertIsNone(ArenaJournal(root,'r',9).normal_mode_context(r,'w'))

    def test_independent_normal_state_binds_original_frame_opponent_stock_and_window(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',9);r=classify(quick());e=dict(captured_at=1)
            i=j.intent('normal_mode',r,e,'w');j.sent(i,'sent')
            normal=classify(p.team())
            self.assertFalse(j.observe_normal_mode(normal,e,'w'))
            self.assertFalse(j.observe_normal_mode(normal,dict(captured_at=2),'other'))
            self.assertFalse(j.observe_normal_mode(classify(p.team(name='other')),dict(captured_at=2),'w'))
            self.assertFalse(j.observe_normal_mode(classify(p.team('1/11')),dict(captured_at=2),'w'))
            self.assertTrue(j.observe_normal_mode(normal,dict(captured_at=2),'w'))
            self.assertFalse(j.normal_mode_pending())
            self.assertFalse(j.observe_normal_mode(normal,dict(captured_at=3),'w'))
            self.assertTrue(j.return_to_npc_context(normal,'w',3))
            self.assertFalse(j.state['attempted']);self.assertEqual(j.run['wins'],0)

    def test_free_challenge_regeneration_during_mode_switch_does_not_latch_progress(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',9);r=classify(quick());e=dict(captured_at=1)
            i=j.intent('normal_mode',r,e,'w');j.sent(i,'sent')
            self.assertTrue(j.observe_normal_mode(classify(p.team('1/13')),dict(captured_at=2),'w'))
            self.assertFalse(j.normal_mode_pending());self.assertFalse(j.state['attempted'])

    def test_unsent_or_unknown_switch_does_not_claim_success(self):
        for status in ('not_sent','unknown'):
            with tempfile.TemporaryDirectory() as root:
                j=ArenaJournal(root,'r',9);r=classify(quick());e=dict(captured_at=1)
                i=j.intent('normal_mode',r,e,'w');j.sent(i,status)
                self.assertFalse(j.observe_normal_mode(classify(p.team()),dict(captured_at=2),'w'))
                self.assertTrue(j.normal_mode_pending())
                self.assertIsNone(j.return_to_npc_context(classify(p.team()),'w',2))

    def test_no_toggle_after_entry_or_pending_result_or_without_original_team_chain(self):
        for phase in ('entry','result','selection_only','wrong_name','wrong_window'):
            with tempfile.TemporaryDirectory() as root:
                j=ArenaJournal(root,'r',9);r=classify(p.team());e=dict(captured_at=1)
                for kind in ('select','challenge'):
                    i=j.intent(kind,r,e,'w');j.sent(i,'sent')
                    if phase=='selection_only':break
                if phase in ('entry','result'):
                    i=j.intent('entry',r,e,'w');j.sent(i,'sent')
                if phase=='result':j.battle(dict(captured_at=2),'w');j.complete(dict(captured_at=3),'w')
                q=classify(quick(name='other' if phase=='wrong_name' else 'NPC A'))
                self.assertIsNone(j.normal_mode_context(q,'other' if phase=='wrong_window' else 'w'))


class NormalModeWorkerTests(unittest.TestCase):
    def exercise(self,*args,**kwargs):return p.ArenaProgressionTests.exercise(self,*args,**kwargs)

    def test_current_screen_switch_observe_return_then_original_safe_selection(self):
        normal=p.team();normal.visuals.add('arena_native_back')
        tr,c,s,_=self.exercise([quick(),normal,p.npc(),p.npc(True),p.team(),p.battle(False),p.result(),p.npc()])
        self.assertEqual([k for _,k,_ in tr.inputs],['normal_mode','return_to_npc','select','challenge','entry','result_close'])
        self.assertNotIn('快速对战',[label for _,_,label in tr.inputs])
        self.assertEqual(s['runs']['current-frame']['wins'],1)
        self.assertEqual(len(s['attempted']),1);self.assertEqual(len(s['normal_mode_observations']),1)
        self.assertFalse(c.attentions);self.assertEqual(c.statuses[-1][1]['mode'],'done')

    def test_selected_chain_survives_mode_switch_and_only_normal_new_frame_enters(self):
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),quick(),quick(),p.team(),p.battle(False),p.result(),p.npc()])
        self.assertEqual([(i,k) for i,k,_ in tr.inputs],[(1,'select'),(2,'challenge'),(3,'normal_mode'),(5,'entry'),(7,'result_close')])
        self.assertEqual(s['runs']['current-frame']['wins'],1);self.assertFalse(c.attentions)

    def test_switch_message_is_not_acceptance_entry_or_win(self):
        tr,c,s,_=self.exercise([quick(),quick(),quick()])
        self.assertEqual([k for _,k,_ in tr.inputs],['normal_mode'])
        self.assertFalse(s['attempted']);self.assertFalse(s['completed'])
        self.assertEqual(s['runs']['current-frame']['wins'],0);self.assertFalse(s.get('normal_mode_observations'))

    def test_each_independently_completed_round_can_switch_without_resetting_quota(self):
        rows=[p.npc(),p.npc(True),quick(),p.team(),p.battle(False),p.result(),
              p.npc(),p.npc(True),quick(),p.team(),p.battle(False),p.result(),p.npc()]
        tr,c,s,_=self.exercise(rows,requested=2)
        kinds=[k for _,k,_ in tr.inputs]
        self.assertEqual(kinds.count('normal_mode'),2);self.assertEqual(kinds.count('entry'),2)
        self.assertEqual(s['runs']['current-frame']['requested'],2)
        self.assertEqual(s['runs']['current-frame']['wins'],2)
        self.assertEqual(len(s['attempted']),2);self.assertEqual(len(s['completed']),2)
        self.assertEqual(len(s['normal_mode_observations']),2);self.assertFalse(c.attentions)

    def test_expired_source_frame_does_not_reserve_or_send_mode_switch(self):
        tr,c,s,_=self.exercise([quick()],timestamps=[time.monotonic()-6])
        self.assertFalse(tr.inputs);self.assertFalse(s['actions']);self.assertFalse(s['attempted'])

    def test_send_failure_not_reused_or_counted(self):
        for status in ('not_sent','unknown'):
            tr,c,s,_=self.exercise([quick(),quick(),p.team()],
                fail_on='normal_mode' if status=='not_sent' else 'unknown_normal_mode',
                expect_error=RuntimeError if status=='unknown' else None)
            self.assertEqual([k for _,k,_ in tr.inputs],['normal_mode'])
            self.assertEqual(s['actions'][-1]['status'],status);self.assertFalse(s['attempted'])

    def test_intent_and_evidence_write_failures_send_nothing(self):
        for method in ('intent','evidence'):
            with self.subTest(method=method):
                tr,c,s,_=self.exercise([quick()],patches=[patch.object(ArenaJournal,method,side_effect=OSError('disk full'))],expect_error=OSError)
                self.assertFalse(tr.inputs);self.assertFalse(s['attempted'])

    def test_changed_opponent_or_stock_after_switch_does_not_enter_or_return(self):
        for normal in (p.team(name='other'),p.team('1/11')):
            normal.visuals.add('arena_native_back')
            tr,c,s,_=self.exercise([quick(),normal,normal])
            self.assertEqual([k for _,k,_ in tr.inputs],['normal_mode'])
            self.assertFalse(s['attempted']);self.assertFalse(s.get('normal_mode_observations'))


if __name__=='__main__':unittest.main()
