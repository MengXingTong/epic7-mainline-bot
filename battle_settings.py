"""Declarative native battle UI: AUTO on and speed 2x, never resource entry.

White A/arrows identify a control, NOT an OFF state. Normal-cycle observations
prove rotation (ON), or a canonical stationary manual-turn field (OFF). Each
command has an immutable pre-send intent and an independently observed result.
"""
import copy
import hashlib
import re
import time
import uuid
from collections import deque
import cv2
import numpy as np
from ui_control_guard import verify_live_controls

AUTO_RECT=(1360,5,1440,85)
SPEED_RECT=(1300,5,1365,85)
DIGIT_RECT=(1340,39,1358,68)
MAX_SENDS=2
OFF_SPAN=3.0
RESPONSE_WAIT=4.0


def white(image,rect):
    x1,y1,x2,y2=rect
    return image[y1:y2,x1:x2].min(axis=2)>210


def overlap(a,b):
    if a.shape!=b.shape:return 0.
    n=max(int(a.sum()),int(b.sum()))
    return float(np.count_nonzero(a&b))/n if n else 0.


def _target(text,rect,x,y,score,source):
    x1,y1,x2,y2=rect
    return dict(text=text,score=float(score),x=float(x),y=float(y),
        box=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],source=source)


def auto_field(f,ocr):
    """Read A+two native arrows at any rotation; return a candidate, not OFF."""
    if hasattr(f,'battle_auto_field'):return f.battle_auto_field
    f.battle_auto_field=None
    if f.image.shape!=(900,1600,3):return None
    mask=white(f.image,AUTO_RECT)
    _,_,stats,centers=cv2.connectedComponentsWithStats(np.uint8(mask)*255)
    pieces=list(zip(stats[1:],centers[1:]))
    letters=[(s,c) for s,c in pieces if 6<=s[2]<=25 and 10<=s[3]<=30 and 35<=s[4]<=180
             and 35<=c[0]<=60 and 25<=c[1]<=50]
    arrows=[(s,c) for s,c in pieces if 15<=s[2]<=50 and 15<=s[3]<=50 and 150<=s[4]<=650]
    if len(letters)!=1 or len(arrows)!=2 or not 450<=int(mask.sum())<=1600:return None
    s,c=letters[0];x,y,w,h,_=map(int,s)
    originals=[v for v in f.words if v['text']=='A' and v['score']>=.98
               and 1360+x-3<=v['x']<=1360+x+w+3 and 5+y-3<=v['y']<=5+y+h+3]
    if len(originals)>1:return None
    if originals:score=originals[0]['score'];origin='current_battle_auto_original_field'
    else:
        tile=f.image[5+y-1:5+y+h+1,1360+x-1:1360+x+w+1]
        image=cv2.resize(tile,(max(1,round(tile.shape[1]*48/tile.shape[0])),48),interpolation=cv2.INTER_LANCZOS4)
        rows,_=ocr(image,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2 or rows[0][0]!='A' or rows[0][1]<.98:return None
        score=float(rows[0][1]);origin='current_battle_auto_field_read'
    ring=mask.copy();ring[y:y+h,x:x+w]=False
    arrows.sort(key=lambda v:v[1][1])
    canonical=(28<=arrows[0][0][2]<=48 and 15<=arrows[0][0][3]<=30
        and 28<=arrows[1][0][2]<=48 and 15<=arrows[1][0][3]<=30
        and 12<=arrows[0][1][1]<=32 and 38<=arrows[1][1][1]<=60
        and 8<=arrows[1][1][0]-arrows[0][1][0]<=25)
    target=_target('A',AUTO_RECT,1360+c[0],5+c[1],score,origin)
    target['captured_at']=f.at
    f.battle_auto_field=dict(target=target,ring=ring,canonical=bool(canonical))
    return f.battle_auto_field


def speed_field(f,ocr):
    """The current battle-only chevron and 1/2 digit, never story playback speed."""
    if hasattr(f,'battle_speed_field'):return f.battle_speed_field
    f.battle_speed_field=None
    if f.image.shape!=(900,1600,3):return None
    mask=white(f.image,SPEED_RECT)
    _,_,stats,_=cv2.connectedComponentsWithStats(np.uint8(mask)*255)
    chevrons=[s for s in stats[1:] if 17<=s[2]<=48 and 25<=s[3]<=45 and 180<=s[4]<=1100
              and 7<=s[0]<=35 and 8<=s[1]<=30]
    if not chevrons or not 250<=int(mask.sum())<=1800:return None
    originals=[v for v in f.words if re.fullmatch(r'[xX×]\s*[12]',v['text'])
        and v['score']>=.98 and 1300<=v['x']<=1365 and 5<=v['y']<=85]
    if len(originals)>1:return None
    if originals:
        value=int(re.search(r'[12]',originals[0]['text'])[0]);score=originals[0]['score'];origin='current_battle_speed_original_field'
    else:
        digit=np.uint8(white(f.image,DIGIT_RECT))*255
        if not 30<=int(np.count_nonzero(digit))<=380:return None
        image=cv2.resize(digit,(round(digit.shape[1]*48/digit.shape[0]),48),interpolation=cv2.INTER_LANCZOS4)
        rows,_=ocr(cv2.cvtColor(image,cv2.COLOR_GRAY2BGR),use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2 or rows[0][0] not in ('1','2') or not .98<=rows[0][1]<=1:return None
        value=int(rows[0][0]);score=float(rows[0][1]);origin='current_battle_speed_digit_field_read'
    target=_target('x'+str(value),SPEED_RECT,1333,43,score,origin)
    target['captured_at']=f.at
    f.battle_speed_field=dict(state=value,target=target,digit=white(f.image,DIGIT_RECT))
    return f.battle_speed_field


def manual_signature(f):
    """A visible skill-choice bar and unchanged current HP/wave, not a cutscene."""
    hp=[w['text'] for w in f.words if re.fullmatch(r'\d{1,6}/\d{1,6}',w['text'])
        and w['score']>=.98 and 300<=w['x']<=580 and 835<=w['y']<=865]
    wave=[re.sub(r'\s+','',w['text']) for w in f.words if re.fullmatch(r'[xX×※]?\s*[1-5]\s*/\s*[1-5]',w['text'])
          and w['score']>=.85 and 155<=w['x']<=310 and 0<=w['y']<=70]
    if len(hp)!=1 or len(wave)!=1:return None
    for x1,x2 in ((1210,1320),(1350,1460),(1470,1580)):
        tile=f.image[775:880,x1:x2]
        count=int(np.count_nonzero(tile.min(axis=2)>210))
        if not 90<=count<=6000 or float(tile.std())<25:return None
    return (wave[0],hp[0])


class AutoObserver:
    """History comes from ordinary cycles, not extra screenshots or OCR voting."""
    def __init__(self):self.samples=deque(maxlen=5);self.last_on=None;self.previous=None;self.on_samples=[]
    def clear(self):self.samples.clear();self.last_on=None;self.previous=None;self.on_samples=[]
    def observe(self,f,field,sequence):
        if field is None:self.clear();return dict(state='unknown',samples=[])
        previous=self.previous
        if previous and (f.at<=previous['at'] or f.at-previous['at']>6 or sequence!=previous['sequence']):
            self.clear();previous=None
        sample=dict(at=f.at,ring=field['ring'].copy(),canonical=field['canonical'],
                    manual=manual_signature(f),sequence=sequence,frame=f)
        self.previous=sample
        if (previous and .15<=f.at-previous['at']<=6
            and overlap(previous['ring'],sample['ring'])<.82):
            self.samples.clear();self.samples.append(sample);self.last_on=f.at;self.on_samples=[previous,sample]
            return dict(state='on',samples=self.on_samples,source='current_native_arrow_rotation')
        # Observe motion on EVERY normal cycle, but retain only spaced stationary
        # samples. A fixed five-frame buffer cannot span 3s at the 0.25s cadence.
        if self.samples and any(v['manual']!=sample['manual'] or not v['canonical']
                or overlap(v['ring'],sample['ring'])<.99 for v in self.samples):
            self.samples.clear()
        if not self.samples or f.at-self.samples[-1]['at']>=OFF_SPAN/3:
            self.samples.append(sample)
        rows=list(self.samples)
        if rows[-1]['at']!=sample['at']:rows.append(sample)
        if (len(rows)>=3 and rows[-1]['at']-rows[0]['at']>=OFF_SPAN and sample['manual'] is not None
            and all(v['manual']==sample['manual'] and v['canonical'] and overlap(v['ring'],sample['ring'])>=.99 for v in rows)):
            return dict(state='off',samples=rows,source='stationary_native_manual_turn')
        if self.last_on is not None and 0<=f.at-self.last_on<OFF_SPAN:
            return dict(state='on',samples=self.on_samples,source='recent_native_rotation_no_off_transition')
        return dict(state='unknown',samples=rows)


def _save_samples(r,reading):
    """A command's temporal OFF proof must exist durably before that command."""
    from runner import ROOT,atomic_json
    directory=ROOT/'evidence';directory.mkdir(exist_ok=True)
    ident=uuid.uuid4().hex;rows=[]
    for i,sample in enumerate(reading.get('samples',[])):
        f=sample['frame'];path=directory/('battle-auto-state-'+ident+'-'+str(i)+'.png')
        ok,data=cv2.imencode('.png',f.image)
        if not ok:raise OSError('当前自动状态截图编码失败；不发送。')
        path.write_bytes(data.tobytes())
        rows.append(dict(captured_at=f.at,image=str(path.relative_to(ROOT)),image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest(),
                         ring_sha256=hashlib.sha256(sample['ring'].tobytes()).hexdigest(),manual=sample['manual']))
    metadata=dict(state=reading['state'],source=reading.get('source'),samples=rows)
    name=directory/('battle-auto-state-'+ident+'.json');atomic_json(name,metadata)
    return dict(path=str(name.relative_to(ROOT)),**metadata)


def verify_setting(r,control,field):
    """Last-mile pixels preserve state, not merely the identity of an A glyph."""
    from runner import ROOT
    proof=verify_live_controls(r,[field['target']],'battle-setting-'+control)
    if proof is None:return None
    image=cv2.imdecode(np.frombuffer((ROOT/proof['current_evidence']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if image is None or hashlib.sha256(image.tobytes()).hexdigest()!=proof['current_sha256']:return None
    if control=='speed':
        if overlap(white(r.frame.image,DIGIT_RECT),white(image,DIGIT_RECT))<.99:return None
    else:
        # During the ON animation a changed arrow phase cancels the plan even
        # if the A and a 90% text/arrow overlap would have passed the old guard.
        if overlap(white(r.frame.image,AUTO_RECT),white(image,AUTO_RECT))<.99:return None
    return proof


def _confirmed(r,record,control,state,f,reading=None):
    slot=record.setdefault(control,dict(messages=[],confirmations=[]))
    desired='on' if control=='auto' else 2
    if state!=desired:return False
    messages=slot['messages'];last=messages[-1] if messages else None
    if not last and not slot.get('initial_desired_observation'):
        slot['initial_desired_observation']=dict(state=state,captured_at=f.at,
            evidence=r.evidence('battle-setting-already-desired-'+control),
            state_proof=_save_samples(r,reading) if control=='auto' and reading else None,
            source='independent_current_state_no_command_needed')
        r.save()
    if last and f.at>last['at'] and not any(c.get('message_id')==last['id'] for c in slot['confirmations']):
        confirmation=dict(message_id=last['id'],state=state,captured_at=f.at,evidence=r.evidence('battle-setting-confirmed-'+control),
                          source='independent_current_state_not_send_acceptance',
                          state_proof=_save_samples(r,reading) if control=='auto' and reading else None)
        slot['confirmations'].append(confirmation);r.save()
    return True


def _command(r,record,control,field,reading,observer):
    f=r.frame;slot=record.setdefault(control,dict(messages=[],confirmations=[]));messages=slot['messages']
    if messages:
        last=messages[-1]
        if last['status'] not in ('sent','not_sent'):return False
        confirmed=any(c.get('message_id')==last['id'] for c in slot['confirmations'])
        if not confirmed:
            if len([v for v in messages if v['transition']==last['transition']])>=MAX_SENDS:return False
            if f.at<=last['captured_at'] or time.time()-last['finished_at']<RESPONSE_WAIT:return False
            transition=last['transition']
        else:transition=uuid.uuid4().hex
    else:transition=uuid.uuid4().hex
    temporal=_save_samples(r,reading) if control=='auto' else None
    if time.time()-f.at>3:return False
    proof=verify_setting(r,control,field)
    if proof is None or time.time()-f.at>3 or time.time()-proof['captured_at']>.75:return False
    message=dict(id=uuid.uuid4().hex,transition=transition,control=control,from_state=reading['state'],
        desired='on' if control=='auto' else 2,status='reserved',at=time.time(),captured_at=f.at,
        target=copy.deepcopy(field['target']),state_proof=temporal,pixel_proof=proof,evidence=r.evidence('battle-setting-intent-'+control))
    messages.append(message);r.save()
    from pc_backend import TapNotSent,FrameExpired
    r._battle_setting_proof=proof
    try:
        if time.time()-f.at>5 or time.time()-proof['captured_at']>.75:
            message.update(status='not_sent',reason='state verification expired before invocation')
        else:
            result=r.action('开启已核实关闭的战斗自动（不入场、不托管）' if control=='auto' else '将已核实的战斗1倍速调至2倍速（不入场）',field['target'])
            message['status']='not_sent' if result is False else 'sent'
    except (TapNotSent,FrameExpired) as exc:message.update(status='not_sent',reason=str(exc))
    except BaseException:
        message.update(status='unknown',finished_at=time.time());r.save();observer.clear();raise
    finally:
        del r._battle_setting_proof
    message['finished_at']=time.time();r.save();observer.clear()
    return True


def step(r,f,mode):
    from battle_auto_control import hud,control_context
    from entry_preflight import active_context
    context=active_context(r) or control_context(r.s,r.run_id)
    if not context or not hud(f):
        if hasattr(r,'_battle_auto_observer'):r._battle_auto_observer.clear()
        return None
    if not 0<=time.time()-f.at<=3:return True,.25
    key=context['key'];owner=(r.run_id,key)
    if getattr(r,'_battle_settings_owner',None)!=owner:
        r._battle_settings_owner=owner;r._battle_auto_observer=AutoObserver()
    observer=r._battle_auto_observer
    auto=auto_field(f,r.ocr);speed=speed_field(f,r.ocr)
    reading=observer.observe(f,auto,getattr(r,'input_sequence',0))
    state=reading['state'];speed_state=speed['state'] if speed else 'unknown'
    records=r.s.setdefault('battle_desired_settings',{});record=records.get(key)
    if record and record.get('run_id')!=r.run_id:
        return r.observe_progress_evidence('battle_settings',dict(code='foreign_settings',reason='保留其他run的战斗设置意图；未切换。'))
    if record is None:
        record=dict(run_id=r.run_id,**context,desired=dict(auto='on',speed=2));records[key]=record
    auto_ready=_confirmed(r,record,'auto',state,f,reading);speed_ready=_confirmed(r,record,'speed',speed_state,f)
    if state=='off' and _command(r,record,'auto',auto,reading,observer):return True,.25
    if speed_state==1 and _command(r,record,'speed',speed,dict(state=1),observer):return True,.25
    if auto_ready and speed_ready:
        r.s['reason']='已核实战斗自动开启、倍速2×；只观察战斗/结算，不再次切换。'
        return True,.25
    return r.observe_progress_evidence('battle_settings',dict(code='battle_settings_state',
        reason=f'正在核实当前战斗设置：自动={state}，倍速={speed_state}；仅明确关闭/1×才操作，不按白色图标盲切。'))
