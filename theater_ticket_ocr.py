"""Current-frame ticket inventory refinement; never authorizes an input."""
import re
import numpy as np
from PIL import Image, ImageEnhance
from abyss_core import Token
from theater_core import norm, confident

SOURCE = 'theater_ticket_stock_ocr'
STOCK_REGION = (.36, .50, .65, .60)
BOX = (660, 470, 900, 540)
MIN_SCORE = .90


def _in_region(token, width, height, region):
    x,y=token.center;x0,y0,x1,y1=region
    return x0*width<x<x1*width and y0*height<y<y1*height



def _split_stock(sampled, tokens, width, height, ocr, original):
    """Punctuation-independent label/digits, each >=.98 in BOTH views.

    The split is fixed by the observed field layout, never by an expected
    digit. All digits must exactly match the primary numeric string; a crop
    truncation, extra field, conflict or weak read remains zero-input.
    """
    boxes = ((660,470,749,540), (749,470,900,540))
    verified = []
    for brightness in (1,2):
        for index, box in enumerate(boxes):
            roi = sampled.crop(box)
            view = ImageEnhance.Brightness(roi).enhance(brightness).resize(
                (roi.width*3, roi.height*3), Image.Resampling.LANCZOS)
            results,_ = ocr(np.asarray(view)[:,:,::-1].copy())
            if not results or len(results) != 1:
                return tokens
            points,text,score = results[0]
            expected = '持有' if index == 0 else original[1]
            if (norm(text) != expected or score < .98 or not points
                    or min(p[0] for p in points) < 0 or min(p[1] for p in points) < 0
                    or max(p[0] for p in points) > view.width or max(p[1] for p in points) > view.height
                    or max(p[0] for p in points) <= min(p[0] for p in points)
                    or max(p[1] for p in points) <= min(p[1] for p in points)):
                return tokens
            verified.append((box[0]+min(p[0] for p in points)/3,
                box[1]+min(p[1] for p in points)/3,box[0]+max(p[0] for p in points)/3,
                box[1]+max(p[1] for p in points)/3,float(score)))
    x=min(v[0] for v in verified);y=min(v[1] for v in verified)
    right=max(v[2] for v in verified);bottom=max(v[3] for v in verified)
    token=Token('持有'+original[1],x*width/1600,y*height/900,(right-x)*width/1600,
                (bottom-y)*height/900,source=SOURCE,score=min(v[4] for v in verified))
    return [*tokens,token] if _in_region(token,width,height,STOCK_REGION) else tokens


def refine_ticket_stock(sampled, tokens, width, height, ocr):
    """Keep the primary; require two full >=.90 or four split >=.98 reads.

    Only the exact, position-verified one-ticket modal can trigger this crop.
    No field confidence is lowered and no historical stock is substituted.
    """
    titles=[t for t in tokens if norm(t.text)=='使用剧场门票']
    questions=[t for t in tokens if _in_region(t,width,height,(.24,.28,.77,.39))
               and any(v in norm(t.text) for v in ('使用','消耗','观览吗'))]
    stocks=[t for t in tokens if norm(t.text).startswith('持有')
            and _in_region(t,width,height,STOCK_REGION)]
    if (len(titles)!=1 or not confident(titles[0])
            or not _in_region(titles[0],width,height,(.35,.15,.66,.29))
            or len(questions)!=1 or not confident(questions[0])
            or norm(questions[0].text)!='确定要使用1张剧场门票来立即观览吗'
            or len(stocks)!=1 or confident(stocks[0])):
        return tokens
    original=re.fullmatch(r'持有([0-9]{1,6})',norm(stocks[0].text))
    if not original:
        return tokens
    roi=sampled.crop(BOX)
    variants=(roi.resize((720,210),Image.Resampling.LANCZOS),
              ImageEnhance.Brightness(roi).enhance(2).resize((720,210),Image.Resampling.LANCZOS))
    refined=[]
    weak=False
    for variant in variants:
        results,_=ocr(np.asarray(variant)[:,:,::-1].copy())
        candidates=[]
        for box,text,score in results or []:
            if not norm(text).startswith('持有'):
                continue
            match=re.fullmatch(r'持有([0-9]{1,6})',norm(text))
            if not match:
                return tokens
            if score<MIN_SCORE:
                weak=True
            if (not box or min(p[0] for p in box)<0 or min(p[1] for p in box)<0
                    or max(p[0] for p in box)>variant.width or max(p[1] for p in box)>variant.height
                    or max(p[0] for p in box)<=min(p[0] for p in box)
                    or max(p[1] for p in box)<=min(p[1] for p in box)):
                return tokens
            x=min(p[0] for p in box)/3+BOX[0];y=min(p[1] for p in box)/3+BOX[1]
            w=(max(p[0] for p in box)-min(p[0] for p in box))/3
            h=(max(p[1] for p in box)-min(p[1] for p in box))/3
            t=Token('持有'+match[1],x*width/1600,y*height/900,w*width/1600,h*height/900,
                    source=SOURCE,score=float(score))
            if not _in_region(t,width,height,STOCK_REGION):
                return tokens
            candidates.append((int(match[1]),t))
        if len(candidates)!=1 or candidates[0][0]!=int(original[1]):
            return tokens
        refined.append(candidates[0])
    if refined[0][0]!=refined[1][0]:
        return tokens
    if weak:
        return _split_stock(sampled,tokens,width,height,ocr,original)
    t=min((v[1] for v in refined),key=lambda t:t.score)
    return [*tokens,t]
