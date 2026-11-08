"""Recover missed, independently saved arena victories; never resend an entry.

A new count remains a new count. Historical wins belong only to their original
run, and an observed list return is not manufactured into a sent close message.
"""
from __future__ import annotations
import copy,hashlib,json,re,time,uuid
from dataclasses import asdict
from pathlib import Path
from PIL import Image
from assistant_config import read_json,atomic_json
from assistant_instances import homes,history_key
from arena_core import classify,norm
from arena_journal import ArenaJournal,binding


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _source_scope(root,request,run_id,settled,*,navigation=False):
    if not re.fullmatch(r'[0-9a-f]{32}',run_id):raise ValueError('原竞技场任务编号无效。')
    base=request.get('instance_base',request.get('home'))
    if not base:raise ValueError('缺少原竞技场任务来源；不新开。')
    folders=[home/'runs'/run_id for _,home in homes(base) if (home/'runs'/run_id/'request.json').is_file()]
    if len(folders)!=1:raise ValueError('原竞技场任务来源不唯一；不新开。')
    folder=folders[0].resolve();source=read_json(folder/'request.json');status=read_json(folder/'status.json');control=read_json(folder/'control.json')
    target=source.get('target',{});current=request['target']
    stopped=status.get('mode')=='stopped' and control.get('action')=='stop'
    closed_failure=(status.get('mode')=='blocked' and control.get('action') in ('run','stop')
                    and ((settled and status.get('scene')=='arena_result')
                         or (navigation and status.get('scene') in ('arena_npc','arena_team'))))
    if (source.get('run_id')!=run_id or Path(source.get('run_dir','')).resolve()!=folder
        or Path(source.get('home','')).resolve()!=folder.parent.parent
        or source.get('settings',{}).get('task')!='arena'
        or Path(source['settings'].get('data_dir','')).resolve()!=Path(root).resolve()
        or history_key(target)!=history_key(current)
        or (target.get('package') if target.get('client')=='mumu' else target.get('exe'))
           !=(current.get('package') if current.get('client')=='mumu' else current.get('exe'))
        or request.get('settings',{}).get('task')!='arena'
        or status.get('run_id')!=run_id or not (stopped or closed_failure)
        or control.get('run_id')!=run_id
        or not source.get('requested_at',0)<status.get('updated_at',0)<request.get('requested_at',0)):
        raise ValueError('原竞技场请求/目标/停止来源不一致；不认领其他结果。')
    log=folder/'worker.log';events=[]
    for line in log.read_text(encoding='utf-8').splitlines():
        try:events.append(json.loads(line))
        except json.JSONDecodeError:continue
    files=[folder/name for name in ('request.json','status.json','control.json','worker.log')]
    return dict(request=source,status=status,events=events,hashes={str(p):digest(p) for p in files})


def _pair(arena,evidence):
    paths=[]
    for field in ('image','metadata'):
        path=(arena/evidence[field]).resolve()
        if not path.is_relative_to(arena.resolve()) or not path.is_file() or digest(path)!=evidence[field+'_sha256']:
            raise ValueError('原竞技场证据路径或哈希已变化；不补记。')
        paths.append(path)
    meta=read_json(paths[1])
    if meta.get('captured_at')!=evidence.get('captured_at'):raise ValueError('原竞技场证据时点不一致。')
    return paths[0],meta


def prepare(root,request,ocr):
    """Read-only plan: source logs link the old unknown-frame asset to its run."""
    arena=Path(root)/'arena';path=arena/'state.json'
    if not path.exists():return None
    state=read_json(path);old=state.get('active');run_id=request['run_id']
    owners={v['pending_result']:name for name,v in state.get('runs',{}).items() if name!=run_id and v.get('pending_result')}
    if old and old.get('run_id')!=run_id:owners[old['key']]=old['run_id']
    if not owners:return prepare_navigation(root,request,state)
    if len(owners)!=1:raise ValueError('存在多个未核实竞技场结果；不合并或新开。')
    key,prior_id=next(iter(owners.items()))
    prior_entry=old if old and old.get('key')==key else state.get('completed',{}).get(key,{})
    controller=prior_entry.get('controller_run_id',prior_id)
    if controller!=prior_id and not any(v.get('phase')=='reconciled' and v.get('resume_original_quota')
        and v.get('original_run_id')==prior_id and v.get('new_request_run_id')==controller for v in state.get('reconciliations',[])):
        raise ValueError('原竞技场批次缺少执行者接续来源；不猜测任务身份。')
    scope=_source_scope(root,request,controller,key in state.get('completed',{}))
    j=ArenaJournal(root,prior_id,state['runs'][prior_id]['requested'],persist=False)
    if int(scope['request']['settings'].get('arena_count',0))!=j.run['requested']:
        raise ValueError('原竞技场目标次数与原请求不一致；不重建或修改目标。')
    entry=j.active or j.state['completed'].get(key)
    if not entry or entry.get('key')!=key or entry.get('run_id')!=prior_id or not entry.get('battle_evidence'):
        raise ValueError('原竞技场缺少独立战斗证据；不猜测胜利、不重发。')
    original=j.state['attempted'][key]
    if any(entry.get(k)!=v for k,v in original.items()):
        raise ValueError('原竞技场active/结算与不可改写入场不一致。')
    dispatches=j.state['entry_dispatches'][key]
    if len(dispatches)!=1 or dispatches[0].get('status')!='sent':raise ValueError('原竞技场不是唯一已发送入场；不新开。')
    for field,scene in (('entry_evidence','arena_team'),('battle_evidence','arena_battle')):
        _,meta=_pair(arena,entry[field]);reading=meta.get('reading',{})
        if meta.get('binding')!=entry['binding'] or reading.get('scene')!=scene or norm(reading.get('opponent',''))!=norm(entry['opponent']):
            raise ValueError('原入场/战斗证据不属于此对手或目标。')
        if scene=='arena_team' and (reading.get('cost')!=1 or reading.get('stock')!=entry.get('stock_before') or entry.get('cost')!=1):
            raise ValueError('原竞技场费用/库存来源不一致。')
    if any(a.get('at',0)>entry['at'] and (a.get('key')!=key or a['kind'] not in ('entry','entry_confirm','auto')) for a in j.state['actions'] if a.get('run_id')==prior_id):
        # An existing completed result may already have a close intention. It
        # stays intact; only its own exact result, not an unknown asset, is used.
        if j.active:raise ValueError('原入场后存在其他输入链；不认领未知结果。')
    candidates=[]
    if entry.get('result_evidence'):
        saved=entry['result_evidence'];reports=[v for v in j.state.get('reconciliations',[]) if v.get('key')==key and v.get('result_evidence')==saved]
        candidates=[reports[-1]['source_evidence'] if reports else saved]
    else:
        notices=[e for e in scope['events'] if e.get('kind')=='status' and e.get('mode')=='attention'
                 and e.get('attention_code')=='arena_unknown' and e.get('wins')==j.run['wins']
                 and e.get('arena_requested')==j.run['requested'] and entry['at']<e.get('updated_at',0)<=scope['status']['updated_at']]
        for meta_path in sorted((arena/'evidence').glob('*.json')):
            match=re.fullmatch(r'(\d{19})-[0-9a-f]{8}',meta_path.stem)
            if not match:continue
            at=int(match[1])/1e9
            if not any(0<=notice['updated_at']-at<=3 for notice in notices):continue
            meta=read_json(meta_path);image=meta_path.with_suffix('.png')
            if not image.is_file() or meta.get('reading',{}).get('scene')!='arena_unknown':continue
            candidates.append(dict(image=str(image.relative_to(arena)),metadata=str(meta_path.relative_to(arena)),
                image_sha256=digest(image),metadata_sha256=digest(meta_path),captured_at=meta.get('captured_at')))
    if len(candidates)>8:raise ValueError('原未知截图来源过多，无法唯一核对；不新开。')
    from arena_worker import read_observation
    for evidence in candidates:
        image,meta=_pair(arena,evidence);captured=meta.get('captured_at')
        if (meta.get('binding')!=entry['binding'] or not isinstance(captured,(int,float))
            or captured<=entry['battle_evidence']['captured_at']):continue
        match=re.fullmatch(r'(\d{19})-[0-9a-f]{8}',Path(evidence['image']).stem)
        if not match or not entry['at']<int(match[1])/1e9<=scope['status']['updated_at']:continue
        if any(e.get('attention_code')=='arena_defeat' and entry['at']<e.get('updated_at',0)<=int(match[1])/1e9 for e in scope['events']):
            raise ValueError('原入场存在明确战败事实；不按后来的结果恢复或重试。')
        with Image.open(image) as original:obs=read_observation(original.copy(),ocr,captured)
        r=classify(obs)
        if r.scene!='arena_result' or norm(r.opponent)!=norm(entry['opponent']):continue
        return dict(journal=j,journal_sha256=digest(path),key=key,scope=scope,source_evidence=evidence,
                    original_active=copy.deepcopy(j.active),reading=r,observation=obs,new_request=copy.deepcopy(request),prepared_at=time.time())
    raise ValueError('原竞技场没有可独立核实的完整胜利截图；保留未结算记录，不重发或新开。')


def prepare_navigation(root,request,state):
    """Continue an interrupted quota only when *every* old entry is settled.

    Unlike result recovery this cannot credit a win or adopt a battle. It only
    carries the quota across an ordinary pre-entry selection/transition fault.
    """
    actions=state.get('actions',[])
    if not actions:return None
    last=actions[-1];prior_id=last.get('run_id');run=state.get('runs',{}).get(prior_id,{})
    if (prior_id==request['run_id'] or not run or run.get('wins')==run.get('requested')
        or request['settings']['arena_count']!=run.get('requested')):return None
    controller=last.get('controller_run_id',prior_id)
    if controller!=prior_id and not any(v.get('phase')=='reconciled' and v.get('resume_original_quota')
        and v.get('original_run_id')==prior_id and v.get('new_request_run_id')==controller for v in state.get('reconciliations',[])):
        raise ValueError('原批次选人接续缺少执行者来源；不新开另一批。')
    scope=_source_scope(root,request,controller,False,navigation=True)
    # A deliberate stopped batch remains a deliberate new-start decision. This
    # automatic quota carry is specifically for a self-caused known-page fault.
    if scope['status'].get('mode')!='blocked':return None
    j=ArenaJournal(root,prior_id,run['requested'],persist=False)
    if (j.active or any(r.get('pending_result') for r in j.state['runs'].values())
        or scope['status'].get('wins')!=j.run['wins']
        or scope['status'].get('arena_requested')!=j.run['requested']
        or scope['request']['settings'].get('arena_count')!=j.run['requested']):
        raise ValueError('原次数/胜利/当前入场来源不一致；不按空active重开。')
    attempts={k:v for k,v in j.state['attempted'].items() if v.get('run_id')==prior_id}
    completed={k:v for k,v in j.state['completed'].items() if v.get('run_id')==prior_id}
    if attempts.keys()!=completed.keys() or len(completed)!=j.run['wins']:
        raise ValueError('原批次仍有未核实入场；不自动重试或重置次数。')
    sources=[]
    for key,entry in attempts.items():
        done=completed[key]
        if (any(done.get(k)!=v for k,v in entry.items())
            or j.state['entry_dispatches'][key][0]['status']!='sent'
            or not done.get('battle_evidence') or not done.get('result_evidence') or not done.get('close_evidence')):
            raise ValueError('原成功把数缺少完整入场/战斗/胜利/返回列表事实。')
        for field,scene in (('entry_evidence','arena_team'),('battle_evidence','arena_battle'),('result_evidence','arena_result'),('close_evidence','arena_npc')):
            sources.append(done[field]);_,meta=_pair(j.root,done[field]);r=meta.get('reading',{})
            if meta.get('binding')!=entry['binding'] or r.get('scene')!=scene:
                raise ValueError('原成功证据窗口或页面不符；不延续次数。')
            if field!='close_evidence' and r.get('opponent')!=entry['opponent']:
                raise ValueError('原成功证据对手不一致。')
        if not (done['entry_evidence']['captured_at']<done['battle_evidence']['captured_at']
                <done['result_evidence']['captured_at']<done['close_evidence']['captured_at']):
            raise ValueError('原成功证据不是独立后继帧。')
    own=[a for a in actions if a['run_id']==prior_id]
    boundary=max((i for i,a in enumerate(own) if a['kind']=='result_close'),default=-1)
    tail=own[boundary+1:]
    # A retained batch can already have a proven prior maintenance actor. Keep
    # its full history but validate the latest actor's contiguous input suffix
    # against that actor's own immutable request, not an older timestamp.
    first=next((i for i,a in enumerate(tail) if a.get('controller_run_id',prior_id)==controller),len(tail))
    tail=tail[first:]
    if not tail or any(a['kind'] not in ('navigate','select','challenge','return_to_npc')
        or a['status']!='sent' or a.get('controller_run_id',prior_id)!=controller
        or a['binding']!=last['binding'] or not scope['request']['requested_at']<a['at']<=scope['status']['updated_at'] for a in tail):
        raise ValueError('原故障不是唯一已知的免费选人导航链；不接续未知输入。')
    for a in tail:
        sources.append(a['evidence']);_,meta=_pair(j.root,a['evidence'])
        if meta.get('binding')!=a['binding'] or meta.get('reading')!=a['reading']:
            raise ValueError('原免费导航截图与发送来源不一致。')
    if any(e.get('attention_code') in ('arena_defeat','arena_resource','arena_opponent')
        and e.get('updated_at',0)>=tail[0]['at'] for e in scope['events']):
        raise ValueError('原导航后存在战败/资源/外来战斗事实；不自动继续。')
    return dict(mode='navigation',journal=j,journal_sha256=digest(j.path),scope=scope,
        navigation_ids=[a['id'] for a in tail],source_evidence=sources,binding=last['binding'],new_request=copy.deepcopy(request))


def apply_navigation(plan,snap,obs,reading,request):
    j=plan['journal']
    if (request!=plan['new_request'] or digest(j.path)!=plan['journal_sha256']
        or any(digest(p)!=h for p,h in plan['scope']['hashes'].items())):
        raise ValueError('选人接续的原请求/状态/证据已变化；不消费旧计划。')
    if (reading.scene not in ('arena_npc','arena_team') or not reading.target
        or reading.target.score is None or reading.target.score<.98
        or binding(snap.binding)!=plan['binding'] or not 0<=time.monotonic()-snap.captured_at<=5):
        raise ValueError('当前不是同窗口新鲜完整NPC列表/队伍页；不输入、不接续。')
    for evidence in plan['source_evidence']:_pair(j.root,evidence)
    # This records observation + actor provenance, never entry acceptance or win.
    evidence=j.evidence(snap,obs,reading)
    report=dict(id=uuid.uuid4().hex,phase='reconciled',kind='pre_entry_navigation',
        original_run_id=j.run_id,new_request_run_id=request['run_id'],resume_original_quota=True,
        old_run_wins=j.run['wins'],old_requested=j.run['requested'],source_journal_sha256=plan['journal_sha256'],
        source_files=plan['scope']['hashes'],navigation_ids=plan['navigation_ids'],current_evidence=evidence,
        at=time.time(),game_input_sent=False,completion_claimed=False)
    j.state.setdefault('reconciliations',[]).append(report);j.save()
    return report


def apply(plan,snap,obs,reading,request):
    """Persist real past completion + fresh list disappearance, with zero input."""
    if plan.get('mode')=='navigation':return apply_navigation(plan,snap,obs,reading,request)
    j=plan['journal'];entry=j.active or j.state['completed'][plan['key']]
    if request!=plan['new_request']:raise ValueError('竞技场新请求已变化；不使用旧恢复计划。')
    if digest(j.path)!=plan['journal_sha256'] or any(digest(p)!=h for p,h in plan['scope']['hashes'].items()):
        raise ValueError('竞技场恢复计划的来源已变化；未写入或输入。')
    if (reading.scene!='arena_npc' or not reading.target or reading.target.score is None or reading.target.score<.98
        or binding(snap.binding)!=entry['binding'] or not 0<=time.monotonic()-snap.captured_at<=5):
        raise ValueError('当前不是本目标的新鲜完整NPC列表；不推断结算已关闭。')
    _pair(j.root,plan['source_evidence'])
    result_evidence=copy.deepcopy(entry.get('result_evidence'))
    if result_evidence is None:
        directory=j.root/'recovery';directory.mkdir(exist_ok=True)
        path=directory/(uuid.uuid4().hex+'-historical-result.json')
        atomic_json(path,dict(source='historical_replay_not_live_input',captured_at=plan['source_evidence']['captured_at'],
            binding=entry['binding'],reading=asdict(plan['reading']),tokens=[asdict(t) for t in plan['observation'].tokens],
            visuals=sorted(plan['observation'].visuals),original=plan['source_evidence']))
        result_evidence=dict(plan['source_evidence'],metadata=str(path.relative_to(j.root)),metadata_sha256=digest(path))
    return_evidence=j.evidence(snap,obs,reading)
    report=dict(id=uuid.uuid4().hex,phase='verified',key=plan['key'],original_run_id=j.run_id,
        new_request_run_id=request['run_id'],new_request_count=request['settings']['arena_count'],
        old_run_wins=j.run['wins'],old_requested=j.run['requested'],
        resume_original_quota=(plan['scope']['status'].get('mode')=='blocked'
            and int(request['settings']['arena_count'])==j.run['requested']),
        source_journal_sha256=plan['journal_sha256'],
        source_files=plan['scope']['hashes'],source_evidence=plan['source_evidence'],result_evidence=result_evidence,
        return_evidence=return_evidence,original_active=plan['original_active'],at=time.time(),game_input_sent=False)
    j.state.setdefault('reconciliations',[]).append(report);j.save()
    if j.active:j.complete(result_evidence,snap.binding)
    j.acknowledge_reconciled_return(return_evidence,reading,snap.binding,report['id'])
    return report


def reconcile(root,request,ocr,capture,control):
    plan=prepare(root,request,ocr)
    if plan is None:return
    from assistant_worker import capture_fresh
    from arena_worker import read_observation
    snap=capture_fresh(capture,control);obs=read_observation(snap.image,ocr,snap.captured_at);reading=classify(obs)
    control.preview(snap.image)
    report=apply(plan,snap,obs,reading,request)
    if report['resume_original_quota']:
        control.log('已核实原竞技场流程与当前页面；继续原次数和胜利计数，不另开一批、不重发资源入场。')
        return plan['journal'].run_id
    control.log('原竞技场已按独立原图恢复胜利并核实当前返回列表；无补发、无伪造关闭，本次次数独立计数。')
