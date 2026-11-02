"""Map-local positive completion evidence; missing stars are never a clear."""
from functools import lru_cache
import re
import cv2
import numpy as np

CLEAR_PROOFS=('已通关绿色勾','已通关关卡星级')

@lru_cache(maxsize=1)
def _badge_templates():
    templates=[]
    for radius in range(10,19):
        side=radius*2+5;c=radius+2;mask=np.zeros((side,side),np.uint8)
        cv2.circle(mask,(c,c),radius,255,max(2,round(radius*.17)))
        points=np.array([(round(c-radius*.55),c),(round(c-radius*.08),round(c+radius*.4)),(round(c+radius*.83),round(c-radius*.6))],np.int32)
        tick=np.zeros_like(mask);cv2.polylines(tick,[points],False,255,max(2,round(radius*.24)))
        mask|=tick
        yy,xx=np.ogrid[:side,:side];tick[(xx-c)**2+(yy-c)**2>(radius*.72)**2]=0
        templates.append((mask,tick))
    return tuple(templates)

def row_markers(image,hsv,y,lock_template=None):
    """Coordinates belong to the normalized 1600x900 game client, not the desktop."""
    y=int(y);top=max(0,y-65);bottom=min(image.shape[0],y+65)
    tile=hsv[top:bottom,:130];yy,xx=np.ogrid[top:bottom,:130]
    distance=(xx-68)**2+(yy-y)**2;ring=(distance>=39**2)&(distance<=61**2)
    cyan=(tile[:,:,0]>=80)&(tile[:,:,0]<=112)&(tile[:,:,1]>90)&(tile[:,:,2]>125)
    green=(tile[:,:,0]>=32)&(tile[:,:,0]<=85)&(tile[:,:,1]>115)&(tile[:,:,2]>90)
    area=max(1,np.count_nonzero(ring))
    cyan_score=float(np.count_nonzero(cyan&ring)/area)
    outline_green=float(np.count_nonzero(green&ring)/area)
    patch=hsv[max(0,y+7):min(image.shape[0],y+43),77:112]
    green_pixels=int(np.count_nonzero((patch[:,:,0]>=32)&(patch[:,:,0]<=85)&(patch[:,:,1]>115)&(patch[:,:,2]>90)))
    badge_score=0.0
    if green_pixels>=80 and outline_green>=.05:
        p=hsv[max(0,y):min(image.shape[0],y+58),65:125]
        binary=np.uint8((p[:,:,0]>=32)&(p[:,:,0]<=85)&(p[:,:,1]>115)&(p[:,:,2]>90))*255
        for template,tick in _badge_templates():
            if binary.shape[0]>=template.shape[0] and binary.shape[1]>=template.shape[1]:
                _,score,_,(x,z)=cv2.minMaxLoc(cv2.matchTemplate(binary,template,cv2.TM_CCOEFF_NORMED))
                candidate=binary[z:z+template.shape[0],x:x+template.shape[1]]
                if float(np.mean(candidate[tick>0]>0))>=.5:badge_score=max(badge_score,score)
    lock_score=0.0
    if lock_template is not None:
        gray=cv2.cvtColor(image[max(0,y+4):min(image.shape[0],y+48),68:119],cv2.COLOR_BGR2GRAY)
        if gray.shape[0]>=lock_template.shape[0] and gray.shape[1]>=lock_template.shape[1]:
            lock_score=float(cv2.matchTemplate(gray,lock_template,cv2.TM_CCOEFF_NORMED).max())
    locked=lock_score>.81
    clear_badge=not locked and badge_score>=.35
    return dict(cyan=round(cyan_score,4),green=green_pixels,green_ring=round(outline_green,4),clear_badge=clear_badge,clear_badge_score=round(badge_score,4),lock_score=lock_score,locked=locked,completion='cleared' if clear_badge else 'uncleared' if locked else 'unconfirmed')

_RATING_LABEL=re.compile(r'(?:通关星级|关卡星级|最高星级|通关评价|已获星数|已获得星星)')
def read_stage_rating(frame):
    """Only labeled stage ratings; friendship diamonds, hero rarity and chapter totals do not qualify.

    Return None if no supported rating is visible. Zero is a positively read zero,
    not a fallback for failed OCR. Never infer completion from a generic task icon.
    """
    labels=[]
    credit_y=min((w['y'] for w in frame.words if w['x']>=1100 and '信用等级' in w['text']),default=900)
    for word in frame.words:
        text=re.sub(r'\s+','',word['text'])
        if word['score']<.85 or not (1100<=word['x']<=1599 and 90<=word['y']<min(730,credit_y-15)):continue
        if _RATING_LABEL.search(text):labels.append(word)
    readings=[]
    for label in labels:
        nearby=[w for w in frame.words if w['score']>=.85 and 1100<=w['x']<=1599 and abs(w['y']-label['y'])<=38]
        numbers=set()
        for word in nearby:
            text=re.sub(r'\s+','',word['text'])
            numeric=re.search(r'(?:通关星级|关卡星级|最高星级|通关评价|已获星数|已获得星星)[:：]?([0-3])(?:/3|颗?星)?$',text)
            if not numeric:numeric=re.fullmatch(r'([0-3])/3',text)
            if numeric:numbers.add(int(numeric.group(1)))
            glyph_text=_RATING_LABEL.sub('',text).lstrip(':：')
            glyphs=re.fullmatch(r'[★☆]{3}',glyph_text)
            if glyphs:numbers.add(glyph_text.count('★'))
        if len(numbers)==1:readings.append(dict(count=numbers.pop(),source='labeled_stage_rating',label=label['text'],region=[1100,max(0,label['y']-38),1599,min(900,label['y']+38)]))
    counts={r['count'] for r in readings}
    return readings[0] if len(counts)==1 else None

def is_cleared(row):
    return bool(row and not row.get('locked') and row.get('completion')=='cleared')

def is_unlocked(row):
    return bool(row and 'lock_score' in row and not row.get('locked',row['lock_score']>.81))
