import copy,unittest
from test_free_story_handoff import case
from mainline_story_results import native_chapter_completion

class NativeChapterResultTests(unittest.TestCase):
    def setup_case(self):
        r,b,f,old,d,c=case();a=r.s['active'];key=a['key'];a.update(playback_observed_at='observed',playback_evidence='evidence/story.png')
        target=dict(episode=6,chapter=2,stage=1,key='E6-C2-S1',locked=False,cyan=.3,clear_badge=False)
        trace=[dict(kind='screen',screen='story',stage=key),dict(kind='action',action='跳过剧情',stage=key),dict(kind='action',action='确认跳过剧情',stage=key),dict(kind='screen',screen='story_reward',stage=key),dict(kind='action',action='关闭已发放的免费奖励遮罩',stage=key)]
        return r.s,target,[dict(stage=2,locked=True)],trace
    def test_unbroken_native_next_chapter_is_independent_result_not_close_alone(self):
        s,d,rows,events=self.setup_case();self.assertIsNotNone(native_chapter_completion(s,d,rows,events))
    def test_unverified_story_failed_archived_or_manual_navigation_cannot_infer_clear(self):
        for change in ('no_play','same_chapter','jump','already_clear','next_unlocked','unknown','navigation','archive'):
            s,d,rows,events=self.setup_case()
            if change=='no_play':s['active'].pop('playback_observed_at')
            if change=='same_chapter':d['chapter']=1
            if change=='jump':d['chapter']=3
            if change=='already_clear':d['clear_badge']=True
            if change=='next_unlocked':rows[0]['locked']=False
            if change=='unknown':events.insert(2,dict(kind='screen',screen='unknown_dialog'))
            if change=='navigation':events.insert(-1,dict(kind='action',action='完成本章后进入下一章',stage=s['active']['key']))
            if change=='archive':s['unresolved_entries']=[dict(entry=copy.deepcopy(s['active']))]
            self.assertIsNone(native_chapter_completion(s,d,rows,events),change)

if __name__=='__main__':unittest.main()
