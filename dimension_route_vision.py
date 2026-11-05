"""Observed-map glyph/road analyzer. Templates are derived in-memory from this
frame's independently highlighted rooms; no screenshots/assets are distributed.
Unrecognized sprites, unverified roads and offscreen regions are not invented.
"""
import cv2
import numpy as np
from abyss_core import Token
from dimension_routes import Node,avoid_combat


def analyze(image):
    rgb=np.asarray(image.convert('RGB')).astype(float);h,w=rgb.shape[:2]
    blue=((rgb[:,:,2]>100)&(rgb[:,:,2]>rgb[:,:,0]*1.12)&(rgb[:,:,2]>rgb[:,:,1]*1.1)).astype('uint8')*255
    blue[:int(.15*h)]=0;blue[int(.83*h):]=0
    blue=cv2.morphologyEx(blue,cv2.MORPH_CLOSE,np.ones((1,1),np.uint8))
    _,_,stats,centers=cv2.connectedComponentsWithStats(blue)
    rooms=[];templates={}
    for (x,y,ww,hh,area),(cx,cy) in zip(stats[1:],centers[1:]):
        if not (.035*w<ww<.085*w and .05*h<hh<.14*h and .75<ww/hh<1.25 and area>ww*hh*.3):continue
        pointer=rgb[max(0,int(y-.05*h)):y,max(0,int(cx-.025*w)):min(w,int(cx+.025*w))]
        available=((pointer.min(axis=2)>190).sum() if pointer.size else 0)>=w*h*.00003
        icon=rgb[y:y+hh,x:x+ww]
        ink=((icon.min(axis=2)>190)&(icon.max(axis=2)-icon.min(axis=2)<35)).astype('uint8')*255
        _,labels,parts,pc=cv2.connectedComponentsWithStats(ink)
        main=[(i,row) for i,row in enumerate(parts[1:],1) if row[4]>ww*hh*.02]
        if not main:continue
        main.sort(key=lambda row:row[1][4],reverse=True);body=main[0][1]
        question=any(body[4]>row[4]*4 and row[1]>body[1]+body[3]+1 and .12*ww<row[2]<.3*ww and .12*hh<row[3]<.3*hh for i,row in main[1:])
        flag=body[2]/body[3]>1.2 and body[4]>body[2]*body[3]*.45 and body[2]>ww*.5 and body[3]>hh*.3
        if question:kind='unknown';glyph='question'
        elif flag:kind='unknown';glyph='flag'
        elif (len(main)==2 and body[2]/body[3]<.8 and body[3]>.6*hh and main[1][1][1]>=body[1]+body[3]-.05*hh and main[1][1][4]<body[4]*.2):kind='rest';glyph='rest'
        elif len(main)==3 and all(row[4]>ww*hh*.025 for i,row in main):kind='battle';glyph='swords'
        else:continue
        mask=np.zeros_like(ink)
        for i,row in main:mask[labels==i]=255
        yy,xx=np.where(mask);dx=int(xx.min());dy=int(yy.min());template=mask[dy:int(yy.max())+1,dx:int(xx.max())+1]
        templates.setdefault(glyph,(template,dx,dy,float(ww),float(hh),kind))
        if not available:continue
        cx=float(x+ww/2);cy=float(y+hh/2)
        ident=kind+'@'+str(round(cx/w*50))+':'+str(round(cy/h*50))
        rooms.append(dict(id=ident,kind=kind,x=float(cx),y=float(cy),rect=(int(x),int(y),int(ww),int(hh)),available=True))
    if not rooms:return None
    gray=cv2.cvtColor(rgb.astype('uint8'),cv2.COLOR_RGB2GRAY)
    for glyph,(template,dx,dy,ww,hh,kind) in templates.items():
        result=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
        result[:int(.12*h)]=0;result[int(.8*h):]=0
        for _ in range(32):
            _,score,_,(x,y)=cv2.minMaxLoc(result)
            if score<.84:break
            result[max(0,y-int(hh)):y+int(hh),max(0,x-int(ww)):x+int(ww)]=0
            cx=x-dx+ww/2;cy=y-dy+hh/2
            if any(abs(cx-n['x'])<.04*w and abs(cy-n['y'])<.06*h for n in rooms):continue
            ident=kind+'@'+str(round(cx/w*50))+':'+str(round(cy/h*50))
            rooms.append(dict(id=ident,kind=kind,x=cx,y=cy,rect=(int(cx-ww/2),int(cy-hh/2),int(ww),int(hh)),available=False))
    neutral=((rgb.min(axis=2)>65)&(rgb.max(axis=2)-rgb.min(axis=2)<35)).astype('uint8')*255
    _,_,parts,points=cv2.connectedComponentsWithStats(neutral)
    scale=w/1212
    dots=np.array([(x,y) for (xx,yy,ww,hh,a),(x,y) in zip(parts[1:],points[1:]) if 1<=ww<=7*scale and 1<=hh<=7*scale and 2*scale*scale<=a<=40*scale*scale])
    edges={'current':[]}
    available=[n for n in rooms if n['available']]
    for n in available:edges['current'].append(n['id'])
    for a in rooms:
        for b in rooms:
            if not .1*w<b['x']-a['x']<.35*w or len(dots)<5:continue
            start=np.array([a['x'],a['y']]);delta=np.array([b['x'],b['y']])-start;length=np.linalg.norm(delta)
            projection=(dots-start)@delta/(length*length)
            residual=np.linalg.norm((dots-start)-projection[:,None]*delta,axis=1)
            line=np.sort(projection[(projection>.20)&(projection<.80)&(residual<.008*h)]*length)
            if len(line)<5 or line[-1]-line[0]<length*.3:continue
            gaps=np.diff(line);median=float(np.median(gaps))
            regular=((gaps>median*.65)&(gaps<median*1.35)).mean()
            if .007*w<median<.017*w and regular>=.75:edges.setdefault(a['id'],[]).append(b['id'])
    beyond=[n for n in rooms if n['x']>max(a['x'] for a in available)+.1*w]
    if beyond:
        frontier=min(n['x'] for n in beyond);goals=[n['id'] for n in beyond if n['x']<frontier+.05*w]
    else:goals=[n['id'] for n in available]
    route=avoid_combat([Node('current','event')]+[Node(n['id'],n['kind']) for n in rooms],edges,'current',goals,full_graph=False)
    if not route and len(available)==1 and available[0]['kind']=='unknown':
        route=avoid_combat([Node('current','event'),Node(available[0]['id'],'unknown')],{'current':[available[0]['id']]},'current',[available[0]['id']],full_graph=False)
    if not route or len(route.nodes)<2:return None
    chosen=next(n for n in available if n['id']==route.nodes[1])
    if chosen['kind'] not in ('unknown','rest'):return None # Never silently turn avoid-combat into an optional fight.
    x,y,ww,hh=chosen['rect']
    token=Token('避战候选路线节点',x,y,ww,hh,source='dimension_route_avoid',score=.99)
    return dict(token=token,key=chosen['id'],route=route,rooms=rooms,edges=edges)
