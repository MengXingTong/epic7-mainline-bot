"""Verified native dismissal of chat overlays; never type/send or replay entry."""
from __future__ import annotations
import copy,time,uuid
from task_overlays import chat_panel_heading,chat_panel_visible
from free_notices import target_binding,entry_context
from ui_control_guard import verify_live_controls

CLOSE_ACTION='关闭已核实聊天侧栏（原生返回，不输入聊天）'
DEPARTURES=frozenset({'story','skip_confirm','tutorial_skip','battle','victory','settlement','map','lobby','team','support','story_reward','account_upgrade_notice','rankup_splash'})


def close_controls(f):
    """Full empty-editor or known connecting panel; heading alone is a veto."""
    if not chat_panel_visible(f.words):return None
    def unique(text,rect):
        x1,y1,x2,y2=rect
        rows=[w for w in f.words if w['text'].strip()==text and w['score']>=.98
              and x1<w['x']<x2 and y1<w['y']<y2]
        return rows[0] if len(rows)==1 else None
    headings=[w for w in f.words if w['text'].strip() in ('骑士团频道','世界频道','聊天频道','频道')
              and w['score']>=.98 and 880<w['x']<1360 and 0<w['y']<90]
    if len(headings)!=1:return None
    editor=unique('点击此处并输入',(880,774,1424,891));send=unique('输入',(1376,774,1584,891))
    if editor and send:return [headings[0],editor,send]
    connecting=[w for w in f.words if w['text'].rstrip('。.')=='与聊天服务器连接中'
                and w['score']>=.98 and 880<w['x']<1520 and 360<w['y']<585]
    return [headings[0],connecting[0]] if len(connecting)==1 else None


class ChatRecoveryController:
    def __init__(self,r):self.r=r
    def active(self):
        ledger=self.r.s.get('chat_recoveries',{})
        return next((row for row in ledger.get('occurrences',[]) if row['id']==ledger.get('active_id')),None)
    def observe_scene(self,scene,f):
        row=self.active()
        if not row or row.get('phase')!='awaiting_disappearance' or scene not in DEPARTURES:return
        if chat_panel_heading(f.words) or chat_panel_visible(f.words):return
        messages=row['messages']
        if not messages or messages[-1]['status']!='sent' or f.at<=messages[-1]['sent_at']:return
        if not 0<=time.time()-f.at<=5 or target_binding(self.r,f)!=row['binding']:return
        row.update(phase='closed',closed_at=time.time(),departure=dict(scene=scene,captured_at=f.at,
                   evidence=self.r.evidence('chat-closed-'+uuid.uuid4().hex)))
        self.r.s['chat_recoveries']['active_id']=None;self.r.save()
    def step(self,f):
        r=self.r;controls=close_controls(f)
        if controls is None:
            return r.observe_progress_evidence('chat_recovery',dict(code='chat_controls',reason='正在复核聊天侧栏完整标题和空输入区；未输入聊天、未点击底层。'))
        row=self.active();binding=target_binding(r,f)
        if row and (row['binding']!=binding or row['run_id']!=getattr(r,'run_id',None)):
            return r.attention('chat_target','聊天恢复目标变化','保留原恢复意图；不向变化后的目标发送返回。')
        if row and row['messages']:
            last=row['messages'][-1]
            if last['status'] not in ('sent','cancelled_before_send'):return r.attention('chat_dispatch','聊天关闭发送结果不明','原关闭意图保留；不复用未知发送，不输入聊天或重新入场。')
            if sum(m['status']=='sent' for m in row['messages'])>=2 or (last['status']=='sent' and time.time()-last['sent_at']<3):
                return r.observe_progress_evidence('chat_recovery',dict(code='chat_disappearance',reason='原生关闭已发送，等待聊天侧栏独立消失；不连按返回。'))
        from pc_backend import FrameExpired
        try:proof=verify_live_controls(r,controls,'chat-close')
        except FrameExpired:
            return r.observe_progress_evidence('chat_recovery',dict(code='chat_frame_expired',reason='聊天关闭尚未发送，来源帧已过期；丢弃旧计划并重新识别。'))
        if proof is None:
            return r.observe_progress_evidence('chat_recovery',dict(code='chat_changed',reason='聊天控件在发送前已变化，丢弃返回计划并重新读取；不点穿底层。'))
        if row is None:
            ledger=r.s.setdefault('chat_recoveries',dict(schema=1,active_id=None,occurrences=[]))
            row=dict(id=uuid.uuid4().hex,run_id=getattr(r,'run_id',None),binding=binding,
                     entry_context=entry_context(r),opened_at=time.time(),phase='visible',messages=[])
            ledger['occurrences'].append(row);ledger['active_id']=row['id']
        message=dict(id=uuid.uuid4().hex,status='reserved',reserved_at=time.time(),proof=copy.deepcopy(proof),action=CLOSE_ACTION)
        row['messages'].append(message);r.save()
        if not 0<=time.time()-proof['captured_at']<=.75 or not 0<=time.time()-f.at<=5:
            message.update(status='cancelled_before_send',finished_at=time.time());r.save()
            return True,.25
        from runner import event
        r.ensure_game()
        if not 0<=time.time()-proof['captured_at']<=.75 or not 0<=time.time()-f.at<=5:
            message.update(status='cancelled_before_send',finished_at=time.time());r.save()
            return True,.25
        r.input_sequence=getattr(r,'input_sequence',0)+1;r.s['last_action']=CLOSE_ACTION
        event('chat_panel_close_intent',message_id=message['id'],action=CLOSE_ACTION,stage=(r.s.get('active') or {}).get('key'),proof=proof)
        try:
            if getattr(r,'pc',None):r.pc.back()
            else:r.adb('shell','input','keyevent','4')
        except Exception as exc:
            from pc_backend import TapNotSent
            message.update(status='not_sent' if isinstance(exc,TapNotSent) else 'unknown',reason=str(exc),finished_at=time.time());r.save();raise
        message.update(status='sent',sent_at=time.time());row['phase']='awaiting_disappearance'
        r.s['reason']='已原生关闭当前核实的聊天侧栏，等待独立消失后接续原流程；不输入聊天、不重新入场。'
        r.save();return True,.25
