"""One-use repair of a proven tutorial UI interception, never general battle retry.

Original sent/attempt/archives are immutable. A human continuation instruction
and an independently reviewed source manifest are required; none is generated
by the normal worker or from the mere existence of an attempted stage.
"""
from __future__ import annotations
import copy,time,re
from entry_journal import attempt_digest
from story_reopen import state_digest


def same_unstarted_source(candidate,original):
    """Passive entry-response diagnostics do not change an immutable entry.

    This is identity comparison, not evidence that input was intercepted. A
    reviewed, hash-bound permit is still required by every repair operation.
    Never discard the diagnostic or allow battle/result/input fact extensions.
    """
    if not isinstance(candidate,dict) or not original.keys()<=candidate.keys() or any(candidate[k]!=v for k,v in original.items()):return False
    extra=set(candidate)-set(original)
    if not extra:return True
    if extra!={'result_observation'}:return False
    observation=candidate['result_observation']
    return (isinstance(observation,dict) and bool(observation.get('run_id'))
            and bool(observation.get('diagnostics')) and
            all(isinstance(v,dict) and v.get('code')=='entry_response' for v in observation['diagnostics']))


def source_chain(state,key):
    original=state.get('attempted',{}).get(key)
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    archives=[r for r in state.get('unresolved_entries',[]) if r.get('entry',{}).get('key')==key]
    if (not original or state.get('terminal') or key in state.get('completed',{}) or len(dispatches)!=1 or len(archives)>1
        or dispatches[0].get('status')!='sent' or dispatches[0].get('entry')!=original
        or dispatches[0].get('original_sha256')!=attempt_digest(original) or (archives and not same_unstarted_source(archives[0].get('entry'),original)) or (not archives and not same_unstarted_source(state.get('active'),original))
        or original.get('entry_kind')=='story_only' or not 0<original.get('cost',0)<=100
        or any(original.get(k) for k in ('playback_observed_at','story_seen','victory_seen','battle_seen','defeat_seen'))):
        raise ValueError('教学接续原唯一sent/归档/未开战证据链不一致。')
    return dict(original=original,dispatches=dispatches,archives=archives)


def _fresh_pair(r,scene,observations):
    """Use the current mainline cycle; optional older observations grant nothing."""
    from runner import classify
    if len(observations) not in (1,2) or observations[-1] is not r.frame:raise ValueError('需要本周期当前帧。')
    b=observations[-1]
    if (not 0<=time.time()-b.at<=3 or any(f.raw_size!=b.raw_size or classify(f)!=scene for f in observations)
        or (len(observations)==2 and not 0<b.at-observations[0].at<=5)):
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
    if max(abs(targets[0][k]-t[k]) for t in targets for k in ('x','y'))>8:raise ValueError('准备战斗目标移动。')
    record=copy.deepcopy(permit);record.update(status='reserved_open',at=time.time(),map_ticket=dict(ticket,phase='map'),map_evidence=r.evidence('tutorial-handoff-map-'+key))
    r.s.setdefault('tutorial_entry_handoffs',[]).append(record)
    r.ticket=dict(ticket,phase='map');r.save()
    r.action('修复教学配置截获：接续原关准备页（不是开战）',targets[-1])
    record.update(status='open_sent',open_sent_at=time.time());r.save();return record


def same_live_mumu_source(r,record):
    """Long free navigation is not expiry of a reviewed first-entry permit.

    Rebind its immutable source request, run, process and geometry. This never
    extends the current frame TTL or permits replay of a consumed entry intent.
    Old PC/unsourced callers keep their original 120-second bound.
    """
    import hashlib,json
    from pathlib import Path
    cfg=getattr(r,'cfg',{})
    if (cfg.get('backend')!='mumu_adb' or not record.get('game_pid')
        or not record.get('source_snapshot') or not record.get('source_snapshot_sha256')
        or not record.get('run_id') or record['run_id']!=getattr(r,'run_id',None)
        or record.get('raw_size')!=list(r.frame.raw_size)):return False
    try:
        raw=Path(record['source_snapshot']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['source_snapshot_sha256']:return False
        request=json.loads(raw)['request'];target=request['target']
        if (request.get('run_id')!=record['run_id'] or target.get('client')!='mumu'
            or target.get('serial')!=cfg.get('serial') or target.get('package')!=cfg.get('package')):return False
    except (OSError,ValueError,KeyError,TypeError):return False
    return r.adb('shell','pidof',cfg['package']).decode().strip()==record['game_pid']


def enter_handoff(r,record,observations,live_original=None):
    from story_core import team_entry_control
    from tutorial_core import owned_hero_selector_visible
    key=record['key'];chain=source_chain(r.s,key);original=chain['original']
    if (record not in r.s.get('tutorial_entry_handoffs',[]) or record.get('status')!='open_sent'
        or record.get('source_chain_sha256')!=state_digest(chain) or (r.s.get('active') is not None and (live_original!=chain['original'] or r.s.get('active')!=live_original))
        or not r.ticket or r.ticket.get('key')!=key
        or (time.time()-record['open_sent_at']>120 and not same_live_mumu_source(r,record))):
        raise ValueError('教学接续准备页原链不符或已消费。')
    _fresh_pair(r,'team',observations);targets=[];available=None
    for f in observations:
        saved=r.frame;r.frame=f
        try:matches=r.title_matches(f)
        finally:r.frame=saved
        control=team_entry_control(f)
        costs=[w for w in f.words if re.fullmatch(r'\d{1,6}\s*/\s*\d{1,6}',w['text']) and 1180<w['x']<1340 and 775<w['y']<880 and w['score']>=.98]
        entry_targets=[w for w in f.words if w['text']=='进行任务' and w['score']>=.98 and 1300<=w['x']<=1599 and 770<=w['y']<=899]
        if not matches or owned_hero_selector_visible(f) or control['kind'] not in ('single_task','auto_on') or len(costs)!=1 or len(entry_targets)!=1:
            raise ValueError('原关标题、单次入口或当前费用未完整核实。')
        required,available=map(int,re.findall(r'\d+',costs[0]['text']))
        if required!=original['cost'] or available<max(required,original['stamina_before']):
            raise ValueError('当前费用改变、体力不足或原无扣费上下文不符。')
        targets.append(entry_targets[0])
    if max(abs(targets[0][k]-t[k]) for t in targets for k in ('x','y'))>8:raise ValueError('入场目标变化。')
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
    if max(abs(targets[0][k]-t[k]) for t in targets for k in ('x','y'))>8:raise ValueError('准备控件变化。')
    step=dict(status='reserved',at=time.time(),evidence=r.evidence('configured-return-to-preparation-'+key),target=targets[-1])
    record['post_configuration_open']=step;r.save()
    r.action('免费配置完成返回地图后，接续原关准备页（不是新开战）',targets[-1])
    step.update(status='sent',sent_at=time.time());r.save();return step
