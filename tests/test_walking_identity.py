"""Generated walking identity/field regressions; no private client captures."""
import copy
import hashlib
import time
import unittest
from unittest.mock import Mock,patch

import runner
from walking_map import walking_map_info,strengthen_walking_map_title,node_key
import test_walking_map as walking_tests
from test_walking_map import map_frame,prep


class WalkingIdentityTests(unittest.TestCase):
    make=walking_tests.WalkingMapTests.make
    apply=walking_tests.WalkingMapTests.apply
    opened=walking_tests.WalkingMapTests.opened
    enter=walking_tests.WalkingMapTests.enter

    def invalid_title(self):
        f=map_frame();word=f.words[0];word.update(text='混示例地区',x=118,
            box=[[54,24],[182,24],[182,61],[54,61]])
        return f

    def title_read(self,text='示例地区',score=.999):
        return ([[[0,8],[120,8],[120,46],[0,46]],text,score],)

    def test_back_control_contamination_is_invalid_despite_high_confidence(self):
        f=self.invalid_title();self.assertIsNone(walking_map_info(f))
        self.assertGreater(f.words[0]['score'],.98)

    def test_missing_valid_title_gets_one_original_field_read_and_keeps_source(self):
        f=self.invalid_title();original=copy.deepcopy(f.words[0]);at=f.at;pixels=f.image.tobytes()
        ocr=Mock(return_value=(self.title_read(),None))
        strengthen_walking_map_title(f,ocr);strengthen_walking_map_title(f,ocr)
        ocr.assert_called_once();self.assertEqual(ocr.call_args.args[0].shape,(54,420,3))
        self.assertEqual(f.at,at);self.assertEqual(f.image.tobytes(),pixels)
        self.assertEqual(f.words[0],original);self.assertEqual(walking_map_info(f)['region'],'示例地区')
        proof=f.words[-1]['verification'];self.assertEqual(proof['captured_at'],at)
        self.assertEqual(proof['crop_sha256'],hashlib.sha256(f.image[16:70,80:500].tobytes()).hexdigest())

    def test_weak_valid_original_can_only_be_strengthened_with_same_text_once(self):
        f=map_frame();f.words[0]['score']=.97;old=copy.deepcopy(f.words[0])
        ocr=Mock(return_value=(self.title_read(),None));strengthen_walking_map_title(f,ocr)
        self.assertEqual(walking_map_info(f)['region'],'示例地区');self.assertEqual(f.words[0],old)
        g=map_frame();g.words[0]['score']=.97
        strengthen_walking_map_title(g,Mock(return_value=(self.title_read('其他地区'),None)))
        self.assertIsNone(walking_map_info(g))

    def test_valid_title_is_not_reread_or_replaced_by_old_expected_name(self):
        f=map_frame('另一大陆');ocr=Mock()
        strengthen_walking_map_title(f,ocr);ocr.assert_not_called()
        self.assertEqual(walking_map_info(f)['region'],'另一大陆')

    def test_weak_ambiguous_or_unknown_field_stays_zero_authority(self):
        for rows in (self.title_read(score=.979),self.title_read()+self.title_read('另一大陆'),(),self.title_read('确认')):
            f=self.invalid_title();ocr=Mock(return_value=(rows,None))
            strengthen_walking_map_title(f,ocr);strengthen_walking_map_title(f,ocr)
            ocr.assert_called_once();self.assertIsNone(walking_map_info(f))

    def test_title_read_requires_full_native_shell_and_no_modal(self):
        for variant in ('missing','modal'):
            f=self.invalid_title()
            if variant=='missing':f.words.pop(1)
            else:f.words+=prep().words[:1]+[dict(text='确认',score=.999,x=800,y=450)]
            ocr=Mock();strengthen_walking_map_title(f,ocr);ocr.assert_not_called()

    def test_unrouted_title_change_does_not_create_a_blank_book_or_send_input(self):
        r,s=self.opened();old=copy.deepcopy(r.s);bid=s.book_id;count=r.action.call_count
        self.apply(r,s,map_frame('混示例地区'))
        self.assertEqual(s.book_id,bid);self.assertEqual(set(r.s['story_progress']['books']),set(old['story_progress']['books']))
        self.assertEqual(r.s['story_progress']['current_book'],bid)
        self.assertEqual(r.action.call_count,count);r.attention.assert_not_called()
        self.assertEqual(s.book['walking_map'],old['story_progress']['books'][bid]['walking_map'])

    def test_mismatched_title_cannot_switch_to_an_existing_other_book(self):
        r,s=self.opened();bid=s.book_id
        r.s['story_progress']['books']['walking|别的地区']=dict(region='别的地区',regions_seen=['别的地区'],walking_map={})
        self.apply(r,s,map_frame('别的地区'))
        self.assertEqual(s.book_id,bid);self.assertEqual(r.s['story_progress']['current_book'],bid)

    def test_preparation_region_mismatch_returns_map_preserving_both_sources(self):
        r,s=self.opened();source=copy.deepcopy(s.book['walking_map']['preparation_source'])
        nav=copy.deepcopy(s.book['walking_map']['navigation']);self.enter(r,s,region='另一个地区')
        r.back.assert_called_once();self.assertEqual(s.book['attempted'],{})
        self.assertEqual(s.book['walking_map']['preparation_source'],source)
        self.assertEqual(s.book['walking_map']['navigation'][:len(nav)],nav)
        self.assertEqual(s.book['walking_map']['navigation'][-1]['status'],'sent')
        self.assertIsNone(s.book['walking_map']['navigation'][-1]['source'])

    def test_missing_node_in_source_returns_known_page_not_entry_or_defeat(self):
        r,s=self.opened();self.enter(r,s,number=4,name='原图尚不可见节点')
        r.back.assert_called_once();self.assertEqual(s.book['attempted'],{});self.assertEqual(s.book['completed'],{})

    def test_pending_resource_entry_cannot_be_navigated_away_on_mismatch(self):
        r,s=self.opened();self.enter(r,s);old=copy.deepcopy(s.book['attempted']);count=r.action.call_count
        self.enter(r,s,region='别的地区');r.back.assert_not_called()
        self.assertEqual(s.book['attempted'],old);self.assertEqual(r.action.call_count,count)

    def test_free_return_is_bounded_and_unknown_or_failed_intent_not_reused(self):
        r,s=self.opened();self.enter(r,s,region='另一个地区');self.enter(r,s,region='另一个地区')
        r.back.assert_called_once();v=s.book['walking_map']['navigation'][-1];v['status']='unknown'
        self.enter(r,s,region='另一个地区');r.back.assert_called_once();self.assertEqual(s.book['attempted'],{})

    def test_noncoloured_next_node_reads_only_native_preparation_then_exact_identity(self):
        r,s=self.opened();self.enter(r,s);s.clear('synthetic independent settlement')
        old=copy.deepcopy(s.book['attempted']);self.apply(r,s,map_frame(coloured=(1,)))
        self.assertEqual(r.action.call_args.kwargs['word']['text'],'准备战斗')
        self.assertEqual(s.book['attempted'],old)
        self.assertEqual(s.book['walking_map']['preparation_source']['expected_number'],2)
        self.enter(r,s);r.back.assert_called_once();self.assertEqual(s.book['attempted'],old)

    def test_native_preparation_can_verify_boss_node_without_colour_as_unlock(self):
        r,s=self.opened();self.enter(r,s);s.clear('synthetic independent settlement')
        self.apply(r,s,map_frame(coloured=(1,)));self.enter(r,s,number=2,name='清泉溪谷')
        self.assertEqual(len(s.book['attempted']),2);self.assertEqual(len(s.book['completed']),1)
        self.assertEqual(s.book['active']['stage'],node_key('示例地区',2))

    def test_fixed_field_does_not_refresh_expired_frame_for_navigation(self):
        f=self.invalid_title();f.at=time.time()-10
        strengthen_walking_map_title(f,Mock(return_value=(self.title_read(),None)))
        r,s=self.make(f);self.apply(r,s,f);r.action.assert_not_called()

    def test_missing_next_after_bounded_search_reads_parent_route_without_fake_completion(self):
        r,s=self.opened();self.enter(r,s);s.clear('synthetic independent settlement')
        key=node_key('示例地区',2);s.book['navigation']=dict(desired=key,pan_region='示例地区',pan_tries=4)
        old=copy.deepcopy(s.book['completed']);f=map_frame();f.words=[w for w in f.words if not w['text'].startswith('2.')]
        self.apply(r,s,f);r.back.assert_called_once();r.drag.assert_not_called();r.attention.assert_not_called()
        self.assertEqual(s.book['completed'],old);self.assertEqual(len(s.book['attempted']),1)
        self.assertEqual(s.book['walking_map']['overview_return']['status'],'sent')
        self.apply(r,s,map_frame());self.assertEqual(s.book['completed'],old)

    def test_parent_route_return_never_runs_while_resource_entry_pending(self):
        r,s=self.opened();self.enter(r,s);old=copy.deepcopy(s.book['attempted'])
        s.book['navigation']=dict(desired=node_key('示例地区',2),pan_region='示例地区',pan_tries=4)
        self.apply(r,s,map_frame());r.back.assert_not_called();r.drag.assert_not_called()
        self.assertEqual(s.book['attempted'],old)

    def test_field_read_failure_is_not_swallowed_to_send_input(self):
        f=self.invalid_title()
        with self.assertRaises(OSError):strengthen_walking_map_title(f,Mock(side_effect=OSError('ocr failed')))
        self.assertIsNone(walking_map_info(f))


if __name__=='__main__':unittest.main()
