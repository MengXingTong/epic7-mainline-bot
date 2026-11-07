"""Positive native chapter handoff for an unbroken, recorded story flow."""
import hashlib,json
from entry_journal import attempt_digest
from map_identity import same_chapter,native_forward_chapter
from progression_evidence import story_result_trace


def native_chapter_completion(state,selected,rows,events):
    a=state.get('active') or {};key=a.get('key');original=state.get('attempted',{}).get(key)
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    if (a.get('entry_kind')!='story_only' or a.get('cost')!=0 or not a.get('playback_observed_at') or not a.get('playback_evidence')
        or original is None or key in state['completed'] or state.get('terminal')
        or len(dispatches)!=1 or dispatches[0].get('status')!='sent' or dispatches[0].get('original_sha256')!=attempt_digest(original)
        or dispatches[0].get('entry')!=original or any((row.get('entry') or {}).get('key')==key for row in state.get('unresolved_entries',[]))):return None
    if (not native_forward_chapter(a,selected) or selected.get('stage')!=1
        or selected.get('locked') is not False or selected.get('cyan',0)<.055 or selected.get('clear_badge')):return None
    next_row=next((row for row in rows if row['stage']==2),None)
    if not next_row or next_row.get('locked') is not True:return None
    starts=[index for index,event in enumerate(events) if event.get('kind')=='screen' and event.get('screen')=='story' and event.get('stage')==key]
    if not starts:return None
    tail=events[starts[0]:]
    result=story_result_trace(tail,key,require_open=False,require_return=False)
    if not result.proven:return None
    return dict(source='native_next_chapter_after_recorded_story_and_reward',from_key=key,
                to_key=selected['key'],original_dispatch_id=dispatches[0]['id'],playback_evidence=a['playback_evidence'],
                observed_next_locked_stage=2,**result.proof)


def accepted_opening_messages(ack,dispatch,trace,root):
    """Verify existing accepted message receipts; never create a resend right."""
    import math
    from pathlib import Path
    import runner
    from story_open_ack import MAX_ADDITIONAL_MESSAGES,digest
    messages=ack.get('messages',[])
    if not isinstance(messages,list) or len(messages)>MAX_ADDITIONAL_MESSAGES:raise ValueError('入口消息回执数量不符。')
    actions=[];receipts=[];identities=set();last_sent=dispatch.get('finished_at',0)
    root=Path(root).resolve()
    for index,message in enumerate(messages):
        expected='补发尚未响应的免费观看入口 '+ack['key']+' #'+str(index+1)
        identity=message.get('id');source=message.get('source',{})
        hits=[i for i,e in enumerate(trace) if e.get('kind')=='action' and e.get('action')==expected and e.get('stage')==ack['key']]
        if (not identity or identity in identities or message.get('status')!='sent' or message.get('action')!=expected
            or len(hits)!=1 or source.get('original_dispatch_id')!=dispatch['id']
            or source.get('original_sha256')!=dispatch['original_sha256']
            or source.get('events_sha256')!=digest(trace[:hits[0]])):
            raise ValueError('原入口补发回执或因果来源不符。')
        observations=message.get('observations',[])
        if len(observations)!=2:raise ValueError('原入口补发缺少独立双帧。')
        first,second=observations
        try:
            reserved=float(message['reserved_at']);sent=float(message['sent_at']);accepted=float(ack['accepted_at'])
            times=[float(o['captured_at']) for o in observations]
            if (not all(math.isfinite(t) for t in (reserved,sent,accepted,*times))
                or not last_sent<=times[0]<times[1]<=reserved<=sent<=accepted
                or not 0<times[1]-times[0]<=8 or reserved-times[1]>5):raise ValueError('原入口补发时间链不符。')
        except (KeyError,TypeError,OverflowError):raise ValueError('原入口补发时间无效。')
        hashes=[]
        for observation in observations:
            target=observation.get('target',{});node=observation.get('map',{})
            if (observation.get('binding')!=ack['binding'] or node.get('key')!=ack['key']
                or node.get('locked') is not False or node.get('clear_badge') or node.get('star_count') not in (None,0)
                or target.get('text') not in ('观看故事','观看剧情') or target.get('score',0)<.98
                or not 1200<=target.get('x',0)<=1599 or not 750<=target.get('y',0)<=899):
                raise ValueError('原入口补发目标或绑定不符。')
            path=(root/observation.get('evidence','')).resolve()
            if (root/'evidence').resolve() not in path.parents or not path.is_file():raise ValueError('原入口补发证据缺失。')
            image=runner.cv2.imdecode(runner.np.frombuffer(path.read_bytes(),runner.np.uint8),1)
            if image is None or hashlib.sha256(image.tobytes()).hexdigest()!=observation.get('image_sha256'):
                raise ValueError('原入口补发像素证据不一致。')
            hashes.append(observation['image_sha256'])
        if max(abs(first['target'][k]-second['target'][k]) for k in ('x','y'))>8:raise ValueError('原入口补发目标移动。')
        identities.add(identity);last_sent=sent;actions.append(expected)
        receipts.append(dict(message_id=identity,receipt_sha256=digest(message),image_sha256=hashes))
    return actions,receipts


def recorded_clipped_story_completion(frame,state,selected,rows,events,*,run_id,current_binding,root,diagnostics=None):
    """Two visible rows need a full same-run playback/reward chain AND a check.

    This stricter result-only path never makes the clipped label clickable or
    infers completion from the next unlocked node/chapter star total alone.
    """
    import datetime,math
    from pathlib import Path
    import runner
    from mainline_map import row_markers
    def reject(code,reason,status='blocked'):
        if diagnostics is not None:diagnostics.update(status=status,code=code,reason=reason)
        return None
    if diagnostics is not None:diagnostics.clear()
    a=state.get('active') or {};key=a.get('key');original=state.get('attempted',{}).get(key)
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    if (runner.classify(frame)!='map' or not run_id or state.get('terminal') or not original
        or a.get('entry_kind')!='story_only' or a.get('cost')!=0 or not a.get('playback_observed_at')
        or any(a.get(k)!=v for k,v in original.items()) or key in state.get('completed',{})
        or len(dispatches)!=1 or dispatches[0].get('status')!='sent' or dispatches[0].get('entry')!=original
        or dispatches[0].get('original_sha256')!=attempt_digest(original)
        or any(a.get(k) for k in ('battle_seen','victory_seen','defeat_seen','exit_seen','outcome'))
        or any((row.get('entry') or {}).get('key')==key for row in state.get('unresolved_entries',[]))):return reject('source_mismatch','原剧情入场、发送状态或归档来源不一致。')
    dispatch=dispatches[0];ack=state.get('story_open_acknowledgements',{}).get(dispatch.get('id'),{})
    if (ack.get('run_id')!=run_id or ack.get('key')!=key or ack.get('original_dispatch_id')!=dispatch['id']
        or ack.get('original_sha256')!=attempt_digest(original) or ack.get('phase')!='accepted'
        or ack.get('accepted_scene')!='story' or ack.get('binding')!=current_binding):return reject('acceptance_mismatch','原run、目标绑定或游戏接受记录不一致。')
    try:
        start=float(original['start_epoch']);accepted=float(ack['accepted_at'])
        playback=datetime.datetime.fromisoformat(a['playback_observed_at']).timestamp()
        if not math.isfinite(start) or not start<=accepted<=playback+1:return reject('source_time','原入口与播放证据时间顺序不一致。')
        trace=[e for e in events if datetime.datetime.fromisoformat(e['time']).timestamp()>=math.floor(start)]
    except (KeyError,TypeError,ValueError,OverflowError):return reject('source_time','原入口或事件时间无效。')
    # Scope by the actual original opening, not by a rounded wall-clock second:
    # a previous stage can complete in that same second without belonging here.
    opens=[i for i,e in enumerate(trace) if e.get('kind')=='action' and e.get('stage')==key and e.get('action')=='观看故事（仅一次）']
    if len(opens)!=1:return reject('original_open','原剧情入口消息不唯一或缺失。')
    trace=trace[opens[0]:]
    try:
        opening_messages,message_receipts=accepted_opening_messages(ack,dispatch,trace,root)
        # Passive notification detours are not input-name exemptions. Resolve
        # every close against its same-entry durable disappearance receipt.
        from types import SimpleNamespace
        from story_open_ack import proven_notice_detours
        playback_indices=[i for i,e in enumerate(trace) if e.get('kind')=='screen' and e.get('screen')=='story' and e.get('stage')==key]
        before_playback=trace[:playback_indices[0]] if playback_indices else trace
        detours,notice_receipts=proven_notice_detours(SimpleNamespace(s=state,frame=frame),ack,before_playback,evidence_root=root)
    except ValueError as exc:return reject('opening_receipt',str(exc))
    result=story_result_trace([e for i,e in enumerate(trace) if i not in detours],key,opening_messages=opening_messages)
    if diagnostics is not None:diagnostics.update(result.diagnostic())
    if not result.proven:return None
    # Resolve original independent evidence, never an arbitrary caller path.
    root=Path(root).resolve();evidence_hashes={}
    for name,value in (('preflight',original.get('evidence')),('playback',a.get('playback_evidence')),('acceptance',ack.get('acceptance_evidence'))):
        if not isinstance(value,str) or not value:return reject('missing_evidence','原剧情独立证据缺失。')
        path=(root/value).resolve()
        if (root/'evidence').resolve() not in path.parents or not path.is_file():return reject('missing_evidence','原剧情独立证据缺失或路径越界。')
        evidence_hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if evidence_hashes['preflight']!=ack.get('preflight_sha256'):return reject('evidence_hash','原入口截图哈希不一致。')
    if not same_chapter(selected,a):
        return reject('foreign_map','当前章节与原剧情结果不一致，且未通过原生换章核验。')
    if (not same_chapter(selected,a) or selected.get('stage')!=a['stage']+1
        or selected.get('locked') is not False or selected.get('clear_badge') or selected.get('cyan',0)<.055):return reject('map_identity','当前地图尚未完整显示原节点的相邻关系。','pending')
    grid=sorted(rows,key=lambda row:row['stage'])
    if (len(grid)!=2 or [r['stage'] for r in grid]!=[a['stage']+1,a['stage']+2]
        or grid[0]['y']!=selected.get('y') or grid[1].get('locked') is not True):return reject('map_grid','当前编号行与独立锁定关系尚不足。','pending')
    gap=grid[1]['y']-grid[0]['y'];y=grid[0]['y']-gap
    if not 121<=gap<=129 or not 158<=y<=185:return reject('map_geometry','当前结果标记的几何定位不足。','pending')
    template_path=Path(__file__).resolve().parent/'assets'/'lock.png'
    if not template_path.is_file():return reject('missing_template','缺少独立锁定核验资源。')
    template=runner.cv2.imdecode(runner.np.frombuffer(template_path.read_bytes(),runner.np.uint8),runner.cv2.IMREAD_GRAYSCALE)
    if template is None:return reject('invalid_template','独立锁定核验资源无法读取。')
    markers=row_markers(frame.image,runner.cv2.cvtColor(frame.image,runner.cv2.COLOR_BGR2HSV),round(y),template)
    if not markers['clear_badge'] or markers['locked']:return reject('map_marker','尚未完整读出原节点的独立绿环与内部通关勾。','pending')
    return dict(stage=a['stage'],name=a['name'],y=y,**markers,source='same_run_recorded_story_two_row_clipped_predecessor',
                grid=[dict(stage=r['stage'],y=r['y']) for r in grid],star_count=None,clickable=False,
                run_id=run_id,original_dispatch_id=dispatch['id'],evidence_sha256=evidence_hashes,
                **result.proof,source_events_sha256=hashlib.sha256(json.dumps(trace,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),opening_message_receipts=message_receipts,free_notice_receipts=notice_receipts,
                captured_at=frame.at,marker_pixels_sha256=hashlib.sha256(frame.image[max(0,round(y)-65):round(y)+65,:130].tobytes()).hexdigest())
