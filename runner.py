"""MuMu Epic Seven story runner. Android-local ADB only; never spends refill resources.
Every paid entry requires a fresh, positively verified uncleared map node.
"""
from __future__ import annotations
import  datetime as dt, difflib, json, os, re, subprocess, sys, time, traceback, tempfile
from pathlib import Path
CODE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_ROOT))
sys.path.insert(0, str(CODE_ROOT / 'vendor'))
from ui_text import ChineseArgumentParser,error_text,scene_name
from runtime_paths import data_root, config_path
from task_blockers import capacity_blocker,TaskAttention
from task_overlays import rankup_splash,account_upgrade_notice_close
from mainline_map import CLEAR_PROOFS,row_markers,read_stage_rating,is_cleared,is_unlocked
from story_core import map_info as legacy_map_info,exit_target as legacy_exit_target,clear_banner as legacy_clear_banner,region_cards as legacy_region_cards
import copy
ROOT = data_root()
for _stream in (sys.stdout,sys.stderr):
    if hasattr(_stream,'reconfigure'): _stream.reconfigure(encoding='utf-8',errors='replace')
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
TZ = dt.timezone(dt.timedelta(hours=8))
def now(): return dt.datetime.now(TZ).isoformat(timespec='seconds')
def norm(s): return re.sub(r'[\s，。！？：:,.!?·…+－_—\-|ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIl]+', '', s).lower()
def atomic_json(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)
def write_status_report(path,text):
    """Best-effort display report only; never use this for progress/evidence writes."""
    path=Path(path)
    if path.name!='STATUS.md':raise ValueError('允许暂缓写入的仅为状态展示报告；关键记录不适用。')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.STATUS-',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name);stream.write(text)
        os.replace(temporary,path)
        return ''
    except OSError as exc:
        winerror=getattr(exc,'winerror',None)
        code=('系统错误 '+str(winerror)) if winerror is not None else ('错误码 '+str(exc.errno) if exc.errno is not None else type(exc).__name__)
        return '状态报告暂时无法更新（'+code+'）；关键进度已保存，以软件界面和 state.json 为准。'
    finally:
        # Only this call's newly-created temporary file, never a destination/history file.
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass

def event(kind, **kwargs):
    with (ROOT/'events.jsonl').open('a', encoding='utf8') as f:
        f.write(json.dumps(dict(time=now(),kind=kind,**kwargs),ensure_ascii=False)+'\n')
class Frame:
    def __init__(self, image, results, raw_size=None):
        self.image=image; self.raw_size=raw_size or (1600,900); self.at=time.time()
        self.words=[]
        for box,text,score in results or []:
            if score < .55: continue
            self.words.append(dict(text=text, score=float(score), x=float(np.mean([p[0] for p in box])), y=float(np.mean([p[1] for p in box])), box=box))
        self.text='\n'.join(w['text'] for w in self.words)
        self.clean=norm(self.text)
    def find(self, pattern, region=(0,0,1600,900), exact=False):
        x1,y1,x2,y2=region
        return next((w for w in self.words if x1<=w['x']<=x2 and y1<=w['y']<=y2 and (norm(w['text'])==norm(pattern) if exact else re.search(pattern,w['text'],re.I))),None)
    def any(self,*terms): return any(norm(t) in self.clean for t in terms)

def selected_node(f):
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    p=CODE_ROOT/'assets'/'lock.png'
    lock_template=cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),cv2.IMREAD_GRAYSCALE) if p.exists() else None
    rows=[]
    for w in f.words:
        m=re.match(r'^\s*(\d{1,2})\s*[.．、。]\s*(.+)',w['text'])
        if not m or not (100<=w['x']<=650 and 190<=w['y']<=730):continue
        y=int(round(w['y']))
        row=dict(stage=int(m.group(1)),name=m.group(2),y=y,x=w['x'],**row_markers(f.image,hsv,y,lock_template))
        rows.append(row)
    rows.sort(key=lambda row:row['cyan'],reverse=True)
    if not rows or rows[0]['cyan']<.055:return None,rows
    if len(rows)>1 and rows[0]['cyan']-rows[1]['cyan']<.025:return None,rows
    chosen=rows[0]
    rating=read_stage_rating(f)
    chosen.update(star_count=rating['count'] if rating else None,star_evidence=rating)
    if rating and not chosen['locked']:
        if rating['count']==0 and chosen['clear_badge']:chosen['completion']='conflict'
        else:chosen['completion']='cleared' if rating['count']>0 else 'uncleared'
    return chosen,rows

def resource_warning(f):
    center=''.join(w['text'] for w in f.words if 280<w['x']<1330 and 130<w['y']<750)
    c=norm(center)
    phrases=['体力不足','行动力不足','补充体力','体力补充','恢复体力','体力恢复','兑换体力','购买体力','补充行动力','行动力补充','恢复行动力','行动力恢复','购买行动力','兑换行动力']
    if any(norm(x) in c for x in phrases): return True
    resource=any(norm(x) in c for x in ['生命之叶','天空石','道具','钻石'])
    use=any(norm(x) in c for x in ['是否消耗','是否使用','使用道具','消耗道具','购买','兑换','补充','不足'])
    return resource and use

def paid_revive_defeat_verified(f):
    # A defeat can hide FAILED behind the growth guide. A priced blue-currency
    # revive offer together with Leave/Replay is distinct from free Resume.
    if not f.find(r'^继续战斗$',(1050,760,1230,890)): return False
    if not f.find(r'^重新进行$',(1340,760,1599,890)): return False
    if not f.find(r'^离开$',(80,760,245,899)): return False
    price=f.find(r'^\d+$',(990,790,1060,865))
    if not price or price['score']<.90: return False
    hsv=cv2.cvtColor(f.image[790:860,945:990],cv2.COLOR_BGR2HSV)
    gem=(hsv[:,:,0]>=85)&(hsv[:,:,0]<=130)&(hsv[:,:,1]>70)&(hsv[:,:,2]>90)
    return int(np.count_nonzero(gem))>=100

def victory_objectives_verified(f):
    # Stylized CLEAR can be split/reordered by OCR. Require all three actual
    # result-only mission panels plus the GREEN success check in the first one.
    panels=((300,680,560,745),(720,680,1000,745),(1140,680,1450,745))
    if not all(f.find('关卡任务',region) for region in panels): return False
    if not f.find('闯关成功',(300,730,560,795)): return False
    hsv=cv2.cvtColor(f.image[680:755,245:320],cv2.COLOR_BGR2HSV)
    green=(hsv[:,:,0]>=32)&(hsv[:,:,0]<=85)&(hsv[:,:,1]>115)&(hsv[:,:,2]>100)
    return int(np.count_nonzero(green))>=100

def classify(f):
    # Vetoes are ordered before EVERY action, including every kind of confirmation.
    if capacity_blocker(w['text'] for w in f.words):return 'capacity_stop'
    if resource_warning(f): return 'resource_stop'
    if (f.any('网络连接异常') and f.any('重新连接') or f.any('与服务器的连接已中断')) and f.find('点击重试',(500,550,1100,780)): return 'network_error'
    version_retry=(f.find(r'^无法连接至版本服务器[。.]?$',(500,150,1100,280)),f.find(r'^网络连接失败$',(550,350,1050,530)),f.find(r'^点击重试$',(500,550,1100,780)))
    if all(word and word['score']>=.90 for word in version_retry):return 'network_error'
    if paid_revive_defeat_verified(f): return 'defeat'
    if account_upgrade_notice_close(f.words):return 'account_upgrade_notice'
    if rankup_splash(f.words):return 'rankup_splash'
    conf=f.find(r'^(确认|确定|確定|確認)$')
    cancel=f.find(r'^(取消|취소)$')
    middle=''.join(w['text'] for w in f.words if 260<w['x']<1360 and 140<w['y']<750)
    failure_banner=norm(''.join(w['text'] for w in f.words if 280<w['x']<1340 and 120<w['y']<640))
    if (any(norm(t) in failure_banner for t in ('FAILED','DEFEAT','战斗失败','挑战失败','闯关失败','任務失敗','任务失败'))
        or (f.any('再次挑战','重新挑战','再挑战') and not f.any('获得的道具','任务成功','闯关成功'))): return 'defeat'
    if f.any('给予协助的朋友') and f.any('发送好友申请') and f.find(r'^取消$',(500,570,800,720)) and f.find(r'^申请$',(800,570,1100,720)): return 'friend_decline'
    if conf and ('跳过教学' in middle or '跳过教學' in middle): return 'tutorial_skip_confirm'
    if f.find(r'^跳过教学$',(1330,0,1599,100)) and not conf:return 'tutorial_skip'
    if conf and ('跳过故事' in middle or '跳过剧情' in middle): return 'skip_confirm'
    if conf and cancel: return 'unknown_dialog'
    if f.any('故事完成奖励已正常发放','获得星星奖励已正常发放') and f.find('点击关闭',(500,500,1100,720)): return 'story_reward'
    if f.any('支线故事通知') and f.any('已解锁') and f.any('支线故事一览') and f.find('点击关闭',(500,550,1100,780)): return 'unlock_notice'
    # A settlement confirmation must have two independent result-only labels.
    if conf and f.find('获得的道具', (1150,0,1599,160)) and f.find('战斗结果',(1100,740,1430,899)):
        return 'settlement'
    if conf and f.any('Rank Up','Rank.Up','等级提升','等级上升') and not f.any('购买','兑换'): return 'rankup'
    if f.any('解锁缘分') and f.any('结下缘分') and f.find(r'^OK$',(600,550,1000,720)): return 'bond_notice'
    if legacy_region_cards(f):return 'legacy_story_regions'
    if legacy_map_info(f):return 'legacy_story_map'
    if legacy_clear_banner(f):return 'legacy_story_clear'
    if legacy_exit_target(f):return 'legacy_story_exit'
    if f.find(r'^离开$',(50,750,230,899)) and f.find(r'^大厅$',(250,750,430,899)) and f.find(r'^重新进行$',(1300,750,1599,899)): return 'post_clear_exit'
    if f.find(r'跳过', (1400,0,1599,100)): return 'story'
    if (f.any('CLEAR','VICTORY') and f.any('关卡任务') and f.any('闯关成功')) or victory_objectives_verified(f): return 'victory'
    if f.find('准备战斗',(1200,750,1599,899)) and f.find('Episode',(50,0,400,90)):
        return 'map'
    if f.find('选择队伍',(1130,750,1599,899)) and f.any('选择辅助英雄'): return 'support'
    if f.find('进行任务|战斗开始',(1150,750,1599,899)) and f.any('队伍战斗力','管理队伍'): return 'team'
    if f.find(r'^Episode$',(1300,120,1599,330)) and f.find(r'Rank',(0,0,400,150)): return 'lobby'
    if f.find(r'\d\s*/\s*\d',(140,0,400,85)) or f.find(r'\d+\s*/\s*\d+',(280,770,690,899)):
        return 'battle'
    if f.any('CLEAR','VICTORY') and not conf: return 'result_transition'
    if f.image.mean()<13: return 'loading'
    if conf or cancel: return 'unknown_dialog'
    return 'unknown'

class Runner:
    def __init__(self,observe=False):
        self.cfg=json.loads(config_path().read_text(encoding='utf-8-sig'))
        if self.cfg.get('backend','mumu_adb') not in ('mumu_adb','stove_pc'):
            raise RuntimeError('未知的输入后端；禁止发送输入。')
        self.pc=None
        if self.cfg.get('backend')=='stove_pc':
            from pc_backend import PcBackend
            if not (ROOT/'state.json').is_file():
                raise RuntimeError('桌面端需要明确选择已有进度记录；不会创建空历史。')
            self.pc=PcBackend(self.cfg['pc'],ROOT/'STOP')
            if not observe:self.pc.authorize(self.cfg.get('pc_preflight',{}))
        self.s=json.loads((ROOT/'state.json').read_text(encoding='utf8')) if (ROOT/'state.json').exists() else {'schema':1,'started_at':now(),'completed':{},'attempted':{},'active':None,'victories':0}
        if self.pc and not observe:
            binding=self.s.get('pc_profile_binding') or {}
            if any(str(binding.get(k,''))!=str(self.cfg['pc'].get(k,'')) for k in ('server','account_id')):
                raise RuntimeError('旧版桌面端历史缺少匹配的账号或服务器绑定；请使用对应的桌面端启动器。')
        self.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        self.ticket=None; self.last_mode=None; self.mode_since=time.time(); self.battle_seen=0; self.last_gesture=0; self.last_stamina=None; self.unknown_gestures=0
    def adb(self,*args,timeout=25):
        r=subprocess.run([self.cfg['adb'],'-s',self.cfg['serial'],*map(str,args)],capture_output=True,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode: raise RuntimeError(r.stderr.decode(errors='replace')[:1000])
        return r.stdout
    def capture(self):
        if getattr(self,'pc',None):
            raw=self.pc.capture()
        else:
            png=self.adb('exec-out','screencap','-p')
            raw=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
        if raw is None: raise RuntimeError('模拟器截图无效。')
        h,w=raw.shape[:2]
        if w<h: raise RuntimeError('检测到纵向画面；未发送输入。')
        if not getattr(self,'pc',None) and abs(w/h-16/9)>.03: raise RuntimeError('请将模拟器设为 16:9 横屏分辨率；未发送输入。')
        im=cv2.resize(raw,(1600,900)) if (w,h)!=(1600,900) else raw
        results,_=self.ocr(im)
        f=Frame(im,results,(w,h))
        self.frame=f
        tmp=ROOT/'latest.tmp.png'; tmp.write_bytes(cv2.imencode('.png',im)[1].tobytes()); os.replace(tmp,ROOT/'latest.png')
        atomic_json(ROOT/'latest-ocr.json',dict(time=now(),words=f.words,text=f.text))
        energy=f.find(r'\d+\s*/\s*\d+',(770,0,925,85)) or f.find(r'\d+\s*/\s*\d+',(950,0,1100,85))
        if energy:
            m=re.search(r'(\d+)\s*/\s*(\d+)',energy['text'])
            if m and int(m.group(2))>=100: self.s['stamina']=int(m.group(1))
        return f
    def save(self):
        self.s['updated_at']=now(); self.s['worker_pid']=os.getpid()
        self.s['manual_clears']=sum(1 for item in self.s.get('completed',{}).values() if item.get('manual_completed'))
        self.s['script_victories']=self.s.get('victories',0)-self.s['manual_clears']
        atomic_json(ROOT/'state.json',self.s)
        active=self.s.get('active') or self.ticket or {}
        text=(f"# 第七史诗主线运行状态\n\n- 状态：**{self.s.get('status','启动中')}**\n- 更新时间：{self.s['updated_at']}（北京时间）\n- 当前/最近关卡：{active.get('key',self.s.get('last_stage','待识别'))} {active.get('name','')}\n- 本次已确认通关：{self.s.get('victories',0)} 关（脚本 {self.s.get('script_victories',0)}，用户手动补过 {self.s.get('manual_clears',0)}）\n- 最近读取体力：{self.s.get('stamina','未读取')}\n- 说明：{self.s.get('reason','')}\n- 最后动作：{self.s.get('last_action','无')}\n\n安全规则：不兑换/购买体力；不点重复挑战；已尝试关卡不再次入场；无法确认未通关时停止。\n\n最近画面见 latest.png；动作与安全检查见 events.jsonl；通关/尝试记录见 state.json。\n")
        previous=getattr(self,'report_warning','')
        self.report_warning=write_status_report(ROOT/'STATUS.md',text)
        if self.report_warning!=previous:
            message=self.report_warning or '状态报告已恢复更新。'
            print(json.dumps({'kind':'log','text':message},ensure_ascii=False),flush=True)
    def evidence(self,label):
        p=ROOT/'evidence'/f"{dt.datetime.now(TZ):%H%M%S}-{label}.png"; p.parent.mkdir(exist_ok=True)
        p.write_bytes(cv2.imencode('.png',self.frame.image)[1].tobytes())
        return str(p.relative_to(ROOT))
    def ensure_game(self):
        if getattr(self,'pc',None):
            self.pc.ensure();return
        activity=self.adb('shell','dumpsys','activity','activities').decode('utf8',errors='replace')
        resumed=[line for line in activity.splitlines() if 'topResumedActivity' in line or 'mResumedActivity' in line]
        if not any(self.cfg['package'] in line for line in resumed):
            raise RuntimeError('模拟器前台应用不是已授权的游戏；未发送输入。')
    def action(self,kind,word=None,xy=None):
        self.ensure_game()
        if time.time()-self.frame.at>5: raise RuntimeError('观察画面已过期；已取消操作。')
        blocker=capacity_blocker(w['text'] for w in self.frame.words)
        if blocker:raise TaskAttention(blocker.code,blocker.title,blocker.reason)
        if resource_warning(self.frame): raise RuntimeError('输入前触发资源消耗保护，已拒绝操作。')
        x,y=xy if xy else (word['x'],word['y'])
        w,h=self.frame.raw_size; coords=[round(x*w/1600),round(y*h/900)]
        self.input_sequence=getattr(self,'input_sequence',0)+1
        event('action',action=kind,xy=coords,stage=(self.s.get('active') or self.ticket or {}).get('key'))
        self.s['last_action']=kind; self.save()
        if getattr(self,'pc',None):self.pc.tap(x,y)
        else:self.adb('shell','input','tap',*coords)
    def drag(self,why,start,end):
        self.ensure_game()
        if time.time()-self.frame.at>5:raise RuntimeError('观察画面已过期；已取消地图拖动。')
        if capacity_blocker(w['text'] for w in self.frame.words) or resource_warning(self.frame):raise RuntimeError('地图拖动前触发业务安全保护，已拒绝操作。')
        self.input_sequence=getattr(self,'input_sequence',0)+1;self.s['last_action']=why;self.save();event('drag',reason=why,start=start,end=end)
        if getattr(self,'pc',None):self.pc.drag(*start,*end)
        else:
            w,h=self.frame.raw_size
            self.adb('shell','input','swipe',round(start[0]*w/1600),round(start[1]*h/900),round(end[0]*w/1600),round(end[1]*h/900),450)
    def back(self,why):
        self.ensure_game()
        self.input_sequence=getattr(self,'input_sequence',0)+1
        event('back',reason=why); self.s['last_action']='返回主线重新验证'; self.save()
        if getattr(self,'pc',None):self.pc.back()
        else:self.adb('shell','input','keyevent','4')
    def stop(self,status,reason):
        self.s.update(status=status,reason=reason,terminal=True,stop_at=now(),stop_evidence=self.evidence('STOP'))
        self.save(); event('stop',status=status,reason=reason); print(json.dumps({'status':status,'reason':reason},ensure_ascii=False),flush=True)
        return False,0
    def start_current_screen(self):
        # Complete snapshot retained before releasing display-only terminal state.
        if self.s.get('terminal') or self.s.get('active') or self.s.get('attention'):
            self.s.setdefault('resume_audit',[]).append(dict(at=now(),policy='current_screen',previous=copy.deepcopy(self.s if 'resume_audit' not in self.s else {k:v for k,v in self.s.items() if k!='resume_audit'})))
        self.archive_unresolved_active('新任务从当前画面继续，旧入场不再用于推断本次结算')
        self.s.update(terminal=False,status='从当前画面继续',reason='不回查旧关，不自动重试；原始记录完整留档')
        self.s.pop('attention',None);self.save()
    def archive_unresolved_active(self,why):
        active=self.s.get('active')
        if active:
            self.s.setdefault('unresolved_entries',[]).append(dict(at=now(),reason=why,entry=copy.deepcopy(active)))
            self.s['active']=None;self.save()
    def attention(self,code,title,reason):
        self.ticket=None
        self.s.update(status=title,reason=reason,terminal=False,attention=dict(code=code,at=now(),evidence=self.evidence('ATTENTION')))
        self.save();raise TaskAttention(code,title,reason)
    def completed(self,proof):
        a=self.s.get('active')
        if not a: return
        key=a['key']
        if key not in self.s['completed']:
            self.s['completed'][key]={**a,'completed_at':now(),'proof':proof,'evidence':self.evidence('clear-'+key)}
            self.s['victories']=len(self.s['completed'])
            event('completed',stage=key,proof=proof)
        self.s['last_stage']=key; self.s['last_cleared']=a; self.s['active']=None; self.save()
    def map_ticket(self,f):
        e=f.find(r'Episode\s*\d+',(50,0,430,90)); c=f.find(r'第\s*\d+\s*章',(80,95,340,160))
        node,rows=selected_node(f)
        if not e or not c or not node: return None,rows,'无法可靠识别章节、编号或蓝色选中节点'
        episode=int(re.search(r'\d+',e['text']).group()); chapter=int(re.search(r'\d+',c['text']).group())
        d=dict(episode=episode,chapter=chapter,**node)
        d['key']=f"E{episode}-C{chapter}-S{node['stage']}"; d['verified_epoch']=time.time()
        if node['locked']:return d,rows,'锁定关卡'
        if node['completion']=='conflict':return d,rows,'当前通关标记不一致'
        if is_cleared(node):return d,rows,'已通关绿色勾' if node['clear_badge'] else '已通关关卡星级'
        return d,rows,'未通关蓝色当前节点'
    def title_matches(self,f):
        if not self.ticket: return False
        target=norm(self.ticket['name']); titlewords=[w for w in f.words if 1140<w['x']<1560 and 145<w['y']<195]
        return any(difflib.SequenceMatcher(None,target,norm(w['text'])).ratio()>.68 for w in titlewords)
    def step(self,f):
        mode=classify(f); self.s['screen']=mode
        if mode!=self.last_mode:
            self.mode_since=time.time(); self.unknown_gestures=0; self.last_mode=mode
            event('screen',screen=mode,stage=(self.s.get('active') or self.ticket or {}).get('key'))
        age=time.time()-self.mode_since
        self.s.update(status='正在推进主线',reason='已识别画面：'+scene_name(mode),terminal=False)
        if (ROOT/'STOP').exists(): return self.stop('用户停止','检测到 STOP 文件；未关闭游戏')
        if mode=='network_error':
            retries=[x for x in self.s.get('network_retries',[]) if time.time()-x<600]
            if len(retries)>=3: return self.stop('网络异常停止','10分钟内三次网络重连仍未恢复；不重开关卡、不改代理、不消费资源')
            retries.append(time.time());self.s['network_retries']=retries;self.ticket=None
            self.s.update(status='正在恢复网络连接',reason='只点击已明确识别的网络重试，不是关卡重试；入场和通关记录保留')
            self.action('网络重试（非关卡重试）',f.find('点击重试',(500,550,1100,780))); return True,10
        if mode=='capacity_stop':
            b=capacity_blocker(w['text'] for w in f.words)
            return self.attention(b.code,b.title,b.reason)
        if mode=='resource_stop':
            return self.attention('resource','体力/入场资源不足','请手动处理后点“处理后继续”；没有确认、兑换或使用资源。')
        if mode=='defeat': return self.stop('强度不足卡关','识别到战斗失败/付费续战界面；不花费资源续战、不重新挑战，保留现场')
        if mode=='unknown_dialog': return self.attention('dialog','弹窗等待处理','请手动处理当前弹窗后点“处理后继续”；未自动确认或购买。')
        if getattr(self,'story',None):
            result=self.story.step(f,mode)
            if result is not None:return result
        if mode=='friend_decline':
            self.action('取消好友申请提示，不发送任何好友申请',f.find(r'^取消$',(500,570,800,720))); return True,3
        if mode=='tutorial_skip':
            self.action('跳过已识别的免费地图教学',f.find(r'^跳过教学$',(1330,0,1599,100)));return True,1
        if mode=='tutorial_skip_confirm':
            self.action('确认仅跳过教学',f.find(r'^(确认|确定|確定|確認)$'));return True,1
        if mode=='skip_confirm':
            self.action('确认跳过剧情',f.find(r'^(确认|确定|確定|確認)$')); return True,2
        if mode=='story':
            self.action('跳过剧情',f.find('跳过',(1400,0,1599,100))); return True,2
        if mode=='settlement':
            if not self.s.get('active') and not self.s.get('last_cleared') and self.cfg.get('start_policy')!='current_screen':
                return self.stop('安全暂停待修复','结算画面没有可对应的本次入场记录，停止而非猜测进度')
            self.completed('独立识别：获得的道具 + 战斗结果 + 结算确认')
            self.ticket=None
            self.action('确认通关结算',f.find(r'^(确认|确定|確定|確認)$',(1300,750,1599,899))); return True,4
        if mode=='unlock_notice':
            self.action('关闭免费支线解锁通知，继续主线',f.find('点击关闭',(500,550,1100,780))); return True,3
        if mode=='bond_notice':
            self.action('关闭已解锁缘分的免费通知',f.find(r'^OK$',(600,550,1000,720))); return True,3
        if mode=='post_clear_exit':
            if self.s.get('active') or (not self.s.get('last_cleared') and self.cfg.get('start_policy')!='current_screen'): return self.stop('安全暂停待修复','关后离开界面缺少已结算记录；不点重新进行')
            self.action('已结算后离开关卡，绝不重新进行',f.find(r'^离开$',(50,750,230,899))); return True,4
        if mode=='story_reward':
            self.action('关闭已发放的免费奖励遮罩',f.find('点击关闭',(500,500,1100,720))); return True,3
        if mode=='victory':
            if not self.s.get('active') and not self.s.get('last_cleared') and self.cfg.get('start_policy')!='current_screen': return self.stop('安全暂停待修复','胜利页缺少本次入场记录')
            if self.s.get('active') and not self.s['active'].get('victory_seen'):
                self.s['active']['victory_seen']=True; self.s['active']['victory_evidence']=self.evidence('victory-'+self.s['active']['key'])
            self.action('通关星级页继续至结算',xy=(1550,845)); return True,3
        if mode=='account_upgrade_notice':
            self.action('关闭免费账号升级行动力上限提示',account_upgrade_notice_close(f.words));return True,3
        if mode=='rankup_splash':
            self.action('关闭免费等级提升全屏提示',xy=(800,872));return True,3
        if mode=='rankup':
            self.action('关闭等级提升提示',f.find(r'^(确认|确定|確定|確認)$')); return True,3
        if mode=='lobby':
            self.ticket=None
            if self.s.get('active'):
                if self.cfg.get('start_policy')=='current_screen':self.archive_unresolved_active('当前已在大厅；不回查旧关')
                else:return self.stop('安全暂停待修复','未见结算即返回大厅；保留已尝试记录，不重新开同一关')
            self.action('从大厅进入主线章节',f.find(r'^Episode$',(1300,120,1599,330))); return True,4
        if mode=='map':
            d,rows,proof=self.map_ticket(f)
            if not d:
                if age<20: self.save(); return True,4
                return self.stop('安全暂停待修复',proof)
            self.s['map_verification']=dict(target=d,proof=proof,rows=rows)
            a=self.s.get('active')
            if a and self.cfg.get('start_policy')=='current_screen':
                self.archive_unresolved_active('从当前地图选择新关；不回查原关是否通关');a=None
            if a:
                oldrow=next((r for r in rows if r['stage']==a['stage']),None)
                if d['episode']==a['episode'] and d['chapter']==a['chapter'] and is_cleared(oldrow):
                    self.completed('返回地图后，原关卡出现绿色已通关勾')
                else: return self.stop('安全暂停待修复','已入场但未确认通关；保留尝试记录，不重复开战')
            if proof=='锁定关卡': return self.stop('安全暂停待修复','当前节点仍锁定；不入场、不回刷旧关')
            if proof=='当前通关标记不一致':return self.attention('stage_rating','当前关通关标记不一致','已读到的星级和通关勾互相矛盾，未将此关判为完成；刷新当前关后继续。')
            if proof in CLEAR_PROOFS:
                nextrow=next((r for r in rows if r['stage']==d['stage']+1),None)
                if nextrow and is_unlocked(nextrow) and not is_cleared(nextrow):
                    self.ticket=None; self.action('避开已通关关卡，选择下一关',xy=(nextrow['x'],nextrow['y'])); return True,3
                if nextrow and not is_unlocked(nextrow):return self.attention('locked_next','下一关尚未解锁','当前关通关标记已识别，但下一关仍带锁；不会点击锁定关卡。')
                if d['stage']>=10:
                    self.ticket=None; self.action('完成本章后进入下一章',xy=(320,137)); return True,4
                return self.stop('安全暂停待修复','当前已通关且无法可靠定位下一新关卡；未重复挑战')
            if d['key'] in self.s['attempted'] or d['key'] in self.s['completed']:
                if self.cfg.get('start_policy')=='current_screen':
                    return self.attention('current_stage_unresolved','当前关未显示通关',f"{d['key']} 只有原入场/历史记录，当前画面没有明确通关标记；不当作已完成跳关、不点击后面的锁定关。处理当前关后可从所选新关继续，不回查旧关。")
                return self.stop('安全暂停待修复',f"防重复入场：{d['key']} 已有尝试记录，不再次消耗体力")
            if self.s.get('last_cleared') and self.cfg.get('start_policy')!='current_screen':
                last=self.s['last_cleared']
                if (d['episode'],d['chapter'],d['stage']) <= (last['episode'],last['chapter'],last['stage']):
                    return self.stop('安全暂停待修复','关卡编号未向前推进，拒绝倒退刷关')
            self.ticket=d; self.ticket['proof']=proof; self.ticket['evidence']=self.evidence('preflight-'+d['key']); self.ticket['phase']='map'
            self.s['verified']=self.ticket; self.s['last_stage']=d['key']
            event('preflight',target=self.ticket)
            self.action('未通关验证通过，准备战斗',f.find('准备战斗',(1200,750,1599,899))); return True,3
        if mode=='support':
            if not self.ticket or self.ticket.get('phase') not in ('map','support') or time.time()-self.ticket['verified_epoch']>120:
                self.ticket=None; self.back('辅助界面没有本轮新关验证凭据'); return True,3
            if not self.title_matches(f): return self.stop('安全暂停待修复','辅助选择界面的关卡名称与已验证地图节点不一致')
            self.ticket['phase']='support'
            self.action('选择当前队伍',f.find('选择队伍',(1130,750,1599,899))); return True,3
        if mode=='team':
            if self.s.get('active'):
                if self.cfg.get('start_policy')=='current_screen':
                    self.archive_unresolved_active('已有入场意图，返回当前地图而非重复开战');self.ticket=None;self.back('从当前地图继续');return True,3
                return self.stop('安全暂停待修复','已记录一次入场请求但仍在队伍页；不重复点击进行任务')
            if not self.ticket or self.ticket.get('phase')!='support' or time.time()-self.ticket['verified_epoch']>120:
                self.ticket=None; self.back('队伍界面没有完整地图验证链'); return True,3
            if not self.title_matches(f): return self.stop('安全暂停待修复','开战前关卡名称不一致，拒绝入场')
            cost=f.find(r'\d+\s*/\s*\d+',(1180,775,1340,880))
            if not cost or cost['score']<.90:
                if age<20:
                    self.s['reason']='入场数字受闪光/动画干扰，等待新截图重新严格读取；尚未入场、不猜测数值'
                    self.save(); return True,3
                return self.stop('安全暂停待修复','连续20秒不能可靠读取入场消耗和剩余体力，拒绝猜测')
            match=re.search(r'(\d+)\s*/\s*(\d+)',cost['text']); required,available=map(int,match.groups())
            if required>100: return self.stop('安全暂停待修复','入场消耗读数异常')
            if available<required: return self.attention('resource','体力不足',f'当前体力 {available} 小于消耗 {required}；手动处理后继续，没有打开兑换框。')
            self.s['stamina']=available
            hsv=cv2.cvtColor(f.image[650:710,900:1095],cv2.COLOR_BGR2HSV)
            isauto=np.count_nonzero((hsv[:,:,0]>30)&(hsv[:,:,0]<90)&(hsv[:,:,1]>90)&(hsv[:,:,2]>65))>800
            if not isauto:
                auto=f.find(r'^AUTO$',(880,625,1100,730))
                if not auto: return self.stop('安全暂停待修复','无法确认自动战斗开关')
                self.action('开启自动战斗',auto); return True,2
            key=self.ticket['key']
            if key in self.s['attempted'] or key in self.s['completed']: return self.stop('安全暂停待修复','最终开战前防重检查未通过')
            a=dict(self.ticket,cost=required,stamina_before=available,started_at=now(),start_epoch=time.time())
            self.s['attempted'][key]=a; self.s['active']=a
            self.s['reason']=f"已验证新关 {key}，本次入场只消耗体力 {required}，绝不兑换"
            self.save() # Durable intent BEFORE the one permitted entry input.
            self.action('进行任务（仅一次入场）',f.find('进行任务',(1300,750,1599,899))); self.ticket=None; return True,5
        if mode=='battle':
            self.battle_seen=time.time()
            a=self.s.get('active')
            if a and time.time()-a['start_epoch']>self.cfg['max_battle_seconds']:
                return self.stop('安全暂停待修复','单关超时，不能确定强度不足；保持现场，未重开关卡')
            self.s['reason']='自动战斗中，等待剧情或通关结算；不点击技能、召唤或重试'; self.save(); return True,5
        if mode in ('loading','result_transition'):
            if age>180: return self.stop('安全暂停待修复','加载或结果过渡超过3分钟，保留现场等待巡检')
            self.save(); return True,4
        # Full-screen CG: only during a recorded run, no popup labels, no battle HUD.
        a=self.s.get('active')
        if a and age>=12 and time.time()-self.battle_seen>12 and time.time()-self.last_gesture>25 and self.unknown_gestures<2:
            if len(f.words)<=8 and not f.any('确认','确定','取消','购买','兑换','补充','使用','消耗','重试','商店','返回','菜单','轻触画面开始','轻触屏幕开始','账号','服务器','登录','登陆','验证','STOVE') and f.image.mean()>20:
                self.last_gesture=time.time(); self.unknown_gestures+=1
                self.evidence('CG-before')
                self.action('全屏CG第一下点击',xy=(800,450))
                time.sleep(.12)
                # Android touch gesture, not a Windows mouse operation. Same safe CG point.
                w,h=f.raw_size; x,y=round(w/2),round(h/2)
                if getattr(self,'pc',None):
                    second=self.capture()
                    if resource_warning(second) or classify(second)!='unknown' or len(second.words)>8:
                        return self.stop('安全暂停待修复','PC长按前画面已变化；不继续CG手势')
                    self.pc.hold(800,450,2.8)
                else:self.adb('shell','input','swipe',x,y,x,y,2800)
                event('action',action='全屏CG第二下按住2.8秒')
                self.save(); return True,5
        if age>90: return self.stop('安全暂停待修复','未知画面持续90秒；不盲点确认、不回刷旧关')
        self.save(); return True,4
    def run(self,once=False,observe=False):
        if self.s.get('terminal') and not observe:
            print('保留停止状态；请查看状态报告。处理原因后，需明确执行续跑命令。',flush=True); return
        errors=0
        while True:
            try:
                f=self.capture()
                if observe:
                    d,rows,p=self.map_ticket(f) if classify(f)=='map' else (None,[],None)
                    print(json.dumps(dict(mode=classify(f),text=f.text,target=d,proof=p,rows=rows),ensure_ascii=False,indent=2)); return
                keep,delay=self.step(f); errors=0
                print(json.dumps(dict(time=now(),screen=classify(f),status=self.s['status'],active=self.s.get('active',{}),last_action=self.s.get('last_action')),ensure_ascii=False),flush=True)
                if once or not keep: return
                time.sleep(delay)
            except KeyboardInterrupt: return
            except Exception as exc:
                errors+=1; event('error',error=str(exc),trace=traceback.format_exc())
                if getattr(self,'pc',None):
                    self.s.update(status='PC安全暂停',reason=error_text(exc),terminal=True);self.save();return
                self.s.update(status='异常重连中',reason=error_text(exc)); self.save()
                if errors>=3:
                    self.s.update(status='安全暂停待修复',reason='连续三次异常：'+error_text(exc),terminal=True); self.save(); return
                time.sleep(5)
                try: subprocess.run([self.cfg['adb'],'connect',self.cfg['serial']],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception: pass


def record_pc_startup_failure(exc):
    """Preserve history when native initialization fails before the run loop."""
    try:
        cfg=json.loads(config_path().read_text(encoding='utf-8-sig'))
        if cfg.get('backend')!='stove_pc':return False
        state=json.loads((ROOT/'state.json').read_text(encoding='utf8'))
        state.update(terminal=True,status='PC启动安全暂停',reason=error_text(exc),updated_at=now())
        atomic_json(ROOT/'state.json',state)
        active=state.get('active') or state.get('last_cleared') or {}
        text=(f"# 第七史诗主线运行状态\n\n- 状态：**PC启动安全暂停**\n- 更新时间：{state['updated_at']}\n- 当前/最近关卡：{active.get('key','未识别')}\n- 本次已确认通关：{len(state.get('completed',{}))}\n- 说明：{error_text(exc)}\n\n启动未完成，不发送输入；全部原始入场/通关记录保留。\n")
        warning=write_status_report(ROOT/'STATUS.md',text)
        if warning:print(json.dumps({'kind':'log','text':warning},ensure_ascii=False),flush=True)
        event('pc_startup_stop',error=str(exc),preserved_all_history=True)
        return True
    except Exception:return False


def main():
    parser=ChineseArgumentParser(); parser.add_argument('--observe',action='store_true'); parser.add_argument('--step',action='store_true'); args=parser.parse_args()
    import msvcrt
    lock=(ROOT/'worker.lock').open('a+b')
    if lock.seek(0,os.SEEK_END)==0: lock.write(b'0'); lock.flush()
    lock.seek(0)
    try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: print('工作进程已在运行；未启动第二个执行进程。'); return
    try:
        try:Runner(observe=args.observe).run(once=args.step,observe=args.observe)
        except Exception as exc:
            if args.observe or not record_pc_startup_failure(exc):raise
            print('桌面端启动已安全停止：'+error_text(exc),flush=True);return 1
    finally: lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1); lock.close()
if __name__=='__main__': raise SystemExit(main())

