import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import assistant_portable as portable
from assistant_config import atomic_json,load_settings

class PortableProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.home=self.root/'data';self.home.mkdir()
        self.patch=patch.object(portable,'CODE_ROOT',self.root);self.patch.start()
        self.proof={'server':'test-server','account_id':'12345','checked_at':time.time()}
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_no_history_on_first_observation(self):
        self.assertIsNone(portable.registered_root(self.home))
        self.assertFalse((self.home/'profiles').exists())
    def test_initialize_needs_consent(self):
        with self.assertRaises(ValueError):portable.initialize_verified(self.proof,False,self.home)
        self.assertIsNone(portable.registered_root(self.home))
    def test_initialize_requires_fresh_proof(self):
        for proof in ({},{**self.proof,'checked_at':0},{**self.proof,'account_id':'oops'}):
            with self.assertRaises(ValueError):portable.initialize_verified(proof,True,self.home)
        self.assertIsNone(portable.registered_root(self.home))
    def test_verified_init_registered_and_cannot_replace(self):
        root,state=portable.initialize_verified(self.proof,True,self.home)
        self.assertEqual(portable.registered_root(self.home),root)
        self.assertEqual(state['initialization'],'first_use_verified_account')
        with self.assertRaises(ValueError):portable.initialize_verified(self.proof,True,self.home)
        self.assertEqual(json.loads((root/'state.json').read_text()),state)
    def test_registered_missing_history_never_reinitialized(self):
        root,_=portable.initialize_verified(self.proof,True,self.home)
        (root/'state.json').unlink()
        with self.assertRaises(ValueError):portable.registered_root(self.home)
        with self.assertRaises(ValueError):portable.initialize_verified(self.proof,True,self.home)
        self.assertFalse((root/'state.json').exists())
    def test_orphan_directory_blocks_new_profile(self):
        (self.home/'profiles'/'incomplete').mkdir(parents=True)
        with self.assertRaises(ValueError):portable.initialize_verified(self.proof,True,self.home)
    def test_import_preserves_failed_history_and_evidence(self):
        root=self.root/'old';root.mkdir()
        original={'attempted':{'S1':{'outcome':'defeat'}},'completed':{},'active':{'key':'S1'},'terminal':True}
        atomic_json(root/'state.json',original);before=(root/'state.json').read_bytes()
        (root/'STOP').write_text('keep')
        result,state=portable.register_existing(root,self.home)
        self.assertEqual(result,root);self.assertEqual(state,original)
        self.assertEqual((root/'state.json').read_bytes(),before);self.assertEqual((root/'STOP').read_text(),'keep')
    def test_corrupt_import_not_registered(self):
        root=self.root/'bad';root.mkdir();atomic_json(root/'state.json',{'attempted':[],'completed':{}})
        with self.assertRaises(ValueError):portable.register_existing(root,self.home)
        self.assertFalse((self.home/'profile.json').exists())
    def test_saved_managed_paths_are_relative(self):
        root,_=portable.initialize_verified(self.proof,True,self.home)
        with patch.object(portable,'enabled',return_value=True):
            portable.save_settings({'data_dir':str(root),'worker_python':'C:/private/python.exe','portable_first_use':False},self.home)
        settings=json.loads((self.home/'settings.json').read_text())
        self.assertFalse(Path(settings['data_dir']).is_absolute())
        self.assertEqual(settings['worker_python'],'runtime/python.exe')
        self.assertNotIn('portable_first_use',settings)
    def test_import_cannot_switch_registered_profile(self):
        portable.initialize_verified(self.proof,True,self.home)
        other=self.root/'other';other.mkdir();atomic_json(other/'state.json',{'attempted':{},'completed':{}})
        with self.assertRaises(ValueError):portable.register_existing(other,self.home)
    def test_relocation_resolves_managed_history(self):
        root,_=portable.initialize_verified(self.proof,True,self.home)
        import shutil
        moved=self.root/'moved';shutil.copytree(self.home,moved/'data')
        with patch.object(portable,'CODE_ROOT',moved):
            self.assertEqual(portable.registered_root(moved/'data'),moved/root.relative_to(self.root))

    def test_direct_start_creates_no_account_or_server_binding(self):
        root,state=portable.initialize_selected(True,self.home)
        self.assertEqual(state['initialization'],'first_use_user_selected_profile')
        self.assertNotIn('pc_profile_binding',state)
        self.assertNotIn('server',state);self.assertNotIn('account_id',state)
        self.assertEqual(portable.registered_root(self.home),root)
    def test_direct_start_cannot_replace_registered_or_lost_history(self):
        root,_=portable.initialize_selected(True,self.home)
        with self.assertRaises(ValueError):portable.initialize_selected(True,self.home)
        (root/'state.json').unlink()
        with self.assertRaises(ValueError):portable.initialize_selected(True,self.home)
        self.assertFalse((root/'state.json').exists())
    def test_direct_start_requires_start_command(self):
        with self.assertRaises(ValueError):portable.initialize_selected(False,self.home)
        self.assertFalse((self.home/'profile.json').exists())
