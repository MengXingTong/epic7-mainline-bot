import unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from arena_core import Reading,count,classify
from arena_journal import ArenaJournal
from abyss_core import Observation,Token
from task_blockers import TaskAttention
from assistant_config import read_json,validate_run

def tok(text,x,y,score=.999):return Token(text,x*1600-10,y*900-8,20,16,score=score)
def team(cost='1/12',opponent='NPC A',score=.999):
    return Observation(1600,900,[tok('新手竞技场',.10,.05),tok('战斗开始',.66,.92),tok('NPC对战',.69,.77),tok(opponent,.70,.71),tok(cost,.58,.92,score)])
class ArenaTests(unittest.TestCase):
    def test_count(self):
        for v in (1,7,9999,'7'):self.assertEqual(count(v),int(v))
        for v in (0,-1,True,False,1.5,'01',' 7',10000,''):
            with self.assertRaises(ValueError):count(v)
    def test_team(self):
        r=classify(team());self.assertEqual((r.scene,r.cost,r.stock,r.opponent),('arena_team',1,12,'NPC A'))
    def test_low_cost_ocr(self):self.assertEqual(classify(team(score=.97)).scene,'arena_unknown')
    def test_cost_invalid(self):
        for cost in ('2/12','1/0'):
            with self.assertRaises(TaskAttention):classify(team(cost))
    def test_modal(self):
        for text in ('确认','取消','点击关闭'):
            o=team();o.tokens.append(tok(text,.5,.5));self.assertEqual(classify(o).scene,'arena_unknown')
    def test_risk(self):
        for text in ('战斗失败','购买挑战书','挑战书不足','复活'):
            o=team();o.tokens.append(tok(text,.5,.5))
            with self.assertRaises(TaskAttention):classify(o)
    def test_no_player_entry(self):
        o=team();o.tokens=[t for t in o.tokens if t.text!='NPC对战'];self.assertEqual(classify(o).scene,'arena_unknown')
    def test_entry_chain(self):
        with tempfile.TemporaryDirectory() as d:
            j=ArenaJournal(d,'r',7);r=classify(team());ev={'captured_at':1,'image_sha256':'a'}
            with self.assertRaises(ValueError):j.intent('entry',r,ev,'window')
            for kind in ('select','challenge'):
                ident=j.intent(kind,r,ev,'window');j.sent(ident,'sent')
            ident=j.intent('entry',r,ev,'window');j.sent(ident,'sent')
            self.assertEqual(len(j.state['attempted']),1);self.assertEqual(j.run['wins'],0)
            with self.assertRaises(ValueError):j.intent('entry',r,ev,'window')
            with self.assertRaises(ValueError):j.complete({'captured_at':3},'window')
            j.battle({'captured_at':2},'window')
            with self.assertRaises(ValueError):j.complete({'captured_at':2},'window')
            with self.assertRaises(ValueError):j.complete({'captured_at':3},'changed')
            j.complete({'captured_at':3},'window');self.assertEqual(j.run['wins'],1)
            with self.assertRaises(ValueError):j.complete({'captured_at':4},'window')
            self.assertEqual(ArenaJournal(d,'r',7).run['wins'],1)
    def test_pending_not_bypassed(self):
        for status in ('sent','unknown','not_sent'):
            with tempfile.TemporaryDirectory() as d:
                j=ArenaJournal(d,'r',7);r=classify(team());ev={'captured_at':1}
                for k in ('select','challenge','entry'):
                    i=j.intent(k,r,ev,'w');j.sent(i,status if k=='entry' else 'sent')
                with self.assertRaises(ValueError):ArenaJournal(d,'new',7)
                self.assertIsNotNone(j.active);self.assertEqual(j.run['wins'],0)
    def test_stop_at_count(self):
        with tempfile.TemporaryDirectory() as d:
            j=ArenaJournal(d,'r',1);r=classify(team());ev={'captured_at':1}
            for k in ('select','challenge','entry'):
                i=j.intent(k,r,ev,'w');j.sent(i,'sent')
            j.battle({'captured_at':2},'w');j.complete({'captured_at':3},'w')
            with self.assertRaises(ValueError):j.intent('entry',r,ev,'w')
    def test_window_chain(self):
        with tempfile.TemporaryDirectory() as d:
            j=ArenaJournal(d,'r',1);r=classify(team());ev={'captured_at':1}
            for k in ('select','challenge'):
                i=j.intent(k,r,ev,'w');j.sent(i,'sent')
            with self.assertRaises(ValueError):j.intent('entry',r,ev,'other')
    def test_quantity_not_mutated(self):
        with tempfile.TemporaryDirectory() as d:
            ArenaJournal(d,'r',7)
            with self.assertRaises(ValueError):ArenaJournal(d,'r',8)

class ArenaWorkerTests(unittest.TestCase):
    def test_two_rounds_close_results_before_new_entry_and_stop(self):
        from unittest.mock import patch
        from PIL import Image
        from assistant_transport import FrameSnapshot
        import arena_worker
        import time
        with tempfile.TemporaryDirectory() as d:
            phase=['npc'];round_no=[1];clicks=[];tick=[time.monotonic()]
            class Control:
                def check(self):pass
                def preview(self,image):pass
                def status(self,*a,**kw):pass
                def sleep(self,n):pass
                def attention(self,exc):raise AssertionError(str(exc))
            class Transport:
                def __init__(self,*a):pass
                def ensure(self):return 'binding'
                def capture(self):
                    tick[0]+=.01
                    return FrameSnapshot(Image.new('RGB',(1600,900)),'binding',tick[0])
                def tap(self,snap,target):
                    clicks.append((phase[0],target.text))
                    if phase[0]=='npc' and target.text=='NPC '+str(round_no[0]):phase[0]='selected'
                    elif phase[0]=='selected' and target.text=='挑战':phase[0]='team'
                    elif phase[0]=='team':phase[0]='battle'
                    elif phase[0]=='battle':phase[0]='result'
                    elif phase[0]=='result':round_no[0]+=1;phase[0]='npc'
                    else:raise AssertionError((phase,target))
            def reading(o):
                name='NPC '+str(round_no[0])
                if phase[0] in ('npc','selected'):return Reading('arena_npc',tok(name,.4,.3),name)
                if phase[0]=='team':return Reading('arena_team',tok('战斗开始',.65,.92),name,12,1)
                if phase[0]=='battle':return Reading('arena_battle',tok('A',.88,.05),name)
                return Reading('arena_result',tok('确认',.9,.92),name)
            def observation(*args):return Observation(1600,900,[tok('挑战',.5,.92)],visuals={'arena_npc_first_selected','arena_challenge_enabled'})
            req={'run_id':'synthetic','settings':{'arena_count':2},'target':{},'run_dir':d}
            with patch('assistant_config.validate_run',return_value=(Path(d),{})),patch('assistant_transport.UnifiedTransport',Transport),patch('arena_worker.read_observation',observation),patch('arena_worker.classify',reading),patch('arena_worker.ObservationCycle'):
                arena_worker.run(req,Control())
            s=read_json(Path(d)/'arena/state.json')
            self.assertEqual(s['runs']['synthetic']['wins'],2)
            self.assertIsNone(s['runs']['synthetic']['pending_result'])
            self.assertIsNone(s['active']);self.assertEqual(len(s['attempted']),2)
            self.assertEqual([x for x in clicks if x[1]=='战斗开始'],[('team','战斗开始')]*2)
            self.assertEqual([x for x in clicks if x[1]=='确认'],[('result','确认')]*2)
            self.assertTrue(all(r.get('close_evidence') for r in s['completed'].values()))

class ArenaRecognitionTests(unittest.TestCase):
    def result(self):
        return Observation(1600,900,[tok('VICTORY',.5,.35),tok('战斗结果',.78,.92),tok('确认',.915,.92),tok('NPC对战的胜负',.50,.64),tok('不会影响积分。',.5,.67),tok('NPC A',.6,.085)])
    def test_complete_result(self):self.assertEqual(classify(self.result()).scene,'arena_result')
    def test_every_result_field_required(self):
        for i in range(6):
            o=self.result();o.tokens.pop(i);self.assertEqual(classify(o).scene,'arena_unknown')
            o=self.result();t=o.tokens[i];o.tokens[i]=Token(t.text,t.x,t.y,t.w,t.h,score=.979);self.assertEqual(classify(o).scene,'arena_unknown')
    def test_result_duplicates_rejected(self):
        for i in range(6):
            o=self.result();o.tokens.append(o.tokens[i]);self.assertEqual(classify(o).scene,'arena_unknown')
    def test_extra_modal_rejected(self):
        for label in ('未知通知','继续','确认','取消'):
            o=self.result();o.tokens.append(tok(label,.5,.5));self.assertEqual(classify(o).scene,'arena_unknown')
    def test_underlying_result_is_not_click_authority(self):
        o=self.result();o.visuals.add('arena_notice_modal');self.assertEqual(classify(o).scene,'arena_unknown')
    def test_single_victory_never_completes(self):
        o=Observation(1600,900,[tok('VICTORY',.5,.35)]);self.assertEqual(classify(o).scene,'arena_unknown')
    def test_battle_auto_requires_known_hud_and_exact_a(self):
        o=Observation(1600,900,[tok('NPC A',.6,.085),tok('A',.88,.05)],visuals={'arena_pause','arena_hp_left','arena_hp_right','arena_auto_white'})
        r=classify(o);self.assertEqual(r.scene,'arena_battle');self.assertEqual(r.target.text,'A')
        o.visuals.add('arena_auto_on');self.assertIsNone(classify(o).target)
        o.visuals.remove('arena_pause');self.assertEqual(classify(o).scene,'arena_unknown')
    def test_n_icon_not_a_second_opponent(self):
        o=team();o.tokens.append(tok('N',.763,.71));self.assertEqual(classify(o).scene,'arena_team')
    def test_weak_npc_name_does_not_reclick_tab(self):
        o=Observation(1600,900,[tok('新手竞技场',.1,.05),tok('NPC交战对手',.30,.16),tok('NPC对战',.87,.3),tok('name',.4,.31,.97)])
        self.assertEqual(classify(o).scene,'arena_unknown')


class ArenaFieldTests(unittest.TestCase):
    def ocr_rows(self,o):
        return [[[ [t.x,t.y],[t.x+t.w,t.y],[t.x+t.w,t.y+t.h],[t.x,t.y+t.h]],t.text,t.score] for t in o.tokens]
    def test_current_cost_dual_read_and_original_retained(self):
        from unittest.mock import Mock
        from PIL import Image
        from arena_worker import read_observation
        for second,score,accepted in [('1/12',.999,True),('1/12',.979,False),('1/11',.999,False)]:
            o=team(score=.91);base=self.ocr_rows(o);box=[[1,1],[10,1],[10,10],[1,10]]
            ocr=Mock(side_effect=[(base,None),([[box,'1/12',.999]],None),([[box,second,score]],None)])
            read=read_observation(Image.new('RGB',(1600,900)),ocr,1)
            self.assertEqual(read.tokens[4].score,.91)
            self.assertEqual(classify(read).scene,'arena_team' if accepted else 'arena_unknown')
    def test_multiline_only_aligned_name_field(self):
        from arena_core import opponent_field
        for x,y,score,ok in [(.311,.33,.999,True),(.35,.33,.999,False),(.311,.40,.999,False),(.311,.33,.979,False)]:
            o=Observation(1600,900,[tok('巴萨尔商团扩张计',.37,.30),tok('划',x,y,score)])
            # Align both left edges rather than centres for a wrapped last glyph.
            f=o.tokens[0];o.tokens[0]=Token(f.text,.305*1600,f.y,.13*1600,f.h,score=f.score)
            result=opponent_field(o,(.30,.28,.49,.35))
            if ok:self.assertEqual(result.text,'巴萨尔商团扩张计划')
            elif y<=.35:self.assertIsNone(result)


class ArenaLedgerTests(unittest.TestCase):
    def test_original_dispatch_hash_cannot_be_replaced(self):
        from assistant_config import atomic_json
        with tempfile.TemporaryDirectory() as d:
            j=ArenaJournal(d,'r',1);r=classify(team());ev={'captured_at':1}
            for k in ('select','challenge','entry'):
                i=j.intent(k,r,ev,'w');j.sent(i,'sent')
            key=j.active['key'];j.state['attempted'][key]['cost']=99;j.save()
            with self.assertRaises(ValueError):ArenaJournal(d,'r',1)
    def test_original_sent_cannot_be_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            j=ArenaJournal(d,'r',1);r=classify(team());ev={'captured_at':1}
            for k in ('select','challenge','entry'):
                i=j.intent(k,r,ev,'w');j.sent(i,'sent')
            j.state['actions'].pop();j.save()
            with self.assertRaises(ValueError):ArenaJournal(d,'r',1)
    def test_auto_intent_not_reusable_even_if_not_sent(self):
        for status in ('sent','not_sent','unknown'):
            with tempfile.TemporaryDirectory() as d:
                j=ArenaJournal(d,'r',1);r=classify(team());ev={'captured_at':1}
                for k in ('select','challenge','entry'):
                    i=j.intent(k,r,ev,'w');j.sent(i,'sent')
                j.battle({'captured_at':2},'w');b=Reading('arena_battle',tok('A',.88,.05),r.opponent)
                i=j.intent('auto',b,{'captured_at':3},'w');j.sent(i,status)
                with self.assertRaises(ValueError):j.intent('auto',b,{'captured_at':4},'w')
    def test_second_off_panel_confirm_rejected(self):
        o=ArenaRecognitionTests().result();o.tokens.append(tok('确认',.9,.2));self.assertEqual(classify(o).scene,'arena_unknown')

if __name__=='__main__':unittest.main()
