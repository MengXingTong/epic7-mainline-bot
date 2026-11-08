"""Underfilled-team confirmation belongs to the original entry, never a retry."""
import copy,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from abyss_core import Observation
from arena_core import Reading,classify
from arena_journal import ArenaJournal
from task_blockers import TaskAttention
import test_arena_progression as p


def warning():
    rows=[('新手竞技场',.10,.05),('未配置英雄',.50,.27),('队伍内有未配置英雄的栏位。',.50,.43),
          ('确定要用这个队伍开始战斗吗？',.50,.46),('点击不再显示按钮，今日内将不再显示弹窗，',.50,.575),
          ('并开始战斗。',.50,.61),('取消',.33,.74),('确认',.50,.74),('不再显示',.667,.74)]
    return Observation(1600,900,[p.token(t,x,y) for t,x,y in rows],visuals={'arena_team_warning_confirm'})


class ArenaTeamWarningTests(unittest.TestCase):
    def exercise(self,*args,**kwargs):return p.ArenaProgressionTests.exercise(self,*args,**kwargs)
    def test_all_text_controls_positions_confidence_and_native_confirm_required(self):
        self.assertEqual(classify(warning()).scene,'arena_team_warning')
        for index in range(len(warning().tokens)):
            for change in ('remove','weak','move'):
                o=warning()
                if change=='remove':o.tokens.pop(index)
                elif change=='weak':o.tokens[index]=replace(o.tokens[index],score=.979)
                else:o.tokens[index]=replace(o.tokens[index],y=o.tokens[index].y+120)
                self.assertNotEqual(classify(o).scene,'arena_team_warning',(index,change))
        o=warning();o.visuals.clear();self.assertNotEqual(classify(o).scene,'arena_team_warning')
    def test_unknown_text_duplicates_resource_and_defeat_keep_protection(self):
        for text in ('其他通知','确认','取消','不再显示','购买挑战书','战斗失败'):
            o=warning();o.tokens.append(p.token(text,.5,.5))
            if text in ('购买挑战书','战斗失败'):
                with self.assertRaises(TaskAttention):classify(o)
            else:self.assertNotEqual(classify(o).scene,'arena_team_warning')
    def test_first_warning_confirms_original_entry_without_another_attempt(self):
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),p.team(),warning(),p.battle(),p.result(),p.npc()])
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge','entry','entry_confirm','auto','result_close'])
        self.assertEqual(len(s['attempted']),1);self.assertEqual(len(s['entry_dispatches']),1)
        row=next(a for a in s['actions'] if a['kind']=='entry_confirm');entry=next(a for a in s['actions'] if a['kind']=='entry')
        self.assertEqual(row['key'],entry['key']);self.assertEqual(row['original_entry_action_id'],entry['id'])
        self.assertEqual(row['reading']['opponent'],'');self.assertEqual(row['original_opponent'],'NPC A')
        self.assertEqual(row['reading']['target']['text'],'确认');self.assertFalse(c.attentions)
        self.assertEqual(s['runs']['current-frame']['wins'],1)
    def test_repeated_warning_does_not_confirm_twice_or_count_acceptance_as_win(self):
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),p.team(),warning(),warning(),warning()])
        self.assertEqual(sum(k=='entry_confirm' for _,k,_ in tr.inputs),1)
        self.assertEqual(len(s['attempted']),1);self.assertFalse(s['completed']);self.assertIsNotNone(s['active'])
        self.assertTrue(any(k.get('mode')=='waiting_evidence' for a,k in c.statuses))
    def test_foreign_warning_without_original_entry_is_zero_input(self):
        tr,c,s,_=self.exercise([warning(),warning()]);self.assertFalse(tr.inputs);self.assertFalse(s['attempted'])
    def test_warning_after_battle_has_no_permission_to_start_again(self):
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),p.team(),p.battle(),warning()])
        self.assertFalse(any(k=='entry_confirm' for _,k,_ in tr.inputs));self.assertEqual(len(s['attempted']),1)
    def test_confirmation_not_sent_or_unknown_keeps_original_dispatch(self):
        for failure in ('entry_confirm','unknown_entry_confirm'):
            tr,c,s,_=self.exercise([p.npc(),p.npc(True),p.team(),warning(),warning()],fail_on=failure,
                expect_error=RuntimeError if failure.startswith('unknown') else None)
            self.assertEqual(sum(k=='entry_confirm' for _,k,_ in tr.inputs),1)
            self.assertEqual(next(iter(s['entry_dispatches'].values()))[0]['status'],'sent')
            self.assertEqual(s['actions'][-1]['status'],'unknown' if failure.startswith('unknown') else 'not_sent')
            self.assertFalse(s['completed'])
    def test_confirmation_intent_write_failure_sends_no_confirmation(self):
        original=ArenaJournal.intent
        def intent(j,kind,*args):
            if kind=='entry_confirm':raise OSError('cannot persist confirmation')
            return original(j,kind,*args)
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),p.team(),warning()],patches=[patch.object(ArenaJournal,'intent',intent)],expect_error=OSError)
        self.assertFalse(any(k=='entry_confirm' for _,k,_ in tr.inputs));self.assertEqual(len(s['attempted']),1)
    def test_journal_rejects_foreign_window_stale_frame_and_second_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',1);r=classify(p.team());ev=dict(captured_at=1)
            for kind in ('select','challenge','entry'):
                i=j.intent(kind,r,ev,'w');j.sent(i,'sent')
            r=classify(warning());before=copy.deepcopy(j.state)
            for at,bound in ((1,'w'),(2,'other')):
                with self.assertRaises(ValueError):j.intent('entry_confirm',r,dict(captured_at=at),bound)
            self.assertEqual(j.state,before)
            i=j.intent('entry_confirm',r,dict(captured_at=2),'w');j.sent(i,'sent')
            with self.assertRaises(ValueError):j.intent('entry_confirm',r,dict(captured_at=3),'w')
            self.assertEqual(len(j.state['attempted']),1)


class ArenaStoppedFreeNavigationTests(unittest.TestCase):
    def prepare(self,root):
        j=ArenaJournal(root,'current-frame',1);r=classify(p.npc(True));ev=dict(captured_at=1)
        for kind in ('select','challenge'):
            i=j.intent(kind,r,ev,'window');j.sent(i,'unknown' if kind=='challenge' else 'sent')
    def test_explicit_maintenance_reselects_without_changing_unknown_free_send(self):
        tr,c,s,_=p.ArenaProgressionTests.exercise(self,[p.npc(True),p.npc(True),p.team()],prepare=self.prepare,
            maintenance_source=dict(active_marker={},receipt='synthetic-source'))
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge','entry'])
        self.assertEqual(s['actions'][1]['status'],'unknown');self.assertEqual(s['actions'][2]['unknown_free_action_id'],s['actions'][1]['id'])
        self.assertEqual(len(s['attempted']),1);self.assertFalse(c.attentions)
    def test_legacy_expired_maintenance_reselection_is_preserved_then_replanned(self):
        def prepare(root):
            self.prepare(root);j=ArenaJournal(root,'current-frame',1)
            j.maintenance_source=dict(receipt='original-source');r=classify(p.npc(True))
            i=j.intent('select',r,dict(captured_at=2),'window');j.sent(i,'unknown')
        tr,c,s,_=p.ArenaProgressionTests.exercise(self,[p.npc(True),p.npc(True),p.team()],prepare=prepare,
            maintenance_source=dict(active_marker={},receipt='new-source'))
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge','entry'])
        self.assertEqual(s['actions'][1]['status'],'unknown');self.assertEqual(s['actions'][2]['status'],'unknown')
        self.assertEqual(s['actions'][3]['unknown_free_action_id'],s['actions'][2]['id'])
        self.assertEqual(len(s['attempted']),1)

    def test_new_known_lobby_navigation_does_not_reuse_old_selection(self):
        def prepare(root):
            self.prepare(root);j=ArenaJournal(root,'current-frame',1)
            r=Reading('arena_lobby',p.token('竞技场',.92,.54))
            i=j.intent('navigate',r,dict(captured_at=2),'window');j.sent(i,'sent')
        tr,c,s,_=p.ArenaProgressionTests.exercise(self,[p.npc(True),p.npc(True),p.team()],prepare=prepare)
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge','entry'])
        self.assertEqual(s['actions'][1]['status'],'unknown')
        self.assertEqual(s['actions'][3]['kind'],'select')

    def test_no_explicit_maintenance_does_not_automatically_reuse_unknown_send(self):
        tr,c,s,_=p.ArenaProgressionTests.exercise(self,[p.npc(True),p.npc(True)],prepare=self.prepare)
        self.assertFalse(tr.inputs);self.assertEqual(s['actions'][1]['status'],'unknown');self.assertFalse(s['attempted'])
    def test_maintenance_does_not_adopt_foreign_name_or_unknown_resource_entry(self):
        tr,c,s,_=p.ArenaProgressionTests.exercise(self,[p.npc(True,name='foreign')],prepare=self.prepare,
            maintenance_source=dict(active_marker={},receipt='synthetic-source'))
        self.assertFalse(tr.inputs);self.assertFalse(s['attempted'])

if __name__=='__main__':unittest.main()
