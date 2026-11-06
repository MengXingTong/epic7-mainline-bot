"""Positive native chapter handoff for an unbroken, recorded story flow."""
import hashlib,json
from entry_journal import attempt_digest


def native_chapter_completion(state,selected,rows,events):
    a=state.get('active') or {};key=a.get('key');original=state.get('attempted',{}).get(key)
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    if (a.get('entry_kind')!='story_only' or a.get('cost')!=0 or not a.get('playback_observed_at') or not a.get('playback_evidence')
        or original is None or key in state['completed'] or state.get('terminal')
        or len(dispatches)!=1 or dispatches[0].get('status')!='sent' or dispatches[0].get('original_sha256')!=attempt_digest(original)
        or dispatches[0].get('entry')!=original or any((row.get('entry') or {}).get('key')==key for row in state.get('unresolved_entries',[]))):return None
    if ((selected.get('episode'),selected.get('chapter'),selected.get('stage'))!=(a.get('episode'),a.get('chapter',-2)+1,1)
        or selected.get('locked') is not False or selected.get('cyan',0)<.055 or selected.get('clear_badge')):return None
    next_row=next((row for row in rows if row['stage']==2),None)
    if not next_row or next_row.get('locked') is not True:return None
    starts=[index for index,event in enumerate(events) if event.get('kind')=='screen' and event.get('screen')=='story' and event.get('stage')==key]
    if not starts:return None
    tail=events[starts[-1]:]
    if any(event.get('kind') in ('stop','back','drag','completed') or (event.get('kind')=='screen' and event.get('screen') in ('defeat','unknown','unknown_dialog','resource_stop','capacity_stop')) for event in tail):return None
    actions=[event for event in tail if event.get('kind')=='action']
    allowed={'跳过剧情','确认跳过剧情','确认已免费加入的故事英雄（不配置或消耗英雄）','关闭已发放的免费奖励遮罩'}
    if (not actions or any(event.get('stage')!=key or event.get('action') not in allowed for event in actions)
        or actions[-1]['action']!='关闭已发放的免费奖励遮罩'
        or sum(event['action']=='跳过剧情' for event in actions)!=1 or sum(event['action']=='确认跳过剧情' for event in actions)!=1
        or not any(event.get('kind')=='screen' and event.get('screen')=='story_reward' for event in tail)):
        return None
    return dict(source='native_next_chapter_after_recorded_story_and_reward',from_key=key,
                to_key=selected['key'],original_dispatch_id=dispatches[0]['id'],playback_evidence=a['playback_evidence'],
                observed_next_locked_stage=2,events_sha256=hashlib.sha256(json.dumps(tail,ensure_ascii=False,sort_keys=True).encode()).hexdigest())


def recorded_clipped_story_completion(frame,state,selected,rows,events,*,run_id,current_binding,root):
    """Two visible rows need a full same-run playback/reward chain AND a check.

    This stricter result-only path never makes the clipped label clickable or
    infers completion from the next unlocked node/chapter star total alone.
    """
    import datetime,math
    from pathlib import Path
    import runner
    from mainline_map import row_markers
    a=state.get('active') or {};key=a.get('key');original=state.get('attempted',{}).get(key)
    dispatches=state.get('entry_dispatches',{}).get(key,[])
    if (runner.classify(frame)!='map' or not run_id or state.get('terminal') or not original
        or a.get('entry_kind')!='story_only' or a.get('cost')!=0 or not a.get('playback_observed_at')
        or any(a.get(k)!=v for k,v in original.items()) or key in state.get('completed',{})
        or len(dispatches)!=1 or dispatches[0].get('status')!='sent' or dispatches[0].get('entry')!=original
        or dispatches[0].get('original_sha256')!=attempt_digest(original)
        or any(a.get(k) for k in ('battle_seen','victory_seen','defeat_seen','exit_seen','outcome'))
        or any(row.get('entry',{}).get('key')==key for row in state.get('unresolved_entries',[]))):return None
    dispatch=dispatches[0];ack=state.get('story_open_acknowledgements',{}).get(dispatch.get('id'),{})
    if (ack.get('run_id')!=run_id or ack.get('key')!=key or ack.get('original_dispatch_id')!=dispatch['id']
        or ack.get('original_sha256')!=attempt_digest(original) or ack.get('phase')!='accepted'
        or ack.get('accepted_scene')!='story' or ack.get('binding')!=current_binding or ack.get('messages')):return None
    try:
        start=float(original['start_epoch']);accepted=float(ack['accepted_at'])
        playback=datetime.datetime.fromisoformat(a['playback_observed_at']).timestamp()
        if not math.isfinite(start) or not start<=accepted<=playback+1:return None
        trace=[e for e in events if datetime.datetime.fromisoformat(e['time']).timestamp()>=math.floor(start)]
    except (KeyError,TypeError,ValueError,OverflowError):return None
    if any(e.get('kind') not in ('screen','preflight','action','skip_control_verified') for e in trace):return None
    if any(e.get('kind')=='screen' and e.get('screen') not in ('map','story','skip_confirm','story_reward') for e in trace):return None
    starts=[i for i,e in enumerate(trace) if e.get('kind')=='screen' and e.get('screen')=='story' and e.get('stage')==key]
    if len(starts)!=1:return None
    before=[e for e in trace[:starts[0]] if e.get('kind')=='action']
    tail=trace[starts[0]:];actions=[e for e in tail if e.get('kind')=='action']
    allowed={'跳过剧情','确认跳过剧情','关闭已发放的免费奖励遮罩'}
    if (len(before)!=1 or before[0].get('stage')!=key or before[0].get('action')!='观看故事（仅一次）'
        or not actions or any(e.get('stage')!=key or e.get('action') not in allowed for e in actions)
        or actions[-1]['action']!='关闭已发放的免费奖励遮罩'
        or sum(e['action']=='跳过剧情' for e in actions)!=1 or sum(e['action']=='确认跳过剧情' for e in actions)!=1
        or not any(e.get('kind')=='screen' and e.get('screen')=='story_reward' and e.get('stage')==key for e in tail)):
        return None
    # Resolve original independent evidence, never an arbitrary caller path.
    root=Path(root).resolve();evidence_hashes={}
    for name,value in (('preflight',original.get('evidence')),('playback',a.get('playback_evidence')),('acceptance',ack.get('acceptance_evidence'))):
        if not isinstance(value,str) or not value:return None
        path=(root/value).resolve()
        if (root/'evidence').resolve() not in path.parents or not path.is_file():return None
        evidence_hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if evidence_hashes['preflight']!=ack.get('preflight_sha256'):return None
    if ((selected.get('episode'),selected.get('chapter'),selected.get('stage'))!=(a['episode'],a['chapter'],a['stage']+1)
        or selected.get('locked') is not False or selected.get('clear_badge') or selected.get('cyan',0)<.055):return None
    grid=sorted(rows,key=lambda row:row['stage'])
    if (len(grid)!=2 or [r['stage'] for r in grid]!=[a['stage']+1,a['stage']+2]
        or grid[0]['y']!=selected.get('y') or grid[1].get('locked') is not True):return None
    gap=grid[1]['y']-grid[0]['y'];y=grid[0]['y']-gap
    if not 121<=gap<=129 or not 158<=y<=185:return None
    template_path=Path(__file__).resolve().parent/'assets'/'lock.png'
    if not template_path.is_file():return None
    template=runner.cv2.imdecode(runner.np.frombuffer(template_path.read_bytes(),runner.np.uint8),runner.cv2.IMREAD_GRAYSCALE)
    if template is None:return None
    markers=row_markers(frame.image,runner.cv2.cvtColor(frame.image,runner.cv2.COLOR_BGR2HSV),round(y),template)
    if not markers['clear_badge'] or markers['locked']:return None
    return dict(stage=a['stage'],name=a['name'],y=y,**markers,source='same_run_recorded_story_two_row_clipped_predecessor',
                grid=[dict(stage=r['stage'],y=r['y']) for r in grid],star_count=None,clickable=False,
                run_id=run_id,original_dispatch_id=dispatch['id'],evidence_sha256=evidence_hashes,
                events_sha256=hashlib.sha256(json.dumps(trace,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                captured_at=frame.at,marker_pixels_sha256=hashlib.sha256(frame.image[max(0,round(y)-65):round(y)+65,:130].tobytes()).hexdigest())
