"""Fixed battle-actor field rereads; no account identity/OCR threshold lowering."""
from __future__ import annotations
import copy,re
import cv2

ACTORS={'护卫队长克劳乌'}

def strengthen_actor(f,ocr):
    original=[w for w in f.words if w['text'] in ACTORS and .85<=w['score']<.98
              and 260<=w['x']<=560 and 770<=w['y']<=835]
    if len(original)!=1:return
    if not any(re.search(r'\d+\s*/\s*\d+',w['text']) and 155<w['x']<310 and 0<w['y']<70 for w in f.words):return
    if not any(re.fullmatch(r'\d+/\d+',w['text']) and w['score']>=.98 and 300<w['x']<580 and 835<w['y']<890 for w in f.words):return
    source=original[0];crop=f.image[785:835,280:540]
    readings=[]
    for scale in (2,3):
        rows,_=ocr(cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC))
        exact=[(text,float(score)) for _,text,score in rows or [] if text.strip()==source['text']]
        if len(exact)!=1 or exact[0][1]<.98:
            return _strengthen_krau_suffix(f,ocr,source)
        readings.append(exact[0])
    word=copy.deepcopy(source);word.update(score=min(score for text,score in readings),source='current_fixed_actor_roi_dual_read',verification_scores=[score for text,score in readings])
    f.words.append(word)


def _strengthen_krau_suffix(f,ocr,source):
    # The role prefix is not the character identity. Keep its original score;
    # independently verify the full actual name in the fixed suffix field.
    if source['text']!='护卫队长克劳乌' or source['score']<.95:return
    crop=f.image[789:831,414:512];scores=[]
    for scale in (1,2):
        image=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(image,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text.strip()!='克劳乌' or score<.98:return
        scores.append(float(score))
    f.words.append(dict(text='克劳乌',score=min(scores),x=463,y=810,
                        box=[[414,789],[512,789],[512,831],[414,831]],
                        source='current_fixed_actor_suffix_dual_read',verification_scores=scores))

def strengthen_enemy_levels(f,ocr):
    """Read current green level badge only after enemy-shield/live-HP geometry.

    A merged level/remaining-HP OCR line is not a reason to lower thresholds or
    borrow old enemy positions. Two crop reads must agree at >=.98.
    """
    import numpy as np
    if not any(re.search(r'\d+\s*/\s*\d+',w['text']) and 155<w['x']<310 and 0<w['y']<70 for w in f.words):return
    if not any(re.fullmatch(r'\d+/\d+',w['text']) and w['score']>=.98 and 300<w['x']<580 and 835<w['y']<890 for w in f.words):return
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV);tile=hsv[180:670,970:1500]
    green=np.uint8((tile[:,:,1]>90)&(tile[:,:,2]>90))*255
    _,_,stats,_=cv2.connectedComponentsWithStats(green)
    for x,y,w,h,area in stats[1:]:
        x,y,w,h,area=map(int,(x+970,y+180,w,h,area))
        if not (20<=w<=36 and 18<=h<=30 and 200<=area<=850):continue
        cx,cy=x+w/2,y+h/2
        shield=hsv[max(0,int(cy)-24):int(cy)+24,int(cx)-70:int(cx)-15]
        red=((shield[:,:,0]<12)|(shield[:,:,0]>170))&(shield[:,:,1]>150)&(shield[:,:,2]>110)
        bar=hsv[int(cy)-13:int(cy)+3,int(cx)+15:min(1599,int(cx)+90)]
        live=np.uint8((((bar[:,:,0]>=30)&(bar[:,:,0]<=85))|(bar[:,:,0]<12)|(bar[:,:,0]>170))&(bar[:,:,1]>90)&(bar[:,:,2]>90))*255
        contours,_=cv2.findContours(live,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if np.count_nonzero(red)<400 or not any(cv2.contourArea(c)>=12 and cv2.boundingRect(c)[0]<=6 and cv2.boundingRect(c)[2]>=3 and cv2.boundingRect(c)[3]>=3 for c in contours):continue
        existing=[row for row in f.words if abs(row['x']-cx)<=12 and abs(row['y']-cy)<=12]
        if existing:continue
        crop=f.image[y:y+h,x:x+w];reads=[]
        for scale in (2,3):
            rows,_=ocr(cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC),use_det=False,use_cls=False)
            if not rows or len(rows)!=1 or len(rows[0])!=2:break
            text,score=rows[0]
            if not re.fullmatch(r'[1-9]\d?',text.strip()) or score<.98:break
            reads.append((text.strip(),float(score)))
        if len(reads)!=2 or reads[0][0]!=reads[1][0]:continue
        f.words.append(dict(text=reads[0][0],score=min(r[1] for r in reads),x=cx,y=cy,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],
                            source='current_enemy_level_badge_dual_read',verification_scores=[r[1] for r in reads]))

def strengthen_chapter_reward_thresholds(f,ocr):
    """Current fixed star-threshold fields, detector dual-read at original score."""
    # Counter, exact map action and fixed label geometry are the anchors. A map
    # title is not a prerequisite; no account/identity field is read or modified.
    totals=[w for w in f.words if re.fullmatch(r'\d{1,3}/\d{1,3}',w['text']) and w['score']>=.98 and 20<w['x']<110 and 750<w['y']<795]
    if len(totals)!=1 or not any(w['text'] in ('观看故事','观看剧情','准备战斗') and w['score']>=.98 and w['x']>1250 and w['y']>780 for w in f.words):return
    for rect in ((185,752,225,794),(305,755,342,790),(425,752,470,794)):
        x1,y1,x2,y2=rect
        existing=[w for w in f.words if x1<=w['x']<=x2 and y1<=w['y']<=y2 and re.fullmatch(r'[1-9]\d{0,2}',w['text']) and w['score']>=.98]
        if existing:continue
        reads=[]
        for scale in (2,3):
            crop=cv2.resize(f.image[y1:y2,x1:x2],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
            rows,_=ocr(crop,use_cls=False)
            valid=bool(rows and len(rows)==1 and len(rows[0])==3 and re.fullmatch(r'[1-9]\d{0,2}',rows[0][1].strip()) and rows[0][2]>=.98)
            if valid:box,text,score=rows[0]
            else:
                direct,_=ocr(crop,use_det=False,use_cls=False)
                if not direct or len(direct)!=1 or len(direct[0])!=2:break
                text,score=direct[0]
                if not re.fullmatch(r'[1-9]\d{0,2}',text.strip()) or score<.98:break
            reads.append((text.strip(),float(score)))
        source='current_chapter_reward_threshold_dual_read'
        if len(reads)!=2 or reads[0][0]!=reads[1][0]:
            reads=_tight_chapter_threshold_reads(f,ocr,rect)
            source='current_chapter_reward_threshold_tight_dual_read'
        if len(reads)!=2 or reads[0][0]!=reads[1][0]:continue
        f.words.append(dict(text=reads[0][0],score=min(r[1] for r in reads),x=(x1+x2)/2,y=(y1+y2)/2,box=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],source=source,verification_scores=[r[1] for r in reads]))


def _tight_chapter_threshold_reads(f,ocr,rect):
    # Current white digit components within this fixed label only. Neither the
    # adjacent gold star nor trailing background/whitespace is a digit proof.
    import numpy as np
    x1,y1,x2,y2=rect;tile=cv2.cvtColor(f.image[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
    mask=np.uint8((tile[:,:,1]<90)&(tile[:,:,2]>180))*255
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    glyphs=[(int(x),int(y),int(w),int(h)) for x,y,w,h,area in stats[1:] if 12<=h<=30 and 2<=w<=25 and area>=20]
    if not 1<=len(glyphs)<=3:return []
    glyphs.sort()
    if max(y for x,y,w,h in glyphs)-min(y for x,y,w,h in glyphs)>3:return []
    if any(b[0]-(a[0]+a[2])>10 for a,b in zip(glyphs,glyphs[1:])):return []
    left=x1+min(x for x,y,w,h in glyphs)-2;right=x1+max(x+w for x,y,w,h in glyphs)+2
    top=y1+min(y for x,y,w,h in glyphs)-2;bottom=y1+max(y+h for x,y,w,h in glyphs)+2
    reads=[]
    for scale in (2,3):
        crop=cv2.resize(f.image[top:bottom,left:right],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return []
        text,score=rows[0]
        if not re.fullmatch(r'[1-9]\d{0,2}',text) or score<.98:return []
        reads.append((text,float(score)))
    return reads

def strengthen_orbis_unlock_notice(f,ocr):
    """Known free-guide body field, two current recognizer reads; no fuzzy text."""
    required=[('欧勒毕斯指南',(500,180,1100,280)),('可帮助继承者更好地了解《第七史诗》。',(400,495,1200,565)),('点击关闭',(650,600,950,710))]
    for text,(x1,y1,x2,y2) in required:
        words=[w for w in f.words if w['text']==text and w['score']>=.98 and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        if len(words)!=1:return
    if any(w['text']=='欧勒毕斯指南功能已开启。' and w['score']>=.98 for w in f.words):return
    scores=[];crop=f.image[484:510,660:942]
    for scale in (2,3):
        rows,_=ocr(cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC),use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!='欧勒毕斯指南功能已开启。' or score<.98:return
        scores.append(float(score))
    f.words.append(dict(text='欧勒毕斯指南功能已开启。',score=min(scores),x=801,y=497,box=[[660,484],[942,484],[942,510],[660,510]],source='current_free_orbis_notice_dual_read',verification_scores=scores))

def strengthen_summon_promo_title(f,ocr):
    """Same full current promo title twice; grants only independent ad close."""
    signals=[('立即前往召唤',(1250,680,1580,785)),('确认',(1250,785,1580,880)),('NEW!',(560,250,700,350))]
    for text,(x1,y1,x2,y2) in signals:
        if len([w for w in f.words if w['text']==text and w['score']>=.98 and x1<=w['x']<=x2 and y1<=w['y']<=y2])!=1:return
    original=[w for w in f.words if re.fullmatch(r'[\u4e00-\u9fff·]{2,20}',w['text']) and .8<=w['score']<.98 and 100<w['x']<750 and 150<w['y']<255]
    if len(original)!=1:return
    readings=[]
    for scale in (1,2):
        crop=cv2.resize(f.image[172:245,140:670],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!=original[0]['text'] or score<.98:return
        readings.append(float(score))
    word=copy.deepcopy(original[0]);word.update(score=min(readings),source='current_summon_promo_title_dual_read',verification_scores=readings)
    f.words.append(word)

def strengthen_owned_unit_levels(f,ocr):
    """Placed-owned-hero red grade badge + adjoining current HP, any 1..999."""
    import numpy as np
    required=[('准备战斗',(60,10,260,80)),('等级',(1250,80,1400,155)),('搜索',(1440,80,1599,155))]
    for text,(x1,y1,x2,y2) in required:
        if len([w for w in f.words if w['text']==text and w['score']>=.98 and x1<=w['x']<=x2 and y1<=w['y']<=y2])!=1:return
    if not any(w['text'] in ('维多丽卡','不成熟的维多丽卡') and w['score']>=.98 and 1260<w['x']<1530 and 280<w['y']<350 for w in f.words):return
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    for sx,sy in ((715,555),(375,562),(562,652)):
        left,top=sx-80,sy-340;tile=hsv[top:sy-230,left:sx+20]
        mask=np.uint8(((tile[:,:,0]<12)|(tile[:,:,0]>170))&(tile[:,:,1]>100)&(tile[:,:,2]>80))*255
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        candidates=[]
        for x,y,w,h,area in stats[1:]:
            x,y,w,h,area=map(int,(x+left,y+top,w,h,area))
            if not (20<=w<=38 and 20<=h<=38 and 220<=area<=1100):continue
            hp=hsv[y-6:y+12,x+w:min(1600,x+w+85)]
            green=np.uint8((hp[:,:,0]>=30)&(hp[:,:,0]<=85)&(hp[:,:,1]>90)&(hp[:,:,2]>90))*255
            contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if any(cv2.boundingRect(c)[0]<=5 and cv2.boundingRect(c)[2]>=55 and cv2.boundingRect(c)[3]>=4 for c in contours):candidates.append((x,y,w,h))
        if len(candidates)!=1:continue
        x,y,w,h=candidates[0];cx,cy=x+w/2,y+h/2
        if any(abs(row['x']-cx)<=15 and abs(row['y']-cy)<=15 and row['score']>=.98 for row in f.words):continue
        reads=[]
        for scale in (2,3):
            crop=cv2.resize(f.image[y:y+h,x:x+w],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
            rows,_=ocr(crop,use_det=False,use_cls=False)
            if not rows or len(rows)!=1 or len(rows[0])!=2:break
            text,score=rows[0]
            if not re.fullmatch(r'[1-9]\d{0,2}',text.strip()) or score<.98:break
            reads.append((text.strip(),float(score)))
        if len(reads)!=2 or reads[0][0]!=reads[1][0]:continue
        f.words.append(dict(text=reads[0][0],score=min(t[1] for t in reads),x=cx,y=cy,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],source='current_owned_unit_level_dual_read',verification_scores=[r[1] for r in reads]))

def strengthen_preparation_cost(f,ocr):
    """Discard glow suffix only with same-frame full numeric prefix + two reads."""
    if not any(w['text']=='准备战斗' and w['score']>=.98 and 60<w['x']<260 and 10<w['y']<80 for w in f.words):return
    if not any(w['text']=='进行任务' and w['score']>=.98 and 1300<w['x']<1599 and 770<w['y']<899 for w in f.words):return
    words=[w for w in f.words if re.match(r'^\d{1,6}\s*/\s*\d{1,6}',w['text']) and .90<=w['score'] and 1180<w['x']<1340 and 775<w['y']<880]
    if len(words)!=1:return
    original=words[0]
    if re.fullmatch(r'\d{1,6}\s*/\s*\d{1,6}',original['text']) and original['score']>=.98:return
    expected=re.match(r'^(\d{1,6}\s*/\s*\d{1,6})',original['text'])[1].replace(' ','')
    scores=[]
    for scale in (2,3):
        crop=cv2.resize(f.image[811:852,1225:1313],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text.strip()!=expected or score<.98:return
        scores.append(float(score))
    w=copy.deepcopy(original);w.update(text=expected,score=min(scores),source='current_preparation_cost_dual_read',verification_scores=scores)
    f.words.append(w)

def strengthen_free_single_summon_label(f,ocr):
    """Only the current FREE 1/1 button; never strengthen a priced summon."""
    signals=[('召唤',(60,0,220,85)),('可免费召唤1/1！',(950,720,1260,795)),('免费',(970,795,1090,865))]
    for text,(x1,y1,x2,y2) in signals:
        if len([w for w in f.words if w['text']==text and w['score']>=.98 and x1<=w['x']<=x2 and y1<=w['y']<=y2])!=1:return
    if any(w['text']=='召唤1次' and w['score']>=.98 and 1100<w['x']<1250 and 790<w['y']<875 for w in f.words):return
    scores=[]
    for scale in (2,3):
        crop=cv2.resize(f.image[808:851,1115:1220],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!='召唤1次' or score<.98:return
        scores.append(float(score))
    f.words.append(dict(text='召唤1次',score=min(scores),x=1167.5,y=829.5,box=[[1115,808],[1220,808],[1220,851],[1115,851]],source='current_free_single_summon_label_dual_read',verification_scores=scores))

def strengthen_wishlist_close(f,ocr):
    if len([w for w in f.words if w['text']=='添加愿望单' and w['score']>=.98 and 100<w['x']<420 and 40<w['y']<130])!=1:return
    if len([w for w in f.words if w['text']=='应用推荐列表' and w['score']>=.98 and 280<w['x']<620 and 735<w['y']<815])!=1:return
    if any(w['text']=='点击关闭' and w['score']>=.98 and 650<w['x']<950 and 830<w['y']<895 for w in f.words):return
    scores=[]
    for scale in (2,3):
        crop=cv2.resize(f.image[852:885,775:858],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!='点击关闭' or score<.98:return
        scores.append(float(score))
    f.words.append(dict(text='点击关闭',score=min(scores),x=816.5,y=868.5,box=[[775,852],[858,852],[858,885],[775,885]],source='current_wishlist_close_dual_read',verification_scores=scores))

def strengthen_wishlist_count(f,ocr):
    if not any(w['text']=='愿望单' and w['score']>=.98 and 780<w['x']<925 and 650<w['y']<735 for w in f.words):return
    if not any(w['text']=='可免费召唤1/1！' and w['score']>=.98 for w in f.words):return
    scores=[];value=None
    for scale in (2,3):
        crop=cv2.resize(f.image[680:715,927:996],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if not re.fullmatch(r'\d{1,3}/\d{1,3}',text) or score<.98:return
        if value is not None and text!=value:return
        value=text;scores.append(float(score))
    f.words.append(dict(text=value,score=min(scores),x=961.5,y=697.5,box=[[927,680],[996,680],[996,715],[927,715]],source='current_wishlist_count_dual_read',verification_scores=scores))


def strengthen_spirit_altar_purpose(f,ocr):
    """Current fixed purpose field, not a rewritten weak/misread prefix."""
    required=[('精灵祭坛',(500,180,1100,280)),('可进入精灵祭坛。',(500,465,1100,515)),('的各种符文！',(550,530,1050,580)),('点击关闭',(650,600,950,710))]
    for text,(x1,y1,x2,y2) in required:
        if len([w for w in f.words if w['text']==text and w['score']>=.98 and x1<=w['x']<=x2 and y1<=w['y']<=y2])!=1:return
    if any(w['text']=='请采集可用于英雄觉醒' and w['score']>=.98 and 600<w['x']<1000 and 510<w['y']<535 for w in f.words):return
    context=[w for w in f.words if re.fullmatch('请[采朵]集可用于英雄觉醒',w['text']) and w['score']>=.95 and 600<w['x']<1000 and 510<w['y']<535]
    if len(context)!=1:return
    scores=[]
    for scale in (1,2):
        crop=cv2.resize(f.image[508:538,747:930],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!='可用于英雄觉醒' or score<.98:return
        scores.append(float(score))
    f.words.append(dict(text='可用于英雄觉醒',score=min(scores),x=838.5,y=523,box=[[747,508],[930,508],[930,538],[747,538]],source='current_altar_purpose_dual_read',verification_scores=scores))


def strengthen_owned_card_level(f,ocr):
    """Read only the selected owned-card level, never its stars or old level."""
    required=[('准备战斗',(60,10,260,80)),('等级',(1250,80,1400,155)),('搜索',(1440,80,1599,155))]
    for text,(x1,y1,x2,y2) in required:
        if len([w for w in f.words if w['text']==text and w['score']>=.98 and x1<=w['x']<=x2 and y1<=w['y']<=y2])!=1:return
    if len([w for w in f.words if w['text'] in ('维多丽卡','不成熟的维多丽卡') and w['score']>=.98 and 1260<w['x']<1530 and 280<w['y']<350])!=1:return
    if any(re.fullmatch(r'[1-9]\d{0,2}',w['text']) and w['score']>=.98 and 1240<w['x']<1400 and 345<w['y']<400 for w in f.words):return
    originals=[w for w in f.words if re.fullmatch(r'[1-9]\d{0,2}[★☆*\s]*',w['text']) and w['score']>=.80 and 1240<w['x']<1400 and 345<w['y']<400]
    if len(originals)!=1:return
    expected=re.match(r'[1-9]\d{0,2}',originals[0]['text'])[0];reads=[]
    for scale in (2,3):
        crop=cv2.resize(f.image[354:396,1243:1287],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!=expected or score<.98:return
        reads.append(float(score))
    f.words.append(dict(text=expected,score=min(reads),x=1265,y=375,box=[[1243,354],[1287,354],[1287,396],[1243,396]],source='current_owned_card_level_dual_read',verification_scores=reads))


def strengthen_preparation_entry_label(f,ocr):
    """Separate the single-entry label from its glitter, never a repeat button."""
    for text,region in (('准备战斗',(60,10,260,80)),('闯关成功',(1180,200,1380,255)),('完成故事',(1180,245,1380,295)),('1名以上英雄存活',(1180,280,1450,330)),('管理队伍',(25,815,200,899))):
        x1,y1,x2,y2=region
        if len([w for w in f.words if w['text']==text and w['score']>=.98 and x1<w['x']<x2 and y1<w['y']<y2])!=1:return
    if any(w['text']=='进行任务' and w['score']>=.98 and 1300<w['x']<1599 and 770<w['y']<899 for w in f.words):return
    source=[w for w in f.words if re.fullmatch(r'进行任务[+＋*✦\s]*',w['text']) and w['score']>=.85 and 1300<w['x']<1599 and 770<w['y']<899]
    if len(source)!=1:return
    reads=[]
    for scale in (2,3):
        crop=cv2.resize(f.image[806:855,1370:1490],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        rows,_=ocr(crop,use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0]
        if text!='进行任务' or score<.98:return
        reads.append(float(score))
    f.words.append(dict(text='进行任务',score=min(reads),x=1430,y=830.5,box=[[1370,806],[1490,806],[1490,855],[1370,855]],source='current_preparation_single_entry_label_dual_read',verification_scores=reads))


def strengthen_map_stage_number(f,ocr):
    """Re-read only a weak map row's numeric prefix; never raise name confidence."""
    import hashlib,numpy as np
    import runner
    from mainline_map import row_markers
    if runner.classify(f)!='map':return
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV);candidates=[]
    for word in f.words:
        match=re.fullmatch(r'\s*([1-9]\d?)\s*[.．、。]\s*(.+)',word['text'])
        if not match or not .55<=word['score']<.85 or not (100<=word['x']<=650 and 190<=word['y']<=730):continue
        marker=row_markers(f.image,hsv,round(word['y']))
        if marker['cyan']<.055 or marker['clear_badge'] or marker['locked']:continue
        candidates.append((word,match))
    if len(candidates)!=1:return
    word,match=candidates[0];box=np.asarray(word['box'],dtype=float)
    if box.shape!=(4,2) or not np.isfinite(box).all():return
    left,top=box.min(axis=0);right,bottom=box.max(axis=0);height=bottom-top
    if not 15<=height<=60:return
    x1=max(0,int(left)-2);x2=min(1600,int(left)+round(height*.61*len(match[1])+2))
    y1=max(0,int(top)-2);y2=min(900,int(bottom)+3)
    crop=f.image[y1:y2,x1:x2];scores=[];dotted=False
    for scale in (2,3):
        rows,_=ocr(cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC),use_det=False,use_cls=False)
        if not rows or len(rows)!=1 or len(rows[0])!=2:return
        text,score=rows[0];read=re.fullmatch(r'([1-9]\d?)[.．]?',text.strip())
        if not read or read[1]!=match[1] or not 0<=score<=1:return
        dotted=dotted or text.strip().endswith(('.', '．'))
        scores.append(float(score))
    crop_kind='original_numeric_prefix'
    if min(scores)<.98:
        # A trailing row separator can weaken the whole recognition, even when
        # both reads agree on the original number. Isolate only tall current
        # digit glyphs, never guess a digit or promote the stage-name score.
        if not dotted:return
        rect=_tight_map_number_crop(f,(x1,y1,x2,y2),len(match[1]))
        if rect is None:return
        x1,y1,x2,y2=rect;crop=f.image[y1:y2,x1:x2];scores=[]
        for scale in (2,3):
            rows,_=ocr(cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC),use_det=False,use_cls=False)
            if not rows or len(rows)!=1 or len(rows[0])!=2:return
            text,score=rows[0]
            if text.strip()!=match[1] or not .98<=score<=1:return
            scores.append(float(score))
        crop_kind='current_numeric_glyphs'
    word['stage_number_verification']=dict(source='current_map_numeric_prefix_dual_read',number=int(match[1]),scores=scores,
        captured_at=f.at,crop=[x1,y1,x2,y2],crop_sha256=hashlib.sha256(crop.tobytes()).hexdigest(),crop_kind=crop_kind)


def _tight_map_number_crop(f,rect,digit_count):
    """Bound current bright numeral glyphs inside the original prefix only."""
    import numpy as np
    x1,y1,x2,y2=rect;height=y2-y1
    tile=cv2.cvtColor(f.image[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
    mask=np.uint8((tile[:,:,1]<130)&(tile[:,:,2]>170))*255
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    glyphs=[(int(x),int(y),int(w),int(h)) for x,y,w,h,area in stats[1:]
            if max(10,round(height*.4))<=h<=height-2 and 1<=w<=h and area>=max(12,h)]
    if len(glyphs)!=digit_count:return None
    glyphs.sort()
    if max(y for x,y,w,h in glyphs)-min(y for x,y,w,h in glyphs)>3:return None
    if max(h for x,y,w,h in glyphs)-min(h for x,y,w,h in glyphs)>3:return None
    if any(not 0<=b[0]-(a[0]+a[2])<=height*.45 for a,b in zip(glyphs,glyphs[1:])):return None
    return (max(x1,x1+min(x for x,y,w,h in glyphs)-2),
            max(y1,y1+min(y for x,y,w,h in glyphs)-2),
            min(x2,x1+max(x+w for x,y,w,h in glyphs)+2),
            min(y2,y1+max(y+h for x,y,w,h in glyphs)+2))
