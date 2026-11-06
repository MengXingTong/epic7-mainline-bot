"""Durable dismissal of positively identified passive free notices.

A close message is scoped to one observed appearance, never to a stage/run-wide
once-only latch. Known disappearance rearms later occurrences; OCR gaps do not.
Only registry-backed harmless notices qualify. This never records a stage clear,
resets an entry, buys resources or accepts an arbitrary confirmation dialog.
"""
from __future__ import annotations
import copy,hashlib,time,uuid
from dataclasses import asdict

SCENES=frozenset({'tutorial_completed_notice'})
DEPARTURE_SCENES=frozenset({'map','lobby','support','team','story','battle','victory','settlement','story_reward','account_upgrade_notice','date_change_notice'})
MAX_CLOSE_MESSAGES=3
CLOSE_ACK_SECONDS=3.
CLOSE_ACTION='关闭已核实的免费提示（不代表关卡通关）'


def entry_context(r):
    """Provenance only: dismissing a notice never authorizes an entry itself."""
    a=r.s.get('active') or {};rows=r.s.get('entry_dispatches',{}).get(a.get('key'),[])
    if len(rows)!=1:return None
    row=rows[0]
    return dict(key=a.get('key'),original_dispatch_id=row.get('id'),
                original_sha256=row.get('original_sha256'))


def target_binding(r,f):
    pc=getattr(r,'pc',None)
    window=getattr(pc,'frame_window',None) if pc else None
    return dict(raw_size=list(f.raw_size),window=asdict(window) if window else None)


def notice_modal_band_visible(image):
    """Known full-width notice chrome is an absence veto, NOT input authority."""
    import numpy as np
    if image.ndim!=3 or image.shape[:2]!=(900,1600):return True
    pixels=image.astype(np.int16)
    edge=np.max(np.abs(pixels[1:,8:1592]-pixels[:-1,8:1592]),axis=2)
    coverage=np.mean(edge>=12,axis=1)
    return bool(float(coverage[220:295].max())>.70 and float(coverage[610:675].max())>.70)


class FreeNoticeController:
    def __init__(self,r):self.r=r;self.pending=None;self.departure=None
    def active(self):
        ledger=self.r.s.get('free_notice_dismissals',{})
        return next((row for row in ledger.get('occurrences',[]) if row['id']==ledger.get('active_id')),None)
    def observe_scene(self,scene,f):
        if scene in SCENES:
            self.departure=None;return
        self.pending=None
        record=self.active()
        if not record:return
        if scene not in DEPARTURE_SCENES or notice_modal_band_visible(f.image):
            self.departure=None;return
        current=target_binding(self.r,f)
        if not 0<=time.time()-f.at<=3:self.departure=None;return
        prior=self.departure
        if prior and (f.at,current,scene)==prior[:3]:return  # Worker and Runner may inspect the same frame.
        observation=dict(captured_at=f.at,binding=current,scene=scene,
                         image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest())
        self.departure=(f.at,current,scene,observation)
        if prior is None or not 0<f.at-prior[0]<=5 or current!=prior[1] or scene!=prior[2]:
            observation['evidence']=self.r.evidence('free-notice-departure-'+record['id']+'-'+str(time.time_ns()))
            return
        observation['evidence']=self.r.evidence('free-notice-gone-'+record['id'])
        record.update(phase='dismissed',gone_at=time.time(),gone_scene=scene,
                      disappearance_evidence=observation['evidence'],disappearance_observations=[prior[3],observation])
        self.r.s['free_notice_dismissals']['active_id']=None
        self.departure=None;self.r.save()
    def step(self,f):
        from task_overlays import passive_free_notice
        r=self.r;notice=passive_free_notice(f.words)
        if notice is None or f is not r.frame:self.pending=None;return None
        if not 0<=time.time()-f.at<=3:self.pending=None;return True,.25
        self.departure=None
        run_id=getattr(r,'run_id',None) or 'legacy'
        context=target_binding(r,f);record=self.active()
        if record and record['run_id']!=run_id:
            record.update(phase='superseded_by_explicit_new_run',ended_at=time.time())
            r.s['free_notice_dismissals']['active_id']=None;r.save();record=None
        if record and (record['kind']!=notice['kind'] or record['body']!=notice['body']):
            record.update(phase='replaced_by_known_notice',ended_at=time.time())
            r.s['free_notice_dismissals']['active_id']=None;r.save();record=None
        messages=record['messages'] if record else []
        if messages and time.time()-messages[-1].get('finished_at',messages[-1]['reserved_at'])<CLOSE_ACK_SECONDS:
            self.pending=None;r.s['reason']='免费提示关闭消息已发送，等待弹窗消失；不连点底层页面。';return True,.25
        if len(messages)>=MAX_CLOSE_MESSAGES:
            self.pending=None
            return r.attention('free_notice_unresponsive','免费提示关闭仍未响应','当前同一弹窗已发送3条独立关闭消息，仍未确认消失；保留记录，不连续盲点。之后重新出现的弹窗不受本次次数限制。')
        observation=dict(captured_at=f.at,binding=context,body=notice['body'],target=copy.deepcopy(notice['target']),image_sha256=hashlib.sha256(f.image.tobytes()).hexdigest())
        previous=self.pending
        self.pending=(f,observation)
        if (previous is None or f is previous[0] or not 0<f.at-previous[0].at<=5
            or previous[1]['binding']!=context or previous[1]['body']!=notice['body']
            or max(abs(previous[1]['target'][key]-notice['target'][key]) for key in ('x','y'))>8):
            observation['evidence']=r.evidence('free-notice-observe-'+str(time.time_ns()))
            return True,.25
        observation['evidence']=r.evidence('free-notice-close-'+str(time.time_ns()))
        if record is None:
            ledger=r.s.setdefault('free_notice_dismissals',dict(schema=1,occurrences=[],active_id=None))
            record=dict(id=uuid.uuid4().hex,run_id=run_id,kind=notice['kind'],body=notice['body'],
                        opened_at=time.time(),phase='visible',binding=context,entry_context=entry_context(r),messages=[])
            ledger['occurrences'].append(record);ledger['active_id']=record['id']
        message=dict(id=uuid.uuid4().hex,status='reserved',reserved_at=time.time(),
                     observations=[previous[1],observation])
        record['messages'].append(message);self.pending=None
        r.save()  # Critical journal; failure must prevent the input.
        try:r.action(CLOSE_ACTION,notice['target'])
        except Exception as exc:
            from pc_backend import TapNotSent
            message.update(status='not_sent' if isinstance(exc,TapNotSent) else 'unknown',reason=str(exc),finished_at=time.time())
            r.save();raise
        message.update(status='sent',finished_at=time.time());record['phase']='awaiting_disappearance'
        r.s['reason']='已发送本次免费提示的关闭消息；后续再次出现可重新识别，不写通关。'
        r.save();return True,.25
