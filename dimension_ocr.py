"""Extra OCR limited to observed recruitment cost cells, never account identity."""
import re
import numpy as np
from abyss_core import Token,normalize


def enrich(ocr,image,o):
    roster=any(o.find(r+'招募券',region=(0,0,.25,.1)) for r in ('骑士','战士','精灵师','盗贼'))
    expedition=o.find('彗星神殿：外围区域',region=(0,0,.35,.1))
    if roster or expedition:
        rect=(int(.91*o.width),int(.025*o.height),int(.958*o.width),int(.07*o.height))
        crop=image.crop(rect);crop=crop.resize((crop.width*4,crop.height*4))
        results,_=ocr(np.array(crop)[:,:,::-1].copy())
        pieces=sorted(results or [],key=lambda row:min(p[0] for p in row[0]))
        joined=''.join(normalize(text) for box,text,score in pieces)
        readings=[(joined,min(float(score) for box,text,score in pieces))] if pieces and re.fullmatch(r'\d{1,2}/\d{1,2}',joined) and all(score>=.85 for box,text,score in pieces) else []
        if len(readings)==1:
            text,score=readings[0];o.tokens.append(Token(text,rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1],source='dimension_budget',score=score))
    if expedition:
        rect=(int(.727*o.width),int(.02*o.height),int(.758*o.width),int(.075*o.height))
        crop=image.crop(rect);crop=crop.resize((crop.width*4,crop.height*4));results,_=ocr(np.array(crop)[:,:,::-1].copy())
        pieces=sorted(results or [],key=lambda row:min(p[0] for p in row[0]));joined=''.join(normalize(text) for box,text,score in pieces)
        if pieces and re.fullmatch(r'\d{1,6}',joined) and all(score>=.85 for box,text,score in pieces):
            o.tokens.append(Token(joined,rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1],source='dimension_fragments',score=min(float(score) for box,text,score in pieces)))
    if expedition:
        rect=(int(.812*o.width),int(.02*o.height),int(.853*o.width),int(.075*o.height))
        crop=image.crop(rect);crop=crop.resize((crop.width*4,crop.height*4));results,_=ocr(np.array(crop)[:,:,::-1].copy())
        pieces=sorted(results or [],key=lambda row:min(p[0] for p in row[0]));joined=''.join(normalize(text) for box,text,score in pieces)
        if pieces and re.fullmatch(r'\d{1,2}/\d{1,2}',joined) and all(score>=.85 for box,text,score in pieces):
            o.tokens.append(Token(joined,rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1],source='dimension_life',score=min(float(score) for box,text,score in pieces)))
    if not roster:return o
    # Each visible name has its own right-hand cost cell. Keep exact name association.
    for name in list(o.tokens):
        x,y=name.center
        if not (.28*o.width<x<.43*o.width and .12*o.height<y<.84*o.height):continue
        if not re.fullmatch(r'[\u4e00-\u9fff]{2,14}',name.text):continue
        rect=(int(.466*o.width),int(y+.03*o.height),int(.493*o.width),int(y+.071*o.height))
        crop=image.crop(rect);crop=crop.resize((crop.width*4,crop.height*4))
        results,_=ocr(np.array(crop)[:,:,::-1].copy())
        numbers=[(int(text),float(score)) for box,text,score in results or [] if re.fullmatch(r'[1-9]',normalize(text)) and score>=.85]
        if len(numbers)==1:
            n,score=numbers[0];o.tokens.append(Token(str(n),rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1],source='dimension_cost:'+name.text,score=score))
    return o
