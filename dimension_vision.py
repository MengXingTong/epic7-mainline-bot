"""Small positive visual checks for observed Dimension UI; no guessed inputs."""
import numpy as np
import cv2
import json
from abyss_core import Token

def apply(image,observation):
    pixels=np.asarray(image.convert('RGB')).astype(float);h,w=pixels.shape[:2]
    def crop(rect):
        x,y,r,b=rect;return pixels[int(y*h):int(b*h),int(x*w):int(r*w)]
    panel=crop((.04,.20,.21,.32))
    gold=(panel[:,:,0]>45)&(panel[:,:,0]>panel[:,:,2]*1.22)&(panel[:,:,1]>panel[:,:,2]*1.12)
    edge=crop((.018,.20,.032,.77));bright=(edge[:,:,0]>180)&(edge[:,:,1]>145)&(edge[:,:,2]<190)
    right=crop((.215,.20,.23,.77));right_bright=(right[:,:,0]>180)&(right[:,:,1]>145)&(right[:,:,2]<190)
    if gold.mean()>.6 and bright.mean()>.07 and right_bright.mean()>.07:observation.visuals.add('loadout-contract-selected')
    claimed=crop((.915,.55,.95,.62))
    purple=((claimed[:,:,0]>80)&(claimed[:,:,2]>110)&(claimed[:,:,2]>claimed[:,:,0]*1.1)&(claimed[:,:,0]>claimed[:,:,1]*1.05)).astype('uint8')*255
    contours,_=cv2.findContours(purple,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x,y,ww,hh=cv2.boundingRect(contour);area=cv2.contourArea(contour);perimeter=cv2.arcLength(contour,True)
        hull=cv2.convexHull(contour);hull_area=cv2.contourArea(hull);hull_perimeter=cv2.arcLength(hull,True)
        tick=any(other is not contour and .08*ww*hh<cv2.contourArea(other)<.4*ww*hh and abs((cv2.boundingRect(other)[0]+cv2.boundingRect(other)[2]/2)-(x+ww/2))<ww*.35 and abs((cv2.boundingRect(other)[1]+cv2.boundingRect(other)[3]/2)-(y+hh/2))<hh*.35 for other in contours)
        if (.015*w<ww<.035*w and .015*w<hh<.035*w and .8<ww/hh<1.2 and hull_perimeter
                and hull_area>ww*hh*.65 and 4*np.pi*hull_area/hull_perimeter**2>.8 and tick):
            observation.visuals.add('dimension-supply-reward-claimed')
    loot=crop((.17,.16,.34,.30))
    loot_gold=(loot[:,:,0]>45)&(loot[:,:,0]>loot[:,:,2]*1.22)&(loot[:,:,1]>loot[:,:,2]*1.12)
    le=crop((.148,.17,.162,.7));re=crop((.34,.17,.35,.7))
    def gold_edge(a):return ((a[:,:,0]>180)&(a[:,:,1]>145)&(a[:,:,2]<190)).mean()
    if loot_gold.mean()>.6 and gold_edge(le)>.05 and gold_edge(re)>.05:observation.visuals.add('dimension-loot-first-selected')
    # Actual event-story Continue triangle, not an arbitrary blank-screen tap.
    lower=((pixels.min(axis=2)>90)&(pixels.max(axis=2)-pixels.min(axis=2)<20)).astype('uint8')*255
    lower[:int(.94*h)]=0;lower[:,:int(.45*w)]=0;lower[:,int(.55*w):]=0
    contours,_=cv2.findContours(lower,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    triangles=[]
    for contour in contours:
        x,y,ww,hh=cv2.boundingRect(contour)
        approx=cv2.approxPolyDP(contour,.06*cv2.arcLength(contour,True),True)
        if .005*w<ww<.02*w and .004*h<hh<.02*h and len(approx)==3 and cv2.contourArea(contour)>ww*hh*.3:
            vertices=approx[:,0,:];bottom=vertices[vertices[:,1].argmax()]
            if abs(float(bottom[0])-(x+ww/2))<ww*.25:triangles.append((x,y,ww,hh))
    if len(triangles)==1:
        x,y,ww,hh=triangles[0];observation.tokens.append(Token('事件叙事继续指示',x,y,ww,hh,source='dimension_event_continue',score=.99))
    green=((pixels[:,:,1]>80)&(pixels[:,:,1]>pixels[:,:,0]*1.3)&(pixels[:,:,1]>pixels[:,:,2]*1.3)).astype('uint8')*255
    green[:int(.13*h)]=0;green[int(.52*h):]=0;green[:,:int(.3*w)]=0;green[:,int(.73*w):]=0
    _,_,bars,_=cv2.connectedComponentsWithStats(green)
    full=[row for row in bars[1:] if .035*w<row[2]<.07*w and .003*h<row[3]<.015*h and row[4]>row[2]*row[3]*.8]
    if len(full)==4:observation.visuals.add('dimension-four-full-hp-members')
    # A currently actionable map node needs saturated blue, white crossed-icon
    # pixels and an independent bright pointer directly above it. Gray future
    # nodes or circles alone never authorize a click.
    mask=((pixels[:,:,2]>100)&(pixels[:,:,2]>pixels[:,:,0]*1.12)&(pixels[:,:,2]>pixels[:,:,1]*1.1)).astype('uint8')*255
    mask[:int(.15*h)]=0;mask[int(.83*h):]=0
    kernel=1 # Preserve the gap separating the actionable pointer from its room.;mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((kernel,kernel),np.uint8))
    n,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
    candidates=[]
    for (x,y,ww,hh,area),(cx,cy) in zip(stats[1:],centers[1:]):
        if not (.035*w<ww<.085*w and .05*h<hh<.14*h and .75<ww/hh<1.25 and area>ww*hh*.3):continue
        icon=pixels[y:y+hh,x:x+ww];white=((icon[:,:,0]>170)&(icon[:,:,1]>170)&(icon[:,:,2]>160)).sum()
        pointer=crop((max(0,(cx-.025*w)/w),max(0,(y-.05*h)/h),min(1,(cx+.025*w)/w),y/h))
        bright=((pointer[:,:,0]>190)&(pointer[:,:,1]>190)&(pointer[:,:,2]>190)).sum()
        if white>ww*hh*.025 and bright>w*h*.00003:candidates.append((x,y,ww,hh))
    if len(candidates)==1:
        x,y,ww,hh=candidates[0];observation.tokens.append(Token('当前高亮路线节点',int(x),int(y),int(ww),int(hh),source='dimension_route_visual',score=.99))
    if observation.has('战利品') and observation.has('英雄') and observation.find('彗星神殿：外围区域',region=(0,0,.35,.1)):
        from dimension_route_vision import analyze
        decision=analyze(image)
        if decision:
            observation.tokens.append(decision['token'])
            route=decision['route']
            observation.visuals.add('dimension_route_plan:'+json.dumps({'key':decision['key'],'nodes':route.nodes,'lower':route.minimum_combats,'upper':route.maximum_combats,'detail':route.detail,'edges':decision['edges'],'rooms':decision['rooms']},ensure_ascii=False,sort_keys=True))
    return observation
