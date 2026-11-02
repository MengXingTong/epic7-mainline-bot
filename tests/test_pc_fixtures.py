"""Optional private PC screenshots. They are never shipped or committed."""
import json,os,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import runner

def fixture(name,raw=False):
    directory=os.environ.get('EPIC7_PC_FIXTURES')
    if not directory:raise unittest.SkipTest('Set EPIC7_PC_FIXTURES for local-only PC screenshot regressions')
    root=Path(directory)
    if not (root/(name+'-ocr.json')).exists():raise unittest.SkipTest('Private PC fixture is not available')
    data=json.loads((root/(name+'-ocr.json')).read_text(encoding='utf8'))
    if raw:
        meta=json.loads((root/(name+'-meta.json')).read_text(encoding='utf8'))
        image=runner.cv2.imdecode(runner.np.frombuffer((root/(name+'.png')).read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
        x,y,w,h=meta['client_rect'];image=runner.cv2.resize(image[y:y+h,x:x+w],(1600,900))
    else:image=runner.cv2.imdecode(runner.np.frombuffer((root/(name+'-normalized.png')).read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
    return runner.Frame(image,[(w['box'],w['text'],w['score']) for w in data['words']])

class PcFixtureTests(unittest.TestCase):
    def ticket(self,f):return runner.Runner.__new__(runner.Runner).map_ticket(f)
    def test_real_pc_cleared_stage_is_vetoed(self):
        f=fixture('cleared9');node,_,proof=self.ticket(f)
        self.assertEqual(runner.classify(f),'map');self.assertEqual(node['key'],'E3-C3-S9');self.assertEqual(proof,'已通关绿色勾')
    def test_real_pc_next_node_is_uncleared_not_locked(self):
        f=fixture('map10');node,_,proof=self.ticket(f)
        self.assertEqual(node['key'],'E3-C3-S10');self.assertEqual(proof,'未通关蓝色当前节点');self.assertEqual(node['green'],0);self.assertLess(node['lock_score'],.81)
    def test_raw_pc_client_crop_normalizes_to_the_same_stage(self):
        f=fixture('map10',raw=True);node,_,proof=self.ticket(f)
        self.assertEqual(node['key'],'E3-C3-S10');self.assertEqual(proof,'未通关蓝色当前节点')
    def test_real_pc_completed_map_never_plans_reentry(self):
        f=fixture('cleared9');r=runner.Runner.__new__(runner.Runner)
        r.ticket=None;r.frame=f;r.last_mode='map';r.mode_since=time.time();r.battle_seen=0;r.last_gesture=0;r.unknown_gestures=0;r.cfg={}
        r.s={'active':None,'attempted':{'E3-C3-S9':{'outcome':'defeat'}},'completed':{'E3-C3-S9':{}},'last_cleared':{'episode':3,'chapter':3,'stage':9}}
        r.save=Mock();r.action=Mock()
        with patch.object(runner,'event'):r.step(f)
        self.assertEqual(r.action.call_args.args[0],'避开已通关关卡，选择下一关')

if __name__=='__main__':unittest.main(verbosity=2)
