"""No native input: Dimension recognition, original-history preservation and worker tests."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from abyss_core import Token,Observation
from dimension_core import Action,Reading,classify,plan,same_reading
from dimension_journal import DimensionJournal
from task_blockers import TaskAttention


def token(text,x=.5,y=.5,score=.99):return Token(text,x*1200-20,y*675-10,40,20,score=score)
def summary(extra=()):
    return Observation(1200,675,[token('星之旅程',.5,.07),token('完成节点',.45,.18),
        token('最终分数',.1,.73),token('获得星辰气息',.56,.73),token('点击关闭',.5,.96),*extra])
def hub(stage='1',extra=()):
    return Observation(1200,675,[token('次元探查',.1,.04),token('研究'),token('舰桥'),
        token('探查记录档案'),token('次元核共鸣'),token('第'+stage+'阶段',.8,.82),token('开始探查',.86,.92),*extra])

class RecognitionTests(unittest.TestCase):
    def test_summary_not_a_clear(self):
        r=classify(summary());self.assertEqual(r.scene,'dimension_summary');self.assertIsNone(r.stage)
        self.assertEqual(plan(r).kind,'navigate');self.assertIn('不记通关',plan(r).name)
    def test_summary_requires_every_independent_anchor(self):
        for i in range(5):
            o=summary();o.tokens.pop(i)
            self.assertEqual(classify(o).scene,'unknown')
    def test_low_confidence_close_never_authorizes_input(self):
        o=summary();o.tokens[-1]=token('点击关闭',.5,.96,.79)
        self.assertIsNone(plan(classify(o)))
    def test_missing_confidence_never_authorizes_input(self):
        o=summary();o.tokens[-1]=token('点击关闭',.5,.96,None)
        self.assertIsNone(plan(classify(o)))
    def test_wrong_close_region_rejected(self):
        o=summary();o.tokens[-1]=token('点击关闭',.1,.3)
        self.assertIsNone(plan(classify(o)))
    def test_risk_overlay_blocks_underlying_summary(self):
        for text in ('购买体力','兑换','是否复活','重新挑战','确定','确认','取消','天空石不足','放弃探查','是否使用道具'):
            r=classify(summary([token(text)]))
            with self.subTest(text=text),self.assertRaises(TaskAttention):plan(r)
    def test_unknown_overlay_blocks_even_if_summary_anchors_remain(self):
        with self.assertRaises(TaskAttention):plan(classify(summary([token('新的系统通知')])))
    def test_merged_confirmation_caption_is_not_missed(self):
        with self.assertRaises(TaskAttention):plan(classify(summary([token('是否继续探查？请确认')])))
    def test_weak_risk_text_still_blocks(self):
        with self.assertRaises(TaskAttention):plan(classify(summary([token('购买',score=.3)])))
    def test_capacity_is_not_defeat(self):
        r=classify(summary([token('装备背包已满')]))
        self.assertEqual(r.scene,'attention');self.assertIn('装备',r.detail)
    def test_defeat_stops_without_retry(self):
        with self.assertRaises(TaskAttention):plan(classify(Observation(1200,675,[token('战斗失败')])))
    def test_hub_identifies_stage_but_does_not_start(self):
        for n in ('1','10','99'):
            r=classify(hub(n));self.assertEqual(r.stage,n)
            with self.assertRaises(TaskAttention):plan(r)
    def test_conflicting_hub_stage_is_unknown(self):
        self.assertEqual(classify(hub(extra=[token('第2阶段',.9,.82)])).scene,'unknown')
    def test_empty_unseen_choices_never_authorize_input(self):
        for texts in ([],['选择','确定'],['招募英雄','选择'],['普通战斗','开始战斗'],['事件','继续']):
            o=Observation(1200,675,[token(t) for t in texts])
            try:a=plan(classify(o))
            except TaskAttention:a=None
            self.assertIsNone(a)
    def test_entrance_needs_battle_menu_not_first_coordinate(self):
        o=Observation(1200,675,[token('战斗',.1,.04),token('一般'),token('活动'),token('赛季'),token('次元探查',.2,.3)])
        self.assertEqual(classify(o).scene,'dimension_entrance')
        o.tokens.pop(0);self.assertEqual(classify(o).scene,'unknown')
    def test_stability_requires_same_scene_stage_and_button(self):
        a=Reading('dimension_summary',token('点击关闭',.5,.96));b=Reading('dimension_summary',token('点击关闭',.51,.96))
        self.assertTrue(same_reading(a,b,1200,675))
        self.assertFalse(same_reading(a,Reading('unknown'),1200,675))
        self.assertFalse(same_reading(a,Reading('dimension_summary',token('点击关闭',.6,.96)),1200,675))
        self.assertFalse(same_reading(Reading('dimension_hub',stage='1'),Reading('dimension_hub',stage='2'),1200,675))
    def test_no_implicit_completion_or_paid_action_kind(self):
        self.assertIsNone(plan(Reading('unknown')))
        self.assertIsNone(plan(Reading('dimension_route',token('继续'))))

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.original={'attempted':{'old':{'outcome':'defeat'}},'completed':{'clear':{}},'active':{'key':'old'},'last_cleared':'clear'}
        (self.root/'state.json').write_text(json.dumps(self.original));self.before=(self.root/'state.json').read_bytes()
        self.journal=DimensionJournal(self.root)
        obs=summary();snap=SimpleNamespace(image=Image.new('RGB',(1200,675),'purple'),captured_at=time.monotonic())
        self.proof=self.journal.evidence(snap,obs,classify(obs),'test_setup')
    def tearDown(self):
        self.assertEqual((self.root/'state.json').read_bytes(),self.before);self.temp.cleanup()
    def test_registration_and_original_history_preserved(self):
        self.assertTrue((self.root/'dimension/registration.json').exists())
        self.assertEqual(self.journal.state['attempted'],{})
    def test_deleted_ledger_is_not_reinitialized(self):
        self.journal.path.unlink()
        with self.assertRaisesRegex(RuntimeError,'丢失或损坏'):DimensionJournal(self.root)
        self.assertFalse(self.journal.path.exists())
    def test_corrupt_ledger_is_not_reinitialized(self):
        self.journal.path.write_text('{}')
        with self.assertRaises(RuntimeError):DimensionJournal(self.root)
        self.assertEqual(self.journal.path.read_text(),'{}')
    def test_registration_mismatch_fails_closed(self):
        self.journal.state['registration_id']='other';self.journal.save()
        with self.assertRaises(RuntimeError):DimensionJournal(self.root)
    def test_unregistered_existing_files_cannot_be_discarded(self):
        (self.root/'dimension/registration.json').unlink()
        with self.assertRaises(RuntimeError):DimensionJournal(self.root)
    def test_intent_persists_before_input_and_is_not_repeatable(self):
        r=classify(summary());a=plan(r);ident=self.journal.reserve(r,a,self.proof)
        saved=json.loads(self.journal.path.read_text('utf-8'))
        self.assertEqual(saved['pending']['id'],ident)
        with self.assertRaises(TaskAttention):DimensionJournal(self.root).reserve(r,a,'other.png')
    def test_page_change_is_not_completion_evidence(self):
        r=classify(summary());self.journal.reserve(r,plan(r),self.proof)
        self.journal.observe(classify(hub()),'after.png')
        self.assertIsNone(self.journal.state['pending']);self.assertEqual(self.journal.state['completed'],{})
        self.assertIsNone(self.journal.state['last_cleared']);self.assertEqual(len(self.journal.state['events']),2)
    def test_same_page_does_not_clear_pending(self):
        r=classify(summary());self.journal.reserve(r,plan(r),self.proof);self.journal.observe(r,'after.png')
        self.assertIsNotNone(self.journal.state['pending'])
    def test_unverified_entry_and_choice_cannot_get_input_authority(self):
        for kind in ('enter','choice','retry','purchase','start_battle'):
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):
                self.journal.reserve(Reading('unknown'),Action('bad',token('开始'),kind,'1'),self.proof)
        self.assertEqual(self.journal.state['events'],[])
    def test_evidence_is_private_and_contains_exact_observation(self):
        o=summary();s=SimpleNamespace(image=Image.new('RGB',(1200,675),'purple'),captured_at=time.monotonic())
        name=self.journal.evidence(s,o,classify(o),'unit_test')
        self.assertTrue((self.journal.root/name).is_file());meta=json.loads((self.journal.root/name).with_suffix('.json').read_text('utf-8'))
        self.assertEqual(meta['reason'],'unit_test');self.assertEqual(meta['width'],1200)
        self.assertEqual(meta['tokens'][-1]['text'],'点击关闭');self.assertEqual(len(meta['image_sha256']),64)
    def test_tampered_missing_and_traversing_evidence_cannot_authorize_input(self):
        r=classify(summary());a=plan(r)
        for name in ('missing.png','../state.json'):
            with self.subTest(name=name),self.assertRaises((RuntimeError,OSError)):self.journal.reserve(r,a,name)
        (self.journal.root/self.proof).write_bytes(b'tampered')
        with self.assertRaises(RuntimeError):self.journal.reserve(r,a,self.proof)
        self.assertIsNone(self.journal.state['pending'])
    def test_forged_navigation_action_is_rejected(self):
        with self.assertRaises(RuntimeError):self.journal.reserve(classify(summary()),Action('开战',token('开始战斗')),self.proof)

    def test_write_failure_not_swallowed(self):
        with patch('dimension_journal.os.replace',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):self.journal.reserve(classify(summary()),plan(classify(summary())),self.proof)
        self.assertIsNone(json.loads(self.journal.path.read_text('utf-8'))['pending'])

class IntegrationTests(unittest.TestCase):
    def test_mode_in_all_entrypoints_and_portable_allowlist(self):
        import assistant_config,build_portable,assistant_status
        self.assertIn('次元探查',assistant_status.activity('run','dimension',False,True).title)
        for name in ('dimension_core.py','dimension_journal.py','dimension_worker.py'):self.assertIn(name,build_portable.SOURCES)
        for name in ('assistant_app.py','assistant_control.py'):
            self.assertIn("'saint_3_7','dimension'",(Path(__file__).resolve().parents[1]/name).read_text('utf-8'))
    def test_background_back_consumes_frame_and_checks_target(self):
        from assistant_transport import UnifiedTransport
        t=UnifiedTransport.__new__(UnifiedTransport);t.api=Mock();t.frame=object();frame=t.frame
        t._fresh=Mock();t.back(frame);t._fresh.assert_called_once_with(frame)
        t.api.escape.assert_called_once();self.assertIsNone(t.frame)
    def test_background_back_does_not_input_on_invalid_frame(self):
        from assistant_transport import UnifiedTransport
        t=UnifiedTransport.__new__(UnifiedTransport);t.api=Mock();t.frame=object()
        t._fresh=Mock(side_effect=RuntimeError('stale'))
        with self.assertRaises(RuntimeError):t.back(t.frame)
        t.api.escape.assert_not_called()

class PrivateObservedPages(unittest.TestCase):
    def test_each_recorded_page_matches_its_real_ocr(self):
        folder=Path(__file__).resolve().parents[1]/'.local/dimension-validation'
        paths=list(folder.glob('*-intent.json'))
        if not paths:raise unittest.SkipTest('本机次元截图/OCR不随源码分发')
        scenes=set()
        for p in paths:
            stem=p.name.removesuffix('-intent.json');meta=json.loads((folder/(stem+'-ocr.json')).read_text('utf-8-sig'))
            with Image.open(folder/(stem+'.png')) as im:w,h=im.size
            words=[]
            for row in meta['words']:
                b=row['box'];x=min(p[0] for p in b);y=min(p[1] for p in b)
                words.append(Token(row['text'],x,y,max(p[0] for p in b)-x,max(p[1] for p in b)-y,score=row['score']))
            reading=classify(Observation(w,h,words));scenes.add(reading.scene)
            self.assertNotEqual(reading.scene,'unknown',p.name)
        self.assertTrue({'dimension_summary','dimension_tutorial_skip','dimension_hub','dimension_difficulty','dimension_archive_page'}<=scenes)

class WorkerSafetyTests(unittest.TestCase):
    def exercise(self,reading,write_failure=False,tap_failure=False,observe=False,stop=False):
        from dimension_worker import run
        from assistant_worker import StopRun
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=b'{"attempted":{"old":{}},"completed":{},"active":{"key":"old"}}'
            (root/'state.json').write_bytes(original)
            if stop:(root/'STOP').write_text('user stop')
            control=Mock();control.attention.side_effect=StopRun()
            snap=SimpleNamespace(image=Image.new('RGB',(1200,675),'purple'),captured_at=1)
            transport=Mock()
            if tap_failure:transport.tap.side_effect=RuntimeError('delivery unknown')
            request={'settings':{'task':'dimension','observe':observe},'target':{'client':'pc'},'once':observe}
            import itertools
            with patch('assistant_config.validate_run',return_value=(root,{})),patch('assistant_transport.UnifiedTransport',return_value=transport),patch('assistant_worker.capture_fresh',return_value=snap),patch('rapidocr_onnxruntime.RapidOCR',return_value=Mock(return_value=([],None))),patch('dimension_worker.classify',return_value=reading),patch('dimension_worker.time.monotonic',side_effect=itertools.count(0,20)):
                if write_failure:
                    with patch('dimension_journal.DimensionJournal.reserve',side_effect=PermissionError('disk full')):
                        with self.assertRaises(PermissionError):run(request,control)
                elif observe:run(request,control)
                else:
                    with self.assertRaises((StopRun,RuntimeError)):run(request,control)
            self.assertEqual((root/'state.json').read_bytes(),original)
            if observe:self.assertFalse((root/'dimension').exists())
            return transport,control
    def test_hub_pauses_with_zero_input(self):
        transport,control=self.exercise(classify(hub()))
        transport.tap.assert_not_called();transport.back.assert_not_called();control.attention.assert_called_once()
    def test_unknown_is_evidenced_and_never_clicked(self):
        transport,control=self.exercise(Reading('unknown'))
        transport.tap.assert_not_called();transport.back.assert_not_called();control.attention.assert_called_once()
    def test_unchanged_page_is_not_clicked_again(self):
        transport,control=self.exercise(classify(summary()))
        transport.tap.assert_called_once();control.attention.assert_called_once()
    def test_journal_write_failure_prevents_input(self):
        transport,control=self.exercise(classify(summary()),write_failure=True)
        transport.tap.assert_not_called();transport.back.assert_not_called()
    def test_delivery_exception_does_not_retry(self):
        transport,control=self.exercise(classify(summary()),tap_failure=True)
        transport.tap.assert_called_once();transport.back.assert_not_called()
    def test_internal_observer_does_not_create_history_or_input(self):
        transport,control=self.exercise(classify(summary()),observe=True)
        transport.tap.assert_not_called();transport.back.assert_not_called()
    def test_new_stop_vetoes_input(self):
        transport,control=self.exercise(classify(summary()),stop=True)
        transport.tap.assert_not_called();transport.back.assert_not_called()

if __name__=='__main__':unittest.main()
