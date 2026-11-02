"""Legacy story-map support and explicit successful Saint 3-7 farming policy.

Pure scene readers plus a controller using the existing guarded Runner transport.
Only Saint 3-7 may repeat, and only after a durable successful clear; never on defeat.
"""
from __future__ import annotations
import copy,re,time,uuid
import cv2,numpy as np

SAINT_BOOK='saint_eulogy'
SAINT_STAGE='3-7'
STAGE_RE=re.compile(r'^\s*([1-9])\s*[-−–—一]\s*(\d{1,2})[.．、。\s]*(.*)')

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

def auto_enabled(f):
    hsv=cv2.cvtColor(f.image[650:710,900:1095],cv2.COLOR_BGR2HSV)
    return np.count_nonzero((hsv[:,:,0]>30)&(hsv[:,:,0]<90)&(hsv[:,:,1]>90)&(hsv[:,:,2]>65))>800

def entry_cost(f):
    word=f.find(r'^\d+\s*/\s*\d+$',(1180,775,1400,890))
    if not word or word['score']<.90:return None
    required,available=map(int,re.fullmatch(r'(\d+)\s*/\s*(\d+)',word['text']).groups())
    return (required,available) if 0<required<=100 else None

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
        if self.book_id in root.get('books',{}):
            old=self.book;old['mode']='farm' if self.goal and (SAINT_STAGE in old.get('stages',{}) or old.get('mode')=='farm') else 'progress'
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
        desired=self.desired_stage()
        if desired and stage['id']!=desired:
            self.r.back('准备页编号不是目标 '+desired+'，返回地图重新选择');self.ticket=None;return True,.7
        pending=[a for a in self.book['attempted'].values() if a['stage']==stage['id'] and a['id'] not in self.book['completed'] and not a.get('rejected_before_battle')]
        if pending:return self.wait('当前剧情关已有入场记录','结果不明不再次入场；保留全部记录和现场。')
        if stage['id'] in self.book['stages'] and not (self.goal and stage['id']==SAINT_STAGE):
            self.ticket=None;self.r.back('这关已通关，返回地图选下一关');return True,.7
        if self.goal and stage_order(stage['id'])>stage_order(SAINT_STAGE):return self.wait('不会推进超过圣女3-7','当前准备页已超过目标关；返回目标地图后继续。')
        cost=entry_cost(f)
        if cost is None:return self.wait('等待清晰入场体力读数','未能可靠读取本次消耗/剩余体力，不猜测。')
        required,available=cost
        if available<required:
            self.r.s.update(status='等待体力自然恢复',reason=f'体力 {available}/{required}；不购买、不兑换，30秒后重新读取。',story_waiting_resource=True)
            self.r.save();return True,30
        self.r.s.pop('story_waiting_resource',None)
        if not auto_enabled(f):
            auto=f.find(r'^AUTO$',(880,625,1100,730))
            if not auto:return self.wait('无法识别AUTO开关','保留当前队伍，未开始战斗。')
            return self.act('开启剧情关卡原生自动战斗',auto)
        intent=dict(id=uuid.uuid4().hex,stage=stage['id'],name=stage['name'],region=stage['region'],cost=required,stamina_before=available,start_epoch=time.time(),proof='当前准备页精确关卡编号+体力+AUTO',evidence=self.r.evidence('story-entry-'+stage['id']))
        self.book['attempted'][intent['id']]=copy.deepcopy(intent);self.book['active']=intent
        self.r.save()  # Persist full per-run intent BEFORE the only entry click.
        self.entry_wait_until=time.monotonic()+15;self.ticket=None
        return self.act('剧情关卡入场 '+stage['id']+'（仅正常体力）',word)
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
                    name=previous['region'] if previous else self.book.get('chapter_regions',{}).get(str(neighbour)) or {1:SAINT_REGIONS[1],2:SAINT_REGIONS[2]}.get(neighbour)
                    gate=region_exit(f,current,self.book.get('regions_seen',[]),target_name=name)
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
            return self.act('关闭CLEAR胜利遮罩，继续读取出口或结算',xy=(800,820))
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
