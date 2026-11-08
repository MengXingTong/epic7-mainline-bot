"""Private-history routing regressions: fake files/endpoints, zero game input."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from assistant_config import atomic_json,read_json
from assistant_instances import abyss_history_key,abyss_history_path,exclusive_abyss_history,slot_home
from assistant_portable import initialize_selected
from test_instances import FakeLeases

TARGET=dict(client='mumu',serial='127.0.0.1:16384',package='game')

class AbyssHistoryRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.second=slot_home(self.base,2)
        self.other,self.other_state=initialize_selected(True,self.base)
        self.root,self.state=initialize_selected(True,self.second)
        self.request=dict(home=str(self.base),instance_base=str(self.base),target=TARGET,
                          settings=dict(task='abyss',observe=False,data_dir=str(self.root)))
        self.key=abyss_history_key(self.request,self.state)
        self.other_key=abyss_history_key(self.request,self.other_state)
        self.first=self.base/'abyss-history.json';self.original=self.second/'abyss-history.json'
        self.record=dict(attempted={'86':dict(requested_at=1,keep='original')},completed={'85':dict(observed_clear_at=2)},
                         entry_dispatches={'86':[dict(id='original',status='sent',evidence='retained.png')]})
        atomic_json(self.first,dict(schema=1,clients={self.other_key:dict(attempted={'88':{}},completed={'87':{}})}))
        atomic_json(self.original,dict(schema=1,clients={self.key:copy.deepcopy(self.record)}))
        # Reproduce existing metadata after the user selected the other profile;
        # this is a fake fixture, not a profile registration/migration operation.
        self.bind(self.base,self.root)
    def bind(self,home,root):
        atomic_json(home/'profile.json',dict(schema=1,kind='imported',data_dir=str(root)))
    def snapshot(self):
        return {p:p.read_bytes() for p in self.base.rglob('*.json')}
    def preserved(self,before):
        self.assertEqual(self.snapshot(),before)
    def test_two_current_slot_bindings_with_distinct_identities_reuse_unique_original(self):
        before=self.snapshot()
        self.assertEqual(abyss_history_path(self.request),self.original)
        self.assertEqual(read_json(self.original)['clients'][self.key],self.record);self.preserved(before)
    def test_exact_profile_history_survives_original_slot_switching_to_another_profile(self):
        self.bind(self.second,self.other);before=self.snapshot()
        self.assertEqual(abyss_history_path(self.request),self.original);self.preserved(before)
    def test_physical_endpoint_changes_do_not_change_persistent_profile_identity(self):
        before=self.snapshot();request=copy.deepcopy(self.request);request['target']=dict(client='pc',exe='other.exe')
        self.assertEqual(abyss_history_key(request,self.state),self.key)
        self.assertEqual(abyss_history_path(request),self.original);self.preserved(before)
    def test_unrelated_keys_in_selected_file_are_not_lost(self):
        data=read_json(self.original);data['clients']['unrelated']=dict(attempted={'12':{}},completed={});atomic_json(self.original,data)
        before=self.snapshot();self.assertEqual(abyss_history_path(self.request),self.original);self.preserved(before)
    def test_duplicate_real_identity_is_blocked_even_if_identical(self):
        for same in (True,False):
            data=read_json(self.first);data['clients'][self.key]=copy.deepcopy(self.record)
            if not same:data['clients'][self.key]['attempted']['90']={}
            atomic_json(self.first,data);before=self.snapshot()
            with self.assertRaisesRegex(ValueError,'同一进度身份'):abyss_history_path(self.request)
            self.preserved(before)
    def test_empty_duplicate_identity_cannot_override_nonempty_original(self):
        data=read_json(self.first);data['clients'][self.key]=dict(attempted={},completed={});atomic_json(self.first,data)
        before=self.snapshot()
        with self.assertRaises(ValueError):abyss_history_path(self.request)
        self.preserved(before)
    def test_missing_identity_with_multiple_candidates_never_creates_empty_replacement(self):
        self.state['local_profile_id']='never-seen';atomic_json(self.root/'state.json',self.state);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'没有唯一身份'):abyss_history_path(self.request)
        self.preserved(before)
    def test_legacy_call_without_target_keeps_ambiguity_guard(self):
        request=copy.deepcopy(self.request);request.pop('target');before=self.snapshot()
        with self.assertRaises(ValueError):abyss_history_path(request)
        self.preserved(before)
    def test_legacy_unique_original_path_is_preserved(self):
        self.bind(self.base,self.other);request=copy.deepcopy(self.request);request.pop('target');before=self.snapshot()
        self.assertEqual(abyss_history_path(request),self.original);self.preserved(before)
    def test_target_only_legacy_key_cannot_adopt_another_profile_bucket(self):
        self.state.pop('local_profile_id');atomic_json(self.root/'state.json',self.state)
        legacy=abyss_history_key(self.request,self.state)
        self.bind(self.second,self.other)
        atomic_json(self.original,dict(schema=1,clients={legacy:self.record}))
        before=self.snapshot()
        # Current bound ledger is reused; a foreign serial-only bucket is not
        # positive evidence that this profile owns that other file.
        self.assertEqual(abyss_history_path(self.request),self.first);self.preserved(before)
    def test_corrupt_clients_or_schema_are_not_hidden_by_other_valid_file(self):
        for broken in (dict(schema=2,clients={}),dict(schema=1,clients=[]),dict(schema=1,clients={self.key:{'attempted':[], 'completed':{}}})):
            atomic_json(self.original,broken);before=self.snapshot()
            with self.assertRaisesRegex(ValueError,'格式损坏'):abyss_history_path(self.request)
            self.preserved(before)
    def test_stable_key_and_legacy_key_hashes_are_backward_compatible(self):
        self.assertEqual(self.key,hashlib.sha256(('local_profile|'+self.state['local_profile_id']).encode()).hexdigest()[:24])
        with patch('assistant_portable.enabled',return_value=False):
            self.assertEqual(abyss_history_key(dict(target=dict(client='pc',exe='fake.exe')),{}),hashlib.sha256(b'pc|fake.exe').hexdigest()[:24])
        with patch('assistant_portable.enabled',return_value=True):
            state=dict(pc_profile_binding=dict(server='test',account_id='12345'))
            self.assertEqual(abyss_history_key(dict(target=dict(client='pc',exe='fake.exe')),state),hashlib.sha256(b'account|account|test|12345').hexdigest()[:24])
    def test_invalid_profile_identity_never_falls_back_to_endpoint_or_empty_bucket(self):
        with self.assertRaisesRegex(ValueError,'身份损坏'):abyss_history_key(self.request,dict(local_profile_id=5))
    def test_mutex_serializes_whole_ledger_and_releases_on_errors(self):
        api=FakeLeases();before=self.snapshot()
        with exclusive_abyss_history(self.original,api=api):
            with self.assertRaisesRegex(RuntimeError,'正在被'):
                with exclusive_abyss_history(self.original,api=api):pass
            with exclusive_abyss_history(self.first,api=api):self.assertEqual(len(api.live),2)
        self.assertFalse(api.live)
        with self.assertRaisesRegex(RuntimeError,'test'):
            with exclusive_abyss_history(self.original,api=api):raise RuntimeError('test')
        self.assertFalse(api.live);self.preserved(before)
    def test_worker_history_lease_precedes_any_transport_or_input(self):
        from assistant_worker import abyss_run
        api=FakeLeases();api.acquire=Mock(return_value=None);before=self.snapshot()
        with patch('assistant_worker.validate_run',return_value=(self.root,self.state)),patch('assistant_instances.NamedLeases',return_value=api),patch('assistant_transport.UnifiedTransport') as transport:
            with self.assertRaisesRegex(RuntimeError,'正在被'):abyss_run(self.request,Mock())
            transport.assert_not_called()
        self.preserved(before)
    def test_worker_receives_selected_path_and_original_state_under_lease(self):
        from assistant_worker import abyss_run
        api=FakeLeases();before=self.snapshot()
        def body(request,control,path,state):
            self.assertTrue(api.live);self.assertEqual(path,self.original);self.assertIs(state,self.state);return 'selected'
        with patch('assistant_worker.validate_run',return_value=(self.root,self.state)),patch('assistant_instances.NamedLeases',return_value=api),patch('assistant_worker._abyss_run_with_history',side_effect=body):
            self.assertEqual(abyss_run(self.request,Mock()),'selected')
        self.assertFalse(api.live);self.preserved(before)

if __name__=='__main__':unittest.main()
