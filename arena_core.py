"""Conservative NPC-arena page recognition; no input or state mutation."""
from dataclasses import dataclass
import re
from abyss_core import Observation, Token
from task_blockers import TaskAttention, capacity_blocker


def count(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,3}', str(value)):
        raise ValueError('竞技场次数必须为 1～9999 的整数。')
    return int(value)


def norm(text):
    return re.sub(r'\s+', '', text).casefold()


def one(o, text, region, threshold=.94):
    rows=[t for t in o.tokens if norm(t.text)==norm(text) and o.in_region(t,region)]
    if len(rows)==1 and rows[0].score is not None and rows[0].score>=threshold:
        return rows[0]


def opponent_field(o,region):
    groups={}
    for t in o.tokens:
        if not o.in_region(t,region) or t.score is None:continue
        key=(norm(t.text),round(t.x,2),round(t.y,2),round(t.w,2),round(t.h,2))
        if key not in groups or groups[key].score<t.score:groups[key]=t
    rows=list(groups.values())
    if not rows or any(t.score<.98 for t in rows):return None
    if len(rows)==1:return rows[0]
    # Only two aligned lines inside one fixed name field; never merge heroes,
    # level badges, a neighbouring opponent, or arbitrary OCR elsewhere.
    if len(rows)==2:
        first,second=sorted(rows,key=lambda t:t.y)
        if (abs(first.x-second.x)<=o.width*.015 and .018<=(second.center[1]-first.center[1])/o.height<=.055
                and len(second.text)<len(first.text) and all(re.fullmatch(r'[^\d\W_]+',t.text) for t in rows)):
            x=min(t.x for t in rows);y=min(t.y for t in rows)
            right=max(t.x+t.w for t in rows);bottom=max(t.y+t.h for t in rows)
            return Token(first.text+second.text,x,y,right-x,bottom-y,source='arena_name_multiline',score=min(t.score for t in rows))


@dataclass(frozen=True)
class Reading:
    scene: str='arena_unknown'
    target: Token|None=None
    opponent: str=''
    stock: int|None=None
    cost: int|None=None


def classify(o):
    text=''.join(norm(t.text) for t in o.tokens)
    blocker=capacity_blocker([t.text for t in o.tokens])
    if blocker:
        raise TaskAttention(blocker.code,blocker.title,blocker.reason)
    if any(w in text for w in ('战斗失败','defeat','战败','挑战失败')):
        raise TaskAttention('arena_defeat','竞技场战败','保留入场与战败证据，不自动重试。')
    if any(w in text for w in ('不足','复活','购买','兑换','网络错误','连接中断')):
        raise TaskAttention('arena_resource','资源或风险提示','不购买挑战书、体力，不兑换、复活或确认未知提示。')
    warning_specs=(('未配置英雄',(.42,.22,.59,.31)),
        ('队伍内有未配置英雄的栏位。',(.30,.395,.70,.447)),
        ('确定要用这个队伍开始战斗吗？',(.30,.435,.70,.485)),
        ('点击不再显示按钮，今日内将不再显示弹窗，',(.25,.54,.75,.60)),
        ('并开始战斗。',(.40,.585,.61,.64)),('取消',(.26,.69,.40,.80)),
        ('确认',(.43,.69,.57,.80)),('不再显示',(.59,.69,.75,.80)))
    warning=[one(o,label,region,.98) for label,region in warning_specs]
    if (all(warning) and 'arena_team_warning_confirm' in o.visuals
        and one(o,'新手竞技场',(.025,0,.22,.10),.98)
        and all(sum(norm(t.text)==norm(label) for t in o.tokens)==1 for label in ('取消','确认','不再显示'))):
        allowed={norm(t.text) for t in warning}
        if not any(o.in_region(t,(.22,.20,.78,.80)) and norm(t.text) not in allowed for t in o.tokens):
            # The blurred underlying opponent is not observed. The journal
            # alone may bind this exact known dialog to its unique original entry.
            return Reading('arena_team_warning',warning[-2])
    if 'arena_notice_modal' in o.visuals:return Reading()
    victory=one(o,'VICTORY',(.30,.25,.72,.44),.98)
    result=one(o,'战斗结果',(.73,.85,.85,.98),.98)
    confirm=one(o,'确认',(.86,.85,.97,.98),.98)
    npc_result=one(o,'NPC对战的胜负',(.40,.59,.60,.68),.98)
    unaffected=one(o,'不会影响积分。',(.40,.63,.60,.71),.98)
    if victory and result and confirm and npc_result and unaffected and sum(norm(t.text)=='确认' for t in o.tokens)==1:
        names=[t for t in o.tokens if o.in_region(t,(.53,.065,.76,.11)) and t.score is not None and t.score>=.98]
        allowed={'victory','npc对战的胜负','不会影响积分。'}
        allowed.update(v.split(':',1)[1] for v in o.visuals if v.startswith('arena_victory_original:'))
        extra=[t for t in o.tokens if o.in_region(t,(.25,.20,.75,.85)) and norm(t.text) not in allowed and not re.fullmatch(r'\d+',norm(t.text))]
        if len(names)==1 and not extra and not any(norm(t.text) in ('取消','确定','点击关闭','重试','重新挑战') for t in o.tokens):
            return Reading('arena_result',confirm,names[0].text)
    if any(norm(t.text) in ('取消','确认','确定','点击关闭','重试','重新挑战') for t in o.tokens):
        return Reading()
    hud={'arena_pause','arena_hp_left','arena_hp_right'}
    if hud.issubset(o.visuals):
        names=[t for t in o.tokens if o.in_region(t,(.53,.065,.76,.11)) and t.score is not None and t.score>=.98]
        auto=one(o,'A',(.865,.02,.90,.07),.98)
        if len(names)==1:
            target=auto if auto and 'arena_auto_white' in o.visuals and 'arena_auto_on' not in o.visuals else None
            return Reading('arena_battle',target,names[0].text)
    header=one(o,'新手竞技场',(.025,0,.22,.10),.98)
    if header:
        start=one(o,'战斗开始',(.60,.85,.74,.98),.98)
        npc=one(o,'NPC对战',(.62,.73,.75,.82),.98)
        opponents=[t for t in o.tokens if o.in_region(t,(.60,.68,.755,.75)) and t.score is not None and t.score>=.98]
        quick=one(o,'快速对战',(.60,.85,.74,.98),.98)
        daily=one(o,'本日快速对战剩余次数',(.35,.87,.51,.93),.98)
        daily_counts=[t for t in o.tokens if o.in_region(t,(.39,.92,.47,.97))
                      and re.fullmatch(r'\d{1,4}/\d{1,4}',norm(t.text))
                      and t.score is not None and t.score>=.98]
        has_start=any(norm(t.text)=='战斗开始' for t in o.tokens)
        has_quick=any(norm(t.text)=='快速对战' for t in o.tokens)
        quick_layout=bool(quick and not has_start and daily and len(daily_counts)==1
                          and 'arena_normal_mode_toggle' in o.visuals)
        if quick_layout:
            remaining,maximum=map(int,norm(daily_counts[0].text).split('/'))
            quick_layout=0<=remaining<=maximum and maximum>0
        if ((start and not has_quick) or quick_layout) and npc and len(opponents)==1:
            costs=[t for t in o.tokens if o.in_region(t,(.54,.87,.62,.96)) and re.fullmatch(r'\d{1,4}/\d{1,5}',norm(t.text)) and t.score is not None and t.score>=.98]
            if len(costs)==1:
                cost,stock=map(int,norm(costs[0].text).split('/'))
                if cost!=1:
                    raise TaskAttention('arena_cost','NPC对战费用不符合预期','当前仅允许每把1张现有挑战书，不猜测费用。')
                if stock<cost:
                    raise TaskAttention('arena_resource','挑战书不足','不打开购买或兑换。')
                if quick_layout:
                    # This is ONLY the adjacent free mode switch, never the
                    # resource-spending quick battle button or an entry target.
                    target=Token('切换普通战斗',o.width*.723,o.height*.878,
                                 o.width*.046,o.height*.085,
                                 source='arena_normal_mode_toggle',score=1)
                    return Reading('arena_quick_team',target,opponents[0].text,stock,cost)
                return Reading('arena_team',start,opponents[0].text,stock,cost)
        title=one(o,'NPC交战对手',(.22,.11,.45,.21),.98)
        tab=one(o,'NPC对战',(.81,.24,.95,.36),.98)
        if title and tab:
            name=opponent_field(o,(.30,.285,.49,.345))
            if name:
                return Reading('arena_npc',name,name.text)
            return Reading()
        if tab:
            return Reading('arena_tab',tab)
    hub=one(o,'竞技场',(0,0,.20,.10),.98)
    beginner=one(o,'新手竞技场',(.26,.87,.46,.99),.98)
    if hub and beginner and one(o,'世界竞技场',(.54,.87,.73,.99),.98):
        return Reading('arena_hub',beginner)
    lobby=one(o,'竞技场',(.87,.48,.99,.59),.98)
    if lobby and one(o,'Episode',(.84,.20,.99,.31),.98) and one(o,'英雄',(.70,.89,.81,.99),.98):
        return Reading('arena_lobby',lobby)
    return Reading()
