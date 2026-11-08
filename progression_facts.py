"""Current game facts, not click acknowledgements, determine mainline progress.

No input, no retries, no event-name allowlist and no historical completion
fabrication. A forward unlocked node permits forward navigation; only a real
completion marker (or a proven lock->unlock change) completes the old stage.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass,field
from pathlib import Path
from map_identity import same_chapter,stage_order,valid_stage_identity,episode_handoff
from mainline_map import is_cleared,is_unlocked,row_markers


@dataclass(frozen=True)
class MapProgressFact:
    completed: bool=False
    forward_unlocked: bool=False
    reason: str='当前帧尚未显示本关完成或下一关解锁，继续观察；未判战败。'
    proof: dict=field(default_factory=dict)


def map_progress_fact(frame,entry,selected,rows):
    """Read the current map once; dispatch/playback/switch logs are not authority."""
    if not entry or not selected:return MapProgressFact()
    if not all(valid_stage_identity(row) for row in (entry,selected)):return MapProgressFact()
    same=same_chapter(entry,selected)
    if same:
        current=next((r for r in rows if r.get('stage')==entry.get('stage')),None)
        if current and is_cleared(current):
            return MapProgressFact(True,False,'当前地图明确显示原关卡完成。',dict(source='current_stage_clear',row=copy.deepcopy(current)))
        if current and current.get('completion')=='conflict':return MapProgressFact(reason='当前地图完成标记尚不一致，继续观察；未判失败。')
        successor=next((r for r in rows if r.get('stage')==entry.get('stage',-2)+1),None)
        before=entry.get('progress_before') or {}
        if (successor and is_unlocked(successor) and before.get('next_locked') is True
            and before.get('key')==entry.get('key')):
            return MapProgressFact(True,True,'原先锁定的下一关已在当前地图解锁。',dict(source='successor_lock_to_unlock',before=copy.deepcopy(before),row=copy.deepcopy(successor)))
        # A clipped predecessor is still a current image fact. It does not need
        # a perfect historical playback/notification/input acknowledgement chain.
        if (current is None and selected.get('stage')==entry.get('stage',-2)+1
            and is_unlocked(selected) and selected.get('cyan',0)>=.055):
            nearby=sorted((r for r in rows if selected['stage']<=r.get('stage',-1)<=selected['stage']+1),key=lambda r:r['stage'])
            if len(nearby)==2 and nearby[1]['stage']==nearby[0]['stage']+1:
                gap=nearby[1]['y']-nearby[0]['y'];y=nearby[0]['y']-gap
                if 121<=gap<=129 and 158<=y<=185:
                    import cv2,numpy as np
                    p=Path(__file__).resolve().parent/'assets'/'lock.png'
                    lock=cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),0) if p.is_file() else None
                    if lock is not None:
                        marker=row_markers(frame.image,cv2.cvtColor(frame.image,cv2.COLOR_BGR2HSV),round(y),lock)
                        if is_cleared(marker):
                            return MapProgressFact(True,True,'当前地图裁切区域仍明确显示原节点通关勾和下一关解锁。',dict(source='current_clipped_stage_clear',y=y,marker=marker))
        forward=(selected.get('stage')==entry.get('stage',-2)+1 and is_unlocked(selected)
                 and selected.get('cyan',0)>=.055)
    else:
        # Do not fabricate the old chapter's completion. A positively identified
        # later map may nevertheless continue from its new unlocked stage.
        next_chapter=(entry.get('episode')==selected.get('episode') and stage_order(selected)>stage_order(entry)
                      and selected.get('stage')==1)
        # A newly visible named Episode is not the old chapter's stage 1. Keep
        # the old active in the unresolved archive, never mark it completed.
        lock_score=selected.get('lock_score')
        handoff=(episode_handoff(entry,selected) and selected.get('locked') is False
                 and type(lock_score) in (int,float) and 0<=lock_score<=.81)
        forward=((next_chapter or handoff)
                 and is_unlocked(selected) and selected.get('cyan',0)>=.055)
    if forward:
        return MapProgressFact(False,True,'当前已明确选中后继未锁节点；继续向前，不虚构上一关完成。',dict(source='current_forward_unlocked',target=copy.deepcopy(selected)))
    return MapProgressFact()
