"""Conservative live reconciliation of an exact manually-cleared failed stage.
Navigation is cost-free only. Never plans support/team/mission-entry actions.
"""
from __future__ import annotations
import copy,json,re,time,uuid
from pathlib import Path
from state_tools import manual_clear

class ReconcileBlocked(RuntimeError):pass

def pending_reconciliation(state):
    active=state.get('active') or {}
    if not isinstance(active,dict):return False
    key=active.get('key')
    if not key or key not in state.get('attempted',{}) or key in state.get('completed',{}):return False
    try:expected=f"E{int(active['episode'])}-C{int(active['chapter'])}-S{int(active['stage'])}"
    except (KeyError,TypeError,ValueError):return False
    attempt=state['attempted'][key]
    if not isinstance(attempt,dict):return False
    return (key==expected and all(int(active[k])>0 for k in ('episode','chapter','stage'))
            and all(attempt.get(k)==active.get(k) for k in ('episode','chapter','stage')))

def match_account(state,proof,allow_initial=False,expected_server=None):
    if not proof or not proof.get('server') or not re.fullmatch(r'\d{4,20}',str(proof.get('account_id',''))):raise ReconcileBlocked('账号字段不完整，不能补记历史。')
    if not 0<=time.time()-proof.get('checked_at',0)<=120:raise ReconcileBlocked('账号核对已过期，请重新核对。')
    if not isinstance(proof.get('window'),dict) or not proof['window']:raise ReconcileBlocked('账号证据没有绑定当前客户端。')
    binding=state.get('pc_profile_binding')
    if binding:
        if any(str(proof[k])!=str(binding.get(k,'')) for k in ('server','account_id')):raise ReconcileBlocked('当前账号与原历史绑定不一致，不补记、不换绑。')
    elif not allow_initial or not expected_server or proof['server']!=expected_server:
        raise ReconcileBlocked('旧历史尚未绑定账号；首次绑定需要明确确认历史属于当前账号，不能自动套用。')
    return {k:str(proof[k]) for k in ('server','account_id')}

def exact_map_proof(frame,active):
    from runner import Runner,classify,resource_warning
    if resource_warning(frame) or classify(frame)!='map':raise ReconcileBlocked('请在主线地图核对原关卡；弹窗、队伍和战斗页不能补记。')
    r=Runner.__new__(Runner);node,rows,proof=r.map_ticket(frame)
    episode=frame.find(r'Episode\s*\d+',(50,0,430,90));chapter=frame.find(r'第\s*\d+\s*章',(80,95,340,160))
    if not episode or not chapter or min(episode['score'],chapter['score'])<.85:raise ReconcileBlocked('不能可靠确认原章节，不猜测历史。')
    ep=int(re.search(r'\d+',episode['text']).group());ch=int(re.search(r'\d+',chapter['text']).group())
    if ep!=active['episode'] or ch!=active['chapter']:
        raise ReconcileBlocked('当前不是原失败章节；请在主线地图选中原关卡后再开始自动核对。')
    if node and node.get('key')==active['key'] and proof=='已通关绿色勾':return node,proof,None
    from runner import norm
    matches=[row for row in rows if row['stage']==active['stage'] and norm(row['name'])==norm(active.get('name',''))]
    if len(matches)!=1:raise ReconcileBlocked('原失败关卡未唯一出现在可见列表；请选中原关卡，软件会核对通关勾。')
    if node and node.get('key')==active['key']:raise ReconcileBlocked('原关卡尚未识别到绿色通关勾；不清除失败记录，不重试。')
    row=matches[0]
    return None,None,(row['x'],row['y'])


def chapter_back_target(frame,active):
    """Positive left-chevron geometry, only on an identified next-chapter map."""
    from runner import classify
    if classify(frame)!='map':return None
    e=frame.find(r'Episode\s*\d+',(50,0,430,90));c=frame.find(r'第\s*\d+\s*章',(80,95,340,160))
    if not e or not c or min(e['score'],c['score'])<.85:return None
    ep=int(re.search(r'\d+',e['text']).group());ch=int(re.search(r'\d+',c['text']).group())
    if ep!=active['episode'] or not active['chapter']<ch<=active['chapter']+3:return None
    import cv2,numpy as np
    region=frame.image[110:165,30:90]
    hsv=cv2.cvtColor(region,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([0,0,125]),np.array([179,85,255]))
    n,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
    hits=[]
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if not (5<=w<=22 and 12<=h<=32 and 20<=area<=220):continue
        pixels=np.column_stack(np.where(labels[y:y+h,x:x+w]==i))
        upper=pixels[pixels[:,0]<h*.25,1];middle=pixels[(pixels[:,0]>=h*.35)&(pixels[:,0]<=h*.65),1];lower=pixels[pixels[:,0]>h*.75,1]
        if min(len(upper),len(middle),len(lower))==0:continue
        if upper.mean()-middle.mean()<2 or lower.mean()-middle.mean()<2:continue
        hits.append((30+x+w/2,110+y+h/2))
    if len(hits)!=1:raise ReconcileBlocked('未识别上一章左箭头，不猜测点击坐标。')
    return ('previous_chapter:'+str(ch),hits[0])

def reconcile_live(root,state,account,capture,tap,final_guard,*,allow_initial=False,expected_server=None,private_dir=None,log=lambda text:None,selected_profile=False):
    """Caller owns profile locks. Two green proofs + target guard + CAS; legacy mode also verifies account."""
    from runner import classify,resource_warning,now,atomic_json,write_status_report
    root=Path(root)
    if not pending_reconciliation(state):raise ReconcileBlocked('没有可安全核对的唯一原失败关卡，未修改历史。')
    if (root/'STOP').exists():raise ReconcileBlocked('用户STOP仍存在，未自动移除停止标记。')
    binding=None if selected_profile else match_account(state,account,allow_initial,expected_server)
    active=state['active'];seen=set();node=proof=frame=None
    for _ in range(14):
        frame=capture()
        if not 0<=time.time()-frame.at<=8:raise ReconcileBlocked('核对画面已过期。')
        if resource_warning(frame):raise ReconcileBlocked('资源弹窗优先，停止核对，不确认。')
        mode=classify(frame)
        if mode=='lobby':
            token=frame.find(r'^Episode$',(1300,120,1599,330))
            if not token or token['score']<.85:raise ReconcileBlocked('未确认主线入口，不盲点。')
            kind='open_episode';xy=(token['x'],token['y'])
        elif mode=='map':
            previous=chapter_back_target(frame,active)
            if previous:kind,xy=previous
            else:
                node,proof,xy=exact_map_proof(frame,active)
                if node:break
                kind='select_original_stage'
        elif mode in ('loading','unknown') and seen:
            time.sleep(.25);continue
        else:raise ReconcileBlocked('当前不是主线地图或大厅，未进入战斗或处理未知弹窗。')
        if kind in seen:
            time.sleep(.25);continue  # Observe transitions; never click the same navigation twice.
        seen.add(kind);log('自动核对：'+kind);tap(*xy);time.sleep(.6)
    else:raise ReconcileBlocked('未在有限导航内核实原关卡通关。')
    confirm=capture();second,second_proof,xy=exact_map_proof(confirm,active)
    if not second or second_proof!=proof or second['key']!=node['key'] or confirm.at<=frame.at:
        raise ReconcileBlocked('连续两帧原关卡通关证据不一致，未补记。')
    if not selected_profile:match_account(state,account,allow_initial,expected_server)
    final_guard()
    original=json.loads((root/'state.json').read_text(encoding='utf-8-sig'))
    if original!=state:raise ReconcileBlocked('核对期间历史已变化，拒绝覆盖。')
    if (root/'STOP').exists():raise ReconcileBlocked('核对期间收到STOP，未改历史。')
    stamp=now();nonce=uuid.uuid4().hex
    evidence=root/'evidence'/('manual-clear-'+active['key']+'-'+nonce+'.png');evidence.parent.mkdir(exist_ok=True)
    import cv2
    evidence.write_bytes(cv2.imencode('.png',confirm.image)[1].tobytes())
    before=Path(private_dir or evidence.parent)/('history-before-'+nonce+'.json');before.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(before,original)
    new=manual_clear(state,second,second_proof,str(evidence.relative_to(root)),stamp)
    if binding is not None:new.setdefault('pc_profile_binding',{**binding,'bound_at':stamp,'source':'explicit_user_manual_clear_repair'})
    new.setdefault('reconciliation_history',[]).append({'key':active['key'],'at':stamp,'previous_status':state.get('status'),'previous_reason':state.get('reason'),'previous_terminal':state.get('terminal'),'proof':str(evidence.relative_to(root)),'source':'two_live_exact_green_nodes','verification':'selected_local_profile' if selected_profile else 'account_binding'})
    new.update(terminal=False,status='手动通关已自动核实，可以继续主线',reason='保留原失败尝试和证据；原关两帧绿色通关勾一致，未重新入场。',updated_at=stamp,worker_pid=None)
    if json.loads((root/'state.json').read_text(encoding='utf-8-sig'))!=original:raise ReconcileBlocked('写入前历史发生变化，取消补记。')
    atomic_json(root/'state.json',new)
    with (root/'events.jsonl').open('a',encoding='utf-8') as file:file.write(json.dumps({'time':stamp,'kind':'manual_clear_auto_reconciled','stage':active['key'],'evidence':str(evidence.relative_to(root))},ensure_ascii=False)+'\n')
    warning=write_status_report(root/'STATUS.md','# 主线状态\n\n已自动核实原失败关卡手动通关，保留历史，可以从下一未通关关卡继续。\n\n原始失败尝试、失败证据与手动通关截图均保留；本次核对未进入关卡。\n')
    if warning:log(warning)
    log('原关手动通关已核实并补记；未重复消耗体力。')
    return new
