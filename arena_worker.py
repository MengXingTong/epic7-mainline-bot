"""NPC arena worker. Unknown screens never authorize input."""
from dataclasses import asdict
import time
from arena_core import Reading,classify,norm,one
from arena_journal import ArenaJournal
from abyss_core import Observation,Token
from task_blockers import TaskAttention
from task_timing import ObservationCycle


def read_observation(image,ocr,captured_at):
    import numpy as np
    from PIL import Image
    sampled=image.resize((1600,900),Image.Resampling.BICUBIC)
    results,_=ocr(np.array(sampled)[:,:,::-1].copy())
    sx,sy=image.width/1600,image.height/900
    obs=Observation(image.width,image.height,[Token(text,min(p[0] for p in box)*sx,min(p[1] for p in box)*sy,(max(p[0] for p in box)-min(p[0] for p in box))*sx,(max(p[1] for p in box)-min(p[1] for p in box))*sy,score=float(score)) for box,text,score in results or []],captured_at)
    # Original OCR is preserved; a weak first-row label is strengthened only by
    # two independent reads of this frame's fixed NPC-name field, both >= .98.
    candidates=[t for t in obs.tokens if obs.in_region(t,(.30,.285,.49,.345)) and t.score is not None and .90<=t.score<.98]
    if len(candidates)==1 and one(obs,'NPC交战对手',(.22,.11,.45,.21),.98):
        original=candidates[0];verified=[]
        pad=original.h*.5
        crop=image.crop((round(original.x-pad),round(original.y-pad),round(original.x+original.w+pad),round(original.y+original.h+pad)))
        for width in (480,640):
            part=crop.resize((width,round(crop.height*width/crop.width)),Image.Resampling.LANCZOS)
            rows,_=ocr(np.array(part)[:,:,::-1].copy())
            if not rows or len(rows)!=1:break
            box,text,score=rows[0]
            if norm(text)!=norm(original.text) or score<.98:break
            verified.append(float(score))
        if len(verified)==2:
            obs.tokens.append(Token(original.text,original.x,original.y,original.w,original.h,source='arena_opponent_double_read',score=min(verified)))
    if one(obs,'新手竞技场',(.025,0,.22,.10),.98) and one(obs,'战斗开始',(.60,.85,.74,.98),.98) and one(obs,'NPC对战',(.62,.73,.75,.82),.98):
        import re
        costs=[t for t in obs.tokens if obs.in_region(t,(.54,.87,.62,.96)) and re.fullmatch(r'\d{1,4}/\d{1,5}',norm(t.text)) and t.score is not None and .90<=t.score<.98]
        if len(costs)==1:
            original=costs[0];scores=[]
            crop=image.crop((round(image.width*.559),round(image.height*.893),round(image.width*.602),round(image.height*.950)))
            for width in (240,320):
                part=crop.resize((width,round(crop.height*width/crop.width)),Image.Resampling.BICUBIC)
                rows,_=ocr(np.array(part)[:,:,::-1].copy())
                if not rows or len(rows)!=1:break
                box,text,score=rows[0]
                if norm(text)!=norm(original.text) or score<.98:break
                scores.append(float(score))
            if len(scores)==2:obs.tokens.append(Token(original.text,original.x,original.y,original.w,original.h,source='arena_cost_double_read',score=min(scores)))
    result_context=all(one(obs,label,region,.98) for label,region in (
        ('NPC对战的胜负',(.40,.59,.60,.68)),('不会影响积分。',(.40,.63,.60,.71)),
        ('战斗结果',(.73,.85,.85,.98)),('确认',(.86,.85,.97,.98))))
    if result_context:
        from PIL import ImageEnhance
        names=[t for t in obs.tokens if obs.in_region(t,(.53,.065,.76,.11)) and t.score is not None and .90<=t.score<.98]
        if len(names)==1:
            original=names[0];pad=original.h*.5;scores=[]
            crop=image.crop((round(original.x-pad),round(original.y-pad),round(original.x+original.w+pad),round(original.y+original.h+pad)))
            for contrast in (1.3,1.6):
                part=ImageEnhance.Contrast(crop).enhance(contrast).resize((480,round(crop.height*480/crop.width)),Image.Resampling.BICUBIC)
                rows,_=ocr(np.array(part)[:,:,::-1].copy())
                if not rows or len(rows)!=1:break
                box,text,score=rows[0]
                if norm(text)!=norm(original.text) or score<.98:break
                scores.append(float(score))
            if len(scores)==2:obs.tokens.append(Token(original.text,original.x,original.y,original.w,original.h,source='arena_result_name_double_read',score=min(scores)))
        if not one(obs,'VICTORY',(.30,.25,.72,.44),.98):
            originals=[t for t in obs.tokens if obs.in_region(t,(.30,.25,.72,.44)) and t.score is not None and t.score>=.85]
            if len(originals)==1:
                original=originals[0];scores=[]
                crop=image.crop((round(image.width*.379),round(image.height*.300),round(image.width*.652),round(image.height*.392)))
                for contrast in (1,1.6):
                    part=ImageEnhance.Contrast(crop).enhance(contrast)
                    rows,_=ocr(np.array(part)[:,:,::-1].copy(),use_det=False,use_cls=False)
                    if not rows or len(rows)!=1 or norm(rows[0][0])!='victory' or rows[0][1]<.98:break
                    scores.append(float(rows[0][1]))
                if len(scores)==2:
                    obs.tokens.append(Token('VICTORY',original.x,original.y,original.w,original.h,source='arena_victory_double_read',score=min(scores)))
                    obs.visuals.add('arena_victory_original:'+norm(original.text))
    from arena_vision import apply
    return apply(image,obs)


def signature(reading):
    t=reading.target
    return (reading.scene,reading.opponent,reading.stock,reading.cost,t.text if t else '',tuple(round(v,1) for v in t.center) if t else ())


def run(request,control):
    from assistant_config import validate_run
    from assistant_transport import UnifiedTransport
    from assistant_worker import capture_fresh,wait_for_input,PauseRun,StopRun
    from pc_backend import PcSafetyError,TapNotSent
    from rapidocr_onnxruntime import RapidOCR
    settings=request['settings'];root,_=validate_run(settings,request['target'],allow_reconcile=True)
    def check():
        control.check()
        from pathlib import Path
        if (Path(root)/'STOP').exists():raise StopRun()
    tr=UnifiedTransport(settings,request['target'],check);bound=tr.ensure()
    def capture():
        if tr.ensure()!=bound:raise PcSafetyError('竞技场窗口/进程寿命/几何变化；停止，不自动重绑。')
        return tr.capture()
    j=ArenaJournal(root,request['run_id'],settings['arena_count'])
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    cycle=ObservationCycle();previous=None;last_sent=None;unknown_since=None;selected=False;challenged=False
    history=[a for a in j.state['actions'] if a['run_id']==request['run_id']]
    last_entry=max((i for i,a in enumerate(history) if a['kind']=='entry'),default=-1)
    tail=history[last_entry+1:]
    selected=any(a['kind']=='select' and a['status']=='sent' for a in tail)
    challenged=any(a['kind']=='challenge' and a['status']=='sent' for a in tail)
    while True:
        try:
            cycle.begin();check();snap=capture_fresh(capture,control)
            obs=read_observation(snap.image,ocr,snap.captured_at)
            try:r=classify(obs)
            except TaskAttention as exc:
                evidence=j.evidence(snap,obs,Reading('arena_blocked'))
                j.state.setdefault('attention_events',[]).append(dict(code=exc.code,at=time.time(),evidence=evidence,active_key=(j.active or {}).get('key')))
                j.save();raise
            control.preview(snap.image)
            control.status(f'NPC竞技场：已独立核实 {j.run["wins"]}/{j.run["requested"]} 把。',mode='run',scene=r.scene,wins=j.run['wins'],arena_requested=j.run['requested'])
            if j.remaining==0 and not j.run.get('pending_result'):
                control.status(f'NPC竞技场已完成 {j.run["wins"]}/{j.run["requested"]} 把；没有追加下一把。',mode='done');return
            kind=None
            if j.active:
                if r.scene in ('arena_battle','arena_result') and r.opponent!=j.active['opponent']:
                    raise TaskAttention('arena_opponent','当前对手与原入场不一致','不认领外来战斗或结果，不追加入场。')
                if r.scene=='arena_battle':
                    if not j.active['battle_evidence']:j.battle(j.evidence(snap,obs,r),snap.binding)
                    if r.target and not any(a['kind']=='auto' and a.get('key')==j.active['key'] for a in j.state['actions']):kind='auto'
                elif r.scene=='arena_result':
                    if previous and previous[0]==signature(r):
                        j.complete(j.evidence(snap,obs,r),snap.binding)
                        selected=False;challenged=False;previous=None
                        cycle.wait(control);continue
                    else:previous=(signature(r),snap.captured_at);cycle.wait(control);continue
                elif r.scene not in ('arena_unknown',):
                    # A sent entry is never automatically repeated.
                    if time.monotonic()-j.active['entry_evidence']['captured_at']>15:
                        raise TaskAttention('arena_pending','等待原竞技场结果','保留已发送入场，不再次开战；当前尚无独立战斗/结算证据。')
            else:
                if r.scene in ('arena_lobby','arena_hub','arena_tab'):kind='navigate'
                elif r.scene=='arena_npc':
                    if j.run.get('pending_result'):
                        sig=('closed_result',signature(r))
                        if previous and previous[0]==sig:
                            j.acknowledge_close(j.evidence(snap,obs,r),snap.binding)
                            previous=None;selected=False;challenged=False
                        else:previous=(sig,snap.captured_at)
                        cycle.wait(control);continue
                    if not selected:kind='select'
                    else:
                        challenge=one(obs,'挑战',(.43,.86,.56,.97),.98)
                        if challenge:
                            r=Reading('arena_npc',challenge,r.opponent);kind='challenge'
                elif r.scene=='arena_team':
                    if not challenged:raise TaskAttention('arena_source','缺少本次首位NPC选择链','请回到NPC对战列表再继续；不从外来队伍页直接开战。')
                    kind='entry'
                elif r.scene=='arena_result':
                    if j.run.get('pending_result'):kind='result_close'
            if kind:
                sig=signature(r)
                if last_sent and last_sent[0]==sig:
                    previous=None
                    if time.monotonic()-last_sent[2]>12:raise TaskAttention('arena_no_transition','已发送控件尚未响应','不连点、不重发入场；保留原发送记录。')
                    cycle.wait(control);continue
                if not previous or previous[0]!=(kind,sig):
                    previous=((kind,sig),snap.captured_at);cycle.wait(control);continue
                if snap.captured_at<=previous[1]:raise PcSafetyError('不是独立的新帧。')
                if wait_for_input(control,tr,snap):previous=None;cycle.wait(control);continue
                ev=j.evidence(snap,obs,r);ident=j.intent(kind,r,ev,snap.binding)
                try:tr.tap(snap,r.target)
                except TapNotSent:
                    j.sent(ident,'not_sent');raise TaskAttention('arena_not_sent','本次输入明确未发送','保留意图，重新核对后处理；不会自动重复入场。')
                except BaseException:
                    j.sent(ident,'unknown');raise
                j.sent(ident,'sent');last_sent=(signature(r),kind,time.monotonic());previous=None;unknown_since=None
                if kind=='select':selected=True
                if kind=='challenge':challenged=True
            elif r.scene=='arena_unknown':
                previous=None
                if unknown_since is None:unknown_since=time.monotonic()
                if time.monotonic()-unknown_since>25:
                    j.evidence(snap,obs,r)
                    raise TaskAttention('arena_unknown','竞技场当前页面未完整识别','未知页面/弹层零输入，保留所有记录后等待适配。')
            else:unknown_since=None
            cycle.wait(control)
        except PauseRun:previous=None;control.paused()
        except TaskAttention as exc:previous=None;control.attention(exc);unknown_since=None
