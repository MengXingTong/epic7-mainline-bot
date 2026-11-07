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
        or dispatch.get('entry')!=active or dispatch.get('original_sha256')!=attempt_digest(original)
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
            or control['kind']!=active.get('team_entry_mode') or control['kind'] in ('unknown','enable_auto')):
            raise EntryPreparationDeferred('原入场费用/库存/自动队伍控件尚未通过独立新帧核验；未发送。')
        return control['target'] if control['kind']=='single_task' else f.find('进行任务',(1300,750,1599,899))
    raise ValueError('未登记的首次入场操作，未发送。')


def dispatch_first_entry(r,dispatch,action,*,resume=False):
    import runner
    from story_open_ack import binding
    from pc_backend import TapNotSent
    active,original=_source(r,dispatch);book=r.s.setdefault('entry_preparations',{})
    preparation=book.get(dispatch.get('id'))
    if preparation is None:
        if resume:raise ValueError('缺少原首次入场准备回执，未发送。')
        preparation=dict(id=dispatch['id'],key=active['key'],original_sha256=dispatch['original_sha256'],
            run_id=getattr(r,'run_id',None),action=action,phase='prepared',binding=binding(r),
            raw_size=list(r.frame.raw_size),prepared_at=time.time())
        book[dispatch['id']]=preparation
        r.save()  # ALL large critical writes precede the last observation.
    if (preparation.get('phase')!='prepared' or preparation.get('run_id')!=getattr(r,'run_id',None)
        or preparation.get('action')!=action or preparation.get('original_sha256')!=dispatch['original_sha256']):
        raise ValueError('首次入场准备已消费或来源变化，不重复发送。')
    receipt=Path(runner.ROOT)/'evidence'/('entry-invocation-'+dispatch['id']+'.json')
    if receipt.exists():raise ValueError('首次入场已有调用意图或不明结果，不重复发送。')
    # Use the current cycle observation exactly once. No repeated capture/OCR.
    f=r.frame
    if binding(r)!=preparation['binding'] or list(f.raw_size)!=preparation['raw_size']:
        raise ValueError('首次入场的目标或几何变化，未发送。')
    target=_target(r,preparation)
    if target is None or not 0<=time.time()-f.at<=5:
        raise EntryPreparationDeferred('本周期观察已过期，保留未调用的准备计划，等待下一正常观察周期。')
    evidence=r.evidence('entry-final-target-'+dispatch['id']+'-'+str(time.time_ns()))
    invocation=dict(id=dispatch['id'],key=active['key'],action=action,run_id=getattr(r,'run_id',None),
        original_sha256=dispatch['original_sha256'],binding=preparation['binding'],captured_at=f.at,
        target=copy.deepcopy(target),evidence=evidence,image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest(),
        status='invoking',reserved_at=time.time())
    if not 0<=time.time()-f.at<=5:raise EntryPreparationDeferred('最终控件留证已过期，未创建调用意图。')
    runner.atomic_json(receipt,invocation)  # Small, consumed BEFORE any backend call.
    preparation.update(phase='invoking',invocation=str(receipt.relative_to(runner.ROOT)))
    r._prepared_entry_action=action
    try:
        r.action(action,target)
    except Exception as exc:
        status='not_sent' if isinstance(exc,TapNotSent) else 'unknown'
        invocation.update(status=status,finished_at=time.time(),reason=str(exc));runner.atomic_json(receipt,invocation)
        preparation.update(phase=status,reason=str(exc))
        if status=='not_sent':finish_dispatch(dispatch,status,str(exc))
        r.save()
        raise
    finally:
        r._prepared_entry_action=None
    invocation.update(status='sent',finished_at=time.time());runner.atomic_json(receipt,invocation)
    preparation.update(phase='sent',finished_at=invocation['finished_at'])
    finish_dispatch(dispatch,'sent');r.save()


def continue_prepared_entry(r,mode):
    active=r.s.get('active') or {};rows=r.s.get('entry_dispatches',{}).get(active.get('key'),[])
    if not rows:return None
    dispatch=rows[-1]
    preparation=r.s.get('entry_preparations',{}).get(dispatch.get('id'))
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
            receipt=Path(runner.ROOT)/'evidence'/('entry-invocation-'+dispatch['id']+'.json')
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
