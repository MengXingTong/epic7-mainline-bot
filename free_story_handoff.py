"""Zero-cost story UI handoff after an independently proven chapter reward.

This is not a retry permit: original attempted/sent remain immutable, no story
playback/battle/failure may have occurred, and the intercepting reward must have
changed from the original notification dot into its own claimed check mark.
"""
from __future__ import annotations
import copy,hashlib,json,time
import cv2,numpy as np
from entry_journal import attempt_digest
from tutorial_core import chapter_reward_pending


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def claimed_reward_check(image,x):
    hsv=cv2.cvtColor(image[798:855,x-31:x+31],cv2.COLOR_BGR2HSV)
    binary=np.uint8((hsv[:,:,0]>=32)&(hsv[:,:,0]<=85)&(hsv[:,:,1]>110)&(hsv[:,:,2]>90))*255
    best=0.
    for scale in (.7,.85,1.,1.15):
        side=round(47*scale);mask=np.zeros((side,side),np.uint8)
        points=np.array([(round(side*.17),round(side*.48)),(round(side*.4),round(side*.73)),(round(side*.85),round(side*.2))],np.int32)
        cv2.polylines(mask,[points],False,255,max(2,round(6*scale)))
        if side<=min(binary.shape):best=max(best,float(cv2.matchTemplate(binary,mask,cv2.TM_CCOEFF_NORMED).max()))
    return best


def source_handoff(state,historical,current,events,map_data,control):
    active=state.get('active') or {};key=active.get('key');original=state.get('attempted',{}).get(key)
    rows=state.get('entry_dispatches',{}).get(key,[])
    if (not key or active.get('entry_kind')!='story_only' or active.get('cost')!=0 or original is None
        or original.get('entry_kind')!='story_only' or original.get('cost')!=0 or key in state['completed']
        or len(rows)!=1 or rows[0].get('status')!='sent' or rows[0].get('entry')!=original
        or rows[0].get('original_sha256')!=attempt_digest(original)
        or any(active.get(k)!=original.get(k) for k in ('key','episode','chapter','stage','name','cost','start_epoch'))
        or active.get('playback_observed_at') or active.get('story_seen') or active.get('victory_seen')
        or any((row.get('entry') or {}).get('key')==key for row in state.get('unresolved_entries',[]))
        or any(row.get('original_dispatch_id')==rows[0]['id'] for row in state.get('free_story_handoffs',[]))):return None
    source=reward_interception_proof(original,rows[0],historical,current,events,map_data,control)
    if source:source['source_state_sha256']=digest(state)
    return source


def reward_interception_proof(original,dispatch,historical,current,events,map_data,control):
    """Detection-only facts; this function alone never authorizes an entry.

    A no-input observation of a passive known notice is not playback. Any real
    action beyond the one free reward close, or battle/story/failure, vetoes.
    """
    from runner import Runner,mainline_map_control
    key=original['key']
    historical_map=Runner.__new__(Runner).map_ticket(historical)[0]
    historical_control=mainline_map_control(historical)
    if not historical_map or historical_map['key']!=key or not historical_control or historical_control['kind']!='story_only':return None
    pending=chapter_reward_pending(historical)
    if not pending or chapter_reward_pending(current):return None
    if claimed_reward_check(current.image,pending['card_x'])<.50:return None
    if (not map_data or map_data['key']!=key or map_data.get('locked') or map_data.get('clear_badge')
        or not control or control['kind']!='story_only' or control['target']['score']<.98):return None
    opens=[(index,event) for index,event in enumerate(events) if event.get('kind')=='action' and event.get('stage')==key and event.get('action')=='观看故事（仅一次）']
    if len(opens)!=1:return None
    index,opened=opens[0];tail=events[index+1:]
    actions=[event for event in tail if event.get('kind')=='action']
    from itertools import groupby
    screens=[name for name,_ in groupby(event.get('screen') for event in tail if event.get('kind')=='screen' and event.get('screen') not in ('tutorial_completed_notice','unknown','unknown_dialog','loading'))]
    if (len(actions)!=1 or actions[0].get('action')!='关闭已发放的免费奖励遮罩' or actions[0].get('stage')!=key
        or screens!=['story_reward','map'] or any(event.get('kind') in ('completed','stop','back','drag') for event in tail)):
        return None
    from datetime import datetime
    open_at=datetime.fromisoformat(opened['time']).timestamp();close_at=datetime.fromisoformat(actions[0]['time']).timestamp()
    if abs(open_at-dispatch['reserved_at'])>3 or not 0<=close_at-open_at<=5:return None
    return dict(policy='same_zero_cost_story_flow_after_proven_free_reward_interception',key=key,
                original_dispatch_id=dispatch['id'],original_attempt_sha256=attempt_digest(original),
                source_events_sha256=digest(events),
                historical_image_sha256=hashlib.sha256(historical.image.tobytes()).hexdigest(),
                chapter_reward=pending['needed'],claimed_check_score=claimed_reward_check(current.image,pending['card_x']),
                open_event=copy.deepcopy(opened),notice_close_event=copy.deepcopy(actions[0]),at=time.time())


def dispatch_handoff(r,source):
    from runner import classify,mainline_map_control
    if not source or source.get('source_state_sha256')!=digest(r.s):raise ValueError('同一免费故事流程来源已变化；未发送。')
    key=source['key'];a=r.s.get('active') or {};original=r.s['attempted'].get(key)
    if a.get('key')!=key or a.get('entry_kind')!='story_only' or a.get('cost')!=0 or key in r.s['completed'] or original is None or attempt_digest(original)!=source['original_attempt_sha256']:
        raise ValueError('原零体力流程身份不符；未发送。')
    if any(row.get('original_dispatch_id')==source['original_dispatch_id'] for row in r.s.get('free_story_handoffs',[])):
        raise ValueError('该奖励截获链已接续过；不重复发送。')
    f=r.frame;d,_,proof=r.map_ticket(f);control=mainline_map_control(f)
    if classify(f)!='map' or not d or d['key']!=key or proof!='未通关蓝色当前节点' or not control or control['kind']!='story_only' or time.time()-f.at>3:
        raise ValueError('本帧未核实同一未播放的免费故事；未发送。')
    record=copy.deepcopy(source);record.update(status='reserved',consumed_at=time.time(),evidence=r.evidence('free-story-handoff-'+key))
    r.s.setdefault('free_story_handoffs',[]).append(record);r.save()
    r.action('接续被免费领奖截获的同一次零体力故事流程（不重播）',control['target'])
    record.update(status='sent',sent_at=time.time());a['free_story_handoff_epoch']=time.time();r.save()
    return record


class StoryHandoffController:
    """One continuous free-UI chain; two current frames, never old-frame input."""
    def __init__(self,r):self.r=r;self.cache=None;self.pending=None
    def step(self,f):
        from pathlib import Path
        import runner
        r=self.r;a=r.s.get('active') or {};key=a.get('key')
        if a.get('entry_kind')!='story_only' or a.get('cost')!=0:return None
        if any(row.get('key')==key for row in r.s.get('free_story_handoffs',[])):return None
        original=r.s.get('attempted',{}).get(key) or {}
        relative=original.get('evidence')
        if not relative:return None
        root=Path(runner.ROOT).resolve();path=(root/relative).resolve()
        if not path.is_file() or (root/'evidence').resolve() not in path.parents:return None
        blob=path.read_bytes();sha=hashlib.sha256(blob).hexdigest()
        if self.cache is None or self.cache[:2]!=(key,sha):
            image=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape[:2]!=(900,1600):return None
            hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
            possible=any(np.count_nonzero((hsv[782:804,x-11:x+12,0]<30)&(hsv[782:804,x-11:x+12,1]>180)&(hsv[782:804,x-11:x+12,2]>150))>=35 for x in (158,282,407))
            if not possible:self.cache=(key,sha,None);return None
            results,_=r.ocr(image);historical=runner.Frame(image,results);historical.at=0
            self.cache=(key,sha,historical)
        historical=self.cache[2]
        if historical is None:return None
        events=[json.loads(line) for line in (root/'events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
        d,_,proof=r.map_ticket(f);control=runner.mainline_map_control(f)
        source=source_handoff(r.s,historical,f,events,d,control)
        if source is None:self.pending=None;return None
        source['original_preflight_file_sha256']=sha
        point=(control['target']['x'],control['target']['y'])
        if (self.pending is None or self.pending[0]!=source['original_dispatch_id'] or f.at<=self.pending[2]
            or max(abs(x-y) for x,y in zip(point,self.pending[1]))>8 or time.time()-f.at>3):
            self.pending=(source['original_dispatch_id'],point,f.at);return True,.25
        dispatch_handoff(r,source);self.pending=None
        return True,.25
