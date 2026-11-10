"""Durable FIRST-entry intent using the current cycle's single observation.

Reservation is not dispatch. Persist history and a one-shot invocation receipt
before input, without a second screenshot/OCR. If persistence ages this frame,
keep the uninvoked reservation for the next normal observation cycle. Never
replay an invoked/unknown receipt, adopt an old archive or invent not_sent.
"""
import copy
import hashlib
import json
import time
from pathlib import Path
from entry_journal import attempt_digest,finish_dispatch
from task_blockers import EntryPreparationDeferred


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _source(r,dispatch):
    active=r.s.get('active') or {};key=active.get('key');original=r.s.get('attempted',{}).get(key)
    rows=r.s.get('entry_dispatches',{}).get(key,[])
    if (not original or not rows or rows[-1] is not dispatch or dispatch.get('status')!='reserved'
        or dispatch.get('entry')!=original or {k:v for k,v in active.items() if k!='result_observation'}!=original
        or dispatch.get('original_sha256')!=attempt_digest(original)
        or any(row.get('status')!='not_sent' or row.get('original_sha256')!=attempt_digest(original) for row in rows[:-1])
        or any(active.get(k)!=original.get(k) for k in ('key','episode','chapter','chapter_suffix','stage','name','cost','entry_kind')) or key in r.s.get('completed',{})):
        raise ValueError('首次入场准备来源不一致，未发送。')
    return active,original


def _target(r,preparation):
    import runner
    f=r.frame;active=r.s['active'];action=preparation['action']
    if action=='观看故事（仅一次）':
        d,_,proof=r.map_ticket(f);control=runner.mainline_map_control(f)
        if (runner.classify(f)!='map' or not d or d['key']!=active['key']
            or proof!='未通关蓝色当前节点' or d.get('locked') is not False or d.get('clear_badge')
            or d.get('star_count') not in (None,0) or not control or control['kind']!='story_only'):
            raise EntryPreparationDeferred('原免费观看入口尚未在新帧完整核实；保留准备计划，仅观察。')
        return control['target']
    if action=='进行任务（仅一次入场）':
        import re
        from story_core import team_entry_control
        if runner.classify(f)!='team' or not r.title_matches(f):
            raise EntryPreparationDeferred('原队伍与关卡标题尚未在新帧完整核实；未发送入场。')
        word=f.find(r'\d+\s*/\s*\d+',(1180,775,1340,880))
        match=re.search(r'(\d+)\s*/\s*(\d+)',word['text']) if word and word['score']>=.90 else None
        control=team_entry_control(f)
        if (not match or int(match[1])!=active['cost'] or int(match[2])<int(match[1])
            or control['kind']!='single_task' or active.get('team_entry_mode') not in ('single_task','auto_on')):
            raise EntryPreparationDeferred('原入场费用/库存/普通单次任务控件尚未通过独立新帧核验；未发送。')
        return control['target']
    raise ValueError('未登记的首次入场操作，未发送。')


def _preparation(r,dispatch):
    """An explicitly audited legacy cancellation uses a separate NEW plan."""
    # Historical dispatches can predate preparation IDs. They grant no prepared
    # input, but must not block independent map facts or ordinary observation.
    if not isinstance(dispatch.get('id'),str) or not dispatch['id']:return None
    continuation=r.s.get('entry_preparation_continuations',{}).get(dispatch['id'])
    if continuation and continuation.get('run_id')==getattr(r,'run_id',None):
        original=r.s.get('entry_preparations',{}).get(dispatch['id'])
        source=Path(__import__('runner').ROOT)/'evidence'/('entry-invocation-'+dispatch['id']+'.json')
        if (digest(original)!=continuation['source_preparation_sha256']
            or continuation['original_sha256']!=dispatch['original_sha256']
            or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=continuation['source']['receipt_sha256']):
            raise ValueError('入场接续的原始准备来源变化，未发送。')
        return continuation['plan']
    return r.s.get('entry_preparations',{}).get(dispatch['id'])


def _invocation_path(r,dispatch,preparation):
    """Every cancelled pre-backend intent remains immutable; never reuse it."""
    import runner
    root=Path(runner.ROOT);cancelled=preparation.get('guard_cancellations',[])
    for index,row in enumerate(cancelled):
        name=preparation.get('receipt_prefix','entry-invocation-'+dispatch['id'])+(('-'+str(index)) if index else '')+'.json'
        path=root/'evidence'/name
        if (row.get('receipt')!=str(path.relative_to(root)) or not path.is_file()
            or row.get('sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()):
            raise ValueError('原入场发送前取消来源变化，未发送。')
        value=json.loads(path.read_text(encoding='utf8'))
        if (value.get('status')!='cancelled_before_backend' or value.get('input_boundary')!='not_called'
            or value.get('id')!=dispatch['id'] or value.get('run_id')!=getattr(r,'run_id',None)
            or value.get('original_sha256')!=dispatch['original_sha256']):
            raise ValueError('原入场不是可证明的调用前取消，不重复发送。')
    suffix=('-'+str(len(cancelled))) if cancelled else ''
    return root/'evidence'/(preparation.get('receipt_prefix','entry-invocation-'+dispatch['id'])+suffix+'.json')


def dispatch_first_entry(r,dispatch,action,*,resume=False):
    import runner
    from story_open_ack import binding
    from pc_backend import TapNotSent,FrameExpired
    active,original=_source(r,dispatch);book=r.s.setdefault('entry_preparations',{})
    preparation=_preparation(r,dispatch)
    if preparation is None:
        if resume:raise ValueError('缺少原首次入场准备回执，未发送。')
        preparation=dict(id=dispatch['id'],key=active['key'],original_sha256=dispatch['original_sha256'],
            run_id=getattr(r,'run_id',None),action=action,phase='prepared',binding=binding(r),
            raw_size=list(r.frame.raw_size),prepared_at=time.time())
        book[dispatch['id']]=preparation
        r.save()
    if (preparation.get('phase')!='prepared' or preparation.get('run_id')!=getattr(r,'run_id',None)
        or preparation.get('action')!=action or preparation.get('original_sha256')!=dispatch['original_sha256']):
        raise ValueError('首次入场准备已消费或来源变化，不重复发送。')
    receipt=_invocation_path(r,dispatch,preparation)
    if receipt.exists():raise ValueError('首次入场已有调用意图或不明结果，不重复发送。')
    f=r.frame
    if binding(r)!=preparation['binding'] or list(f.raw_size)!=preparation['raw_size']:
        raise ValueError('首次入场的目标或几何变化，未发送。')
    target=_target(r,preparation)
    if target is None or not 0<=time.time()-f.at<=5:
        raise EntryPreparationDeferred('本周期观察已过期，保留未调用的准备计划，等待下一正常观察周期。')
    evidence=r.evidence('entry-final-target-'+dispatch['id']+'-'+str(time.time_ns()))
    invocation=dict(id=dispatch['id'],key=active['key'],action=action,run_id=getattr(r,'run_id',None),
        original_sha256=dispatch['original_sha256'],binding=preparation['binding'],captured_at=f.at,
        target=copy.deepcopy(target),evidence=evidence,image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest())
    boundary=dict(called=False,written=False)
    def before_input(kind):
        if (kind!=action or r.frame is not f or binding(r)!=preparation['binding']
            or list(f.raw_size)!=preparation['raw_size']):
            raise ValueError('首次入场发送前目标或观察来源变化，未调用输入。')
        if not 0<=time.time()-f.at<=5:raise FrameExpired('首次入场调用前观察过期；未调用输入。')
        invocation.update(status='invoking',input_boundary='reserved',reserved_at=time.time())
        runner.atomic_json(receipt,invocation)
        boundary['written']=True
        preparation.update(phase='invoking',invocation=str(receipt.relative_to(runner.ROOT)))
        # The small intent write is included in TTL too. Its cancelled intent
        # gets its own terminal receipt; the next cycle creates a NEW one.
        if not 0<=time.time()-f.at<=5:raise FrameExpired('入场调用意图落盘后观察过期；未调用输入。')
        boundary['called']=True
    r._prepared_entry_action=action;r._entry_dispatch_boundary=before_input
    try:
        r.action(action,target)
        if not boundary['called']:raise ValueError('首次入场没有经过实际输入调用边界，不记录发送。')
    except Exception as exc:
        if not boundary['called']:
            if boundary['written']:
                invocation.update(status='cancelled_before_backend',input_boundary='not_called',finished_at=time.time(),reason=str(exc))
                runner.atomic_json(receipt,invocation)
                preparation.setdefault('guard_cancellations',[]).append(dict(receipt=str(receipt.relative_to(runner.ROOT)),
                    sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),reason=str(exc)))
            preparation.update(phase='prepared',last_guard_reason=str(exc));r.save()
            if isinstance(exc,FrameExpired):
                raise EntryPreparationDeferred('首次入场在输入调用前因观察过期取消；保留原入场链，下一正常周期重新核实，无需手动继续。') from exc
            raise
        status='not_sent' if isinstance(exc,TapNotSent) else 'unknown'
        invocation.update(status=status,input_boundary='called',finished_at=time.time(),reason=str(exc));runner.atomic_json(receipt,invocation)
        preparation.update(phase=status,reason=str(exc))
        if status=='not_sent':finish_dispatch(dispatch,status,str(exc))
        r.save();raise
    finally:
        r._prepared_entry_action=None;r._entry_dispatch_boundary=None
    invocation.update(status='sent',input_boundary='called',finished_at=time.time());runner.atomic_json(receipt,invocation)
    preparation.update(phase='sent',finished_at=invocation['finished_at'])
    finish_dispatch(dispatch,'sent')
    continuation=r.s.get('entry_preparation_continuations',{}).get(dispatch['id'])
    if continuation and continuation.get('plan') is preparation:continuation['phase']='submitted'
    r.save()


def continue_prepared_entry(r,mode):
    response=continue_guard_continuation(r,mode)
    if response is not None:return response
    active=r.s.get('active') or {};rows=r.s.get('entry_dispatches',{}).get(active.get('key'),[])
    if not rows:return None
    dispatch=rows[-1]
    preparation=_preparation(r,dispatch)
    if not preparation or preparation.get('phase')!='prepared':return None
    if preparation.get('run_id')!=getattr(r,'run_id',None):return None
    expected='map' if preparation['action']=='观看故事（仅一次）' else 'team'
    if mode!=expected:
        # A local uninvoked plan must not block already-running known gameplay
        # (for example the user started it). Never pretend our reservation sent
        # that entry or claim its result. Archive it, then let ordinary current-
        # screen story skipping / battle observation / result closing proceed.
        accepted={'story','skip_confirm','battle','victory','settlement','story_reward'}
        if mode in accepted and r.cfg.get('start_policy')=='current_screen':
            import runner
            from story_open_ack import binding
            from pc_backend import PcSafetyError
            _source(r,dispatch)
            if binding(r)!=preparation['binding'] or list(r.frame.raw_size)!=preparation['raw_size']:
                raise PcSafetyError('未调用入场计划的目标或几何已变化，未处理后继流程。')
            receipt=_invocation_path(r,dispatch,preparation)
            if receipt.exists():raise ValueError('原入场已有调用意图，不按外部推进归档。')
            evidence=r.evidence('prepared-external-progress-'+dispatch['id']+'-'+str(time.time_ns()))
            preparation.update(phase='external_progress',observed_scene=mode,observed_at=time.time(),evidence=evidence)
            r.archive_unresolved_active('本准备没有调用发送；当前已出现后继实际流程，保留原reserved和全部证据，不用旧计划认领结果')
            r.ticket=None;r.save()
            runner.event('entry_preparation_external_progress',stage=dispatch['entry']['key'],screen=mode,
                         original_dispatch_id=dispatch['id'],proof='no_invocation_receipt',evidence=evidence)
            return None
        raise EntryPreparationDeferred('原首次入场准备等待对应的已知页面；本帧不发送输入。')
    if expected=='team':r.ticket=copy.deepcopy(r.s['attempted'][active['key']])
    dispatch_first_entry(r,dispatch,preparation['action'],resume=True)
    r.ticket=None
    return True,.25


def register_guard_continuation(r,seed,proof):
    """Explicit maintenance ONLY: review this legacy pre-action FrameExpired.

    Never infer permission from reserved/unknown, a timeout, unchanged stamina,
    or ordinary Start. Preserve the old unknown receipt, plan and archives.
    """
    import ast,datetime
    import runner
    from story_open_ack import binding
    root=Path(runner.ROOT);key=seed.get('key');did=seed.get('dispatch_id')
    original=r.s.get('attempted',{}).get(key);rows=r.s.get('entry_dispatches',{}).get(key,[])
    old=r.s.get('entry_preparations',{}).get(did)
    receipt=root/'evidence'/('entry-invocation-'+str(did)+'.json')
    events=root/'events.jsonl'
    source=Path(seed.get('source_runner','')).resolve()
    local=(Path(runner.CODE_ROOT)/'.local').resolve()
    if (not proof.get('user_authorization') or not proof.get('nonce')
        or seed.get('run_id')!=getattr(r,'run_id',None) or seed.get('state_sha256')!=proof.get('state_sha256')
        or seed.get('events_sha256')!=hashlib.sha256(events.read_bytes()).hexdigest()
        or seed.get('events_sha256')!=proof.get('source_events_sha256')
        or not original or len(rows)!=1 or rows[0].get('id')!=did or rows[0].get('status')!='reserved'
        or rows[0].get('entry')!=original or rows[0].get('original_sha256')!=attempt_digest(original)
        or key in r.s.get('completed',{}) or r.s.get('terminal') or r.s.get('active')
        or not old or old.get('phase')!='unknown' or old.get('action')!='进行任务（仅一次入场）'
        or old.get('original_sha256')!=attempt_digest(original) or old.get('binding')!=binding(r)
        or old.get('reason')!='观察画面已过期；已取消操作。'
        or seed.get('preparation_sha256')!=digest(old) or not receipt.is_file()
        or seed.get('receipt_sha256')!=hashlib.sha256(receipt.read_bytes()).hexdigest()
        or old.get('invocation')!=str(receipt.relative_to(root))
        or local not in source.parents or not source.is_file()
        or seed.get('source_runner_sha256')!=hashlib.sha256(source.read_bytes()).hexdigest()
        or did in r.s.get('entry_preparation_continuations',{})):
        raise ValueError('旧入口缺少明确维护授权或完整调用前取消来源，不接续。')
    value=json.loads(receipt.read_text(encoding='utf8'))
    if (value.get('status')!='unknown' or value.get('id')!=did or value.get('key')!=key
        or value.get('action')!=old['action'] or value.get('run_id')!=old.get('run_id')
        or value.get('binding')!=old['binding'] or value.get('reason')!=old['reason']
        or value.get('original_sha256')!=attempt_digest(original)
        or not 0<=value['reserved_at']-value['captured_at']<=5
        or not 5<value['finished_at']-value['captured_at']<30):
        raise ValueError('旧调用取消时序或入口身份不符，不接续。')
    # Verify the exact old raising site: only read-only ensure_game and its
    # freshness guard precede it. A backend FrameExpired is NOT this proof.
    tree=ast.parse(source.read_text(encoding='utf8'))
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_action')
    if (ast.unparse(method.body[0])!='self.ensure_game()'
        or not isinstance(method.body[1],ast.If)
        or ast.unparse(method.body[1].test)!='time.time() - self.frame.at > 5'
        or not any(isinstance(n,ast.Raise) and ast.unparse(n.exc)=="FrameExpired('观察画面已过期；已取消操作。')" for n in ast.walk(method.body[1]))):
        raise ValueError('原始代码不证明在输入调用前取消，不接续。')
    archived=[x for x in r.s.get('unresolved_entries',[]) if x.get('entry',{}).get('key')==key]
    if (len(archived)!=1 or {k:v for k,v in archived[0]['entry'].items() if k!='result_observation'}!=original
        or seed.get('archive_sha256')!=digest(archived[0])
        or did in r.s.get('entry_acceptances',{})):
        raise ValueError('旧入口归档或实际接受记录不符，不接续。')
    records=[json.loads(line) for line in events.read_text(encoding='utf8').splitlines() if line.strip()]
    for row in records:
        at=datetime.datetime.fromisoformat(row['time']).timestamp()
        if at<int(value['reserved_at']):continue
        if (row.get('kind') in ('action','back','drag')
            or row.get('kind')=='screen' and row.get('screen') not in ('team','support','map')):
            raise ValueError('旧取消后出现输入或实际流程，不能按首次入场接续。')
    continuation=dict(id=proof['nonce'],run_id=r.run_id,key=key,dispatch_id=did,phase='revalidate_map',
        original_sha256=attempt_digest(original),source_preparation_sha256=digest(old),
        source=copy.deepcopy(seed),user_authorization=proof['user_authorization'],
        original_preparation=copy.deepcopy(old),original_receipt=value,original_dispatch=copy.deepcopy(rows[0]),
        registered_at=time.time(),navigation=[],plan=dict(id=did,key=key,run_id=r.run_id,action=old['action'],
            phase='prepared',binding=copy.deepcopy(old['binding']),raw_size=copy.deepcopy(old['raw_size']),
            original_sha256=old['original_sha256'],prepared_at=time.time(),receipt_prefix='entry-continuation-'+proof['nonce']))
    r.s.setdefault('entry_preparation_continuations',{})[did]=continuation
    r.save()


def continue_guard_continuation(r,mode):
    """Revalidate the map before ONE first actual entry on an audited chain."""
    import re
    import runner
    from story_core import team_entry_control
    from story_open_ack import binding
    pending=[v for v in r.s.get('entry_preparation_continuations',{}).values()
             if v.get('run_id')==getattr(r,'run_id',None) and v.get('phase') in ('revalidate_map','navigating')]
    if not pending:return None
    if len(pending)!=1:raise ValueError('不唯一的旧入口接续，不发送。')
    c=pending[0];f=r.frame;key=c['key'];plan=c['plan']
    if (binding(r)!=plan['binding'] or list(f.raw_size)!=plan['raw_size']):
        raise ValueError('接续目标或几何变化，不发送。')
    original=r.s['attempted'][key];rows=r.s['entry_dispatches'][key]
    if (len(rows)!=1 or rows[0]!=c['original_dispatch'] or key in r.s.get('completed',{})
        or digest(r.s['entry_preparations'][c['dispatch_id']])!=c['source_preparation_sha256']):
        raise ValueError('原始入口记录变化，不发送。')
    def wait(reason):r.s['reason']=reason;r.save_observation();return True,.25
    if not 0<=time.time()-f.at<=5:return wait('接续当前观察过期，零输入等待新帧。')
    ticket=c.get('map_ticket') or {}
    fresh=ticket.get('key')==key and 0<=time.time()-ticket.get('verified_epoch',0)<=120
    if mode=='map':
        d,maprows,proof=r.map_ticket(f);control=runner.mainline_map_control(f)
        following=next((v for v in maprows if d and v['stage']==d['stage']+1),None)
        if (not d or d.get('key')!=key or proof!='未通关蓝色当前节点' or d.get('locked') is not False
            or d.get('clear_badge') or d.get('star_count') not in (None,0)
            or not following or following.get('locked') is not True
            or not control or control['kind']!='battle' or control['target']['score']<.98):
            return wait('等待原关未完成及后继仍锁定的当前地图事实；不猜测完成、不重复入场。')
        c.update(phase='navigating',map_ticket=dict(d,phase='map',proof=proof,
            evidence=r.evidence('guard-continuation-map'),progress_before=dict(key=key,next_locked=True)))
        r.ticket=copy.deepcopy(c['map_ticket']);target=control['target'];label='入场前取消后重新核实原关准备页'
    elif mode in ('team','support'):
        if not fresh:
            # Do not bypass the map chain from a team page. Only the fully
            # recognized preparation layout may receive a native Back.
            if mode=='team' and team_entry_control(f)['kind']!='single_task':return wait('等待完整队伍页，未返回或入场。')
            if mode=='support' and not (f.find('选择辅助英雄') and f.find('选择队伍',(1130,750,1599,899))):return wait('等待完整辅助页，未返回或入场。')
            target=None;label='入场前取消后从准备页返回地图重验'
        else:
            r.ticket=copy.deepcopy(ticket)
            if not r.title_matches(f):return wait('接续准备页关名尚未匹配原地图，零输入观察。')
            if mode=='support':
                target=f.find(r'^选择队伍$',(1130,750,1599,899));label='入场前取消后选择原关队伍'
                if not target or target['score']<.98:return wait('等待当前选择队伍控件。')
            else:
                # The separate new plan consumes no new entry reservation and
                # leaves the legacy unknown receipt and archive byte-for-byte.
                r.s['active']=copy.deepcopy(original);c['phase']='dispatching';r.save()
                dispatch_first_entry(r,rows[0],plan['action'],resume=True)
                c['phase']='submitted';r.ticket=None;r.save();return True,.25
    else:
        if mode in ('story','battle','victory','settlement','story_reward'):
            c.update(phase='external_progress',observed_scene=mode,evidence=r.evidence('guard-continuation-external-progress'))
            r.save()
        return None  # Known free notices retain their ordinary priority.
    prior=[v for v in c['navigation'] if v['label']==label and v['scene']==mode]
    if prior and (prior[-1]['status'] not in ('sent','guard_cancelled')
                  or sum(v['status']=='sent' for v in prior)>=3
                  or prior[-1]['status']=='sent' and f.at<=prior[-1]['finished_at']+3):
        return wait('等待已发送免费导航的独立画面响应，未重复消耗入场。')
    nav=dict(label=label,scene=mode,status='reserved',captured_at=f.at,evidence=r.evidence('guard-continuation-navigation'))
    c['navigation'].append(nav);r.save()
    # Save can age this frame. No input has been called at this point.
    if not 0<=time.time()-f.at<=5:
        nav.update(status='guard_cancelled',finished_at=time.time());r.save()
        return wait('免费导航落盘后观察过期，等待正常新帧。')
    try:
        if target is None:r.back(label)
        else:r.action(label,target)
    except Exception as exc:
        from pc_backend import NavigationFrameExpired
        if isinstance(exc,NavigationFrameExpired):
            nav.update(status='guard_cancelled',finished_at=time.time());r.save()
            return wait('免费导航在输入前过期，重新观察当前页，不重用原导航意图。')
        nav.update(status='unknown',finished_at=time.time());r.save();raise
    nav.update(status='sent',finished_at=time.time());r.save();return True,.25
