"""Synthetic navigation tests. No device, network or paid summon input."""
import copy,hashlib,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from test_map_layout import frame
from task_blockers import TaskAttention
from tutorial_core import tutorial_plan,TutorialController
from tutorial_control_templates import covenant_back


def current():
    f=frame([('召唤',117,42),('圣约召唤',152,797),('愿望单',855,697),
             ('5',1036,827),('召唤1次',1166,830),('50',1351,828),('召唤10次',1486,830),('(14/14)',959,697)])
    runner.cv2.polylines(f.image,[runner.np.array([[60,23],[33,41],[60,59]],dtype=runner.np.int32)],False,(255,255,255),7)
    return f


def reference(folder,f):
    root=folder/'control_templates';root.mkdir(exist_ok=True)
    blob=runner.cv2.imencode('.png',f.image[12:72,18:76])[1].tobytes()
    (root/'covenant-back.png').write_bytes(blob)
    (root/'covenant-back.json').write_text(json.dumps(dict(kind='reviewed_covenant_back',region=[18,12,76,72],image_sha256=hashlib.sha256(blob).hexdigest(),source_user_instruction='test only',source_request_sha256='a'*64,source_capture_sha256='b'*64)),encoding='utf8')


def source():
    return dict(rule='guided_free_covenant_menu',signature='menu-source',status='sent',**{k:dict(status='sent') for k in ('tab_selection','free_draw','wishlist_open','wishlist_recommend','wishlist_confirm','wishlist_close','free_draw_after_wishlist')})


class SummonReturnTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);reference(self.root,current())
        self.patch=patch('tutorial_control_templates.data_root',return_value=self.root);self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def controller(self):
        r=Mock();r.ticket=None;r.s=dict(active=None,attempted={'old':{'sent':True}},completed={'done':{}},tutorial={'actions':[source()]})
        r.evidence.return_value='synthetic';r.attention.side_effect=lambda *args:(_ for _ in ()).throw(TaskAttention(*args))
        return r,TutorialController(r)
    def dispatch(self,c):
        c.step(current());return c.step(current())
    def test_current_paid_page_allows_only_back_not_a_paid_draw(self):
        p=tutorial_plan(current());self.assertEqual(p['rule'],'guided_free_covenant_return')
        self.assertEqual(p['target']['text'],'返回');self.assertLess(p['target']['x'],80)
        self.assertEqual(runner.classify(current()),'new_player_tutorial')
    def test_every_anchor_missing_weak_duplicate_or_moved_vetoes(self):
        for i in range(7):
            for mode in ('missing','weak','duplicate','moved'):
                f=current()
                if mode=='missing':f.words.pop(i)
                if mode=='weak':f.words[i]['score']=.979
                if mode=='duplicate':f.words.append(copy.deepcopy(f.words[i]))
                if mode=='moved':f.words[i]['y']=450
                self.assertIsNone(tutorial_plan(f),(i,mode))
    def test_unknown_modal_free_notice_capacity_and_failure_have_no_back(self):
        for text in ('确认','取消','OK','点击关闭','未知新通知','免费1次！','购买体力','装备背包已满','战斗失败'):
            f=current();f.words+=frame([(text,800,400)]).words
            self.assertIsNone(tutorial_plan(f),text)
    def test_incidental_art_ocr_does_not_require_whole_screen_stability(self):
        f=current();f.words+=frame([('mmmm',630,600)]).words
        self.assertEqual(tutorial_plan(f)['rule'],'guided_free_covenant_return')
    def test_missing_corrupt_tampered_or_dim_glyph_is_not_a_back(self):
        f=current();f.image[12:72,18:76]//=2;self.assertIsNone(tutorial_plan(f))
        (self.root/'control_templates'/'covenant-back.json').write_text('{broken',encoding='utf8')
        self.assertIsNone(covenant_back(current()))
        (self.root/'control_templates'/'covenant-back.json').write_text('[]',encoding='utf8')
        self.assertIsNone(covenant_back(current()))
        reference(self.root,current());(self.root/'control_templates'/'covenant-back.png').write_bytes(b'changed')
        self.assertIsNone(covenant_back(current()))
        (self.root/'control_templates'/'covenant-back.json').unlink();self.assertIsNone(covenant_back(current()))
    def test_back_uses_current_frame_persisted_once_and_preserves_progress(self):
        r,c=self.controller();before=copy.deepcopy(r.s);reserved=[]
        r.action.side_effect=lambda *a:reserved.append(copy.deepcopy(r.s))
        f=current();c.step(f);c.step(f);r.action.assert_called_once()
        c.step(current());r.action.assert_called_once();self.assertEqual(r.action.call_args.args[1]['text'],'返回')
        self.assertEqual(reserved[0]['tutorial']['actions'][0]['return_navigation']['status'],'reserved')
        self.assertEqual(r.s['tutorial']['actions'][0]['return_navigation']['status'],'sent')
        self.dispatch(TutorialController(r));r.action.assert_called_once()
        for k in ('active','attempted','completed'):self.assertEqual(r.s[k],before[k])
    def test_no_source_incomplete_ambiguous_or_active_source_never_clicks(self):
        for mode in ('none','duplicate','unknown_draw','missing_config','active'):
            r,c=self.controller()
            if mode=='none':r.s['tutorial']['actions']=[]
            if mode=='duplicate':r.s['tutorial']['actions'].append(source())
            if mode=='unknown_draw':r.s['tutorial']['actions'][0]['free_draw_after_wishlist']['status']='reserved'
            if mode=='missing_config':del r.s['tutorial']['actions'][0]['wishlist_close']
            if mode=='active':r.s['active']={'key':'entry'}
            with self.assertRaises(TaskAttention):self.dispatch(c)
            r.action.assert_not_called()
    def test_save_failure_and_send_unknown_never_become_second_send(self):
        r,c=self.controller();r.save.side_effect=OSError('full')
        with self.assertRaises(OSError):self.dispatch(c)
        r.action.assert_not_called()
        r,c=self.controller();r.action.side_effect=RuntimeError('unknown send')
        with self.assertRaises(RuntimeError):self.dispatch(c)
        self.assertEqual(r.s['tutorial']['actions'][0]['return_navigation']['status'],'reserved')
        r.action.reset_mock();r.action.side_effect=None;self.dispatch(TutorialController(r));r.action.assert_not_called()
    def test_expired_frame_does_not_dispatch(self):
        r,c=self.controller();f=current();f.at=time.time()-10;c.step(f);r.action.assert_not_called()

class SummonEpisodeTests(unittest.TestCase):
    def current(self):
        return frame([('进行圣约召唤(1/1)',940,147),('Episode',1000,234),('欧勒毕斯指南',1190,220),('图鉴',1350,220),('英雄',1500,220),('成就',1190,655),('英雄休息室',1350,655),('召唤',1045,569)])
    def test_complete_menu_targets_only_episode_and_missing_anchor_never_clicks(self):
        p=tutorial_plan(self.current());self.assertEqual(p['rule'],'guided_free_covenant_episode');self.assertEqual(p['target']['text'],'Episode')
        for i in range(8):
            f=self.current();f.words.pop(i);self.assertIsNone(tutorial_plan(f),i)
        for text in ('确认','取消','点击关闭','新通知','购买体力'):
            f=self.current();f.words+=frame([(text,800,400)]).words;self.assertIsNone(tutorial_plan(f))
    def test_original_return_sent_required_and_episode_navigation_is_one_use(self):
        for status in ('sent','reserved',None):
            r=Mock();r.ticket=None;s=source();s['return_navigation']={'status':status}
            r.s={'active':None,'tutorial':{'actions':[s]}};r.evidence.return_value='synthetic'
            r.attention.side_effect=lambda *a:(_ for _ in ()).throw(TaskAttention(*a));c=TutorialController(r)
            if status=='sent':
                c.step(self.current());c.step(self.current());r.action.assert_called_once()
                self.assertEqual(r.action.call_args.args[1]['text'],'Episode')
                TutorialController(r).step(self.current());r.action.assert_called_once()
            else:
                with self.assertRaises(TaskAttention):c.step(self.current())
                r.action.assert_not_called()

if __name__=='__main__':unittest.main()
