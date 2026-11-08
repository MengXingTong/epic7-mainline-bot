"""Mainline entry acceptance: a positive capacity rejection is not a battle.

A sent or missing response NEVER permits another paid message. Only a complete
pre-entry capacity refusal, tied to one unaccepted source, can continue after a
new user run. Original attempts, dispatches and archives are immutable.
"""
import copy,hashlib,re,time,uuid
from entry_journal import attempt_digest
from story_reopen import state_digest


def identity(a,b):
    return all(a.get(k)==b.get(k) for k in ('key','episode','chapter','chapter_suffix','stage','name','cost'))


def live_binding(r):
    from story_open_ack import binding
    value=binding(r)
    if value['client']=='mumu':value['game_pid']=r.adb('shell','pidof',r.cfg['package']).decode().strip()
    return value


def evidence(r,tag):
    import runner
    f=r.frame;image=r.evidence(tag);name='entry-response-'+uuid.uuid4().hex+'.json'
    value=dict(captured_at=f.at,raw_size=list(f.raw_size),words=copy.deepcopy(f.words),image=image,
               image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest())
    runner.atomic_json(runner.ROOT/'evidence'/name,value)
    return dict(image=image,observation='evidence/'+name,observation_sha256=state_digest(value))


def modal(f):
    """Observe only: full native capacity modal, never a reason to click it."""
    def one(pattern,area):
        x1,y1,x2,y2=area
        rows=[w for w in f.words if re.fullmatch(pattern,w['text']) and w['score']>=.98
              and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        return rows[0] if len(rows)==1 else None
    if any(re.fullmatch(r'确认|确定|购买|兑换|复活|重新挑战',w['text']) for w in f.words):return None
    title=one(r'背包空间不足',(600,220,1000,330))
    body=one(r'(英雄|装备|神器)(背包)?已满[。.]?',(500,370,1100,490))
    instruction=one(r'请整理或扩[充張张](英雄|装备|神器)背包后再重试[。.]?',(400,400,1200,530))
    buttons=[one(t,area) for t,area in [('取消',(350,550,650,690)),('整理',(650,550,950,690)),('扩充',(950,550,1250,690))]]
    if not title or not body or not instruction or not all(buttons):return None
    subject=re.match(r'英雄|装备|神器',body['text'])[0]
    if subject not in instruction['text']:return None
    return dict(kind='complete_capacity_modal',subject=subject,title=title['text'],body=body['text'],instruction=instruction['text'])


def original(r,key):
    a=r.s.get('attempted',{}).get(key);rows=r.s.get('entry_dispatches',{}).get(key,[])
    if (not a or key in r.s.get('completed',{}) or r.s.get('terminal') or a.get('entry_kind')=='story_only'
        or a.get('outcome') in ('defeat','failed','unknown')
        or any(v.get('outcome')=='defeat' and v.get('stage')==key for v in r.s.get('stage_outcomes',[]))
        or not 0<a.get('cost',0)<=100 or len(rows)!=1 or rows[0].get('status')!='sent'
        or rows[0].get('entry')!=a or rows[0].get('original_sha256')!=attempt_digest(a)):
        raise ValueError('入场响应原唯一sent/资源/完成状态不符；不接续。')
    return a


def pending_source(r):
    a=r.s.get('active') or {};key=a.get('key')
    if not key or any(a.get(k) for k in ('battle_seen','story_seen','victory_seen','settlement_observed','playback_observed_at')):return None
    try:o=original(r,key)
    except ValueError:return None
    if not identity(a,o):return None
    fid=a.get('entry_preflight_flow')
    if fid:
        flow=r.s.get('entry_preflight_flows',{}).get(fid,{})
        sends=flow.get('sends',[])
        if flow.get('phase')!='submitted' or not sends or sends[-1].get('status')!='sent':return None
        return dict(id=sends[-1]['id'],kind='flow_send',flow_id=fid,key=key,run_id=sends[-1]['run_id'],sent_at=sends[-1]['finished_at'])
    hid=a.get('tutorial_handoff_id')
    if hid:
        records=[v for v in r.s.get('tutorial_entry_handoffs',[]) if v.get('id')==hid and v.get('key')==key and v.get('status')=='sent']
        if len(records)!=1:return None
        h=records[0];return dict(id='handoff:'+hid,kind='tutorial_handoff',key=key,run_id=h['run_id'],sent_at=h['sent_at'],source_sha256=state_digest(h))
    d=r.s['entry_dispatches'][key][0];p=r.s.get('entry_preparations',{}).get(d['id'],{})
    if p.get('phase')!='sent' or p.get('run_id')!=getattr(r,'run_id',None):return None
    return dict(id='dispatch:'+d['id'],kind='dispatch',key=key,run_id=p['run_id'],sent_at=d['finished_at'],source_sha256=state_digest(d))


def create_rejection(r,source,proof,proof_evidence,*,binding=None):
    o=original(r,source['key'])
    if source['id'] in r.s.get('entry_acceptances',{}):raise ValueError('原发送已有实际接受证据，不能按预检拒绝接续。')
    flows=r.s.setdefault('entry_preflight_flows',{})
    flow=flows.get(source.get('flow_id'))
    if flow is None:
        if any(v.get('key')==o['key'] for v in flows.values()):raise ValueError('已有同关响应流程，不重复导入拒绝许可。')
        fid=uuid.uuid4().hex
        flow=dict(id=fid,key=o['key'],original_sha256=attempt_digest(o),binding=binding or live_binding(r),
                  raw_size=list(r.frame.raw_size),refusals=[],navigation=[],sends=[])
        flows[fid]=flow
    if any(v['source']['id']==source['id'] for v in flow['refusals']):return flow
    flow['refusals'].append(dict(id=uuid.uuid4().hex,source=copy.deepcopy(source),proof=copy.deepcopy(proof),
        evidence=copy.deepcopy(proof_evidence),run_id=source['run_id'],at=time.time()))
    flow.update(phase='rejected',continuation_run_id=None,map_ticket=None)
    r.save();return flow


def observe(r,f,mode):
    if not getattr(r,'run_id',None):return
    source=pending_source(r)
    if not source or source['run_id']!=r.run_id:return
    if mode=='capacity_stop':
        proof=modal(f)
        if proof and source['id'] not in r.s.get('entry_acceptances',{}):
            # A complete independent response, persisted before attention/input.
            create_rejection(r,source,proof,evidence(r,'entry-capacity-rejected'))
        return
    accepted=mode in ('story','victory','settlement')
    if mode in ('battle','new_player_tutorial'):
        from battle_auto_control import hud
        accepted=hud(f)
    if accepted and source['id'] not in r.s.setdefault('entry_acceptances',{}):
        proof=evidence(r,'entry-accepted-'+mode)
        r.s['entry_acceptances'][source['id']]=dict(source=source,mode=mode,captured_at=f.at,evidence=proof)
        if source.get('flow_id'):r.s['entry_preflight_flows'][source['flow_id']]['phase']='accepted'
        r.save()


def import_reviewed_rejection(r,permit):
    """Explicit maintenance only. Never infer an old refusal from attempted.

    A review may attest a historical tool-observed popup whose pixels weren't
    independently retained. Preserve that limitation; the attestation is not an
    invented image/OCR hash, not not_sent, and not a general retry permission.
    """
    o=original(r,permit.get('key'));source=permit.get('source') or {}
    if (not permit.get('id') or not permit.get('user_instruction') or not permit.get('source_hashes')
        or permit.get('state_sha256')!=state_digest(r.s) or permit.get('original_sha256')!=attempt_digest(o)
        or source.get('kind')!='tutorial_handoff' or source.get('key')!=o['key'] or r.s.get('active')
        or permit.get('binding')!=live_binding(r)):
        raise ValueError('历史容量拒绝审查来源不符，未导入。')
    rows=[h for h in r.s.get('tutorial_entry_handoffs',[]) if 'handoff:'+h.get('id','')==source.get('id')]
    if len(rows)!=1 or rows[0].get('status')!='sent' or state_digest(rows[0])!=source.get('source_sha256'):
        raise ValueError('被拒绝的原接续发送不符，未导入。')
    from pathlib import Path
    for path,expected in permit['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:raise ValueError('审查来源文件已变化。')
    flow=create_rejection(r,source,dict(kind='reviewed_legacy_capacity_rejection',permit=copy.deepcopy(permit),
        subject='英雄',original_popup_pixels_retained=False),dict(review_id=permit['id']),binding=permit['binding'])
    return flow


def active_context(r):
    a=r.s.get('active') or {};flow=r.s.get('entry_preflight_flows',{}).get(a.get('entry_preflight_flow'))
    if not flow or flow.get('phase') not in ('submitted','accepted') or not flow.get('sends'):return None
    last=flow['sends'][-1]
    try:o=original(r,flow['key'])
    except ValueError:return None
    if last.get('status')!='sent' or last.get('run_id')!=r.run_id or not identity(a,o):return None
    return dict(key=a['key'],scope='verified_preflight_continuation',entry_key=a['key'],original_sha256=attempt_digest(o))


def wait(r,reason):
    r.s['reason']=reason;return True,.25


def _send(r,flow,kind,target,*,entry=False):
    if not 0<=time.time()-r.frame.at<=3:return wait(r,'当前控件已过期；只重新观察，不复用旧控件。')
    book=flow['sends'] if entry else flow['navigation']
    if not entry:
        previous=[v for v in book if v['kind']==kind and v['run_id']==r.run_id]
        if previous:
            last=previous[-1]
            if last['status'] not in ('sent','not_sent') or len(previous)>=2 or r.frame.at<=last['finished_at']+4:
                return wait(r,'等待已发送免费导航的游戏响应；当前帧不重复发送。')
    message=dict(id=uuid.uuid4().hex,kind=kind,run_id=r.run_id,status='reserved',at=time.time(),
        captured_at=r.frame.at,target=copy.deepcopy(target),evidence=evidence(r,'preflight-'+kind))
    book.append(message)
    if entry:
        o=original(r,flow['key']);a=copy.deepcopy(o)
        a.update(entry_preflight_flow=flow['id'],entry_response_send=message['id'])
        r.s['active']=a;flow['phase']='invoking'
    r.save() # consumed BEFORE invocation; no replay on any failure/unknown.
    from pc_backend import FrameExpired,TapNotSent
    try:
        if time.time()-r.frame.at>5:
            raise FrameExpired('本周期控件留证已过期；意图已消费，不发送。')
        result=r.action('接续容量预检拒绝后的首次入场（保留原sent）' if entry else kind,target)
        message['status']='not_sent' if result is False else 'sent'
    except (FrameExpired,TapNotSent) as exc:
        message.update(status='not_sent',reason=str(exc))
    except BaseException:
        message.update(status='unknown',finished_at=time.time());r.save();raise
    message['finished_at']=time.time()
    if entry:flow['phase']='submitted' if message['status']=='sent' else 'unresolved'
    r.save();return True,.25


def step(r,f,mode):
    if not getattr(r,'run_id',None):return None
    flows=r.s.get('entry_preflight_flows',{})
    pending=[v for v in flows.values() if v.get('phase') in ('rejected','navigating','invoking','submitted','unresolved')
             and v.get('key') not in r.s.get('completed',{})]
    if not pending:return None
    if len(pending)!=1:return wait(r,'存在多个容量响应链，先核对来源；不选择任意旧关。')
    flow=pending[0]
    context=r.s.get('active') or getattr(r,'ticket',None) or {}
    if context.get('key') and context['key']!=flow['key']:return None
    o=original(r,flow['key'])
    if flow['original_sha256']!=attempt_digest(o) or flow['binding']!=live_binding(r) or list(f.raw_size)!=flow['raw_size']:
        raise ValueError('容量接续目标、进程、几何或原记录改变；停止输入。')
    if flow['phase'] in ('invoking','submitted','unresolved'):
        if mode in ('map','support','team'):return wait(r,'等待这次入场的独立游戏响应；仅sent/未响应绝不重发耗资源入场。')
        return None
    refusal=flow['refusals'][-1]
    if r.run_id==refusal['run_id']:return wait(r,'容量处理后须由使用者新开始当前流程；本run不自动再次入场。')
    from runner import mainline_map_control,norm
    from story_core import team_entry_control
    if mode=='map':
        d,rows,proof=r.map_ticket(f);control=mainline_map_control(f)
        if not d or d['key']!=o['key']:return None
        if d.get('name_complete') is False or norm(d.get('name',''))!=norm(o['name']):return wait(r,'等待原关完整名称，不借同号节点接续。')
        if proof!='未通关蓝色当前节点' or d.get('locked') is not False or d.get('clear_badge'):return None
        following=next((v for v in rows if v['stage']==d['stage']+1),None)
        if following and following.get('locked') is not True:return None
        if not control or control['kind']!='battle' or control['target']['score']<.98:return None
        flow.update(phase='navigating',continuation_run_id=r.run_id,map_ticket=dict(d,phase='map',proof=proof,
            progress_before=dict(key=d['key'],next_locked=(following or {}).get('locked'))))
        r.ticket=copy.deepcopy(flow['map_ticket'])
        return _send(r,flow,'容量处理后接续原关准备页（免费导航）',control['target'])
    if mode not in ('support','team'):return None
    if flow.get('continuation_run_id')!=r.run_id or not flow.get('map_ticket'):
        return wait(r,'等待当前地图的原关完整身份；不从无地图链的队伍页发送入场。')
    r.ticket=copy.deepcopy(flow['map_ticket'])
    if not r.title_matches(f):return wait(r,'当前队伍页关名与原关不符；不发送。')
    if mode=='support':
        target=f.find(r'^选择队伍$',(1130,750,1599,899))
        if not target or target['score']<.98:return wait(r,'等待本帧完整选择队伍控件。')
        return _send(r,flow,'容量接续选择当前队伍（免费导航）',target)
    control=team_entry_control(f)
    costs=[w for w in f.words if re.fullmatch(r'\d{1,6}\s*/\s*\d{1,6}',w['text']) and w['score']>=.98
           and 1180<=w['x']<=1340 and 775<=w['y']<=880]
    targets=[w for w in f.words if w['text']=='进行任务' and w['score']>=.98 and 1300<=w['x']<=1599 and 770<=w['y']<=899]
    if control['kind']!='single_task' or len(costs)!=1 or len(targets)!=1:
        return wait(r,'等待当前原关完整队伍、单次入口及费用；不点教学或未知遮罩下的入口。')
    cost,stock=map(int,re.findall(r'\d+',costs[0]['text']))
    if cost!=o['cost'] or stock<cost:return wait(r,'当前费用变化或资源不足，未发送、未兑换。')
    flow['current_resources']=dict(cost=cost,available=stock,captured_at=f.at)
    return _send(r,flow,'entry',targets[0],entry=True)
