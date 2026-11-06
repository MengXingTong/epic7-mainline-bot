"""Positive navigation out of the observed free-summon flow, not a draw reader."""
import re
from tutorial_control_templates import covenant_back


def covenant_return_plan(f,unique):
    anchors=[unique(f,p,region,.98) for p,region in (
        ('召唤',(60,0,220,85)),('圣约召唤',(15,755,265,865)),
        ('愿望单',(780,650,925,735)),
        ('5',(985,795,1090,865)),('召唤1次',(1100,790,1250,875)),
        ('50',(1290,795,1410,865)),('召唤10次',(1410,790,1580,880)))]
    if not all(anchors):return None
    if any(re.search(r'免费|点击关闭|OK|确定|确认|取消|获得奖励|跳过|通知|提示|警告|错误|已加入',w['text']) for w in f.words):return None
    # Character art can animate and produce incidental OCR. Do not impose a
    # full-screen text whitelist; the live arrow must also match absolute
    # brightness, so a dimmed underlying page never authorizes a return.
    back=covenant_back(f)
    if not back:return None
    return dict(rule='guided_free_covenant_return',label='免费召唤发送后仅返回原流程（当前已是付费按钮，绝不再抽取；不补记成功）',target=back,proof=[*anchors,back])


def covenant_episode_plan(f,unique):
    """Observed completed tutorial menu; navigate, never claim the task reward."""
    anchors=[unique(f,p,region,.98) for p,region in (
        (r'进行圣约召唤\s*[(（]1/1[)）]',(780,100,1130,185)),
        ('Episode',(850,185,1100,280)),('欧勒毕斯指南',(1100,180,1290,255)),
        ('图鉴',(1280,180,1420,255)),('英雄',(1440,180,1580,255)),
        ('成就',(1110,600,1280,695)),('英雄休息室',(1260,600,1440,695)),
        ('召唤',(980,530,1100,610)))]
    if not all(anchors):return None
    if any(re.search(r'确认|取消|点击关闭|OK|购买|复活|通知|警告|错误',w['text']) for w in f.words):return None
    return dict(rule='guided_free_covenant_episode',label='按本帧圣约任务1/1和完整菜单进入Episode主线（不点任务奖励）',target=anchors[1],proof=anchors)
