"""No OS input: volatile-target race prevention and audited chat dismissal."""
import copy,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from chat_recovery import ChatRecoveryController,close_controls
from ui_control_guard import matching_control_pixels,verify_live_controls
from task_blockers import TaskAttention


def make_frame(rows):
    image=runner.np.full((900,1600,3),40,runner.np.uint8);words=[]
    for i,(text,x,y,width) in enumerate(rows):
        x1,x2=x-width//2,x+width//2;y1,y2=y-16,y+17
        words.append(([[x1,y1],[x2,y1],[x2,y2],[x1,y2]],text,.999))
        runner.cv2.putText(image,'SKIP' if text=='跳过' else 'FIELD'+str(i),(x1+2,y+8),runner.cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),2)
    return runner.Frame(image,words)


def chat():
    return make_frame([('骑士团频道',996,38,190),('点击此处并输入',1100,845,250),('输入',1485,845,100)])


def story():return make_frame([('跳过',1510,47,64)])


def runner_for(f):
    r=runner.Runner.__new__(runner.Runner);r.frame=f;r.s=dict(active={'key':'stage','cost':8},
        attempted={'stage':{'cost':8}},completed={},entry_dispatches={'stage':[{'id':'entry','status':'sent'}]})
    r.run_id='run';r.ticket=None;r.last_mode=None;r.mode_since=time.time();r.cfg={};r.story=None
    r.save=Mock();r.evidence=Mock(return_value='independent.png');r.ensure_game=Mock();r.pc=Mock(frame_window=None)
    r._capture_pixels=Mock(return_value=(f.image.copy(),f.raw_size));r.capture=Mock();r.ocr=Mock()
    return r


class RecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=patch.object(runner,'ROOT',Path(self.tmp.name));self.root.start();self.addCleanup(self.root.stop)
        self.events=patch.object(runner,'event');self.events.start();self.addCleanup(self.events.stop)



class ChatRecoveryTests(RecoveryTestCase):
    def observe_later(self,c,scene,f):
        # A distinct post-send observation, independent of OS clock resolution.
        f.at=c.active()['messages'][-1]['sent_at']+.01
        with patch('chat_recovery.time.time',return_value=f.at+.01):c.observe_scene(scene,f)

    def test_native_close_durable_before_input_keeps_original_entry_then_proves_departure(self):
        f=chat();r=runner_for(f);before=copy.deepcopy(r.s);order=[]
        r.save.side_effect=lambda:order.append('save');r.pc.back.side_effect=lambda:order.append('back')
        c=ChatRecoveryController(r);self.assertEqual(c.step(f),(True,.25))
        self.assertEqual(order,['save','back','save'])
        row=c.active();self.assertEqual(row['messages'][0]['status'],'sent')
        self.assertEqual(len(list(Path(self.tmp.name).glob('evidence/*.png'))),2)
        c.step(f);r.pc.back.assert_called_once();r.pc.tap.assert_not_called()
        f=make_frame([('关卡任务',500,400,140),('闯关成功',500,440,140)])
        self.observe_later(c,'victory',f)
        self.assertIsNone(c.active());self.assertEqual(row['phase'],'closed')
        for key,value in before.items():self.assertEqual(r.s[key],value)
        r.capture.assert_not_called();r.ocr.assert_not_called()

    def test_equal_timestamp_cannot_prove_departure_even_with_a_coarse_clock(self):
        r=runner_for(chat());c=ChatRecoveryController(r);c.step(r.frame)
        sent=c.active()['messages'][-1]['sent_at'];f=make_frame([('3/3',200,30,80)])
        f.at=sent
        with patch('chat_recovery.time.time',return_value=sent+.1):c.observe_scene('battle',f)
        self.assertEqual(c.active()['phase'],'awaiting_disappearance')
        self.observe_later(c,'battle',f);self.assertIsNone(c.active())
        r.pc.back.assert_called_once()

    def test_android_close_uses_native_back_not_a_chat_coordinate(self):
        f=chat();r=runner_for(f);r.pc=None;r.adb=Mock();c=ChatRecoveryController(r)
        c.step(f);r.adb.assert_called_once_with('shell','input','keyevent','4')

    def test_reappearing_panel_has_its_own_occurrence_not_a_run_lifetime_latch(self):
        r=runner_for(chat());c=ChatRecoveryController(r);c.step(r.frame)
        self.observe_later(c,'battle',make_frame([('3/3',200,30,80)]))
        r.frame=chat();r._capture_pixels.return_value=(r.frame.image.copy(),r.frame.raw_size)
        c.step(r.frame)
        self.assertEqual(len(r.s['chat_recoveries']['occurrences']),2)
        self.assertEqual(r.pc.back.call_count,2)

    def test_missing_weak_duplicate_or_drafted_editor_never_sends_native_back(self):
        for kind in ('heading','editor','send','weak','duplicate','draft'):
            f=chat()
            if kind in ('heading','editor','send'):f.words.pop(('heading','editor','send').index(kind))
            elif kind=='weak':f.words[0]['score']=.979
            elif kind=='duplicate':f.words.append(copy.deepcopy(f.words[0]))
            else:f.words[1]['text']='user draft'
            r=runner_for(f);c=ChatRecoveryController(r);c.step(f)
            r.pc.back.assert_not_called();r.pc.tap.assert_not_called();r._capture_pixels.assert_not_called()

    def test_changed_panel_or_popup_cannot_receive_old_back(self):
        for kind in ('gone','popup'):
            f=chat();r=runner_for(f);im=f.image.copy()
            if kind=='gone':im[:]=40
            else:im[300:650,950:1500]=220
            r._capture_pixels.return_value=(im,f.raw_size)
            ChatRecoveryController(r).step(f)
            r.pc.back.assert_not_called();self.assertNotIn('chat_recoveries',r.s)

    def test_expired_cancelled_intent_can_be_replanned_without_reusing_it(self):
        r=runner_for(chat());c=ChatRecoveryController(r);c.step(r.frame)
        row=c.active();row['messages'][0]['status']='cancelled_before_send'
        r.frame=chat();r._capture_pixels.return_value=(r.frame.image.copy(),r.frame.raw_size)
        c.step(r.frame)
        self.assertEqual(len(row['messages']),2)
        self.assertEqual(row['messages'][0]['status'],'cancelled_before_send')

    def test_actual_send_failure_is_not_automatically_repeated(self):
        r=runner_for(chat());r.pc.back.side_effect=RuntimeError('delivery unknown');c=ChatRecoveryController(r)
        with self.assertRaises(RuntimeError):c.step(r.frame)
        self.assertEqual(c.active()['messages'][0]['status'],'unknown')
        with self.assertRaises(TaskAttention):c.step(r.frame)
        self.assertEqual(r.pc.back.call_count,1)

    def test_key_evidence_or_intent_write_failure_prevents_input(self):
        for kind in ('evidence','state'):
            r=runner_for(chat());c=ChatRecoveryController(r)
            if kind=='state':r.save.side_effect=OSError('disk full')
            with patch.object(Path,'write_bytes',side_effect=OSError('evidence full')) if kind=='evidence' else patch.object(runner,'now',return_value='now'):
                with self.assertRaises(OSError):c.step(r.frame)
            r.pc.back.assert_not_called()

    def test_unknown_frame_is_not_disappearance_and_high_priority_blocker_wins(self):
        r=runner_for(chat());c=ChatRecoveryController(r);c.step(r.frame)
        c.observe_scene('unknown',make_frame([]));self.assertIsNotNone(c.active())
        f=chat();f.words.extend(make_frame([('装备背包已满',800,420,200)]).words);r=runner_for(f)
        with self.assertRaises(TaskAttention) as exc:r.step(f)
        self.assertEqual(exc.exception.code,'equipment');r.pc.back.assert_not_called()


class VolatileControlTests(RecoveryTestCase):
    def test_skip_control_removed_or_replaced_by_chat_rejects_stale_click_within_ttl(self):
        for kind in ('removed','chat'):
            f=story();r=runner_for(f);im=f.image.copy();im[20:80,1450:1590]=40
            if kind=='chat':runner.cv2.circle(im,(1510,47),16,(230,230,230),2)
            r._capture_pixels.return_value=(im,f.raw_size)
            self.assertIs(r.action('跳过剧情',f.words[0]),False)
            r.pc.tap.assert_not_called();r.capture.assert_not_called();r.ocr.assert_not_called()

    def test_live_control_pixels_allow_one_real_control_without_second_full_ocr(self):
        f=story();r=runner_for(f);r.action('跳过剧情',f.words[0])
        r.pc.tap.assert_called_once_with(1510.,47.5);r._capture_pixels.assert_called_once()
        r.capture.assert_not_called();r.ocr.assert_not_called()
        self.assertEqual(r.frame.at,f.at)

    def test_geometry_change_or_expired_frame_is_not_recoverable_capture_noise(self):
        from pc_backend import FrameExpired
        f=story();r=runner_for(f);r._capture_pixels.return_value=(f.image,(1280,720))
        with self.assertRaises(RuntimeError):r.action('跳过剧情',f.words[0])
        r.pc.tap.assert_not_called()
        f=story();r=runner_for(f);f.at-=6
        with self.assertRaises(FrameExpired):r.action('跳过剧情',f.words[0])
        r._capture_pixels.assert_not_called();r.pc.tap.assert_not_called()

    def test_transient_guard_black_capture_is_zero_input_not_a_worker_failure(self):
        from pc_message_backend import CaptureUnavailable
        f=story();r=runner_for(f);r._capture_pixels.side_effect=CaptureUnavailable('temporary black frame')
        self.assertIs(r.action('跳过剧情',f.words[0]),False);r.pc.tap.assert_not_called()
        r=runner_for(chat());r._capture_pixels.side_effect=CaptureUnavailable('temporary black frame')
        ChatRecoveryController(r).step(r.frame);r.pc.back.assert_not_called()

    def test_expired_chat_frame_replans_without_consuming_a_close_intent(self):
        r=runner_for(chat());r.frame.at-=6
        ChatRecoveryController(r).step(r.frame)
        self.assertNotIn('chat_recoveries',r.s);r.pc.back.assert_not_called()

    def test_confirm_requires_both_live_confirm_and_cancel_glyphs(self):
        f=make_frame([('是否跳过故事？',800,400,240),('确认',935,575,80),('取消',665,575,80)])
        r=runner_for(f);im=f.image.copy();im[555:595,620:710]=40;r._capture_pixels.return_value=(im,f.raw_size)
        self.assertIs(r.action('确认跳过剧情',f.words[1]),False);r.pc.tap.assert_not_called()


if __name__=='__main__':unittest.main()
