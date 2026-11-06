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
