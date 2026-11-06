"""Offline-only regression: never tap chat after the story label disappears."""
import copy,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import cv2,numpy as np
import runner
from pc_backend import PcSafetyError
from task_blockers import TaskAttention
from task_overlays import chat_panel_visible,top_right_skip_control
from task_timing import needs_stability_wait
from ui_text import scene_name


def frame(rows=(),image=None):
    results=[]
    for row in rows:
        text,x,y,*score=row
        results.append(([[x-15,y-10],[x+15,y-10],[x+15,y+10],[x-15,y+10]],text,score[0] if score else .999))
    return runner.Frame(np.full((900,1600,3),50,np.uint8) if image is None else image,results)


def story(tutorial=False):
    return frame([('跳过教学' if tutorial else '跳过',1510,47)])


def chat(connecting=False):
    rows=[('骑士团频道',997,38)]
    rows+=([('与聊天服务器连接中。',1250,490),('请稍等。',1250,520)] if connecting else [('点击此处并输入',1100,845),('输入',1485,845)])
    return frame(rows)


class StorySkipRecognitionTests(unittest.TestCase):
    def test_unique_confident_exact_current_skip_only(self):
        self.assertEqual(runner.classify(story()),'story')
        self.assertEqual(runner.classify(story(True)),'tutorial_skip')
        self.assertEqual(runner.classify(frame([('跳过教学',1360,47)])),'tutorial_skip')
        for rows in [[('不要跳过',1510,47)],[('跳过剧情说明',1510,47)],
                     [('跳过',1510,47,.899)],[('跳过',1300,47)],
                     [('跳过',1510,120)],[('跳过',1510,47),('跳过',1200,400)]]:
            f=frame(rows)
            self.assertIsNone(top_right_skip_control(f.words))
            self.assertNotEqual(runner.classify(f),'story')

    def test_incomplete_results_veto_residual_skip_or_teaching_label(self):
        for tutorial in (False,True):
            for result in ('CLEAR','C L E A R','VICTORY','关卡任务','闯关成功','战斗结果','获得的道具'):
                f=frame([('跳过教学' if tutorial else '跳过',1510,47),(result,800,550)])
                self.assertIsNone(top_right_skip_control(f.words,tutorial=tutorial))
                self.assertNotIn(runner.classify(f),('story','tutorial_skip'))

    def test_chat_panel_and_connecting_spinner_are_immediate_attention_scenes(self):
        for connecting in (False,True):
            f=chat(connecting)
            self.assertTrue(chat_panel_visible(f.words))
            self.assertEqual(runner.classify(f),'chat_panel')
            self.assertFalse(needs_stability_wait('chat_panel'))
        self.assertIn('聊天',scene_name('chat_panel'))

    def test_partial_weak_or_wrong_position_chat_cannot_authorize_any_input(self):
        for rows in [[('骑士团频道',997,38)],[('点击此处并输入',1100,845),('输入',1485,845)],
                     [('骑士团频道',997,38,.84),('与聊天服务器连接中。',1250,490)],
                     [('骑士团频道',500,400),('与聊天服务器连接中。',1250,490)]]:
            self.assertFalse(chat_panel_visible(frame(rows).words))

    def test_chat_overlay_vetoes_underlying_story_result_and_free_notice(self):
        base=chat().words
        rows=[(w['text'],w['x'],w['y']) for w in base]
        for extra in [[('跳过',1510,47)],[('CLEAR',800,550),('关卡任务',400,720),('闯关成功',400,770)],
                      [('获得的道具',1380,95),('战斗结果',1240,835),('确认',1460,835)],
                      [('升级！',800,300),('账号升等，行动力上限已提升',800,440),('点击关闭',800,650)]]:
            self.assertEqual(runner.classify(frame(rows+extra)),'chat_panel')

    def test_partial_chat_header_vetoes_underlying_controls_without_authorizing_close(self):
        for extra in [[('跳过',1510,47)],[('CLEAR',800,550)],
                      [('获得的道具',1380,95),('战斗结果',1240,835),('确认',1460,835)]]:
            f=frame([('骑士团频道',997,38)]+extra)
            self.assertEqual(runner.classify(f),'unknown_dialog')
            self.assertIsNone(top_right_skip_control(f.words))

    def test_resource_capacity_and_defeat_still_outrank_chat(self):
        base=[(w['text'],w['x'],w['y']) for w in chat().words]
        for extra,expected in [([('是否使用道具兑换体力',800,420)],'resource_stop'),
                               ([('装备背包已满',800,420)],'capacity_stop'),
                               ([('FAILED',800,250)],'defeat')]:
            self.assertEqual(runner.classify(frame(base+extra)),expected)

    def test_chat_attention_preserves_entry_and_never_clicks_or_completes(self):
        f=chat(True);r=runner.Runner.__new__(runner.Runner)
        r.frame=f;r.s={'completed':{},'attempted':{'stage':{'cost':8}},'active':{'key':'stage'},'victories':0}
        r.ticket=None;r.last_mode=None;r.mode_since=time.time();r.cfg={}
        before=copy.deepcopy(r.s)
        r.save=Mock();r.evidence=Mock(return_value='offline-evidence');r.action=Mock();r.completed=Mock()
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)),patch.object(runner,'event'):
            with self.assertRaises(TaskAttention) as caught:r.step(f)
        self.assertEqual(caught.exception.code,'chat_panel')
        self.assertEqual(r.s['active'],before['active']);self.assertEqual(r.s['attempted'],before['attempted'])
        self.assertEqual(r.s['completed'],before['completed']);r.action.assert_not_called();r.completed.assert_not_called()


class StorySkipDispatchTests(unittest.TestCase):
    def make_runner(self,tutorial=False):
        r=runner.Runner.__new__(runner.Runner);r.frame=story(tutorial)
        r.s={'active':{'key':'stage'},'attempted':{'stage':{'cost':8}},'completed':{}}
        r.ticket=None;r.save=Mock();r.ensure_game=Mock()
        r.pc=Mock();r.pc.frame_window=('same-window',);r.pc.frame_viewport=('same-viewport',)
        def capture():
            r.frame=story(tutorial)
            return r.frame
        r.capture=Mock(side_effect=capture)
        r._capture_pixels=Mock(return_value=(r.frame.image,(1600,900)))
        label='跳过教学' if tutorial else '跳过'
        r.ocr=Mock(return_value=([[label,.999]],None))
        return r

    def dispatch(self,r,root,events=None,tutorial=False):
        kind='跳过已识别的免费地图教学' if tutorial else '跳过剧情'
        word=top_right_skip_control(r.frame.words,tutorial=tutorial)
        with patch.object(runner,'ROOT',Path(root)),patch.object(runner,'event') as log:
            if events is not None:log.side_effect=lambda kind,**kw:events.append((kind,kw))
            return r.action(kind,word)

    def test_fresh_page_and_independent_label_allow_one_current_control_tap(self):
        for tutorial in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                r=self.make_runner(tutorial);before=copy.deepcopy(r.s);events=[]
                self.dispatch(r,tmp,events,tutorial)
                r.pc.tap.assert_called_once_with(1510.0,47.0)
                r.capture.assert_called_once();r._capture_pixels.assert_called_once()
                self.assertEqual(r.s['active'],before['active']);self.assertEqual(r.s['attempted'],before['attempted'])
                self.assertEqual(r.ocr.call_count,2)
                proof=next(v for k,v in events if k=='skip_control_verified')
                self.assertTrue((Path(tmp)/proof['evidence']).is_file());self.assertEqual(len(proof['image_sha256']),64)

    def test_adb_uses_the_same_verified_label_without_window_or_coordinate_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner();r.pc=None;r.adb=Mock()
            self.dispatch(r,tmp)
            r.adb.assert_called_once_with('shell','input','tap',1510,47)
            r=self.make_runner();r.pc=None;r.adb=Mock();r.ocr.return_value=([['频道',.999]],None)
            self.assertIs(self.dispatch(r,tmp),False);r.adb.assert_not_called()

    def test_state_save_happens_before_quick_capture_not_between_verification_and_tap(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner();order=[]
            r.save.side_effect=lambda:order.append('save')
            def pixels():order.append('quick_capture');return r.frame.image,(1600,900)
            r._capture_pixels.side_effect=pixels;r.pc.tap.side_effect=lambda *a:order.append('tap')
            self.dispatch(r,tmp)
            self.assertIn('save',order[:order.index('quick_capture')])
            self.assertNotIn('save',order[order.index('quick_capture'):order.index('tap')])
            self.assertEqual(order[-1],'save')

    def test_page_changed_to_chat_result_or_dialog_cancels_before_local_check(self):
        for changed in [chat(),chat(True),frame([('CLEAR',800,550)]),
                        frame([('跳过',1510,47),('确认',935,575),('取消',666,575)]),
                        frame([('跳过',1510,47),('体力不足',800,450)])]:
            with tempfile.TemporaryDirectory() as tmp:
                r=self.make_runner();before=copy.deepcopy(r.s)
                def capture():r.frame=changed;return changed
                r.capture.side_effect=capture
                self.assertIs(self.dispatch(r,tmp),False)
                r.pc.tap.assert_not_called();r._capture_pixels.assert_not_called()
                self.assertEqual(r.s['active'],before['active']);self.assertEqual(r.s['attempted'],before['attempted'])

    def test_label_disappearing_during_full_page_ocr_never_taps_old_chat_location(self):
        for results in [[],[['跳过',.979]],[['频道',.999]],[['跳过',.999]]*2,[['跳过>',.999]]]:
            with tempfile.TemporaryDirectory() as tmp:
                r=self.make_runner();r.ocr.return_value=(results,None);events=[]
                self.assertIs(self.dispatch(r,tmp,events),False);r.pc.tap.assert_not_called()
                self.assertNotIn('action',[k for k,v in events]);self.assertEqual(r.s['completed'],{})

    def test_disagreeing_dual_reads_and_unverified_text_box_cannot_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner();r.ocr.side_effect=[([['跳过',.999]],None),([['频道',.999]],None)]
            self.assertIs(self.dispatch(r,tmp),False);r.pc.tap.assert_not_called()
            for box in ([[0,0],[30,0],[30,20],[0,20]],[[1490,30],[1491,30],[1491,60],[1490,60]]):
                r=self.make_runner();fresh=story();fresh.words[0]['box']=box
                def capture():r.frame=fresh;return fresh
                r.capture.side_effect=capture
                self.assertIs(self.dispatch(r,tmp),False);r.pc.tap.assert_not_called()

    def test_original_weak_or_coordinate_only_input_cannot_use_guard_as_new_permission(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)),patch.object(runner,'event'):
            r=self.make_runner();r.frame.words[0]['score']=.7
            self.assertIs(r.action('跳过剧情',r.frame.words[0]),False);r.capture.assert_not_called();r.pc.tap.assert_not_called()
            with self.assertRaises(RuntimeError):r.action('跳过剧情',xy=(1510,47))
            r.pc.tap.assert_not_called()

    def test_target_movement_window_change_and_capture_errors_are_not_retried(self):
        for change in ('control','window','viewport','size','capture'):
            with tempfile.TemporaryDirectory() as tmp:
                r=self.make_runner()
                if change=='control':
                    changed=frame([('跳过',1550,47)])
                    def capture():r.frame=changed;return changed
                    r.capture.side_effect=capture
                    self.assertIs(self.dispatch(r,tmp),False)
                else:
                    def pixels():
                        if change=='capture':raise PcSafetyError('capture failed')
                        if change=='window':r.pc.frame_window=('changed',)
                        if change=='viewport':r.pc.frame_viewport=('changed',)
                        return r.frame.image,((1280,720) if change=='size' else (1600,900))
                    r._capture_pixels.side_effect=pixels
                    with self.assertRaises((PcSafetyError,RuntimeError)):self.dispatch(r,tmp)
                r.pc.tap.assert_not_called()

    def test_transient_blank_capture_only_cancels_and_reobserves_with_no_input(self):
        from pc_message_backend import CaptureUnavailable
        for full in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                r=self.make_runner()
                (r.capture if full else r._capture_pixels).side_effect=CaptureUnavailable('blank frame')
                self.assertIs(self.dispatch(r,tmp),False);r.pc.tap.assert_not_called()
                self.assertEqual(r.s['completed'],{})

    def test_expired_local_check_and_evidence_write_failure_never_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner()
            def slow_ocr(image,**kwargs):
                result=r.ocr.return_value
                clock[0]+=1.01
                return result
            clock=[time.time()];r.ocr.side_effect=slow_ocr
            with patch.object(runner.time,'time',side_effect=lambda:clock[0]):
                self.assertIs(self.dispatch(r,tmp),False)
            r.pc.tap.assert_not_called()
            r=self.make_runner()
            with patch.object(Path,'write_bytes',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):self.dispatch(r,tmp)
            r.pc.tap.assert_not_called()

    def test_animated_background_does_not_require_whole_screen_stability(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner()
            animated=r.frame.image.copy();animated[150:800,:]=200
            r._capture_pixels.return_value=(animated,(1600,900))
            self.dispatch(r,tmp);r.pc.tap.assert_called_once()

    def test_dimmed_or_replaced_label_patch_never_passes_on_text_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner();changed=r.frame.image.copy();changed[35:60,1490:1530]=0
            r._capture_pixels.return_value=(changed,(1600,900))
            self.assertIs(self.dispatch(r,tmp),False);r.pc.tap.assert_not_called()

    def test_action_log_delay_cannot_extend_local_target_lifetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner();clock=[time.time()]
            def log(kind,**kw):
                if kind=='action':clock[0]+=1.01
            with patch.object(runner,'ROOT',Path(tmp)),patch.object(runner,'event',side_effect=log),patch.object(runner.time,'time',side_effect=lambda:clock[0]):
                from pc_backend import FrameExpired
                with self.assertRaises(FrameExpired):r.action('跳过剧情',r.frame.words[0])
            r.pc.tap.assert_not_called()

    def test_original_persistence_failure_never_captures_or_sends(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.make_runner();r.save.side_effect=OSError('state write denied')
            with self.assertRaises(OSError):self.dispatch(r,tmp)
            r.capture.assert_not_called();r.pc.tap.assert_not_called()


class PrivateChatReplayTests(unittest.TestCase):
    def test_private_incident_is_chat_not_underlying_victory(self):
        folder=os.environ.get('EPIC7_CHAT_GUARD_FIXTURE')
        if not folder:raise unittest.SkipTest('Private chat capture not distributed')
        root=Path(folder);data=json.loads((root/'chat-ocr.json').read_text(encoding='utf-8-sig'))
        f=runner.Frame(cv2.imread(str(root/'chat.png')),[(w['box'],w['text'],w['score']) for w in data['words']])
        self.assertEqual(runner.classify(f),'chat_panel')
        self.assertIsNone(top_right_skip_control(f.words))

    def test_private_story_label_survives_real_production_crop_ocr(self):
        folder=os.environ.get('EPIC7_CHAT_GUARD_FIXTURE')
        if not folder:raise unittest.SkipTest('Private story capture not distributed')
        root=Path(folder)
        if not (root/'story.png').exists():raise unittest.SkipTest('Private story capture not distributed')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        image=cv2.imread(str(root/'story.png'));results,_=ocr(image);f=runner.Frame(image,results)
        self.assertEqual(runner.classify(f),'story')
        with tempfile.TemporaryDirectory() as tmp:
            r=StorySkipDispatchTests().make_runner();r.frame=f;r.ocr=ocr
            def capture():r.frame=f;return f
            r.capture.side_effect=capture;r._capture_pixels.return_value=(image,(1600,900))
            StorySkipDispatchTests().dispatch(r,tmp)
            target=top_right_skip_control(f.words)
            r.pc.tap.assert_called_once_with(target['x'],target['y'])


if __name__=='__main__':unittest.main()
