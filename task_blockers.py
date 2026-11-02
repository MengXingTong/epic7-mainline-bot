"""Non-combat conditions that require manual handling, never a defeat verdict."""
from dataclasses import dataclass
import re,unicodedata

@dataclass(frozen=True)
class Blocker:
    code:str
    title:str
    reason:str

class TaskAttention(RuntimeError):
    def __init__(self,code,title,reason):
        self.code=code;self.title=title;self.reason=reason
        super().__init__(reason)

_TRANSLATE=str.maketrans({'裝':'装','備':'备','滿':'满','達':'达','數':'数','間':'间','夠':'够','獲':'获','無':'无','擴':'扩','欄':'栏','儲':'储'})
def capacity_blocker(texts):
    text=re.sub(r'[\s，。！？：:,.!?·…+_—\-|/（）()]+','',unicodedata.normalize('NFKC',''.join(texts)).translate(_TRANSLATE))
    full=r'(?:已满(?!级)|已达上限|已达到上限|达到.{0,6}上限|超过.{0,8}上限|超出.{0,8}上限|空间不足|容量不足|空间不够|数量上限|持有上限|没有足够.{0,5}空间|无法再获)'
    rules=(('equipment',r'装备','装备背包已满'),('artifact',r'神器','神器容量已满'),('hero',r'英雄(?:栏|数量|持有)?','英雄栏已满'),('inventory',r'背包|道具箱|道具容量|储存空间','背包容量不足'))
    for code,subject,title in rules:
        if re.search(subject+r'.{0,28}'+full,text) or re.search(full+r'.{0,18}'+subject,text):
            return Blocker(code,title,'请手动整理容量后点“处理后继续”；不会出售、扩容、兑换或重试已记录关卡。')
    return None
