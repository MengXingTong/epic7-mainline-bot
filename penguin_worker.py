"""Experimental PC Penguin Nest worker. Unknown outcomes never trigger another purchase."""
import time
from pathlib import Path
from dataclasses import asdict
from penguin_core import classify,plan
from penguin_vision import read_observation
from penguin_journal import PenguinJournal
from task_blockers import TaskAttention
from task_timing import ObservationCycle


def fingerprint(reading,action):
    target=action.target
    return (reading.scene,action.kind,reading.selected,reading.maximum,reading.total,
            reading.stock,reading.unit,reading.currency,action.desired,
            target.text if target else None)


def same_target(first,second,scale):
    if first is None or second is None:return first is second
    return first.text==second.text and max(abs(a-b) for a,b in zip(first.center,second.center))<=scale*.008


def run(request,control):
    from assistant_config import validate_run
    from assistant_transport import UnifiedTransport
    from assistant_worker import capture_fresh,wait_for_input,PauseRun,StopRun
    from pc_backend import PcSafetyError,TapNotSent
    from rapidocr_onnxruntime import RapidOCR
    settings=request['settings'];root,_=validate_run(settings,request['target'],allow_reconcile=True)
    def check():
        control.check()
        if (Path(root)/'STOP').exists():raise StopRun()
    transport=UnifiedTransport(settings,request['target'],check)
    binding=transport.ensure()
    def capture():
        if transport.ensure()!=binding:raise PcSafetyError('企鹅任务窗口/进程/几何已变化，停止；不重绑或抢焦点。')
        return transport.capture()
    journal=PenguinJournal(root,request['run_id'],settings['penguin_quantity'])
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    cycle=ObservationCycle();previous=None;last_sent=None;waiting_since=None;quantity_ack=None
    while True:
        try:
            cycle.begin();check()
            snap=capture_fresh(capture,control)
            obs=read_observation(snap.image,ocr,snap.captured_at)
            reading=classify(obs)
            control.preview(snap.image)
            count=journal.run['purchased'];requested=journal.run['requested']
            control.status(f'买企鹅：已核实 {count}/{requested} 只；每批先核对数量与费用。',
                mode='run',scene=reading.scene,wins=count,penguin_requested=requested)
            if journal.pending:
                pending=journal.pending
                if pending['status']!='sent':
                    raise TaskAttention('penguin_dispatch','购买发送结果未明',
                        '原扣费意图已保留，不取消、不重开、不再次购买；请人工核对。')
                if reading.scene=='penguin_altar' and reading.stock!=pending['stock_before']:
                    # Independent post-dispatch frame pair; never click == success.
                    if previous and previous[0]==('result',reading.stock,reading.unit,reading.currency):
                        evidence=journal.evidence(snap,obs,reading)
                        if journal.confirm(reading,evidence,snap.binding):
                            if journal.remaining==0:
                                control.status(f'已完成：独立核实购买 {journal.run["purchased"]}/{requested} 只企鹅。',
                                    mode='done',wins=journal.run['purchased']);return
                            previous=None;last_sent=None;waiting_since=None
                            cycle.wait(control);continue
                    previous=(('result',reading.stock,reading.unit,reading.currency),None)
                else:previous=None
                if waiting_since is None:waiting_since=time.monotonic()
                if time.monotonic()-waiting_since>=10:
                    raise TaskAttention('penguin_result','等待独立购买结果',
                        '已发送一次购买；请手动关闭实际获得物品页后点继续，核对祭坛余额。不会重发或按点击补记成功。')
                cycle.wait(control);continue
            if journal.remaining<=0:
                control.status(f'已完成：独立核实购买 {count}/{requested} 只企鹅。',mode='done',wins=count);return
            if quantity_ack and reading.scene=='penguin_dialog':
                old,expected,maximum,at=quantity_ack
                if reading.maximum!=maximum or reading.selected not in (old,expected):
                    raise TaskAttention('penguin_quantity_change','数量发生意外变化','不沿用变化前授权；请核实当前数量。')
                if reading.selected==old:
                    if time.monotonic()-at>=10:
                        raise TaskAttention('penguin_no_transition','调数后没有核实到变化','不重复调数；请停止后重新开始。')
                    previous=None;cycle.wait(control);continue
                quantity_ack=None
            action=plan(reading,journal.run['phase'],journal.remaining,journal.run['baseline'])
            if action.kind in ('wait','wait_result'):
                previous=None
                if waiting_since is None:waiting_since=time.monotonic()
                if time.monotonic()-waiting_since>=10:
                    journal.evidence(snap,obs,reading)
                    raise TaskAttention('penguin_unknown','当前页面或控件未完整核实','未知弹层、加载或证据不足时零输入；请处理后继续。')
                cycle.wait(control);continue
            waiting_since=None
            sig=fingerprint(reading,action)
            if last_sent and last_sent[0]==sig and same_target(last_sent[1],action.target,obs.width):
                if time.monotonic()-last_sent[2]>=10:
                    raise TaskAttention('penguin_no_transition','操作后没有核实到变化','不会在相同数量/页面重复发送；请处理后继续。')
                previous=None;cycle.wait(control);continue
            if not previous or previous[0]!=sig or not same_target(previous[1],action.target,obs.width):
                previous=(sig,action.target);cycle.wait(control);continue
            if wait_for_input(control,transport,snap):previous=None;continue
            check()
            evidence=journal.evidence(snap,obs,reading)
            # Evidence I/O is part of freshness; expired frames are recaptured only BEFORE intent.
            if time.monotonic()-snap.captured_at>4:
                previous=None;cycle.wait(control);continue
            ident=journal.reserve(action,reading,evidence,snap.binding)
            try:transport.tap(snap,action.target)
            except TapNotSent:
                journal.sent(ident,'not_sent')
                raise TaskAttention('penguin_not_sent','输入被接管，已停止本次发送','保留意图；最终购买不自动重发。请核对记录。')
            except BaseException:
                journal.sent(ident,'unknown');raise
            journal.sent(ident,'sent')
            last_sent=(sig,action.target,time.monotonic());previous=None
            if action.kind in ('most','minimum','plus','minus'):
                expected={'most':reading.maximum,'minimum':1,'plus':reading.selected+1,'minus':reading.selected-1}[action.kind]
                quantity_ack=(reading.selected,expected,reading.maximum,time.monotonic())
            if action.kind=='purchase':waiting_since=time.monotonic()
            cycle.wait(control)
        except PauseRun:
            previous=None;control.paused()
        except TaskAttention as exc:
            previous=None;control.attention(exc)
            waiting_since=None
