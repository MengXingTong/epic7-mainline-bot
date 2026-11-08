"""Native free AUTO, original entry binding, and one-field OCR; no OS inputs."""
import copy,time,unittest
from unittest.mock import Mock,patch
import runner
import battle_auto_control as auto
import battle_settings as settings
from entry_journal import reserve_entry,finish_dispatch
from test_map_layout import frame


def battle_frame():
    im=runner.np.full((900,1600,3),22,runner.np.uint8)
    im[20:59,1542:1549]=230;im[20:59,1560:1567]=230
    return frame([('×1/3',212,26),('100/100',420,859),('故事英雄',400,810)],im)


def off_frame():
    f=battle_frame();cv=runner.cv2;np=runner.np
    field=f.image[5:85,1360:1440]
    cv.polylines(field,[np.array([(27,35),(27,16),(64,16),(64,20),(35,20),(35,32)],np.int32)],False,(230,230,230),3)
    cv.polylines(field,[np.array([(33,48),(33,56),(70,56),(70,36),(66,36),(66,51),(40,51)],np.int32)],False,(230,230,230),3)
    cv.putText(field,'A',(43,44),cv.FONT_HERSHEY_SIMPLEX,.6,(230,230,230),2)
    return f


def target(f):return dict(text='A',score=.999,x=1408.,y=42.,box=[[1360,5],[1440,5],[1440,85],[1360,85]],source='current_battle_auto_field_read',captured_at=f.at)


def configured():
    r=Mock();r.run_id='run';r.frame=battle_frame();r.ocr=Mock()
    a=dict(key='stage',episode='named:test',chapter=1,stage=2,name='battle',cost=8,team_entry_mode='single_task',start_epoch=time.time()-10)
    r.s=dict(attempted={},completed={},entry_dispatches={},active=copy.deepcopy(a))
    dispatch=reserve_entry(r.s,a['key'],a);finish_dispatch(dispatch,'sent')
    r.action=Mock(return_value=None);r.evidence.return_value='independent.png'
    r.observe_progress_evidence.return_value=(True,.25)
    return r


def apply(r,mode='battle',value=True):
    # Dispatch tests inject an already PROVEN semantic state, never use white
    # arrows as OFF. Observer/animation/manual-turn proof is tested separately.
    f=r.frame;t=target(f)
    field=dict(target=t,ring=runner.np.zeros((80,80),bool),canonical=True)
    with patch.object(settings,'auto_field',return_value=field),patch.object(settings,'speed_field',return_value=dict(state=2,target=t)),patch.object(settings.AutoObserver,'observe',return_value=dict(state='off' if value else 'on',samples=[])),patch.object(settings,'_save_samples',return_value=dict(source='synthetic proven OFF')),patch.object(settings,'verify_setting',return_value=dict(captured_at=time.time(),source_at=f.at,controls=[t])):
        return auto.step(r,f,mode)


class NativeAutoFieldTests(unittest.TestCase):
    def test_real_hud_gate_requires_wave_health_and_two_pause_bars(self):
        f=battle_frame();self.assertTrue(auto.hud(f))
        for change in ('wave','health','pause','modal'):
            b=battle_frame()
            if change=='wave':b.words[0]['score']=.84
            elif change=='health':b.words[1]['score']=.979
            elif change=='pause':b.image[13:72,1532:1580]=22
            else:b.words+=frame([('确认',900,575)]).words
            self.assertFalse(auto.hud(b))

    def test_lower_summon_meter_does_not_ambiguate_actual_health(self):
        for text in ('0/5','1/5','5/5'):
            f=battle_frame();f.words+=frame([(text,465,873)]).words
            self.assertTrue(auto.hud(f),text)

    def test_lower_meter_alone_does_not_replace_missing_or_low_confidence_health(self):
        for mode in ('missing','weak'):
            f=battle_frame()
            if mode=='missing':f.words.pop(1)
            else:f.words[1]['score']=.979
            f.words+=frame([('5/5',465,873)]).words
            self.assertFalse(auto.hud(f))

    def test_only_one_current_field_read_and_no_cross_frame_cache(self):
        f=off_frame();ocr=Mock(return_value=([['A',.999]],None))
        t=auto.off_target(f,ocr);self.assertIsNotNone(t)
        self.assertEqual(t['text'],'A');self.assertEqual(t['captured_at'],f.at)
        self.assertEqual(ocr.call_args.kwargs,dict(use_det=False,use_cls=False))
        self.assertEqual(ocr.call_count,1);self.assertIs(auto.off_target(f,ocr),t)
        self.assertEqual(ocr.call_count,1)
        g=off_frame();self.assertIsNotNone(auto.off_target(g,ocr));self.assertEqual(ocr.call_count,2)

    def test_unknown_letter_low_confidence_or_missing_off_arrow_never_authorizes(self):
        for text,score in (('B',.999),('A',.979)):
            f=off_frame();self.assertIsNone(auto.off_target(f,Mock(return_value=([[text,score]],None))))
        f=off_frame();f.image[5:34,1360:1440]=22
        ocr=Mock();self.assertIsNone(auto.off_target(f,ocr));ocr.assert_not_called()

    def test_original_strong_current_a_does_not_get_an_extra_ocr(self):
        f=off_frame();f.words+=frame([('A',1409,42)]).words;ocr=Mock()
        t=auto.off_target(f,ocr);self.assertIsNotNone(t);ocr.assert_not_called()


class NativeAutoDispatchTests(unittest.TestCase):
    def test_regular_unified_manual_fallback_is_preempted_but_real_new_account_guides_are_not(self):
        from test_map_layout import fake_runner
        for tutorial,new_account,response in (('krau_story_basic',False,(True,.25)),
                ('krau_story_basic',False,None),('krau_story_basic',True,None),('other_free_guide',False,None)):
            r=fake_runner(battle_frame());r.run_id='run';r.s=configured().s;r.cfg['new_account_tutorial']=new_account
            r.tutorial_controller=Mock();r.tutorial_controller.step.return_value=(True,.25)
            with patch('runner.classify',return_value='new_player_tutorial'),patch('runner.tutorial_plan',return_value=dict(rule=tutorial)),patch('runner.event'),patch('battle_auto_control.step',return_value=response) as switch:
                r.step(r.frame)
            if not new_account and tutorial=='krau_story_basic':
                switch.assert_called_once();r.tutorial_controller.step.assert_not_called();r.action.assert_not_called()
            else:
                switch.assert_not_called();r.tutorial_controller.step.assert_called_once()

    def test_original_sent_binding_and_durable_intent_before_free_auto_only(self):
        r=configured();before=copy.deepcopy(r.s);order=[]
        r.save.side_effect=lambda:order.append('save')
        def click(*args):
            self.assertEqual(r.s['battle_desired_settings']['stage']['auto']['messages'][-1]['status'],'reserved')
            order.append('tap')
        r.action.side_effect=click
        self.assertEqual(apply(r),(True,.25))
        self.assertEqual(order,['save','save','tap','save'])  # Desired speed observation + reserved intent, then tap.
        self.assertEqual(r.s['battle_desired_settings']['stage']['auto']['messages'][0]['status'],'sent')
        for key in before:self.assertEqual(r.s[key],before[key])
        self.assertIn('不入场',r.action.call_args.args[0])

    def test_invalid_entry_unknown_result_completed_or_foreign_archive_zero_input(self):
        for invalid in ('unknown_send','duplicate','completed','archive','result'):
            r=configured()
            if invalid=='unknown_send':r.s['entry_dispatches']['stage'][0]['status']='unknown'
            elif invalid=='duplicate':r.s['entry_dispatches']['stage']*=2
            elif invalid=='completed':r.s['completed']['stage']={}
            elif invalid=='archive':r.s['unresolved_entries']=[dict(entry=dict(key='stage'))]
            else:r.s['active']['victory_seen']=True
            self.assertIsNone(apply(r));r.action.assert_not_called()

    def test_current_battle_new_start_can_enable_auto_without_adopting_archived_entry(self):
        r=configured();old=copy.deepcopy(r.s['active']);r.s['active']=None
        r.s['unresolved_entries']=[dict(entry=old,reason='new start from current screen')]
        r.s['last_cleared']={'key':'earlier-fact'};before=copy.deepcopy(r.s);order=[]
        r.save.side_effect=lambda:order.append('save')
        def click(*args):
            record=r.s['battle_desired_settings']['current-battle:run']
            self.assertEqual(record['scope'],'current_battle_ui_only')
            self.assertIsNone(record['entry_key']);self.assertIsNone(record['original_sha256'])
            self.assertEqual(record['auto']['messages'][-1]['status'],'reserved');order.append('tap')
        r.action.side_effect=click
        self.assertEqual(apply(r,mode='new_player_tutorial'),(True,.25))
        self.assertEqual(order,['save','save','tap','save'])  # Desired speed observation + reserved intent, then tap.
        for key in before:self.assertEqual(r.s[key],before[key])
        self.assertIsNone(auto.source(r.s))
        self.assertIsNone(r.s['active']);self.assertNotIn('stage',r.s['completed'])

    def test_ui_only_context_requires_a_run_no_active_and_no_terminal(self):
        r=configured();r.s['active']=None
        self.assertEqual(auto.control_context(r.s,r.run_id)['scope'],'current_battle_ui_only')
        for run_id in ('',None,False):self.assertIsNone(auto.control_context(r.s,run_id))
        r.s['terminal']=True;self.assertIsNone(apply(r));r.action.assert_not_called()
        r=configured();r.s['active']={};self.assertIsNone(apply(r));r.action.assert_not_called()

    def test_ui_only_context_never_inherits_an_archived_auto_budget(self):
        r=configured();apply(r);old=copy.deepcopy(r.s['battle_desired_settings']['stage'])
        r.s['active']=None;r.action.reset_mock();self.assertEqual(apply(r),(True,.25))
        self.assertEqual(r.s['battle_desired_settings']['stage'],old)
        self.assertEqual(len(r.s['battle_desired_settings']['current-battle:run']['auto']['messages']),1)
        r.action.assert_called_once()

    def test_ui_only_unknown_or_reserved_message_never_replays(self):
        for status in ('unknown','reserved'):
            r=configured();r.s['active']=None;apply(r);r.action.reset_mock()
            last=r.s['battle_desired_settings']['current-battle:run']['auto']['messages'][-1]
            last.update(status=status,finished_at=time.time()-5)
            self.assertEqual(apply(r),(True,.25));r.action.assert_not_called()

    def test_ui_only_needs_current_hud_off_glyph_and_successful_persistence(self):
        for failure in ('hud','off','live','state','evidence'):
            r=configured();r.s['active']=None
            if failure=='hud':r.frame.words=[]
            if failure=='state':r.save.side_effect=OSError('disk full')
            if failure=='evidence':r.evidence.side_effect=OSError('disk full')
            if failure in ('state','evidence'):
                with self.assertRaises(OSError):apply(r)
            elif failure=='live':
                with patch.object(settings,'verify_setting',return_value=None):auto.step(r,r.frame,'battle')
            else:apply(r,value=failure!='off')
            r.action.assert_not_called()

    def test_no_known_hud_or_unknown_overlay_zero_input(self):
        r=configured();r.frame.words+=frame([('确认',900,575)]).words
        self.assertIsNone(apply(r));r.action.assert_not_called()

    def test_fresh_off_state_is_bounded_and_never_reuses_one_intent(self):
        r=configured();apply(r);r.action.reset_mock()
        apply(r);r.action.assert_not_called()
        for _ in range(3):
            last=r.s['battle_desired_settings']['stage']['auto']['messages'][-1];last['finished_at']-=5
            time.sleep(.02);r.frame=battle_frame()
            apply(r)
        self.assertEqual(len(r.s['battle_desired_settings']['stage']['auto']['messages']),2)
        self.assertEqual(r.action.call_count,1)
        self.assertEqual(len(r.s['entry_dispatches']['stage']),1)

    def test_unknown_send_never_retries(self):
        r=configured();r.action.side_effect=RuntimeError('send uncertain')
        with self.assertRaises(RuntimeError):apply(r)
        self.assertEqual(r.s['battle_desired_settings']['stage']['auto']['messages'][0]['status'],'unknown')
        r.action.reset_mock();apply(r);r.action.assert_not_called()

    def test_write_or_evidence_failure_prevents_input(self):
        for kind in ('state','evidence'):
            r=configured()
            if kind=='state':r.save.side_effect=OSError('disk full')
            else:r.evidence.side_effect=OSError('disk full')
            with self.assertRaises(OSError):apply(r)
            r.action.assert_not_called()

    def test_expired_or_changed_field_never_creates_an_input_intent(self):
        r=configured();r.frame.at-=4
        self.assertEqual(apply(r),(True,.25));r.action.assert_not_called()
        r=configured()
        with patch.object(settings,'verify_setting',return_value=None):
            auto.step(r,r.frame,'battle')
        r.action.assert_not_called();self.assertFalse((r.s.get('battle_desired_settings',{}).get('stage') or {}).get('auto',{}).get('messages'))

    def test_after_auto_send_manual_basic_fallback_is_not_replayed(self):
        r=configured();r.s['tutorial']=dict(combat_latch=1,actions=[dict(status='sent',keep='original basic')])
        before=copy.deepcopy(r.s['tutorial']);apply(r);r.action.reset_mock()
        self.assertEqual(apply(r,mode='new_player_tutorial',value=False),(True,.25))
        r.action.assert_not_called();self.assertEqual(r.s['tutorial'],before)


if __name__=='__main__':unittest.main()
