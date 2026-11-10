"""Legacy story-map support and explicit successful Saint 3-7 farming policy.

Pure scene readers plus a controller using the existing guarded Runner transport.
Only Saint 3-7 may repeat, and only after a durable successful clear; never on defeat.
"""
from __future__ import annotations
import copy,re,time,uuid
import cv2,numpy as np
from walking_map import walking_map_info,WalkingMapAdapter

SAINT_BOOK='saint_eulogy'
SAINT_STAGE='3-7'
STAGE_RE=re.compile(r'^\s*([1-9]\d{0,2})\s*[-−–—一]\s*([1-9]\d{0,2})(?!\d)[.．、。\s]*(.*)')

def stage_id(text):
    match=STAGE_RE.match(text)
    return (str(int(match[1]))+'-'+str(int(match[2]))) if match else None

def stage_order(value):return tuple(map(int,value.split('-')))

def next_stage(value):
    chapter,number=stage_order(value);return str(chapter)+'-'+str(number+1)

def read_stage(f):
    rows=[]
    for word in f.words:
        sid=stage_id(word['text'])
        if sid and word['score']>=.85 and 1120<=word['x']<=1599 and 135<=word['y']<=210:
            rows.append(dict(id=sid,name=STAGE_RE.match(word['text'])[3].strip(),word=word))
    if len(rows)!=1:return None
    titles=sorted((w for w in f.words if 1120<=w['x']<=1390 and 85<=w['y']<=135 and w['score']>=.85 and '防御战成就' not in w['text']),key=lambda w:w['x'])
    region=titles[0]['text'] if titles else ''
    return dict(rows[0],region=region)

def map_info(f):
    walking=walking_map_info(f)
    if walking:return walking
    if not f.find('准备战斗',(1100,750,1599,899)) or f.find('Episode',(0,0,500,90)):return None
    rows=[]
    for word in f.words:
        sid=stage_id(word['text'])
        if sid and word['score']>=.8 and 0<=word['x']<1460 and 130<=word['y']<=880:
            rows.append(dict(id=sid,name=STAGE_RE.match(word['text'])[3].strip(),word=word))
    if len({row['id'] for row in rows})<3 and not (rows and f.find(r'^地区信息$',(1450,300,1599,420)) and f.find(r'^任务$',(1450,180,1599,280))):return None
    # A map animation/route can hide the chapter prefix (e.g. 1-7 -> 7.).
    # Only complete a partial map label when all full labels agree on chapter;
    # the actual entry still requires the complete number on the team page.
    chapters={row['id'].split('-')[0] for row in rows}
    if len(chapters)==1:
        chapter=next(iter(chapters))
        for word in f.words:
            partial=re.fullmatch(r'\s*(\d{1,2})[.．、。]\s*(\D.+)',word['text'])
            if not partial or word['score']<.90 or not (0<=word['x']<1460 and 130<=word['y']<=880):continue
            sid=chapter+'-'+str(int(partial[1]))
            if not any(row['id']==sid for row in rows):rows.append(dict(id=sid,name=partial[2].strip(),word=word,inferred_prefix=True))
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    for row in rows:
        x,y=round(row['word']['x']),round(row['word']['y'])
        tile=hsv[max(95,y-245):max(96,y-35),max(0,x-95):min(1480,x+95)]
        row['marker_score']=int(np.count_nonzero((tile[:,:,0]>105)&(tile[:,:,0]<158)&(tile[:,:,1]>100)&(tile[:,:,2]>160)))
    ranked=sorted(rows,key=lambda r:r['marker_score'],reverse=True)
    chosen=ranked[0] if ranked and ranked[0]['marker_score']>=80 and (len(ranked)==1 or ranked[0]['marker_score']>ranked[1]['marker_score']*2+20) else None
    title=next((w['text'] for w in f.words if 70<w['x']<500 and 10<w['y']<85),'旧版剧情地图')
    return dict(rows=rows,selected=chosen,region=title)

SAINT_REGIONS={1:'圣王国伊杰拉',2:'黎塔尼亚北部',3:'圣域最深处'}
def region_cards(f):
    if not f.find('最后的战斗',(1100,750,1599,899)):return None
    cards={chapter:f.find('^'+name+'$',(100,650,1450,780)) for chapter,name in SAINT_REGIONS.items()}
    return cards if all(cards.values()) else None

def region_exit(f,chapter,visited=(),target_name=None):
    candidates=[]
    for word in f.words:
        match=re.fullmatch(r'往(.{2,12})',word['text'])
        if not match or word['score']<.9 or not (100<=word['x']<=1400 and 130<=word['y']<=750):continue
        name=match[1]
        if target_name and name!=target_name or not target_name and name in visited:continue
        x,y=round(word['x']),round(word['y']-70)
        tile=cv2.cvtColor(f.image[max(90,y-40):y+40,max(0,x-55):min(1470,x+55)],cv2.COLOR_BGR2HSV)
        if tile.size==0:continue
        green=np.count_nonzero((tile[:,:,0]>=30)&(tile[:,:,0]<=90)&(tile[:,:,1]>90)&(tile[:,:,2]>80))
        if green>500:candidates.append(dict(x=x,y=y,name=name))
    return candidates[0] if len(candidates)==1 else None

def completed_waves(f):
    word=f.find(r'([1-9])\s*/\s*([1-9])',(100,0,400,90))
    if not word or word['score']<.75:return False
    match=re.search(r'([1-9])\s*/\s*([1-9])',word['text'])
    return match[1]==match[2]

def clear_banner(f):
    word=f.find(r'^C\s*L\s*E\s*A\s*R$',(500,180,1100,600))
    return bool(word and word['score']>=.94 and completed_waves(f))

def exit_target(f,clear_overlay=False):
    if clear_overlay:
        if not f.find(r'C\s*L\s*E\s*A\s*R',(500,180,1100,600)):return None
    elif not (f.find(r'^离开$',(0,750,250,899)) and f.find(r'^大厅$',(250,750,500,899)) and f.find(r'^重新进行$',(1300,750,1599,899))):return None
    if not completed_waves(f):return None
    tile=cv2.cvtColor(f.image[350:810,1000:1590],cv2.COLOR_BGR2HSV)
    mask=np.uint8((tile[:,:,0]>=85)&(tile[:,:,0]<=120)&(tile[:,:,1]>(60 if clear_overlay else 100))&(tile[:,:,2]>(65 if clear_overlay else 180)))*255
    count,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
    dots=[(float(c[0]+1000),float(c[1]+350)) for s,c in zip(stats[1:],centers[1:]) if 40<=s[4]<=(900 if clear_overlay else 1600) and 8<=s[2]<=(45 if clear_overlay else 85) and 5<=s[3]<=(28 if clear_overlay else 70) and (not clear_overlay or s[2]>s[3])]
    if len(dots)<5:return None
    # Stone floors can produce similarly coloured fragments. Find the dotted
    # exit's diagonal consensus rather than letting one unrelated fragment veto it.
    points=np.array(dots);best=None
    for i,(x1,y1) in enumerate(points):
        for x2,y2 in points[i+1:]:
            if abs(x2-x1)<70:continue
            slope=(y2-y1)/(x2-x1)
            if not .4<=slope<=1.8:continue
            near=points[np.abs(points[:,1]-(y1+slope*(points[:,0]-x1)))<12]
            if len(near)<5:continue
            xs,ys=near.T
            if np.ptp(xs)<100 or np.ptp(ys)<100:continue
            rank=(len(near),float(np.ptp(xs)))
            if best is None or rank>best[0]:best=(rank,near)
    if best is None:return None
    xs,ys=best[1].T
    return dict(x=min(1570,round(float(max(xs))+80)),y=min(710,round(float(np.median(ys)))),dots=len(xs))

def team_entry_control(f):
    """Read an ordinary single-entry layout, independently of preparation AUTO.

    AUTO presence, position, confidence and state never authorize or veto entry.
    Required hero setup/overlays still veto; battle AUTO is a separate UI flow.
    """
    from tutorial_core import guided_team_slot_visible
    # Known Skip is a free overlay control, never permission to click through
    # to the otherwise fully readable resource-entry button beneath it.
    if any(re.fullmatch(r'跳过教[学學]',w['text']) for w in f.words):
        return dict(kind='unknown',target=None,proof='教学跳过遮罩仍在；先处理已核实的免费教学，不点击底层资源入口')
    if guided_team_slot_visible(f):
        from tutorial_core import _guided_slot_candidates
        # Native fixed-story parties can pulse several OPTIONAL empty slots.
        # A gold rim alone is not a forced setup tutorial. Only this complete
        # native layout + multiple visible slots disambiguates it;
        # a single guided slot, setup text, or a partial layout still vetoes.
        native=_native_story_team_target(f)
        instructions=any(re.search(r'教学|点击|请选择|请配置|拖动',w['text']) for w in f.words)
        if not (native and not instructions
                and len(_guided_slot_candidates(f,detection_only=True))>=2):
            return dict(kind='unknown',target=None,proof='教学高亮配置空位仍可见；不向底层进行任务发送入场')
    return _team_entry_layout(f)


def _native_mission_glyphs(f,objectives):
    """Three native diamonds aligned to their current pixel centroids.

    Text baseline and panel margins differ slightly between native layouts.
    Locate the current glyph within the bounded mission gutter, then apply the
    same count/colour/centroid/taper requirements to its centred 35x41 tile.
    No OCR reread, text-specific permit or broad bright-area input fallback.
    """
    def mask(tile):
        hsv=cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)
        return (hsv[:,:,0]>=10)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>=85)&(hsv[:,:,2]>=100)
    for objective in objectives:
        row=round(objective['y'])
        search=f.image[row-21:row+14,1148:1208]
        if search.shape[:2]!=(35,60):return False
        gold=mask(search)
        if not 180<=int(np.count_nonzero(gold))<=500:return False
        ys,xs=np.nonzero(gold)
        x=1148+round(float(xs.mean()));y=row-21+round(float(ys.mean()))
        if not 1160<=x<=1200 or abs(y-row)>9:return False
        tile=f.image[y-17:y+18,x-20:x+21]
        if tile.shape[:2]!=(35,41):return False
        gold=mask(tile)
        if not 180<=int(np.count_nonzero(gold))<=500:return False
        ys,xs=np.nonzero(gold);widths=gold.sum(axis=1)
        if (not 13<=float(xs.mean())<=26 or not 12<=float(ys.mean())<=24
            or float(np.mean(widths[12:23]))-max(float(np.mean(widths[:5])),float(np.mean(widths[-5:])))<4):
            return False
    return True


def _preparation_field_frame(f):
    """Use a bound current field, not count its weak original as a new control.

    Original OCR remains in f.words and in the supplement's original_ocr. A
    duplicate/changed source or a stale/unbound supplement cannot strengthen it.
    """
    if getattr(f,'preparation_fields_resolved',False):return f
    hidden=set()
    for source in ('current_preparation_power_label_field_read','current_preparation_single_entry_label_field_read'):
        reads=[w for w in f.words if w.get('source')==source]
        if len(reads)!=1:continue
        read=reads[0];original=read.get('original_ocr')
        originals=[w for w in f.words if w.get('source')!=source and w==original]
        if (read.get('captured_at')==f.at and read['score']>=.98
            and read.get('verification_scores')==[read['score']]
            and len(originals)==1 and originals[0]['score']<.98):
            hidden.add(id(originals[0]))
        else:hidden.add(id(read))
    if not hidden:return f
    current=copy.copy(f);current.words=[w for w in f.words if id(w) not in hidden]
    current.preparation_fields_resolved=True
    return current


def _native_story_team_target(f):
    """Fixed story party with one separate, non-starting hosted control.

    The three displayed objectives are passive mission descriptions. Their
    wording never requests configuring, spending, reviving or retrying heroes.
    Only the ordinary single-task button is returned; map/title/cost/history
    remain Runner and first-entry-dispatch obligations.
    """
    f=_preparation_field_frame(f)
    # Objectives describe optional achievements, not input instructions. Read
    # both complete passive rows with their three native mission glyphs instead
    # of maintaining a per-hero/per-survivor/per-chapter text allowlist.
    objective=r'.{4,40}'
    specs=[(r'准备战斗',(60,10,260,80),.98),
           (r'故事队伍',(25,80,155,150),.98),
           (r'故事队伍',(220,80,380,140),.98),
           (r'闯关成功',(1180,200,1380,250),.98),
           (objective,(1180,245,1550,290),.95),
           (objective,(1180,290,1550,325),.95),
           (r'登场的敌人',(1180,330,1450,395),.98),
           (r'^[-−一·—–－]?\s*队伍战斗力$',(300,770,560,835),.98),
           (r'管理队伍',(25,815,200,899),.98),
           (r'托管战斗',(750,690,900,765),.98),
           (r'进行任务',(1300,770,1599,899),.98)]
    anchors=[]
    for pattern,(x1,y1,x2,y2),score in specs:
        words=[w for w in f.words if re.fullmatch(pattern,w['text'])
               and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        if len(words)!=1 or words[0]['score']<score:return None
        anchors.append(words[0])
    if not _native_mission_glyphs(f,anchors[3:6]):return None
    story=[w for w in f.words if w['text']=='故事' and w['score']>=.98
           and 200<=w['x']<=1000 and 160<=w['y']<=350]
    if (not story or any('辅助英雄' in w['text'] for w in f.words)
        or sum(w['text']=='托管战斗' for w in f.words)!=1
        or sum(w['text']=='进行任务' for w in f.words)!=1):return None
    return anchors[-1]


def _legacy_story_team_target(f):
    """Known old story/defense party; empty mission panel, not preparation AUTO."""
    specs=[(r'准备战斗',(60,10,260,80),.98),
           (r'支线故事[1-9]队',(20,80,190,160),.98),
           (r'没有可执行的',(1180,245,1550,290),.98),
           (r'任务[。.]?',(1180,290,1550,325),.98),
           (r'登场的敌人',(1180,330,1450,395),.98),
           (r'可获得的奖励',(1180,540,1450,625),.98),
           (r'[-−一·—–－]?\s*队伍战斗力',(300,770,560,835),.90),
           (r'管理队伍',(25,815,200,899),.98),
           (r'进行任务|战斗开始',(1300,770,1599,899),.98)]
    anchors=[]
    for pattern,(x1,y1,x2,y2),score in specs:
        words=[w for w in f.words if re.fullmatch(pattern,w['text'])
               and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        if len(words)!=1 or words[0]['score']<score:return None
        anchors.append(words[0])
    hosted=[w for w in f.words if w['text']=='托管战斗']
    if (sum(w['text'] in ('进行任务','战斗开始') for w in f.words)!=1 or len(hosted)>1
        or any(w['score']<.98 or not (750<=w['x']<=900 and 690<=w['y']<=765) for w in hosted)):
        return None
    return anchors[-1]


def _team_entry_layout(f):
    """Read the preparation layout; hosted/repeat controls are never tap targets."""
    f=_preparation_field_frame(f)
    unknown=dict(kind='unknown',target=None,proof='队伍准备页完整布局或唯一普通单次入口尚未核实；不以AUTO作为入场条件')
    from tutorial_core import owned_hero_selector_visible
    if owned_hero_selector_visible(f):return unknown
    if sum(w['text'] in ('进行任务','战斗开始') for w in f.words)!=1:return unknown
    if f.find(r'^(确认|确定|確認|確定|取消)$'):return unknown
    if any(re.search(r'重复战斗|连续战斗|重复进行|托管次数|托管中',w['text']) for w in f.words):return unknown
    story_anchors=[
        f.find(r'^准备战斗$',(60,10,260,80)),
        f.find(r'^故事队伍$',(25,80,155,150)),
        f.find(r'^故事队伍$',(220,80,380,140)),
        f.find(r'^故事$',(200,160,1000,350)),
        f.find(r'^闯关成功$',(1180,200,1380,250)),
        f.find(r'^完成故事$',(1180,245,1380,290)),
        f.find(r'^[1-4]名以上英雄存活$',(1180,280,1450,325)),
        f.find(r'^登场的敌人$',(1180,330,1450,395)),
        f.find(r'^[-−一·—–－]?\s*队伍战斗力$',(300,770,560,835)),
        f.find(r'^管理队伍$',(25,815,200,899)),
        f.find(r'^进行任务$',(1300,770,1599,899)),
    ]
    if all(w and w['score']>=(.90 if index==8 else .95) for index,w in enumerate(story_anchors)) and not f.any('托管战斗','辅助英雄'):
        return dict(kind='single_task',target=story_anchors[-1],
                    proof='已识别故事固定队伍、三项关卡任务与普通单次入口；不宣称已开启自动，仍需地图/标题/体力/历史链')
    native_story=_native_story_team_target(f)
    if native_story:
        return dict(kind='single_task',target=native_story,
                    proof='已识别故事固定队伍、完整三项任务、独立托管控件和普通单次入口；未操作托管，不推断战斗内AUTO状态')
    if f.find(r'^故事队伍$') and f.any('托管战斗'):
        # A partial/changed native story page must not fall through to the
        # unrelated legacy party branch or a hosted configuration overlay.
        return unknown
    # Episode mission rows are passive achievement descriptions, not setup
    # commands. Their text varies with stage: recognize the complete native
    # three-diamond panel instead of requiring particular survivor/story text.
    episode_specs=[
        (r'准备战斗',(60,10,260,80),.98),
        (r'Episode1队',(20,80,160,160),.98),
        (r'Episode2队',(20,165,160,235),.98),
        (r'Episode3队',(20,240,160,310),.98),
        (r'闯关成功',(1180,200,1380,250),.98),
        (r'.{4,40}',(1180,245,1550,290),.95),
        (r'.{4,40}',(1180,290,1550,325),.95),
        (r'登场的敌人',(1180,330,1450,395),.98),
        (r'[-−一·—–－]?\s*队伍战斗力',(300,770,560,835),.90),
        (r'管理队伍',(25,815,200,899),.98),
        (r'进行任务',(1300,770,1599,899),.98),
    ]
    episode_anchors=[]
    for pattern,(x1,y1,x2,y2),score in episode_specs:
        words=[w for w in f.words if re.fullmatch(pattern,w['text'])
               and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        episode_anchors.append(words[0] if len(words)==1 and words[0]['score']>=score else None)
    hosted=[w for w in f.words if '托管战斗' in w['text']]
    bottom=[w for w in hosted if w['text']=='托管战斗' and w['score']>=.98
            and 750<=w['x']<=900 and 690<=w['y']<=765]
    top=[w for w in hosted if w['text']=='托管战斗' and w['score']>=.98
         and 1390<=w['x']<=1535 and 75<=w['y']<=150]
    hosted_valid=(not hosted or (len(bottom)==1 and len(top)<=1 and len(hosted)==len(bottom)+len(top)))
    if all(episode_anchors) and hosted_valid and _native_mission_glyphs(f,episode_anchors[4:7]):
        return dict(kind='single_task',target=episode_anchors[-1],
                    proof='已识别原生Episode三队标签、三枚原生任务菱形及完整被动目标区、普通单次入口；不按成就文案配队、不操作独立托管控件，AUTO与辅助英雄占位不作为入场条件，不推断战斗内AUTO状态')
    if any(f.find(r'^Episode'+str(n)+r'队$') for n in (1,2,3)):
        # An incomplete Episode page cannot borrow hosted/other-party identity.
        return unknown
    legacy_story=_legacy_story_team_target(f)
    if legacy_story:
        return dict(kind='single_task',target=legacy_story,
                    proof='已识别旧剧情队伍标签、完整空任务面板、敌人与奖励区及唯一普通入场控件；AUTO与辅助英雄占位不作为入场条件，未操作托管，不推断战斗内AUTO状态')
    if f.find(r'^支线故事[1-9]队$'):return unknown
    # The legacy hosted controls identify this layout but are NEVER targets.
    # Optional AUTO and support occupancy are not evidence for resource entry.
    specs=[
        (r'准备战斗',(60,10,260,80)),
        (r'托管战斗',(1390,75,1535,150)),
        (r'托管战斗',(750,690,900,765)),
        (r'[-−一·—–－]?\s*队伍战斗力',(300,770,560,835)),
        (r'管理队伍',(25,815,200,899)),
        (r'进行任务',(1300,770,1599,899)),
    ]
    anchors=[]
    for pattern,(x1,y1,x2,y2) in specs:
        words=[w for w in f.words if re.fullmatch(pattern,w['text'])
               and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        if len(words)!=1 or words[0]['score']<.90:return unknown
        anchors.append(words[0])
    if sum(w['text']=='托管战斗' for w in f.words)!=2 or sum(w['text']=='进行任务' for w in f.words)!=1:
        return unknown
    return dict(kind='single_task',target=anchors[-1],
                proof='已识别准备标题、两处独立托管控件、队伍战斗力、管理队伍和唯一普通单次入口；AUTO与辅助英雄占位不作为入场条件，未操作托管或确认战斗内自动开关')

def entry_cost(f,*,allow_zero=False):
    word=f.find(r'^\d+\s*/\s*\d+$',(1180,775,1400,890))
    if not word or word['score']<.90:return None
    required,available=map(int,re.fullmatch(r'(\d+)\s*/\s*(\d+)',word['text']).groups())
    return (required,available) if (0 if allow_zero else 1)<=required<=100 else None

class StoryController:
    def __init__(self,runner,settings):
        self.r=runner;self.settings=settings;self.goal=settings.get('task')=='saint_3_7' or settings.get('story_farm_on_reach')=='saint_3_7'
        self.context=bool(self.goal);self.ticket=None
        root=runner.s.get('story_progress',{})
        saved=root.get('current_book')
        self.book_id=SAINT_BOOK if self.goal else saved if saved in root.get('books',{}) else None
        self.context=self.context or self.book_id is not None
        self.entry_wait_until=0
        self.selection_failures={}
        self.walking=WalkingMapAdapter(self)
        if self.book_id in root.get('books',{}):
            old=self.book;old['mode']='farm' if self.goal and (SAINT_STAGE in old.get('stages',{}) or old.get('mode')=='farm') else 'progress'
            active=old.get('active')
            if (old.get('walking_map') and not self.goal and active
                and getattr(runner,'current_screen_start',False)
                and (active.get('map_binding') or {}).get('run_id')!=getattr(runner,'run_id',None)):
                old.setdefault('unresolved_entries',[]).append(dict(at=time.time(),reason='显式新开始完整归档原行走入场；不认领本次结果、不删除原入场或补记完成',entry=copy.deepcopy(active)))
                old['active']=None;runner.save()
    @property
    def book(self):
        root=self.r.s.setdefault('story_progress',{'schema':1,'books':{}})
        return root['books'].setdefault(self.book_id,{'attempted':{},'completed':{},'stages':{},'active':None,'last_cleared':None,'mode':'progress','farm_runs':0})
    def bind(self,region,chapter=None):
        if not self.book_id:
            known=[key for key,value in self.r.s.get('story_progress',{}).get('books',{}).items() if region in value.get('regions_seen',[value.get('region')])]
            self.book_id=known[0] if len(known)==1 else 'legacy|'+region
        self.context=True;self.book['region']=region
        seen=self.book.setdefault('regions_seen',[])
        if region not in seen:seen.append(region)
        if chapter:self.book.setdefault('chapter_regions',{})[str(chapter)]=region
        self.r.s['story_progress']['current_book']=self.book_id
    def desired_stage(self):
        if self.walking.enabled:return self.walking.desired()
        if self.goal and (self.book.get('mode')=='farm' or SAINT_STAGE in self.book.get('stages',{})):return SAINT_STAGE
        route=self.book.get('region_route',{})
        if route.get('from_stage')==self.book.get('last_cleared') and route.get('target_stage'):return route['target_stage']
        return next_stage(self.book['last_cleared']) if self.book.get('last_cleared') else None
    def total_wins(self):return sum(len(b.get('completed',{})) for b in self.r.s.get('story_progress',{}).get('books',{}).values())
    def stage_label(self):
        if not self.context:return ''
        return (self.book.get('active') or {}).get('stage') or self.book.get('last_cleared') or ''
    def wait(self,title,reason):return self.r.attention('story',title,reason)
    def act(self,kind,word=None,xy=None):
        farming=self.goal and self.book.get('mode')=='farm'
        detail=f'圣女3-7 · 已成功 {self.book.get("farm_runs",0)} 次 · {kind}' if farming else kind
        self.r.s.update(status='圣女3-7循环刷取中' if farming else '正在推进剧情关卡',reason=detail)
        self.r.action(kind,word=word,xy=xy);return True,.6
    def remember_map(self,page):
        atlas=self.book.setdefault('map_atlas',{}).setdefault(page['region'],{})
        shifts=[(r['word']['x']-atlas[r['id']]['x'],r['word']['y']-atlas[r['id']]['y']) for r in page['rows'] if r['id'] in atlas]
        if len(shifts)>=2:
            shift=np.median(shifts,axis=0)
            if max(np.linalg.norm(np.array(v)-shift) for v in shifts)<35:
                for point in atlas.values():point['x']+=float(shift[0]);point['y']+=float(shift[1])
        for row in page['rows']:atlas[row['id']]={'x':row['word']['x'],'y':row['word']['y']}
        return atlas
    def pan_for(self,desired,atlas):
        nav=self.book.setdefault('navigation',{})
        tries=nav.get('pan_tries',0) if nav.get('desired')==desired and nav.get('pan_region')==self.book.get('region') else 0
        if tries>=4:return self.wait('当前地图未找到目标关','四次有界地图导航仍未出现 '+desired+'；不猜测入场。')
        point=atlas.get(desired)
        if point and (point['y']<160 or point['y']>750 or point['x']<150 or point['x']>1390):
            dx=max(-420,min(420,800-point['x']));dy=max(-350,min(350,480-point['y']))
        else:dx,dy=((0,-340),(400,0),(0,650),(-750,0))[tries]
        nav.update(desired=desired,pan_tries=tries+1,pan_region=self.book.get('region'));self.r.s.update(status='正在推进剧情关卡',reason='后台移动地图查找 '+desired);self.r.save()
        # Drag from unoccupied central terrain; each next input gets a fresh
        # captured frame and only a complete preparation number permits entry.
        start=(780,650 if dy<0 else 200 if dy>0 else 450)
        end=(max(100,min(1400,start[0]+dx)),max(120,min(750,start[1]+dy)))
        self.r.drag('后台移动剧情地图查找 '+desired,start,end);return True,.7
    def enter(self,f,stage,word):
        from entry_journal import can_enter,reserve_entry,finish_dispatch
        from pc_backend import TapNotSent
        desired=self.desired_stage()
        if desired and stage['id']!=desired:
            self.r.back('准备页编号不是目标 '+desired+'，返回地图重新选择');self.ticket=None;return True,.7
        pending=[a for a in self.book['attempted'].values() if a['stage']==stage['id'] and a['id'] not in self.book['completed'] and not a.get('rejected_before_battle') and not can_enter(self.book,a['id'])]
        if pending:return self.wait('当前剧情关已有入场记录','结果不明不再次入场；保留全部记录和现场。')
        if stage['id'] in self.book['stages'] and not (self.goal and stage['id']==SAINT_STAGE):
            self.ticket=None;self.r.back('这关已通关，返回地图选下一关');return True,.7
        if self.goal and stage_order(stage['id'])>stage_order(SAINT_STAGE):return self.wait('不会推进超过圣女3-7','当前准备页已超过目标关；返回目标地图后继续。')
        cost=entry_cost(f,allow_zero=self.walking.enabled)
        if cost is None:return self.wait('等待清晰入场体力读数','未能可靠读取本次消耗/剩余体力，不猜测。')
        required,available=cost
        if available<required:
            self.r.s.update(status='等待体力自然恢复',reason=f'体力 {available}/{required}；不购买、不兑换，30秒后重新读取。',story_waiting_resource=True)
            self.r.save();return True,30
        self.r.s.pop('story_waiting_resource',None)
        control=team_entry_control(f)
        if control['kind']!='single_task':return self.wait('队伍页入场方式等待确认','未核实当前队伍准备页的完整布局与唯一普通单次任务入口；不以AUTO或辅助英雄占位作为条件。')
        if control['kind']=='single_task':word=control['target']
        intent=dict(id=uuid.uuid4().hex,stage=stage['id'],name=stage['name'],region=stage['region'],cost=required,stamina_before=available,start_epoch=time.time(),team_entry_mode=control['kind'],proof='当前准备页精确关卡编号与体力；'+control['proof'],evidence=self.r.evidence('story-entry-'+stage['id']))
        if stage.get('map_binding'):intent['map_binding']=copy.deepcopy(stage['map_binding'])
        dispatch=reserve_entry(self.book,intent['id'],intent);self.book['active']=intent
        self.r.save()  # Persist full per-run intent BEFORE the only entry click.
        self.entry_wait_until=time.monotonic()+15;self.ticket=None
        try:result=self.act('剧情关卡入场 '+stage['id']+'（仅正常体力）',word)
        except TapNotSent as exc:
            finish_dispatch(dispatch,'not_sent',str(exc))
            self.book.setdefault('unresolved_entries',[]).append(copy.deepcopy(intent));self.book['active']=None
            self.r.save()
            return self.wait('开战点击尚未发送','鼠标接管时取消了点击；移出后点继续，重新核对当前关再开战。')
        finish_dispatch(dispatch,'sent');self.r.save()
        return result
    def clear(self,proof):
        active=self.book.get('active')
        if not active:return
        record=copy.deepcopy(active);record.update(completed_at=time.time(),proof=proof,evidence=self.r.evidence('story-clear-'+active['stage']))
        self.book['completed'][active['id']]=record
        self.book['stages'].setdefault(active['stage'],record)
        self.book['last_cleared']=active['stage'];self.book['active']=None
        if self.goal and active['stage']==SAINT_STAGE:
            self.book['mode']='farm';self.book['farm_runs']+=1
        self.r.save()
    def step(self,f,mode):
        page=map_info(f) if mode=='legacy_story_map' else None
        if page and page.get('layout')=='walking_short':return self.walking.map_step(f,page)
        if self.walking.enabled and mode in ('support','team'):return self.walking.prep_step(f,mode)
        stage=read_stage(f) if mode in ('support','team') else None
        if page:
            chapters={stage_order(r['id'])[0] for r in page['rows']}
            self.bind(page['region'],next(iter(chapters)) if len(chapters)==1 else None)
        elif stage:self.bind(stage['region'],stage_order(stage['id'])[0])
        if mode=='legacy_story_regions':
            if not self.book_id:self.book_id=SAINT_BOOK;self.context=True
            cards=region_cards(f)
            desired=self.desired_stage() or '1-1';chapter=stage_order(desired)[0]
            # The third overview card is a final-battle shortcut, not evidence
            # that it contains numbered chapter 3. Navigate via a known region.
            known=self.book.get('chapter_regions',{})
            target_name=known.get(str(chapter)) or ({1:SAINT_REGIONS[1],2:SAINT_REGIONS[2]}.get(chapter))
            card=next((word for word in cards.values() if word['text']==target_name),None)
            if card is None:card=cards[2]
            self.book.setdefault('navigation',{}).update(desired=desired,overview_seen=True)
            return self.act('进入剧情地区 '+card['text'],xy=(card['x'],card['y']-260))
        if mode in ('lobby','map'):
            if self.goal:return self.wait('圣女3-7等待目标支线','请打开时间之书《圣女追悼文》；不会把主线当成圣女支线。')
            self.context=False;self.book_id=None
            self.r.s.get('story_progress',{}).pop('current_book',None)
            return None
        if not self.context:return None
        active=self.book.get('active')
        if mode=='legacy_story_map':
            atlas=self.remember_map(page)
            if active:
                if time.time()-active['start_epoch']<20:return True,.7
                return self.wait('剧情入场结果尚未结算','没有独立结算证据，不重复已入场关卡。')
            desired=self.desired_stage()
            if desired:
                chapters={stage_order(r['id'])[0] for r in page['rows']};wanted_chapter=stage_order(desired)[0]
                current=next(iter(chapters)) if len(chapters)==1 else None
                if current and current!=wanted_chapter:
                    neighbour=current+(1 if current<wanted_chapter else -1)
                    previous=next((route for route in reversed(self.book.get('region_transitions',[])) if stage_order(route['target_stage'])[0]==neighbour),None)
                    saint_names=SAINT_REGIONS if self.goal or self.book_id==SAINT_BOOK else {}
                    name=previous['region'] if previous else self.book.get('chapter_regions',{}).get(str(neighbour)) or saint_names.get(neighbour)
                    gate=region_exit(f,current,self.book.get('regions_seen',[]),target_name=name) if name or wanted_chapter>current else None
                    if gate:
                        nav=self.book.setdefault('navigation',{});key=page['region']+'>'+desired;tries=nav.setdefault('region_tries',{}).get(key,0)
                        if tries>=2:return self.wait('目标地区导航未生效','未进入未知关卡或重复消耗体力。')
                        nav['region_tries'][key]=tries+1;self.r.save()
                        return self.act('经原生地区入口返回目标 '+desired,xy=(gate['x'],gate['y']))
                    return self.pan_for(desired,atlas)
                row=next((r for r in page['rows'] if r['id']==desired),None)
                if not row:
                    last=self.book.get('last_cleared')
                    chapter=stage_order(last)[0] if last else None
                    gate=region_exit(f,chapter,self.book.get('regions_seen',[])) if chapter and self.book.get('mode')!='farm' else None
                    # A native unlocked next-region arrow is a real progression
                    # route, not an invented N+1 stage. Preserve this route and
                    # verify the first complete number in the new preparation.
                    same_chapter=[stage_order(r['id'])[1] for r in page['rows'] if stage_order(r['id'])[0]==chapter]
                    if gate and same_chapter and stage_order(last)[1]>=max(same_chapter):
                        old=self.book.get('region_route',{});tries=old.get('tries',0) if old.get('from_stage')==last else 0
                        if tries>=2:return self.wait('地区导航未生效','已两次点击已解锁地区入口，未重复关卡入场。')
                        route=dict(from_stage=last,target_stage=str(chapter+1)+'-1',region=gate['name'],tries=tries+1,evidence=self.r.evidence('story-region-route'))
                        self.book['region_route']=route;self.book.setdefault('region_transitions',[]).append(copy.deepcopy(route));self.r.save()
                        return self.act('前往下一剧情地区 '+gate['name'],xy=(gate['x'],gate['y']))
                    return self.pan_for(desired,atlas)
                node=(row['word']['x'],row['word']['y']-70)
                if node[1]<100 or node[1]>770 and node[0]>850:return self.pan_for(desired,atlas)
                if not self.ticket or self.ticket.get('id')!=desired or self.ticket.get('phase')!='selected':
                    self.ticket=dict(row,region=page['region'],phase='selected')
                    # Legacy plaques are captions, not hit targets. The actual
                    # node icon sits above its caption in the 1600x900 layout.
                    return self.act('选择剧情节点 '+desired,xy=(row['word']['x'],max(100,row['word']['y']-70)))
            # Purple quest pin != selected stage. Selection is confirmed by the
            # complete stage number on support/team, before any stamina input.
            self.ticket=dict(id=desired,region=page['region'],phase='opening')
            return self.act('打开剧情关卡准备页'+(' '+desired if desired else '（读取当前选择）'),f.find('准备战斗',(1100,750,1599,899)))
        if stage and mode=='support':
            desired=self.desired_stage()
            if desired and stage['id']!=desired:
                count=self.selection_failures.get(desired,0)+1;self.selection_failures[desired]=count
                if count>=2:return self.wait('关卡选择未生效','准备页两次不是目标 '+desired+'；未进行任务。')
                self.r.back('准备页不是目标 '+desired+'，返回地图选关');self.ticket=None;return True,.7
            self.selection_failures.clear()
            self.ticket=dict(stage,phase='support')
            return self.act('沿用队伍推进剧情 '+stage['id'],f.find('选择队伍',(1120,750,1599,899)))
        if stage and mode=='team':
            if active:
                if stage['id']==active['stage'] and time.monotonic()<self.entry_wait_until:return True,.8
                return self.wait('剧情已发出一次入场请求','仍在准备页，不重复进行任务。')
            return self.enter(f,stage,f.find(r'^(进行任务|战斗开始)$',(1300,750,1599,899)))
        if mode in ('legacy_story_exit','legacy_story_clear'):
            if mode=='legacy_story_exit' and not active:
                return self.act('当前无待结算入场，离开至剧情地图选关',f.find(r'^离开$',(0,750,250,899)))
            target=exit_target(f,clear_overlay=mode=='legacy_story_clear')
            if not target and not (mode=='legacy_story_clear' and clear_banner(f)):return None
            if active and mode=='legacy_story_clear':
                if not active.get('victory_seen'):active.update(victory_seen=True,victory_evidence=self.r.evidence('story-clear-banner-'+active['stage']));self.r.save()
            if active and mode=='legacy_story_exit':
                if not active.get('exit_seen'):active.update(exit_seen=time.time(),exit_evidence=self.r.evidence('story-exit-'+active['stage']));self.r.save()
            if target:return self.act('越过蓝色出口前往下一区域',xy=(target['x'],target['y']))
            return self.act('关闭胜利遮罩，继续读取出口或结算',xy=(800,820))
        if mode in ('story','skip_confirm') and active and not active.get('story_seen'):
            active['story_seen']=time.time();self.r.save()
        if mode=='settlement':
            self.clear('独立结算证据：获得的道具、战斗结果、确认')
            self.ticket=None
            return self.act('确认剧情关卡结算',f.find(r'^(确认|确定|確定|確認)$',(1300,750,1599,899)))
        if mode=='victory' and active:
            active['victory_seen']=True;self.r.save()
            return self.act('剧情胜利页继续至结算',xy=(1550,845))
        if mode=='battle' and active:
            if time.time()-active['start_epoch']>1800:return self.wait('剧情单场超过30分钟','保留现场，不复活、不重试。')
            detail=f'圣女3-7循环战斗中 · 已成功 {self.book.get("farm_runs",0)} 次；等待本轮结算。' if self.goal and self.book.get('mode')=='farm' else '等待原生自动战斗与蓝色出口，不点击技能。'
            self.r.s.update(status='剧情自动战斗中',reason=detail);self.r.save();return True,2.5
        if mode=='post_clear_exit' and not active and self.book.get('last_cleared'):
            return self.act('结算后返回剧情地图，按目标选关',f.find(r'^离开$',(0,750,250,899)))
        return None
