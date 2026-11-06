"""Optional privately reviewed glyph controls; never create references from unknown UI.

Source captures stay in the local account profile, not in release/Git assets.
A reference only strengthens a fixed named control; business source guards still
apply and no paid summon button is part of this control contract.
"""
import hashlib,json
from pathlib import Path
import cv2,numpy as np
from runtime_paths import data_root


def covenant_free_tab(f):
    root=data_root()/'control_templates';manifest=root/'covenant-free-tab.json';image=root/'covenant-free-tab.png'
    if not manifest.is_file() or not image.is_file():return None
    data=json.loads(manifest.read_text(encoding='utf8'));blob=image.read_bytes()
    if (data.get('kind')!='reviewed_covenant_free_tab' or data.get('label')!='圣约召唤'
        or data.get('region')!=[60,780,230,835] or data.get('image_sha256')!=hashlib.sha256(blob).hexdigest()
        or not data.get('source_user_instruction') or not data.get('source_request_sha256')):return None
    reference=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_GRAYSCALE)
    if reference is None or reference.shape!=(55,170) or np.std(reference)<15:return None
    current=cv2.cvtColor(f.image[780:835,60:230],cv2.COLOR_BGR2GRAY)
    score=float(cv2.matchTemplate(current,reference,cv2.TM_CCOEFF_NORMED)[0,0])
    if score<.98:return None
    return dict(text='圣约召唤',x=145,y=807.5,score=score,source='reviewed_local_covenant_tab_template',reference_sha256=data['image_sha256'])


def covenant_back(f):
    """Only a privately reviewed, fixed back glyph; never OS-back or paid input."""
    root=data_root()/'control_templates'
    manifest=root/'covenant-back.json';image=root/'covenant-back.png'
    if not manifest.is_file() or not image.is_file():return None
    try:
        data=json.loads(manifest.read_text(encoding='utf8'));blob=image.read_bytes()
        if not isinstance(data,dict):return None
        if (data.get('kind')!='reviewed_covenant_back' or data.get('region')!=[18,12,76,72]
            or data.get('image_sha256')!=hashlib.sha256(blob).hexdigest()
            or not data.get('source_user_instruction')
            or any(not isinstance(data.get(k),str) or len(data[k])!=64 for k in ('source_request_sha256','source_capture_sha256'))):return None
        reference=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_GRAYSCALE)
        if reference is None or reference.shape!=(60,58) or np.std(reference)<25:return None
        current=cv2.cvtColor(f.image[12:72,18:76],cv2.COLOR_BGR2GRAY)
        if current.shape!=reference.shape:return None
        # Correlation alone accepts a dimmed glyph behind a modal. Both the
        # spatial match and absolute brightness must survive the current frame.
        score=float(cv2.matchTemplate(current,reference,cv2.TM_CCOEFF_NORMED)[0,0])
        if score<.995 or float(np.mean(np.abs(current.astype(float)-reference)))>3:return None
        return dict(text='返回',x=47,y=42,score=score,source='reviewed_local_covenant_back',reference_sha256=data['image_sha256'])
    except (OSError,ValueError,TypeError,cv2.error):return None
