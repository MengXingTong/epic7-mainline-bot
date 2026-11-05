"""Positive-recognition planner for experimental Dimensional Exploration.

Score summaries are not completion evidence. Unseen routes, combat, recruitment
and choices deliberately pause until their own evidence-backed handlers exist.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re
from abyss_core import Observation, Token, normalize
from task_blockers import TaskAttention, capacity_blocker

RISK_WORDS = ('购买','兑换','天空石','复活','重新挑战','再次挑战','重试','放弃','重置',
              '消耗','不足','付费','连接失败','网络连接中断','重新连接',
              '購買','兌換','復活','確認','確定','是否使用')

@dataclass(frozen=True)
class Reading:
    scene: str
    target: Token | None = None
    stage: str | None = None
    detail: str = ''
    key: str = ''
    hero: str = ''
    cost: int | None = None
    budget: tuple[int,int] | None = None
    recruits: tuple[tuple[str,str],...] = ()
    route: tuple[str,...] = ()
    event: str = ''
    combat_bounds: tuple[int,int] | None = None

@dataclass(frozen=True)
class Action:
    name: str
    token: Token | None
    kind: str = 'navigate'
    stage: str | None = None


def classify(o: Observation, context=None) -> Reading:
    # Never let a recognized page under a resource/modal overlay authorize input.
    blocker = capacity_blocker(t.text for t in o.tokens)
    if blocker:return Reading('attention', detail=blocker.title+'；'+blocker.reason)
    p=Observation(o.width,o.height,[t for t in o.tokens if t.score is not None and t.score>=.8],o.captured_at,o.visuals)
    active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(active.get('current_node'),{})
    if (node.get('kind')=='rest' and node.get('rest_leave_intent') and not o.contains(*RISK_WORDS)
            and p.has('有尚未选择的奖励。') and p.has('未选择的奖励无法再次获得。')
            and p.find('取消',region=(.33,.59,.47,.69)) and p.find('确认',region=(.5,.59,.65,.69))):
        return Reading('dimension_rest_skip_confirm',p.find('确认',region=(.5,.59,.65,.69)),key=active['current_node'],detail='仅确认跳过尚未选择的休整奖励；不丢弃已有道具，不花费、不复活。')
    # Rest services contain a static revival description. This exception grants
    # only the observed Leave button; never a service, purchase or revive click.
    rest_active=((context or {}).get('active') or {})
    rest_node=rest_active.get('nodes',{}).get(rest_active.get('current_node'),{})
    risky=[t.text for t in o.tokens if any(word in t.text for word in RISK_WORDS)]
    if (rest_node.get('kind')=='rest' and p.find('彗星神殿：外围区域',region=(0,0,.35,.1))
            and p.has('进行英雄升阶。') and p.has('使死亡的英雄复活。') and p.has('恢复生命体征。')
            and p.has('英雄生命值恢复50%。') and p.find('离开',region=(.72,.84,.99,.99))
            and risky and all(t=='使死亡的英雄复活。' for t in risky)
            and not o.contains('确认','确定','取消','是否')):
        return Reading('dimension_rest_leave',p.find('离开',region=(.72,.84,.99,.99)),key=rest_active['current_node'],detail='只离开休整，不操作任何升阶、复活或恢复服务。')
    if o.contains(*RISK_WORDS):
        return Reading('attention', detail='资源、付费、复活、重试或网络提示，需手动处理。')
    if p.has('战斗失败','挑战失败','DEFEAT','失败'):
        return Reading('defeat', detail='失败后不自动重试。')
    if o.contains('确认','确定','取消','是否'):
        return Reading('attention', detail='尚未验证的确认弹窗，不点击。')
    # Low-confidence text still participates in blockers above, never in targets.
    o=Observation(o.width,o.height,[t for t in o.tokens if t.score is not None and t.score>=.8],o.captured_at,o.visuals)
    battle_active=(context or {}).get('active') or {};battle_node=battle_active.get('nodes',{}).get(battle_active.get('current_node'),{})
    if (battle_node.get('battle_start_intent') and battle_node.get('status')!='completed' and 'battle-pause' in o.visuals
            and o.find('战利品',region=(0,0,.2,.08))):
        return Reading('dimension_battle_wait',stage=battle_active['stage'],key=battle_active['current_node'],detail='有本次开战意图且实帧暂停HUD匹配；只等原生自动战斗，不点击技能。')
    loot=o.find('闪电箭','闪电箭簇',region=(.16,.3,.36,.43))
    if (loot and o.has('地下怪兽鳞片') and o.has('星光药瓶') and o.contains('战斗开始时，在3回合')
            and o.contains('内获得免疫效果') and o.find('选择战利品',region=(.35,.84,.65,.99))):
        active=(context or {}).get('active') or {};key=active.get('current_node','')
        if 'dimension-loot-first-selected' in o.visuals:
            return Reading('dimension_loot_confirm',o.find('选择战利品',region=(.35,.84,.65,.99)),key=key,event='loot_flash_arrow',detail='选中金色卡面与边框已核实；领取通用三回合免疫，不重新抽取。')
        return Reading('dimension_loot_select',loot,key=key,event='loot_flash_arrow',detail='选通用三回合免疫；队伍没有射手，不选射手切换专用效果；不消耗重抽币。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.find('获得随机招募券。',region=(.7,.35,.97,.47))
            and o.find('获得战利品。',region=(.7,.5,.97,.62)) and o.find('离开',region=(.72,.84,.99,.99))):
        active=(context or {}).get('active') or {}
        if 'dimension-supply-reward-claimed' in o.visuals:
            return Reading('dimension_supply_complete',o.find('离开',region=(.72,.84,.99,.99)),key=active.get('current_node',''),detail='补给战利品已领取勾选标志，结合当前领取意图核验，不再重抽。')
        return Reading('dimension_supply_loot',o.find('获得战利品。',region=(.7,.5,.97,.62)),key=active.get('current_node',''),detail='四人队伍已齐，选择当前补给的免费战利品，不再额外招募或购买。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.contains('刻有古代文字') and o.contains('残破古老石碑映入眼帘')
            and o.find('查看石碑下方的缝隙。',region=(.2,.75,.5,.9)) and o.find('拓印无名纹样。',region=(.5,.75,.8,.9))
            and o.contains('所有英雄生命值降低25%')):
        active=(context or {}).get('active') or {}
        return Reading('dimension_event_choice',o.find('查看石碑下方的缝隙。',region=(.2,.75,.5,.9)),key=active.get('current_node',''),event='ancient_stele',detail='选左侧缝隙，避开右侧明确降低全队25%生命值的选项；随后核对实际碎片变化。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.find('撕裂的祭服铺在地上。')
            and o.find('拿走祭服。',region=(.2,.75,.5,.9)) and o.find('将祭服留在原地。',region=(.5,.75,.8,.9))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_event_choice',o.find('将祭服留在原地。',region=(.5,.75,.8,.9)),key=active.get('current_node',''),event='torn_vestment',detail='选择明确的留下祭服；不选择左侧消耗生命体征的取物选项。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.contains('石碑下方的泥土缝隙中放着几枚古老的硬币')
            and o.contains('探查队将那些被遗忘的名字留在身后') and o.find('事件叙事继续指示')):
        active=(context or {}).get('active') or {}
        budgets={tuple(map(int,normalize(t.text).split('/'))) for t in o.tokens if t.source=='dimension_budget'}
        budget=next(iter(budgets)) if len(budgets)==1 else None
        return Reading('dimension_event_result',o.find('事件叙事继续指示'),key=active.get('current_node',''),event='ancient_stele',budget=budget,detail='石碑缝隙结果；独立核对碎片+50，生命体征与招募额度未减少。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.contains('决定不去触碰破损的祭服')
            and o.contains('微弱的光芒逐渐消失') and o.find('事件叙事继续指示')):
        active=(context or {}).get('active') or {}
        budgets={tuple(map(int,normalize(t.text).split('/'))) for t in o.tokens if t.source=='dimension_budget'}
        budget=next(iter(budgets)) if len(budgets)==1 else None
        return Reading('dimension_event_result',o.find('事件叙事继续指示'),key=active.get('current_node',''),event='torn_vestment',budget=budget,detail='不触碰祭服结果；核对招募额度和生命体征均未减少。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.contains('清理掉柱子周围的灰尘和残骸后')
            and o.contains('探查队记录下空间的位置后离开了古老') and o.find('事件叙事继续指示')):
        active=(context or {}).get('active') or {}
        budgets={tuple(map(int,normalize(t.text).split('/'))) for t in o.tokens if t.source=='dimension_budget'}
        budget=next(iter(budgets)) if len(budgets)==1 else None
        return Reading('dimension_event_result',o.find('事件叙事继续指示'),key=active.get('current_node',''),event='dust_corridor',budget=budget,detail='事件结果叙事及招募额度变化独立核验；仅记本节点，不记整轮完成。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.contains('灰尘弥漫的回廊')
            and o.find('清理柱子周围的灰尘和残骸。',region=(.2,.75,.5,.9))
            and o.find('招募额度提升1',region=(.2,.88,.5,.99))
            and o.find('招募1名随机英雄',region=(.5,.88,.8,.99))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_event_choice',o.find('清理柱子周围的灰尘和残骸。',region=(.2,.75,.5,.9)),key=active.get('current_node',''),event='dust_corridor',detail='选择界面明确奖励招募额度+1的清理选项；不消耗碎片、不额外战斗或随机招募。')
    if (o.find('升级',region=(.35,.12,.65,.27)) and o.find('招募额度提升',region=(.35,.65,.65,.78))
            and any(re.fullmatch(r'\d{1,2}>\d{1,2}',normalize(t.text)) and o.in_region(t,(.4,.7,.6,.8)) for t in o.tokens)
            and o.find('点击关闭',region=(.35,.84,.65,.94))):
        return Reading('dimension_expedition_upgrade',o.find('点击关闭',region=(.35,.84,.65,.94)),key=((context or {}).get('active') or {}).get('current_node',''),detail='免费探查等级提升，不是账号升级，也不代表整轮通关。')
    close = o.find('点击关闭', region=(.3,.85,.7,1))
    if (o.find('星之旅程',region=(.25,0,.75,.15)) and o.has('完成节点')
            and o.has('最终分数') and o.has('获得星辰气息') and close):
        known={normalize(t) for t in ('星之旅程','完成节点','招募英雄','获得次元碎片','获得战利品',
               '一般战斗','般战斗','精英战斗','首领战斗','最终分数','获得星辰气息','点击关闭')}
        extra=[t for t in o.tokens if normalize(t.text) not in known
               and not re.fullmatch(r'x?\d[\d,.]*(?:pt)?',normalize(t.text))]
        if extra:return Reading('attention',detail='汇总页上出现未验证的额外文字/覆盖层，不点击关闭。')
        return Reading('dimension_summary',close,detail='仅关闭分数汇总，不据此补记通关。')
    if (o.find('准备一般战斗','准备首领战斗',region=(0,0,.3,.1)) and o.has('管理队伍') and o.has('队伍战斗力')
            and o.find('开始战斗',region=(.72,.84,.99,.99)) and o.has('冒险家拉斯')
            and o.has('自由自在的佣兵赫尔嘉') and o.has('圣炎的艾庭')
            and sum(normalize(t.text)=='sp' for t in o.tokens)>=4
            and 'dimension-four-full-hp-members' in o.visuals):
        return Reading('dimension_battle_prepare',o.find('开始战斗',region=(.72,.84,.99,.99)),key=((context or {}).get('active') or {}).get('current_node',''),detail='四名已招募英雄、四条满血条与三名未遮挡姓名联合核验；第四名仅有四名可选且招募链完整。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄')
            and any(normalize(t.text).endswith('首领战斗') and o.in_region(t,(.7,.1,.98,.2)) for t in o.tokens)
            and o.contains('层主正在等待着你') and o.contains('他层域探查')
            and o.contains('登场的敌人') and o.find('进入',region=(.72,.84,.99,.99))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_boss_gate',o.find('进入',region=(.72,.84,.99,.99)),key=active.get('selected_node',''),detail='当前唯一开放的区域层主，胜利才能到下一层域；避战仍保留必经首领。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄')
            and any(normalize(t.text).endswith('补给') and o.in_region(t,(.7,.1,.98,.2)) for t in o.tokens)
            and o.contains('可招募英雄或获得战利品') and o.find('进入',region=(.72,.84,.99,.99))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_supply_gate',o.find('进入',region=(.72,.84,.99,.99)),key=active.get('selected_node',''),detail='已核实补给，不进行普通召唤、兑换或购买。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄')
            and any(normalize(t.text).endswith('休整') and o.in_region(t,(.7,.1,.98,.2)) for t in o.tokens)
            and o.contains('可整顿队伍或进行英雄升阶') and o.find('进入',region=(.72,.84,.99,.99))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_rest_gate',o.find('进入',region=(.72,.84,.99,.99)),key=active.get('selected_node',''),detail='只进入已验证的休整节点，不授权升星、升阶或花费。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄')
            and any(normalize(t.text).endswith('事件') and o.in_region(t,(.7,.1,.98,.2)) for t in o.tokens)
            and o.contains('无法得知即将发生什么') and o.find('进入',region=(.72,.84,.99,.99))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_event_gate',o.find('进入',region=(.72,.84,.99,.99)),key=active.get('selected_node',''),detail='已选可达问号节点，详情为事件；内容未探明，不保证无战斗。')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄')
            and o.find('一般战斗',region=(.7,.1,.97,.2)) and o.contains('胜利时可获得探查经验值')
            and o.contains('登场的敌人') and o.contains('可获得的奖励') and o.find('进入',region=(.72,.84,.99,.99))):
        return Reading('dimension_node_gate',o.find('进入',region=(.72,.84,.99,.99)),key='initial',detail='当前唯一可行动节点为起始一般战斗，尚无可选分支；避战不跳过必经节点。')
    if (o.find('VICTORY',region=(.3,0,.7,.15)) and o.has('次元碎片') and o.has('完成领取')
            and o.find('继续探查',region=(.35,.84,.65,.99))):
        active=(context or {}).get('active') or {}
        return Reading('dimension_node_victory',o.find('继续探查',region=(.35,.84,.65,.99)),key=active.get('current_node',''),detail='单节点独立胜利结算，不能记整轮阶段完成。')
    avoid=next((t for t in o.tokens if t.source=='dimension_route_avoid'),None)
    if o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄') and avoid:
        proofs=[json.loads(v.removeprefix('dimension_route_plan:')) for v in o.visuals if v.startswith('dimension_route_plan:')]
        active=(context or {}).get('active') or {}
        if len(proofs)==1 and active.get('last_cleared_node'):
            proof=proofs[0];key='node-'+str(len(active.get('nodes',{})))+'-'+proof['key']
            return Reading('dimension_route_avoid',avoid,key=key,route=tuple(proof['nodes']),combat_bounds=(proof['lower'],proof['upper']),detail=proof['detail'])
    current=o.find('当前高亮路线节点')
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and o.has('战利品') and o.has('英雄') and current):
        active=(context or {}).get('active') or {}
        key='node-'+str(len(active.get('nodes',{})))+'-current' if active.get('last_cleared_node') else 'initial'
        return Reading('dimension_route_node',current,key=key,detail='唯一蓝色高亮且带独立指针的当前可达节点；仅打开详情，不直接开战。')
    active=(context or {}).get('active') or {}
    role=active.get('current_role')
    selected=active.get('hero_selection_intents',{}).get(role,{})
    hero=selected.get('hero')
    if (role and hero and o.find(role+'招募券',region=(0,0,.25,.1))
            and o.find(hero,region=(.02,.08,.25,.2)) and o.has('战斗力')
            and o.find('招募英雄',region=(.7,.84,.99,.99))):
        costs={int(t.text) for t in o.tokens if t.source=='dimension_cost:'+hero and re.fullmatch(r'[1-9]',t.text)}
        budgets=set()
        for t in o.tokens:
            m=re.fullmatch(r'(\d{1,2})/(\d{1,2})[:.]*',normalize(t.text))
            if m and o.in_region(t,(.88,0,.98,.09)):budgets.add(tuple(map(int,m.groups())))
        if len(costs)==1 and len(budgets)==1:
            return Reading('dimension_hero_recruit',o.find('招募英雄',region=(.7,.84,.99,.99)),key=role,hero=hero,cost=next(iter(costs)),budget=next(iter(budgets)))
    preferences={'骑士':('冒险家拉斯',),'精灵师':('守护天使蒙茉朗西','吉祥物海兹'),'战士':('自由自在的佣兵赫尔嘉','塔拉诺尔禁卫队'),'盗贼':('圣炎的艾庭','新绿的艾庭','可丽')}
    if (role in preferences and o.find(role+'招募券',region=(0,0,.25,.1)) and o.has('搜索')
            and o.has('无选择的英雄。') and o.find('招募英雄',region=(.7,.84,.99,.99))):
        for name in preferences[role]:
            hero_token=o.find(name,region=(.25,.1,.75,.85))
            if hero_token:return Reading('dimension_hero_select',hero_token,detail='优先当前可见的低额度基准队伍；招募前核对费用。',key=name)
    expedition=o.find('彗星神殿：外围区域',region=(0,0,.35,.1))
    ticket_roles=('骑士','战士','精灵师','盗贼')
    ticket_labels=sum(o.has(role+'招募券') for role in ticket_roles)
    if expedition and o.has('进入探查') and (ticket_labels>=2 or o.has('招募完毕')):
        active=(context or {}).get('active') or {};done=dict(active.get('recruited_roles',{}));confirmed=[]
        for role,cx in zip(ticket_roles,(.173,.391,.61,.829)):
            intent=active.get('recruit_intents',{}).get(role,{})
            if intent and o.find('招募完毕',region=(cx-.1,.56,cx+.1,.65)) and o.find(intent['hero'],region=(cx-.1,.64,cx+.1,.72)):
                confirmed.append((role,intent['hero']));done[role]=intent
        budgets={tuple(map(int,normalize(t.text).split('/'))) for t in o.tokens if t.source=='dimension_budget'}
        budget=next(iter(budgets)) if len(budgets)==1 else None
        for role in ('骑士','精灵师','战士','盗贼'):
            card=o.find(role+'招募券',region=(0,.35,.99,.5))
            if not card or role in done:continue
            cx=card.center[0]/o.width
            recruit=o.find('招募英雄',region=(max(0,cx-.09),.65,min(.99,cx+.09),.78))
            if recruit:return Reading('dimension_ticket',recruit,detail='使用当前探查提供的职业招募券，不进行普通召唤。',key=role,budget=budget,recruits=tuple(confirmed))
        if len(confirmed)==4:return Reading('dimension_team_ready',o.find('进入探查',region=(.7,.84,.99,.99)),budget=budget,recruits=tuple(confirmed))
    # Initial free loadout: only the first unlocked contract card is implemented.
    contract=o.find('雇佣契约','履佣契约',region=(0,.3,.23,.43))
    if (o.find('彗星神殿：外围区域',region=(0,0,.35,.1)) and contract
            and o.contains('招募额度提升3') and o.contains('一名英雄')
            and o.find('选择',region=(.72,.84,.98,.99))):
        card_text=''.join(t.text for t in o.tokens if o.in_region(t,(0,.15,.23,.8)))
        if '解锁' not in card_text and '锁定' not in card_text:
            if 'loadout-contract-selected' in o.visuals:
                return Reading('dimension_loadout_confirm',o.find('选择',region=(.72,.84,.98,.99)),detail='金色卡面与高亮边框已核实，确认雇佣契约。')
            return Reading('dimension_loadout_card',contract,detail='选择未锁定的雇佣契约，优先额外招募与队伍完整性。')
    title=o.find('次元探查',region=(0,0,.25,.1))
    if title and o.has('研究') and o.has('舰桥') and o.has('探查记录档案') and o.has('次元核共鸣'):
        skip=o.find('跳过教学',region=(.78,0,.99,.12))
        if skip:return Reading('dimension_tutorial_skip',skip)
        stages=[re.fullmatch(r'第([1-9]\d*)阶段',normalize(t.text)) for t in o.tokens if o.in_region(t,(.7,.75,.99,.87))]
        stages={m.group(1) for m in stages if m}
        if len(stages)==1 and o.find('开始探查',region=(.7,.84,.99,.99)):
            return Reading('dimension_hub',o.find('开始探查',region=(.7,.84,.99,.99)),stage=next(iter(stages)),detail='阶段入场需明确授权且无既有尝试；不重复开局。')
    if (o.find('难度',region=(.1,0,.4,.25)) and o.has('分数倍率') and o.has('Easy','Normal')
            and o.contains('我军人员恢复量降低50%') and o.contains('生命体征最大值降低1')
            and o.find('选择',region=(.35,.84,.65,.99))):
        return Reading('dimension_difficulty',o.find('选择',region=(.35,.84,.65,.99)),detail='仅返回当前选择，不选新阶段、不入场。')
    if (o.find('探查记录档案',region=(0,0,.3,.1)) and o.has('故事') and o.has('怪物') and o.has('事件')
            and o.find('100%',region=(.85,.9,.99,1))):
        return Reading('dimension_archive_page',detail='收集档案不是难度通关记录；仅返回。')
    if (o.find('战斗',region=(.86,.34,.99,.57)) and o.find('召唤',region=(.86,.53,.99,.76))
            and o.find('商店',region=(.86,.65,.99,.87))):
        return Reading('dimension_lobby',o.find('战斗',region=(.86,.34,.99,.57)))
    if o.has('一般') and o.has('活动') and o.has('赛季','赛事') and o.find('战斗',region=(0,0,.2,.13)):
        gate=o.find('次元探查',region=(0,.08,.55,.65))
        if gate:return Reading('dimension_entrance',gate)
    return Reading('unknown',detail='尚未验收的次元探查画面；不猜测按钮或地图节点。')


NAVIGATION_NAMES = {
    'dimension_expedition_upgrade':'关闭免费探查升级提示',
    'dimension_summary':'关闭星之旅程汇总（不记通关）',
    'dimension_tutorial_skip':'跳过次元探查教学',
    'dimension_lobby':'打开战斗菜单',
    'dimension_entrance':'进入次元探查',
    'dimension_difficulty':'返回当前难度（不入场、不改难度）',
}

def plan(reading: Reading, context=None) -> Action | None:
    if reading.scene=='dimension_supply_complete':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if node.get('status')=='completed' and node.get('loot_confirm_intent') and not node.get('supply_leave_intent'):
            return Action('已领取补给战利品，继续避战路线',reading.target,'supply_leave',active['stage'])
        raise TaskAttention('dimension_supply_complete','补给结果未核实','缺少已领取证据、领取意图或已发送离开。')
    if reading.scene in ('dimension_loot_select','dimension_loot_confirm'):
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if not node.get('supply_choice_intent'):raise TaskAttention('dimension_loot','战利品未关联','没有当前补给的免费奖励选择。')
        if reading.scene=='dimension_loot_select' and not node.get('loot_select_intent'):
            return Action('选择通用三回合免疫战利品（不重抽）',reading.target,'loot_select',active['stage'])
        if reading.scene=='dimension_loot_confirm' and node.get('loot_select_intent') and not node.get('loot_confirm_intent'):
            return Action('领取选中的免费免疫战利品',reading.target,'loot_confirm',active['stage'])
        raise TaskAttention('dimension_loot_pending','战利品结果未核实','已有相同选择/领取意图，不重复抽取或领取。')
    if reading.scene=='dimension_supply_loot':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if node.get('kind')=='supply' and not node.get('supply_choice_intent'):
            return Action('补给选择免费战利品，增强避战队伍',reading.target,'supply_loot',active['stage'])
        raise TaskAttention('dimension_supply','补给未核实','缺少本次补给入场，或免费奖励选项已经发送。')
    if reading.scene=='dimension_rest_skip_confirm':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if node.get('rest_leave_intent') and not node.get('rest_skip_confirm_intent'):
            return Action('确认跳过未选休整奖励，继续避战',reading.target,'rest_confirm',active['stage'])
        raise TaskAttention('dimension_rest_confirm','休整确认未核实','缺少本次离开意图或此确认已发送。')
    if reading.scene=='dimension_rest_leave':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if node.get('kind')=='rest' and not node.get('rest_leave_intent'):
            return Action('离开休整：不升阶、不复活、不消费',reading.target,'rest_leave',active['stage'])
        raise TaskAttention('dimension_rest','休整离开未核实','缺少当前休整入场或已经发送离开意图。')
    if reading.scene=='dimension_event_result':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if node.get('status')=='completed' and node.get('event_success')==reading.event and not node.get('result_continue_intent'):
            return Action('事件无交战完成，继续避战路线',reading.target,'event_continue',active['stage'])
        raise TaskAttention('dimension_event_result','事件结果未核实','事件奖励变化未核实或继续意图已发送。')
    if reading.scene=='dimension_event_choice':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key,{})
        if node.get('kind')=='event' and reading.event not in node.get('choice_intents',{}):
            return Action('避战事件：查看石碑缝隙，避开扣血选项' if reading.event=='ancient_stele' else '避战事件：留下祭服，不消耗生命体征' if reading.event=='torn_vestment' else '避战事件：清理回廊，领取明确的招募额度+1',reading.target,'event_choice',active['stage'])
        raise TaskAttention('dimension_event_choice','事件选择未核实','缺少当前事件入场，或同一抉择已发送，不重复选择。')
    if reading.scene=='dimension_route_avoid':
        active=(context or {}).get('active') or {};previous=active.get('nodes',{}).get(active.get('last_cleared_node'),{})
        if previous.get('status')=='completed' and reading.key not in active.get('node_navigation_intents',{}) and reading.route:
            return Action('避战选路：选择已核实的低交战可达分支',reading.target,'node_open',active['stage'])
        raise TaskAttention('dimension_route','路线选择未核实','没有独立上一节点完成证据，或该节点选择已发送。')
    if reading.scene=='dimension_node_victory':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key)
        if node and node.get('status')=='completed' and not node.get('result_continue_intent'):
            return Action('确认当前节点胜利，返回避战选路',reading.target,'battle_continue',active['stage'])
        raise TaskAttention('dimension_victory','节点结算未关联','缺少相符入场/独立胜利记录，或返回意图已发送。')
    if reading.scene=='dimension_battle_prepare':
        active=(context or {}).get('active') or {};node=active.get('nodes',{}).get(reading.key)
        if node and not node.get('battle_start_intent') and len(active.get('recruited_roles',{}))==4:
            return Action('开始当前唯一必经战斗（不重复节点）',reading.target,'battle_start',active['stage'])
        raise TaskAttention('dimension_battle_start','禁止重复开战','节点入场、队伍记录缺失或已经发送开战意图。')
    if reading.scene in ('dimension_node_gate','dimension_event_gate','dimension_rest_gate','dimension_supply_gate','dimension_boss_gate'):
        active=(context or {}).get('active') or {}
        if reading.key in active.get('node_navigation_intents',{}) and reading.key not in active.get('nodes',{}):
            return Action('进入当前必经层主准备（不重复）' if reading.scene=='dimension_boss_gate' else '进入补给节点（不购买）' if reading.scene=='dimension_supply_gate' else '进入休整节点（不升阶、不消费）' if reading.scene=='dimension_rest_gate' else '进入已核实事件节点' if reading.scene=='dimension_event_gate' else '进入当前必经一般战斗准备流程',reading.target,'node_enter',active['stage'])
        raise TaskAttention('dimension_node_entry','禁止重复进入节点','缺少本次节点导航证据，或节点已有入场记录。')
    if reading.scene=='dimension_route_node':
        active=(context or {}).get('active') or {}
        if active.get('route_start_intent') and reading.key not in active.get('node_navigation_intents',{}):
            return Action('核验唯一当前可达节点详情（尚不开战）',reading.target,'node_open',active['stage'])
        raise TaskAttention('dimension_node','节点未核实','没有本次路线，或相同节点已发送导航意图，不重复打开。')
    if reading.scene=='dimension_team_ready':
        active=(context or {}).get('active') or {};roles=active.get('recruited_roles',{})
        if set(roles)=={'骑士','精灵师','战士','盗贼'} and reading.budget and reading.budget[0]==sum(v['cost'] for v in roles.values()) and not active.get('route_start_intent'):
            return Action('编成核验通过，进入本次探查路线',reading.target,'route_begin',active['stage'])
        raise TaskAttention('dimension_team','编成未核实','四职业、额度或首次进入路线意图未满足；不重复进入。')
    if reading.scene=='dimension_hero_recruit':
        active=(context or {}).get('active') or {};role=active.get('current_role')
        if (role!=reading.key or role in active.get('recruit_intents',{}) or active.get('hero_selection_intents',{}).get(role,{}).get('hero')!=reading.hero):
            raise TaskAttention('dimension_recruit','禁止重复招募','职业上下文不匹配或招募意图已存在。')
        if reading.budget is None or reading.cost is None:
            raise TaskAttention('dimension_budget','招募额度未知','不能核实当前额度与本名英雄的费用。')
        used,total=reading.budget;remaining=3-len(active.get('recruited_roles',{}))
        if not 0<=used<=total or used+reading.cost+max(0,remaining)*2>total:
            raise TaskAttention('dimension_budget','保留完整队伍额度','费用或剩余额度不足以完成四职业最低编成。')
        return Action('招募'+reading.hero+'（探查额度'+str(reading.cost)+'）',reading.target,'hero_recruit',active['stage'])
    if reading.scene=='dimension_hero_select':
        active=(context or {}).get('active')
        if active and active.get('current_role') in ('骑士','精灵师','战士','盗贼') and active['current_role'] not in active.get('hero_selection_intents',{}):
            return Action('查看'+reading.key+'招募详情',reading.target,'hero_select',active['stage'])
        raise TaskAttention('dimension_hero_select','等待英雄选择核验','缺少当前职业上下文，或已有选择意图。')
    if reading.scene=='dimension_ticket':
        active=(context or {}).get('active')
        if active and active.get('loadout_confirm_intent') and reading.key not in active.get('ticket_intents',{}):
            return Action('打开'+reading.key+'招募名单',reading.target,'ticket_open',active['stage'])
        raise TaskAttention('dimension_ticket','招募券等待核验','缺少当前入场/方案记录，或该职业招募已发送，不重复操作。')
    if reading.scene=='dimension_loadout_confirm':
        active=(context or {}).get('active')
        if active and active.get('loadout_selection') and not active.get('loadout_confirm_intent'):
            return Action('确认雇佣契约',reading.target,'loadout_confirm',active['stage'])
        raise TaskAttention('dimension_loadout_confirm','等待方案确认','缺少选择记录或确认已发送，不重复操作。')
    if reading.scene=='dimension_loadout_card':
        active=(context or {}).get('active')
        if active and not active.get('loadout_selection'):
            return Action('选择雇佣契约',reading.target,'loadout_select',active['stage'])
        raise TaskAttention('dimension_loadout','等待初始方案核验','没有已记录入场，或本次方案选择已发送，不能重复点击。')
    if reading.scene=='dimension_hub':
        book=context or {};stage=reading.stage
        if (reading.target and stage and stage in book.get('entry_authorizations',{})
                and stage not in book.get('attempted',{}) and stage not in book.get('completed',{})
                and not book.get('active')):
            return Action('开始次元探查第'+stage+'阶段',reading.target,'enter',stage)
        raise TaskAttention('dimension_entry','次元探查入场已暂停','当前阶段未明确授权、已有尝试或已有未结算探查；不自动重新入场。')
    if reading.scene in ('attention','defeat'):

        raise TaskAttention('dimension_'+reading.scene,'次元探查等待处理',reading.detail)
    if reading.scene=='dimension_archive_page':
        return Action('返回次元探查舰桥',None,'back')
    if reading.target is not None and reading.scene in NAVIGATION_NAMES:
        return Action(NAVIGATION_NAMES[reading.scene],reading.target)
    return None


def fingerprint(o: Observation) -> str:
    rows=sorted((normalize(t.text),round(t.center[0]/o.width,2),round(t.center[1]/o.height,2)) for t in o.tokens)
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()


def reading_key(r: Reading):
    return (r.scene,r.stage,normalize(r.target.text) if r.target else None,r.key,r.hero,r.cost,('/'.join(map(str,r.budget)) if r.budget is not None else None))


def same_reading(a: Reading, b: Reading, width: int, height: int) -> bool:
    if reading_key(a)!=reading_key(b):return False
    if a.target is None or b.target is None:return a.target is b.target
    ax,ay=a.target.center;bx,by=b.target.center
    return abs(ax-bx)<=width*.015 and abs(ay-by)<=height*.015
