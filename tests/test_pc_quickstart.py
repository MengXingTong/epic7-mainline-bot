"""Quick-start regression: fake windows/OCR only, never native game input."""
import copy,json,sys,tempfile,time,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import runner
import pc_quickstart as Q
from pc_startup import observed_account,navigation_target,StartupBlocked
from pc_backend import PcBackend,PcSafetyError,WindowSnapshot
from test_pc_backend import FakeApi


def frame(words=(),grid=False):
    im=runner.np.zeros((900,1600,3),runner.np.uint8)
    if grid:
        for y in (20,42):
            for x in (1532,1554):
                im[y:y+15,x:x+15]=(240,120,10)
                im[y+4:y+11,x+4:x+11]=0
    rows=[]
    for row in words:
        text,x,y,*score=row
        rows.append(([[x-5,y-5],[x+5,y-5],[x+5,y+5],[x-5,y+5]],text,score[0] if score else .999))
    return runner.Frame(im,rows)


def account(server='原石铸界',uid='123456',extra=()):
    return frame([('账号信息',250,140),('服务器账号编号',300,550),(server,1250,440),(uid,1400,550),*extra])


def map_frame(extra=()):
    return frame([('Episode 3',200,40),('准备战斗',1390,830),*extra],grid=True)


class QuickTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.api=FakeApi();self.win=self.api.window
    def state(self,active=None):return dict(attempted={'old':{'outcome':'defeat'}},completed={'clear':{}},active=active,last_cleared={'key':'clear'})
    def proof(self):return observed_account(account(),self.win)
    def save_state(self,root,s):root.mkdir(parents=True,exist_ok=True);(root/'state.json').write_text(json.dumps(s),encoding='utf8')
    def test_account_is_read_automatically_without_configuration(self):
        p=self.proof();self.assertEqual(p['server'],'原石铸界');self.assertEqual(p['account_id'],'123456')
    def test_account_ambiguity_low_score_and_non_numeric_ids_block(self):
        for f in (account(uid='123l56'),account(extra=[('654321',1300,560)]),account(extra=[('亚洲服务器',1200,420)]),account(uid='123456',extra=[('是否消耗道具兑换体力',800,500)])):
            with self.subTest(text=f.text),self.assertRaises(StartupBlocked):observed_account(f,self.win)
    def test_account_page_labels_are_required(self):
        with self.assertRaises(StartupBlocked):observed_account(frame([('原石铸界',1250,440),('123456',1400,550)]),self.win)
    def test_menu_navigation_requires_known_page_and_blue_grid(self):
        self.assertEqual(navigation_target(map_frame())[0],'menu')
        with self.assertRaises(StartupBlocked):navigation_target(frame([('Episode 3',200,40),('准备战斗',1390,830)]))
        with self.assertRaises(StartupBlocked):navigation_target(frame(grid=True))
    def test_settings_and_menu_navigation_are_limited(self):
        f=frame([('设置',180,50),('游戏设置',180,220),('账号信息',180,700)])
        self.assertEqual(navigation_target(f),('account_tab',(180.,700.)))
        f=frame([(t,1000+50*i,200+i*30) for i,t in enumerate(('英雄','背包','召唤','好友'))]+[('设置',1520,736)])
        self.assertEqual(navigation_target(f)[0],'settings')
    def test_menu_without_gear_or_settings_text_is_not_blind_clicked(self):
        f=frame([(t,1000+50*i,200+i*30) for i,t in enumerate(('英雄','背包','召唤','好友'))])
        with self.assertRaises(StartupBlocked):navigation_target(f)
    def test_low_confidence_account_id_is_rejected(self):
        f=account();next(w for w in f.words if w['text']=='123456')['score']=.89
        with self.assertRaises(StartupBlocked):observed_account(f,self.win)
    def test_resource_dialog_auth_battle_defeat_never_navigate(self):
        for extra in ([('是否消耗道具兑换体力',800,500)],[('登录',800,500)],[('确认',800,500),('取消',650,500)],[('FAILED',800,300)]):
            with self.subTest(extra=extra),self.assertRaises(StartupBlocked):navigation_target(map_frame(extra))
    def backend(self,f,**kwargs):
        self.api.capture=lambda w:f.image.copy()
        b=PcBackend(dict(game_exe=self.win.exe,experimental_input_enabled=True),self.home/'STOP',api=self.api,**kwargs);b.capture();return b
    def test_preflight_navigation_does_not_authorize_task_input(self):
        f=map_frame();b=self.backend(f);self.assertEqual(b.navigate_account(f),'menu');self.assertFalse(b.allowed)
        b.capture()
        with self.assertRaises(PcSafetyError):b.tap(1390,830)
        self.assertEqual(len([c for c in self.api.calls if c==('button',True)]),1)
    def test_readonly_preflight_never_navigates(self):
        f=map_frame();b=self.backend(f,read_only=True)
        with self.assertRaises(PcSafetyError):b.navigate_account(f)
        self.assertEqual(self.api.calls,[])
    def test_navigation_rejects_unobserved_and_consumed_frame(self):
        f=map_frame();b=self.backend(f);changed=map_frame();changed.image[0,0]=255
        with self.assertRaises(PcSafetyError):b.navigate_account(changed)
        self.assertEqual(self.api.calls,[])
        b.navigate_account(f)
        with self.assertRaises(PcSafetyError):b.navigate_account(f)
    def test_stop_geometry_and_staleness_also_guard_navigation(self):
        f=map_frame();clock=[100.];b=self.backend(f,clock=lambda:clock[0]);clock[0]+=6
        with self.assertRaises(PcSafetyError):b.navigate_account(f)
        self.assertEqual(self.api.calls,[])
        clock[0]=100.;(self.home/'STOP').write_text('user')
        with self.assertRaises(PcSafetyError):b.navigate_account(f)
    def test_first_run_profile_has_verified_identity_not_fake_completions(self):
        root,s=Q.select_profile(self.home,None,None,self.proof())
        self.assertFalse(root.exists());self.assertEqual(s['attempted'],{});self.assertEqual(s['completed'],{})
        self.assertEqual(s['pc_profile_binding']['server'],'原石铸界')
        root.mkdir(parents=True)
        with self.assertRaises(RuntimeError):Q.select_profile(self.home,None,None,self.proof())
    def test_existing_history_is_reused_without_clearing(self):
        s=self.state();root,got=Q.select_profile(self.home,self.home,s,self.proof())
        self.assertIs(got,s);self.assertEqual(got['attempted']['old']['outcome'],'defeat')
    def test_account_change_never_rebinds_or_creates_blank_history(self):
        s=self.state();s['pc_profile_binding']={'server':'亚洲服务器','account_id':'123456'};before=copy.deepcopy(s)
        with self.assertRaisesRegex(RuntimeError,'不一致'):Q.select_profile(self.home,self.home,s,self.proof())
        self.assertEqual(s,before)
    def test_missing_registered_history_never_falls_back_to_new(self):
        with self.assertRaises(RuntimeError):Q.existing_profile(self.home,{'data_dir':str(self.home/'missing')},code_root=self.home)
    def test_multiple_or_incomplete_profile_folders_block(self):
        (self.home/'profiles/orphan').mkdir(parents=True)
        with self.assertRaises(RuntimeError):Q.existing_profile(self.home,{},code_root=self.home)
    def test_legacy_history_is_auto_discovered(self):
        self.save_state(self.home,self.state())
        self.assertEqual(Q.existing_profile(self.home,{},code_root=self.home),self.home.resolve())
    def test_active_defeat_or_uncertain_attempt_never_auto_restarts(self):
        for active in ({'key':'E3-C3-S10','outcome':'defeat'},{'key':'E3-C3-S10'}):
            for resume in (False,True):
                s=self.state(active);before=copy.deepcopy(s)
                with self.assertRaises(RuntimeError):Q.entry_gate(self.home,s,resume)
                self.assertEqual(s,before)
    def test_stop_is_not_removed_by_normal_start(self):
        (self.home/'STOP').write_text('user')
        with self.assertRaises(RuntimeError):Q.entry_gate(self.home,self.state(),False)
        self.assertTrue((self.home/'STOP').exists())
    def test_account_navigation_is_bounded_and_requires_two_matching_reads(self):
        values=iter([map_frame(),frame([('设置',180,50),('游戏设置',180,220),('账号信息',180,700)]),account(),account()])
        calls=[];b=types.SimpleNamespace(window=self.win,navigate_account=lambda f:calls.append(navigation_target(f)[0]))
        with patch.object(Q.time,'sleep'):
            proof,_=Q.inspect_account(b,lambda:next(values))
        self.assertEqual(calls,['menu','account_tab']);self.assertEqual(proof['account_id'],'123456')
    def test_same_startup_screen_is_not_clicked_twice(self):
        calls=[];b=types.SimpleNamespace(window=self.win,navigate_account=lambda f:calls.append('click'))
        with patch.object(Q.time,'sleep'),self.assertRaises(RuntimeError):Q.inspect_account(b,map_frame)
        self.assertEqual(calls,['click'])
    def test_inconsistent_two_frame_account_proof_is_rejected(self):
        values=iter([account(),account(uid='654321')]);b=types.SimpleNamespace(window=self.win)
        with self.assertRaises(RuntimeError):Q.inspect_account(b,lambda:next(values))
    def test_failed_resume_restores_user_stop(self):
        home=self.home/'.local/pc';home.mkdir(parents=True);root=self.home/'data';s=self.state();s['terminal']=True;self.save_state(root,s)
        (root/'STOP').write_text('manual stop')
        (home/'preferences.json').write_text(json.dumps({'data_dir':str(root)}))
        with patch.object(Q,'CODE_ROOT',self.home),patch('builtins.input',return_value='Y'),patch.object(Q.time,'sleep'),patch('pc_backend.Win32Api',side_effect=RuntimeError('fake native error')):
            with self.assertRaises(RuntimeError):Q.main(['resume','--delay','2'])
        self.assertEqual((root/'STOP').read_text(),'manual stop');self.assertEqual(Q.read_state(root),s)
    def test_stop_does_not_require_game_or_account_config(self):
        home=self.home/'.local/pc';home.mkdir(parents=True);root=self.home/'data';self.save_state(root,self.state())
        (home/'preferences.json').write_text(json.dumps({'data_dir':str(root)}))
        with patch.object(Q,'CODE_ROOT',self.home),patch('pc_backend.Win32Api',side_effect=AssertionError('No native API')):
            Q.main(['stop'])
        self.assertTrue((root/'STOP').exists())
    def test_bound_daily_start_needs_no_input_or_account_page_from_user(self):
        home=self.home/'.local/pc';home.mkdir(parents=True);root=self.home/'data';s=self.state();s['pc_profile_binding']={'server':'原石铸界','account_id':'123456'};self.save_state(root,s)
        (home/'preferences.json').write_text(json.dumps({'data_dir':str(root),'experimental_consent':True}))
        before=copy.deepcopy(s)
        with patch.object(Q,'CODE_ROOT',self.home),patch.object(Q.time,'sleep'),patch('pc_backend.Win32Api',return_value=self.api),patch('builtins.input',side_effect=AssertionError('No daily confirmation')),patch.object(Q,'inspect_account',return_value=(self.proof(),account())),patch.object(Q,'return_to_game',return_value=map_frame()),patch.object(Q,'start_supervisor') as start:
            Q.main(['start','--delay','2'])
        self.assertEqual(start.call_count,1);cfg=start.call_args[0][0]
        self.assertEqual(cfg['pc']['server'],'原石铸界');self.assertEqual(cfg['pc']['game_exe'],self.win.exe)
        self.assertEqual(Q.read_state(root),before)

if __name__=='__main__':unittest.main()
