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


FRIENDSHIP_TITLES=('英雄亲密度等级上升','英雄亲密度等级提升',
                   '英雄親密度等級上升','英雄親密度等級提升')


def friendship_upgrade_notice_close(words,width=1600,height=900):
    """Dismiss the free friendship notice at its current, observed close label."""
    translate=str.maketrans({'親':'亲','級':'级','輕':'轻','觸':'触','後':'后',
        '關':'关','閉':'闭','點':'点','擊':'击','購':'购','買':'买','兌':'兑',
        '換':'换','復':'复','確':'确','認':'认'})
    rows=[(re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',w['text'])).translate(translate).casefold(),
           w['x']/width,w['y']/height,w) for w in words]
    if any(text in ('取消','failed','defeat') or any(v in text for v in
           ('购买','兑换','复活','是否消耗','是否使用','消耗道具','使用道具','战斗失败','挑战失败'))
           for text,x,y,word in rows):return None
    confident=[row for row in rows if row[3].get('score',1.0)>=.8]
    heading=any(text in ('英雄亲密度等级上升','英雄亲密度等级提升') and .25<x<.9 and .08<y<.5
                for text,x,y,word in confident)
    close=[word for text,x,y,word in confident if text in ('轻触后关闭','轻触关闭','点击关闭')
           and .25<x<.9 and .5<y<.96]
    confirmations=[row for row in rows if row[0] in ('确认','确定')]
    if confirmations:
        # The friendship modal can cover the independent battle-result page.
        # Ignore only its observed bottom-right Confirm; every other confirm,
        # cancel, paid/resource or defeat combination remains a veto.
        settlement_background=(len(confirmations)==1 and confirmations[0][3].get('score',1.0)>=.8
            and .78<confirmations[0][1]<.98
            and .78<confirmations[0][2]<.98
            and any(text=='获得的道具' and .72<x<.99 and 0<y<.18
                    for text,x,y,word in confident)
            and any(text=='战斗结果' and .65<x<.9 and .78<y<.98
                    for text,x,y,word in confident))
        if not settlement_background:return None
    return close[0] if heading and len(close)==1 else None
