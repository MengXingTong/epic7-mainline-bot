"""Free native battle AUTO; UI operation never grants entry/result ownership."""
import copy
import re
import time
import cv2
import numpy as np
from entry_journal import attempt_digest
from ui_control_guard import verify_live_controls

MAX_MESSAGES=2


def source(state):
    a=state.get('active') or {};key=a.get('key');original=state.get('attempted',{}).get(key)
    rows=state.get('entry_dispatches',{}).get(key,[])
    if (not key or not original or a.get('team_entry_mode')!='single_task' or a.get('cost',0)<=0
        or key in state.get('completed',{}) or state.get('terminal')
        or a.get('victory_seen') or a.get('settlement_observed') or a.get('outcome') in ('defeat','failed','unknown')
        or len(rows)!=1 or rows[0].get('status')!='sent' or rows[0].get('entry')!=original
        or rows[0].get('original_sha256')!=attempt_digest(original)
        or any(a.get(k)!=original.get(k) for k in ('key','episode','chapter','chapter_suffix','stage','name','cost','team_entry_mode','start_epoch'))
        or any((v.get('entry') or {}).get('key')==key for v in state.get('unresolved_entries',[]))):return None
    return a


def control_context(state,run_id):
    """Keep free current-screen UI distinct from ownership of a paid entry.

    A new start may archive an old battle. It can enable the positively OFF
    native AUTO on the current battle without adopting that archive, adding an
    entry, or acquiring any right to settle its result. An existing active must
    still match its original single-task journal; no invalid active is bypassed.
    """
    if not isinstance(run_id,str) or not run_id or state.get('terminal'):return None
    a=source(state)
    if a:
        return dict(key=a['key'],scope='original_single_task',entry_key=a['key'],
                    original_sha256=attempt_digest(state['attempted'][a['key']]))
    if state.get('active') is not None:return None
    return dict(key='current-battle:'+run_id,scope='current_battle_ui_only',
                entry_key=None,original_sha256=None)


def hud(frame):
    if frame.image.shape!=(900,1600,3):return False
    if any(re.search(r'确认|确定|取消|跳过教学|购买|兑换|复活|点击关闭',w['text']) for w in frame.words):return False
    wave=[w for w in frame.words if re.fullmatch(r'[xX×※]?\s*[1-5]\s*/\s*[1-5]',w['text'])
          and w['score']>=.85 and 155<=w['x']<=310 and 0<=w['y']<=70]
    hp=[w for w in frame.words if re.fullmatch(r'\d{1,6}/\d{1,6}',w['text'])
        and w['score']>=.98 and 300<=w['x']<=580 and 835<=w['y']<=890]
    if len(wave)!=1 or len(hp)!=1:return False
    current,total=map(int,re.search(r'(\d+)\s*/\s*(\d+)',wave[0]['text']).groups())
    health,maximum=map(int,hp[0]['text'].split('/'))
    if not 1<=current<=total<=5 or not 0<health<=maximum:return False
    pause=frame.image[13:72,1532:1580];mask=np.uint8(pause.min(axis=2)>215)*255
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    bars=[s for s in stats[1:] if s[4]>=71 and s[3]>=27 and 1.8<=s[3]/max(s[2],1)<=8]
    return len(bars)==2 and abs(int(bars[0][1])-int(bars[1][1]))<8


def off_target(frame,ocr):
    """One current-field read only if full OCR missed A; no old-frame cache."""
    if hasattr(frame,'battle_auto_target'):return frame.battle_auto_target
    frame.battle_auto_target=None
    tile=frame.image[5:85,1360:1440];mask=np.uint8(tile.min(axis=2)>210)*255
    _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    parts=list(zip(stats[1:],centers[1:]))
    arrows=[(s,c) for s,c in parts if 28<=s[2]<=48 and 15<=s[3]<=30 and 150<=s[4]<=600]
    letters=[(s,c) for s,c in parts if 6<=s[2]<=25 and 10<=s[3]<=30 and s[4]>=35
             and 35<=c[0]<=60 and 25<=c[1]<=50]
    if len(arrows)!=2 or len(letters)!=1:return None
    arrows.sort(key=lambda v:v[1][1])
    if not (12<=arrows[0][1][1]<=32 and 38<=arrows[1][1][1]<=60
            and 8<=arrows[1][1][0]-arrows[0][1][0]<=25):return None
    s,c=letters[0];x,y,w,h,area=map(int,s)
    original=[v for v in frame.words if v['text']=='A' and v['score']>=.98
              and 1360+x-3<=v['x']<=1360+x+w+3 and 5+y-3<=v['y']<=5+y+h+3]
    if len(original)>1:return None
    if original:score=original[0]['score'];origin='current_battle_auto_original_field'
    else:
        crop=frame.image[5+y-1:5+y+h+1,1360+x-1:1360+x+w+1]
        crop=cv2.resize(crop,(max(1,round(crop.shape[1]*48/crop.shape[0])),48),interpolation=cv2.INTER_LANCZOS4)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or rows[0][0]!='A' or rows[0][1]<.98:return None
        score=float(rows[0][1]);origin='current_battle_auto_field_read'
    target=dict(text='A',score=score,x=1360+float(c[0]),y=5+float(c[1]),
                box=[[1360,5],[1440,5],[1440,85],[1360,85]],source=origin,
                glyph_box=[1360+x,5+y,1360+x+w,5+y+h],captured_at=frame.at)
    frame.battle_auto_target=target
    return target


def step(r,frame,mode):
    """A free UI operation: positive battle HUD, exact A + two OFF arrows."""
    from entry_preflight import active_context
    context=active_context(r) or control_context(r.s,r.run_id)
    if not context or not hud(frame):return None
    if not 0<=time.time()-frame.at<=3:return True,.25
    records=r.s.setdefault('battle_auto_controls',{});record=records.get(context['key'])
    if record and record.get('run_id')!=r.run_id:
        return r.observe_progress_evidence('battle_auto',dict(code='foreign_auto_record',reason='自动控件原记录不属于当前run；不切换。'))
    target=off_target(frame,r.ocr)
    messages=(record or {}).get('messages',[])
    if target is None:
        if messages and mode=='new_player_tutorial':
            r.s['reason']='自动按钮已发送，继续观察真实战斗；不追加基础技能手操、不重复开战。'
            return True,.25
        return None
    if messages:
        last=messages[-1]
        if (last['status'] not in ('sent','not_sent') or len(messages)>=MAX_MESSAGES
            or frame.at<=last['captured_at'] or time.time()-last['finished_at']<4):
            r.s['reason']='等待游戏接受已发送的自动按钮；不重复切换或发送入场。'
            return True,.25
    proof=verify_live_controls(r,[target],'battle-auto')
    if proof is None:return True,.25
    if time.time()-frame.at>3 or time.time()-proof['captured_at']>.75:return True,.25
    if record is None:
        record=dict(run_id=r.run_id,**context,messages=[])
        records[context['key']]=record
    message=dict(status='reserved',at=time.time(),captured_at=frame.at,target=copy.deepcopy(target),proof=proof,
                 evidence=r.evidence('battle-auto-off-'+str(len(record['messages'])+1)))
    record['messages'].append(message);r.save()
    from pc_backend import TapNotSent,FrameExpired
    try:
        if time.time()-proof['captured_at']>.75 or time.time()-frame.at>5:
            message.update(status='not_sent',reason='fresh verification expired before invocation')
        else:
            result=r.action('开启已核实的战斗内自动（不入场、不托管）',target)
            message['status']='not_sent' if result is False else 'sent'
    except (TapNotSent,FrameExpired) as exc:
        message.update(status='not_sent',reason=str(exc))
    except BaseException:
        message.update(status='unknown',finished_at=time.time());r.save();raise
    message['finished_at']=time.time();r.save()
    return True,.25
