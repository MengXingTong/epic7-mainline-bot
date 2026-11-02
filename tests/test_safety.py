"""Offline tests only. No ADB, no game inputs, no live-state writes."""
import copy,importlib.util,json,time,unittest,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('runner',ROOT/'runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.event=lambda *a,**k: None

def fake(words):
    out=[]
    for t,x,y in words: out.append(([[x-12,y-10],[x+12,y-10],[x+12,y+10],[x-12,y+10]],t,.999))
    return m.Frame(m.np.full((900,1600,3),50,dtype=m.np.uint8),out)
def fixture(name):
    p=Path(os.environ.get('EPIC7_PRIVATE_FIXTURES',str(ROOT/'tests'/'fixtures')))
    if not (p/(name+'.png')).is_file() or not (p/(name+'-ocr.json')).is_file():
        raise unittest.SkipTest('Private screenshot fixtures are not distributed; use EPIC7_PRIVATE_FIXTURES for local regression')
    data=json.loads((p/(name+'-ocr.json')).read_text(encoding='utf-8-sig'))
    rows=[(w['box'],w['text'],w['score']) for w in data['words']] if isinstance(data,dict) else data
    return m.Frame(m.cv2.imread(str(p/(name+'.png'))),rows)
class SafetyTests(unittest.TestCase):
    def test_refill_before_confirm(self):
        for text in ['体力不足','是否消耗道具兑换体力','是否使用生命之叶补充体力','天空石购买体力']:
            with self.subTest(text=text):
                self.assertEqual(m.classify(fake([(text,800,420),('确认',935,575),('取消',666,575)])),'resource_stop')
    def test_unknown_confirm_never_whitelisted(self):
        self.assertEqual(m.classify(fake([('确认',1442,825)])),'unknown_dialog')
    def test_story_only_confirm(self):
        self.assertEqual(m.classify(fake([('确定要跳过故事吗？',800,404),('确认',935,575),('取消',666,575)])),'skip_confirm')
    def test_settlement_two_labels_required(self):
        self.assertEqual(m.classify(fake([('获得的道具',1453,60),('战斗结果',1260,825),('确认',1442,825)])),'settlement')
        self.assertEqual(m.classify(fake([('获得的道具',1453,60),('确认',1442,825)])),'unknown_dialog')
    def test_defeat(self):
        self.assertEqual(m.classify(fake([('FAILED',800,250),('再次挑战',1400,825)])),'defeat')
    def test_split_stylized_defeat_banner(self):
        self.assertEqual(m.classify(fake([('FAI',690,550),('LED',900,550),('3/3',212,26)])),'defeat')
    def test_actual_victory_splash_not_mistaken_for_battle(self):
        self.assertEqual(m.classify(fixture('victory')),'victory')
    def test_actual_free_star_reward_overlay(self):
        self.assertEqual(m.classify(fixture('star-reward')),'story_reward')
    def test_actual_free_unlock_notice(self):
        self.assertEqual(m.classify(fixture('unlock-notice')),'unlock_notice')
    def test_unlock_notice_never_overrides_resource_veto(self):
        self.assertEqual(m.classify(fake([('支线故事通知',800,200),('已解锁 支线故事一览',800,320),('点击关闭',800,698),('是否使用道具兑换体力',800,420)])),'resource_stop')
    def test_actual_bond_unlock_notification(self):
        self.assertEqual(m.classify(fixture('bond-notice')),'bond_notice')
    def test_post_clear_screen_chooses_leave_not_replay(self):
        f=fake([('离开',158,825),('大厅',335,825),('重新进行',1476,825),('3/3',212,26)])
        self.assertEqual(m.classify(f),'post_clear_exit');r=self.make_runner(f)
        r.s['last_cleared']={'key':'E2-C8-S10'};r.step(f)
        self.assertEqual(r.calls,['已结算后离开关卡，绝不重新进行'])
    def test_post_clear_exit_requires_recorded_settlement(self):
        f=fake([('离开',158,825),('大厅',335,825),('重新进行',1476,825),('3/3',212,26)])
        r=self.make_runner(f);r.s['active']={'key':'E2-C8-S10'};r.step(f)
        self.assertTrue(r.calls[0].startswith('STOP: 关后离开界面缺少已结算记录'))
    def cost_runner(self,f):
        r=self.make_runner(f);r.title_matches=lambda f:True
        r.ticket={'key':'E2-C9-S8','episode':2,'chapter':9,'stage':8,'name':'苦征恶战II','phase':'support','verified_epoch':time.time()}
        return r
    def test_transient_cost_ocr_does_not_guess_or_enter(self):
        f=fixture('team-cost-ocr-transient');r=self.cost_runner(f);keep,delay=r.step(f)
        self.assertTrue(keep);self.assertEqual(r.calls,[]);self.assertEqual(r.s['attempted'],{})
    def test_persistent_cost_ocr_failure_still_stops(self):
        f=fixture('team-cost-ocr-transient');r=self.cost_runner(f);r.last_mode='team';r.mode_since=time.time()-25
        keep,delay=r.step(f);self.assertFalse(keep);self.assertTrue(r.calls[0].startswith('STOP: 连续20秒'))
    def test_reliable_next_frame_allows_only_one_entry(self):
        bad=fixture('team-cost-ocr-transient');good=fixture('team-cost-readable');r=self.cost_runner(bad)
        r.step(bad);self.assertEqual(r.calls,[]);r.frame=good;r.step(good)
        self.assertEqual(r.calls,['进行任务（仅一次入场）']);self.assertEqual(list(r.s['attempted']),['E2-C9-S8'])
    def test_actual_fragmented_clear_banner(self):
        f=fixture('victory-fragmented');self.assertTrue(m.victory_objectives_verified(f));self.assertEqual(m.classify(f),'victory')
    def test_fragmented_victory_requires_green_success_check(self):
        f=fixture('victory-fragmented');f.image[680:755,245:320]=0
        self.assertFalse(m.victory_objectives_verified(f));self.assertNotEqual(m.classify(f),'victory')
    def test_prepare_objectives_not_mistaken_for_victory(self):
        f=fixture('team-cost-readable');self.assertFalse(m.victory_objectives_verified(f));self.assertEqual(m.classify(f),'team')
    def test_victory_background_never_overrides_refill_veto(self):
        f=fixture('victory-fragmented');rows=[(w['box'],w['text'],w['score']) for w in f.words]
        rows.append(([[600,400],[1100,400],[1100,450],[600,450]],'是否消耗道具兑换体力',.999))
        self.assertEqual(m.classify(m.Frame(f.image,rows)),'resource_stop')
    def test_actual_friend_request_is_declined(self):
        f=fixture('friend-request');self.assertEqual(m.classify(f),'friend_decline');r=self.make_runner(f);r.step(f)
        self.assertEqual(r.calls,['取消好友申请提示，不发送任何好友申请'])
    def test_friend_request_requires_cancel_and_request_buttons(self):
        f=fake([('给予协助的朋友',800,220),('发送好友申请吗',800,340),('确认',1440,825),('申请',935,660)])
        self.assertEqual(m.classify(f),'unknown_dialog')
    def test_friend_popup_never_overrides_refill_veto(self):
        f=fixture('friend-request');rows=[(w['box'],w['text'],w['score']) for w in f.words]
        rows.append(([[600,400],[1100,400],[1100,450],[600,450]],'是否消耗道具兑换体力',.999))
        self.assertEqual(m.classify(m.Frame(f.image,rows)),'resource_stop')
    def test_actual_paid_revive_screen_is_defeat(self):
        f=fixture('defeat-revive');self.assertTrue(m.paid_revive_defeat_verified(f));self.assertEqual(m.classify(f),'defeat')
    def test_paid_revive_requires_blue_currency_icon(self):
        f=fixture('defeat-revive');f.image[790:860,945:990]=0
        self.assertFalse(m.paid_revive_defeat_verified(f))
    def test_free_resume_not_mistaken_for_paid_defeat(self):
        f=fake([('离开',158,825),('大厅',335,825),('继续战斗',1140,825),('重新进行',1476,825)])
        self.assertFalse(m.paid_revive_defeat_verified(f))
    def test_actual_defeat_stops_without_revive_or_replay(self):
        f=fixture('defeat-revive');r=self.make_runner(f);keep,delay=r.step(f)
        self.assertFalse(keep);self.assertEqual(len(r.calls),1);self.assertTrue(r.calls[0].startswith('STOP: 识别到战斗失败'))
    def test_version_server_error_retries_network_and_preserves_pending_story(self):
        f=fake([('无法连接至版本服务器。',800,214),('网络连接失败',800,438),('点击重试',802,675)])
        self.assertEqual(m.classify(f),'network_error');r=self.make_runner(f)
        book={'active':{'id':'pending','stage':'3-7'},'completed':{'successful':{}},'farm_runs':43}
        r.s['story_progress']={'books':{'saint_eulogy':copy.deepcopy(book)}}
        keep,delay=r.step(f);self.assertTrue(keep);self.assertEqual(delay,10)
        self.assertEqual(r.calls,['网络重试（非关卡重试）']);self.assertEqual(r.s['story_progress']['books']['saint_eulogy'],book)
    def test_version_retry_needs_all_three_positive_labels_and_positions(self):
        for words in ([('网络连接失败',800,438),('点击重试',802,675)],[('无法连接至版本服务器。',800,214),('网络连接失败',800,438),('点击重试',1400,825)]):
            self.assertNotEqual(m.classify(fake(words)),'network_error')
    def test_version_network_page_does_not_bypass_resources_or_retry_budget(self):
        words=[('无法连接至版本服务器。',800,214),('网络连接失败',800,438),('点击重试',802,675)]
        self.assertEqual(m.classify(fake(words+[('购买体力',800,550)])),'resource_stop')
        r=self.make_runner(fake(words));r.s['network_retries']=[time.time()]*3
        keep,delay=r.step(fake(words));self.assertFalse(keep);self.assertEqual(len(r.calls),1);self.assertTrue(r.calls[0].startswith('STOP: 10分钟内三次网络重连'))
    def test_actual_network_error_only_retries_connection(self):
        f=fixture('network-retry');self.assertEqual(m.classify(f),'network_error');r=self.make_runner(f);keep,delay=r.step(f)
        self.assertTrue(keep);self.assertEqual(r.calls,['网络重试（非关卡重试）']);self.assertEqual(r.s['attempted'],{})
    def test_network_retry_is_bounded_and_does_not_restart_stage(self):
        f=fixture('network-retry');r=self.make_runner(f);r.s['network_retries']=[time.time()]*3
        keep,delay=r.step(f);self.assertFalse(keep);self.assertTrue(r.calls[0].startswith('STOP: 10分钟内三次网络重连'))
    def test_network_background_never_overrides_refill_veto(self):
        f=fixture('network-retry');rows=[(w['box'],w['text'],w['score']) for w in f.words]
        rows.append(([[600,400],[1100,400],[1100,450],[600,450]],'是否使用道具兑换体力',.999))
        self.assertEqual(m.classify(m.Frame(f.image,rows)),'resource_stop')
    def test_actual_server_timeout_is_network_not_stage_retry(self):
        self.assertEqual(m.classify(fixture('network-timeout')),'network_error')
    def test_actual_uncleared_node(self):
        node,rows=m.selected_node(fixture('uncleared')); self.assertEqual(node['stage'],2)
        self.assertEqual(node['green'],0);self.assertLess(node.get('lock_score',1),.81);self.assertGreater(node['cyan'],.055)
    def test_actual_cleared_node_is_rejected(self):
        node,rows=m.selected_node(fixture('cleared'));self.assertEqual(node['stage'],2);self.assertGreaterEqual(node['green'],14)
    def make_runner(self,f):
        r=m.Runner.__new__(m.Runner);r.frame=f;r.ticket=None;r.last_mode=None;r.mode_since=time.time();r.battle_seen=0;r.last_gesture=0;r.unknown_gestures=0
        r.s={'completed':{},'attempted':{},'active':None,'victories':0};r.cfg={'max_battle_seconds':1800}
        r.save=lambda:None;r.evidence=lambda *a:'offline-test';r.calls=[]
        r.action=lambda kind,*a,**k:r.calls.append(kind)
        r.stop=lambda status,reason:(r.calls.append('STOP: '+reason) or (False,0))
        return r
    def test_selected_completed_never_prepares_battle(self):
        f=fixture('cleared');r=self.make_runner(f);r.step(f)
        self.assertEqual(r.calls,['避开已通关关卡，选择下一关'])
    def test_previous_attempt_blocks_fresh_entry(self):
        f=fixture('uncleared');r=self.make_runner(f);r.s['attempted']['E2-C6-S2']={'cost':8};r.step(f)
        self.assertTrue(r.calls[0].startswith('STOP: 防重复入场'));self.assertEqual(len(r.calls),1)
    def test_lost_entry_result_never_retries(self):
        f=fixture('uncleared');r=self.make_runner(f);r.s['active']={'key':'E2-C6-S2','episode':2,'chapter':6,'stage':2};r.step(f)
        self.assertTrue(r.calls[0].startswith('STOP: 已入场但未确认通关'))
    def test_restart_at_team_requires_return_to_map(self):
        f=fake([('进行任务',1440,828),('队伍战斗力',400,806),('8/774',1264,831)])
        r=self.make_runner(f);r.back=lambda why:r.calls.append('BACK');r.step(f);self.assertEqual(r.calls,['BACK'])
    def test_completion_overrides_preflight_proof_without_error(self):
        f=fixture('victory');r=self.make_runner(f)
        r.s['active']={'key':'E2-C6-S3','proof':'preflight','evidence':'before.png'}
        r.completed('victory result');self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['completed']['E2-C6-S3']['proof'],'victory result')
        self.assertEqual(r.s['victories'],1)
    def test_no_second_entry_with_active_record(self):
        f=fake([('进行任务',1440,828),('队伍战斗力',400,806),('8/774',1264,831)])
        r=self.make_runner(f);r.s['active']={'key':'E2-C6-S2'};r.step(f);self.assertTrue(r.calls[0].startswith('STOP: 已记录一次入场'))
if __name__=='__main__': unittest.main(verbosity=2)
