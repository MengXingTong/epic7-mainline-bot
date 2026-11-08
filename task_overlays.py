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


def battle_settlement_confirm(words,width=1600,height=900):
    """Require both result labels and a unique, confident bottom-right button."""
    rows=[(re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',w['text'])).translate(
        str.maketrans({'確':'确','認':'认'})),w['x']/width,w['y']/height,w) for w in words]
    if any(text in ('取消','취소') for text,x,y,word in rows):return None
    confirmations=[row for row in rows if row[0] in ('确认','确定')]
    confident=[row for row in rows if row[3].get('score',1.0)>=.8]
    if (len(confirmations)==1 and confirmations[0][3].get('score',1.0)>=.8
        and .8125<confirmations[0][1]<.98 and .8333<confirmations[0][2]<.98
        and any(text=='获得的道具' and .72<x<.99 and 0<y<.18 for text,x,y,word in confident)
        and any(text=='战斗结果' and .6875<x<.894 and .822<y<.999 for text,x,y,word in confident)):
        return confirmations[0][3]
    return None


def date_change_notice_close(words,width=1600,height=900):
    """Close only the date-change notice that explicitly returns to the lobby."""
    rows=[(re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',w['text'])).casefold(),
           w['x']/width,w['y']/height,w) for w in words]
    if any(text in ('确认','确定','確認','確定','取消','취소','failed','defeat') or any(v in text for v in
           ('购买','兑换','复活','是否消耗','是否使用','消耗道具','使用道具','战斗失败','挑战失败','闯关失败','任务失败','任務失敗'))
           for text,x,y,w in rows):return None
    confident=[row for row in rows if row[3].get('score',1)>=.85]
    heading=any(text=='变更日期' and .3<x<.7 and .2<y<.4 for text,x,y,w in confident)
    caption=any(text=='日期变更将前往大厅' and .3<x<.7 and .38<y<.6 for text,x,y,w in confident)
    close=[row for row in rows if row[0]=='点击关闭']
    if heading and caption and len(close)==1:
        text,x,y,word=close[0]
        if word.get('score',1)>=.85 and .3<x<.7 and .55<y<.8:return word
    return None


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
        if battle_settlement_confirm(words,width,height) is None:return None
    return close[0] if heading and len(close)==1 else None


def chat_panel_heading(words,width=1600,height=900):
    """A partial chat header may veto the background, never authorize a tap."""
    return any(re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',w['text'])) in
               ('骑士团频道','世界频道','聊天频道','频道') and w.get('score',1.0)>=.85
               and .55<w['x']/width<.85 and 0<w['y']/height<.10 for w in words)


def chat_panel_visible(words,width=1600,height=900):
    """Identify the chat overlay, not chat words in a story or the lobby."""
    rows=[(re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',w['text'])),
           w['x']/width,w['y']/height,w.get('score',1.0)) for w in words]
    rows=[row for row in rows if row[3]>=.85]
    heading=chat_panel_heading(words,width,height)
    entry=any(t=='点击此处并输入' and .55<x<.89 and .86<y<.99 for t,x,y,score in rows)
    send=any(t=='输入' and .86<x<.99 and .86<y<.99 for t,x,y,score in rows)
    connecting=any(t=='与聊天服务器连接中' and .55<x<.95 and .40<y<.65 for t,x,y,score in rows)
    return heading and ((entry and send) or connecting)


def top_right_skip_control(words,*,tutorial=False):
    """Only a unique current exact label authorizes the shared chat/skip area."""
    # Even incomplete results cannot reuse a residual Skip token.
    result_labels={'clear','victory','关卡任务','闯关成功','战斗结果','获得的道具'}
    def normalized(w):return re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',w['text'])).casefold()
    # The preparation objective is not a result banner. Only a full known
    # preparation layout distinguishes it; partial results keep their veto.
    def anchor(label,bounds):
        x1,y1,x2,y2=bounds
        rows=[w for w in words if normalized(w)==label and w.get('score',0)>=.98
              and x1<=w['x']<=x2 and y1<=w['y']<=y2]
        return len(rows)==1
    preparation=(tutorial and anchor('准备战斗',(60,10,260,80))
        and anchor('可获得的奖励',(1150,535,1450,620))
        and anchor('登场的敌人',(1180,330,1450,395))
        and anchor('闯关成功',(1180,200,1450,285)))
    if any(normalized(w) in result_labels and not
           (preparation and normalized(w)=='闯关成功' and 1180<=w['x']<=1450 and 200<=w['y']<=285)
           for w in words):return None
    if chat_panel_heading(words):return None
    label='跳过教学' if tutorial else '跳过'
    candidates=[w for w in words if re.sub(r'\s+','',unicodedata.normalize('NFKC',w['text']))==label]
    if len(candidates)!=1:return None
    w=candidates[0]
    if w.get('score',0)<.90 or not ((1330 if tutorial else 1400)<=w['x']<=1599 and 0<=w['y']<=100):return None
    return w


# Explicit passive notices only. New error namespaces are NOT wildcard-approved.
_PASSIVE_FREE_NOTICE_BODIES={
    'tutorial_complete.already_completed_tutorial':'tutorial_completed_notice',
    '该教学已完成。':'tutorial_completed_notice',
    '该教程已完成。':'tutorial_completed_notice',
    '此教学已完成。':'tutorial_completed_notice',
    '此教程已完成。':'tutorial_completed_notice',
}


def passive_free_notice(words,width=1600,height=900):
    """Known harmless body + one current Close, not every closeable dialog.

    Background narrative containing e.g. 确认自己 is not a Confirm button.
    Real confirmation controls and in-panel unknown/cost text still veto. The
    classifier's independent capacity/resource/defeat guards remain higher.
    """
    def text(word):return re.sub(r'\s+','',unicodedata.normalize('NFKC',word['text']))
    rows=[(text(w),w['x']/width,w['y']/height,w) for w in words]
    if any(re.fullmatch(r'确认|确定|取消|確認|確定|OK|YES|NO',t,re.I) for t,x,y,w in rows):return None
    headings=[(t,w) for t,x,y,w in rows if t in _PASSIVE_FREE_NOTICE_BODIES]
    closes=[w for t,x,y,w in rows if t in ('点击关闭','點擊關閉')]
    if len(headings)!=1 or len(closes)!=1:return None
    body,title=headings[0];close=closes[0]
    if (title.get('score',0)<.98 or close.get('score',0)<.98
        or not (.30<title['x']/width<.70 and .33<title['y']/height<.55)
        or not (.35<close['x']/width<.65 and .55<close['y']/height<.70)):
        return None
    # The notice panel itself must contain only the approved body and Close.
    # Do not confuse faded text outside the panel with modal controls.
    if any(w is not title and w is not close and .18<x<.83 and .29<y<.71 for t,x,y,w in rows):return None
    return dict(kind=_PASSIVE_FREE_NOTICE_BODIES[body],body=body,target=close)


def tutorial_completed_notice_close(words,width=1600,height=900):
    notice=passive_free_notice(words,width,height)
    return notice['target'] if notice and notice['kind']=='tutorial_completed_notice' else None
