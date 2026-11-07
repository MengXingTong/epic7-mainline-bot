"""Target-owned history routing: no input, history migration or blank profiles."""
import copy,hashlib,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from assistant_config import atomic_json,read_json
from assistant_instances import history_key,known_target_root,resolve_target_profile,remember_target,slot_home
from assistant_portable import initialize_selected,registered_root

A=dict(client='mumu',serial='127.0.0.1:16384',package='epic7')
B=dict(client='mumu',serial='127.0.0.1:16416',package='epic7')


class TargetProfileRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.second=slot_home(self.base,2)
        self.b,_=initialize_selected(True,self.base);self.a,_=initialize_selected(True,self.second)
        for root,key in ((self.a,'A'),(self.b,'B')):
            atomic_json(root/'state.json',dict(attempted={key:{'outcome':'retained'}},completed={},active={'key':key},entry_dispatches={key:[{'status':'sent'}]}))
        remember_target(B,self.b,self.base);remember_target(A,self.a,self.second)
        self.folder=self.second/'runs'/('a'*32);self.folder.mkdir(parents=True)
        self.request=dict(run_id='a'*32,run_dir=str(self.folder),home=str(self.second),instance_base=str(self.base),target=B,
                          user_selected_profile=True,settings=dict(data_dir=str(self.a),task='mainline'))
        atomic_json(self.folder/'request.json',self.request)
        atomic_json(self.second/'active-run.json',dict(run_id='a'*32,run_dir=str(self.folder),worker_pid=0))
        self.before={p:p.read_bytes() for p in (self.a/'state.json',self.b/'state.json',self.second/'profile.json',self.folder/'request.json')}

    def preserved(self):
        for p,value in self.before.items():self.assertEqual(p.read_bytes(),value,str(p))

    def test_new_unvalidated_request_cache_does_not_create_a_second_binding(self):
        self.assertEqual(known_target_root(B,self.base),self.b)
        self.preserved()

    def test_proven_other_target_cache_routes_to_selected_targets_unique_original(self):
        value,audit=resolve_target_profile(self.request['settings'],B,self.base)
        self.assertEqual(value['data_dir'],str(self.b));self.assertEqual(self.request['settings']['data_dir'],str(self.a))
        self.assertEqual(audit['previous_data_dir'],str(self.a));self.assertEqual(audit['resolved_data_dir'],str(self.b))
        self.assertEqual(audit['previous_registered_target_keys'],[history_key(A)])
        self.assertFalse(audit['history_mutated']);self.preserved()

    def test_real_conflicting_target_bindings_are_still_rejected(self):
        remember_target(B,self.a,self.second)
        with self.assertRaisesRegex(ValueError,'多个原记录'):resolve_target_profile(self.request['settings'],B,self.base)
        self.preserved()

    def test_unowned_legacy_request_conflict_is_not_ignored(self):
        c=self.base/'unowned';c.mkdir();atomic_json(c/'state.json',{'attempted':{},'completed':{}})
        request=copy.deepcopy(self.request);request['settings']['data_dir']=str(c);atomic_json(self.folder/'request.json',request)
        with self.assertRaisesRegex(ValueError,'多个原记录'):known_target_root(B,self.base)

    def test_explicit_import_is_not_silently_replaced(self):
        value=copy.deepcopy(self.request['settings']);value['profile_choice']=dict(kind='explicit_import',target_key=history_key(B),data_dir=str(self.a))
        with self.assertRaisesRegex(ValueError,'明确选择'):resolve_target_profile(value,B,self.base)
        self.preserved()

    def test_cached_import_for_previous_target_does_not_pin_a_different_client(self):
        value=copy.deepcopy(self.request['settings']);value['profile_choice']=dict(kind='explicit_import',target_key=history_key(A),data_dir=str(self.a))
        resolved,_=resolve_target_profile(value,B,self.base);self.assertEqual(resolved['data_dir'],str(self.b))
        self.preserved()

    def test_unknown_selected_client_cannot_take_another_clients_cache(self):
        c=dict(B,serial='127.0.0.1:16448')
        with self.assertRaisesRegex(ValueError,'另一个客户端'):resolve_target_profile(self.request['settings'],c,self.base)
        self.preserved()

    def test_selected_target_missing_history_does_not_fall_back_to_cached_other_client(self):
        (self.b/'state.json').unlink()
        with self.assertRaisesRegex(ValueError,'原进度丢失'):known_target_root(B,self.base)
        self.assertFalse((self.b/'state.json').exists());self.assertEqual((self.a/'state.json').read_bytes(),self.before[self.a/'state.json'])

    def test_same_original_or_localhost_alias_has_no_routing_side_effect(self):
        value,audit=resolve_target_profile({'data_dir':str(self.b)},dict(B,serial='localhost:16416'),self.base)
        self.assertEqual(value['data_dir'],str(self.b));self.assertIsNone(audit);self.preserved()

    def test_worker_routes_without_replacing_slot_profile_or_touching_game(self):
        from assistant_worker import prepare_selected_profile
        request=copy.deepcopy(self.request)
        with patch('assistant_transport.UnifiedTransport') as transport:
            self.assertEqual(prepare_selected_profile(request,Mock()),self.b)
        transport.assert_not_called();self.preserved()
        self.assertEqual(registered_root(self.second),self.a)
        receipt=read_json(self.folder/'profile-resolution.json',{})
        self.assertEqual(receipt['resolved_data_dir'],str(self.b));self.assertFalse(receipt['history_mutated'])

    def test_old_unregistered_primary_history_is_still_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d).resolve();root=base/'original';root.mkdir();atomic_json(root/'state.json',{'attempted':{'old':{}},'completed':{}})
            folder=base/'runs'/'old';folder.mkdir(parents=True)
            atomic_json(folder/'request.json',dict(run_id='old',target=B,settings={'data_dir':str(root)}))
            atomic_json(base/'active-run.json',dict(run_id='old',run_dir=str(folder)))
            self.assertEqual(known_target_root(B,base),root)

    def test_known_profile_routing_still_requires_the_explicit_start(self):
        from assistant_worker import prepare_selected_profile
        request=copy.deepcopy(self.request);request['user_selected_profile']=False
        with self.assertRaisesRegex(RuntimeError,'缺少开始指令'):prepare_selected_profile(request,Mock())
        self.assertEqual(request['settings'],self.request['settings'])
        self.assertFalse((self.folder/'profile-resolution.json').exists());self.preserved()

    def test_audit_persistence_error_blocks_routing_before_input(self):
        from assistant_worker import prepare_selected_profile
        with patch('assistant_worker.atomic_json',side_effect=OSError('audit disk full')),patch('assistant_transport.UnifiedTransport') as transport:
            with self.assertRaises(OSError):prepare_selected_profile(copy.deepcopy(self.request),Mock())
        transport.assert_not_called();self.preserved()


if __name__=='__main__':unittest.main()
