"""MuMu Epic Seven story runner. Android-local ADB only; never spends refill resources.
Every paid entry requires a fresh, positively verified uncleared map node.
"""
from __future__ import annotations
import  datetime as dt, difflib, hashlib, json, os, re, subprocess, sys, time, traceback, tempfile
from pathlib import Path
CODE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_ROOT))
sys.path.insert(0, str(CODE_ROOT / 'vendor'))
from ui_text import ChineseArgumentParser,error_text,scene_name
from runtime_paths import data_root, config_path
from task_blockers import capacity_blocker,TaskAttention
from task_overlays import rankup_splash,account_upgrade_notice_close,friendship_upgrade_notice_close,FRIENDSHIP_TITLES,battle_settlement_confirm,date_change_notice_close,chat_panel_visible,chat_panel_heading,top_right_skip_control,tutorial_completed_notice_close
from map_identity import chapter_header,same_chapter,stage_key,stage_order,native_forward_chapter
from mainline_map import CLEAR_PROOFS,chapter_navigation_control,row_markers,read_stage_rating,is_cleared,is_unlocked,clipped_story_completion,complete_map_row_labels
from story_core import map_info as legacy_map_info,exit_target as legacy_exit_target,clear_banner as legacy_clear_banner,region_cards as legacy_region_cards
from story_core import team_entry_control
from tutorial_core import tutorial_plan,TutorialController,chapter_reward_pending,owned_hero_selector_visible
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
def atomic_json(path, value, *, compact=False):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=None if compact else 2, separators=(',',':') if compact else None), encoding='utf-8')
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

def write_capture_display(root,image_bytes,ocr_payload):
    """Publish display copies, retaining a durable fresh pair if either is busy.

    Only latest.png/latest-ocr.json replacement is best-effort. Temp creation,
    capture/OCR encoding, and the independent evidence fallback MUST succeed or
    the exception propagates, before any input can use this captured frame.
    """
    root=Path(root);temporaries=[]
    payload=json.dumps(ocr_payload,ensure_ascii=False,indent=2).encode('utf-8')
    try:
        for suffix,data in (('.png',image_bytes),('.json',payload)):
            with tempfile.NamedTemporaryFile(dir=root,prefix='.capture-',suffix=suffix,delete=False) as stream:
                path=Path(stream.name);temporaries.append(path);stream.write(data)
        try:
            os.replace(temporaries[0],root/'latest.png')
            os.replace(temporaries[1],root/'latest-ocr.json')
            return '',None
        except OSError:
            # A busy display destination is not permission to discard the fresh
            # screenshot/OCR. Preserve both in new, non-overwriting evidence files.
            import uuid
            tag='capture-'+str(time.time_ns())+'-'+uuid.uuid4().hex
            folder=root/'evidence';folder.mkdir(exist_ok=True)
            image=folder/(tag+'.png');ocr=folder/(tag+'.json')
            with image.open('xb') as stream:stream.write(image_bytes)
            with ocr.open('xb') as stream:stream.write(payload)
            proof=dict(image=str(image.relative_to(root)),ocr=str(ocr.relative_to(root)),
                       image_sha256=hashlib.sha256(image_bytes).hexdigest(),ocr_sha256=hashlib.sha256(payload).hexdigest())
            return '最新截图/OCR展示副本暂无法更新；当前新帧已独立留证，不使用旧展示图发送输入。',proof
    finally:
        for path in temporaries:
            try:path.unlink(missing_ok=True)
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
    for w in complete_map_row_labels(f.words,frame=f):
        m=re.match(r'^\s*(\d{1,2})\s*[.．、。]\s*(.+)',w['text'])
        if not m or not (100<=w['x']<=650 and 190<=w['y']<=730):continue
        number_proof=None
        if w['score']<.85:
            proof=w.get('stage_number_verification') or {};crop=proof.get('crop',[]);scores=proof.get('scores',[])
            if (proof.get('source') not in ('current_map_numeric_prefix_field_read','current_map_numeric_prefix_dual_read') or proof.get('number')!=int(m.group(1))
                or proof.get('captured_at')!=f.at or len(scores)!=(1 if proof.get('source')=='current_map_numeric_prefix_field_read' else 2) or min(scores)<.98 or len(crop)!=4):continue
            x1,y1,x2,y2=crop
            if not (0<=x1<x2<=1600 and 0<=y1<y2<=900):continue
            if hashlib.sha256(f.image[y1:y2,x1:x2].tobytes()).hexdigest()!=proof.get('crop_sha256'):continue
            number_proof=proof
        y=int(round(w['y']))
        row=dict(stage=int(m.group(1)),name=m.group(2),y=y,x=w['x'],**row_markers(f.image,hsv,y,lock_template))
        if w.get('label_components'):row['name_components']=copy.deepcopy(w['label_components'])
        if w.get('label_verification'):row['name_verification']=copy.deepcopy(w['label_verification'])
        if w.get('stage_label_pending'):row['name_complete']=False
        if number_proof:row.update(number_verification=copy.deepcopy(number_proof),name_score=w['score'])
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

def mainline_episode(f):
    rows=[]
    for word in f.words:
        if word['score']<.90 or not (50<=word['x']<=430 and 0<=word['y']<=90):continue
        match=re.fullmatch(r'Episode\s*(\d+)',word['text'],re.I)
        era=re.fullmatch(r'第\s*(\d+)\s*时代\s*Episode',word['text'],re.I)
        if match or era:rows.append(dict(episode=int((match or era)[1]),word=word,layout='era' if era else 'episode'))
        else:
            # Named Episodes use the same map, story and team contracts. The
            # word '外传' in this exact header is not a different task mode.
            import unicodedata
            named=re.fullmatch(r'外传\s*Episode\s*:\s*(.+)',unicodedata.normalize('NFKC',word['text']),re.I)
            if named and word['score']<.98:return None
            if named:
                from map_identity import named_episode
                try:identity=named_episode(named[1])
                except ValueError:continue
                rows.append(dict(episode=identity,word=word,layout='named_episode'))
    return rows[0] if len(rows)==1 else None


def mainline_map_control(f):
    """Return the one positively identified mainline map action.

    Battle nodes and zero-stamina story nodes share the Episode map layout but
    use different lower-right controls.  This only identifies the page/control;
    map_ticket still requires the chapter and blue selected node before input.
    A generic story label elsewhere never receives input.
    """
    if not mainline_episode(f):return None
    candidates=[]
    battle=f.find('准备战斗',(1200,750,1599,899))
    story=f.find(r'^(观看故事|观看剧情)$',(1200,750,1599,899))
    if battle:candidates.append(dict(kind='battle',target=battle))
    if story and story['score']>=.85:candidates.append(dict(kind='story_only',target=story))
    return candidates[0] if len(candidates)==1 else None

def classify(f):
    # Vetoes are ordered before EVERY action, including every kind of confirmation.
    if capacity_blocker(w['text'] for w in f.words):return 'capacity_stop'
    if resource_warning(f): return 'resource_stop'
    if (f.any('网络连接异常') and f.any('重新连接') or f.any('与服务器的连接已中断')) and f.find('点击重试',(500,550,1100,780)): return 'network_error'
    version_retry=(f.find(r'^无法连接至版本服务器[。.]?$',(500,150,1100,280)),f.find(r'^网络连接失败$',(550,350,1050,530)),f.find(r'^点击重试$',(500,550,1100,780)))
    if all(word and word['score']>=.90 for word in version_retry):return 'network_error'
    if paid_revive_defeat_verified(f): return 'defeat'
    conf=f.find(r'^(确认|确定|確定|確認)$')
    cancel=f.find(r'^(取消|취소)$')
    middle=''.join(w['text'] for w in f.words if 260<w['x']<1360 and 140<w['y']<750)
    failure_banner=norm(''.join(w['text'] for w in f.words if 280<w['x']<1340 and 120<w['y']<640))
    if (any(norm(t) in failure_banner for t in ('FAILED','DEFEAT','战斗失败','挑战失败','闯关失败','任務失敗','任务失败'))
        or (f.any('再次挑战','重新挑战','再挑战') and not f.any('获得的道具','任务成功','闯关成功'))): return 'defeat'
    if chat_panel_visible(f.words):return 'chat_panel'
    if chat_panel_heading(f.words):return 'unknown_dialog'
    if friendship_upgrade_notice_close(f.words):return 'friendship_upgrade_notice'
    if account_upgrade_notice_close(f.words):return 'account_upgrade_notice'
    if rankup_splash(f.words):return 'rankup_splash'
    if date_change_notice_close(f.words):return 'date_change_notice'
    if tutorial_completed_notice_close(f.words):return 'tutorial_completed_notice'
    if f.any('变更日期','日期变更'):return 'unknown_dialog'
    if tutorial_plan(f):return 'new_player_tutorial'
    if f.any(*FRIENDSHIP_TITLES,'轻触后关闭','輕觸後關閉'):return 'unknown_dialog'
    if f.any('给予协助的朋友') and f.any('发送好友申请') and f.find(r'^取消$',(500,570,800,720)) and f.find(r'^申请$',(800,570,1100,720)): return 'friend_decline'
    if conf and ('跳过教学' in middle or '跳过教學' in middle): return 'tutorial_skip_confirm'
    if top_right_skip_control(f.words,tutorial=True) and not conf:return 'tutorial_skip'
    if conf and ('跳过故事' in middle or '跳过剧情' in middle): return 'skip_confirm'
    if conf and cancel: return 'unknown_dialog'
    # A settlement confirmation must have two independent result-only labels.
    if battle_settlement_confirm(f.words):return 'settlement'
    if conf and f.any('Rank Up','Rank.Up','等级提升','等级上升') and not f.any('购买','兑换'): return 'rankup'
    # Unrecognized controls veto underlying maps, rewards and battle HUDs.
    if conf or cancel:return 'unknown_dialog'
    if f.any('故事完成奖励已正常发放','获得星星奖励已正常发放') and f.find('点击关闭',(500,500,1100,720)): return 'story_reward'
    if f.any('支线故事通知') and f.any('已解锁') and f.any('支线故事一览') and f.find('点击关闭',(500,550,1100,780)): return 'unlock_notice'
    if f.any('解锁缘分') and f.any('结下缘分') and f.find(r'^OK$',(600,550,1000,720)): return 'bond_notice'
    # An incomplete closeable modal must never expose its underlying map/team.
    if f.find(r'^OK$'):return 'unknown_dialog'
    if f.find(r'^(点击关闭|點擊關閉)$'):return 'unknown_dialog'
    if chapter_reward_pending(f):return 'chapter_reward_pending'
    if legacy_region_cards(f):return 'legacy_story_regions'
    if legacy_map_info(f):return 'legacy_story_map'
    # Mainline results share CLEAR and the final-wave HUD with legacy story
    # banners. Result-only objectives must win even as CLEAR OCR flickers.
    if victory_objectives_verified(f):return 'victory'
    if legacy_clear_banner(f):return 'legacy_story_clear'
    if legacy_exit_target(f):return 'legacy_story_exit'
    if f.find(r'^离开$',(50,750,230,899)) and f.find(r'^大厅$',(250,750,430,899)) and f.find(r'^重新进行$',(1300,750,1599,899)): return 'post_clear_exit'
    if top_right_skip_control(f.words): return 'story'
    if f.any('CLEAR','VICTORY') and f.any('关卡任务') and f.any('闯关成功'): return 'victory'
    if mainline_map_control(f):return 'map'
    if f.find('选择队伍',(1130,750,1599,899)) and f.any('选择辅助英雄'): return 'support'
    if owned_hero_selector_visible(f):return 'team_hero_selection'
    if f.find('进行任务|战斗开始',(1150,750,1599,899)) and f.any('队伍战斗力','管理队伍'):
        return 'unknown_dialog' if conf or cancel else 'team'
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
    def _capture_pixels(self):
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
        return im,(w,h)
    def capture(self):
        capture_started=time.perf_counter()
        im,(w,h)=self._capture_pixels()
        captured_at=time.time();ocr_started=time.perf_counter()
        results,_=self.ocr(im)
        ocr_finished=time.perf_counter()
        f=Frame(im,results,(w,h));f.at=captured_at
        from tutorial_ocr import strengthen_actor,strengthen_enemy_levels,strengthen_chapter_reward_thresholds,strengthen_orbis_unlock_notice,strengthen_summon_promo_title,strengthen_owned_unit_levels,strengthen_preparation_cost,strengthen_free_single_summon_label,strengthen_wishlist_close,strengthen_wishlist_count,strengthen_spirit_altar_purpose,strengthen_owned_card_level,strengthen_preparation_entry_label,strengthen_map_stage_number,strengthen_map_row_label
        strengthen_map_stage_number(f,self.ocr)
        strengthen_map_row_label(f,self.ocr)
        strengthen_actor(f,self.ocr)
        strengthen_enemy_levels(f,self.ocr)
        strengthen_chapter_reward_thresholds(f,self.ocr)
        strengthen_orbis_unlock_notice(f,self.ocr)
        strengthen_summon_promo_title(f,self.ocr)
        strengthen_owned_unit_levels(f,self.ocr)
        strengthen_owned_card_level(f,self.ocr)
        strengthen_preparation_entry_label(f,self.ocr)
        strengthen_preparation_cost(f,self.ocr)
        from tutorial_ocr import strengthen_preparation_power_label
        strengthen_preparation_power_label(f,self.ocr)
        strengthen_free_single_summon_label(f,self.ocr)
        strengthen_wishlist_close(f,self.ocr)
        strengthen_wishlist_count(f,self.ocr)
        strengthen_spirit_altar_purpose(f,self.ocr)
        enrichment_finished=time.perf_counter()
        self.frame=f
        encoded_ok,encoded=cv2.imencode('.png',im)
        if not encoded_ok:raise OSError('当前截图编码失败；未发送输入。')
        previous=getattr(self,'capture_warning','')
        self.capture_warning,self.capture_snapshot=write_capture_display(ROOT,encoded.tobytes(),dict(time=now(),words=f.words,text=f.text))
        if self.capture_snapshot:event('capture_display_fallback',snapshot=self.capture_snapshot)
        if previous!=self.capture_warning:
            print(json.dumps(dict(kind='log',text=self.capture_warning or '最新截图/OCR展示已恢复更新。'),ensure_ascii=False),flush=True)
        energy=f.find(r'\d+\s*/\s*\d+',(770,0,925,85)) or f.find(r'\d+\s*/\s*\d+',(950,0,1100,85))
        if energy:
            m=re.search(r'(\d+)\s*/\s*(\d+)',energy['text'])
            if m and int(m.group(2))>=100: self.s['stamina']=int(m.group(1))
        f.capture_timings=dict(capture_ms=round((ocr_started-capture_started)*1000,2),
                               full_ocr_ms=round((ocr_finished-ocr_started)*1000,2),
                               enrichment_ms=round((enrichment_finished-ocr_finished)*1000,2),
                               capture_total_ms=round((time.perf_counter()-capture_started)*1000,2))
        return f
    def save(self):
        self.s['updated_at']=now(); self.s['worker_pid']=os.getpid()
        self.s['manual_clears']=sum(1 for item in self.s.get('completed',{}).values() if item.get('manual_completed'))
        self.s['script_victories']=self.s.get('victories',0)-self.s['manual_clears']
        atomic_json(ROOT/'state.json',self.s,compact=True)
        self._saved_observation=self._observation_signature()
        active=self.s.get('active') or self.ticket or {}
        text=(f"# 第七史诗主线运行状态\n\n- 状态：**{self.s.get('status','启动中')}**\n- 更新时间：{self.s['updated_at']}（北京时间）\n- 当前/最近关卡：{active.get('key',self.s.get('last_stage','待识别'))} {active.get('name','')}\n- 本次已确认通关：{self.s.get('victories',0)} 关（脚本 {self.s.get('script_victories',0)}，用户手动补过 {self.s.get('manual_clears',0)}）\n- 最近读取体力：{self.s.get('stamina','未读取')}\n- 说明：{self.s.get('reason','')}\n- 最后动作：{self.s.get('last_action','无')}\n\n安全规则：不兑换/购买体力；不点重复挑战；已尝试关卡不再次入场；无法确认未通关时停止。\n\n最近画面见 latest.png；动作与安全检查见 events.jsonl；通关/尝试记录见 state.json。\n")
        previous=getattr(self,'report_warning','')
        self.report_warning=write_status_report(ROOT/'STATUS.md',text)
        if self.report_warning!=previous:
            message=self.report_warning or '状态报告已恢复更新。'
            print(json.dumps({'kind':'log','text':message},ensure_ascii=False),flush=True)
    def _observation_signature(self):
        return tuple(self.s.get(k) for k in ('status','screen','reason','stamina'))+((self.s.get('active') or {}).get('key'),)
    def save_observation(self):
        if getattr(self,'_saved_observation',None)!=self._observation_signature():self.save()
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
    def _can_replan_ui(self,kind):
        # Exact ordinary control + scene, not an arbitrary Confirm or an entry.
        ordinary={
            '未通关验证通过，准备战斗':'map','避开已通关关卡，选择下一关':'map',
            '完成本章后进入下一章':'map','选择当前队伍':'support',
            '确认通关结算':'settlement','关闭已发放的免费奖励遮罩':'story_reward',
            '跳过剧情':'story','确认跳过剧情':'skip_confirm','通关星级页继续至结算':'victory',
        }
        return bool(kind in ordinary and ordinary[kind]==self.s.get('screen')
                    and (not self.s.get('active') or kind in ('跳过剧情','确认跳过剧情','通关星级页继续至结算','确认通关结算')))
    def action(self,kind,word=None,xy=None):
        from pc_backend import FrameExpired,NavigationFrameExpired,TapNotSent,NavigationInputDeferred
        try:return self._action(kind,word,xy)
        except FrameExpired as exc:
            if self._can_replan_ui(kind):
                raise NavigationFrameExpired('普通界面点击尚未发送，画面已过期；重新取图核对当前页。') from exc
            raise
        except TapNotSent as exc:
            if getattr(self,'pc',None) and self._can_replan_ui(kind):
                event('navigation_input_not_sent',action=kind,screen=self.s['screen'],
                      proof='TapNotSent_before_button_down',reason=str(exc),
                      input_sequence=getattr(self,'input_sequence',None))
                raise NavigationInputDeferred(str(exc)) from exc
            raise
    def _known_skip_control(self,kind,word):
        """Recognize once, then verify volatile control pixels immediately before send."""
        tutorial=kind in ('跳过已识别的免费地图教学','确认仅跳过教学')
        confirmation=kind in ('确认跳过剧情','确认仅跳过教学')
        expected=('tutorial_skip_confirm' if tutorial else 'skip_confirm') if confirmation else ('tutorial_skip' if tutorial else 'story')
        if confirmation:
            targets=[w for w in self.frame.words if w['text'] in ('确认','确定','確定','確認') and w['score']>=.90]
            cancels=[w for w in self.frame.words if w['text']=='取消' and w['score']>=.90]
            target=targets[0] if len(targets)==1 else None
            controls=[target,*cancels] if target and len(cancels)==1 else []
        else:
            target=top_right_skip_control(self.frame.words,tutorial=tutorial)
            controls=[target] if target else []
        if (classify(self.frame)!=expected or not target or not controls or word is None
            or any(target.get(k)!=word.get(k) for k in ('text','x','y','box'))):
            self.s['reason']='当前帧没有对应的唯一跳过控件；继续观察，不用旧坐标。'
            event('skip_control_cancelled',action=kind,reason=self.s['reason'])
            return None
        from ui_control_guard import verify_live_controls
        proof=verify_live_controls(self,controls,'skip-confirm' if confirmation else 'skip')
        if proof is None:
            event('skip_control_cancelled',action=kind,reason='发送前控件像素已变化；零输入重取图')
            return None
        self._live_skip_proof=proof
        event('skip_control_verified',action=kind,target=target,evidence=proof['current_evidence'],
              captured_at=proof['captured_at'],source='control_pixels_last_mile',proof=proof,
              stage=(self.s.get('active') or self.ticket or {}).get('key'),
              capture_timings=getattr(self.frame,'capture_timings',{}))
        return target
    def _action(self,kind,word=None,xy=None):
        self.ensure_game()
        if time.time()-self.frame.at>5:
            from pc_backend import FrameExpired
            raise FrameExpired('观察画面已过期；已取消操作。')
        blocker=capacity_blocker(w['text'] for w in self.frame.words)
        if blocker:raise TaskAttention(blocker.code,blocker.title,blocker.reason)
        if resource_warning(self.frame): raise RuntimeError('输入前触发资源消耗保护，已拒绝操作。')
        guarded=kind in ('跳过剧情','跳过已识别的免费地图教学','确认跳过剧情','确认仅跳过教学')
        skip_started=time.perf_counter() if guarded else None
        if guarded:
            if xy is not None:raise RuntimeError('跳过操作必须提供本帧已识别控件，禁止固定坐标。')
            word=self._known_skip_control(kind,word)
            if word is None:return False
        chapter_proof=None
        if kind=='完成本章后进入下一章':
            d,rows,proof=self.map_ticket(self.frame)
            target=chapter_navigation_control(self.frame,d,rows) if classify(self.frame)=='map' and proof in CLEAR_PROOFS else None
            if xy is not None or not target or word!=target:return False
            from ui_control_guard import verify_live_controls
            chapter_proof=verify_live_controls(self,[target],'native-chapter-navigation')
            if chapter_proof is None:return False
            event('chapter_navigation_intent',target=target,stage=d['key'],proof=chapter_proof)
        x,y=xy if xy else (word['x'],word['y'])
        w,h=self.frame.raw_size; coords=[round(x*w/1600),round(y*h/900)]
        self.input_sequence=getattr(self,'input_sequence',0)+1
        from progression_evidence import story_effect
        effect=story_effect(kind)
        event('action',action=kind,xy=coords,stage=(self.s.get('active') or self.ticket or {}).get('key'),
              **({'effect':effect} if effect else {}),
              **({'skip_timings':dict(source='control_pixels_last_mile',
                   recognized_to_intent_ms=round((time.perf_counter()-skip_started)*1000,2),
                   capture_to_intent_ms=round((time.time()-self.frame.at)*1000,2),
                   capture=getattr(self.frame,'capture_timings',{}))} if guarded else {}))
        self.s['last_action']=kind
        if not guarded and getattr(self,'_prepared_entry_action',None)!=kind:self.save()
        if guarded and (not 0<=time.time()-self.frame.at<=5 or not 0<=time.time()-self._live_skip_proof['captured_at']<=.75):
            from pc_backend import FrameExpired
            event('skip_control_cancelled',action=kind,reason='发送前即时复核已过期')
            raise FrameExpired('当前跳过观察已过期；未发送输入，重新读取当前帧。')
        if chapter_proof and (not 0<=time.time()-self.frame.at<=5 or not 0<=time.time()-chapter_proof['captured_at']<=.75):
            from pc_backend import FrameExpired
            raise FrameExpired('章节控件复核已过期；未发送输入。')
        if getattr(self,'pc',None):self.pc.tap(x,y)
        else:self.adb('shell','input','tap',*coords)
        if guarded:self.save()  # Free skip intent/evidence was saved before input.
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
    def observe_progress_evidence(self,scope,diagnostic,entry=None):
        """Missing evidence is a live observation task, never a retry permit."""
        reason=diagnostic.get('reason') or '正在核对当前推进所需的独立证据。'
        context=entry if entry is not None else self.s.setdefault('evidence_observations',{})
        slot='result_observation' if entry is not None else scope
        previous=context.get(slot)
        if not previous or previous.get('run_id')!=getattr(self,'run_id',None):
            previous=dict(run_id=getattr(self,'run_id',None),first_seen_at=now(),observations=0,diagnostics=[])
            context[slot]=previous
        code=diagnostic.get('code',scope)
        requirement=next((item for item in previous['diagnostics'] if item['code']==code),None)
        new_requirement=requirement is None
        if new_requirement:
            requirement=dict(code=code,reason=reason,at=now(),observations=0,
                evidence=self.evidence('progress-observation-'+scope+'-'+str(time.time_ns())))
            previous['diagnostics'].append(requirement)
        requirement.update(last_seen_at=now(),observations=requirement['observations']+1)
        previous.update(last_observed_at=now(),observations=previous['observations']+1)
        self.observation_wait=dict(code=scope,reason=reason,stage=(entry or {}).get('key',''))
        self.s.update(status='正在核实推进证据',reason=reason+' 持续读取新帧，证据齐全后自动推进；不重放、不补记通关，无需反复点继续。')
        if new_requirement or time.time()-previous.get('checkpoint_at',0)>=10:
            previous['checkpoint_at']=time.time();self.save()
        return True,.25
    def observe_story_result(self,diagnostic):
        return self.observe_progress_evidence('story_result',diagnostic,self.s['active'])
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
        e=mainline_episode(f); chapter_fields,c=chapter_header(f)
        node,rows=selected_node(f)
        if not e or not c or not node: return None,rows,'无法可靠识别章节、编号或蓝色选中节点'
        episode=e['episode']
        d=dict(episode=episode,**chapter_fields,**node)
        d['key']=stage_key(d); d['verified_epoch']=time.time()
        if node['locked']:return d,rows,'锁定关卡'
        if node['completion']=='conflict':return d,rows,'当前通关标记不一致'
        if is_cleared(node):return d,rows,'已通关绿色勾' if node['clear_badge'] else '已通关关卡星级'
        return d,rows,'未通关蓝色当前节点'
    def open_story_node(self,d,target):
        """Persist a no-cost story attempt before its only allowed click."""
        from entry_journal import reserve_entry,finish_dispatch
        from pc_backend import TapNotSent
        key=d['key']
        a=dict(self.ticket or d,cost=0,started_at=now(),start_epoch=time.time(),entry_kind='story_only',
               entry_proof='当前Episode、章节、蓝色选中节点与右下角观看故事控件')
        dispatch=reserve_entry(self.s,key,a);self.s['active']=a
        from story_open_ack import register_open
        register_open(self,dispatch)
        self.s['reason']=f'已发送纯剧情节点 {key} 的入口消息；尚未确认游戏接受，通关仍须独立证据'
        try:
            if getattr(self,'run_id',None):
                from entry_preparation import dispatch_first_entry
                dispatch_first_entry(self,dispatch,'观看故事（仅一次）')
            else:
                self.save()  # Historical CLI; no new continuation capability.
                self.action('观看故事（仅一次）',target)
        except TapNotSent as exc:
            if dispatch['status']=='reserved':finish_dispatch(dispatch,'not_sent',str(exc))
            self.archive_unresolved_active('观看故事按下前取消，确认未发送；原意图与发送结果完整保留')
            self.s.update(status='观看故事点击尚未发送',reason='鼠标接管时取消了点击；移出后点继续，重新核对当前节点。')
            self.save()
            raise TaskAttention('entry_not_sent',self.s['status'],self.s['reason']) from exc
        if dispatch['status']=='reserved':
            finish_dispatch(dispatch,'sent');self.save()
        self.ticket=None
        return True,3
    def title_matches(self,f):
        if not self.ticket: return False
        target=norm(self.ticket['name']); titlewords=[w for w in f.words if 1140<w['x']<1560 and 145<w['y']<195]
        return any(difflib.SequenceMatcher(None,target,norm(w['text'])).ratio()>.68 for w in titlewords)
    def step(self,f):
        self.observation_wait=None
        mode=classify(f); self.s['screen']=mode
        if mode!=self.last_mode:
            self.mode_since=time.time(); self.unknown_gestures=0; self.last_mode=mode
            event('screen',screen=mode,stage=(self.s.get('active') or self.ticket or {}).get('key'))
        age=time.time()-self.mode_since
        acknowledgement=getattr(self,'story_open_ack',None)
        if acknowledgement:acknowledgement.observe_scene(mode,f)
        from free_notices import FreeNoticeController
        if not getattr(self,'free_notices',None):self.free_notices=FreeNoticeController(self)
        self.free_notices.observe_scene(mode,f)
        from chat_recovery import ChatRecoveryController
        if not getattr(self,'chat_recovery',None):self.chat_recovery=ChatRecoveryController(self)
        self.chat_recovery.observe_scene(mode,f)
        self.s.update(status='正在推进主线',reason='已识别画面：'+scene_name(mode),terminal=False)
        if (ROOT/'STOP').exists(): return self.stop('用户停止','检测到 STOP 文件；未关闭游戏')
        if mode=='network_error':
            retries=[x for x in self.s.get('network_retries',[]) if time.time()-x<600]
            if len(retries)>=3: return self.stop('网络异常停止','10分钟内三次网络重连仍未恢复；不重开关卡、不改代理、不消费资源')
            retries.append(time.time());self.s['network_retries']=retries;self.ticket=None
            self.s.update(status='正在恢复网络连接',reason='只点击已明确识别的网络重试，不是关卡重试；入场和通关记录保留')
            self.action('网络重试（非关卡重试）',f.find('点击重试',(500,550,1100,780))); return True,10
        if mode=='capacity_stop':
            if getattr(self,'run_id',None):
                from entry_preflight import observe as observe_entry_response
                observe_entry_response(self,f,mode)
            b=capacity_blocker(w['text'] for w in f.words)
            return self.attention(b.code,b.title,b.reason)
        if mode=='resource_stop':
            return self.attention('resource','体力/入场资源不足','请手动处理后点“处理后继续”；没有确认、兑换或使用资源。')
        if mode=='defeat':
            self.s.setdefault('stage_outcomes',[]).append(dict(outcome='defeat',at=now(),stage=(self.s.get('active') or {}).get('key'),evidence=self.evidence('explicit-defeat')))
            return self.stop('强度不足卡关','当前画面明确显示战败；不复活、不重试，保留现场和原记录')
        if getattr(self,'run_id',None):
            from entry_preflight import observe as observe_entry_response,step as continue_preflight
            observe_entry_response(self,f,mode)
            response=continue_preflight(self,f,mode)
            if response is not None:return response
        if mode=='chat_panel':return self.chat_recovery.step(f)
        if mode=='chapter_reward_pending':
            return self.observe_progress_evidence('chapter_reward',dict(code='current_reward_fields',
                reason='已识别免费章节奖励通知，正在复核本帧星数、三档阈值和领取控件；核实前零输入，不用入场点击触发领奖。'))
        if mode=='unknown_dialog': return self.attention('dialog','弹窗等待处理','请手动处理当前弹窗后点“处理后继续”；未自动确认或购买。')
        from entry_preparation import continue_prepared_entry
        prepared=continue_prepared_entry(self,mode)
        if prepared is not None:return prepared
        # A playback/dispatch history mismatch is diagnostic, not defeat and
        # not a reason to block currently recognized free controls. The map's
        # actual completion/unlock facts will settle the stage identity.
        if mode=='friendship_upgrade_notice':
            self.action('关闭免费英雄亲密度提升提示',friendship_upgrade_notice_close(f.words));return True,1
        if mode=='date_change_notice':
            self.ticket=None
            self.action('关闭日期变更通知，按游戏提示返回大厅',date_change_notice_close(f.words));return True,3
        if not getattr(self,'tutorial_controller',None):self.tutorial_controller=TutorialController(self)
        self.tutorial_controller.observe_scene(mode,f)
        if mode in ('battle','new_player_tutorial') and getattr(self,'run_id',None) and hasattr(self,'cfg') and not self.cfg.get('new_account_tutorial',False):
            plan=tutorial_plan(f) if mode=='new_player_tutorial' else None
            if mode=='battle' or (plan and plan['rule']=='krau_story_basic'):
                from battle_auto_control import step as battle_auto_step
                response=battle_auto_step(self,f,mode)
                if response is not None:return response
                if mode=='new_player_tutorial':
                    return self.observe_progress_evidence('battle_auto',dict(code='battle_auto',reason='普通单次战斗等待可核实的游戏自动控件或结果；不沿用教学基础攻击的敌人坐标兜底。'))
        if mode=='new_player_tutorial':
            result=self.tutorial_controller.step(f)
            if result is not None:return result
            return self.attention('tutorial_changed','教学目标已变化','本帧教学控件未通过复核，未发送输入。')
        if getattr(self,'story',None):
            result=self.story.step(f,mode)
            if result is not None:return result
        if mode=='friend_decline':
            self.action('取消好友申请提示，不发送任何好友申请',f.find(r'^取消$',(500,570,800,720))); return True,3
        if mode=='tutorial_skip':
            self.action('跳过已识别的免费地图教学',top_right_skip_control(f.words,tutorial=True));return True,1
        if mode=='tutorial_skip_confirm':
            self.action('确认仅跳过教学',f.find(r'^(确认|确定|確定|確認)$'));return True,1
        if mode=='skip_confirm':
            self.action('确认跳过剧情',f.find(r'^(确认|确定|確定|確認)$')); return True,2
        if mode=='story':
            active=self.s.get('active')
            if active and active.get('entry_kind')=='story_only' and not active.get('playback_observed_at'):
                active['playback_observed_at']=now();active['playback_evidence']=self.evidence('story-playback-'+active['key']);self.save()
            self.action('跳过剧情',top_right_skip_control(f.words)); return True,2
        if mode=='settlement':
            if not self.s.get('active') and not self.s.get('last_cleared') and self.cfg.get('start_policy')!='current_screen':
                return self.stop('安全暂停待修复','结算画面没有可对应的本次入场记录，停止而非猜测进度')
            active=self.s.get('active')
            if active and not active.get('settlement_observed'):
                active['settlement_observed']=dict(at=now(),evidence=self.evidence('settlement-observed-'+active['key']))
                self.save()
            # Closing a result is navigation, not completion authority.
            # Keep active until the current map proves clear / next unlock.
            self.ticket=None
            self.action('确认通关结算',battle_settlement_confirm(f.words)); return True,4
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
        if mode=='tutorial_completed_notice':
            result=self.free_notices.step(f)
            if result is not None:return result
            return self.attention('free_notice_changed','免费提示控件已变化','当前提示或关闭控件未通过核验，未使用旧坐标。')
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
            control=mainline_map_control(f)
            d,rows,proof=self.map_ticket(f)
            if not d:
                return self.observe_progress_evidence('map_identity',dict(code='map_identity',reason=proof))
            self.s['map_verification']=dict(target=d,proof=proof,rows=rows)
            a=self.s.get('active')
            if a:
                from progression_facts import map_progress_fact
                fact=map_progress_fact(f,a,d,rows)
                if fact.completed:
                    a['map_progress_fact']=fact.proof
                    self.completed(fact.reason)
                elif fact.forward_unlocked:
                    # Forward permission is an actual map fact, not an inferred
                    # win. Preserve the entire old active and all original sends.
                    a['forward_map_fact']=fact.proof
                    self.archive_unresolved_active(fact.reason)
                else:
                    # A sent click, elapsed deadline or missing switch is never
                    # defeat. No automatic paid replay; simply keep observing.
                    if a.get('entry_kind')=='story_only':
                        # Retain the existing proven free reward-navigation
                        # handoff; removing outcome log gates must not remove
                        # the recovery that completes a first actual opening.
                        from free_story_handoff import StoryHandoffController
                        if not getattr(self,'story_handoff',None):self.story_handoff=StoryHandoffController(self)
                        response=self.story_handoff.step(f)
                        if response is not None:return response
                        if getattr(self,'story_open_ack',None):
                            response=self.story_open_ack.step(f)
                            if response is not None:return response
                    return self.observe_progress_evidence('stage_outcome',dict(code='stage_outcome',reason=fact.reason),a)
            if proof=='锁定关卡': return self.observe_progress_evidence('stage_locked',dict(code='stage_locked',reason='当前节点仍锁定，继续观察解锁状态；未判战败，不点锁定关。'))
            if proof=='当前通关标记不一致':return self.attention('stage_rating','当前关通关标记不一致','已读到的星级和通关勾互相矛盾，未将此关判为完成；刷新当前关后继续。')
            if proof in CLEAR_PROOFS:
                nextrow=next((r for r in rows if r['stage']==d['stage']+1),None)
                if nextrow and is_unlocked(nextrow) and not is_cleared(nextrow):
                    self.ticket=None; self.action('避开已通关关卡，选择下一关',xy=(nextrow['x'],nextrow['y'])); return True,3
                if nextrow and not is_unlocked(nextrow):return self.observe_progress_evidence('next_locked',dict(code='next_locked',reason='当前关已完成，下一关仍锁定；继续读取实际解锁状态，不判失败。'))
                chapter_control=chapter_navigation_control(f,d,rows)
                if chapter_control:
                    self.ticket=None; self.action('完成本章后进入下一章',chapter_control); return True,.25
                return self.observe_progress_evidence('next_stage',dict(code='next_stage',reason='当前关已完成，正在识别下一未锁节点或地区入口；不重复已完成关。'))
            if d.get('name_complete') is False:
                return self.observe_progress_evidence('map_title',dict(code='map_title',reason='当前关名被OCR拆段，正在独立重读完整行；未导航或创建入场。'))
            from entry_journal import can_enter
            if not can_enter(self.s,d['key']):
                return self.observe_progress_evidence('stage_history',dict(code='stage_history',reason=f"{d['key']} 当前没有完成或后继解锁证据；原点击只保留为发送记录，未判战败、不重复耗体力入场。"))
            if self.s.get('last_cleared') and self.cfg.get('start_policy')!='current_screen':
                last=self.s['last_cleared']
                if stage_order(d)<=stage_order(last):
                    return self.stop('安全暂停待修复','关卡编号未向前推进，拒绝倒退刷关')
            self.ticket=d; self.ticket['progress_before']=dict(key=d['key'],next_locked=next((row.get('locked') for row in rows if row.get('stage')==d['stage']+1),None)); self.ticket['proof']=proof; self.ticket['evidence']=self.evidence('preflight-'+d['key']); self.ticket['phase']='map'
            self.s['verified']=self.ticket; self.s['last_stage']=d['key']
            event('preflight',target=self.ticket)
            if control and control['kind']=='story_only':return self.open_story_node(d,control['target'])
            target=control['target'] if control else f.find('准备战斗',(1200,750,1599,899))
            self.action('未通关验证通过，准备战斗',target); return True,3
        if mode=='support':
            if not self.ticket or self.ticket.get('phase') not in ('map','support') or time.time()-self.ticket['verified_epoch']>120:
                self.ticket=None; self.back('辅助界面没有本轮新关验证凭据'); return True,3
            if not self.title_matches(f): return self.stop('安全暂停待修复','辅助选择界面的关卡名称与已验证地图节点不一致')
            self.ticket['phase']='support'
            self.action('选择当前队伍',f.find('选择队伍',(1130,750,1599,899))); return True,3
        if mode=='team_hero_selection':
            from tutorial_core import owned_hero_placement_verified
            setup=self.s.get('team_config') or {}
            if setup.get('hero') in ('不成熟的维多丽卡','维多丽卡') and owned_hero_placement_verified(f):
                source=setup.get('dispatches',{}).get('assign_owned_victoria',{})
                context=self.s.get('active') or self.ticket or {}
                if (not setup.get('id') or not setup.get('stage_key') or source.get('status')!='sent'
                    or context.get('key')!=setup['stage_key']):
                    return self.attention('team_setup','配置结果缺少原选择链','已看到已配置英雄，但原选择/当前关来源不完整；不自动返回或发送入场。')
                if not self.tutorial_controller.placement_confirmed(f):return True,.25
                setup.update(phase='completed',evidence=self.evidence('owned-hero-placed'))
                closing=setup.get('selector_close')
                if closing:
                    if closing.get('status')=='sent' and time.time()-closing['at']<10:self.save();return True,.25
                    return self.attention('team_setup','英雄选择面板关闭待核实','已发送面板关闭，未重复返回或开战。')
                setup['selector_close']=dict(status='reserved',at=time.time(),evidence=self.evidence('owned-selector-before-back'));self.save()
                self.back('已核实已拥有英雄配置完成，关闭选择面板读取原关卡')
                setup['selector_close']['status']='sent';self.save();return True,.25
            if setup.get('phase') in ('await_selector','await_position','await_confirmation') and time.time()-setup['at']<12:
                self.s['reason']='英雄选择步骤尚在切换；保持当前选择链，不返回地图或开战';self.save();return True,.25
            return self.attention('team_setup','英雄选择等待当前控件','未核实本帧选择/配置结果，不点穿选择面板发送入场。')
        if mode=='team':
            setup=self.s.get('team_config') or {}
            if setup.get('phase') in ('await_selector','await_position','await_confirmation'):
                from tutorial_core import owned_hero_placement_verified
                if owned_hero_placement_verified(f):
                    if not self.tutorial_controller.placement_confirmed(f):return True,.25
                    setup.update(phase='completed',evidence=self.evidence('owned-hero-placed'));self.save();return True,.25
                if time.time()-setup['at']<12:
                    self.s['reason']='等待当前已拥有英雄配置步骤显示位置/完成证据；不返回取消选择、不发送入场';self.save();return True,.25
                return self.attention('team_setup','当前英雄配置等待核实','未看到选位/已配置的完整证据，保留原选择链，不消耗英雄、不重复入场。')
            if self.s.get('active'):
                return self.observe_progress_evidence('entry_response',dict(code='entry_response',reason='当前仍在队伍页，入口发送不代表游戏接受或失败；继续观察，不重复消耗入场。'),self.s['active'])
            if not self.ticket or self.ticket.get('phase') not in ('map','support') or time.time()-self.ticket['verified_epoch']>120:
                self.ticket=None; self.back('队伍界面没有完整地图验证链'); return True,3
            if not self.title_matches(f): return self.stop('安全暂停待修复','开战前关卡名称不一致，拒绝入场')
            cost=f.find(r'\d+\s*/\s*\d+',(1180,775,1340,880))
            if not cost or cost['score']<.90:
                if age<20:
                    self.s['reason']='入场数字受闪光/动画干扰，等待新截图重新严格读取；尚未入场、不猜测数值'
                    self.save(); return True,3
                return self.observe_progress_evidence('entry_cost',dict(code='entry_cost',reason='入场费用暂未读全，继续读取当前字段；未发送、未判失败。'))
            match=re.search(r'(\d+)\s*/\s*(\d+)',cost['text']); required,available=map(int,match.groups())
            if required>100: return self.stop('安全暂停待修复','入场消耗读数异常')
            if available<required: return self.attention('resource','体力不足',f'当前体力 {available} 小于消耗 {required}；手动处理后继续，没有打开兑换框。')
            self.s['stamina']=available
            control=team_entry_control(f)
            if control['kind']!='single_task':return self.stop('安全暂停待修复','未核实当前队伍准备页的完整布局与唯一普通单次任务入口；尚未入场，不以AUTO或辅助英雄占位作为条件')
            key=self.ticket['key']
            from entry_journal import can_enter,reserve_entry,finish_dispatch
            from pc_backend import TapNotSent
            if not can_enter(self.s,key): return self.observe_progress_evidence('entry_history',dict(code='entry_history',reason=f'{key} 原发送记录保留，当前结果待观察；未判失败，不重复耗体力。'))
            a=dict(self.ticket,cost=required,stamina_before=available,started_at=now(),start_epoch=time.time(),team_entry_mode=control['kind'],team_entry_proof=control['proof'])
            dispatch=reserve_entry(self.s,key,a);self.s['active']=a
            self.s['reason']=f"已验证新关 {key}，本次入场只消耗体力 {required}，绝不兑换"
            entry=control['target']
            try:
                if getattr(self,'run_id',None):
                    from entry_preparation import dispatch_first_entry
                    dispatch_first_entry(self,dispatch,'进行任务（仅一次入场）')
                else:
                    self.save() # Historical CLI does not acquire this lifecycle.
                    self.action('进行任务（仅一次入场）',entry)
            except TapNotSent as exc:
                if dispatch['status']=='reserved':finish_dispatch(dispatch,'not_sent',str(exc))
                self.archive_unresolved_active('开战按下前取消，确认未发送；原入场意图与发送结果完整保留')
                self.s.update(status='开战点击尚未发送',reason='鼠标接管时取消了点击；移出后点继续，重新核对当前关再开战。')
                self.save()
                raise TaskAttention('entry_not_sent',self.s['status'],self.s['reason']) from exc
            if dispatch['status']=='reserved':
                finish_dispatch(dispatch,'sent');self.save()
            self.ticket=None; return True,5
        if mode=='battle':
            self.battle_seen=time.time()
            a=self.s.get('active')
            if a and time.time()-a['start_epoch']>self.cfg['max_battle_seconds']:
                return self.observe_progress_evidence('battle_outcome',dict(code='battle_outcome',reason='战斗等待时间较长，但没有明确战败画面；继续观察实际结果，不重开。'),a)
            self.s['reason']=('新手战斗观察中，等待可核实的基础技能回合或剧情/结算；不点魂燃、神兽或重试' if self.cfg.get('new_account_tutorial') else '自动战斗中，等待剧情或通关结算；不点击技能、召唤或重试'); self.save_observation(); return True,5
        if mode in ('loading','result_transition'):
            if age>180: return self.observe_progress_evidence('scene_loading',dict(code='scene_loading',reason='仍在加载或结果过渡，尚无明确战败；继续观察。'))
            self.save_observation(); return True,4
        if mode=='unknown' and getattr(self,'run_id',None):
            # Unified runs never promote an unrecognized CG/narration to a
            # centre click/hold. Wait for a real current control or map fact.
            return self.observe_progress_evidence('unknown_scene',dict(code='unknown_scene',reason='当前画面尚无已核实控件，继续零输入观察；不套用旧CLI的CG点击或长按。'))
        # Full-screen CG: only during a recorded run, no popup labels, no battle HUD.
        a=self.s.get('active')
        if not self.cfg.get('new_account_tutorial',False) and a and age>=12 and time.time()-self.battle_seen>12 and time.time()-self.last_gesture>25 and self.unknown_gestures<2:
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

