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
    from free_notices import notice_modal_band_visible
    sampled=cv2.resize(rgb,(1600,900))
    if notice_modal_band_visible(sampled):o.visuals.add('arena_notice_modal')
    return o
