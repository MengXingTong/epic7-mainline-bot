"""One-use, user-authorized reopening of an unresolved zero-cost story node.

No automatic permit generation. Never relabels sent as not_sent, rewrites the
original attempt, or allows a battle/stamina/ticket entry through this path.
"""
from __future__ import annotations
import copy,hashlib,json,time
from entry_journal import attempt_digest


def state_digest(state):
    return hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def reopen_story_once(r,permit):
    from runner import classify,mainline_map_control
    active=r.s.get('active') or {};key=permit.get('key')
    original=r.s.get('attempted',{}).get(key)
    dispatches=r.s.get('entry_dispatches',{}).get(key,[])
    if (not permit.get('user_authorization') or not permit.get('id') or permit.get('source_state_sha256')!=state_digest(r.s)
        or active.get('key')!=key or active.get('entry_kind')!='story_only' or active.get('cost')!=0
        or original is None or original.get('entry_kind')!='story_only' or original.get('cost')!=0
        or any(active.get(k)!=original.get(k) for k in ('key','episode','chapter','stage','name','entry_kind','cost','start_epoch'))
        or any((row.get('entry') or {}).get('key')==key for row in r.s.get('unresolved_entries',[]))
        or key in r.s['completed'] or len(dispatches)!=1
        or dispatches[0].get('entry')!=original or dispatches[0].get('status')!='sent' or dispatches[0].get('original_sha256')!=attempt_digest(original)
        or dispatches[0].get('id')!=permit.get('original_dispatch_id')
        or active.get('story_seen') or active.get('victory_seen') or active.get('exit_seen')
        or any(row.get('id')==permit['id'] or row.get('key')==key for row in r.s.get('story_reopen_authorizations',[]))):
        raise ValueError('零体力剧情接续授权或原始唯一已发送入场链不一致；不重复入场。')
    f=r.frame;control=mainline_map_control(f);d,rows,proof=r.map_ticket(f)
    if (classify(f)!='map' or not d or d['key']!=key or d.get('locked') or d.get('clear_badge')
        or not control or control['kind']!='story_only' or control['target']['score']<.98
        or proof!='未通关蓝色当前节点' or time.time()-f.at>3):
        raise ValueError('本帧未核实原未完成纯剧情节点及免费观看控件；未消费授权。')
    record=copy.deepcopy(permit)
    record.update(status='reserved',consumed_at=time.time(),evidence=r.evidence('authorized-story-reopen-'+key),
                  target=copy.deepcopy(control['target']))
    r.s.setdefault('story_reopen_authorizations',[]).append(record)
    active['story_reopen_id']=permit['id'];r.save()  # one-use consumed BEFORE input
    r.action('用户单次授权：重新打开零体力剧情 '+key,control['target'])
    record.update(status='sent',sent_at=time.time());active['story_reopen_epoch']=time.time();r.save()
    return record
