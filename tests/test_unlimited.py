"""No artificial run-count ceilings. Fake captures/plans only; no real game input."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from assistant_config import load_settings,atomic_json
from assistant_portable import save_settings
from assistant_worker import mainline_run,StopRun
from abyss_core import Session,Scene,Reading,Observation,Token

class UnlimitedSettingsTests(unittest.TestCase):
    def test_old_limits_removed_on_normal_and_portable_load(self):
        for portable in (False,True):
            for limit in (1,30,999999,'obsolete',None):
                with self.subTest(portable=portable,limit=limit),tempfile.TemporaryDirectory() as d:
                    home=Path(d);atomic_json(home/'settings.json',{'client':'auto','limit':limit})
                    with patch('assistant_portable.enabled',return_value=portable),patch('assistant_portable.registered_root',return_value=None):settings=load_settings(home)
                    self.assertNotIn('limit',settings)
    def test_new_defaults_have_no_cap(self):
        with tempfile.TemporaryDirectory() as d,patch('assistant_portable.enabled',return_value=True),patch('assistant_portable.registered_root',return_value=None):
            self.assertNotIn('limit',load_settings(Path(d)))
    def test_save_drops_old_limit_but_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as d,patch('assistant_portable.enabled',return_value=False):
            before={'client':'mumu','task':'mainline','limit':30,'data_dir':'original-profile'}
            save_settings(before,Path(d));saved=json.loads((Path(d)/'settings.json').read_text(encoding='utf-8'))
            self.assertNotIn('limit',saved);self.assertEqual(saved['data_dir'],'original-profile');self.assertEqual(before['limit'],30)

class ContinuousExecutionTests(unittest.TestCase):
    def test_abyss_session_has_no_hidden_default_cap(self):
        self.assertFalse(hasattr(Session(),'limit'))
    def test_abyss_continues_past_thirty_and_sixty_clears(self):
        session=Session(normal_verified=True,entered_floor=1,expected_floor=1,phase='battle')
        clear=Observation(1600,900,[Token('下一层',1400,820,140,40)])
        team=Observation(1600,900,[Token('战斗开始',1400,820,140,40)])
        for floor in range(1,66):
            advance=session.plan(Reading(Scene.CLEAR,floor=floor),clear)
            self.assertEqual((advance.kind,advance.target_floor),('advance',floor+1));session.applied(advance)
            start=session.plan(Reading(Scene.TEAM,floor=floor+1),team)
            self.assertEqual(start.kind,'start_battle');session.applied(start)
            self.assertIsNone(session.plan(Reading(Scene.BATTLE),team))
        self.assertEqual(session.wins,65);self.assertEqual(session.expected_floor,66)
    def test_mainline_ignores_legacy_limit_and_runs_until_explicit_stop(self):
        for old_limit in ('missing',1,30):
            with self.subTest(limit=old_limit),tempfile.TemporaryDirectory() as d:
                root=Path(d);atomic_json(root/'state.json',{'attempted':{},'completed':{},'active':None});atomic_json(root/'config.json',{})
                settings={'data_dir':d,'task':'mainline','observe':False,'mumu':{},'start_policy':'current_screen'}
                if old_limit!='missing':settings['limit']=old_limit
                instances=[]
                class FakeRunner:
                    def __init__(self,observe):
                        self.s={'attempted':{},'completed':{},'active':None,'reason':'fake capture'};self.ticket=None;self.captures=0;instances.append(self)
                    def start_current_screen(self):pass
                    def capture(self):
                        self.captures+=1
                        if self.captures>33:raise StopRun()
                        return SimpleNamespace(image=runner.np.zeros((9,16,3),runner.np.uint8))
                    def step(self,frame):self.s['completed'][str(self.captures)]={};return True,5
                request={'settings':settings,'target':{'client':'mumu','serial':'fake-local','package':'fake-game'},'run_dir':d}
                control=Mock()
                with patch('runner.Runner',FakeRunner),patch('runner.classify',return_value='battle'),patch.object(runner,'ROOT',root),patch.dict('os.environ',{},clear=False):
                    with self.assertRaises(StopRun):mainline_run(request,control)
                self.assertEqual(len(instances[0].s['completed']),33)
                self.assertTrue(any(call.kwargs.get('wins')==33 for call in control.status.call_args_list))
