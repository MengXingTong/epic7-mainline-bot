"""NPC arena worker. Unknown screens never authorize input."""
from dataclasses import asdict
import time
from arena_core import Reading,classify,norm,one
from arena_journal import ArenaJournal,binding
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
            original=names[0]
            # The dim result HUD is already localized by this frame's detector.
            # Re-detecting a 480px enlargement distorts small grey glyphs and
            # repeats the expensive detector. Normalize this original field to
            # the recognizer's 48px height instead; never borrow the entry name.
            inside=(original.x>=image.width*.53 and original.y>=image.height*.065
                    and original.x+original.w<=image.width*.76
                    and original.y+original.h<=image.height*.11)
            if inside and original.w>0 and original.h>0:
                from PIL import ImageFilter
                pad=original.h*.1
                crop=image.crop((round(original.x-pad),round(original.y-pad),round(original.x+original.w+pad),round(original.y+original.h+pad)))
                part=crop.filter(ImageFilter.UnsharpMask(radius=1,percent=150,threshold=3))
                part=part.resize((max(1,round(part.width*48/part.height)),48),Image.Resampling.LANCZOS)
                rows,_=ocr(np.array(part)[:,:,::-1].copy(),use_det=False,use_cls=False)
                if rows and len(rows)==1:
                    text,score=rows[0]
                    if norm(text)==norm(original.text) and score>=.98:
                        obs.tokens.append(Token(original.text,original.x,original.y,original.w,original.h,source='arena_result_name_field_read',score=float(score)))
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
    return (reading.scene,reading.opponent,reading.stock,reading.cost,t.text if t else '')


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
        # UnifiedTransport already validates before AND after capture. Bind that
        # verified snapshot to the original selection rather than querying ADB
        # a third time. The send backend still rechecks freshness and its target.
        snap=tr.capture()
        if snap.binding!=bound:raise PcSafetyError('竞技场窗口/进程寿命/几何变化；停止，不自动重绑。')
        return snap
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    from arena_recovery import reconcile
    resumed=reconcile(root,request,ocr,capture,control)
    j=ArenaJournal(root,resumed or request['run_id'],settings['arena_count'])
    j.controller_run_id=request['run_id']  # Actor provenance is distinct from the retained batch/quota.
    j.maintenance_source=request.get('arena_maintenance')
    cycle=ObservationCycle();last_captured_at=None;last_sent=None;unknown_since=None
    while True:
        try:
            cycle.begin();check();snap=capture_fresh(capture,control)
            if last_captured_at is not None and snap.captured_at<=last_captured_at:
                raise PcSafetyError('不是独立的新帧。')
            last_captured_at=snap.captured_at
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
            kind=None;evidence=None
            if j.active:
                if r.scene in ('arena_battle','arena_result') and r.opponent!=j.active['opponent']:
                    raise TaskAttention('arena_opponent','当前对手与原入场不一致','不认领外来战斗或结果，不追加入场。')
                if r.scene=='arena_battle':
                    if not j.active['battle_evidence']:
                        evidence=j.evidence(snap,obs,r);j.battle(evidence,snap.binding)
                    if r.target and not any(a['kind']=='auto' and a.get('key')==j.active['key'] for a in j.state['actions']):kind='auto'
                elif r.scene=='arena_team_warning':
                    if j.team_warning_ready(r,snap.binding,snap.captured_at):kind='entry_confirm'
                    else:control.status('原入场确认正在等待游戏接受；不重复确认、不重新开战。',mode='waiting_evidence')
                elif r.scene=='arena_result':
                    # This complete result is already a fresh successor to the
                    # original entry and battle evidence. Persist the milestone,
                    # then close its verified control on this same current frame.
                    evidence=j.evidence(snap,obs,r);j.complete(evidence,snap.binding)
                    kind='result_close'
                elif r.scene not in ('arena_unknown',):
                    # A sent entry is never automatically repeated.
                    if time.monotonic()-j.active['entry_evidence']['captured_at']>15:
                        raise TaskAttention('arena_pending','等待原竞技场结果','保留已发送入场，不再次开战；当前尚无独立战斗/结算证据。')
            else:
                if r.scene in ('arena_lobby','arena_hub','arena_tab'):kind='navigate'
                elif r.scene=='arena_npc':
                    if j.run.get('pending_result'):
                        # One fresh, fully recognized list proves the prior
                        # result disappeared. Save that fact BEFORE selecting
                        # another opponent; this is not another entry or a win.
                        evidence=j.evidence(snap,obs,r);j.acknowledge_close(evidence,snap.binding)
                        if j.remaining==0:
                            control.status(f'NPC竞技场已完成 {j.run["wins"]}/{j.run["requested"]} 把；没有追加下一把。',mode='done');return
                    selected,challenged=j.navigation()
                    # A challenge send owns the pending free page transition.
                    # OCR name/coordinate jitter must not issue a second click.
                    if j.free_navigation_reset_context(r,snap.binding):kind='select'
                    elif challenged and (not selected or j.state['actions'].index(challenged)>j.state['actions'].index(selected)):
                        pass
                    elif not selected or selected['reading']['opponent']!=r.opponent:
                        kind='select'
                    elif (selected['status']=='sent' and selected['binding']==binding(snap.binding)
                          and {'arena_npc_first_selected','arena_challenge_enabled'}.issubset(obs.visuals)):
                        challenge=one(obs,'挑战',(.43,.86,.56,.97),.98)
                        if challenge:
                            r=Reading('arena_npc',challenge,r.opponent);kind='challenge'
                elif r.scene=='arena_team':
                    if j.entry_chain_matches(r,snap.binding):kind='entry'
                    else:
                        if ('arena_native_back' in obs.visuals
                            and j.return_to_npc_context(r,snap.binding,snap.captured_at)):
                            # Current-screen starts can already be on a team page.
                            # Return for a new list selection, without adopting
                            # that team or treating missing navigation as defeat.
                            r=Reading('arena_team',Token('原生返回',obs.width*.014,obs.height*.015,obs.width*.031,obs.height*.058,source='verified_native_back',score=1),r.opponent,r.stock,r.cost)
                            kind='return_to_npc'
                        else:
                            control.status('NPC队伍页：等待可核实的列表返回/选人来源；尚未发送开战，不重发入场。',mode='waiting_evidence')
                elif r.scene=='arena_result':
                    if j.run.get('pending_result'):kind='result_close'
            if kind:
                if kind=='result_close' and not j.result_close_ready(snap.captured_at):
                    # Sending is not acceptance. Reobserve this known result or
                    # its independent list return, without killing the worker.
                    cycle.wait(control);continue
                sig=signature(r)
                if kind not in ('result_close','return_to_npc') and last_sent and last_sent[0]==sig:
                    if time.monotonic()-last_sent[2]>12:raise TaskAttention('arena_no_transition','已发送控件尚未响应','不连点、不重发入场；保留原发送记录。')
                    cycle.wait(control);continue
                # Known controls use this cycle's current observation, never a
                # mandatory matching second OCR. At most one input per capture;
                # dispatch deduplication and all durable entry checks still apply.
                if wait_for_input(control,tr,snap):cycle.wait(control);continue
                if time.monotonic()-snap.captured_at>5:
                    control.status('当前截图处理已超时；零输入，重新截图核实，不延长旧帧时效。',mode='waiting_evidence')
                    cycle.wait(control);continue
                if evidence is None:evidence=j.evidence(snap,obs,r)
                if time.monotonic()-snap.captured_at>5:
                    control.status('留证后截图已过期；未预存或发送动作，重新取图。',mode='waiting_evidence')
                    cycle.wait(control);continue
                ident=j.intent(kind,r,evidence,snap.binding)
                try:
                    if kind=='return_to_npc':tr.back(snap)
                    else:tr.tap(snap,r.target)
                except TapNotSent:
                    j.sent(ident,'not_sent');raise TaskAttention('arena_not_sent','本次输入明确未发送','保留意图，重新核对后处理；不会自动重复入场。')
                except BaseException:
                    j.sent(ident,'unknown');raise
                j.sent(ident,'sent');last_sent=(signature(r),kind,time.monotonic());unknown_since=None
            elif r.scene=='arena_unknown':
                if unknown_since is None:unknown_since=time.monotonic()
                if time.monotonic()-unknown_since>25:
                    j.evidence(snap,obs,r)
                    raise TaskAttention('arena_unknown','竞技场当前页面未完整识别','未知页面/弹层零输入，保留所有记录后等待适配。')
            else:unknown_since=None
            cycle.wait(control)
        except PauseRun:control.paused()
        except TaskAttention as exc:control.attention(exc);unknown_since=None
