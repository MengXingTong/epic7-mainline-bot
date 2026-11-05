"""Avoid-combat routing over a verified visible graph, never guessed map edges.

Question-mark rooms have a [0, 1] combat interval. A favorable lower bound is
not a guarantee of a no-combat room or a globally minimal undiscovered route.
"""
from dataclasses import dataclass
import heapq

BOUNDS={'battle':(1,1),'elite':(1,1),'boss':(1,1),'event':(0,0),
        'rest':(0,0),'shop':(0,0),'treasure':(0,0),'unknown':(0,1)}

@dataclass(frozen=True)
class Node:
    id:str
    kind:str
    locked:bool=False
    completed:bool=False

@dataclass(frozen=True)
class Route:
    nodes:tuple[str,...]
    minimum_combats:int
    maximum_combats:int
    unknown_rooms:int
    globally_proven:bool
    detail:str


def avoid_combat(nodes,edges,start,goals,*,full_graph=False):
    """edges contains only UI-verified directed links; no Euclidean shortcuts.

    Rank by known encounters, then elite rooms, then unknown encounters and
    length. Completed/locked nodes cannot be traversed to reroll or backtrack.
    A full graph alone is not enough for a proof when unknown rooms may fight.
    """
    by_id={n.id:n for n in nodes};goals=set(goals)
    if len(by_id)!=len(nodes):raise ValueError('重复节点身份，不能覆盖锁定/完成状态。')
    if start not in by_id or not goals<=by_id.keys():raise ValueError('路线端点未核实。')
    if any(n.kind not in BOUNDS for n in nodes):raise ValueError('未知节点类型不能伪装为免费事件。')
    links={k:set(v) for k,v in edges.items()}
    if any(k not in by_id or not set(v)<=by_id.keys() for k,v in links.items()):raise ValueError('连接引用未核实节点。')
    queue=[((0,0,0,0),(start,),0,0)];answers=[];expanded=0
    # Bound is a graph-complexity guard, not a game-stage/run-count ceiling.
    while queue:
        score,path,lower,upper=heapq.heappop(queue);node=path[-1]
        if node in goals:
            answers.append((score,path,lower,upper))
            if len(answers)>=2:break
            continue
        expanded+=1
        if expanded>100000:raise ValueError('可见路线图复杂度超出安全规划范围。')
        for nxt in sorted(links.get(node,())):
            target=by_id[nxt]
            if nxt in path or target.locked or target.completed:continue
            lo,hi=BOUNDS[target.kind];uncertain=int(lo!=hi);elite=int(target.kind=='elite')
            new=(score[0]+lo,score[1]+elite,score[2]+uncertain,score[3]+1)
            heapq.heappush(queue,(new,path+(nxt,),lower+lo,upper+hi))
    if not answers:return None
    score,path,lo,hi=answers[0]
    proven=bool(full_graph and (len(answers)==1 or hi<=answers[1][2]))
    return Route(path,lo,hi,score[2],proven,
        '全图已核实，交战数上界不超过替代路线下界。' if proven else '仅依据已核实连线与可见节点规划；问号可能含战斗，隐藏地图未作全局最优承诺。')
