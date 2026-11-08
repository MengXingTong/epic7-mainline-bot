"""Position-constrained native arena HUD checks, without private image templates."""
import numpy as np
import cv2


def apply(image,o):
    rgb=np.asarray(image.convert('RGB'));h,w=rgb.shape[:2]
    def crop(rect):
        a,b,c,d=rect
        return rgb[round(b*h):round(d*h),round(a*w):round(c*w)]
    pause=crop((.958,.014,.987,.079))
    white=np.uint8(np.min(pause,axis=2)>215)*255
    n,labels,stats,centers=cv2.connectedComponentsWithStats(white)
    bars=[s for s in stats[1:] if s[4]>=pause.size/3*.025 and s[3]>=pause.shape[0]*.45 and 1.8<=s[3]/max(s[2],1)<=8]
    if len(bars)==2 and abs(int(bars[0][1])-int(bars[1][1]))<pause.shape[0]*.14:
        o.visuals.add('arena_pause')
    for name,rect in (('left',(.24,.030,.45,.050)),('right',(.55,.030,.75,.050))):
        bar=crop(rect).astype(float)
        if np.mean((bar[:,:,1]>80)&(bar[:,:,1]>bar[:,:,0]*1.2)&(bar[:,:,1]>bar[:,:,2]*1.3))>.35:
            o.visuals.add('arena_hp_'+name)
    auto=crop((.86,.014,.90,.075)).astype(float)
    colored=np.mean((auto[:,:,1]>100)&(auto[:,:,1]>auto[:,:,0]*1.25)&(auto[:,:,1]>auto[:,:,2]*1.2))
    if colored>.035:o.visuals.add('arena_auto_on')
    if np.mean(np.min(auto,axis=2)>210)>.10:o.visuals.add('arena_auto_white')
    # These are separate acceptance facts, not inferred from OCR containing
    # “挑战”. The retiring shattered row keeps that text while it is disabled.
    row=crop((.30,.36,.75,.382)).astype(float)
    yellow=(row[:,:,0]>140)&(row[:,:,1]>125)&(row[:,:,2]<row[:,:,1]*.8)
    if np.mean(yellow)>.55:o.visuals.add('arena_npc_first_selected')
    button=crop((.42,.89,.58,.95)).astype(float)
    green=(button[:,:,1]>40)&(button[:,:,1]>button[:,:,0]*1.5)&(button[:,:,1]>button[:,:,2]*1.2)
    if np.mean(green)>.65 and np.mean(np.min(button,axis=2)>215)>.02:
        o.visuals.add('arena_challenge_enabled')
    confirm=crop((.43,.70,.57,.775)).astype(float)
    blue=(confirm[:,:,2]>35)&(confirm[:,:,2]>confirm[:,:,1]*1.2)&(confirm[:,:,1]>confirm[:,:,0]*1.15)
    if np.mean(blue)>.60 and np.mean(np.min(confirm,axis=2)>215)>.025:
        o.visuals.add('arena_team_warning_confirm')
    arrow=crop((.014,.015,.045,.073))
    mask=np.min(arrow,axis=2)>215
    ys,xs=np.where(mask)
    if len(xs)>arrow.shape[0]*arrow.shape[1]*.10:
        lo,hi=ys.min(),ys.max();height=hi-lo+1
        ends=xs[(ys<lo+height*.2)|(ys>hi-height*.2)]
        middle=xs[abs(ys-(lo+hi)/2)<height*.13]
        if (height>arrow.shape[0]*.65 and len(ends) and len(middle)
            and ends.mean()>middle.min()+arrow.shape[1]*.35):
            o.visuals.add('arena_native_back')
    from free_notices import notice_modal_band_visible
    sampled=cv2.resize(rgb,(1600,900))
    if notice_modal_band_visible(sampled):o.visuals.add('arena_notice_modal')
    return o
