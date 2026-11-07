"""A sent free-story UI message is not proof of game acceptance or completion.

Only the still-current original run may resend this no-cost opening. Two fresh
positive map observations, its original sent chain and absence of any accepted
story/battle/input chain are required. Paid entries and archived runs never use
this policy. Every additional message is reserved durably and consumed once.
"""
from __future__ import annotations
import copy,hashlib,json,time,uuid
from dataclasses import asdict
from pathlib import Path
from entry_journal import attempt_digest

POLICY='free-story-open-ack-v1-20261106'
MAX_ADDITIONAL_MESSAGES=2
ACK_WAIT_SECONDS=4.
OPEN_ACTION='观看故事（仅一次）'
ACCEPTED_SCENES={'story','battle','victory','settlement','legacy_story_clear','legacy_story_exit','post_clear_exit'}
BLOCKED_SCENES={'defeat','resource_stop','capacity_stop','network_error','chat_panel','lobby','date_change_notice'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def binding(r):
    pc=getattr(r,'pc',None)
    if pc:
        window=pc.frame_window or pc.window
        if window is None:raise ValueError('免费观看入口缺少当前窗口绑定。')
        return dict(client='pc',window=asdict(window))
    cfg=r.cfg
    if not cfg.get('serial') or not cfg.get('package'):raise ValueError('免费观看入口缺少当前模拟器绑定。')
    return dict(client='mumu',serial=cfg['serial'],package=cfg['package'])


def source_chain(r):
    state=r.s;a=state.get('active') or {};key=a.get('key')
    original=state.get('attempted',{}).get(key)
    sends=state.get('entry_dispatches',{}).get(key,[])
    if (not key or state.get('terminal') or a.get('entry_kind')!='story_only' or a.get('cost')!=0
        or original is None or original.get('entry_kind')!='story_only' or original.get('cost')!=0
        or a.get('outcome') in ('defeat','failed','unknown') or original.get('outcome') in ('defeat','failed','unknown')
        or key in state.get('completed',{}) or len(sends)!=1 or sends[0].get('status')!='sent'
        or sends[0].get('entry')!=original or sends[0].get('original_sha256')!=attempt_digest(original)
        or any(a.get(k)!=original.get(k) for k in ('key','episode','chapter','chapter_suffix','stage','name','cost','entry_kind','start_epoch'))
        or any(a.get(k) for k in ('playback_observed_at','playback_evidence','story_seen','victory_seen','exit_seen','battle_seen','defeat_seen'))
        or any(row.get('entry',{}).get('key')==key for row in state.get('unresolved_entries',[]))
        or any(row.get('key')==key for name in ('free_story_handoffs','story_reopen_authorizations','tutorial_entry_handoffs') for row in state.get(name,[]))):
        raise ValueError('免费观看原始发送链不符，或已有实际进入/结果/归档证据；不重发。')
    return a,original,sends[0]


def preflight_hash(r,original):
    import runner
    root=Path(runner.ROOT).resolve();path=(root/original.get('evidence','')).resolve()
    if (root/'evidence').resolve() not in path.parents or not path.is_file():raise ValueError('原免费观看入口证据丢失或路径不符。')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_open(r,dispatch,*,seed=False):
    """Called before a NEW first send; legacy entries require an explicit seed."""
    if not getattr(r,'run_id',None):return None  # Legacy CLI never acquires this permission.
    original=r.s['attempted'][r.s['active']['key']]
    if seed:source_chain(r)
    elif dispatch.get('status')!='reserved':raise ValueError('新的入口响应链必须在首次发送之前登记。')
    book=r.s.setdefault('story_open_acknowledgements',{})
    if dispatch['id'] in book:raise ValueError('原入口响应链已登记，不能重置消息次数。')
    record=dict(policy=POLICY,run_id=r.run_id,key=original['key'],original_dispatch_id=dispatch['id'],
                original_sha256=attempt_digest(original),preflight_sha256=preflight_hash(r,original),
                binding=binding(r),raw_size=list(r.frame.raw_size),phase='awaiting_acceptance',registered_at=time.time(),messages=[])
    if seed:record['maintenance_seed']=copy.deepcopy(r.ack_maintenance_seed)
    book[dispatch['id']]=record
    return record


def seed_original_open(r,seed,proof):
    """Explicit code-maintenance only; never inferred by normal Start/resume."""
    import runner
    a,original,dispatch=source_chain(r)
    path=Path(runner.ROOT)/'events.jsonl'
    if (not seed.get('user_instruction') or seed.get('key')!=a['key'] or seed.get('run_id')!=r.run_id
        or seed.get('original_dispatch_id')!=dispatch['id'] or seed.get('state_sha256')!=proof['state_sha256']
        or seed.get('events_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()
        or not proof.get('user_authorization')):
        raise ValueError('旧入口响应链的明确维护来源不符；不创建重发上下文。')
    if runner.classify(r.frame)!='map':raise ValueError('维护新帧不在原未完成地图；未登记重发。')
    r.ack_maintenance_seed=seed
    record=register_open(r,dispatch,seed=True)
    # Validate the full input trace before saving/activating the legacy context.
    trace_source(r,record)
    return record


def proven_notice_detours(r,record,tail,*,evidence_root=None):
    """Match *each* passive close to its durable, same-entry dismissal receipt.

    A label/screen allowlist alone is insufficient: unrelated, failed or still
    visible notices cannot grant another entry message. Existing v1 receipts
    are accepted only with their original times, window and pixel evidence;
    no historical state is rewritten or adopted by a new run.
    """
    import runner
    from datetime import datetime
    from free_notices import CLOSE_ACTION,SCENES,MAX_CLOSE_MESSAGES,notice_modal_band_visible
    from task_overlays import _PASSIVE_FREE_NOTICE_BODIES
    closes={i for i,e in enumerate(tail) if e.get('kind')=='action' and e.get('action')==CLOSE_ACTION}
    screens={i for i,e in enumerate(tail) if e.get('kind')=='screen' and e.get('screen') in SCENES}
    if not closes and not screens:return set(),[]
    def invalid():raise ValueError('免费提示没有同run、同入口、独立消失及逐条关闭证据；不补发入口。')
    def epoch(e):
        try:return datetime.fromisoformat(e['time']).timestamp()
        except (KeyError,TypeError,ValueError):invalid()
    def image_proof(observation):
        root=Path(runner.ROOT if evidence_root is None else evidence_root).resolve();path=(root/observation.get('evidence','')).resolve()
        if (root/'evidence').resolve() not in path.parents or not path.is_file():invalid()
        image=runner.cv2.imread(str(path))
        if image is None or image.shape!=(900,1600,3):invalid()
        sha=hashlib.sha256(image.tobytes()).hexdigest()
        if observation.get('image_sha256') not in (None,sha):invalid()
        return image,sha
    original=r.s['entry_dispatches'][record['key']][0]
    expected_context={k:record[k] for k in ('key','original_dispatch_id','original_sha256')}
    expected_window=record['binding'].get('window')
    matched=set();covered=set();receipts=[];last_return_index=0
    for notice in r.s.get('free_notice_dismissals',{}).get('occurrences',[]):
        if notice.get('run_id')!=record['run_id'] or notice.get('opened_at',0)<original['reserved_at']:continue
        messages=notice.get('messages',[])
        if (notice.get('phase')!='dismissed' or notice.get('gone_scene')!='map'
            or _PASSIVE_FREE_NOTICE_BODIES.get(notice.get('body'))!=notice.get('kind')
            or notice.get('kind') not in SCENES or not 1<=len(messages)<=MAX_CLOSE_MESSAGES
            or notice.get('entry_context',expected_context)!=expected_context):invalid()
        context=notice.get('binding',{})
        if context.get('window')!=expected_window or context.get('raw_size')!=list(r.frame.raw_size):invalid()
        indices=[];hashes=[];last_finished=0.
        for message in messages:
            observations=message.get('observations',[])
            single=message.get('recognition_policy')=='single_current_observation'
            if message.get('status')!='sent' or len(observations)!=(1 if single else 2):invalid()
            first,second=observations[0],observations[-1]
            if (not original['reserved_at']<=first.get('captured_at',0)<=second.get('captured_at',0)<=message.get('reserved_at',0)
                or (not single and not 0<second['captured_at']-first['captured_at']<=5)
                or not last_finished<=message['reserved_at']<=message.get('finished_at',0)<=notice.get('gone_at',0)) :invalid()
            last_finished=message['finished_at']
            for observation in observations:
                target=observation.get('target',{})
                if (observation.get('binding')!=context or observation.get('body')!=notice['body']
                    or target.get('text') not in ('点击关闭','點擊關閉') or target.get('score',0)<.98
                    or not 560<target.get('x',0)<1040 or not 495<target.get('y',0)<630
                    or not observation.get('image_sha256')):invalid()
                hashes.append(image_proof(observation)[1])
            if max(abs(first['target'][k]-second['target'][k]) for k in ('x','y'))>8:invalid()
            target=second['target'];w,h=context['raw_size'];xy=[round(target['x']*w/1600),round(target['y']*h/900)]
            hits=[i for i in closes if tail[i].get('stage')==record['key'] and tail[i].get('xy')==xy
                  and message['reserved_at']-1<epoch(tail[i])<=message['finished_at']]
            if len(hits)!=1 or hits[0] in matched:invalid()
            index=hits[0]
            prior=[i for i,e in enumerate(tail[:index]) if e.get('kind')=='screen'
                   and e.get('screen') not in ('unknown','unknown_dialog','loading')]
            if not prior or prior[-1] not in screens:invalid()
            matched.add(index);indices.append(index)
        if indices!=sorted(indices):invalid()
        related={i for i in screens if last_return_index<i<=indices[-1]}
        if not related or any(tail[i].get('stage')!=record['key'] or not original['reserved_at']-1<epoch(tail[i])<=last_finished for i in related):invalid()
        covered.update(related)
        returned=[i for i,e in enumerate(tail) if i>indices[-1] and e.get('kind')=='screen' and e.get('screen')=='map'
                  and e.get('stage')==record['key'] and last_finished-1<epoch(e)<=notice['gone_at']]
        if not returned:invalid()
        # The same still-visible notification can be recognized again after
        # its close message. Those are observations, not extra close inputs.
        remaining={i for i in screens if indices[-1]<i<returned[0]}
        if any(tail[i].get('stage')!=record['key'] or not original['reserved_at']-1<epoch(tail[i])<=notice['gone_at'] for i in remaining):invalid()
        covered.update(remaining)
        last_return_index=returned[0]
        gone=notice.get('disappearance_observations')
        if gone is not None:
            single=notice.get('recognition_policy')=='single_current_observation'
            if (len(gone)!=(1 if single else 2) or not last_finished<=gone[0].get('captured_at',0)<=gone[-1].get('captured_at',0)<=notice['gone_at']
                or (not single and not 0<gone[-1]['captured_at']-gone[0]['captured_at']<=5)):invalid()
            for observation in gone:
                if observation.get('binding')!=context or observation.get('scene')!='map' or not observation.get('image_sha256'):invalid()
                image,sha=image_proof(observation)
                if notice_modal_band_visible(image):invalid()
                hashes.append(sha)
        else:
            image,sha=image_proof(dict(evidence=notice.get('disappearance_evidence','')))
            if notice_modal_band_visible(image):invalid()
            hashes.append(sha)
        receipts.append(dict(occurrence_id=notice['id'],message_ids=[m['id'] for m in messages],
                             receipt_sha256=digest(notice),image_sha256=hashes))
    if matched!=closes or covered!=screens:invalid()
    return matched,receipts


def trace_source(r,record):
    import runner
    a,original,dispatch=source_chain(r)
    if (record.get('policy')!=POLICY or record.get('run_id')!=getattr(r,'run_id',None)
        or record.get('key')!=a['key'] or record.get('original_dispatch_id')!=dispatch['id']
        or record.get('original_sha256')!=attempt_digest(original)
        or record.get('preflight_sha256')!=preflight_hash(r,original)
        or record.get('binding')!=binding(r) or record.get('phase')!='awaiting_acceptance'):
        raise ValueError('原run、窗口几何、入口证据或响应阶段不符；不重发。')
    messages=record.get('messages',[])
    if any(m.get('status')!='sent' for m in messages):raise ValueError('已有保留/失败/不明的补发意图，不能再次消费。')
    events=[json.loads(line) for line in (Path(runner.ROOT)/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    starts=[i for i,e in enumerate(events) if e.get('kind')=='action' and e.get('stage')==a['key'] and e.get('action')==OPEN_ACTION]
    if len(starts)!=1:raise ValueError('原首次观看消息不是唯一输入来源。')
    tail=events[starts[0]:]
    detours,receipts=proven_notice_detours(r,record,tail)
    actions=[e for i,e in enumerate(tail) if e.get('kind')=='action' and i not in detours]
    expected=[OPEN_ACTION]+[m['action'] for m in messages]
    if ([e.get('action') for e in actions]!=expected or any(e.get('stage')!=a['key'] for e in actions)
        or any(e.get('kind') in ('back','drag','stop','completed','skip_control_verified') for e in tail)
        or any(e.get('kind')=='screen' and e.get('screen') not in ('map','unknown','unknown_dialog','loading','tutorial_completed_notice') for e in tail)):
        raise ValueError('原发送后有其他实际流程或输入链，不能作为丢失入口消息补发。')
    return dict(events_sha256=digest(tail),original_dispatch_id=dispatch['id'],original_sha256=attempt_digest(original),free_notice_receipts=receipts)


class StoryOpenAcknowledgement:
    def __init__(self,r):self.r=r;self.pending=None;self.last_rejection=None
    def record(self):
        a=self.r.s.get('active') or {}
        rows=self.r.s.get('entry_dispatches',{}).get(a.get('key'),[])
        if len(rows)!=1 or rows[0].get('status')!='sent':return None
        return self.r.s.get('story_open_acknowledgements',{}).get(rows[0].get('id'))
    def observe_scene(self,scene,f):
        if scene!='map':self.pending=None
        record=self.record()
        if not record or record.get('phase')!='awaiting_acceptance':return
        if scene in ACCEPTED_SCENES:
            record.update(phase='accepted',accepted_at=time.time(),accepted_scene=scene,
                          acceptance_evidence=self.r.evidence('story-open-accepted-'+record['key']))
            self.r.save()  # Acceptance is NOT a completed record.
        elif scene in BLOCKED_SCENES:
            record.update(phase='blocked',blocked_scene=scene,blocked_at=time.time());self.r.save()
    def step(self,f):
        import runner
        r=self.r;record=self.record()
        if not record or f is not r.frame or record.get('phase')!='awaiting_acceptance':
            self.pending=None;self.last_rejection=None;return None
        # The first returned map frame is not yet an independently proved dismissal.
        # Give its existing controller the next frame; do not turn that race into
        # a permanent story-result attention. Unknown frames still never input.
        ledger=r.s.get('free_notice_dismissals',{})
        visible=next((n for n in ledger.get('occurrences',[]) if n['id']==ledger.get('active_id')),None)
        if (visible and visible.get('run_id')==record['run_id'] and visible.get('phase')=='awaiting_disappearance'
            and visible.get('messages') and 0<=time.time()-visible['messages'][-1].get('finished_at',0)<8):
            self.pending=None;return True,.25
        try:source=trace_source(r,record);self.last_rejection=None
        except ValueError as exc:
            self.last_rejection=str(exc);self.pending=None;return None  # Existing result/safety handling wins.
        last=record['messages'][-1] if record['messages'] else None
        sent_at=last['sent_at'] if last else r.s['entry_dispatches'][record['key']][0]['finished_at']
        if time.time()-sent_at<ACK_WAIT_SECONDS:
            self.pending=None;return True,.25
        if len(record['messages'])>=MAX_ADDITIONAL_MESSAGES:
            return r.observe_progress_evidence('story_open_response',dict(code='story_open_response',reason='当前仍未显示剧情入口响应，继续观察实际通关或后继解锁；未响应不等于失败，不追加真实重试。'),r.s['active'])
        d,rows,proof=r.map_ticket(f);control=runner.mainline_map_control(f)
        a=r.s['active'];next_row=next((row for row in rows if row.get('stage')==a['stage']+1),None)
        if (runner.classify(f)!='map' or not d or d.get('key')!=record['key'] or d.get('locked') is not False
            or d.get('clear_badge') or d.get('star_count') not in (None,0) or proof!='未通关蓝色当前节点'
            or not next_row or next_row.get('locked') is not True or not control or control['kind']!='story_only'
            or control['target'].get('score',0)<.98):
            self.pending=None;return None
        if not 0<=time.time()-f.at<=3:self.pending=None;return True,.25
        if list(f.raw_size)!=record.get('raw_size',list(f.raw_size)):return None
        target=control['target']
        observation=dict(captured_at=f.at,map=copy.deepcopy(d),target=copy.deepcopy(target),
                         image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest(),binding=binding(r))
        # All source/target checks have completed. Reserve BEFORE any message.
        observation['evidence']=r.evidence('story-open-send-'+record['key']+'-'+str(len(record['messages'])+1))
        message=dict(id=uuid.uuid4().hex,status='reserved',reserved_at=time.time(),source=source,
                     observations=[observation],recognition_policy='single_current_observation',action='补发尚未响应的免费观看入口 '+record['key']+' #'+str(len(record['messages'])+1))
        record['messages'].append(message);self.pending=None;r.save()
        try:r.action(message['action'],target)
        except Exception as exc:
            from pc_backend import TapNotSent
            message.update(status='not_sent' if isinstance(exc,TapNotSent) else 'unknown',reason=str(exc));r.save();raise
        message.update(status='sent',sent_at=time.time());r.save()
        r.s['reason']='故事入口消息已补发，等待游戏接受；不是通关，不重复实际剧情或战斗。'
        return True,.25
