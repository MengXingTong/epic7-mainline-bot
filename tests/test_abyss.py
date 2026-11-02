"""Pure Abyss regressions. Private fixtures are opt-in and never distributed."""
import json,time,os,unittest
from pathlib import Path
from PIL import Image
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_blockers import TaskAttention
from abyss_core import Token,Observation,Scene,Session,Reading,PauseRequired,classify
from abyss_templates import TemplateBank
ROOT=Path(__file__).resolve().parents[1]
FIXTURES=Path(os.environ.get('EPIC7_ABYSS_FIXTURES',str(ROOT/'tests/fixtures/abyss')))
BANK=TemplateBank(ROOT/'.local/assistant/abyss-assets')
def frame(name):
    path=FIXTURES/(name+'-ocr.json')
    if not path.is_file():raise unittest.SkipTest('Private Abyss game fixture not distributed')
    data=json.loads(path.read_text(encoding='utf-8'))
    with Image.open(FIXTURES/(name+'.png')) as image:image=image.convert('RGB')
    tokens=data['tokens'] if isinstance(data,dict) else data
    result=Observation(*image.size,[Token(**t) for t in tokens]);BANK.apply(image,result);return result

class RealFrameTests(unittest.TestCase):
    def test_real_lobby(self):self.assertEqual(classify(frame('lobby')).scene,Scene.LOBBY)
    def test_real_menu_offscreen_abyss(self):
        o=frame('battle-menu-initial');r=classify(o)
        self.assertEqual(r.scene,Scene.BATTLE_MENU)
        self.assertEqual(Session().plan(r,o).kind,'swipe')
    def test_real_menu_visible_abyss(self):
        o=frame('battle-menu-abyss-visible');r=classify(o)
        self.assertEqual(r.scene,Scene.BATTLE_MENU)
        self.assertEqual(Session().plan(r,o).token.text,'深渊')
    def test_real_upper_gate_only(self):
        o=frame('abyss-gate-052');r=classify(o);a=Session().plan(r,o)
        self.assertEqual(r.scene,Scene.ABYSS_GATE);self.assertEqual(r.floor,52)
        self.assertTrue(a.ordinary_gate)
        x,y=a.token.center
        self.assertTrue(.80*o.width<=x<=.99*o.width and .20*o.height<=y<=.53*o.height)
    def test_real_selected_and_available_floor(self):
        o=frame('normal-select-052');r=classify(o)
        self.assertEqual((r.scene,r.floor,r.available_floor),(Scene.NORMAL,52,52))
        self.assertEqual(Session().plan(r,o).kind,'choose_team')
    def test_real_team(self):
        o=frame('team-052');r=classify(o)
        self.assertEqual(r.scene,Scene.TEAM)
        s=Session(normal_verified=True,entered_floor=52,expected_floor=52,phase='team_opening')
        self.assertEqual(s.plan(r,o).kind,'start_battle')
    def test_real_hud_needs_context(self):
        o=frame('battle-052')
        self.assertEqual(classify(o,True).scene,Scene.BATTLE)
        self.assertEqual(classify(o,False).scene,Scene.UNKNOWN)
    def test_held_out_clear_052(self):
        r=classify(frame('clear-052'));self.assertEqual((r.scene,r.floor),(Scene.CLEAR,52))
    def test_existing_clear_is_a_baseline_not_a_win(self):
        o=frame('clear-051');s=Session();a=s.plan(classify(o),o)
        self.assertEqual(s.wins,0);self.assertEqual(s.baseline_floor,51)
        self.assertEqual((a.kind,a.target_floor),('advance',52))
    def test_unrelated_team_never_starts(self):
        o=frame('team-052')
        with self.assertRaises(PauseRequired):Session().plan(classify(o),o)
    def test_full_chain_continues_after_first_clear(self):
        s=Session();o=frame('clear-051');s.applied(s.plan(classify(o),o))
        self.assertEqual(s.expected_floor,52)
        o=frame('team-052');s.applied(s.plan(classify(o),o))
        o=frame('battle-052');self.assertIsNone(s.plan(classify(o,True),o))
        o=frame('clear-052')
        next_action=s.plan(classify(o),o)
        self.assertEqual((next_action.kind,next_action.target_floor),('advance',53))
        self.assertEqual(s.wins,1);self.assertEqual(s.last_won_floor,52)
        self.assertIsNone(s.expected_floor)
    def test_stale_clear_cannot_double_enter(self):
        s=Session();o=frame('clear-051');s.applied(s.plan(classify(o),o))
        self.assertIsNone(s.plan(classify(o),o));self.assertEqual(s.wins,0)
        s.transition_until=time.monotonic()-1
        with self.assertRaises(PauseRequired):s.plan(classify(o),o)
    def test_repeated_clear_does_not_double_count(self):
        s=Session(normal_verified=True,entered_floor=52,expected_floor=52,phase='battle')
        o=frame('clear-052');s.plan(classify(o),o);s.plan(classify(o),o)
        self.assertEqual(s.wins,1)
    def test_unexpected_clear_floor_pauses(self):
        s=Session(normal_verified=True,entered_floor=53,expected_floor=53,phase='battle')
        o=frame('clear-052')
        with self.assertRaises(PauseRequired):s.plan(classify(o),o)
    def test_returning_to_lobby_during_battle_pauses(self):
        s=Session(normal_verified=True,entered_floor=52,expected_floor=52,phase='battle')
        o=frame('lobby')
        with self.assertRaises(PauseRequired):s.plan(classify(o),o)
    def test_wrong_team_floor_pauses(self):
        s=Session(normal_verified=True,entered_floor=53,expected_floor=53,phase='next_opening')
        o=frame('team-052')
        with self.assertRaises(PauseRequired):s.plan(classify(o),o)
    def test_uncertain_available_floor_pauses(self):
        o=frame('normal-select-052');r=Reading(Scene.NORMAL,(),52,None)
        with self.assertRaises(PauseRequired):Session().plan(r,o)
    def test_hard_header_pauses_even_with_proof(self):
        o=Observation(1200,700,[Token('挑战模式',10,100,120,30)])
        s=Session(normal_verified=True,entered_floor=52,expected_floor=52)
        with self.assertRaises(PauseRequired):s.plan(classify(o),o)
    def test_missing_upper_gate_is_not_guessed(self):
        o=frame('abyss-gate-052');o.tokens=[t for t in o.tokens if not(o.in_region(t,(.80,.20,.99,.53)))]
        self.assertIsNone(o.ordinary_entrance())
        self.assertEqual(classify(o).scene,Scene.HARD)
    def test_upper_card_challenge_label_rejected(self):
        o=frame('abyss-gate-052');o.tokens.append(Token('挑战模式',950,220,100,25))
        self.assertIsNone(o.ordinary_entrance())
    def test_negative_available_substring_rejected(self):
        o=Observation(1200,700,[Token('第52层',720,260,90,25),
            Token('不可进行',710,300,120,25),Token('可进行',740,300,90,25)])
        self.assertIsNone(o.available_floor())
    def test_confirmation_popup_pauses(self):
        o=frame('team-052');o.tokens.append(Token('确认',500,350,80,25))
        with self.assertRaises(TaskAttention):Session().plan(classify(o),o)
    def test_defeat_never_retries(self):
        o=Observation(1200,700,[Token('战斗失败',400,250,160,40)])
        with self.assertRaises(PauseRequired):Session().plan(classify(o),o)
    def test_resource_popup_never_purchases(self):
        o=Observation(1200,700,[Token('购买体力',400,250,160,40)])
        with self.assertRaises(TaskAttention):Session().plan(classify(o),o)
    def test_unknown_has_no_action(self):
        o=Observation(1200,700,[]);self.assertIsNone(Session().plan(classify(o),o))
