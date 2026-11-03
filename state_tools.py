"""Offline, copy-on-write reconciliation; never erase a previous attempt."""
import copy

def manual_clear(state,node,proof,evidence,when):
    active=state.get('active')
    if not active or not node or proof!='已通关绿色勾':raise ValueError('人工补记通关需要精确匹配当前入场关卡，并提供绿色通关标记证明。')
    key=active['key']
    if node.get('key')!=key or any(node.get(k)!=active.get(k) for k in ('episode','chapter','stage')):
        raise ValueError('人工通关证明属于其他关卡。')
    if key not in state.get('attempted',{}):raise ValueError('当前入场关卡缺少已落盘的入场记录。')
    if key in state.get('completed',{}):raise ValueError('此关已记录为通关；禁止重复补记。')
    result=copy.deepcopy(state)
    entry={**result['active'],'manual_completed':True,'outcome':'user_cleared_after_stop','completed_at':when,'proof':'手动补过后精确选中原关卡，已核实绿色通关勾','evidence':evidence}
    result['attempted'][key]['manual_cleared_at']=when
    result['completed'][key]=entry
    result['active']=None;result['last_cleared']=entry;result['last_stage']=key
    result['victories']=len(result['completed'])
    result['manual_clears']=sum(bool(x.get('manual_completed')) for x in result['completed'].values())
    result['script_victories']=result['victories']-result['manual_clears']
    return result
