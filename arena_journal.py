"""Durable per-round arena ledger. A message is not a battle or a win."""
from pathlib import Path
from dataclasses import asdict,is_dataclass
import hashlib,time,uuid
from assistant_config import atomic_json,read_json
from arena_core import count
from entry_journal import reserve_entry,finish_dispatch,attempt_digest


def binding(value):
    return asdict(value) if is_dataclass(value) else value


class ArenaJournal:
    def __init__(self,profile,run_id,requested):
        self.root=Path(profile)/'arena';self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'state.json';self.run_id=run_id
        self.state=read_json(self.path,dict(schema=1,runs={},attempted={},completed={},entry_dispatches={},active=None,actions=[],last_cleared=None))
        s=self.state
        if s.get('schema')!=1 or any(not isinstance(s.get(k),dict) for k in ('runs','attempted','completed','entry_dispatches')) or not isinstance(s.get('actions'),list) or 'active' not in s:
            raise ValueError('竞技场原记录损坏，不能清空或替换。')
        ids=[a.get('id') for a in s['actions']]
        if None in ids or len(ids)!=len(set(ids)) or any(a.get('status') not in ('reserved','sent','not_sent','unknown') for a in s['actions']):
            raise ValueError('竞技场输入记录不唯一或发送状态损坏。')
        for key,attempt in s['attempted'].items():
            dispatches=s['entry_dispatches'].get(key,[])
            if len(dispatches)!=1 or dispatches[0].get('original_sha256')!=attempt_digest(attempt):
                raise ValueError('竞技场原入场意图/哈希不一致，不重新生成。')
            actions=[a for a in s['actions'] if a['kind']=='entry' and a.get('key')==key]
            if len(actions)!=1 or actions[0]['id']!=attempt.get('action_id') or actions[0]['status']!=dispatches[0]['status']:
                raise ValueError('竞技场原入场和实际发送链不一致。')
        active=s['active']
        if active and (active.get('key') not in s['attempted'] or active['key'] in s['completed'] or active.get('dispatch_id')!=s['entry_dispatches'][active['key']][0]['id']):
            raise ValueError('竞技场active与原入场或独立结算不一致。')
        requested=count(requested)
        for key,result in s['completed'].items():
            if key not in s['attempted'] or result.get('key')!=key or not result.get('result_evidence') or not result.get('battle_evidence'):
                raise ValueError('竞技场完成来源不完整。')
        for name,run in s['runs'].items():
            if run.get('wins')!=sum(r.get('run_id')==name for r in s['completed'].values()) or not 0<=run['wins']<=count(run['requested']):
                raise ValueError('竞技场计数与独立结算不一致。')
        self.run=s['runs'].setdefault(run_id,dict(requested=requested,wins=0,created_at=time.time(),authorization='用户指定NPC对战次数；仅独立成功后可开始下一把，不重试战败/未知入场'))
        if self.run['requested']!=requested:
            raise ValueError('不能修改原run的竞技场目标次数。')
        if s['active'] and s['active'].get('run_id')!=run_id:
            raise ValueError('原竞技场仍有未结算入场；不归档绕过、不新开。')
        self.save()

    def save(self):atomic_json(self.path,self.state)
    @property
    def active(self):return self.state['active']
    @property
    def remaining(self):return self.run['requested']-self.run['wins']

    def evidence(self,snap,obs,reading):
        folder=self.root/'evidence';folder.mkdir(exist_ok=True)
        name=str(time.time_ns())+'-'+uuid.uuid4().hex[:8]
        image=folder/(name+'.png');snap.image.save(image)
        meta=folder/(name+'.json')
        atomic_json(meta,dict(captured_at=snap.captured_at,binding=binding(snap.binding),reading=asdict(reading),tokens=[asdict(t) for t in obs.tokens],visuals=sorted(obs.visuals)))
        return dict(image=str(image.relative_to(self.root)),metadata=str(meta.relative_to(self.root)),image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),metadata_sha256=hashlib.sha256(meta.read_bytes()).hexdigest(),captured_at=snap.captured_at)

    def intent(self,kind,reading,evidence,target_binding):
        if not reading.target:raise ValueError('没有本帧目标。')
        record=dict(id=uuid.uuid4().hex,run_id=self.run_id,kind=kind,status='reserved',reading=asdict(reading),binding=binding(target_binding),evidence=evidence,at=time.time())
        if kind=='entry':
            if self.active or self.run.get('pending_result') or self.remaining<=0 or reading.scene!='arena_team' or reading.cost!=1 or reading.stock<1:
                raise ValueError('竞技场入场链/费用/次数不允许。')
            chain=[a for a in self.state['actions'] if a['run_id']==self.run_id]
            last=max((i for i,a in enumerate(chain) if a['kind']=='entry'),default=-1)
            selects=[a for a in chain[last+1:] if a['kind']=='select']
            challenges=[a for a in chain[last+1:] if a['kind']=='challenge']
            if not selects or not challenges or selects[-1]['status']!='sent' or challenges[-1]['status']!='sent' or selects[-1]['reading']['opponent']!=reading.opponent or selects[-1]['binding']!=record['binding'] or challenges[-1]['binding']!=record['binding']:
                raise ValueError('没有本run首位NPC选择→挑战→同名队伍页的完整发送链。')
            key=self.run_id+':'+str(self.run['wins']+1)
            details=dict(key=key,run_id=self.run_id,opponent=reading.opponent,stock_before=reading.stock,cost=1,binding=record['binding'],entry_evidence=evidence,action_id=record['id'],at=time.time())
            dispatch=reserve_entry(self.state,key,details)
            self.state['active']=dict(details,dispatch_id=dispatch['id'],battle_evidence=None,result_evidence=None)
            record['key']=key
        if kind=='auto':
            a=self.active
            if not a or reading.scene!='arena_battle' or reading.opponent!=a['opponent'] or not a['battle_evidence'] or record['binding']!=a['binding']:
                raise ValueError('自动按钮不属于原入场战斗。')
            if any(r['kind']=='auto' and r.get('key')==a['key'] for r in self.state['actions']):
                raise ValueError('原自动按钮意图已保留；不重复切换。')
            record['key']=a['key']
        if kind=='result_close':
            key=self.run.get('pending_result')
            result=self.state['completed'].get(key,{})
            if not key or reading.scene!='arena_result' or reading.opponent!=result.get('opponent') or record['binding']!=result.get('binding'):
                raise ValueError('没有本次原结算关闭链。')
            if any(a['kind']=='result_close' and a.get('result_key')==key for a in self.state['actions']):
                raise ValueError('本次结算已存在关闭意图，不重复发送。')
            record['result_key']=key
        self.state['actions'].append(record);self.save()
        return record['id']

    def sent(self,ident,status):
        row=next(a for a in self.state['actions'] if a['id']==ident)
        if row['status']!='reserved' or status not in ('sent','not_sent','unknown'):raise ValueError('不能改写发送结果。')
        row.update(status=status,finished_at=time.time())
        if row['kind']=='entry':
            dispatch=self.state['entry_dispatches'][row['key']][-1]
            if status in ('sent','not_sent'):finish_dispatch(dispatch,status)
            else:dispatch.update(status='unknown',finished_at=time.time())
        self.save()

    def battle(self,evidence,target_binding):
        a=self.active
        if not a or a['binding']!=binding(target_binding):raise ValueError('战斗不属于本窗口原入场。')
        if self.state['entry_dispatches'][a['key']][-1]['status']!='sent':raise ValueError('入场未确认发送，不认领战斗。')
        if not a['battle_evidence']:
            a['battle_evidence']=evidence;self.save()

    def complete(self,evidence,target_binding):
        a=self.active
        if not a or not a['battle_evidence'] or a['binding']!=binding(target_binding) or self.remaining<=0:
            raise ValueError('没有完整入场→战斗→独立结算来源，不能计数。')
        if evidence['captured_at']<=a['battle_evidence']['captured_at']:raise ValueError('结算不是独立后继新帧。')
        a['result_evidence']=evidence
        result=dict(a,finished_at=time.time());self.state['completed'][a['key']]=result
        self.state['last_cleared']=a['key'];self.state['active']=None
        self.run['wins']+=1;self.run['pending_result']=a['key'];self.save()
        return result

    def acknowledge_close(self,evidence,target_binding):
        key=self.run.get('pending_result')
        result=self.state['completed'].get(key,{})
        rows=[a for a in self.state['actions'] if a['kind']=='result_close' and a.get('result_key')==key]
        if not key or len(rows)!=1 or rows[0]['status']!='sent' or result['binding']!=binding(target_binding) or evidence['captured_at']<=rows[0]['evidence']['captured_at']:
            raise ValueError('没有已发送的结算关闭与后继NPC页面证据。')
        result['close_evidence']=evidence
        self.run['pending_result']=None;self.save()
