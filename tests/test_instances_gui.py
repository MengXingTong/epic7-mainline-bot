"""GUI-only multi-window tests. No worker launch or game input."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
try:
    import tkinter as tk
except ImportError:
    tk = None
else:
    from assistant_app import Assistant


@unittest.skipIf(tk is None, 'GUI Python required')
class MultiWindowGuiTests(unittest.TestCase):
    def test_two_windows_isolate_selection_control_preview_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            first = tk.Tk()
            second = tk.Toplevel(first)
            settings = {'client':'auto','task':'mainline','mumu':{},'data_dir':'','worker_python':''}
            try:
                with patch('assistant_app.load_settings', side_effect=lambda *a, **kw: dict(settings)), patch('assistant_app.subprocess.Popen') as launch:
                    a = Assistant(first, ui_check=True, home=base, base_home=base)
                    b = Assistant(second, ui_check=True, home=base/'instances'/'2', slot_number=2, base_home=base)
                    self.assertIn('#1', first.title());self.assertIn('#2', second.title())
                    a.targets=[{'client':'pc','label':'PC 1'}];a.filter_targets()
                    b.targets=[{'client':'mumu','label':'MuMu 2'}];b.filter_targets()
                    a.run_dir=a.home/'runs'/'first';a.run_id='first'
                    b.run_dir=b.home/'runs'/'second';b.run_id='second'
                    a.command('pause');b.command('stop')
                    self.assertEqual(json.loads((a.run_dir/'control.json').read_text())['action'], 'pause')
                    self.assertEqual(json.loads((b.run_dir/'control.json').read_text())['action'], 'stop')
                    self.assertEqual(a.selected_target()['label'], 'PC 1')
                    self.assertEqual(b.selected_target()['label'], 'MuMu 2')
                    self.assertIsNone(a.process);self.assertIsNone(b.process)
                    launch.assert_not_called()
            finally:
                second.destroy();first.destroy()

    def test_worker_receives_its_home_and_base_not_other_window_home(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve();home=base/'instances'/'2'
            root=tk.Tk()
            try:
                with patch('assistant_app.load_settings', return_value={'task':'mainline','mumu':{},'data_dir':''}):
                    app=Assistant(root,ui_check=True,home=home,slot_number=2,base_home=base)
                app.run_id='test';app.run_dir=home/'runs'/'test'
                child=Mock();child.pid=123;child.poll.return_value=None
                request={'settings':{'worker_python':'python.exe'}}
                with patch('assistant_app.subprocess.Popen',return_value=child) as launch, patch('assistant_app.threading.Thread'):
                    app.launch_worker(request)
                self.assertEqual(launch.call_args.kwargs['env']['EPIC7_ASSISTANT_HOME'],str(home))
                self.assertEqual(launch.call_args.kwargs['env']['EPIC7_ASSISTANT_BASE'],str(base))
                self.assertTrue((home/'active-run.json').exists())
                self.assertFalse((base/'active-run.json').exists())
            finally:root.destroy()


    def test_normal_main_gate_allows_two_live_ui_processes(self):
        # Exercise the actual normal startup gate, NOT --ui-check's bypass.
        # Only the UI is patched to disable discovery/worker startup; no game APIs.
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve()
            source=Path(__file__).resolve().parents[1]
            script=base/'startup.py'
            script.write_text("""import sys,json,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
base=Path(sys.argv[2]);identifier=sys.argv[3]
os.environ['EPIC7_ASSISTANT_HOME']=str(base)
import assistant_app as app
app.load_settings=lambda *a,**kw: dict(client='auto',task='mainline',mumu={},data_dir='',worker_python='')
Original=app.Assistant
class UiOnly(Original):
    def __init__(self,root,*a,**kw):
        super().__init__(root,ui_check=True,**kw)
        root.withdraw()
        def ready():
            (base/('ready-'+identifier+'.json')).write_text(json.dumps(dict(number=self.slot_number,home=str(self.home),title=root.title(),window_exists=bool(root.winfo_exists()),process=self.process)),encoding='utf-8')
        root.after(0,ready)
        def finish():
            if (base/'close').exists():root.destroy()
            else:root.after(50,finish)
        root.after(50,finish)
        root.after(20000,root.destroy)
app.Assistant=UiOnly
sys.argv=['assistant_app.py']
app.main()
""",encoding='utf-8')
            children=[]
            try:
                for identifier in ('first','second'):
                    child=subprocess.Popen([sys.executable,'-B','-X','utf8',str(script),str(source),str(base),identifier],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
                    children.append(child)
                    path=base/('ready-'+identifier+'.json')
                    deadline=time.monotonic()+15
                    while not path.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                    if not path.exists():
                        child.terminate();out,err=child.communicate(timeout=5)
                        self.fail('UI did not start: '+out+err)
                a=json.loads((base/'ready-first.json').read_text())
                b=json.loads((base/'ready-second.json').read_text())
                self.assertNotEqual(a['number'],b['number'])
                self.assertNotEqual(a['home'],b['home'])
                self.assertTrue(a['window_exists'] and b['window_exists'])
                self.assertIsNone(a['process']);self.assertIsNone(b['process'])
                self.assertTrue(all(child.poll() is None for child in children))
                (base/'close').touch()
                for child in children:
                    out,err=child.communicate(timeout=10)
                    self.assertEqual(child.returncode,0,out+err)
                self.assertFalse(list(base.rglob('state.json')))
            finally:
                (base/'close').touch()
                for child in children:
                    if child.poll() is None:child.kill();child.wait()
                    child.stdout.close();child.stderr.close()
