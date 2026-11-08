"""Tutorial-interception repair: simulated transport only, immutable old history."""
import copy,time,unittest
from unittest.mock import Mock,patch
from entry_journal import reserve_entry,finish_dispatch
from story_reopen import state_digest
from tutorial_entry_handoff import source_chain,open_handoff,enter_handoff
from test_map_layout import map_frame
from test_team_preparation import preparation,prepared_runner


def source():
    r=prepared_runner(preparation());key=r.ticket['key'];original=dict(r.ticket,cost=20,stamina_before=100,start_epoch=time.time()-100)
    row=reserve_entry(r.s,key,original);finish_dispatch(row,'sent')
    r.s['unresolved_entries']=[dict(entry=copy.deepcopy(original),reason='old-script UI interception')]
    r.s['active']=None;r.map_ticket=Mock(return_value=(dict(original,locked=False,clear_badge=False),[],'未通关蓝色当前节点'))
    p=dict(id='one-use',key=key,user_instruction='User says fix script interruptions and continue to chapter five',source_evidence_sha256={'fixture':'reviewed'},source_chain_sha256=state_digest(source_chain(r.s,key)),source_state_sha256=state_digest(r.s))
    return r,p


def pair(r,maker):
    a=maker();b=maker();b.at=time.time()-.01;a.at=b.at-.01;r.frame=b;return (a,b)


class TutorialEntryHandoffTests(unittest.TestCase):
    def test_slow_free_navigation_requires_same_hash_bound_mumu_lifetime_not_a_new_permit(self):
        import tempfile,json,hashlib
        from pathlib import Path
        for change in ('valid','pid','target','source','run','unsourced'):
            r,p=source();rec=open_handoff(r,p,pair(r,map_frame));r.action.reset_mock()
            rec['open_sent_at']-=121;r.run_id='run';r.cfg.update(backend='mumu_adb',serial='bound',package='game')
            r.adb=Mock(return_value=b'original-pid')
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'source.json';path.write_text(json.dumps(dict(request=dict(run_id='run',target=dict(client='mumu',serial='bound',package='game')))))
                rec.update(run_id='run',game_pid='original-pid',raw_size=[1600,900],source_snapshot=str(path),source_snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                if change=='pid':r.adb.return_value=b'new-pid'
                elif change=='target':r.cfg['serial']='another'
                elif change=='source':path.write_text('{}')
                elif change=='run':r.run_id='another-run'
                elif change=='unsourced':rec.pop('source_snapshot')
                frames=pair(r,preparation)
                if change=='valid':
                    enter_handoff(r,rec,(frames[-1],));self.assertEqual(rec['status'],'sent');r.action.assert_called_once()
                else:
                    with self.assertRaises(ValueError):enter_handoff(r,rec,(frames[-1],))
                    r.action.assert_not_called();self.assertEqual(rec['status'],'open_sent')

    def test_reviewed_handoff_uses_current_cycle_without_mandatory_double_ocr(self):
        r,p=source();f=map_frame();r.frame=f
        rec=open_handoff(r,p,(f,));f=preparation();r.frame=f
        enter_handoff(r,rec,(f,))
        self.assertEqual(rec['status'],'sent');self.assertEqual(r.action.call_count,2)

    def test_nullable_original_fields_cannot_be_dropped_from_the_archive(self):
        r,p=source();key=p['key'];r.s['attempted'][key]['optional']=None
        # First keep the dispatch hash consistent, so only the lost field fails.
        from entry_journal import attempt_digest
        dispatch=r.s['entry_dispatches'][key][0];dispatch['entry']=copy.deepcopy(r.s['attempted'][key]);dispatch['original_sha256']=attempt_digest(dispatch['entry'])
        with self.assertRaises(ValueError):source_chain(r.s,key)

    def test_archived_passive_entry_observation_is_preserved_not_an_automatic_permit(self):
        r,p=source();key=p['key'];archive=r.s['unresolved_entries'][0]['entry']
        archive['result_observation']=dict(run_id='original-run',diagnostics=[dict(code='entry_response',evidence='original.png')])
        chain=source_chain(r.s,key);self.assertEqual(chain['archives'][0]['entry'],archive)
        # The changed source still invalidates the old manifest until reviewed.
        with self.assertRaises(ValueError):open_handoff(r,p,pair(r,map_frame))
        r.action.assert_not_called()
        p.update(source_chain_sha256=state_digest(chain),source_state_sha256=state_digest(r.s))
        before=copy.deepcopy(r.s['unresolved_entries']);rec=open_handoff(r,p,pair(r,map_frame))
        self.assertEqual(rec['status'],'open_sent');self.assertEqual(r.s['unresolved_entries'],before)

    def test_result_or_unknown_extensions_and_terminal_still_reject_source(self):
        for change in ('battle','victory','unknown','wrong_diagnostic','empty_diagnostic','terminal'):
            r,p=source();a=r.s['unresolved_entries'][0]['entry']
            if change=='terminal':r.s['terminal']=True
            elif change=='wrong_diagnostic':a['result_observation']=dict(run_id='run',diagnostics=[dict(code='victory_missing')])
            elif change=='empty_diagnostic':a['result_observation']=dict(run_id='run',diagnostics=[])
            else:a[change+'_seen']=True
            with self.assertRaises(ValueError):source_chain(r.s,p['key'])
            r.action.assert_not_called()

    def test_reviewed_original_entry_uses_single_task_independently_of_preparation_auto(self):
        r,p=source();rec=open_handoff(r,p,pair(r,map_frame))
        from test_map_layout import frame
        def standard():
            f=preparation();f.words=[w for w in f.words if w['text']!='辅助英雄'];f.words.extend(frame([('AUTO',987,675)]).words)
            # Native green AUTO switch, not hosted/repeat play.
            f.image[652:697,910:1100]=(0,160,0)
            return f
        frames=pair(r,standard)
        enter_handoff(r,rec,frames)
        self.assertEqual(rec['status'],'sent');self.assertEqual(r.action.call_count,2)
        self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')

    def test_even_reviewed_handoff_cannot_click_entry_under_teaching_overlay(self):
        r,p=source();rec=open_handoff(r,p,pair(r,map_frame));r.action.reset_mock()
        from test_map_layout import frame
        frames=pair(r,preparation)
        for f in frames:f.words.extend(frame([('跳过教学',1452,42)]).words)
        with self.assertRaises(ValueError):enter_handoff(r,rec,frames)
        r.action.assert_not_called();self.assertEqual(rec['status'],'open_sent')

    def test_navigation_and_entry_are_independent_and_preserve_all_old_history(self):
        r,p=source();before=copy.deepcopy(r.s);snap=[];r.save.side_effect=lambda:snap.append(copy.deepcopy(r.s))
        rec=open_handoff(r,p,pair(r,map_frame))
        self.assertIsNone(r.s['active']);self.assertEqual(rec['status'],'open_sent')
        self.assertEqual(snap[0]['tutorial_entry_handoffs'][0]['status'],'reserved_open')
        enter_handoff(r,rec,pair(r,preparation))
        self.assertEqual(rec['status'],'sent');self.assertEqual(r.action.call_count,2)
        for key in ('attempted','entry_dispatches','unresolved_entries','completed'):self.assertEqual(r.s[key],before[key])
        self.assertEqual(r.s['active']['tutorial_handoff_id'],p['id'])
        with self.assertRaises(ValueError):enter_handoff(r,rec,pair(r,preparation))
        with self.assertRaises(ValueError):open_handoff(r,p,pair(r,map_frame))
        self.assertEqual(r.action.call_count,2)

    def test_missing_instruction_source_changed_history_or_existing_success_never_opens(self):
        for change in ('instruction','hash','source','sent','archive','completed','active'):
            r,p=source();key=p['key']
            if change=='instruction':p['user_instruction']=''
            elif change=='hash':p['source_state_sha256']='bad'
            elif change=='source':p['source_chain_sha256']='bad'
            elif change=='sent':r.s['entry_dispatches'][key][0]['status']='reserved'
            elif change=='archive':r.s['unresolved_entries'].append(copy.deepcopy(r.s['unresolved_entries'][0]))
            elif change=='completed':r.s['completed'][key]={}
            else:r.s['active']={'key':key}
            with self.assertRaises(ValueError):open_handoff(r,p,pair(r,map_frame))
            r.action.assert_not_called()

    def test_unknown_failure_no_send_and_disk_failure_remain_consumed(self):
        for where in ('open','entry'):
            for failure in ('send','save'):
                r,p=source()
                rec=None
                if where=='entry':rec=open_handoff(r,p,pair(r,map_frame));r.action.reset_mock()
                getattr(r,'action' if failure=='send' else 'save').side_effect=RuntimeError('unknown')
                with self.assertRaises(RuntimeError):
                    if where=='open':open_handoff(r,p,pair(r,map_frame))
                    else:enter_handoff(r,rec,pair(r,preparation))
                r.action.side_effect=None;r.save.side_effect=None;r.action.reset_mock()
                with self.assertRaises(ValueError):
                    if where=='open':open_handoff(r,p,pair(r,map_frame))
                    else:enter_handoff(r,rec,pair(r,preparation))
                r.action.assert_not_called()

    def test_selector_wrong_cost_stale_or_partial_page_never_enters(self):
        for change in ('selector','cost','stale','partial','one_frame'):
            r,p=source();rec=open_handoff(r,p,pair(r,map_frame));r.action.reset_mock();frames=pair(r,preparation)
            if change=='selector':
                for f in frames:f.words.extend(__import__('test_map_layout').frame([('等级',1320,117)]).words)
            elif change=='cost':
                for f in frames:f.find('20/100')['text']='21/100'
            elif change=='stale':frames[-1].at=time.time()-6
            elif change=='one_frame':frames=(frames[-1],frames[-1])
            else:
                for f in frames:f.words=[w for w in f.words if w['text']!='新关卡']
            with self.assertRaises(ValueError):enter_handoff(r,rec,frames)
            r.action.assert_not_called();self.assertEqual(rec['status'],'open_sent')

if __name__=='__main__':unittest.main()
