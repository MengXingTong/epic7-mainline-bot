"""Map completion/lock regressions. Generated fixtures and optional private screenshot only."""
import copy,json,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from mainline_map import read_stage_rating,row_markers,is_cleared,is_unlocked
from task_blockers import TaskAttention

def frame(words=(),image=None):
    results=[([[x-25,y-10],[x+25,y-10],[x+25,y+10],[x-25,y+10]],text,.999) for text,x,y in words]
    if image is None:image=runner.np.full((900,1600,3),22,runner.np.uint8)
    return runner.Frame(image,results)

def map_frame(extra=(),image=None):
    if image is None:
        image=runner.np.full((900,1600,3),22,runner.np.uint8)
        color=tuple(map(int,runner.cv2.cvtColor(runner.np.uint8([[[95,220,220]]]),runner.cv2.COLOR_HSV2BGR)[0,0]))
        runner.cv2.circle(image,(68,290),50,color,6)
    return frame([('Episode 3',156,44),('第6章正确的选择',190,136),('5.内讧',164,290),('6.疑虑扩散',166,416),('准备战斗',1390,827),*extra],image)

def fake_runner(f):
    r=runner.Runner.__new__(runner.Runner);r.frame=f;r.ticket=None;r.last_mode=None;r.mode_since=time.time();r.unknown_gestures=0
    r.cfg={'start_policy':'current_screen'};r.s={'completed':{},'attempted':{},'active':None,'victories':0}
    r.save=Mock();r.evidence=Mock(return_value='offline');r.action=Mock();r.back=Mock();return r

class RatingTests(unittest.TestCase):
    def test_absent_or_unreadable_stars_are_unknown_not_cleared(self):
        for extra in [[],[('通关星级',1300,300)],[('信用等级',1190,546),('怀疑',1320,640),('★★★',1320,680)],[('12/30',68,774)]]:
            with self.subTest(extra=extra):
                f=map_frame(extra);self.assertIsNone(read_stage_rating(f));node,_,proof=runner.Runner.__new__(runner.Runner).map_ticket(f)
                self.assertIsNone(node['star_count']);self.assertFalse(is_cleared(node));self.assertEqual(proof,'未通关蓝色当前节点')
    def test_zero_to_three_stars_from_labeled_rating(self):
        for count in range(4):
            for label,value in [('通关星级',f'{count}/3'),('关卡星级','★'*count+'☆'*(3-count))]:
                with self.subTest(count=count,label=label):
                    f=map_frame([(label,1200,300),(value,1430,300)]);node,_,proof=runner.Runner.__new__(runner.Runner).map_ticket(f)
                    self.assertEqual(node['star_count'],count);self.assertEqual(is_cleared(node),count>0)
                    self.assertEqual(proof,'已通关关卡星级' if count else '未通关蓝色当前节点')
    def test_combined_ocr_label_does_not_require_split_boxes(self):
        for text,count in [('通关星级：1/3',1),('最高星级★★☆',2),('已获星数3',3)]:
            reading=read_stage_rating(map_frame([(text,1300,300)]));self.assertEqual(reading['count'],count)
    def test_hero_rarity_and_credit_diamonds_cannot_supply_stage_stars(self):
        f=map_frame([('星级',1300,300),('★★★',1450,300),('信用等级',1190,546),('通关星级：3/3',1300,630)])
        self.assertIsNone(read_stage_rating(f))
    def test_ambiguous_or_low_confidence_rating_not_assumed_complete(self):
        f=map_frame([('通关星级',1200,300),('0/3',1350,300),('3/3',1480,300)])
        self.assertIsNone(read_stage_rating(f));f=map_frame([('通关星级：3/3',1300,300)]);f.words[-1]['score']=.5
        self.assertIsNone(read_stage_rating(f))

class MarkerTests(unittest.TestCase):
    def test_old_pixel_threshold_would_misclassify_green_background(self):
        f=map_frame();f.image[300:325,80:102]=(0,255,0)
        node,_,proof=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertGreaterEqual(node['green'],14);self.assertFalse(node['clear_badge']);self.assertEqual(proof,'未通关蓝色当前节点')
    def test_solid_green_patch_is_not_a_check_badge(self):
        f=map_frame();f.image[240:350,:130]=(0,255,0)
        markers=row_markers(f.image,runner.cv2.cvtColor(f.image,runner.cv2.COLOR_BGR2HSV),290)
        self.assertFalse(markers['clear_badge'])
    def test_green_circle_without_tick_is_not_a_completion_badge(self):
        im=runner.np.full((900,1600,3),22,runner.np.uint8);runner.cv2.circle(im,(68,290),50,(0,255,0),5);runner.cv2.circle(im,(95,318),14,(0,255,0),3)
        markers=row_markers(im,runner.cv2.cvtColor(im,runner.cv2.COLOR_BGR2HSV),290)
        self.assertFalse(markers['clear_badge'])
    def test_unknown_lock_detection_is_not_treated_as_unlocked(self):
        self.assertFalse(is_unlocked({'stage':6}));self.assertFalse(is_unlocked({'lock_score':.95,'locked':True}));self.assertTrue(is_unlocked({'lock_score':.2,'locked':False}))

class RoutingTests(unittest.TestCase):
    def run_step(self,r):
        with patch.object(runner,'event'),patch.object(runner,'ROOT',Path('no-live-state-test')):return r.step(r.frame)
    def test_pending_attempt_cannot_mark_clear_or_skip_to_locked_next(self):
        f=map_frame();r=fake_runner(f);r.s['attempted']['E3-C6-S5']={'requested':True};before=copy.deepcopy(r.s)
        self.assertTrue(self.run_step(r)[0]);self.assertNotIn('attention',r.s);r.action.assert_not_called()
        self.assertEqual(r.s['attempted'],before['attempted']);self.assertEqual(r.s['completed'],{})
    def test_old_completed_entry_without_live_proof_does_not_skip_current(self):
        r=fake_runner(map_frame());r.s['completed']['E3-C6-S5']={'proof':'old'}
        self.assertTrue(self.run_step(r)[0])
        r.action.assert_not_called()
    def test_unattempted_visible_current_stage_is_still_allowed_without_star_panel(self):
        r=fake_runner(map_frame());keep,_=self.run_step(r)
        self.assertTrue(keep);self.assertEqual(r.action.call_args.args[0],'未通关验证通过，准备战斗');self.assertEqual(r.ticket['key'],'E3-C6-S5')
    def test_cleared_stage_cannot_click_a_locked_successor(self):
        r=fake_runner(map_frame());r.map_ticket=Mock(return_value=({'key':'E3-C6-S5','stage':5},[{'stage':6,'lock_score':.96,'locked':True,'x':166,'y':416}],'已通关关卡星级'))
        self.assertTrue(self.run_step(r)[0]);self.assertNotIn('attention',r.s);r.action.assert_not_called()
    def test_cleared_stage_can_select_a_verified_unlocked_successor(self):
        r=fake_runner(map_frame());r.map_ticket=Mock(return_value=({'key':'E3-C6-S5','stage':5},[{'stage':6,'lock_score':.2,'locked':False,'completion':'unconfirmed','x':166,'y':416}],'已通关关卡星级'))
        keep,_=self.run_step(r);self.assertTrue(keep);self.assertEqual(r.action.call_args.kwargs['xy'],(166,416));self.assertIsNone(r.ticket)

class ReportedLayoutTests(unittest.TestCase):
    def test_reported_boss_layout_reads_stage5_unfinished_and_next_three_locked(self):
        directory=Path(__file__).resolve().parents[1]/'.local/map-layout-fix'
        if not (directory/'reported-map.png').exists():self.skipTest('Private user screenshot is not distributed')
        data=json.loads((directory/'reported-map-ocr.json').read_text(encoding='utf-8'));im=runner.cv2.imdecode(runner.np.frombuffer((directory/'reported-map.png').read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
        f=runner.Frame(im,[(w['box'],w['text'],w['score']) for w in data['words']]);node,rows,proof=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(node['key'],'E3-C6-S5');self.assertEqual(proof,'未通关蓝色当前节点');self.assertFalse(node['clear_badge']);self.assertIsNone(node['star_count'])
        self.assertEqual({row['stage'] for row in rows if row['locked']},{6,7,8})
        r=fake_runner(f);r.s['attempted'][node['key']]={'requested':True}
        with patch.object(runner,'event'),patch.object(runner,'ROOT',Path('no-live-state-test')):
            self.assertTrue(r.step(f)[0])
        r.action.assert_not_called();self.assertEqual(r.s['completed'],{})
