"""Positive recognition of free upgrade overlays, never generic dialogs."""
import re,unicodedata

def rankup_splash(words,width=1600,height=900):
    rows=[(re.sub(r"[\W_]+","",unicodedata.normalize('NFKC',w['text'])).casefold(),w['x']/width,w['y']/height) for w in words]
    if any(t in ('确认','确定','確認','確定','取消','购买','購買','复活','兑换') or any(v in t for v in ('购买','兑换','复活','是否消耗','是否使用')) for t,x,y in rows):return False
    heading=any(t=='rankup' and .3<x<.7 and .13<y<.5 for t,x,y in rows)
    number=any(re.fullmatch(r"\d{1,4}",t) and .3<x<.7 and .2<y<.62 for t,x,y in rows)
    footer=''.join(t for t,x,y in rows if .15<x<.85 and .70<y<.96)
    return bool(heading and number and 'rank提升' in footer and re.search(r'已恢复\d+点行动力',footer) and '继续' in footer and '旅程' in footer)


def account_upgrade_notice_close(words,width=1600,height=900):
    """Account stamina-cap increase is free; dismiss only its observed Close label.

    This is not the RANK UP splash and does not have a Confirm button. The
    heading, explanatory caption and close control must belong to this modal.
    """
    translate=str.maketrans({'帳':'账','賬':'账','號':'号','動':'动','級':'级','點':'点','擊':'击','關':'关','閉':'闭','購':'购','買':'买','換':'换','復':'复'})
    rows=[]
    for word in words:
        text=re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',word['text'])).translate(translate).casefold().replace('帐号','账号')
        rows.append((text,word['x']/width,word['y']/height,word))
    if any(text in ('确认','确定','確認','確定','取消','购买','复活','兑换') or any(v in text for v in ('购买','兑换','复活','是否消耗','是否使用','消耗道具','使用道具')) for text,x,y,word in rows):return None
    confident=[row for row in rows if row[3].get('score',1.0)>=.8]
    heading=any(text=='升级' and .3<x<.7 and .12<y<.5 for text,x,y,word in confident)
    caption=''.join(text for text,x,y,word in confident if .2<x<.8 and .22<y<.68)
    notice=bool(re.search(r'账号(?:升等|升级)',caption) and '行动力上限已提升' in caption)
    close=[word for text,x,y,word in confident if text=='点击关闭' and .3<x<.7 and .5<y<.94]
    return close[0] if heading and notice and len(close)==1 else None
