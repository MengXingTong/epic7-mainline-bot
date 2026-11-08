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
    def __init__(self,profile,run_id,requested,*,persist=True):
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
        if s['active'] and s['active'].get('run_id')!=run_id:
            raise ValueError('原竞技场仍有未结算入场；不归档绕过、不新开。')
        if any(name!=run_id and run.get('pending_result') for name,run in s['runs'].items()):
            raise ValueError('原竞技场结果尚未核实返回NPC列表；不新开或跳过关闭事实。')
        self.run=s['runs'].setdefault(run_id,dict(requested=requested,wins=0,created_at=time.time(),authorization='用户指定NPC对战次数；仅独立成功后可开始下一把，不重试战败/未知入场'))
        if self.run['requested']!=requested:
            raise ValueError('不能修改原run的竞技场目标次数。')
        if persist:self.save()

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

    def navigation(self):
        """Current free navigation only; a send is not selected/accepted."""
        rows=[a for a in self.state['actions'] if a['run_id']==self.run_id]
        boundary=max((i for i,a in enumerate(rows) if a['kind'] in ('entry','result_close','return_to_npc','navigate')),default=-1)
        tail=rows[boundary+1:]
        selects=[a for a in tail if a['kind']=='select']
        selected=selects[-1] if selects else None
        challenges=[a for a in tail if a['kind']=='challenge']
        return selected,challenges[-1] if challenges else None

    def entry_chain_matches(self,reading,target_binding):
        selected,challenged=self.navigation();bound=binding(target_binding)
        if not selected or not challenged:return False
        rows=self.state['actions']
        return bool(rows.index(selected)<rows.index(challenged)
            and all(a['status']=='sent' and a['binding']==bound
                    and a['reading']['opponent']==reading.opponent for a in (selected,challenged))
            and challenged.get('selection_id',selected['id'])==selected['id'])

    def free_navigation_reset_context(self,reading,target_binding):
        """Explicit same-run maintenance can reselect, not resend an unknown click."""
        source=getattr(self,'maintenance_source',None);selected,challenged=self.navigation()
        if (not source or reading.scene not in ('arena_npc','arena_team') or self.active
            or any(r.get('pending_result') for r in self.state['runs'].values())
            or any(k not in self.state['completed'] for k in self.state['attempted'])):return None
        last=self.state['actions'][-1] if self.state['actions'] else None
        if not last or last['run_id']!=self.run_id or last['status']!='unknown':return None
        if last['kind']=='challenge':
            if not selected or selected['status']!='sent':return None
            origins=(selected,last)
        elif last['kind']=='select' and last.get('reason')=='maintenance_free_navigation_reset':
            prior=[a for a in self.state['actions'] if a['id']==last.get('unknown_free_action_id')]
            if len(prior)!=1 or prior[0]['kind']!='challenge' or prior[0]['status']!='unknown':return None
            origins=(prior[0],last)
        else:return None
        if any(a['binding']!=binding(target_binding) or a['reading']['opponent']!=reading.opponent for a in origins):return None
        return dict(unknown_free_action_id=last['id'],maintenance_source=source)

    def team_warning_ready(self,reading,target_binding,captured_at):
        a=self.active
        if (not a or reading.scene!='arena_team_warning' or a.get('battle_evidence') or a.get('result_evidence')
            or a['binding']!=binding(target_binding) or a.get('cost')!=1 or a.get('stock_before',0)<1
            or captured_at<=a['entry_evidence']['captured_at']):return False
        rows=self.state['entry_dispatches'].get(a['key'],[])
        if len(rows)!=1 or rows[0]['status']!='sent':return False
        entry=next(x for x in self.state['actions'] if x['id']==a['action_id'])
        # No replay, second confirmation, other input, auto, or later battle may
        # be hidden by the warning. A sent entry alone is not game acceptance.
        tail=self.state['actions'][self.state['actions'].index(entry)+1:]
        return not tail

    def return_to_npc_context(self,reading,target_binding,captured_at):
        """Free navigation from a known team; never recover a resource entry."""
        bound=binding(target_binding)
        if (self.active or any(r.get('pending_result') for r in self.state['runs'].values())
            or self.remaining<=0 or reading.scene!='arena_team' or reading.cost!=1
            or reading.stock is None or reading.stock<1 or self.entry_chain_matches(reading,target_binding)
            or any(k not in self.state['completed'] for k in self.state['attempted'])):
            return None
        own=[a for a in self.state['actions'] if a['run_id']==self.run_id]
        if not own and self.run['wins']==0:
            return dict(reason='current_screen_start',send_index=1)
        last=own[-1] if own else None
        if last and last['kind']=='return_to_npc':
            previous=last['reading']
            if (last['status'] not in ('sent','not_sent') or last['binding']!=bound
                or (previous['opponent'],previous['stock'],previous['cost'])!=(reading.opponent,reading.stock,reading.cost)
                or last.get('send_index',1)>=3 or captured_at<=last['evidence']['captured_at']
                or time.time()-last.get('finished_at',time.time())<2):return None
            return dict(reason=last['reason'],send_index=last.get('send_index',1)+1,
                response_to=last['id'],return_group=last.get('return_group',last['id']))
        reset=self.free_navigation_reset_context(reading,target_binding)
        if reset:return dict(reason='maintenance_free_navigation_reset',send_index=1,**reset)
        selected,challenged=self.navigation()
        if (selected and challenged
            and all(a['status']=='sent' and a['binding']==bound for a in (selected,challenged))):
            return dict(reason='selection_mismatch',send_index=1,selection_id=selected['id'],challenge_id=challenged['id'])
        return None

    def intent(self,kind,reading,evidence,target_binding):
        if not reading.target:raise ValueError('没有本帧目标。')
        record=dict(id=uuid.uuid4().hex,run_id=self.run_id,controller_run_id=getattr(self,'controller_run_id',self.run_id),kind=kind,status='reserved',reading=asdict(reading),binding=binding(target_binding),evidence=evidence,at=time.time())
        if kind=='entry':
            if self.active or self.run.get('pending_result') or self.remaining<=0 or reading.scene!='arena_team' or reading.cost!=1 or reading.stock<1:
                raise ValueError('竞技场入场链/费用/次数不允许。')
            if not self.entry_chain_matches(reading,target_binding):
                raise ValueError('没有本run首位NPC选择→挑战→同名队伍页的完整发送链。')
            key=self.run_id+':'+str(self.run['wins']+1)
            details=dict(key=key,run_id=self.run_id,controller_run_id=getattr(self,'controller_run_id',self.run_id),opponent=reading.opponent,stock_before=reading.stock,cost=1,binding=record['binding'],entry_evidence=evidence,action_id=record['id'],at=time.time())
            dispatch=reserve_entry(self.state,key,details)
            self.state['active']=dict(details,dispatch_id=dispatch['id'],battle_evidence=None,result_evidence=None)
            record['key']=key
        if kind=='select':
            reset=self.free_navigation_reset_context(reading,target_binding)
            if reset:record.update(reason='maintenance_free_navigation_reset',**reset)
        if kind=='entry_confirm':
            if not self.team_warning_ready(reading,target_binding,evidence['captured_at']):
                raise ValueError('未配置英雄确认不属于原唯一sent/尚未实际开战的入场；不重复确认。')
            a=self.active
            record.update(key=a['key'],original_entry_action_id=a['action_id'],original_opponent=a['opponent'],
                original_entry_sha256=attempt_digest(self.state['attempted'][a['key']]))
        if kind=='challenge':
            selected,previous=self.navigation()
            if (self.active or self.run.get('pending_result') or not selected
                or selected['status']!='sent' or selected['binding']!=record['binding']
                or selected['reading']['opponent']!=reading.opponent
                or (previous and self.state['actions'].index(previous)>self.state['actions'].index(selected))):
                raise ValueError('挑战必须属于当前同名选人；原挑战已发送时只观察接受，不按OCR变化重发。')
            record['selection_id']=selected['id']
        if kind=='return_to_npc':
            context=self.return_to_npc_context(reading,target_binding,evidence['captured_at'])
            if not context:
                raise ValueError('当前队伍页不满足免费返回/新帧响应条件；不撤销或重试入场。')
            record.update(input='native_back',**context)
            record.setdefault('return_group',record['id'])
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
            rows=[a for a in self.state['actions'] if a['kind']=='result_close' and a.get('result_key')==key]
            if not self.result_close_ready(evidence['captured_at']):
                raise ValueError('原结果关闭正在等待接受；不重复旧意图或开战。')
            record.update(result_key=key,send_index=len(rows)+1)
            if rows:record['response_to']=rows[-1]['id']
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

    def result_close_ready(self,captured_at):
        key=self.run.get('pending_result')
        rows=[a for a in self.state['actions'] if a['kind']=='result_close' and a.get('result_key')==key]
        if not rows:return True
        # An uncertain invocation is never automatically reused. A sent free
        # close can have one bounded fresh response, but never reopens a battle.
        last=rows[-1]
        return bool(len(rows)<3 and last['status'] in ('sent','not_sent')
                    and captured_at>last['evidence']['captured_at']
                    and time.time()-last.get('finished_at',time.time())>=2)

    def acknowledge_close(self,evidence,target_binding):
        key=self.run.get('pending_result')
        result=self.state['completed'].get(key,{})
        rows=[a for a in self.state['actions'] if a['kind']=='result_close' and a.get('result_key')==key]
        sent=[a for a in rows if a['status']=='sent']
        if (not key or not sent or result['binding']!=binding(target_binding)
            or any(a['binding']!=result['binding'] for a in rows)
            or evidence['captured_at']<=max(a['evidence']['captured_at'] for a in rows)):
            raise ValueError('没有已发送的结算关闭与后继NPC页面证据。')
        result['close_evidence']=evidence
        self.run['pending_result']=None;self.save()

    def acknowledge_reconciled_return(self,evidence,reading,target_binding,ident):
        """Observe an already-dismissed proven result; never forge a close send."""
        reports=[p for p in self.state.get('reconciliations',[]) if p.get('id')==ident]
        key=self.run.get('pending_result');result=self.state['completed'].get(key,{})
        if (len(reports)!=1 or reports[0].get('phase')!='verified' or reports[0].get('key')!=key
            or reports[0].get('result_evidence')!=result.get('result_evidence')
            or reports[0].get('return_evidence')!=evidence or reading.scene!='arena_npc'
            or not reading.target or reading.target.score is None or reading.target.score<.98
            or result.get('binding')!=binding(target_binding)):
            raise ValueError('没有原独立胜利及本次完整NPC列表证据；不解除原入场。')
        result.update(close_evidence=evidence,close_observation_source='historical_result_and_current_npc_list',reconciliation_id=ident)
        self.run['pending_result']=None
        reports[0].update(phase='reconciled',finished_at=time.time(),close_message_claimed=False)
        self.save()
