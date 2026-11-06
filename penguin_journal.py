"""Append-only purchase/dispatch history. Never infer success from a click."""
from pathlib import Path
import hashlib,json,time,uuid
from dataclasses import asdict
from assistant_config import atomic_json,read_json
from penguin_core import quantity
from task_blockers import TaskAttention


class PenguinJournal:
    def __init__(self,profile,run_id,requested):
        self.root=Path(profile)/'penguin';self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'state.json';self.run_id=run_id
        self.state=read_json(self.path,dict(schema=1,runs={},actions=[],purchases=[],pending=None))
        s=self.state
        if (s.get('schema')!=1 or not isinstance(s.get('runs'),dict)
                or not isinstance(s.get('actions'),list) or not isinstance(s.get('purchases'),list)
                or 'pending' not in s):
            raise ValueError('企鹅购买记录损坏；不能清空记录替代。')
        requested=quantity(requested)
        ids=[a.get('id') for a in s['actions']]
        if None in ids or len(ids)!=len(set(ids)):
            raise ValueError('企鹅发送记录不唯一；停止。')
        pending=s['pending']
        if pending and (not isinstance(pending,dict) or pending.get('id') not in ids):
            raise ValueError('企鹅未决购买与发送记录不一致；停止。')
        if pending and (pending!=next(a for a in s['actions'] if a['id']==pending['id'])
                or pending.get('kind')!='purchase'):
            raise ValueError('未决购买内容与原发送意图不一致；停止。')
        purchase_ids=[p.get('dispatch_id') for p in s['purchases']]
        if len(purchase_ids)!=len(set(purchase_ids)):
            raise ValueError('企鹅成功证据重复；停止。')
        for name,run in s['runs'].items():
            if (not isinstance(run,dict) or quantity(run.get('requested'))!=run['requested']
                    or type(run.get('purchased')) is not int or not 0<=run['purchased']<=run['requested']
                    or run['purchased']!=sum(p['quantity'] for p in s['purchases'] if p['run_id']==name)):
                raise ValueError('原企鹅订单数量不一致；停止。')
        for purchase in s['purchases']:
            rows=[a for a in s['actions'] if a['id']==purchase.get('dispatch_id')]
            if (len(rows)!=1 or rows[0].get('kind')!='purchase' or rows[0].get('status')!='sent'
                    or rows[0]['quantity']!=purchase['quantity'] or rows[0]['run_id']!=purchase['run_id']
                    or purchase['run_id'] not in s['runs'] or purchase['quantity']<=0
                    or purchase['stock_before']-purchase['stock_after']!=purchase['total']):
                raise ValueError('原企鹅成功记录缺少一致的已发送购买证据；停止。')
        if pending and pending.get('run_id')!=run_id:
            raise TaskAttention('penguin_unresolved','上次购买结果未明',
                '已保留原数量、发送意图和证据；新开始不能绕过未决扣费，请先人工核对原购买。')
        if run_id not in s['runs']:
            s['runs'][run_id]=dict(requested=requested,purchased=0,phase='navigate',baseline=None,created_at=time.time())
        self.run=s['runs'][run_id]
        if self.run['requested']!=requested or self.run['purchased']!=sum(
                p['quantity'] for p in s['purchases'] if p['run_id']==run_id):
            raise ValueError('企鹅任务数量或成功证据不一致；停止。')
        self.save()

    @property
    def remaining(self):return self.run['requested']-self.run['purchased']
    @property
    def pending(self):return self.state['pending']
    def save(self):atomic_json(self.path,self.state)

    def evidence(self,snap,obs,reading):
        folder=self.root/'evidence';folder.mkdir(exist_ok=True)
        name=str(time.time_ns())+'-'+uuid.uuid4().hex[:8]
        image=folder/(name+'.png');snap.image.save(image)
        meta=folder/(name+'.json')
        binding=asdict(snap.binding) if hasattr(snap.binding,'__dataclass_fields__') else snap.binding
        atomic_json(meta,dict(captured_at=snap.captured_at,binding=binding,
            reading=asdict(reading),tokens=[asdict(t) for t in obs.tokens]))
        return dict(image=str(image.relative_to(self.root)),metadata=str(meta.relative_to(self.root)),
            image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),metadata_sha256=hashlib.sha256(meta.read_bytes()).hexdigest())

    def reserve(self,action,reading,evidence,binding):
        if self.pending:raise ValueError('已有未决企鹅购买；禁止再次发送。')
        if action.kind=='open':
            self.run.update(phase='opening',baseline=dict(stock=reading.stock,unit=reading.unit,currency=reading.currency))
        record=dict(id=uuid.uuid4().hex,run_id=self.run_id,kind=action.kind,
            target=asdict(action.target),reading=asdict(reading),evidence=evidence,
            binding=asdict(binding) if hasattr(binding,'__dataclass_fields__') else binding,
            status='intent',at=time.time())
        if action.kind=='purchase':
            history=[a for a in self.state['actions'] if a['run_id']==self.run_id]
            last_purchase=max((i for i,a in enumerate(history) if a['kind']=='purchase'),default=-1)
            chain=history[last_purchase+1:]
            opened=[a for a in chain if a['kind']=='open']
            if (len(opened)!=1 or any(a['status']!='sent' for a in chain)
                    or opened[0]['binding']!=record['binding']
                    or action.target!=reading.target):
                raise ValueError('没有唯一已发送且同目标的企鹅入口链；不购买。')
            baseline=self.run['baseline']
            from penguin_vision import same_currency
            if not baseline or not same_currency(reading.currency,baseline['currency']):
                raise ValueError('购买币种与本次祭坛来源不符；不购买。')
            n=action.desired
            if (not isinstance(n,int) or n<=0 or n>self.remaining or reading.selected!=n
                    or reading.total!=n*baseline['unit'] or reading.total>baseline['stock']):
                raise ValueError('购买意图超出原数量/费用授权；没有发送。')
            record.update(quantity=n,total=reading.total,stock_before=baseline['stock'],unit=baseline['unit'])
            self.state['pending']=record
            self.run['phase']='await_result'
        self.state['actions'].append(record)
        self.save() # Critical write failure propagates BEFORE any input.
        return record['id']

    def sent(self,ident,status):
        if status not in ('sent','not_sent','unknown'):raise ValueError('发送状态无效。')
        row=next(a for a in self.state['actions'] if a['id']==ident)
        if row['status']!='intent':raise ValueError('不能改写已有发送结果。')
        row.update(status=status,dispatched_at=time.time())
        if self.pending and self.pending['id']==ident:
            self.state['pending']=row
        self.save()

    def confirm(self,reading,evidence,binding):
        row=self.pending
        if not row or row['status']!='sent' or reading.scene!='penguin_altar':return False
        current=asdict(binding) if hasattr(binding,'__dataclass_fields__') else binding
        from penguin_vision import same_currency
        if current!=row['binding']:
            raise TaskAttention('penguin_target','购买目标变化','不跨窗口、进程寿命或几何核销扣费。')
        if reading.stock==row['stock_before']:return False
        if (reading.stock!=row['stock_before']-row['total'] or reading.unit!=row['unit']
                or not same_currency(reading.currency,row['reading']['currency'])):
            raise TaskAttention('penguin_result','购买结果不一致','本帧余额变化不等于原购买总价；不补买、不推断成功。')
        self.state['purchases'].append(dict(dispatch_id=row['id'],run_id=self.run_id,
            quantity=row['quantity'],total=row['total'],stock_before=row['stock_before'],
            stock_after=reading.stock,dispatch_evidence=row['evidence'],result_evidence=evidence,at=time.time()))
        self.run['purchased']+=row['quantity']
        self.run.update(phase='navigate',baseline=None)
        self.state['pending']=None
        self.save()
        return True
