"""Experimental Dimension worker: guarded navigation, evidence and safe attention.

No route/choice/combat is claimed as supported until observed and tested.
"""
from pathlib import Path
import time
from abyss_core import Observation,Token
from dimension_core import classify,plan,same_reading,reading_key
from dimension_journal import DimensionJournal
from dimension_vision import apply as apply_visuals
from dimension_ocr import enrich
from task_blockers import TaskAttention
from task_timing import ObservationCycle


def run(request,control):
    from assistant_config import validate_run
    from assistant_transport import UnifiedTransport
    from assistant_worker import capture_fresh,PauseRun,StopRun
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    settings=request['settings'];root,_=validate_run(settings,request['target'],allow_reconcile=True)
    def check():
        control.check()
        if (Path(root)/'STOP').exists():raise StopRun()
    transport=UnifiedTransport(settings,request['target'],check)
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    from abyss_templates import TemplateBank
    from assistant_config import CODE_ROOT
    bank=TemplateBank(CODE_ROOT/'assets/abyss' if (CODE_ROOT/'portable.json').exists() else CODE_ROOT/'.local/assistant/abyss-assets')
    bank.entries=[entry for entry in bank.entries if entry['name']=='battle-pause']
    journal=None if settings.get('observe') else DimensionJournal(root)
    previous=None;unknown_since=None;visited=set()
    cycle=ObservationCycle()
    while True:
        try:
            cycle.begin()
            check();snap=capture_fresh(transport.capture,control)
            results,_=ocr(np.array(snap.image)[:,:,::-1].copy())
            tokens=[]
            for box,text,score in results or []:
                # Retain weak OCR for conservative overlay/risk blocking.
                x=min(p[0] for p in box);y=min(p[1] for p in box)
                tokens.append(Token(text,x,y,max(p[0] for p in box)-x,max(p[1] for p in box)-y,score=float(score)))
            obs=Observation(snap.image.width,snap.image.height,tokens,snap.captured_at)
            obs=enrich(ocr,snap.image,obs);obs=apply_visuals(snap.image,obs);obs=bank.apply(snap.image,obs)
            reading=classify(obs,journal.state if journal else None);control.preview(snap.image)
            control.status('次元探查：正在核验当前画面（实验性，路线与抉择待验收）',
                mode='observe' if settings.get('observe') else 'run',scene=reading.scene,
                stage=('第'+reading.stage+'阶段') if reading.stage else '',wins=0)
            if settings.get('observe'):
                if request.get('once'):return
                cycle.wait(control);continue
            if previous is None or not same_reading(previous,reading,obs.width,obs.height):
                previous=reading;unknown_since=None;cycle.wait(control);continue
            if reading.scene=='unknown':
                unknown_since=unknown_since or time.monotonic()
                if time.monotonic()-unknown_since<15:cycle.wait(control);continue
            else:unknown_since=None
            if reading.scene=='dimension_battle_wait':
                node=journal.state['active']['nodes'][reading.key]
                if not node.get('battle_observed_evidence'):
                    proof=journal.evidence(snap,obs,reading,'battle_HUD_verified');journal.observe(reading,proof)
                    node['battle_observed_evidence']=proof;node['status']='battle_observed';journal.save()
                if time.time()-node['battle_start_intent']['at']>1200:
                    raise TaskAttention('dimension_battle_timeout','等待战斗超时','已记录战斗超过20分钟，停止输入等待人工处理，不重试。')
                control.status('原生自动战斗/过场核验中；不点击技能、不重开。',mode='run');cycle.wait(control);continue
            evidence=journal.evidence(snap,obs,reading,'stable_observation')
            journal.observe(reading,evidence)
            if reading.scene=='unknown':
                journal.attention(reading,evidence)
                raise TaskAttention('dimension_unknown','次元探查遇到新界面','已在原进度的 dimension/evidence 留存截图与识别；暂停且不猜测点击，需补充此界面的实测处理器。')
            try:action=plan(reading,journal.state)
            except TaskAttention:
                journal.attention(reading,evidence);raise
            if action is None:
                raise TaskAttention('dimension_no_handler','次元探查等待处理','此画面没有已验收动作，零输入。')
            key=reading_key(reading)
            if key in visited:
                raise TaskAttention('dimension_cycle','检测到导航回环','本次运行已操作过相同界面，不重复点击。')
            journal.reserve(reading,action,evidence) # Critical writes precede any input.
            check()
            if action.kind=='back':transport.back(snap)
            else:transport.tap(snap,action.token)
            visited.add(key);control.log('执行：'+action.name+'；等待新帧验证，不将消息发送成功当作流程成功。')
            previous=None;cycle.wait(control)
        except TaskAttention as exc:
            control.attention(exc);previous=None;unknown_since=None
        except PauseRun:
            control.paused();previous=None;unknown_since=None
