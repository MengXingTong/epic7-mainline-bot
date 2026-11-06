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
