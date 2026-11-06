"""One-use repair of a proven tutorial UI interception, never general battle retry.

Original sent/attempt/archives are immutable. A human continuation instruction
and an independently reviewed source manifest are required; none is generated
by the normal worker or from the mere existence of an attempted stage.
"""
from __future__ import annotations
import copy,time,re
from entry_journal import attempt_digest
from story_reopen import state_digest


def source_chain(state,key):
    original=state.get('attempted',{}).get(key)
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    archives=[r for r in state.get('unresolved_entries',[]) if r.get('entry',{}).get('key')==key]
    if (not original or key in state.get('completed',{}) or len(dispatches)!=1 or len(archives)>1
        or dispatches[0].get('status')!='sent' or dispatches[0].get('entry')!=original
        or dispatches[0].get('original_sha256')!=attempt_digest(original) or (archives and archives[0].get('entry')!=original) or (not archives and state.get('active')!=original)
        or original.get('entry_kind')=='story_only' or not 0<original.get('cost',0)<=100
        or any(original.get(k) for k in ('playback_observed_at','story_seen','victory_seen','battle_seen','defeat_seen'))):
        raise ValueError('教学接续原唯一sent/归档/未开战证据链不一致。')
    return dict(original=original,dispatches=dispatches,archives=archives)


def _fresh_pair(r,scene,observations):
    from runner import classify
    if len(observations)!=2 or observations[-1] is not r.frame:raise ValueError('需要当前独立双新帧。')
    a,b=observations
    if (not 0<b.at-a.at<=5 or not 0<=time.time()-b.at<=3 or a.raw_size!=b.raw_size
        or any(classify(f)!=scene for f in observations)):
        raise ValueError('教学接续页面、几何或新鲜度不一致。')


def open_handoff(r,permit,observations):
    from runner import mainline_map_control
    key=permit.get('key');chain=source_chain(r.s,key)
    if (not permit.get('id') or not permit.get('user_instruction') or not permit.get('source_evidence_sha256')
        or permit.get('source_state_sha256')!=state_digest(r.s)
        or permit.get('source_chain_sha256')!=state_digest(chain) or r.s.get('active')
        or any(row.get('key')==key or row.get('id')==permit['id'] for row in r.s.get('tutorial_entry_handoffs',[]))):
        raise ValueError('教学故障接续指令/来源不符或已经使用，未发送。')
    _fresh_pair(r,'map',observations)
    targets=[];ticket=None
    for f in observations:
        d,rows,proof=r.map_ticket(f);control=mainline_map_control(f)
        if (not d or d['key']!=key or d.get('locked') or d.get('clear_badge') or proof!='未通关蓝色当前节点'
            or not control or control['kind']!='battle' or control['target']['score']<.98):
            raise ValueError('原未完成关卡或准备战斗控件未核实。')
        targets.append(control['target']);ticket=d
    if max(abs(targets[0][k]-targets[1][k]) for k in ('x','y'))>8:raise ValueError('准备战斗目标移动。')
    record=copy.deepcopy(permit);record.update(status='reserved_open',at=time.time(),map_ticket=dict(ticket,phase='map'),map_evidence=r.evidence('tutorial-handoff-map-'+key))
    r.s.setdefault('tutorial_entry_handoffs',[]).append(record)
    r.ticket=dict(ticket,phase='map');r.save()
    r.action('修复教学配置截获：接续原关准备页（不是开战）',targets[-1])
    record.update(status='open_sent',open_sent_at=time.time());r.save();return record


def enter_handoff(r,record,observations,live_original=None):
    from story_core import team_entry_control
    from tutorial_core import owned_hero_selector_visible
    key=record['key'];chain=source_chain(r.s,key);original=chain['original']
    if (record not in r.s.get('tutorial_entry_handoffs',[]) or record.get('status')!='open_sent'
        or record.get('source_chain_sha256')!=state_digest(chain) or (r.s.get('active') is not None and (live_original!=chain['original'] or r.s.get('active')!=live_original))
        or not r.ticket or r.ticket.get('key')!=key or time.time()-record['open_sent_at']>120):
        raise ValueError('教学接续准备页原链不符或已消费。')
    _fresh_pair(r,'team',observations);targets=[];available=None
    for f in observations:
        saved=r.frame;r.frame=f
        try:matches=r.title_matches(f)
        finally:r.frame=saved
        control=team_entry_control(f)
        costs=[w for w in f.words if re.fullmatch(r'\d{1,6}\s*/\s*\d{1,6}',w['text']) and 1180<w['x']<1340 and 775<w['y']<880 and w['score']>=.98]
        if not matches or owned_hero_selector_visible(f) or control['kind']!='single_task' or len(costs)!=1:
            raise ValueError('原关标题、单次入口或当前费用未完整核实。')
        required,available=map(int,re.findall(r'\d+',costs[0]['text']))
        if required!=original['cost'] or available<max(required,original['stamina_before']):
            raise ValueError('当前费用改变、体力不足或原无扣费上下文不符。')
        targets.append(control['target'])
    if max(abs(targets[0][k]-targets[1][k]) for k in ('x','y'))>8:raise ValueError('入场目标变化。')
    record.update(status='reserved_entry',entry_reserved_at=time.time(),entry_evidence=r.evidence('tutorial-handoff-entry-'+key),stamina_before=available)
    active=copy.deepcopy(original);active.update(tutorial_handoff_id=record['id'],start_epoch=time.time(),original_start_epoch=original['start_epoch'],started_at=__import__('runner').now())
    r.s['active']=active;r.save()  # consumes once BEFORE input; all errors stay consumed
    r.action('教学配置故障修复后首次实际入场（保留原sent）',targets[-1])
    record.update(status='sent',sent_at=time.time());r.ticket=None;r.save();return record


def begin_live_configuration(r,permit):
    """Reviewed current team UI intercepted a sent start; configure, do NOT enter."""
    from runner import classify
    from tutorial_core import guided_team_slot_plan
    key=permit.get('key');chain=source_chain(r.s,key)
    if (chain['archives'] or r.s.get('active')!=chain['original'] or classify(r.frame) not in ('team','new_player_tutorial')
        or not guided_team_slot_plan(r.frame)
        or not permit.get('id') or not permit.get('user_instruction') or not permit.get('source_evidence_sha256')
        or permit.get('source_state_sha256')!=state_digest(r.s) or permit.get('source_chain_sha256')!=state_digest(chain)
        or any(row.get('key')==key for row in r.s.get('tutorial_entry_handoffs',[]))):
        raise ValueError('当前队伍截获来源不完整；不配置或重开。')
    record=copy.deepcopy(permit);record.update(status='configuring',at=time.time(),
        map_ticket=dict(chain['original'],phase='map',verified_epoch=time.time()),evidence=r.evidence('live-team-interception-'+key))
    r.s.setdefault('tutorial_entry_handoffs',[]).append(record);r.save();return record


def finish_live_configuration(r,record,observations):
    """Same original active, complete setup and current team: one first real start."""
    if record.get('status')!='configuring' or r.s.get('active')!=source_chain(r.s,record['key'])['original']:
        raise ValueError('原配置与未实际开战链改变。')
    setup=r.s.get('team_config') or {}
    if setup.get('phase')!='completed' or setup.get('stage_key')!=record['key'] or not setup.get('id') or (setup.get('selector_close') or {}).get('status')!='sent':raise ValueError('英雄配置未独立核实。')
    original_active=copy.deepcopy(r.s['active'])
    record['original_active']=original_active
    # Preserve the original full active as an immutable source snapshot in the
    # handoff, not as an invented failure/archive. enter_handoff consumes intent.
    record['status']='open_sent';record['open_sent_at']=time.time();r.ticket=record['map_ticket']
    enter_handoff(r,record,observations,live_original=original_active)

def reopen_after_configuration(r,record,observations):
    """Android Back left preparation after placement; finish original UI flow."""
    from runner import mainline_map_control
    key=record['key'];chain=source_chain(r.s,key)
    if (record.get('status')!='configuring' or record.get('source_chain_sha256')!=state_digest(chain)
        or r.s.get('active')!=chain['original'] or record.get('post_configuration_open')
        or (r.s.get('team_config') or {}).get('phase')!='completed'):
        raise ValueError('配置完成后的原链接续不符或已经发送。')
    _fresh_pair(r,'map',observations);targets=[]
    for f in observations:
        d,_,proof=r.map_ticket(f);c=mainline_map_control(f)
        if not d or d['key']!=key or d.get('locked') or d.get('clear_badge') or proof!='未通关蓝色当前节点' or not c or c['kind']!='battle' or c['target']['score']<.98:
            raise ValueError('未核实原未完成关卡的准备页控件。')
        targets.append(c['target'])
    if max(abs(targets[0][k]-targets[1][k]) for k in ('x','y'))>8:raise ValueError('准备控件变化。')
    step=dict(status='reserved',at=time.time(),evidence=r.evidence('configured-return-to-preparation-'+key),target=targets[-1])
    record['post_configuration_open']=step;r.save()
    r.action('免费配置完成返回地图后，接续原关准备页（不是新开战）',targets[-1])
    step.update(status='sent',sent_at=time.time());r.save();return step
