"""Passive mission rows are a verified panel, not stage-specific setup commands."""
import copy,json,os,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import runner
from story_core import team_entry_control
from test_map_layout import frame
import test_team_preparation as team
from test_team_preparation import prepared_runner,step


def preparation(rows=('一次性完成','配置1名寒气属性英雄到队伍中'),hosted=True):
    f=team.TeamPreparationTests().episode_party()
    f.words[5]['text'],f.words[6]['text']=rows
    f.words=[w for w in f.words if w['text']!='辅助英雄无法参与']
    if hosted:f.words+=frame([('托管战斗',820,727)]).words
    f.text='\n'.join(w['text'] for w in f.words);f.clean=runner.norm(f.text)
    return f


class EpisodeMissionPanelTests(unittest.TestCase):
    def test_achievement_wording_does_not_authorize_setup_or_gate_single_entry(self):
        for rows in [('一次性完成','配置1名寒气属性英雄到队伍中'),
                     ('一次性完成','配置1名自然属性英雄到队伍中'),
                     ('完成故事','2名以上英雄存活'),
                     ('配置1名黑暗属性英雄到队伍中','配置1名魔导士职业英雄到队伍中'),
                     ('未使用魂力燃烧技能','3名以上英雄存活')]:
            f=preparation(rows);control=team_entry_control(f)
            self.assertEqual(control['kind'],'single_task',rows)
            self.assertEqual(control['target']['text'],'进行任务')
            r=prepared_runner(f);step(r)
            self.assertEqual(r.action.call_count,1);self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
            self.assertEqual(r.s['completed'],{});self.assertNotIn('team_config',r.s)

    def test_zero_one_or_two_verified_nonstarting_hosted_controls_are_not_targets(self):
        for mode in ('none','bottom','both'):
            f=preparation(hosted=mode!='none')
            if mode=='both':f.words+=frame([('托管战斗',1460,115)]).words
            self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_weak_displaced_duplicate_top_only_or_hosted_panel_still_rejected(self):
        for change in ('weak','displaced','duplicate','top_only','unknown_label','repeat','confirm'):
            f=preparation();w=f.words[-1]
            if change=='weak':w['score']=.979
            elif change=='displaced':w['x']=700
            elif change=='duplicate':f.words.append(copy.deepcopy(w))
            elif change=='top_only':w.update(x=1460,y=115)
            elif change=='unknown_label':w['text']='托管战斗设置'
            elif change=='repeat':f.words+=frame([('重复战斗',800,400)]).words
            else:f.words+=frame([('确认',935,575)]).words
            self.assertEqual(team_entry_control(f)['kind'],'unknown',change)

    def test_each_passive_row_is_unique_in_position_and_confident(self):
        for index in (5,6):
            for change in ('missing','weak','duplicate','displaced'):
                f=preparation();w=f.words[index]
                if change=='missing':f.words.remove(w)
                elif change=='weak':w['score']=.949
                elif change=='duplicate':f.words.append(copy.deepcopy(w))
                else:w['x']=800;w['y']=450
                self.assertEqual(team_entry_control(f)['kind'],'unknown',(index,change))

    def test_each_real_diamond_required_not_bright_rectangle_or_other_colour(self):
        for change in ('absent','one_missing','rectangle','green','dim'):
            f=preparation()
            if change=='absent':f.image[210:330,1160:1210]=22
            elif change=='one_missing':f.image[282:322,1160:1210]=22
            elif change=='rectangle':f.image[210:330,1160:1210]=(50,180,230)
            elif change=='green':f.image[210:330,1160:1210]=(0,220,0)
            else:f.image[210:330,1160:1210]//=4
            self.assertEqual(team_entry_control(f)['kind'],'unknown',change)

    def test_ocr_baseline_offset_uses_current_shape_not_relaxed_taper_threshold(self):
        for margin in (-9,-4,0,5):
            for offset in range(-2,6):
                f=preparation();tile=f.image[205:330,1150:1220].copy()
                f.image[205:330,1150:1220]=22
                f.image[205:330,1150+margin:1220+margin]=tile
                for w in f.words:
                    if 200<w['y']<330 and w['x']>1180:w['y']+=offset
                self.assertEqual(team_entry_control(f)['kind'],'single_task',(margin,offset))
        f=preparation();f.image[210:330,1160:1210]=(50,180,230)
        self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_incomplete_episode_never_borrows_legacy_two_hosted_layout(self):
        f=preparation();f.words+=frame([('托管战斗',1460,115)]).words
        f.words=[w for w in f.words if w['text']!='登场的敌人']
        self.assertEqual(team_entry_control(f)['kind'],'unknown')
        r=prepared_runner(f);step(r);r.action.assert_not_called()

    def test_optional_auto_missing_weak_moved_or_on_never_changes_entry(self):
        for mode in ('missing','weak','moved','on'):
            f=preparation()
            if mode!='missing':
                f.words+=frame([('AUTO',990,680)]).words
                if mode=='weak':f.words[-1]['score']=.60
                elif mode=='moved':f.words[-1]['y']=619
                else:f.image[650:710,900:1095]=(0,200,0)
            self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_current_task_descriptions_do_not_request_configuration_or_free_tutorial(self):
        f=preparation();r=prepared_runner(f);step(r)
        self.assertNotIn('team_config',r.s)
        self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
        for text in ('跳过教学','确认'):
            f=preparation();f.words+=frame([(text,1452 if text=='跳过教学' else 935,42 if text=='跳过教学' else 575)]).words
            self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_weak_party_label_has_one_original_field_read_preserving_raw_ocr_and_time(self):
        from tutorial_ocr import strengthen_preparation_party_labels
        f=preparation();f.words[1]['score']=.975;before=copy.deepcopy(f.words[1]);at=f.at
        ocr=Mock(return_value=([['Episode1队',.999]],None))
        strengthen_preparation_party_labels(f,ocr);strengthen_preparation_party_labels(f,ocr)
        ocr.assert_called_once();self.assertEqual(ocr.call_args.kwargs,dict(use_det=False,use_cls=False))
        self.assertEqual(f.words[1]['original_ocr'],before);self.assertEqual(f.at,at)
        self.assertEqual(f.words[1]['score'],.999);self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_party_label_changed_weak_ambiguous_or_failed_read_never_authorizes(self):
        from tutorial_ocr import strengthen_preparation_party_labels
        for rows in ([['Episode2队',.999]],[['Episode1队',.979]],[['Episode1队',.999],['Episode1队',.999]],[]):
            f=preparation();f.words[1]['score']=.975;before=copy.deepcopy(f.words)
            ocr=Mock(return_value=(rows,None))
            strengthen_preparation_party_labels(f,ocr);strengthen_preparation_party_labels(f,ocr)
            ocr.assert_called_once();self.assertEqual(f.words,before)
            self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_complete_or_partial_or_duplicate_party_label_context_is_not_reread(self):
        from tutorial_ocr import strengthen_preparation_party_labels
        for mode in ('complete','partial','duplicate','shifted'):
            f=preparation()
            if mode!='complete':f.words[1]['score']=.975
            if mode=='partial':f.words=[w for w in f.words if w['text']!='登场的敌人']
            elif mode=='duplicate':f.words.append(copy.deepcopy(f.words[1]))
            elif mode=='shifted':f.words[1]['y']=500
            ocr=Mock();strengthen_preparation_party_labels(f,ocr);ocr.assert_not_called()

    def test_weak_known_party_label_observes_new_frame_without_manual_attention(self):
        f=preparation();f.words[1]['score']=.975
        r=prepared_runner(f);before=copy.deepcopy(r.ticket)
        self.assertTrue(step(r)[0]);r.action.assert_not_called()
        self.assertNotIn('attention',r.s);self.assertFalse(r.s.get('terminal'))
        self.assertEqual(r.ticket,before);self.assertNotIn('E1-C1-S2',r.s['attempted'])
        f.words[1]['score']=.999;step(r)
        self.assertEqual(r.action.call_count,1);self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
        self.assertEqual(len(r.s['entry_dispatches']['E1-C1-S2']),1)

    def test_reservation_and_disk_failure_still_protect_real_resource_entry(self):
        r=prepared_runner(preparation());r.save.side_effect=OSError('disk full')
        with self.assertRaises(OSError):step(r)
        r.action.assert_not_called()
        r=prepared_runner(preparation());step(r);old=copy.deepcopy(r.s['attempted'])
        r.action.reset_mock();step(r);r.action.assert_not_called();self.assertEqual(r.s['attempted'],old)

    def test_current_private_frame_only_reader_replay_and_fake_dispatch(self):
        folder=Path(os.environ.get('EPIC7_EPISODE_MISSION_FIXTURES',str(Path(__file__).resolve().parents[1]/'.local/current-team-stall-20261108')))
        if not (folder/'current.png').is_file():self.skipTest('Private current frame not distributed')
        for image,ocr in (('current.png','current-ocr.json'),('after-map.png','after-map-ocr.json')):
            if not (folder/image).exists():continue
            data=json.loads((folder/ocr).read_text('utf8'))
            f=runner.Frame(runner.cv2.imread(str(folder/image)),[(w['box'],w['text'],w['score']) for w in data['words']])
            control=team_entry_control(f)
            weak_label=any(w['text'] in ('Episode1队','Episode2队','Episode3队') and w['score']<.98 for w in f.words)
            self.assertEqual(control['kind'],'unknown' if weak_label else 'single_task',image)
            r=prepared_runner(f);r.ticket['name']='约定的地点';step(r)
            if weak_label:
                r.action.assert_not_called();self.assertNotIn('attention',r.s)
            else:
                self.assertEqual(r.action.call_count,1);self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
                self.assertEqual(r.s['active']['cost'],8)
            self.assertEqual(r.s['completed'],{})


if __name__=='__main__':unittest.main()
