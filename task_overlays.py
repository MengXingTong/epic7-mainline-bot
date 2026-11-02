"""Positive recognition of free full-screen overlays, never generic dialogs."""
import re,unicodedata

def rankup_splash(words,width=1600,height=900):
    rows=[(re.sub(r"[\W_]+","",unicodedata.normalize('NFKC',w['text'])).casefold(),w['x']/width,w['y']/height) for w in words]
    if any(t in ('确认','确定','確認','確定','取消','购买','購買','复活','兑换') or any(v in t for v in ('购买','兑换','复活','是否消耗','是否使用')) for t,x,y in rows):return False
    heading=any(t=='rankup' and .3<x<.7 and .13<y<.5 for t,x,y in rows)
    number=any(re.fullmatch(r"\d{1,4}",t) and .3<x<.7 and .2<y<.62 for t,x,y in rows)
    footer=''.join(t for t,x,y in rows if .15<x<.85 and .70<y<.96)
    return bool(heading and number and 'rank提升' in footer and re.search(r'已恢复\d+点行动力',footer) and '继续' in footer and '旅程' in footer)
