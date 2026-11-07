"""First-entry power warning confirmation, not retry or warning suppression."""
import copy,datetime,hashlib,json,math
from entry_journal import attempt_digest


def power_warning_plan(f,unique):
    specs=(('战斗指南',(600,185,1000,300)),('登场的敌方战斗力',(500,330,1100,380)),
           ('比我方队伍高出许多[。.]?',(500,375,1100,410)),('要继续进行吗[？?]',(600,410,1000,475)),
           ('点击不再显示按钮[，,]今日内将不再显示弹窗[，,]',(400,490,1200,540)),
           ('并开始战斗[。.]?',(600,535,1000,580)),('取消',(390,615,650,710)),
           ('确认',(670,615,925,710)),('不再显示',(940,615,1190,710)))
    anchors=[unique(f,p,region,.98) for p,region in specs]
    if not all(anchors):return None
    allowed={w['text'] for w in anchors}
    if any(w['text'] not in allowed and w['score']>=.90 for w in f.words if 380<w['x']<1220 and 185<w['y']<720):return None
    return dict(rule='first_entry_power_warning',label='确认原单次入场的战力差提示（仅继续首次战斗，不重开/不点不再显示）',target=anchors[-2],proof=anchors)


def confirmation_source(state,event_path):
    original=state.get('active') or {};key=original.get('key')
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    if (not key or state.get('attempted',{}).get(key)!=original or key in state.get('completed',{})
        or len(dispatches)!=1 or dispatches[0].get('status')!='sent' or dispatches[0].get('entry')!=original
        or dispatches[0].get('original_sha256')!=attempt_digest(original)
        or any(row.get('entry',{}).get('key')==key for row in state.get('unresolved_entries',[]))
        or original.get('entry_kind')=='story_only'
        # AUTO changes battle handling, not the identity/count of this entry.
        # Both modes were verified by the same guarded first-entry pipeline;
        # disabled/unknown/hosted/repeat controls still have no permission.
        or original.get('team_entry_mode') not in ('single_task','auto_on')
        or original.get('proof')!='未通关蓝色当前节点'
        or not 0<original.get('cost',0)<=100 or original.get('stamina_before',0)<original['cost']
        or any(original.get(k) for k in ('playback_observed_at','story_seen','victory_seen','battle_seen','defeat_seen'))):
        raise ValueError('战力确认缺少原唯一单次sent/未实际开战链。')
    records=[json.loads(line) for line in event_path.read_text(encoding='utf8').splitlines() if line.strip()]
    tail=[e for e in records if datetime.datetime.fromisoformat(e['time']).timestamp()>=math.floor(original['start_epoch'])]
    actions=[e for e in tail if e.get('kind')=='action']
    if (len(actions)!=1 or actions[0].get('action')!='进行任务（仅一次入场）' or actions[0].get('stage')!=key
        or any(e.get('kind')=='screen' and e.get('screen') not in ('team','unknown_dialog','new_player_tutorial') for e in tail)
        or any(e.get('kind') not in ('screen','action') for e in tail)):
        raise ValueError('原入场后发生其他输入/战斗/剧情/结果或来源不明，不确认。')
    return dict(key=key,original=copy.deepcopy(original),original_sha256=attempt_digest(original),
                input_chain_sha256=hashlib.sha256(json.dumps(tail,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
