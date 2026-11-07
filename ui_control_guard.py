"""Last-mile glyph checks for controls whose screen role can change quickly.

A new pixel capture validates only the already OCR-identified controls. It never
refreshes old OCR, classifies a new page, or grants stage-entry permission.
"""
from __future__ import annotations
import copy,hashlib,time,uuid
from dataclasses import asdict,is_dataclass
import cv2
import numpy as np


def _rect(word):
    box=np.asarray(word.get('box'),dtype=float)
    if box.shape!=(4,2) or not np.isfinite(box).all():return None
    x1,y1=np.floor(box.min(axis=0)).astype(int);x2,y2=np.ceil(box.max(axis=0)).astype(int)
    if not (0<=x1<x2<=1600 and 0<=y1<y2<=900):return None
    return int(x1),int(y1),int(x2),int(y2)


def _glyph(image,rect):
    x1,y1,x2,y2=rect;tile=image[y1:y2,x1:x2].astype(np.int16)
    return (tile.min(axis=2)>=120)&(tile.max(axis=2)-tile.min(axis=2)<=55)


def matching_control_pixels(before,after,controls):
    if before.shape!=(900,1600,3) or after.shape!=before.shape:return None
    matches=[]
    for word in controls:
        rect=_rect(word)
        if rect is None:return None
        a=_glyph(before,rect);b=_glyph(after,rect);na=int(a.sum());nb=int(b.sum())
        if min(na,nb)<35:return None
        overlap=int(np.count_nonzero(a&b));recall=overlap/na;precision=overlap/nb
        if min(recall,precision)<.90:return None
        matches.append(dict(rect=list(rect),source_pixels=na,current_pixels=nb,recall=recall,precision=precision))
    return matches if matches else None


def verify_live_controls(r,controls,scope,*,clock=time.time):
    """Persist source+current pixels before input; failures never become proof."""
    from runner import ROOT,event
    from pc_backend import FrameExpired
    original=r.frame
    if not 0<=clock()-original.at<=5:raise FrameExpired('控件来源帧已过期；不发送输入。')
    r.ensure_game()
    window=getattr(getattr(r,'pc',None),'frame_window',None)
    original_window=asdict(window) if is_dataclass(window) else None
    from pc_message_backend import CaptureUnavailable
    try:image,raw_size=r._capture_pixels()
    except CaptureUnavailable:
        r.s['reason']='控件即时取图暂时不可用，零输入重新截图；不沿用旧计划。'
        event('control_pixels_changed',scope=scope,source_at=original.at,reason='capture_unavailable_no_input')
        return None
    captured_at=clock()
    window=getattr(getattr(r,'pc',None),'frame_window',None)
    current_window=asdict(window) if is_dataclass(window) else None
    if original_window!=current_window:
        raise RuntimeError('控件核对期间窗口身份或几何发生变化；停止输入。')
    if tuple(raw_size)!=tuple(original.raw_size):
        raise RuntimeError('控件即时核对期间目标几何发生变化；停止输入。')
    if not 0<=clock()-original.at<=5:raise FrameExpired('控件复核期间来源帧已过期；不延长旧帧时效。')
    matches=matching_control_pixels(original.image,image,controls)
    if scope=='chat-close':
        # Only the known side panel, not the animated battle behind it. A new
        # modal or changed conversation requires replanning, never a blind Back.
        delta=np.max(np.abs(original.image[120:790,885:1590].astype(np.int16)-image[120:790,885:1590].astype(np.int16)),axis=2)
        if float(np.mean(delta>24))>.06:matches=None
    directory=ROOT/'evidence';directory.mkdir(exist_ok=True)
    stem='live-control-'+scope+'-'+uuid.uuid4().hex
    paths=[]
    for suffix,pixels in (('source',original.image),('current',image)):
        ok,encoded=cv2.imencode('.png',pixels)
        if not ok:raise OSError('控件核对截图编码失败；不发送输入。')
        path=directory/(stem+'-'+suffix+'.png');path.write_bytes(encoded.tobytes());paths.append(str(path.relative_to(ROOT)))
    proof=dict(scope=scope,source_at=original.at,captured_at=captured_at,raw_size=list(raw_size),
               source_evidence=paths[0],current_evidence=paths[1],controls=copy.deepcopy(controls),matches=matches or [],window=current_window,
               source_sha256=hashlib.sha256(original.image.tobytes()).hexdigest(),
               current_sha256=hashlib.sha256(image.tobytes()).hexdigest())
    if matches is None:
        r.s['reason']='当前控件已变化，已丢弃旧点击计划；重新识别，不沿用右上角坐标。'
        event('control_pixels_changed',scope=scope,source_at=original.at,captured_at=captured_at,proof=proof)
        return None
    if not 0<=clock()-captured_at<=.75:
        event('control_pixels_expired',scope=scope,captured_at=captured_at,proof=proof)
        return None
    return proof
