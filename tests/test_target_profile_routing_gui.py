"""Hidden GUI routing before a request is created; no child/game input."""
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    import tkinter as tk
except ImportError:
    tk=None
else:
    from assistant_app import Assistant


@unittest.skipIf(tk is None,'GUI Python required')
class TargetProfileRoutingGuiTests(unittest.TestCase):
    def test_start_routes_selected_client_before_validating_or_publishing_request(self):
        from assistant_instances import remember_target,slot_home
        from assistant_portable import initialize_selected,registered_root
        from assistant_config import read_json
        with tempfile.TemporaryDirectory() as d:
            base=Path(d).resolve();home=slot_home(base,2)
            b,_=initialize_selected(True,base);a,_=initialize_selected(True,home)
            target_a=dict(client='mumu',serial='127.0.0.1:16384',package='epic7',label='MuMu A')
            target_b=dict(client='mumu',serial='127.0.0.1:16416',package='epic7',label='MuMu B')
            remember_target(target_a,a,home);remember_target(target_b,b,base)
            original={p:p.read_bytes() for p in (a/'state.json',b/'state.json',home/'profile.json')}
            cached=dict(client='auto',task='mainline',data_dir=str(a),worker_python=sys.executable,mumu={})
            root=tk.Tk();root.withdraw()
            try:
                with patch('assistant_app.load_settings',return_value=cached):
                    app=Assistant(root,ui_check=True,home=home,slot_number=2,base_home=base)
                app.targets=[target_b];app.filter_targets();app.launch_worker=Mock()
                with patch('assistant_app.validate_run') as validate:app.start()
                self.assertEqual(validate.call_args.args[0]['data_dir'],str(b))
                app.launch_worker.assert_called_once();request=app.launch_worker.call_args.args[0]
                self.assertEqual(request['target'],target_b)
                self.assertEqual(request['settings']['data_dir'],str(b))
                self.assertEqual(request['profile_resolution']['previous_data_dir'],str(a))
                self.assertEqual(read_json(app.run_dir/'request.json')['settings']['data_dir'],str(b))
                self.assertEqual(registered_root(home),a)
                for p,value in original.items():self.assertEqual(p.read_bytes(),value)
            finally:root.destroy()


if __name__=='__main__':unittest.main()
