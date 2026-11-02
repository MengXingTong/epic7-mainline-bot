"""Planner for the actual Epic Seven PC normal-Abyss flow; no memory/network access."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import re, time, unicodedata
from task_blockers import capacity_blocker,TaskAttention
from task_overlays import rankup_splash,account_upgrade_notice_close


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


@dataclass(frozen=True)
class Token:
    text: str
    x: float
    y: float
    w: float
    h: float
    source: str = "ocr"
    score: float | None = None
    @property
    def center(self): return self.x+self.w/2, self.y+self.h/2


@dataclass
class Observation:
    width: int
    height: int
    tokens: list[Token]
    captured_at: float = field(default_factory=time.monotonic)
    visuals: set[str] = field(default_factory=set)

    def in_region(self, token, region):
        x,y=token.center
        return region[0]*self.width <= x <= region[2]*self.width and region[1]*self.height <= y <= region[3]*self.height

    def find(self, *labels, region=None):
        wanted={normalize(label) for label in labels}
        found=[t for t in self.tokens if normalize(t.text) in wanted
               and (region is None or self.in_region(t,region))
               and t.w < self.width*.55 and t.h < self.height*.18]
        return min(found,key=lambda t:t.w*t.h,default=None)

    def has(self,*labels): return self.find(*labels) is not None
    def contains(self,*labels):
        return any(normalize(label) in normalize(t.text) for t in self.tokens for label in labels)

    def floor_tokens(self,region=None):
        result=[]
        for t in self.tokens:
            match=re.fullmatch(r"(?:深渊)?(?:第)?(\d{1,3})(?:层|f)",normalize(t.text))
            if match and 0<int(match.group(1))<1000 and (region is None or self.in_region(t,region)):
                result.append((int(match.group(1)),t))
        return result

    def selected_floor(self,region=None):
        values={n for n,t in self.floor_tokens(region)}
        return next(iter(values)) if len(values)==1 else None

    def floor_token(self,number,region=None):
        return min((t for n,t in self.floor_tokens(region) if n==number),key=lambda t:t.w*t.h,default=None)

    def available_floor(self):
        positive=[]
        for t in self.tokens:
            if normalize(t.text)!="可进行" or not self.in_region(t,(.56,.08,.78,.98)): continue
            cx,cy=t.center
            if any("不可进行" in normalize(other.text) and other.x<=cx<=other.x+other.w
                   and other.y<=cy<=other.y+other.h for other in self.tokens): continue
            nearby=[(n,ft) for n,ft in self.floor_tokens((.56,.08,.78,.98))
                    if 0 < cy-ft.center[1] < self.height*.085 and abs(cx-ft.center[0]) < self.width*.14]
            if nearby:
                positive.append(min(nearby,key=lambda item:cy-item[1].center[1])[0])
        values=set(positive)
        return next(iter(values)) if len(values)==1 else None

    def ordinary_entrance(self):
        # The verified client has two cards on the RIGHT. Only the upper card is eligible.
        region=(.80,.20,.99,.53)
        if any(self.in_region(t,region) and any(normalize(label) in normalize(t.text) for label in HARD_LABELS) for t in self.tokens):return None
        floor=self.selected_floor(region)
        if floor is None: return None
        token=self.floor_token(floor,region)
        if self.find("进行状况",region=(.78,.05,.99,.22)) is None: return None
        if self.find("挑战模式", "挑战深渊", "深渊挑战",region=(.78,.58,.99,.82)) is None: return None
        if self.find("深渊",region=(0,.14,.24,.34)) is None: return None
        return token


class Scene(str,Enum):
    LOBBY="大厅"
    BATTLE_MENU="战斗模式列表"
    ABYSS_GATE="深渊入口选择"
    NORMAL="普通深渊选层"
    TEAM="准备战斗"
    BATTLE="原生自动战斗"
    CLEAR="普通深渊通关"
    VICTORY="胜利过场"
    RESULT="结算过场"
    DEFEAT="战斗失败"
    HARD="挑战模式（禁止）"
    ACCOUNT_UPGRADE="账号升级行动力上限提示"
    RANKUP="Rank升级提示"
    CAPACITY="容量不足（等待处理）"
    BLOCKED="需要人工处理"
    UNKNOWN="加载或尚未确认界面"


@dataclass(frozen=True)
class Reading:
    scene: Scene
    evidence: tuple[str,...]=()
    floor: int | None=None
    available_floor: int | None=None


HARD_LABELS=("挑战模式","挑战深渊","深渊挑战","高难度深渊")
BLOCKED_PHRASES=("体力不足","购买体力","购买入场券","入场券不足","票券不足","挑战次数不足",
                 "没有足够的","获取更多体力","使用天空石","天空石不足","是否复活","复活英雄",
                 "连接失败","网络连接中断","错误代码","服务器维护","重新连接")


def _account_upgrade_target(o):
    words=[dict(text=t.text,x=t.center[0],y=t.center[1],score=t.score if t.score is not None else 1.0,token=t) for t in o.tokens]
    target=account_upgrade_notice_close(words,o.width,o.height)
    return target['token'] if target else None

def classify(o,normal_verified=False):
    blocker=capacity_blocker(t.text for t in o.tokens)
    if blocker:return Reading(Scene.CAPACITY,(blocker.title,blocker.reason))
    if _account_upgrade_target(o) and not o.contains(*BLOCKED_PHRASES):return Reading(Scene.ACCOUNT_UPGRADE,('升级','账号升等、行动力上限已提升','点击关闭'))
    if rankup_splash([dict(text=t.text,x=t.center[0],y=t.center[1]) for t in o.tokens],o.width,o.height) and not o.contains(*BLOCKED_PHRASES):return Reading(Scene.RANKUP,('RANK UP','免费Rank提升与已恢复行动力','继续旅程'))
    if o.contains(*BLOCKED_PHRASES) or o.has("确认","确定","取消","购买","复活"):
        return Reading(Scene.BLOCKED,("资源/付费/确认弹窗",))
    if o.has("战斗失败","挑战失败","defeat","失败","重新挑战"):
        return Reading(Scene.DEFEAT,("失败或重试提示",))
    # Menu cards include a challenge-summary label; it does NOT make the menu a hard-mode page.
    if o.has("一般") and o.has("活动") and o.has("赛季","赛事") and o.find("战斗",region=(0,0,.2,.13)):
        return Reading(Scene.BATTLE_MENU,("战斗标题","一般/赛季/活动页签"))
    gate=o.ordinary_entrance()
    if gate:
        return Reading(Scene.ABYSS_GATE,("右侧上方普通卡片","下方挑战卡片","进行状况"),
                       o.selected_floor((.80,.20,.99,.53)))
    if o.contains(*HARD_LABELS): return Reading(Scene.HARD,("挑战模式文字",))
    floor=o.selected_floor((.30,.50,.70,.78))
    if floor and o.find("深渊",region=(.35,.48,.66,.66)) and o.find("下一层",region=(.78,.84,.99,.99)) and o.find("返回",region=(0,.84,.23,.99)):
        return Reading(Scene.CLEAR,("普通深渊标题","当前通关层数","下一层","返回"),floor)
    if o.find("深渊",region=(0,.14,.24,.34)) and o.find("选择队伍",region=(.78,.83,.99,.99)):
        return Reading(Scene.NORMAL,("普通深渊标题","选择队伍","右侧层数"),
                       o.selected_floor((.78,.18,.99,.48)),o.available_floor())
    if o.has("准备战斗") and o.find("深渊",region=(.70,.04,.99,.22)) and o.find("战斗开始",region=(.76,.83,.99,.99)):
        return Reading(Scene.TEAM,("准备战斗","深渊","战斗开始"),o.selected_floor((.70,.08,.99,.25)))
    if o.find("战斗",region=(.86,.34,.99,.57)) and o.find("召唤",region=(.86,.53,.99,.76)) and o.find("商店",region=(.86,.65,.99,.87)):
        return Reading(Scene.LOBBY,("右侧战斗/召唤/商店导航",))
    if normal_verified and ("battle-pause" in o.visuals or o.has("战斗暂停按钮")):
        return Reading(Scene.BATTLE,("战斗HUD","普通深渊上下文"))
    if o.has("victory","战斗胜利"): return Reading(Scene.VICTORY,("胜利过场",))
    return Reading(Scene.UNKNOWN)


@dataclass(frozen=True)
class Action:
    name: str
    token: Token | None
    key: str
    scene: Scene
    ordinary_gate: bool=False
    kind: str="click"
    target_floor: int | None=None


class PauseRequired(RuntimeError): pass


@dataclass
class Session:
    normal_verified: bool=False
    entered_floor: int | None=None
    last_won_floor: int | None=None
    baseline_floor: int | None=None
    expected_floor: int | None=None
    wins: int=0
    phase: str="idle"
    last_action_key: str=""
    action_repeats: int=0
    battle_started_at: float | None=None
    transition_until: float=0

    def plan(self,reading,o):
        scene=reading.scene
        if scene==Scene.ACCOUNT_UPGRADE:
            return self._action("关闭免费账号升级行动力上限提示",_account_upgrade_target(o),"account-upgrade-close",scene)
        if scene==Scene.RANKUP:
            return self._action("关闭免费Rank升级提示",Token("继续",o.width*.49,o.height*.96,o.width*.02,o.height*.02),"rankup-continue",scene)
        if scene in (Scene.CAPACITY,Scene.BLOCKED):
            raise TaskAttention("capacity" if scene==Scene.CAPACITY else "dialog",reading.evidence[0] if reading.evidence else "等待处理","请手动处理当前提示后点“处理后继续”；不会自动确认、购买或重新入场。")
        if scene in (Scene.HARD,Scene.DEFEAT):
            self.normal_verified=False
            reason={Scene.HARD:"检测到挑战模式，禁止操作下方高难入口。",Scene.DEFEAT:"战斗失败，已停止，不复活、不重试。",
                    Scene.BLOCKED:"资源、购买或网络提示需要你处理；不会自动确认。"}[scene]
            raise PauseRequired(reason)
        if self.expected_floor is not None and self.phase in ("battle_opening","battle") and scene in (
                Scene.LOBBY,Scene.BATTLE_MENU,Scene.ABYSS_GATE,Scene.NORMAL):
            raise PauseRequired("战斗流程已被手动切换，已停止，不自动重新入场。")
        if scene==Scene.CLEAR:
            self.accept_clear(reading.floor)
            if self.expected_floor is not None:
                if time.monotonic()<self.transition_until: return None
                raise PauseRequired("下一层没有出现预期变化，未重复消耗体力。")
            return self._action("进入下一层准备页",o.find("下一层",region=(.78,.84,.99,.99)),
                                f"clear-next:{reading.floor}",scene,kind="advance",target_floor=reading.floor+1)
        if scene==Scene.LOBBY:
            if self.expected_floor is not None: raise PauseRequired("已离开预期深渊流程，请重新开始。")
            return self._action("打开大厅战斗",o.find("战斗",region=(.86,.34,.99,.57)),"lobby-battle",scene)
        if scene==Scene.BATTLE_MENU:
            if self.expected_floor is not None: raise PauseRequired("已离开预期深渊流程，请重新开始。")
            token=o.find("深渊",region=(0,.22,1,.39))
            if token: return self._action("打开深渊卡片",token,"menu-abyss",scene)
            return Action("向右查找深渊模式",None,"menu-swipe-left",scene,kind="swipe")
        if scene==Scene.ABYSS_GATE:
            if self.expected_floor is not None: raise PauseRequired("层数上下文已改变，请重新开始。")
            return self._action("只进入上方普通深渊",o.ordinary_entrance(),"gate-normal",scene,ordinary_gate=True)
        if scene==Scene.NORMAL:
            if self.phase=="team_opening":
                if time.monotonic()<self.transition_until:return None
                raise PauseRequired("选择队伍后界面未变化，已停止重试。")
            if reading.floor is None or reading.available_floor is None:
                raise PauseRequired("未唯一确认当前层数与可进行层数，已阻止重刷或误入锁定层。")
            if self.last_won_floor is not None and reading.available_floor<=self.last_won_floor:
                raise PauseRequired("下一层尚未解锁，已阻止重复刷上一层。")
            self.normal_verified=True
            if reading.floor!=reading.available_floor:
                token=o.floor_token(reading.available_floor,(.56,.08,.78,.98))
                return self._action("选择可进行层",token,f"select:{reading.available_floor}",scene)
            self.entered_floor=reading.floor
            self.expected_floor=reading.floor
            return self._action("沿用当前队伍",o.find("选择队伍",region=(.78,.83,.99,.99)),
                                f"choose-team:{reading.floor}",scene,kind="choose_team",target_floor=reading.floor)
        if scene==Scene.TEAM:
            self.require_normal()
            if reading.floor and reading.floor!=self.expected_floor:
                raise PauseRequired("队伍页层数与预期不一致，已停止开战。")
            if self.phase=="battle_opening":
                if time.monotonic()<self.transition_until:return None
                raise PauseRequired("开战后界面未变化，已停止重复入场。")
            return self._action("普通深渊开战",o.find("战斗开始",region=(.76,.83,.99,.99)),
                                f"start:{self.expected_floor}",scene,kind="start_battle",target_floor=self.expected_floor)
        if scene==Scene.BATTLE:
            self.require_normal()
            self.phase="battle"
            return None
        return None  # Unknown/transient pages never receive clicks.

    def accept_clear(self,floor):
        if floor is None: raise PauseRequired("未识别通关层数。")
        if self.expected_floor is None:
            if self.last_won_floor is None:
                self.baseline_floor=floor
                self.last_won_floor=floor
                self.entered_floor=floor
                self.normal_verified=True
                self.phase="clear"
            elif floor!=self.last_won_floor:
                raise PauseRequired("通关层数意外改变，已暂停。")
            return
        if floor==self.last_won_floor and self.phase=="next_opening": return
        if floor!=self.expected_floor:
            raise PauseRequired("通关层数与预期不一致，不继续消费体力。")
        if self.phase not in ("battle_opening","battle"):
            raise PauseRequired("尚未确认开战，不将当前画面计为本次通关。")
        self.wins+=1
        self.last_won_floor=floor
        self.entered_floor=floor
        self.expected_floor=None
        self.phase="clear"
        self.normal_verified=True
        self.battle_started_at=None

    def applied(self,action):
        if action.key==self.last_action_key:self.action_repeats+=1
        else:self.last_action_key,self.action_repeats=action.key,1
        if self.action_repeats>2:raise PauseRequired("同一步骤未变化，已停止重复操作。")
        if action.kind=="advance":
            self.expected_floor=action.target_floor
            self.entered_floor=action.target_floor
            self.phase="next_opening"
            self.transition_until=time.monotonic()+15
        elif action.kind=="choose_team":
            self.phase="team_opening"
            self.transition_until=time.monotonic()+15
        elif action.kind=="start_battle":
            self.phase="battle_opening"
            self.battle_started_at=time.monotonic()
            self.transition_until=time.monotonic()+20

    def require_normal(self):
        if not self.normal_verified or self.expected_floor is None:
            raise PauseRequired("缺少普通深渊的层数与进入证据，禁止操作当前战斗。")

    @staticmethod
    def _action(name,token,key,scene,ordinary_gate=False,kind="click",target_floor=None):
        if token is None:raise PauseRequired("按钮没有可靠识别，不猜测点击坐标。")
        return Action(name,token,key,scene,ordinary_gate,kind,target_floor)
