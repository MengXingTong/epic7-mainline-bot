"""Real evidence I/O under Windows paths; game inputs and progress are synthetic."""
import copy
import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import runner
import test_walking_map as walking


class EvidenceFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='e7-evidence-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'中文 空格进度';self.root.mkdir()
        self.r=runner.Runner.__new__(runner.Runner)
        self.r.frame=runner.Frame(runner.np.full((900,1600,3),42,runner.np.uint8),[])
        self.r.s=dict(attempted={'kept':{'outcome':'defeat'}},completed={'old':{'proof':'kept'}},active=None)
        self.r.adb=Mock();self.r.action=Mock()
        root_patch=patch.object(runner,'ROOT',self.root);root_patch.start();self.addCleanup(root_patch.stop)
    def assert_image(self,relative):
        p=self.root/relative
        self.assertEqual(p.parent,self.root/'evidence')
        self.assertIsNone(re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]',p.name))
        decoded=runner.cv2.imdecode(runner.np.frombuffer(p.read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
        self.assertTrue(runner.np.array_equal(decoded,self.r.frame.image))
        return p
    def test_colon_business_id_is_a_real_valid_png_filename(self):
        label='story-entry-walk:synthetic-region:1'
        p=self.assert_image(self.r.evidence(label))
        self.assertIn(hashlib.sha256(label.encode()).hexdigest()[:16],p.name)
    def test_unsafe_paths_device_names_and_control_characters_stay_single_component(self):
        labels=['../escape','..\\escape','C:\\other\\entry','a<>:"/\\|?*b','trailing. ',
                'CON','PRN','AUX','NUL','COM1','LPT9','\x00\x01\x1f\x7f','...','']
        for label in labels:
            with self.subTest(label=repr(label)):self.assert_image(self.r.evidence(label))
        self.assertFalse((self.root.parent/'escape').exists())
    def test_long_unicode_labels_are_bounded_in_windows_utf16_units(self):
        for label in ('界'*1000,'😀'*1000,'x'*10000):
            p=self.assert_image(self.r.evidence(label))
            self.assertLessEqual(len(p.name.encode('utf-16-le'))//2,120)
    def test_unpaired_surrogate_is_sanitized_without_rewriting_source_hash(self):
        label='node-\ud800-end';p=self.assert_image(self.r.evidence(label))
        self.assertIn(hashlib.sha256(label.encode('utf-8',errors='surrogatepass')).hexdigest()[:16],p.name)
    def test_distinct_labels_with_same_sanitized_text_keep_distinct_hashes(self):
        fixed=runner.dt.datetime(2026,11,10,1,2,3,tzinfo=runner.TZ)
        with patch.object(runner.dt,'datetime') as clock:
            clock.now.return_value=fixed
            a=runner.evidence_filename_prefix('a:b');b=runner.evidence_filename_prefix('a?b')
        self.assertNotEqual(a,b);self.assertIn('-a-b-',a);self.assertIn('-a-b-',b)
    def test_same_label_and_clock_never_overwrite_earlier_evidence(self):
        original=self.r.frame.image.copy()
        with patch.object(runner,'evidence_filename_prefix',return_value='010203-same-label-same-hash-'):
            a=self.r.evidence('same');before=(self.root/a).read_bytes()
            self.r.frame.image[:]=80;b=self.r.evidence('same')
        self.assertNotEqual(a,b);self.assertEqual((self.root/a).read_bytes(),before)
        decoded=runner.cv2.imdecode(runner.np.frombuffer(before,runner.np.uint8),runner.cv2.IMREAD_COLOR)
        self.assertTrue(runner.np.array_equal(decoded,original));self.assert_image(b)
    def test_existing_legacy_evidence_and_progress_remain_byte_identical(self):
        folder=self.root/'evidence';folder.mkdir();old=folder/'010203-old-label.png';old.write_bytes(b'original evidence')
        for name in ('state.json','events.jsonl','entry-intent.json'):(self.root/name).write_bytes(b'original record')
        state=copy.deepcopy(self.r.s);self.r.evidence('old-label')
        self.assertEqual(old.read_bytes(),b'original evidence');self.assertEqual(self.r.s,state)
        for name in ('state.json','events.jsonl','entry-intent.json'):self.assertEqual((self.root/name).read_bytes(),b'original record')
    def test_encode_failure_propagates_before_file_creation(self):
        with patch.object(runner.cv2,'imencode',return_value=(False,None)):
            with self.assertRaisesRegex(RuntimeError,'编码失败'):self.r.evidence('entry')
        self.assertFalse((self.root/'evidence').exists());self.r.adb.assert_not_called()
    def test_create_failure_is_fatal_not_a_best_effort_display_warning(self):
        with patch.object(runner.tempfile,'NamedTemporaryFile',side_effect=OSError(22,'invalid file')):
            with self.assertRaises(OSError):self.r.evidence('entry')
        self.r.adb.assert_not_called();self.r.action.assert_not_called()
    def test_short_write_flush_and_close_failures_all_propagate(self):
        payload=runner.cv2.imencode('.png',self.r.frame.image)[1].tobytes()
        for phase in ('write','flush','close'):
            stream=Mock();stream.name=str(self.root/'evidence'/'synthetic.png')
            stream.write.return_value=1 if phase=='write' else len(payload)
            manager=Mock();manager.__enter__=Mock(return_value=stream);manager.__exit__=Mock(return_value=False)
            if phase=='flush':stream.flush.side_effect=OSError('flush failed')
            if phase=='close':manager.__exit__.side_effect=OSError('close failed')
            with self.subTest(phase=phase),patch.object(runner.tempfile,'NamedTemporaryFile',return_value=manager),patch.object(runner.os,'fsync'):
                with self.assertRaises(OSError):self.r.evidence('entry')
        self.r.adb.assert_not_called()
    def test_fsync_failure_is_fatal_and_does_not_return_an_evidence_reference(self):
        original=copy.deepcopy(self.r.s)
        with patch.object(runner.os,'fsync',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.r.evidence('entry')
        self.assertEqual(self.r.s,original);self.r.adb.assert_not_called()
    def test_invalid_label_type_is_rejected_before_writing(self):
        with self.assertRaises(TypeError):self.r.evidence(None)
        self.assertFalse((self.root/'evidence').exists())


class WalkingEvidenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='e7-walk-real-evidence-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'中文 空格';self.root.mkdir()
        self.case=walking.WalkingMapTests();self.r,self.story=self.case.make()
        self.r.evidence=runner.Runner.evidence.__get__(self.r,runner.Runner)
        root_patch=patch.object(runner,'ROOT',self.root);root_patch.start();self.addCleanup(root_patch.stop)
        self.case.apply(self.r,self.story,self.r.frame)
    def test_shared_walking_entry_with_real_evidence_keeps_colon_id_and_sends_once(self):
        old=copy.deepcopy({k:self.r.s[k] for k in ('attempted','completed','last_cleared','entry_dispatches')})
        snapshots=[];self.r.action.side_effect=lambda *a,**kw:snapshots.append(copy.deepcopy(self.story.book))
        self.case.enter(self.r,self.story)
        active=self.story.book['active'];original=snapshots[0]['active']
        self.assertIn(':',active['stage']);self.assertTrue((self.root/active['evidence']).is_file())
        self.assertIsNone(re.search(r'[<>:"/\\|?*]',Path(active['evidence']).name))
        self.assertEqual(original['stage'],active['stage'])
        self.assertEqual(snapshots[0]['entry_dispatches'][active['id']][0]['status'],'reserved')
        self.assertEqual(self.story.book['entry_dispatches'][active['id']][0]['status'],'sent')
        count=self.r.action.call_count;self.case.enter(self.r,self.story)
        self.assertEqual(self.r.action.call_count,count);self.assertEqual(len(self.story.book['attempted']),1)
        self.assertEqual({k:self.r.s[k] for k in old},old)
    def test_entry_evidence_failure_never_reserves_or_dispatches_resource_input(self):
        create=runner.tempfile.NamedTemporaryFile
        def checked(*args,**kwargs):
            if '-story-entry-' in kwargs.get('prefix',''):raise OSError(22,'synthetic critical evidence failure')
            return create(*args,**kwargs)
        count=self.r.action.call_count
        with patch.object(runner.tempfile,'NamedTemporaryFile',side_effect=checked):
            with self.assertRaises(OSError):self.case.enter(self.r,self.story)
        self.assertIsNone(self.story.book['active']);self.assertEqual(self.story.book['attempted'],{})
        self.assertEqual(self.story.book.get('entry_dispatches',{}),{})
        self.assertEqual(self.r.action.call_count,count);self.r.adb.assert_not_called()
    def test_actual_entry_write_or_fsync_failure_never_sends_input(self):
        # Bind and acknowledge the free preparation first, so the failure is
        # precisely the resource-entry evidence, not an earlier display write.
        f=walking.prep();self.r.frame=f
        stage,error=self.story.walking.preparation(f);self.assertIsNone(error)
        nav=next(n for n in self.story.walking.data['navigation'] if n['id']==stage['map_binding']['navigation_id'])
        nav['accepted_at']=1
        count=self.r.action.call_count
        with patch.object(runner.os,'fsync',side_effect=OSError('critical evidence flush')):
            with self.assertRaises(OSError):self.case.enter(self.r,self.story)
        self.assertEqual(self.r.action.call_count,count);self.assertEqual(self.story.book['attempted'],{})
        self.assertIsNone(self.story.book['active']);self.r.adb.assert_not_called()


if __name__=='__main__':unittest.main()
