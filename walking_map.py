"""Shared walking-map adapter: layout/observed identity, never title allowlists.

Uses StoryController's original entry journal, exits and settlement handling.
Short map numbers are scoped to the observed region, not guessed Episodes.
"""
from __future__ import annotations
import copy,hashlib,re,time,uuid
import cv2,numpy as np

_TITLE_PATTERN=r'[\u4e00-\u9fffA-Za-z0-9·（）()：:、\-\s]{2,60}'
_TITLE_RECT=(80,16,500,70)


def _map_anchors(f):
    def one(pattern,region,score=.98):
        x1,y1,x2,y2=region
        words=[w for w in f.words if re.fullmatch(pattern,w['text'].strip())
               and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        return words[0] if len(words)==1 and words[0]['score']>=score else None
    if f.find(r'Episode',(0,0,650,90)):return None
    if f.find(r'^(确认|确定|取消|点击关闭|點擊關閉|OK)$'):return None
    anchors=[one(pattern,region,score) for pattern,region,score in (
        (r'准备战斗',(1100,750,1599,899),.98),
        (r'任务',(1450,180,1599,280),.98),
        (r'地区信息',(1450,300,1599,420),.98),
        (r'成就',(650,750,900,899),.90),
        (r'交易所',(900,750,1120,899),.98))]
    return anchors if all(anchors) else None


def _map_titles(f):
    # The native Back icon/temporary navigation text is NOT part of the title.
    # A confident OCR line whose box crosses that control is still invalid.
    titles=[w for w in f.words if 80<=w['x']<=500 and 10<=w['y']<=85
            and re.fullmatch(_TITLE_PATTERN,w['text'].strip())
            and w.get('box') and min(p[0] for p in w['box'])>=80
            and max(p[0] for p in w['box'])<=500]
    reads=[w for w in titles if w.get('source')=='current_walking_title_field_read']
    originals=[w for w in titles if w.get('source')!='current_walking_title_field_read']
    if (len(reads)==len(originals)==1 and originals[0]['score']<.98
        and text_key(reads[0]['text'])==text_key(originals[0]['text'])):
        return reads
    return titles


def strengthen_walking_map_title(f,ocr):
    """One missing/invalid field read on this original frame; never a vote.

    Keep the original OCR line, pixels and timestamp. Only the fixed title
    field excludes the adjacent Back control; names are not an allowlist.
    """
    if not _map_anchors(f):return
    titles=_map_titles(f)
    if len(titles)>1 or (len(titles)==1 and titles[0]['score']>=.98):return
    if getattr(f,'walking_title_read',False):return
    f.walking_title_read=True
    x1,y1,x2,y2=_TITLE_RECT;crop=f.image[y1:y2,x1:x2]
    rows,_=ocr(crop)
    candidates=[(box,text.strip(),float(score)) for box,text,score in rows or []
                if re.fullmatch(_TITLE_PATTERN,text.strip())]
    if len(candidates)!=1 or candidates[0][2]<.98:return
    box,text,score=candidates[0]
    box=[[float(x)+x1,float(y)+y1] for x,y in box]
    # Do not discard duplicate/conflicting valid originals to manufacture one.
    if titles and text_key(titles[0]['text'])!=text_key(text):return
    f.words.append(dict(text=text,score=score,box=box,
        x=sum(p[0] for p in box)/len(box),y=sum(p[1] for p in box)/len(box),
        source='current_walking_title_field_read',
        verification=dict(captured_at=f.at,rect=list(_TITLE_RECT),
                          crop_sha256=hashlib.sha256(crop.tobytes()).hexdigest())))


def walking_map_info(f):
    """Recognize the shared map layout; short numbers never invent Episodes."""
    anchors=_map_anchors(f);titles=_map_titles(f)
    if not anchors or len(titles)!=1 or titles[0]['score']<.98:return None
    rows=[]
    for word in f.words:
        if not (80<=word['x']<1450 and 130<=word['y']<=740):continue
        match=re.fullmatch(r'([1-9]\d{0,2})[.．、]\s*(.+)',word['text'].strip())
        if not match:continue
        # An uncertain visible node cannot silently disappear from lock/history
        # checks; observe another current frame instead of choosing a subset.
        if word['score']<.98:return None
        rows.append(dict(number=int(match[1]),name=match[2].strip(),word=word,
                         id=None,locked=None,completion='unconfirmed'))
    if not rows or len({r['number'] for r in rows})!=len(rows):return None
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    for row in rows:
        x,y=round(row['word']['x']),round(row['word']['y'])
        tile=hsv[max(90,y-245):max(91,y-35),max(0,x-95):min(1450,x+95)]
        row['marker_score']=int(np.count_nonzero((tile[:,:,0]>105)&(tile[:,:,0]<158)&(tile[:,:,1]>100)&(tile[:,:,2]>160)))
        # Inspect every node independently. Only a coloured native node disk
        # (not surrounding terrain or a quest pin) permits free node selection.
        cy=max(110,y-65);y1,y2=cy-24,cy+25;x1,x2=max(0,x-24),min(1600,x+25)
        icon=hsv[y1:y2,x1:x2]
        yy,xx=np.ogrid[y1:y2,x1:x2]
        # Native enabled plates include purple as well as gold/blue. The tall
        # quest pointer is NOT an unlock: sample the local elliptical plate and
        # require colour in its centre, not character art/terrain above it.
        plate=((xx-x)/24)**2+((yy-cy)/17)**2<=1
        live=plate & (icon[:,:,1]>110) & (icon[:,:,2]>110) & ((icon[:,:,0]<35)|((icon[:,:,0]>=85)&(icon[:,:,0]<=165)))
        centre=(np.abs(xx-x)<=18)&(np.abs(yy-cy)<=6)
        row['node_colour_pixels']=int(np.count_nonzero(live))
        row['node_centre_colour_pixels']=int(np.count_nonzero(live&centre))
        row['navigation_visible']=row['node_colour_pixels']>=150 and row['node_centre_colour_pixels']>=80
        row['node_target']=(x,max(100,y-65))
        row['lock_observation']='no_positive_unlock' if not row['navigation_visible'] else 'coloured_native_node_only'
        # Generic closed-padlock evidence, if present, outranks node colour.
        from pathlib import Path
        path=Path(__file__).resolve().parent/'assets'/'lock.png'
        template=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),0) if path.is_file() else None
        tile=f.image[max(90,y-110):max(91,y-30),max(0,x-60):min(1450,x+60)]
        score=0.0
        if template is not None and tile.shape[0]>=template.shape[0] and tile.shape[1]>=template.shape[1]:
            score=float(cv2.matchTemplate(cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY),template,cv2.TM_CCOEFF_NORMED).max())
        row['lock_score']=score
        if score>=.88:row.update(locked=True,navigation_visible=False,lock_observation='current_closed_padlock')
    ranked=sorted(rows,key=lambda r:r['marker_score'],reverse=True)
    pin=ranked[0] if ranked[0]['marker_score']>=80 and (len(ranked)==1 or ranked[0]['marker_score']>ranked[1]['marker_score']*2+20) else None
    return dict(layout='walking_short',rows=rows,selected=pin,region=titles[0]['text'].strip(),
                title=titles[0],prepare=anchors[0],chapter=None,
                proof='完整免费地图布局；短编号仅作导航，准备页完整编号决定入场')


def text_key(value):
    return re.sub(r'\s+','',value).casefold() if isinstance(value,str) else ''


def region_key(region):
    return hashlib.sha256(text_key(region).encode('utf-8')).hexdigest()[:20]


def node_key(region,number):
    return 'walk:'+region_key(region)+':'+str(number)


class WalkingMapAdapter:
    """Supply map/preparation identity to the original StoryController engine."""
    def __init__(self,story):
        self.story=story;self.r=story.r
        self.allow_initial_binding=bool(getattr(self.r,'current_screen_start',False))
    @property
    def enabled(self):
        return bool(self.story.book_id and self.story.book.get('walking_map'))
    @property
    def data(self):
        return self.story.book.setdefault('walking_map',dict(schema=1,regions={},bindings={},navigation=[]))
    def observe(self,code,reason):
        return self.r.observe_progress_evidence('walking_map',dict(code=code,reason=reason))
    def attach(self,page):
        if self.story.goal:
            return self.story.wait('圣女任务不接管其他地图','普通行走地图不继承圣女3-7的循环权限；原支线记录完整保留。')
        books=self.r.s.get('story_progress',{}).get('books',{})
        region=page['region']
        matches=[key for key,b in books.items() if any(text_key(region)==text_key(name) for name in b.get('regions_seen',[b.get('region')]) if name)]
        route=self.data.get('route') if self.enabled else None
        routed=bool(route and text_key(route.get('target_region'))==text_key(region) and route.get('status')=='sent')
        if len(matches)>1:return self.story.wait('地图历史身份不唯一','同一地区关联多个原记录；不新建空历史、不选择任意一份。')
        if (self.enabled and not routed and not self.allow_initial_binding
            and text_key(region)!=text_key(self.story.book.get('region'))):
            return self.observe('map_region_changed','当前地区字段与原行走地图身份不同，且没有原生地区路线；只补采新帧，不以标题变化新建空历史。')
        if routed:
            if matches and matches[0]!=self.story.book_id:return self.story.wait('地区路线与原历史冲突','原路线和既有地区属于不同持久记录；不合并或绕过历史。')
        else:
            self.story.book_id=matches[0] if matches else 'walking|'+region
        aliases=[name for name in self.story.book.get('regions_seen',[]) if text_key(name)==text_key(region)]
        if len(aliases)>1:return self.story.wait('地区名称别名不唯一','保留原身份；不在不同地区别名之间建立新空记录。')
        if aliases:region=page['region']=aliases[0]
        existing=self.data['regions'].get(region,{})
        known=existing.get('nodes',{})
        for row in page['rows']:
            old=known.get(str(row['number']))
            if old and text_key(old['name'])!=text_key(row['name']):
                return self.story.wait('地区节点身份发生冲突','同地区同编号出现不同名称，保留原记录；不把新页面套入旧关。')
        self.story.bind(region);self.allow_initial_binding=False
        current=dict(region=region,nodes={**known,**{str(r['number']):dict(name=r['name']) for r in page['rows']}})
        self.data['regions'][region]=current
        if routed:
            route.update(accepted_at=time.time(),status='observed',evidence=self.r.evidence('walking-region-arrived'))
        return None
    def desired(self):
        if not self.enabled:return None
        last=self.story.book.get('last_cleared');binding=self.data['bindings'].get(last)
        if not binding or binding['region']!=self.story.book.get('region'):return None
        return node_key(binding['region'],binding['number']+1)
    def snapshot(self,page):
        from story_open_ack import binding
        return dict(run_id=getattr(self.r,'run_id',None),region=page['region'],
                    rows=[dict(number=r['number'],name=r['name'],locked=r['locked']) for r in page['rows']],
                    raw_size=list(self.r.frame.raw_size),binding=binding(self.r),captured_at=self.r.frame.at,
                    pixels_sha256=hashlib.sha256(self.r.frame.image.tobytes()).hexdigest(),
                    evidence=self.r.evidence('walking-map-source'))
    def navigate(self,kind,key,*,word=None,xy=None,back=False,source=None):
        from pc_backend import TapNotSent,FrameExpired,NavigationInputDeferred,NavigationFrameExpired
        self.last_navigation=None
        if not back and word is None and xy is None:
            return self.observe('navigation_target','本帧原生导航控件尚未完整识别；零输入继续观察。')
        records=self.data['navigation'];same=[v for v in records if v['key']==key and v.get('run_id')==getattr(self.r,'run_id',None) and not v.get('accepted_at')]
        if any(v['status'] in ('reserved','unknown') for v in same):
            return self.observe('navigation_unknown','原免费导航发送结果尚不明确；保留意图，不重用或继续耗资源入场。')
        sent=[v for v in same if v['status']=='sent']
        if sent and (time.time()-sent[-1]['sent_at']<2 or len(sent)>=3):
            return self.observe('navigation_response','等待已发送的免费地图导航响应；只重新取图，不连点或重发入场。')
        if not 0<=time.time()-self.r.frame.at<=5:
            return self.observe('navigation_frame','当前地图/准备页已过期；取新帧后重新核实，不刷新旧帧时间。')
        intent=dict(id=uuid.uuid4().hex,key=key,kind=kind,run_id=getattr(self.r,'run_id',None),
                    status='reserved',at=time.time(),source=copy.deepcopy(source),xy=xy,
                    evidence=self.r.evidence('walking-navigation-intent'))
        records.append(intent);self.r.save()
        try:
            if back:self.r.back(kind);result=(True,.25)
            else:result=self.story.act(kind,word=word,xy=xy)
        except (TapNotSent,FrameExpired) as exc:
            intent.update(status='not_sent',finished_at=time.time(),reason=str(exc));self.r.save()
            if isinstance(exc,TapNotSent):raise NavigationInputDeferred(str(exc)) from exc
            raise NavigationFrameExpired(str(exc)) from exc
        except Exception as exc:
            intent.update(status='unknown',finished_at=time.time(),reason=type(exc).__name__);self.r.save();raise
        intent.update(status='sent',sent_at=time.time());self.r.save();self.last_navigation=intent;return result
    def map_step(self,f,page):
        from runner import classify
        from pc_backend import PcSafetyError
        if f is not self.r.frame:raise PcSafetyError('地图观察不是当前帧；停止输入。')
        if classify(f)!='legacy_story_map':return self.observe('map_overlay','地图当前存在更高优先级页面/覆盖层；不发送导航。')
        attached=self.attach(page)
        if attached is not None:return attached
        active=self.story.book.get('active')
        if active:return self.observe('entry_response','原行走关卡已有入场，等待当前真实战斗/独立结算或通关事实；不因回到地图而再次入场。')
        last=self.data['bindings'].get(self.story.book.get('last_cleared'))
        desired=None
        if last and last['region']==page['region']:
            desired=next((r for r in page['rows'] if r['number']==last['number']+1),None)
            if desired and desired['locked'] is True:
                return self.observe('node_unlock','下一地图节点尚无可核实的原生解锁外观；持续观察，不猜锁、不把颜色当通关。')
            if desired is None:
                from story_core import region_exit
                gate=region_exit(f,None,self.story.book.get('regions_seen',[]))
                if gate:
                    source=self.snapshot(page)
                    response=self.navigate('前往已解锁行走地区 '+gate['name'],'route:'+page['region']+'>'+gate['name'],xy=(gate['x'],gate['y']),source=source)
                    latest=self.last_navigation
                    if latest:self.data['route']=dict(target_region=gate['name'],from_region=page['region'],status='sent',navigation_id=latest['id'],source=source);self.r.save()
                    return response
                # Reuse bounded background panning, never turn a missing row
                # into a completion fact or an invented next chapter.
                atlas={node_key(page['region'],row['number']):dict(x=row['word']['x'],y=row['word']['y']) for row in page['rows']}
                desired_key=node_key(page['region'],last['number']+1)
                search=self.story.book.get('navigation',{})
                if (search.get('desired')==desired_key and search.get('pan_region')==page['region']
                    and search.get('pan_tries',0)>=4):
                    # A missing N+1 is not a real stage or a defeat. Inspect the
                    # native parent route instead of repeatedly panning/latching.
                    source=self.snapshot(page)
                    result=self.navigate('返回地区总览核实后续路线',
                        'overview:'+page['region']+':'+str(last['number']),back=True,source=source)
                    latest=self.last_navigation
                    if latest:
                        self.data['overview_return']=dict(navigation_id=latest['id'],source=source,
                            last_completed=self.story.book['last_cleared'],status='sent')
                        self.r.save()
                    return result
                return self.story.pan_for(desired_key,atlas)
        source=self.snapshot(page)
        selection=self.data.get('selection')
        if desired and desired['navigation_visible'] and (not selection or selection.get('number')!=desired['number'] or selection.get('region')!=page['region']):
            response=self.navigate('选择行走地图节点 '+str(desired['number']),'select:'+node_key(page['region'],desired['number']),xy=desired['node_target'],source=source)
            latest=self.last_navigation
            if latest:self.data['selection']=dict(region=page['region'],number=desired['number'],navigation_id=latest['id']);self.r.save()
            return response
        source['expected_number']=desired['number'] if desired else None
        response=self.navigate('打开行走地图准备页','prepare:'+page['region']+':'+str(source['expected_number']),word=page['prepare'],source=source)
        latest=self.last_navigation
        if latest:self.data['preparation_source']=dict(source,navigation_id=latest['id']);self.r.save()
        return response
    def preparation(self,f):
        source=self.data.get('preparation_source')
        if not source or source.get('run_id')!=getattr(self.r,'run_id',None):return None,'missing_map'
        from story_open_ack import binding
        if list(f.raw_size)!=source['raw_size'] or binding(self.r)!=source.get('binding'):return None,'geometry'
        records=[v for v in self.data['navigation'] if v['id']==source['navigation_id']]
        if len(records)!=1 or records[0]['status']!='sent':return None,'navigation_unknown'
        if records[0].get('source')!={key:value for key,value in source.items() if key!='navigation_id'}:return None,'map_source_changed'
        if f.at<source['captured_at']:return None,'preparation_frame'
        # An explicit region field plus a unique exact stage title binds the
        # current prep to the observed map, not to a quest-pointer assumption.
        regions=[w for w in f.words if 1100<=w['x']<=1500 and 80<=w['y']<=140
                 and re.fullmatch(_TITLE_PATTERN,w['text'].strip())]
        if len(regions)!=1 or regions[0]['score']<.98:return None,'preparation_region'
        if text_key(regions[0]['text'])!=text_key(source['region']):return None,'region_mismatch'
        titles=[]
        for word in f.words:
            if not (1100<=word['x']<=1599 and 140<=word['y']<=220):continue
            match=re.fullmatch(r'(?:([1-9]\d{0,2})\s*[-−–—一]\s*)?([1-9]\d{0,2})[.．、。\s]+(.+)',word['text'].strip())
            if match:titles.append((word,match))
        if len(titles)!=1 or titles[0][0]['score']<.98:return None,'preparation_number'
        word,match=titles[0];number=int(match[2]);name=match[3].strip()
        rows=[r for r in source['rows'] if r['number']==number and text_key(r['name'])==text_key(name)]
        if len(rows)!=1 or rows[0].get('locked') is True:return None,'map_node'
        if source['expected_number'] is not None and source['expected_number']!=number:return None,'wrong_node'
        raw_id=(match[1]+'-' if match[1] else '')+str(number)
        identity=node_key(source['region'],number)
        return dict(id=identity,number=number,name=name,region=source['region'],word=word,raw_id=raw_id,
                    map_binding=copy.deepcopy(source)),None
    def prep_page_verified(self,f,mode):
        from runner import classify
        from story_core import team_entry_control
        if classify(f)!=mode:return False
        if mode=='team':return team_entry_control(f)['kind']=='single_task'
        if mode!='support':return False
        for pattern,area in ((r'^准备战斗$',(75,0,250,85)),(r'^选择辅助英雄$',(0,70,1100,240)),(r'^选择队伍$',(1130,750,1599,899))):
            words=[w for w in f.words if re.fullmatch(pattern,w['text']) and area[0]<=w['x']<=area[2] and area[1]<=w['y']<=area[3]]
            if len(words)!=1 or words[0]['score']<.98:return False
        return True
    def prep_step(self,f,mode):
        from story_core import team_entry_control
        from pc_backend import PcSafetyError
        if f is not self.r.frame:raise PcSafetyError('准备页观察不是当前帧；停止输入。')
        if not self.prep_page_verified(f,mode):return self.observe('preparation_layout','准备布局或唯一控件尚未完整核实，零输入等待；不绕过地图链入场。')
        if self.story.book.get('active'):
            return self.observe('entry_response','原关卡已有单次入场意图；等待游戏响应，绝不返回重发耗资源入场。')
        stage,error=self.preparation(f)
        if error=='geometry':raise PcSafetyError('地图来源与当前准备页几何不一致；停止输入，不刷新旧地图链。')
        if error in ('missing_map','wrong_node','region_mismatch','map_node'):
            return self.navigate('返回行走地图重新核实','back:'+error+':'+mode,back=True)
        if error:return self.observe(error,'正在核对当前准备页的地区、完整编号和地图节点名称（'+error+'）；未入场、未判战败，不要求逐章录入。')
        key=stage['id'];old=self.data['bindings'].get(key)
        if old and (old['region']!=stage['region'] or old['number']!=stage['number'] or text_key(old['name'])!=text_key(stage['name'])):
            return self.story.wait('准备关卡与原身份冲突','不覆盖原节点绑定或建立空历史。')
        # Reusing the shared engine must not create a blank-history escape from
        # old unscoped legacy or numbered Episode entries.
        for book in self.r.s.get('story_progress',{}).get('books',{}).values():
            for entry in book.get('attempted',{}).values():
                if entry.get('stage')==key:continue
                if text_key(entry.get('name',''))==text_key(stage['name']) and (text_key(entry.get('region'))==text_key(stage['region']) or entry.get('map_binding')):
                    return self.observe('original_history','该地图节点已有原剧情入场历史；保留原链，不以新布局身份再次入场。')
        for entry in self.r.s.get('attempted',{}).values():
            if entry.get('name') and text_key(entry['name'])==text_key(stage['name']):
                return self.observe('original_mainline_history','当前节点名称与原主线入场记录相同，身份尚不能互换；不建立空记录绕过历史。')
        self.data['bindings'].setdefault(key,dict(region=stage['region'],number=stage['number'],name=stage['name'],raw_id=stage['raw_id'],source=copy.deepcopy(stage['map_binding'])))
        nav=next(v for v in self.data['navigation'] if v['id']==stage['map_binding']['navigation_id'])
        if not nav.get('accepted_at'):nav.update(accepted_at=time.time(),accepted_evidence=self.r.evidence('walking-preparation-observed'));self.r.save()
        if stage['id'] in self.story.book.get('stages',{}):
            return self.navigate('已通关行走节点返回地图','back:completed:'+key,back=True)
        if mode=='support':
            self.data['prepared_stage']=key;self.r.save()
            return self.navigate('沿用队伍推进行走关卡','support:'+key,word=f.find(r'^选择队伍$',(1120,750,1599,899)))
        active=self.story.book.get('active')
        if active:return self.observe('entry_response','原关卡已有单次入场意图；等待游戏响应，绝不重发耗资源入场。')
        result=self.story.enter(f,stage,team_entry_control(f).get('target'))
        self.data.pop('selection',None);self.r.save();return result
