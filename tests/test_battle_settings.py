"""AUTO-on / battle-speed-2x reconciliation. Synthetic pixels and fake inputs."""
import copy,hashlib,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
import battle_settings as settings
import battle_auto_control as legacy
from pc_backend import FrameExpired
from test_battle_auto_control import off_frame,battle_frame,configured,target
from test_map_layout import frame


def ready_frame():
    f=off_frame()
    for x in (1265,1405,1525):
        runner.cv2.rectangle(f.image,(x-40,780),(x+40,870),(150,50,10),-1)
        runner.cv2.circle(f.image,(x,825),35,(240,240,240),3)
    return f


def reading_field(f):
    return dict(target=target(f),ring=runner.np.zeros((80,80),bool),canonical=True)


def speed_frame():
    f=ready_frame();cv=runner.cv2;np=runner.np
    cv.polylines(f.image,[np.array([(1324,24),(1338,39),(1324,54)],np.int32)],False,(240,240,240),6)
    cv.putText(f.image,'1',(1343,62),cv.FONT_HERSHEY_SIMPLEX,.6,(240,240,240),2)
    return f


def apply(r,auto='unknown',speed=2,proof=True):
    f=r.frame;field=reading_field(f);sfield=dict(state=speed,target=settings._target('x'+str(speed),settings.SPEED_RECT,1333,43,.999,'synthetic')) if speed in (1,2) else None
    with patch.object(settings,'auto_field',return_value=field),patch.object(settings,'speed_field',return_value=sfield),patch.object(settings.AutoObserver,'observe',return_value=dict(state=auto,samples=[])),patch.object(settings,'_save_samples',return_value=dict(source='synthetic semantic state')),patch.object(settings,'verify_setting',return_value=dict(captured_at=time.time(),current_evidence='synthetic.png') if proof else None):
        return settings.step(r,f,'battle')


class NativeSettingsReaders(unittest.TestCase):
    def test_white_glyph_alone_is_a_control_not_an_off_state(self):
        f=ready_frame();ocr=Mock(return_value=([['A',.999]],None))
        field=settings.auto_field(f,ocr);self.assertIsNotNone(field)
        observer=settings.AutoObserver()
        self.assertEqual(observer.observe(f,field,0)['state'],'unknown')

    def test_native_rotation_is_on_not_a_second_toggle_permission(self):
        f=ready_frame();ocr=Mock(return_value=([['A',.999]],None));field=settings.auto_field(f,ocr)
        obs=settings.AutoObserver();f.at=100.;obs.observe(f,field,0)
        g=ready_frame();g.at=101.
        moved=dict(field,ring=runner.np.roll(field['ring'],7,axis=0),canonical=False)
        self.assertEqual(obs.observe(g,moved,0)['state'],'on')

    def test_stationary_canonical_manual_turn_needs_independent_normal_cycles(self):
        obs=settings.AutoObserver();result=None
        for at in (100.,101.4,103.2):
            f=ready_frame();f.at=at;field=settings.auto_field(f,Mock(return_value=([['A',.999]],None)))
            result=obs.observe(f,field,0)
        self.assertEqual(result['state'],'off');self.assertEqual(len(result['samples']),3)

    def test_stationary_off_is_detected_at_quarter_second_cycle_without_unbounded_frames(self):
        obs=settings.AutoObserver()
        for i in range(17):
            f=ready_frame();f.at=100.+i*.25
            field=settings.auto_field(f,Mock(return_value=([['A',.999]],None)))
            result=obs.observe(f,field,0)
        self.assertEqual(result['state'],'off')
        self.assertLessEqual(len(obs.samples),5)
        self.assertGreaterEqual(result['samples'][-1]['at']-result['samples'][0]['at'],3.)

    def test_motion_between_spaced_stationary_samples_is_not_missed(self):
        obs=settings.AutoObserver();f=ready_frame();f.at=100.
        field=settings.auto_field(f,Mock(return_value=([['A',.999]],None)))
        obs.observe(f,field,0)
        moved=dict(field,ring=runner.np.roll(field['ring'],7,axis=0),canonical=False)
        f=ready_frame();f.at=100.25
        self.assertEqual(obs.observe(f,moved,0)['state'],'on')
        f=ready_frame();f.at=100.5
        self.assertEqual(obs.observe(f,field,0)['state'],'on')

    def test_stationary_cutscene_or_noncanonical_phase_never_proves_off(self):
        for missing in ('manual','canonical'):
            obs=settings.AutoObserver()
            for at in (100.,101.4,103.2):
                f=ready_frame() if missing!='manual' else off_frame();f.at=at
                field=settings.auto_field(f,Mock(return_value=([['A',.999]],None)))
                if missing=='canonical':field['canonical']=False
                result=obs.observe(f,field,0)
            self.assertEqual(result['state'],'unknown',missing)

    def test_input_change_duplicate_time_large_gap_or_hp_change_restarts_off_proof(self):
        for failure in ('input','time','gap','hp'):
            obs=settings.AutoObserver()
            for i,at in enumerate((100.,101.4,103.2)):
                f=ready_frame();f.at=at
                if i==2:
                    if failure=='time':f.at=101.4
                    elif failure=='gap':f.at=110.
                    elif failure=='hp':f.words[1]['text']='99/100'
                field=settings.auto_field(f,Mock(return_value=([['A',.999]],None)))
                result=obs.observe(f,field,1 if failure=='input' and i==2 else 0)
            self.assertEqual(result['state'],'unknown',failure)

    def test_missing_auto_field_discards_prior_proof(self):
        obs=settings.AutoObserver();f=ready_frame();field=settings.auto_field(f,Mock(return_value=([['A',.999]],None)))
        obs.observe(f,field,0);self.assertEqual(obs.observe(f,None,0)['state'],'unknown');self.assertFalse(obs.samples)

    def test_speed_digit_is_one_current_field_read_and_cached_on_same_frame(self):
        for text,value in (('1',1),('2',2)):
            f=speed_frame();ocr=Mock(return_value=([[text,.999]],None))
            reading=settings.speed_field(f,ocr);self.assertIsNotNone(reading)
            self.assertEqual(reading['state'],value);ocr.assert_called_once()
            self.assertEqual(ocr.call_args.kwargs,dict(use_det=False,use_cls=False))
            self.assertIs(settings.speed_field(f,ocr),reading);ocr.assert_called_once()

    def test_complete_current_speed_text_is_not_reread(self):
        f=speed_frame();f.words+=frame([('×2',1340,55)]).words;ocr=Mock()
        self.assertEqual(settings.speed_field(f,ocr)['state'],2);ocr.assert_not_called()

    def test_weak_changed_unknown_or_ambiguous_speed_digit_never_authorizes(self):
        for rows in ([['1',.979]],[['3',.999]],[['x1',.999]],[['1',.999],['2',.999]],[]):
            self.assertIsNone(settings.speed_field(speed_frame(),Mock(return_value=(rows,None))))

    def test_speed_digit_without_native_battle_chevron_is_not_a_control(self):
        f=speed_frame();f.image[5:85,1300:1340]=22;ocr=Mock()
        self.assertIsNone(settings.speed_field(f,ocr));ocr.assert_not_called()

    def test_legacy_white_off_candidate_is_not_called_by_new_control_dispatch(self):
        r=configured()
        with patch.object(legacy,'off_target',side_effect=AssertionError('white is not OFF')):
            apply(r,auto='on',speed=2)
        r.action.assert_not_called()


class DesiredStateDispatch(unittest.TestCase):
    def test_both_target_states_already_correct_never_toggle(self):
        r=configured();before=copy.deepcopy(r.s)
        for _ in range(3):apply(r,'on',2)
        r.action.assert_not_called()
        for key in before:self.assertEqual(r.s[key],before[key])
        rec=r.s['battle_desired_settings']['stage']
        self.assertEqual(rec['auto']['initial_desired_observation']['state'],'on')
        self.assertEqual(rec['speed']['initial_desired_observation']['state'],2)

    def test_only_explicit_off_turns_on_and_only_one_current_frame_input(self):
        r=configured();apply(r,'off',1)
        r.action.assert_called_once();self.assertEqual(r.action.call_args.args[1]['text'],'A')
        rec=r.s['battle_desired_settings']['stage']
        self.assertEqual(len(rec['auto']['messages']),1);self.assertFalse(rec['speed']['messages'])
        self.assertEqual(rec['auto']['messages'][0]['from_state'],'off')

    def test_unknown_auto_never_toggles_but_verified_one_x_can_set_two_x(self):
        r=configured();apply(r,'unknown',1)
        r.action.assert_called_once();self.assertEqual(r.action.call_args.args[1]['text'],'x1')
        rec=r.s['battle_desired_settings']['stage'];self.assertEqual(rec['speed']['messages'][0]['desired'],2)
        self.assertFalse(rec['auto']['messages'])

    def test_unknown_speed_is_never_a_two_to_one_guess(self):
        for speed in ('unknown',3,None):
            r=configured();apply(r,'on',speed);r.action.assert_not_called()

    def test_send_is_not_acceptance_only_later_current_state_confirms(self):
        r=configured();apply(r,'unknown',1);rec=r.s['battle_desired_settings']['stage'];message=rec['speed']['messages'][0]
        self.assertEqual(message['status'],'sent');self.assertFalse(rec['speed']['confirmations'])
        r.action.reset_mock();r.frame=battle_frame();r.frame.at=message['at']+.01
        with patch.object(settings.time,'time',return_value=message['at']+.05):apply(r,'on',2)
        r.action.assert_not_called()
        self.assertEqual(rec['speed']['confirmations'][0]['message_id'],message['id'])
        self.assertEqual(r.s['completed'],{})

    def test_later_verified_state_regression_can_open_a_new_transition(self):
        r=configured();apply(r,'unknown',1);slot=r.s['battle_desired_settings']['stage']['speed'];first=slot['messages'][0]
        r.frame=battle_frame();r.frame.at=first['at']+.01
        with patch.object(settings.time,'time',return_value=first['at']+.05):apply(r,'on',2)
        r.frame=battle_frame();r.frame.at=first['at']+.1;r.action.reset_mock()
        with patch.object(settings.time,'time',return_value=first['at']+.15):apply(r,'on',1)
        self.assertEqual(len(slot['messages']),2)
        self.assertNotEqual(slot['messages'][0]['transition'],slot['messages'][1]['transition'])
        r.action.assert_called_once()

    def test_same_unaccepted_transition_has_bounded_separate_commands(self):
        r=configured();apply(r,'unknown',1);slot=r.s['battle_desired_settings']['stage']['speed']
        for _ in range(4):
            slot['messages'][-1]['finished_at']-=5;r.frame=battle_frame();apply(r,'unknown',1)
        self.assertEqual(len(slot['messages']),2)
        self.assertNotEqual(slot['messages'][0]['id'],slot['messages'][1]['id'])
        self.assertEqual(len(r.s['entry_dispatches']['stage']),1)

    def test_unknown_or_reserved_setting_send_never_replays(self):
        for status in ('unknown','reserved'):
            r=configured();apply(r,'unknown',1);slot=r.s['battle_desired_settings']['stage']['speed']
            slot['messages'][0].update(status=status,finished_at=time.time()-10)
            r.action.reset_mock();r.frame=battle_frame();apply(r,'unknown',1);r.action.assert_not_called()

    def test_failed_send_is_preserved_unknown_not_retried(self):
        r=configured();r.action.side_effect=RuntimeError('uncertain input')
        with self.assertRaises(RuntimeError):apply(r,'unknown',1)
        self.assertEqual(r.s['battle_desired_settings']['stage']['speed']['messages'][0]['status'],'unknown')
        r.action.reset_mock();r.action.side_effect=None;apply(r,'unknown',1);r.action.assert_not_called()

    def test_evidence_or_state_write_failure_is_zero_input(self):
        for failure in ('state','evidence'):
            r=configured()
            if failure=='state':r.save.side_effect=OSError('disk full')
            else:r.evidence.side_effect=OSError('disk full')
            with self.assertRaises(OSError):apply(r,'unknown',1)
            r.action.assert_not_called()

    def test_same_cycle_pending_unknown_does_not_claim_auto_enabled(self):
        r=configured();apply(r,'unknown','unknown')
        self.assertIn('自动=unknown',r.observe_progress_evidence.call_args.args[1]['reason'])
        r.action.assert_not_called()

    def test_old_white_glyph_messages_and_resource_history_are_immutable(self):
        r=configured();r.s['battle_auto_controls']={'stage':dict(messages=[dict(status='sent',evidence='legacy')])}
        old=copy.deepcopy(r.s);apply(r,'off',2)
        for key in old:self.assertEqual(r.s[key],old[key])

    def test_no_valid_original_active_never_falls_back_to_external_ownership(self):
        r=configured();r.s['entry_dispatches']['stage'][0]['status']='unknown'
        self.assertIsNone(apply(r,'off',1));r.action.assert_not_called()

    def test_current_battle_ui_only_context_never_adopts_old_archive(self):
        r=configured();r.s['active']=None;r.s['unresolved_entries']=[dict(entry=copy.deepcopy(r.s['attempted']['stage']))]
        before=copy.deepcopy(r.s);apply(r,'unknown',1)
        self.assertIsNone(r.s['active']);self.assertEqual(r.s['completed'],{})
        self.assertIn('current-battle:run',r.s['battle_desired_settings'])
        for key in before:self.assertEqual(r.s[key],before[key])

    def test_expired_changed_target_or_unknown_dialog_never_sends(self):
        r=configured();r.frame.at-=4;apply(r,'off',1);r.action.assert_not_called()
        r=configured();apply(r,'off',1,proof=False);r.action.assert_not_called()
        r=configured();r.frame.words+=frame([('确认',935,575)]).words
        self.assertIsNone(apply(r,'off',1));r.action.assert_not_called()


class ActionFreshnessTests(unittest.TestCase):
    def test_setting_proof_expiring_during_state_save_is_not_sent(self):
        from test_map_layout import fake_runner
        r=fake_runner(ready_frame());r.frame.at=time.time();r.ensure_game=Mock();r.pc=Mock()
        r._battle_setting_proof=dict(source_at=r.frame.at,captured_at=time.time())
        r.save=Mock(side_effect=lambda:r._battle_setting_proof.update(captured_at=time.time()-1))
        with patch('runner.event'),self.assertRaises(FrameExpired):
            runner.Runner.action(r,'开启已核实关闭的战斗自动（不入场、不托管）',target(r.frame))
        r.pc.tap.assert_not_called()

    def test_setting_proof_from_different_source_frame_is_not_sent(self):
        from test_map_layout import fake_runner
        r=fake_runner(ready_frame());r.frame.at=time.time();r.ensure_game=Mock();r.pc=Mock();r.save=Mock()
        r._battle_setting_proof=dict(source_at=r.frame.at-1,captured_at=time.time())
        with patch('runner.event'),self.assertRaises(FrameExpired):
            runner.Runner.action(r,'将已核实的战斗1倍速调至2倍速（不入场）',target(r.frame))
        r.pc.tap.assert_not_called()


class StatePixelProofTests(unittest.TestCase):
    def test_arrow_phase_change_cancels_even_when_control_identity_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);f=ready_frame();r=Mock(frame=f)
            image=f.image.copy();image[5:85,1360:1440]=runner.np.roll(image[5:85,1360:1440],3,axis=0)
            path=root/'current.png';runner.cv2.imwrite(str(path),image)
            proof=dict(current_evidence='current.png',current_sha256=hashlib.sha256(image.tobytes()).hexdigest())
            with patch.object(runner,'ROOT',root),patch.object(settings,'verify_live_controls',return_value=proof):
                self.assertIsNone(settings.verify_setting(r,'auto',reading_field(f)))

    def test_speed_digit_change_cancels_old_one_x_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);f=speed_frame();r=Mock(frame=f)
            image=f.image.copy();image[39:68,1340:1358]=22
            runner.cv2.imwrite(str(root/'current.png'),image)
            proof=dict(current_evidence='current.png',current_sha256=hashlib.sha256(image.tobytes()).hexdigest())
            with patch.object(runner,'ROOT',root),patch.object(settings,'verify_live_controls',return_value=proof):
                self.assertIsNone(settings.verify_setting(r,'speed',reading_field(f)))

    def test_temporal_proof_contains_independent_frames_without_timestamp_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);f=ready_frame();f.at=100.;samples=[dict(frame=f,ring=runner.np.zeros((80,80),bool),manual=('1/3','100/100'))]
            with patch.object(runner,'ROOT',root):proof=settings._save_samples(Mock(),dict(state='off',source='synthetic',samples=samples))
            self.assertEqual(proof['samples'][0]['captured_at'],100.)
            self.assertTrue((root/proof['path']).is_file());self.assertEqual(f.at,100.)


if __name__=='__main__':unittest.main()
