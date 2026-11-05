"""Private, fail-closed evidence and action journal for Dimensional Exploration."""
from __future__ import annotations
import hashlib,json,os,time,uuid,re
from abyss_core import normalize
from pathlib import Path
from assistant_config import read_json
from dimension_core import reading_key,fingerprint,plan
from task_blockers import TaskAttention


def durable_json(path,value):
    path=Path(path);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def counter_values(meta,source):
    values=set()
    for t in meta['tokens']:
        if t.get('score',0)<.85:continue
        m=re.fullmatch(r'(\d{1,2})/(\d{1,2})[:.]*',normalize(t['text']))
        if not m:continue
        direct=t['source']==source
        x=(t['x']+t['w']/2)/meta['width'];y=(t['y']+t['h']/2)/meta['height']
        header=t['source']=='ocr' and y<.09 and ((source=='dimension_life' and .80<x<.86) or (source=='dimension_budget' and .89<x<.97))
        if direct or header:values.add('/'.join(m.groups()))
    return values


class DimensionJournal:
    """Separate mode history under the original profile, never reset on Start.

    Registration precedes initial state creation: a missing/corrupt ledger after
    registration is an error, not an invitation to initialize empty attempts.
    """
    def __init__(self,profile):
        self.root=Path(profile)/'dimension';self.root.mkdir(exist_ok=True)
        self.path=self.root/'state.json';registration=self.root/'registration.json'
        if not registration.exists():
            if any(self.root.iterdir()):raise RuntimeError('次元探查已有未登记记录；不创建空历史替代。')
            durable_json(registration,{'schema':1,'id':uuid.uuid4().hex,'created_at':time.time()})
            durable_json(self.path,{'schema':1,'registration_id':read_json(registration)['id'],
                'attempted':{},'completed':{},'active':None,'last_cleared':None,
                'events':[],'pending':None})
        reg=read_json(registration);self.state=read_json(self.path)
        if (not isinstance(reg,dict) or reg.get('schema')!=1 or not isinstance(self.state,dict)
                or self.state.get('schema')!=1 or self.state.get('registration_id')!=reg.get('id')
                or not isinstance(self.state.get('attempted'),dict) or not isinstance(self.state.get('completed'),dict)
                or not isinstance(self.state.get('events'),list)
                or not {'active','last_cleared','pending'}<=self.state.keys()):
            raise RuntimeError('次元探查原记录丢失或损坏；停止，不创建空历史。')
        (self.root/'evidence').mkdir(exist_ok=True)

    def save(self):durable_json(self.path,self.state)

    def evidence(self,snapshot,observation,reading,reason):
        name=str(time.time_ns())+'-'+uuid.uuid4().hex[:8]
        image=self.root/'evidence'/(name+'.png');tmp=image.with_suffix('.png.tmp')
        with tmp.open('xb') as f:
            snapshot.image.save(f,format='PNG');f.flush();os.fsync(f.fileno())
        os.replace(tmp,image)
        metadata={'at':time.time(),'reason':reason,'scene':reading.scene,'stage':reading.stage,
            'captured_at':snapshot.captured_at,'width':observation.width,'height':observation.height,
            'fingerprint':fingerprint(observation),'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
            'tokens':[vars(t) for t in observation.tokens],'visuals':sorted(observation.visuals)}
        durable_json(image.with_suffix('.json'),metadata)
        return str(image.relative_to(self.root))

    def observe(self,reading,evidence):
        changed=False
        active=self.state.get('active')
        if reading.scene=='defeat' and active:
            node=active.get('nodes',{}).get(active.get('current_node'))
            if node and node.get('battle_start_intent') and node.get('status')!='failed':
                node.update(status='failed',defeat_evidence=evidence,failed_at=time.time());active['status']='failed'
                self.state['attempted'][active['stage']].update(outcome='defeat',defeat_evidence=evidence)
                self.state['events'].append({'kind':'defeat_verified','node':active['current_node'],'evidence':evidence,'at':time.time()});changed=True
        if reading.scene=='dimension_supply_complete':
            node=(active or {}).get('nodes',{}).get(reading.key,{})
            if not node.get('loot_confirm_intent') or not node.get('supply_choice_intent'):
                raise TaskAttention('dimension_supply_result','补给结果无法关联','没有本次免费战利品的完整选择/领取记录。')
            if node.get('status')!='completed':
                before_meta=read_json(self.root/Path(node['supply_choice_intent']['evidence']).with_suffix('.json'));after_meta=read_json(self.root/Path(evidence).with_suffix('.json'))
                if not all(len(counter_values(before_meta,source))==1 and counter_values(before_meta,source)==counter_values(after_meta,source) for source in ('dimension_life','dimension_budget')):
                    raise TaskAttention('dimension_supply_counters','补给资源变化未知','领取后生命体征或额度无法核实保持，不继续。')
                node.update(status='completed',reward_evidence=evidence,cleared_at=time.time());active['last_cleared_node']=reading.key
                self.state['events'].append({'kind':'supply_loot_verified','node':reading.key,'evidence':evidence,'at':time.time()});changed=True
        if active and reading.scene in ('dimension_route_avoid','dimension_route_node'):
            previous=active.get('nodes',{}).get(active.get('current_node'),{})
            leave=previous.get('rest_leave_intent')
            if leave and previous.get('status')!='completed':
                before_meta=read_json(self.root/Path(leave['evidence']).with_suffix('.json'));after_meta=read_json(self.root/Path(evidence).with_suffix('.json'))
                counters=counter_values
                if not all(len(counters(before_meta,source))==1 and counters(before_meta,source)==counters(after_meta,source) for source in ('dimension_life','dimension_budget')):
                    raise TaskAttention('dimension_rest_resources','休整资源未核实','离开后生命体征/招募额度无法确认保持，不继续。')
                previous.update(status='completed',exit_evidence=evidence,cleared_at=time.time());active['last_cleared_node']=active['current_node']
                self.state['events'].append({'kind':'rest_exit_verified','node':active['current_node'],'evidence':evidence,'at':time.time()});changed=True
        if reading.scene=='dimension_event_result':
            node=(active or {}).get('nodes',{}).get(reading.key,{})
            choice=node.get('choice_intents',{}).get(reading.event)
            if not choice or reading.budget is None:raise TaskAttention('dimension_event_reward','事件奖励未核实','缺少本次抉择或结果额度。')
            before_meta=read_json(self.root/Path(choice['evidence']).with_suffix('.json'))
            budgets={tuple(map(int,t['text'].split('/'))) for t in before_meta['tokens'] if t['source']=='dimension_budget'}
            after_used,after_max=reading.budget
            if reading.event=='dust_corridor':
                valid=len(budgets)==1 and next(iter(budgets))==(after_used,after_max-1)
            elif reading.event=='ancient_stele':
                after_meta=read_json(self.root/Path(evidence).with_suffix('.json'))
                def fragments(meta):return {int(t['text']) for t in meta['tokens'] if t['source']=='dimension_fragments' and t['score']>=.85}
                before_fragments=fragments(before_meta);after_fragments=fragments(after_meta)
                valid=(len(budgets)==1 and next(iter(budgets))==reading.budget
                    and len(counter_values(before_meta,'dimension_life'))==1 and counter_values(before_meta,'dimension_life')==counter_values(after_meta,'dimension_life')
                    and len(before_fragments)==1 and len(after_fragments)==1 and next(iter(after_fragments))==next(iter(before_fragments))+50)
            elif reading.event=='torn_vestment':
                after_meta=read_json(self.root/Path(evidence).with_suffix('.json'))
                before_life={t['text'] for t in before_meta['tokens'] if t['source']=='dimension_life'}
                after_life={t['text'] for t in after_meta['tokens'] if t['source']=='dimension_life'}
                valid=len(budgets)==1 and next(iter(budgets))==reading.budget and len(before_life)==1 and before_life==after_life
            else:valid=False
            if not valid:raise TaskAttention('dimension_event_reward','事件资源变化未知','实际额度/生命体征与已验证的免费选项结果不符，不继续。')
            if node.get('status')!='completed':
                node.update(status='completed',event_success=reading.event,event_evidence=evidence,cleared_at=time.time())
                active['last_cleared_node']=reading.key
                self.state['events'].append({'kind':'event_success_verified','node':reading.key,'event':reading.event,'budget_after':reading.budget,'evidence':evidence,'at':time.time()});changed=True
        if reading.scene=='dimension_node_victory':
            node=(active or {}).get('nodes',{}).get(reading.key)
            if not node or not node.get('battle_start_intent'):
                raise TaskAttention('dimension_orphan_result','结算无法关联','不能把没有本次开战记录的胜利补记为当前节点。')
            if node.get('status')!='completed':
                node.update(status='completed',victory_evidence=evidence,cleared_at=time.time())
                active['last_cleared_node']=reading.key
                self.state['events'].append({'kind':'node_victory_verified','node':reading.key,'evidence':evidence,'at':time.time()});changed=True
        for role,hero in reading.recruits:
            if not active:raise RuntimeError('没有当前探查，不能认领招募结果。')
            if role in active.get('recruited_roles',{}):continue
            intent=active.get('recruit_intents',{}).get(role)
            if not intent or intent['hero']!=hero or reading.budget is None:
                raise TaskAttention('dimension_recruit_result','招募结果未核实','缺少相符英雄、招募意图或额度读数。')
            used,total=reading.budget;before,maximum=intent['budget_before']
            if total!=maximum or used!=before+intent['cost']:
                raise TaskAttention('dimension_recruit_budget','招募额度变化未知','招募后额度与预期不一致，不继续消费。')
            active.setdefault('recruited_roles',{})[role]={'hero':hero,'cost':intent['cost'],'evidence':evidence,'at':time.time()}
            self.state['events'].append({'kind':'recruit_verified','role':role,'hero':hero,'evidence':evidence,'at':time.time()});changed=True
        if changed:self.save()
        pending=self.state['pending'];key=list(reading_key(reading))
        if pending and pending['reading']!=key:
            self.state['events'].append({'kind':'transition_observed','at':time.time(),
                'action_id':pending['id'],'next_scene':reading.scene,'evidence':evidence})
            # Keep all past intents; a changed page is not proof of completion.
            self.state['pending']=None;self.save()

    def attention(self,reading,evidence):
        self.state['events'].append({'kind':'attention','at':time.time(),'scene':reading.scene,'evidence':evidence})
        self.save()

    def reserve(self,reading,action,evidence):
        key=list(reading_key(reading))
        if self.state['pending']:
            raise TaskAttention('dimension_pending','上次输入尚未验证','当前界面未确认变化；不重复点击或重开。')
        # Revalidate the allowlisted plan, not merely a caller-supplied action kind.
        if action != plan(reading,self.state):raise RuntimeError('动作不是当前已验收界面的计划，已拒绝输入。')
        proof=(self.root/evidence).resolve()
        if not proof.is_relative_to((self.root/'evidence').resolve()) or proof.suffix!='.png':
            raise RuntimeError('次元探查输入证据路径无效。')
        meta=read_json(proof.with_suffix('.json'))
        if (not isinstance(meta,dict) or meta.get('scene')!=reading.scene or meta.get('stage')!=reading.stage
                or meta.get('image_sha256')!=hashlib.sha256(proof.read_bytes()).hexdigest()):
            raise RuntimeError('次元探查输入证据不匹配或缺失。')
        # No unverified combat handler can acquire entry authority accidentally.
        if action.kind not in ('navigate','back','enter','loadout_select','loadout_confirm','ticket_open','hero_select','hero_recruit','route_begin','node_open','node_enter','battle_start','battle_continue','event_choice','event_continue','rest_leave','rest_confirm','supply_loot','loot_select','loot_confirm','supply_leave'):
            raise RuntimeError('次元探查入场/抉择尚未验收，已拒绝输入。')
        event={'id':uuid.uuid4().hex,'kind':'input_intent','at':time.time(),'reading':key,
               'action':action.name,'input_kind':action.kind,'evidence':evidence}
        if action.kind in ('loot_select','loot_confirm','supply_leave'):
            self.state['active']['nodes'][reading.key][action.kind+'_intent']={'item':'闪电箭簇','at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='supply_loot':
            self.state['active']['nodes'][reading.key]['supply_choice_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='rest_confirm':
            self.state['active']['nodes'][reading.key]['rest_skip_confirm_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='rest_leave':
            self.state['active']['nodes'][reading.key]['rest_leave_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='event_continue':
            self.state['active']['nodes'][reading.key]['result_continue_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='event_choice':
            self.state['active']['nodes'][reading.key].setdefault('choice_intents',{})[reading.event]={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='battle_continue':
            self.state['active']['nodes'][reading.key]['result_continue_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='battle_start':
            node=self.state['active']['nodes'][reading.key]
            node['battle_start_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence};node['status']='battle_start_intent'
        if action.kind=='node_enter':
            self.state['active'].setdefault('nodes',{})[reading.key]={'kind':'boss' if reading.scene=='dimension_boss_gate' else 'supply' if reading.scene=='dimension_supply_gate' else 'rest' if reading.scene=='dimension_rest_gate' else 'event' if reading.scene=='dimension_event_gate' else 'battle','status':'entry_intent','at':event['at'],'input_id':event['id'],'evidence':evidence}
            self.state['active']['current_node']=reading.key
        if action.kind=='node_open':
            self.state['active']['selected_node']=reading.key
            if reading.route:
                self.state['active'].setdefault('route_decisions',{})[reading.key]={'route':reading.route,'combat_bounds':reading.combat_bounds,'detail':reading.detail,'evidence':evidence,'at':event['at']}
            self.state['active'].setdefault('node_navigation_intents',{})[reading.key]={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='route_begin':
            self.state['active']['route_start_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='hero_recruit':
            active=self.state['active'];role=active['current_role']
            active.setdefault('recruit_intents',{})[role]={'hero':reading.hero,'cost':reading.cost,'budget_before':reading.budget,'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='hero_select':
            active=self.state['active'];role=active['current_role']
            active.setdefault('hero_selection_intents',{})[role]={'hero':reading.key,'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='ticket_open':
            self.state['active'].setdefault('ticket_intents',{})[reading.key]={'at':event['at'],'input_id':event['id'],'evidence':evidence}
            self.state['active']['current_role']=reading.key
        if action.kind=='loadout_confirm':
            self.state['active']['loadout_confirm_intent']={'at':event['at'],'input_id':event['id'],'evidence':evidence}
        if action.kind=='loadout_select':
            active=self.state['active']
            if not active or active.get('loadout_selection'):raise RuntimeError('初始方案已有选择意图或无当前入场。')
            active['loadout_selection']={'name':'雇佣契约','at':event['at'],'evidence':evidence,'input_id':event['id']}
        if action.kind=='enter':
            stage=action.stage
            if self.state['active'] or stage in self.state['attempted'] or stage in self.state['completed']:
                raise TaskAttention('dimension_attempted','禁止重复探查','阶段已有尝试/完成或另一入场未结算。')
            authorization=self.state.get('entry_authorizations',{}).get(stage)
            if not authorization or authorization.get('consumed_at'):
                raise TaskAttention('dimension_authorization','阶段未授权','没有可用的首次入场授权。')
            entry={'stage':stage,'entry_id':event['id'],'at':event['at'],'evidence':evidence,'status':'entry_intent','strategy':'avoid_combat'}
            self.state['attempted'][stage]=dict(entry);self.state['active']=dict(entry)
            authorization['consumed_at']=event['at']
        self.state['pending']=event;self.state['events'].append(dict(event));self.save()
        return event['id']
