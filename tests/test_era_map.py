"""Era header, small green badge and clipped CURRENT story-result regressions."""
import copy,unittest
import runner
from mainline_map import clipped_story_completion
from test_map_layout import frame


def era_map(tick=True):
    im=runner.np.full((900,1600,3),22,runner.np.uint8)
    cyan=tuple(map(int,runner.cv2.cvtColor(runner.np.uint8([[[95,220,220]]]),runner.cv2.COLOR_HSV2BGR)[0,0]))
    runner.cv2.circle(im,(68,290),50,cyan,6)
    runner.cv2.circle(im,(68,165),35,(0,220,80),3)
    runner.cv2.circle(im,(92,187),11,(0,220,80),3)
    if tick:runner.cv2.polylines(im,[runner.np.array([(87,186),(91,191),(100,180)],runner.np.int32)],False,(0,220,80),3)
    im[:166,:110]=22
    return frame([('第6时代Episode',197,43),('第1章使徒现身',187,138),('2.进击的魔神军队',232,290),('3.紧急疏散',166,416),('4.无法逃离的噩梦',200,540),('准备战斗',1390,827)],im)

class EraMapTests(unittest.TestCase):
    def test_exact_era_header_joins_normal_map_identity_chain(self):
        f=era_map();self.assertEqual(runner.classify(f),'map')
        d,rows,proof=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(d['key'],'E6-C1-S2');self.assertEqual(proof,'未通关蓝色当前节点')
        f.words[0]['text']='Rank 6 Episode';self.assertIsNone(runner.mainline_episode(f))
    def test_clipped_predecessor_is_clear_evidence_but_never_clickable_or_stars(self):
        f=era_map();d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        entry=dict(episode=6,chapter=1,stage=1,name='original story',entry_kind='story_only')
        proof=clipped_story_completion(f,entry,d,rows)
        self.assertIsNotNone(proof);self.assertEqual(proof['stage'],1);self.assertFalse(proof['clickable']);self.assertIsNone(proof['star_count'])
    def test_green_ring_without_internal_check_is_not_clear(self):
        f=era_map(False);d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        entry=dict(episode=6,chapter=1,stage=1,name='original story',entry_kind='story_only')
        self.assertIsNone(clipped_story_completion(f,entry,d,rows))
    def test_one_weak_middle_label_uses_three_other_indexed_rows_not_a_lower_ocr_threshold(self):
        f=era_map();f.words[4]['score']=.84
        f.words+=frame([('5.另一关',180,665)]).words
        d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(sorted(row['stage'] for row in rows),[2,3,5])
        entry=dict(episode=6,chapter=1,stage=1,name='original',entry_kind='story_only')
        proof=clipped_story_completion(f,entry,d,rows)
        self.assertIsNotNone(proof);self.assertFalse(proof['clickable']);self.assertIsNone(proof['star_count'])
        self.assertEqual([row['stage'] for row in proof['grid']],[2,3,5])
    def test_sparse_grid_still_requires_consistent_numbered_spacing_and_internal_check(self):
        for mode in ('spacing','number','duplicate','no_check'):
            f=era_map(mode!='no_check');f.words[4]['score']=.84
            f.words+=frame([('5.另一关',180,665)]).words
            d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
            entry=dict(episode=6,chapter=1,stage=1,name='original',entry_kind='story_only')
            if mode=='spacing':next(row for row in rows if row['stage']==5)['y']+=20
            if mode=='number':next(row for row in rows if row['stage']==5)['stage']=6
            if mode=='duplicate':rows.append(copy.deepcopy(next(row for row in rows if row['stage']==3)))
            self.assertIsNone(clipped_story_completion(f,entry,d,rows),mode)
    def test_wrong_entry_chain_or_ambiguous_grid_is_never_inferred(self):
        f=era_map();d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        for change in ('battle','chapter','stage','grid','missing','locked'):
            entry=dict(episode=6,chapter=1,stage=1,name='original story',entry_kind='story_only');selected=copy.deepcopy(d);grid=copy.deepcopy(rows)
            if change=='battle':entry['entry_kind']='battle'
            if change=='chapter':entry['chapter']=2
            if change=='stage':entry['stage']=0
            if change=='grid':grid[-1]['y']+=10
            if change=='missing':grid.pop()
            if change=='locked':selected['locked']=True
            self.assertIsNone(clipped_story_completion(f,entry,selected,grid))

if __name__=='__main__':unittest.main()
