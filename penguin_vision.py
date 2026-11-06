"""Local OCR and same-session altar currency comparison; no shipped account images."""
import re
import numpy as np
from PIL import Image
from abyss_core import Observation, Token


def currency_signature(image, region):
    w,h=image.size
    crop=np.asarray(image.crop(tuple(round(v*(w if i%2==0 else h)) for i,v in enumerate(region))))
    r,g,b=[crop[:,:,i].astype(float) for i in range(3)]
    mask=(r>85)&(r>g*1.55)&(r>b*1.8)
    ys,xs=np.nonzero(mask)
    if len(xs)<20:
        return None
    mask=mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    if mask.shape[0]<8 or mask.shape[1]<8:
        return None
    small=np.asarray(Image.fromarray(mask.astype('uint8')*255).resize((16,16),Image.Resampling.NEAREST))>0
    return ''.join('1' if v else '0' for v in small.flat)


def same_currency(a,b):
    if not isinstance(a,str) or not isinstance(b,str) or len(a)!=256 or len(b)!=256:
        return False
    intersection=sum(x==y=='1' for x,y in zip(a,b))
    union=sum(x=='1' or y=='1' for x,y in zip(a,b))
    return bool(union and intersection/union>=.70)


def read_observation(image,ocr,captured_at):
    w,h=image.size
    sampled=image.resize((1600,900),Image.Resampling.LANCZOS)
    tokens=[]
    def read(crop,ox,oy,sx,sy,source):
        rows,_=ocr(np.asarray(crop)[:,:,::-1].copy())
        for box,text,score in rows or []:
            x=min(p[0] for p in box);y=min(p[1] for p in box)
            tokens.append(Token(text,ox+x*sx,oy+y*sy,
                (max(p[0] for p in box)-x)*sx,(max(p[1] for p in box)-y)*sy,
                source=source,score=float(score)))
    read(sampled,0,0,w/1600,h/900,'ocr')
    def field(region):
        x1,y1,x2,y2=region
        box=(round(x1*w),round(y1*h),round(x2*w),round(y2*h))
        crop=image.crop(box);read(crop.resize((crop.width*4,crop.height*4)),box[0],box[1],.25,.25,'penguin_field')
    # Tiny Sanctuary text disappears in full-screen OCR on the tested 1064x599 client.
    field((.00,.22,.12,.29))
    modal=any(t.text=='购买商品' and t.score>=.98 for t in tokens)
    altar=not modal and any(t.text=='成长祭坛' and .18*h<t.center[1]<.27*h for t in tokens)
    if modal:
        for region in ((.43,.54,.58,.63),(.48,.78,.60,.86),(.32,.62,.38,.70),(.62,.62,.68,.70)):
            field(region)
    elif altar:
        for region in ((.865,.19,.955,.26),(.108,.70,.160,.79)):
            field(region)
    # Merge overlapping reads of the SAME label only; contradictory numeric reads survive.
    unique=[]
    for t in sorted(tokens,key=lambda t:t.score or 0,reverse=True):
        if any(t.text==p.text and abs(t.center[0]-p.center[0])<w*.018
               and abs(t.center[1]-p.center[1])<h*.018 for p in unique):continue
        unique.append(t)
    # Dimmed background text must never be treated as an active control.
    visible=[]
    for t in unique:
        patch=np.asarray(image.crop((max(0,int(t.x)),max(0,int(t.y)),min(w,int(t.x+t.w)+1),min(h,int(t.y+t.h)+1))))
        if patch.size and np.mean((np.max(patch[:,:,:3],axis=2)>165)&(np.mean(patch[:,:,:3],axis=2)>90))>.015:
            visible.append(t)
    visuals=set()
    if modal:
        signature=currency_signature(image,(.463,.786,.500,.852))
    elif altar:
        signature=currency_signature(image,(.070,.709,.111,.785))
        header=currency_signature(image,(.837,.187,.872,.263))
        if not same_currency(signature,header):signature=None
    else:signature=None
    if signature:visuals.add('penguin_currency:'+signature)
    return Observation(w,h,visible,captured_at,visuals)
