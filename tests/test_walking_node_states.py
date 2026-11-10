"""Enabled node plates are not limited to blue/gold; pointers never authorize entry."""
import copy
import unittest
from pathlib import Path

import runner
import test_walking_map as walking
from walking_map import walking_map_info,node_key


def native_plate(f,number,hue=145):
    row=next(r for r in walking_map_info(f)['rows'] if r['number']==number)
    x,y=row['node_target']
    colour=tuple(map(int,runner.cv2.cvtColor(runner.np.uint8([[[hue,220,230]]]),runner.cv2.COLOR_HSV2BGR)[0,0]))
    runner.cv2.ellipse(f.image,(x,y),(26,17),0,0,360,colour,-1)
    runner.cv2.line(f.image,(x-7,y-6),(x+7,y+6),(240,240,240),2)
    runner.cv2.line(f.image,(x+7,y-6),(x-7,y+6),(240,240,240),2)
    return f


class WalkingNodeStateTests(unittest.TestCase):
    def test_gold_blue_and_purple_native_plates_allow_only_free_navigation(self):
        for hue in (20,100,130,145,160):
            with self.subTest(hue=hue):
                page=walking_map_info(native_plate(walking.map_frame(coloured=()),2,hue))
                row=next(r for r in page['rows'] if r['number']==2)
                self.assertTrue(row['navigation_visible']);self.assertGreaterEqual(row['node_centre_colour_pixels'],80)
                self.assertEqual(row['completion'],'unconfirmed')
    def test_purple_pointer_over_grey_plate_is_not_positive_unlock(self):
        f=walking.map_frame(coloured=());row=walking_map_info(f)['rows'][0]
        x,y=row['node_target']
        purple=tuple(map(int,runner.cv2.cvtColor(runner.np.uint8([[[145,220,230]]]),runner.cv2.COLOR_HSV2BGR)[0,0]))
        runner.cv2.rectangle(f.image,(x-18,y-150),(x+18,y-9),purple,-1)
        page=walking_map_info(f);row=next(r for r in page['rows'] if r['number']==row['number'])
        self.assertGreater(row['marker_score'],80);self.assertFalse(row['navigation_visible'])
    def test_green_terrain_outside_grey_plate_does_not_enable_it(self):
        f=walking.map_frame(coloured=());row=walking_map_info(f)['rows'][0];x,y=row['node_target']
        runner.cv2.rectangle(f.image,(x-24,y-24),(x+24,y+24),(0,220,0),-1)
        runner.cv2.ellipse(f.image,(x,y),(26,17),0,0,360,(70,70,70),-1)
        row=next(r for r in walking_map_info(f)['rows'] if r['number']==row['number'])
        self.assertFalse(row['navigation_visible'])
    def test_small_purple_flicker_does_not_enable_grey_node(self):
        f=walking.map_frame(coloured=());row=walking_map_info(f)['rows'][0];x,y=row['node_target']
        runner.cv2.circle(f.image,(x,y),4,(200,40,200),-1)
        row=next(r for r in walking_map_info(f)['rows'] if r['number']==row['number'])
        self.assertFalse(row['navigation_visible'])
    def test_closed_padlock_overrides_purple_plate(self):
        f=native_plate(walking.map_frame(coloured=()),2);row=next(r for r in walking_map_info(f)['rows'] if r['number']==2)
        lock=runner.cv2.imdecode(runner.np.frombuffer((Path(runner.__file__).parent/'assets/lock.png').read_bytes(),runner.np.uint8),0)
        h,w=lock.shape;x,y=row['node_target'];f.image[y-h//2:y-h//2+h,x-w//2:x-w//2+w]=runner.cv2.cvtColor(lock,runner.cv2.COLOR_GRAY2BGR)
        row=next(r for r in walking_map_info(f)['rows'] if r['number']==2)
        self.assertTrue(row['locked']);self.assertFalse(row['navigation_visible'])
    def test_plate_position_tracks_current_caption_after_map_pan(self):
        f=walking.map_frame(coloured=())
        word=next(w for w in f.words if w['text'].startswith('2.'));word['x']-=120;word['y']+=80
        f=native_plate(f,2);row=next(r for r in walking_map_info(f)['rows'] if r['number']==2)
        self.assertTrue(row['navigation_visible']);self.assertEqual(row['node_target'],(682,460))
    def cleared_first(self):
        case=walking.WalkingMapTests();r,s=case.opened();case.enter(r,s);s.clear('synthetic independent settlement')
        return case,r,s
    def test_after_success_purple_next_node_uses_original_chain_and_only_one_new_entry(self):
        case,r,s=self.cleared_first();old_attempts=copy.deepcopy(s.book['attempted']);old_completions=copy.deepcopy(s.book['completed'])
        f=native_plate(walking.map_frame(coloured=(1,)),2)
        case.apply(r,s,f);self.assertIn('选择行走地图节点 2',r.action.call_args.args[0])
        case.apply(r,s,native_plate(walking.map_frame(coloured=(1,)),2))
        self.assertEqual(r.action.call_args.kwargs['word']['text'],'准备战斗')
        case.enter(r,s,number=2,name='清泉溪谷');self.assertEqual(s.book['active']['stage'],node_key('示例地区',2))
        count=r.action.call_count;case.enter(r,s,number=2,name='清泉溪谷');self.assertEqual(r.action.call_count,count)
        for key,value in old_attempts.items():self.assertEqual(s.book['attempted'][key],value)
        self.assertEqual(s.book['completed'],old_completions)
    def test_purple_plate_never_bypasses_preparation_number(self):
        case,r,s=self.cleared_first()
        case.apply(r,s,native_plate(walking.map_frame(coloured=(1,)),2))
        case.apply(r,s,native_plate(walking.map_frame(coloured=(1,)),2))
        count=r.action.call_count;case.enter(r,s,number=1,name='银杉森林')
        r.back.assert_called_once();self.assertEqual(r.action.call_count,count)
        self.assertEqual(len(s.book['attempted']),1);self.assertIsNone(s.book['active'])


if __name__=='__main__':unittest.main()
