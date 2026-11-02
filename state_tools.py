"""Offline, copy-on-write reconciliation; never erase a previous attempt."""
import copy

def manual_clear(state,node,proof,evidence,when):
    active=state.get('active')
    if not active or not node or proof!='已通关绿色勾':raise ValueError('Manual clear needs the exact active stage and green completion proof')
    key=active['key']
    if node.get('key')!=key or any(node.get(k)!=active.get(k) for k in ('episode','chapter','stage')):
        raise ValueError('Manual clear belongs to another stage')
    if key not in state.get('attempted',{}):raise ValueError('Active stage has no durable attempt record')
    if key in state.get('completed',{}):raise ValueError('Stage is already recorded complete; do not reconcile twice')
    result=copy.deepcopy(state)
    entry={**result['active'],'manual_completed':True,'outcome':'user_cleared_after_stop','completed_at':when,'proof':'手动补过后精确选中原关卡，已核实绿色通关勾','evidence':evidence}
    result['attempted'][key]['manual_cleared_at']=when
    result['completed'][key]=entry
    result['active']=None;result['last_cleared']=entry;result['last_stage']=key
    result['victories']=len(result['completed'])
    result['manual_clears']=sum(bool(x.get('manual_completed')) for x in result['completed'].values())
    result['script_victories']=result['victories']-result['manual_clears']
    return result
