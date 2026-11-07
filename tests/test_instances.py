"""Offline multi-instance regression: fake endpoints only; never sends game input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from assistant_config import atomic_json, load_settings, validate_run
from assistant_instances import (reserve_window, slot_home, resume_slot, exclusive_target,
    target_key, remember_target, known_target_root, NamedLeases)
from assistant_portable import initialize_selected, registered_root

PC = dict(client='pc', hwnd=90123456, pid=123, created=456, exe='EpicSeven.exe', title='第七史诗')
MU = dict(client='mumu', serial='127.0.0.1:16384', package='epic7')


class FakeLeases:
    def __init__(self):
        self.live = set()
        self.closed = []
        self.legacy = set()
    def acquire(self, name):
        if name in self.live:
            return None
        self.live.add(name)
        return name
    def exists(self, name):
        return name in self.legacy
    def release(self, handle):
        self.live.remove(handle)
        self.closed.append(handle)


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.api = FakeLeases()
    def reserve(self, number=None, **kw):
        slot = reserve_window(self.base, number, api=self.api, alive=lambda _: False, **kw)
        self.addCleanup(slot.close)
        return slot
    def test_second_and_third_windows_are_allowed_and_isolated(self):
        a, b, c = self.reserve(), self.reserve(), self.reserve()
        self.assertEqual([a.number, b.number, c.number], [1, 2, 3])
        self.assertEqual(a.home, self.base)
        self.assertEqual(b.home, self.base/'instances'/'2')
        for slot in (a, b, c):
            atomic_json(slot.home/'settings.json', {'number': slot.number})
            atomic_json(slot.home/'active-run.json', {'run_id': str(slot.number)})
        self.assertEqual(json.loads((a.home/'active-run.json').read_text())['run_id'], '1')
        self.assertEqual(json.loads((b.home/'settings.json').read_text())['number'], 2)
    def test_reopen_reuses_slot_and_keeps_history_and_stop(self):
        a = self.reserve()
        root, _ = initialize_selected(True, a.home)
        original = (root/'state.json').read_bytes()
        (root/'STOP').write_text('keep')
        a.close()
        reopened = self.reserve()
        self.assertEqual(reopened.number, 1)
        self.assertEqual(registered_root(reopened.home), root)
        self.assertEqual((root/'state.json').read_bytes(), original)
        self.assertEqual((root/'STOP').read_text(), 'keep')
    def test_legacy_singleton_reserves_only_first_slot(self):
        self.api.legacy.add(r'Local\Epic7UnifiedAssistant')
        second = self.reserve()
        self.assertEqual(second.number, 2)
        with self.assertRaises(ValueError):
            reserve_window(self.base, 1, api=self.api, alive=lambda _: False)
    def test_orphan_worker_keeps_its_slot_reserved(self):
        slot = reserve_window(self.base, api=self.api, alive=lambda h: h == self.base)
        self.addCleanup(slot.close)
        self.assertEqual(slot.number, 2)
    def test_explicit_busy_slot_never_takes_over(self):
        self.reserve(2)
        with self.assertRaises(ValueError):
            self.reserve(2)
    def test_bad_slot_is_rejected(self):
        for number in (0, -1, True, '2'):
            with self.subTest(number=number), self.assertRaises(ValueError):
                slot_home(self.base, number)
    def test_liveness_error_releases_handle_and_does_not_claim_free(self):
        with self.assertRaises(OSError):
            reserve_window(self.base, api=self.api, alive=Mock(side_effect=OSError('unreadable')))
        self.assertFalse(self.api.live)
    def test_resume_finds_original_slot_only(self):
        run = 'a'*32
        path = slot_home(self.base, 3)/'runs'/run/'request.json'
        atomic_json(path, {'run_id': run})
        self.assertEqual(resume_slot(self.base, run), 3)
        with self.assertRaises(ValueError):
            resume_slot(self.base, 'b'*32)
        with self.assertRaises(ValueError):
            resume_slot(self.base, '../../other')
    def test_secondary_does_not_inherit_primary_history_or_settings(self):
        primary = self.base/'.local'/'pc'
        primary.mkdir(parents=True)
        atomic_json(primary/'preferences.json', {'data_dir': str(self.base/'must-not-use')})
        with patch('assistant_config.CODE_ROOT', self.base), patch('assistant_portable.enabled', return_value=False):
            value = load_settings(slot_home(self.base, 2), inherit_legacy=False)
        self.assertFalse(value['data_dir'])
        self.assertEqual(value['mumu'], {})
    def test_validation_uses_selected_home_not_primary_registration(self):
        initialize_selected(True, self.base)
        second = slot_home(self.base, 2)
        root, state = validate_run({'task':'mainline', 'pc_input':'messages'}, PC, home=second)
        self.assertEqual(root, second/'observations')
        self.assertEqual(state['attempted'], {})
        self.assertFalse((second/'profiles').exists())
    def test_same_endpoint_is_blocked_even_with_another_task_or_package(self):
        for target in (PC, MU):
            with self.subTest(target=target), exclusive_target(target, self.base, api=self.api):
                other = dict(target, package='other', label='other', task='abyss')
                with self.assertRaises(RuntimeError):
                    with exclusive_target(other, self.base, api=self.api):
                        self.fail('second writer')
        self.assertFalse(self.api.live)
    def test_different_endpoints_can_run_together(self):
        with exclusive_target(PC, self.base, api=self.api), exclusive_target(MU, self.base, api=self.api), exclusive_target(dict(PC, hwnd=90123457), self.base, api=self.api):
            self.assertEqual(len(self.api.live), 3)
    def test_localhost_aliases_share_one_lock(self):
        for alias in ('localhost:16384', '127.0.0.1:016384', '[::1]:16384'):
            self.assertEqual(target_key(dict(MU, serial=alias)), target_key(MU))
    def test_lock_releases_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            with exclusive_target(PC, self.base, api=self.api):
                raise RuntimeError('simulated')
        with exclusive_target(PC, self.base, api=self.api):
            pass
        self.assertFalse(self.api.live)
    def test_preupgrade_worker_blocks_same_target_before_input(self):
        folder = self.base/'runs'/'old'
        atomic_json(self.base/'active-run.json', {'run_id':'old', 'run_dir':str(folder), 'worker_pid':12345})
        atomic_json(folder/'request.json', {'run_id':'old', 'target':PC})
        with self.assertRaises(RuntimeError):
            with exclusive_target(PC, self.base, api=self.api, alive=lambda _: True):
                self.fail('must not dispatch')
        with exclusive_target(MU, self.base, api=self.api, alive=lambda _: True):
            pass
    def test_known_target_history_is_referenced_in_place_from_other_slot(self):
        root, _ = initialize_selected(True, self.base)
        state = {'attempted':{'S1':{'outcome':'defeat'}}, 'completed':{}, 'active':{'key':'S1'}}
        atomic_json(root/'state.json', state)
        remember_target(MU, root, self.base)
        before = (root/'state.json').read_bytes()
        self.assertEqual(known_target_root(dict(MU, serial='localhost:16384'), self.base), root)
        self.assertEqual((root/'state.json').read_bytes(), before)
        (root/'state.json').unlink()
        with self.assertRaises(ValueError):
            known_target_root(MU, self.base)
        self.assertFalse((root/'state.json').exists())
    def test_recycled_pc_window_does_not_infer_account_history(self):
        root, _ = initialize_selected(True, self.base)
        remember_target(PC, root, self.base)
        self.assertIsNone(known_target_root(dict(PC, created=789), self.base))
    def test_conflicting_histories_are_not_auto_selected(self):
        a, _ = initialize_selected(True, self.base)
        home = slot_home(self.base, 2)
        b, _ = initialize_selected(True, home)
        remember_target(MU, a, self.base)
        remember_target(MU, b, home)
        with self.assertRaises(ValueError):
            known_target_root(MU, self.base)
    def test_target_lease_precedes_profile_and_task(self):
        from assistant_worker import run_request
        folder = self.base/'runs'/'new'
        folder.mkdir(parents=True)
        request = {'run_id':'new', 'run_dir':str(folder), 'home':str(self.base),
                   'instance_base':str(self.base), 'target':PC, 'settings':{'task':'mainline'}}
        with patch('assistant_instances.exclusive_target', side_effect=RuntimeError('busy')), \
             patch('assistant_worker.prepare_selected_profile') as prepare, \
             patch('assistant_worker.validate_run') as validate, \
             patch('assistant_worker.mainline_run') as dispatch:
            run_request(request)
        prepare.assert_not_called(); validate.assert_not_called(); dispatch.assert_not_called()
        self.assertEqual(json.loads((folder/'status.json').read_text())['mode'], 'blocked')


    def test_secondary_known_profile_reuses_original_state_without_ocr(self):
        from assistant_worker import prepare_selected_profile
        root,_=initialize_selected(True,self.base)
        remember_target(MU,root,self.base)
        original=(root/'state.json').read_bytes()
        second=slot_home(self.base,2)
        request={'run_id':'test','run_dir':str(second/'runs'/'test'),'home':str(second),'instance_base':str(self.base),'target':MU,
                 'settings':{},'user_selected_profile':True}
        with patch('assistant_transport.UnifiedTransport') as transport:
            self.assertEqual(prepare_selected_profile(request,Mock()),root)
        transport.assert_not_called()
        self.assertEqual(registered_root(second),root)
        self.assertEqual((root/'state.json').read_bytes(),original)
        self.assertFalse((second/'profiles').exists())
    def test_secondary_reuse_preserves_original_abyss_ledger_path(self):
        from assistant_instances import abyss_history_path
        from assistant_portable import register_existing
        root,_=initialize_selected(True,self.base)
        ledger=self.base/'abyss-history.json'
        atomic_json(ledger,{'schema':1,'clients':{'old':{'attempted':{'58':{}},'completed':{}}}})
        before=ledger.read_bytes()
        second=slot_home(self.base,2)
        register_existing(root,second)
        request={'home':str(second),'instance_base':str(self.base),'settings':{'data_dir':str(root)}}
        self.assertEqual(abyss_history_path(request),ledger)
        self.assertEqual(ledger.read_bytes(),before)
        self.assertFalse((second/'abyss-history.json').exists())
    def test_cli_requires_explicit_instance_when_other_worker_runs(self):
        import assistant_control
        with patch.object(assistant_control,'HOME',self.base), \
             patch('assistant_instances.worker_alive',return_value=True), \
             patch('sys.argv',['assistant_control.py','stop']):
            slot_home(self.base,2).mkdir(parents=True)
            with self.assertRaises(ValueError):assistant_control.main()
        self.assertFalse((self.base/'gui-command.json').exists())
    def test_cli_explicit_stop_only_updates_selected_run(self):
        import assistant_control
        for number in (1,2):
            home=slot_home(self.base,number);folder=home/'runs'/str(number)
            atomic_json(home/'active-run.json',{'run_id':str(number),'run_dir':str(folder),'worker_pid':123})
            atomic_json(folder/'status.json',{'run_id':str(number),'mode':'run'})
            atomic_json(folder/'control.json',{'run_id':str(number),'action':'run'})
        before=(self.base/'runs'/'1'/'control.json').read_bytes()
        with patch.object(assistant_control,'HOME',self.base),patch('sys.argv',['assistant_control.py','--instance','2','stop']):
            assistant_control.main()
        self.assertEqual((self.base/'runs'/'1'/'control.json').read_bytes(),before)
        self.assertEqual(json.loads((slot_home(self.base,2)/'runs'/'2'/'control.json').read_text())['action'],'stop')


@unittest.skipUnless(os.name == 'nt', 'Windows named leases')
class NativeLeaseTests(unittest.TestCase):
    def test_cross_process_exclusion_and_exit_release(self):
        # Pure named kernel object; no window lookup, keypress, or game input.
        with tempfile.TemporaryDirectory() as folder:
            name = r'Local\Epic7Assistant.Test.'+Path(folder).name
            code = "import sys; sys.path.insert(0,sys.argv[2]); from assistant_instances import NamedLeases; a=NamedLeases(); h=a.acquire(sys.argv[1]); print('held' if h else 'busy',flush=True); sys.stdin.readline()"
            child = subprocess.Popen([sys.executable, '-B', '-c', code, name, str(Path(__file__).resolve().parents[1])], cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            api = NamedLeases()
            try:
                self.assertEqual(child.stdout.readline().strip(), 'held')
                self.assertIsNone(api.acquire(name))
                child.stdin.write('\n'); child.stdin.flush()
                self.assertEqual(child.wait(timeout=10), 0)
                handle = api.acquire(name)
                self.assertIsNotNone(handle)
                api.release(handle)
            finally:
                if child.poll() is None:child.kill();child.wait()
                child.stdin.close();child.stdout.close();child.stderr.close()
