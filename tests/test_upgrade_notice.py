"""Free account-upgrade modal: local OCR/synthetic tokens, never live game input."""
import copy,json,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from task_overlays import account_upgrade_notice_close
from abyss_core import Observation,Token,Scene,Session,classify as abyss_classify

NOTICE=[dict(text=t,x=x,y=y,score=.999) for t,x,y in [('升级！',828,312),('账号升等，行动力上限已提升。',824,437),('194>205',826,566),('点击关闭',828,722)]]
def frame(words):
    boxes=[([[w['x']-20,w['y']-10],[w['x']+20,w['y']-10],[w['x']+20,w['y']+10],[w['x']-20,w['y']+10]],w['text'],w.get('score',.999)) for w in words]
    return runner.Frame(runner.np.zeros((900,1600,3),runner.np.uint8),boxes)
def obs(words):return Observation(1600,900,[Token(w['text'],w['x']-20,w['y']-10,40,20,score=w.get('score',.999)) for w in words])

class AccountUpgradeTests(unittest.TestCase):
    def test_reported_ocr_recognizes_upgrade_not_unknown(self):
        self.assertEqual(runner.classify(frame(NOTICE)),'account_upgrade_notice')
        self.assertEqual(account_upgrade_notice_close(NOTICE)['text'],'点击关闭')
    def test_private_reported_image_has_the_same_classification(self):
        directory=Path(__file__).resolve().parents[1]/'.local/upgrade-notice'
        if not (directory/'account-upgrade.png').exists():self.skipTest('Private screenshot not distributed')
        data=json.loads((directory/'account-upgrade-ocr.json').read_text(encoding='utf-8'));im=runner.cv2.imdecode(runner.np.frombuffer((directory/'account-upgrade.png').read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
        f=runner.Frame(im,[(w['box'],w['text'],w['score']) for w in data['words']]);self.assertEqual(runner.classify(f),'account_upgrade_notice')
    def test_mainline_clicks_observed_close_without_recording_a_clear(self):
        r=runner.Runner.__new__(runner.Runner);r.last_mode=None;r.mode_since=time.time();r.unknown_gestures=0;r.ticket={'key':'current'}
        r.s={'active':{'key':'current'},'attempted':{'current':{'keep':True}},'completed':{}};before=copy.deepcopy(r.s)
        r.action=Mock();r.save=Mock()
        with patch.object(runner,'ROOT',Path('no-live-state-test')),patch('runner.event'):keep,_=r.step(frame(NOTICE))
        self.assertTrue(keep);r.action.assert_called_once();target=r.action.call_args.args[1]
        self.assertEqual((target['x'],target['y']),(828,722))
        for key in ('active','attempted','completed'):self.assertEqual(r.s[key],before[key])
    def test_abyss_close_keeps_current_floor_phase_and_wins(self):
        o=obs(NOTICE);session=Session(normal_verified=True,expected_floor=52,entered_floor=52,phase='battle');before=copy.deepcopy(session)
        reading=abyss_classify(o,True);self.assertEqual(reading.scene,Scene.ACCOUNT_UPGRADE)
        action=session.plan(reading,o);self.assertIs(action.token,o.tokens[-1]);self.assertEqual(action.token.center,(828,722))
        self.assertEqual(session,before)
    def test_capacity_numbers_and_caption_splits_are_not_hardcoded(self):
        words=[dict(text=t,x=x,y=y) for t,x,y in [('升级',800,260),('账号升级',650,360),('行动力上限已提升',930,400),('243',650,520),('254',940,520),('点击关闭',800,650)]]
        self.assertIsNotNone(account_upgrade_notice_close(words))
    def test_title_or_close_without_caption_never_authorizes_dismissal(self):
        for words in (NOTICE[:1],NOTICE[1:],NOTICE[:3],NOTICE[:1]+NOTICE[2:]):self.assertIsNone(account_upgrade_notice_close(words))
    def test_purchase_and_refill_veto_wins_over_free_upgrade_background(self):
        words=NOTICE+[dict(text='购买体力',x=800,y=450)]
        self.assertIsNone(account_upgrade_notice_close(words));self.assertEqual(runner.classify(frame(words)),'resource_stop');self.assertEqual(abyss_classify(obs(words)).scene,Scene.BLOCKED)
    def test_confirmation_overlay_is_not_clicked_through(self):
        words=NOTICE+[dict(text='确认',x=900,y=650),dict(text='取消',x=600,y=650)]
        self.assertIsNone(account_upgrade_notice_close(words));self.assertEqual(runner.classify(frame(words)),'unknown_dialog');self.assertEqual(abyss_classify(obs(words)).scene,Scene.BLOCKED)
    def test_wrong_close_region_or_low_confidence_is_not_replaced_with_fixed_point(self):
        for changes in ({'x':1450},{'y':70},{'score':.6}):
            words=copy.deepcopy(NOTICE);words[-1].update(changes);self.assertIsNone(account_upgrade_notice_close(words))
    def test_inventory_popup_priority_remains(self):
        words=NOTICE+[dict(text='装备背包已满',x=800,y=400)]
        self.assertEqual(runner.classify(frame(words)),'capacity_stop');self.assertEqual(abyss_classify(obs(words)).scene,Scene.CAPACITY)
