"""Positive, current-frame new-player tutorial readers; never a generic tap bot.

Every added rule is a named screen/control contract. Unknown guides do not gain
input permission from a finger, a bright area, or absence of a Skip button.
"""
from __future__ import annotations
import copy,hashlib,json,re,time,uuid


def _text(value):
    return re.sub(r'[\s，。！？：:,!?·…]+','',value)


def _unique(f,pattern,region,score=.96):
    x1,y1,x2,y2=region
    matches=[w for w in f.words if re.fullmatch(pattern,w['text'].strip())
             and w.get('score',0)>=score and x1<=w['x']<=x2 and y1<=w['y']<=y2]
    return matches[0] if len(matches)==1 else None


def tutorial_plan(f):
    """Identification only; Runner vetoes, two fresh frames and journal authorize."""
    from task_blockers import capacity_blocker
    if _unique(f,'跳过教学',(1330,0,1599,100),.95):return None
    if capacity_blocker(w['text'] for w in f.words):return None
    if any(re.search(r'购买|兑换|复活|是否消耗|是否使用|消耗道具|使用道具|战斗失败|挑战失败|充值|支付',w['text']) for w in f.words):return None
    recommend_question=_unique(f,'是否应用推荐列表[？?]',(500,335,1100,465),.98)
    recommend_confirm=_unique(f,'确认',(800,515,1100,640),.98)
    recommend_cancel=_unique(f,'取消',(500,515,800,640),.98)
    if recommend_question and recommend_confirm and recommend_cancel:
        return dict(rule='guided_free_covenant_confirm_recommend',label='确认当前免费愿望单的游戏推荐配置（不抽取/消费）',target=recommend_confirm,proof=[recommend_question,recommend_confirm,recommend_cancel])
    from tutorial_battle_confirmation import power_warning_plan
    power_warning=power_warning_plan(f,_unique)
    if power_warning:return power_warning
    from tutorial_team_dialog import auto_configuration_plan
    auto_configuration=auto_configuration_plan(f,_unique)
    if auto_configuration:return auto_configuration
    if any(re.search(r'取消',w['text']) for w in f.words):return None
    acquisition=free_victoria_acquisition_plan(f)
    if acquisition:return acquisition
    attendance_title=_unique(f,'梅露铃的签到奖励',(200,40,950,135),.98)
    attendance_info=_unique(f,'签到奖励一天可获得一次[。.]?',(300,120,850,180),.98)
    attendance_day=_unique(f,r'连续签到第[1-9]\d?天',(1150,650,1500,745),.98)
    attendance_count=_unique(f,r'获得的奖励[：:]\s*[1-9]\d?\s*/\s*28',(1100,715,1550,790),.98)
    attendance_confirm=_unique(f,'确认',(1170,790,1510,880),.98)
    if all((attendance_title,attendance_info,attendance_day,attendance_count,attendance_confirm)):
        return dict(rule='melurin_attendance_ack',label='关闭已免费发放的梅露铃签到奖励（不兑换体力/不购买）',target=attendance_confirm,proof=[attendance_title,attendance_info,attendance_day,attendance_count,attendance_confirm])
    beginner_title=_unique(f,'萌新玩家签到活动',(100,35,650,115),.98)
    beginner_reward=_unique(f,'连续签到奖励',(1160,140,1480,230),.98)
    beginner_mail=_unique(f,'所有签到奖励将发送至邮箱，领取所有奖励后活动页面将不再显示[。.]?',(100,735,1130,805),.98)
    beginner_rank=_unique(f,'因等级不足而未能获得的奖励，将在达成所限等级之后一并发放[。.]?',(100,775,1130,835),.98)
    beginner_confirm=_unique(f,'确认',(1150,740,1490,850),.98)
    if all((beginner_title,beginner_reward,beginner_mail,beginner_rank,beginner_confirm)):
        return dict(rule='beginner_attendance_ack',label='关闭已发往邮箱的萌新免费签到展示（不打开邮箱/不购买）',target=beginner_confirm,proof=[beginner_title,beginner_reward,beginner_mail,beginner_rank,beginner_confirm])
    promo=_unique(f,r'[\u4e00-\u9fff·]{2,20}',(100,150,750,255),.98)
    goto_summon=_unique(f,'立即前往召唤',(1250,680,1580,785),.98)
    promo_confirm=_unique(f,'确认',(1250,785,1580,880),.98)
    promo_caption=_unique(f,r'[\u4e00-\u9fff·]{2,20}',(200,410,610,455),.98)
    promo_new=_unique(f,'NEW!',(560,250,700,350),.98)
    promo_class=_unique(f,'骑士|盗贼|战士|魔导士|射手|精灵师',(280,85,405,160),.98)
    promo_element=_unique(f,'火焰属性|寒气属性|自然属性|光明属性|黑暗属性',(390,85,620,160),.98)
    if all((promo,goto_summon,promo_confirm,promo_caption,promo_new,promo_class,promo_element)):
        return dict(rule='dismiss_observed_summon_promo',label='关闭已识别的英雄宣传展示（不前往召唤）',target=promo_confirm,proof=[promo,goto_summon,promo_confirm,promo_caption,promo_new,promo_class,promo_element])
    if any(re.search(r'确认|确定',w['text']) for w in f.words):return None
    from tutorial_navigation import covenant_return_plan,covenant_episode_plan
    return_plan=covenant_return_plan(f,_unique) or covenant_episode_plan(f,_unique)
    if return_plan:return return_plan
    altar_title=_unique(f,'精灵祭坛',(500,180,1100,280),.98)
    altar_open=_unique(f,'可进入精灵祭坛[。.]?',(500,465,1100,515),.98)
    altar_purpose=_unique(f,'请采集可用于英雄觉醒',(600,510,1000,535),.98)
    if not altar_purpose:
        purpose=_unique(f,'可用于英雄觉醒',(740,508,935,540),.98)
        if purpose and purpose.get('source') in ('current_altar_purpose_field_read','current_altar_purpose_dual_read'):altar_purpose=purpose
    altar_runes=_unique(f,'的各种符文[!！]',(550,530,1050,580),.98)
    altar_close=_unique(f,'点击关闭',(650,600,950,710),.98)
    if all((altar_title,altar_open,altar_purpose,altar_runes,altar_close)):
        return dict(rule='spirit_altar_unlocked',label='关闭已免费开放的精灵祭坛通知（不进入祭坛/不觉醒或消耗材料）',target=altar_close,proof=[altar_title,altar_open,altar_purpose,altar_runes,altar_close])
    awakening=[_unique(f,p,region,.98) for p,region in (
        ('英雄觉醒',(500,180,1100,280)),('可进行英雄觉醒[。.]?',(500,465,1100,515)),
        ('请使用属性相符的各种符文[，,]',(450,510,1150,535)),
        ('使英雄成长变得更强[!！]',(500,530,1100,580)),('点击关闭',(650,600,950,710)))]
    if all(awakening):
        return dict(rule='hero_awakening_unlocked',label='关闭英雄觉醒免费功能说明（不执行觉醒/不消耗符文）',target=awakening[-1],proof=awakening)
    bond=[_unique(f,p,region,.98) for p,region in (
        ('缘分',(500,180,1100,280)),('现在可以结下缘分了[。.]?',(500,465,1100,515)),
        ('请通过缘分得到新英雄[，,]',(450,510,1150,535)),
        ('并配置到队伍中吧[!！]',(500,530,1100,580)),('点击关闭',(650,600,950,710)))]
    if all(bond):
        return dict(rule='bond_feature_unlocked',label='关闭缘分功能免费开放说明（不招募/配置或消耗英雄）',target=bond[-1],proof=bond)
    guide_title=_unique(f,'欧勒毕斯指南',(500,180,1100,280),.98)
    guide_body=_unique(f,'欧勒毕斯指南功能已开启[。.]?',(450,450,1150,525),.98)
    guide_help=_unique(f,'可帮助继承者更好地了解《第七史诗》[。.]?',(400,495,1200,565),.98)
    guide_close=_unique(f,'点击关闭',(650,600,950,710),.98)
    if all((guide_title,guide_body,guide_help,guide_close)):
        return dict(rule='orbis_guide_unlocked',label='关闭已免费开启的欧勒毕斯指南通知（不入场）',target=guide_close,proof=[guide_title,guide_body,guide_help,guide_close])
    covenant_task=_unique(f,r'进行圣约召唤\s*[(（]0/1[)）]',(780,100,1130,185),.98)
    menu_summon=_unique(f,'召唤',(980,530,1100,610),.98)
    free_once=_unique(f,'免费1次[!！]',(970,510,1110,560),.98)
    menu_guide=_unique(f,'欧勒毕斯指南',(1100,180,1290,255),.98)
    if all((covenant_task,menu_summon,free_once,menu_guide)):
        return dict(rule='guided_free_covenant_menu',label='按当前0/1教学与免费1次标记进入圣约召唤页（尚不抽取）',target=menu_summon,proof=[covenant_task,menu_summon,free_once,menu_guide])
    summon_header=_unique(f,'召唤',(60,0,220,85),.98)
    covenant_tab=_unique(f,'圣约召唤',(15,755,265,865),.98)
    covenant_free=_unique(f,'免费1次[!！]',(0,715,180,790),.98)
    if summon_header and covenant_free and not covenant_tab:
        from tutorial_control_templates import covenant_free_tab
        covenant_tab=covenant_free_tab(f)
    free_available=_unique(f,'可免费召唤1/1[!！]',(950,720,1260,795),.98)
    free_cost=_unique(f,'免费',(970,795,1090,865),.98)
    free_single=_unique(f,'召唤1次',(1100,790,1250,875),.98)
    complete_wishes=_unique(f,'14/14',(925,670,1005,725),.98)
    if all((summon_header,covenant_tab,covenant_free,free_available,free_cost,free_single,complete_wishes)):
        return dict(rule='guided_free_covenant_draw_after_wishlist',label='接续当前1/1免费召唤：14/14愿望单已完成后首次实际抽取（不花货币）',target=free_single,proof=[summon_header,covenant_tab,covenant_free,free_available,free_cost,free_single,complete_wishes])
    wishlist=_unique(f,'愿望单',(780,650,925,735),.98)
    if all((summon_header,covenant_tab,free_available,free_cost,wishlist)):
        return dict(rule='guided_free_covenant_wishlist',label='当前免费召唤控件尚未启动，打开明确愿望单配置（不抽取）',target=wishlist,proof=[summon_header,covenant_tab,free_available,free_cost,wishlist])
    if all((summon_header,covenant_tab,covenant_free,free_available,free_cost,free_single)):
        return dict(rule='guided_free_covenant_draw',label='完成当前教学：仅一次明确1/1免费的圣约召唤（不花书签/钻石）',target=free_single,proof=[summon_header,covenant_tab,covenant_free,free_available,free_cost,free_single])
    if summon_header and covenant_tab and covenant_free:
        return dict(rule='guided_free_covenant_tab',label='选择当前标记免费1次的圣约召唤标签（不点付费抽取按钮）',target=covenant_tab,proof=[summon_header,covenant_tab,covenant_free])
    wish_title=_unique(f,'添加愿望单',(100,40,420,130),.98)
    wish_apply=_unique(f,'应用推荐列表',(280,735,620,815),.98)
    wish_close=_unique(f,r'[×xX]?\s*点击关闭',(650,830,950,895),.98)
    wish_unowned=_unique(f,'仅显示未持有',(750,45,1010,125),.98)
    if wish_title and wish_apply and wish_unowned and wish_close:
        import cv2,numpy as np
        occupied=True
        for x,y in ((214,276),(349,276),(214,403),(349,403),(214,530),(349,530),(214,655),(498,276),(632,276),(498,403),(632,403),(498,530),(632,530),(498,655)):
            tile=f.image[y-38:y+38,x-38:x+38]
            if float(np.std(tile))<35:occupied=False;break
        if occupied:
            return dict(rule='guided_free_covenant_close_wishlist',label='核实14个推荐愿望槽已有不同图标后关闭配置（不抽取）',target=wish_close,proof=[wish_title,wish_apply,wish_unowned,wish_close])
    if all((wish_title,wish_apply,wish_unowned)):
        return dict(rule='guided_free_covenant_recommend',label='按当前免费召唤流程应用游戏推荐愿望单（可编辑配置，不抽取/消费）',target=wish_apply,proof=[wish_title,wish_apply,wish_unowned])
    joined=_unique(f,r'.{2,20}已加入',(500,180,1100,300),.98)
    if joined:
        name=joined['text'][:-3]
        identity=_unique(f,'英雄【'+re.escape(name)+r'】已加入[。.]?',(450,460,1150,530),.98)
        guidance=_unique(f,r'将其配置进队伍后[，,]进行战斗吧[。.]?',(450,510,1150,575),.98)
        acknowledge=_unique(f,'OK',(650,600,950,710),.95)
        if identity and guidance and acknowledge:
            return dict(rule='hero_joined',label='确认已免费加入的故事英雄（不配置或消耗英雄）',target=acknowledge,
                        proof=[joined,identity,guidance,acknowledge])
        return None
    reward=_unique(f,'获得奖励',(650,150,950,260),.98)
    received=_unique(f,'已获得奖励[。.]?',(650,260,950,350),.98)
    reward_close=_unique(f,'点击关闭',(650,600,950,730),.98)
    if all((reward,received,reward_close)):
        return dict(rule='free_reward_notice',label='关闭已获得的免费奖励提示',target=reward_close,
                    proof=[reward,received,reward_close])
    if reward or received or reward_close:return None
    arrival=_unique(f,'成为继承者的维多丽卡登场',(600,590,1070,710),.98)
    heir=_unique(f,'维多丽卡',(260,770,560,835),.98)
    heir_hp=_unique(f,r'\d{1,6}/\d{1,6}',(300,835,580,890),.98)
    if arrival and heir and heir_hp:
        import cv2,numpy as np
        tile=cv2.cvtColor(f.image[575:715,600:1060],cv2.COLOR_BGR2HSV)
        blue=(tile[:,:,0]>=85)&(tile[:,:,0]<=115)&(tile[:,:,1]>70)&(tile[:,:,2]>110)
        if np.count_nonzero(blue)>500:
            return dict(rule='heir_victoria_arrival',label='继续已核实的维多丽卡成为继承者登场教学（非入场/抽卡）',target=arrival,proof=[arrival,heir,heir_hp])
    new_skill=_unique(f,'使用全新技能进行攻击',(1000,750,1430,865),.98)
    if new_skill and heir and heir_hp:
        import cv2,numpy as np
        zone=cv2.cvtColor(f.image[715:900,1415:1600],cv2.COLOR_BGR2HSV)
        blue=(zone[:,:,0]>=85)&(zone[:,:,0]<=115)&(zone[:,:,1]>70)&(zone[:,:,2]>100)
        wave=_unique(f,r'[xX×※]?\s*3\s*/\s*3',(155,0,310,70),.75)
        boss=_unique(f,'倪尔伽',(350,0,650,40),.98)
        if wave and boss and np.count_nonzero(blue)>1500 and np.std(f.image[780:880,1490:1580])>25:
            target=dict(x=1515,y=825,text='本帧维多丽卡新技能教学蓝色圆圈内的第三技能；不是魂燃按钮',score=1.)
            return dict(rule='heir_victoria_new_skill',label='按当前强制教学选择维多丽卡全新第三技能（不点魂燃）',target=target,proof=[new_skill,heir,heir_hp,wave,boss,target])
    skill_title=_unique(f,'承诺的荣耀',(1060,440,1320,515),.98)
    skill_attack=_unique(f,'冲锋攻击敌人，并使全体我军人员在2回',(950,550,1420,600),.98)
    skill_immunity=_unique(f,'合内获得免疫效果。根据目标最大生命值',(950,580,1420,635),.98)
    if heir and heir_hp and skill_title and skill_attack and skill_immunity:
        import cv2,numpy as np
        boss=_unique(f,'倪尔伽',(350,0,650,40),.98)
        wave=_unique(f,r'[xX×※]?\s*3\s*/\s*3',(155,0,310,70),.75)
        head=cv2.cvtColor(f.image[260:410,1200:1350],cv2.COLOR_BGR2HSV)
        light=(head[:,:,1]<110)&(head[:,:,2]>70)
        if boss and wave and np.count_nonzero(light)>3000:
            target=dict(x=1250,y=340,text='当前第三技能说明外露的已核实倪尔伽头部，完成技能选敌；不点说明里的强化或魂燃',score=1.)
            return dict(rule='heir_victoria_new_skill_target',label='按原新技能教学链选择当前倪尔伽（不点魂燃/强化）',target=target,proof=[skill_title,heir,heir_hp,wave,boss,skill_attack,skill_immunity,target])
    if heir and heir_hp and not arrival and not new_skill and not skill_title:
        import cv2,numpy as np
        boss=_unique(f,'倪尔伽',(350,0,650,40),.98)
        level=_unique(f,r'Lv[.．]?\s*10',(940,0,1050,40),.98)
        wave=_unique(f,r'[xX×※]?\s*3\s*/\s*3',(155,0,310,70),.75)
        hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
        glow=hsv[735:775,1460:1599];body=hsv[300:710,940:1590]
        gold=(glow[:,:,0]>=15)&(glow[:,:,0]<=40)&(glow[:,:,1]>60)&(glow[:,:,2]>200)
        bright=(glow[:,:,1]<120)&(glow[:,:,2]>220)
        light=(body[:,:,1]<100)&(body[:,:,2]>90)
        green=(body[:,:,0]>=30)&(body[:,:,0]<=85)&(body[:,:,1]>70)&(body[:,:,2]>70)
        if boss and level and wave and np.count_nonzero(gold)>700 and np.count_nonzero(bright)>900 and np.count_nonzero(light)>10000 and np.count_nonzero(green)>3000:
            target=dict(x=1240,y=510,text='新第三技能已选中且说明已独立消失，选取当前倪尔伽躯干完成教学攻击',score=1.)
            return dict(rule='heir_victoria_new_skill_execute',label='技能说明已关闭后，完成当前教学第三技能的敌方躯干选择',target=target,proof=[heir,heir_hp,wave,boss,level,target])
    position=selected_hero_position_plan(f)
    if position:return position
    assignment=owned_hero_assignment_plan(f)
    if assignment:return assignment
    team_slot=guided_team_slot_plan(f)
    if team_slot:return team_slot
    milestone=chapter_star_reward_plan(f)
    if milestone:return milestone
    tag_guide=_unique(f,'通过标签更换英雄',(270,750,700,865),.98)
    tag=_unique(f,'TAG',(90,790,225,880),.98)
    if tag_guide and tag:
        import cv2,numpy as np
        tile=cv2.cvtColor(f.image[725:900,0:250],cv2.COLOR_BGR2HSV)
        blue=(tile[:,:,0]>=85)&(tile[:,:,0]<=115)&(tile[:,:,1]>70)&(tile[:,:,2]>100)
        boss=_unique(f,'倪尔伽',(350,0,650,40),.98)
        wave=_unique(f,r'[xX×※]?\s*1\s*/\s*1',(155,0,310,70),.75)
        levels=[w for w in f.words if re.fullmatch(r'[1-9]\d?',w['text']) and w['score']>=.98 and 100<w['x']<600 and 150<w['y']<600]
        if boss and wave and len(levels)>=2 and np.count_nonzero(blue)>1500:
            target=dict(x=115,y=825,text='当前通过标签更换英雄教学圆圈内TAG控件（不点技能/魂燃）',score=1.)
            return dict(rule='guided_tag_swap',label='按当前强制TAG教学免费更换故事英雄',target=target,proof=[tag_guide,tag,boss,wave,*levels,target])
    restore=restore_offensive_basic_plan(f)
    if restore:return restore
    combat=manual_combat_plan(f)
    if combat:return combat
    heading=_unique(f,'致亲爱的继承者',(450,130,850,230),.98)
    introduction=next((w for w in f.words if '迎接继承者的日子' in w['text'] and w['score']>=.98 and 450<w['x']<1150 and 220<w['y']<310),None)
    journey=_unique(f,'现在[，,]是时候开启新的旅程了[。.]?',(450,420,1000,500),.95)
    close=_unique(f,r'[×xX]?\s*轻触后关闭',(650,830,950,895),.90)
    if all((heading,introduction,journey,close)):
        import cv2,numpy as np
        # Observed welcome-letter stamp, not a generic reward/bright-region tap.
        hsv=cv2.cvtColor(f.image[525:558,738:774],cv2.COLOR_BGR2HSV)
        badge=(hsv[:,:,0]<30)&(hsv[:,:,1]>170)&(hsv[:,:,2]>150)
        stamp=f.image[525:655,735:865]
        rim=np.mean(np.all(stamp>165,axis=2))
        if 40<=np.count_nonzero(badge)<=500 and .10<rim<.8:
            gift=dict(x=800,y=590,text='欢迎信内带通知点的免费礼盒',score=1.0)
            return dict(rule='welcome_gift',label='打开新号欢迎信内免费礼盒',target=gift,
                        proof=[heading,introduction,journey,close])
        return dict(rule='welcome_letter',label='关闭新号欢迎信（不点击礼盒）',target=close,
                    proof=[heading,introduction,journey,close])
    return None


def free_victoria_acquisition_plan(f):
    """Observed post-clear FREE hero display, not a summon/purchase action."""
    hero=_unique(f,'维多丽卡',(25,65,310,145),.98)
    fire=_unique(f,'火焰属性',(40,15,190,85),.98)
    knight=_unique(f,'骑士',(190,15,285,85),.98)
    zodiac=_unique(f,'狮子座',(285,15,405,85),.98)
    detail=_unique(f,'详细信息',(80,210,310,285),.98)
    confirm=_unique(f,'确认',(1250,780,1550,875),.98)
    second=_unique(f,'内心住着暴徒的贵族大小姐',(25,165,365,215),.98)
    if not all((hero,fire,knight,zodiac,detail,confirm,second)):return None
    dialogue=_unique(f,'绝不容忍任何不公，要时刻坚守正义与信念。',(400,715,1200,785),.98)
    if dialogue:
        speaker=_unique(f,'维多丽卡',(650,630,950,705),.98)
        if speaker:return dict(rule='free_victoria_acquisition_dialogue',label='继续已免费获得维多丽卡展示对白（不点暗色确认）',target=dialogue,proof=[hero,fire,knight,zodiac,detail,second,speaker,dialogue,confirm])
        return None
    import cv2,numpy as np
    hsv=cv2.cvtColor(f.image[795:860,1280:1550],cv2.COLOR_BGR2HSV)
    green=(hsv[:,:,0]>=10)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>50)&(hsv[:,:,2]>45)
    if np.count_nonzero(green)<3000:return None
    return dict(rule='free_victoria_acquisition_confirm',label='确认已免费获得的教学维多丽卡（非抽卡/购买）',target=confirm,proof=[hero,fire,knight,zodiac,detail,second,confirm])


def selected_hero_position_plan(f):
    """The explicit purple/gold position-plus shown AFTER an owned card pick."""
    import cv2,numpy as np
    header=_unique(f,'准备战斗',(60,10,260,80),.98)
    sort=_unique(f,'等级',(1250,80,1400,155),.98)
    search=_unique(f,'搜索',(1440,80,1599,155),.98)
    hero=_unique(f,'不成熟的维多丽卡|维多丽卡',(1260,280,1530,350),.98)
    if not all((header,sort,search,hero)) or owned_hero_placement_verified(f):return None
    for x1,y1,x2,y2 in ((650,395,750,490),(328,407,428,502),(505,487,605,582)):
        hsv=cv2.cvtColor(f.image[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        purple=(hsv[:,:,0]>=125)&(hsv[:,:,0]<=165)&(hsv[:,:,1]>90)&(hsv[:,:,2]>40)
        gold=np.uint8((hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>110)&(hsv[:,:,2]>170))*255
        if np.count_nonzero(purple)<2000:continue
        contours,_=cv2.findContours(gold,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        matches=[c for c in contours if 450<cv2.contourArea(c)<1600 and .7<cv2.boundingRect(c)[2]/cv2.boundingRect(c)[3]<1.4]
        if len(matches)!=1:continue
        moments=cv2.moments(matches[0]);x=x1+moments['m10']/moments['m00'];y=y1+moments['m01']/moments['m00']
        target=dict(x=x,y=y,text='本帧选定英雄后出现的紫色圆形底/金色双臂配置加号',score=1.0)
        return dict(rule='place_selected_owned_hero',label='点击当前紫色配置加号，将选定的已拥有英雄放入空位',target=target,proof=[header,sort,search,hero,target])
    return None


def owned_hero_selector_visible(f):
    """Detection-only veto, including partial OCR; never authorizes placement."""
    header=f.find(r'^准备战斗$',(60,10,260,80))
    markers=[f.find(pattern,region) for pattern,region in (
        (r'^等级$',(1250,80,1400,155)),(r'^搜索$',(1440,80,1599,155)),
        (r'^(不成熟的维多丽卡|维多丽卡)$',(1260,280,1530,350)),
        (r'^已配置的英雄$',(650,800,950,880)),
        (r'.*需要配置英雄的位子.*',(250,150,1100,800)))]
    return bool(header and header['score']>=.90 and any(w and w['score']>=.80 for w in markers))


def owned_hero_placement_verified(f):
    """Full current card/placed label, live unit HP and its occupied slot.

    The owned Victoria can be immature or the awarded heir, and story slots
    move across chapters. Never infer placement from red costume pixels alone.
    """
    import cv2,numpy as np
    if f.find('需要配置英雄的位子'):return False
    fields=[_unique(f,pattern,region,.98) for pattern,region in (
        ('准备战斗',(60,10,260,80)),('等级',(1250,80,1400,155)),
        ('搜索',(1440,80,1599,155)),('不成熟的维多丽卡|维多丽卡',(1260,280,1530,350)))]
    if not all(fields):return False
    placed_label=_unique(f,'已配置的英雄',(650,800,950,880),.98)
    card_level=_unique(f,r'[1-9]\d{0,2}',(1240,345,1400,400),.98)
    if not placed_label and not card_level:return False
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    for x,y in ((715,555),(375,562),(562,652)):
        levels=[w for w in f.words if re.fullmatch(r'[1-9]\d{0,2}',w['text']) and w['score']>=.98
                and x-80<=w['x']<=x+20 and y-340<=w['y']<=y-230]
        if len(levels)!=1 or (not placed_label and levels[0]['text']!=card_level['text']):continue
        lx,ly=round(levels[0]['x']),round(levels[0]['y'])
        hp=hsv[max(0,ly-15):ly+5,lx+15:min(1600,lx+95)]
        green=np.uint8((hp[:,:,0]>=30)&(hp[:,:,0]<=85)&(hp[:,:,1]>90)&(hp[:,:,2]>90))*255
        contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        live=any(cv2.boundingRect(c)[0]<=5 and cv2.boundingRect(c)[2]>=55 and cv2.boundingRect(c)[3]>=4 for c in contours)
        body=hsv[y-265:y,x-75:x+75]
        red=((body[:,:,0]<12)|(body[:,:,0]>170))&(body[:,:,1]>100)&(body[:,:,2]>100)
        rim=hsv[y-65:y+70,x-140:x+145]
        blue=(rim[:,:,0]>=85)&(rim[:,:,0]<=120)&(rim[:,:,1]>90)&(rim[:,:,2]>130)
        if live and np.count_nonzero(red)>=1000 and np.count_nonzero(blue)>=300:return True
    return False


def owned_hero_assignment_plan(f):
    """Current owned Victoria card plus in the observed team selector only."""
    import cv2,numpy as np
    header=_unique(f,'准备战斗',(60,10,260,80),.98)
    sort=_unique(f,'等级',(1250,80,1400,155),.98)
    search=_unique(f,'搜索',(1440,80,1599,155),.98)
    hero=_unique(f,'不成熟的维多丽卡|维多丽卡',(1260,280,1530,350),.98)
    if (not all((header,sort,search,hero)) or owned_hero_placement_verified(f)
        or f.find('登场的敌人',(1150,300,1550,430))):return None
    hsv=cv2.cvtColor(f.image[315:385,1160:1235],cv2.COLOR_BGR2HSV)
    gold=(hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>110)&(hsv[:,:,2]>170)
    blue=(hsv[:,:,0]>=90)&(hsv[:,:,0]<=130)&(hsv[:,:,1]>70)&(hsv[:,:,2]>80)
    if np.count_nonzero(blue)<500:return None
    contours,_=cv2.findContours(np.uint8(gold)*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    plus=[c for c in contours if 250<cv2.contourArea(c)<1600 and 20<=cv2.boundingRect(c)[2]<=65 and 20<=cv2.boundingRect(c)[3]<=65 and .7<cv2.boundingRect(c)[2]/cv2.boundingRect(c)[3]<1.4]
    if len(plus)!=1:return None  # a horizontal remove/minus is never an add.
    moments=cv2.moments(plus[0]);x=1160+moments['m10']/moments['m00'];y=315+moments['m01']/moments['m00']
    target=dict(x=x,y=y,text='本帧已拥有维多丽卡卡片左侧配置双臂加号（非移除减号）',score=1.0)
    return dict(rule='assign_owned_victoria',hero=hero['text'],label='将已拥有的'+hero['text']+'配置到已选择空位',target=target,
                proof=[header,sort,search,hero,target])


def _guided_slot_candidates(f, detection_only=False):
    """Empty gold/blue platform; neighbouring thin blue rims are not a unit."""
    import cv2,numpy as np
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV);candidates=[]
    for x,y in ((715,555),(375,562),(562,652)):
        border=hsv[y-65:y+70,x-140:x+145]
        gold=(border[:,:,0]>=15)&(border[:,:,0]<=40)&(border[:,:,1]>60)&(border[:,:,2]>200)
        blue=(border[:,:,0]>=85)&(border[:,:,0]<=115)&(border[:,:,1]>90)&(border[:,:,2]>150)
        core=hsv[y-15:y+15,x-30:x+30]
        if np.count_nonzero(gold)<2500 or np.count_nonzero(blue)<150 or np.mean(core[:,:,2]<110)<.8:continue
        if not detection_only:
            column=hsv[y-285:y-75,x-55:x+55]
            bright=(column[:,:,2]>150)&(column[:,:,1]>60)
            blue_column=(column[:,:,0]>=85)&(column[:,:,0]<=115)&(column[:,:,1]>90)&(column[:,:,2]>150)
            _,_,stats,_=cv2.connectedComponentsWithStats(np.uint8(blue_column)*255)
            # Preserve blue costumes as occupancy. Only disjoint small rim
            # components are discounted; red/other bodies keep the old bound.
            blue_body=any(area>1000 and h>60 and w>30 for _,_,w,h,area in stats[1:])
            if blue_body or np.count_nonzero(bright&~blue_column)>1000:continue
        candidates.append((x,y))
    return candidates


def guided_team_slot_visible(f):
    """Detection-only entry veto; incomplete occupancy can never authorize a tap."""
    return bool(_guided_slot_candidates(f,detection_only=True))


def guided_team_slot_plan(f):
    """Current owned-hero gold-highlighted empty slot, not auto equipment."""
    from story_core import _team_entry_layout
    control=_team_entry_layout(f)
    if control['kind']!='single_task' or '故事固定队伍' not in control['proof']:return None
    heading=_unique(f,'准备战斗',(60,10,260,80),.98)
    manage=_unique(f,'管理队伍',(25,815,200,899),.98)
    stage=[w for w in f.words if w['score']>=.90 and 1140<w['x']<1510 and 140<w['y']<195]
    if not heading or not manage or len(stage)!=1:return None
    candidates=_guided_slot_candidates(f)
    if len(candidates)!=1:return None
    x,y=candidates[0]
    target=dict(x=x,y=y,text='当前教学金色/蓝色边框且中心为空的可配置队伍槽',score=1.0)
    return dict(rule='guided_owned_hero_slot',label='打开教学高亮空位以配置新号已获英雄（不消耗英雄）',target=target,
                proof=[heading,manage,stage[0],target])


def chapter_reward_layout(f):
    stars=_unique(f,r'\d{1,3}/\d{1,3}',(20,750,110,795),.98)
    if not stars:return None
    count,total=map(int,stars['text'].split('/'))
    if not 0<=count<=total<=999:return None
    labels=[_unique(f,r'[1-9]\d{0,2}',bounds,.98) for bounds in ((185,750,225,795),(305,750,342,795),(431,750,465,795))]
    if all(labels):
        tiers=[int(w['text']) for w in labels]
        if not 0<tiers[0]<tiers[1]<tiers[2]==total:return None
    elif total==9 and not any(labels):tiers=[3,6,9]  # original independently accepted nine-star layout
    else:return None
    return dict(count=count,total=total,stars=stars,tiers=tiers,labels=[w for w in labels if w])


def chapter_reward_pending(f):
    """Detection-only veto: a reward badge cannot fall through to stage entry."""
    import cv2,numpy as np
    header=_unique(f,r'(?:Episode\s*\d+|第\s*\d+\s*时代\s*Episode)',(50,0,430,90),.90)
    from map_identity import chapter_header
    _,chapter=chapter_header(f)
    action=_unique(f,r'观看故事|观看剧情|准备战斗',(1250,780,1550,870),.90)
    layout=chapter_reward_layout(f)
    complete_layout=bool(layout and len(layout['labels'])==3)
    if not action or not (complete_layout or (header and chapter)):return None
    tiers=layout['tiers'] if layout else (3,6,9)  # fallback detects only; cannot authorize a claim
    for needed,dot_x,card_x in zip(tiers,(158,282,407),(187,311,436)):
        tile=cv2.cvtColor(f.image[782:804,dot_x-11:dot_x+12],cv2.COLOR_BGR2HSV)
        mask=np.uint8((tile[:,:,0]<30)&(tile[:,:,1]>180)&(tile[:,:,2]>150))*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        matches=[]
        for contour in contours:
            area=cv2.contourArea(contour);perimeter=cv2.arcLength(contour,True)
            (x,y),radius=cv2.minEnclosingCircle(contour)
            if 35<=area<=180 and 4<=radius<=9 and abs(x-11)<=3 and abs(y-11)<=3 and perimeter and 4*np.pi*area/perimeter**2>.55:
                matches.append(contour)
        if len(matches)==1:
            return dict(needed=needed,dot_x=dot_x,card_x=card_x,header=header,chapter=chapter,action=action)
    return None


def chapter_star_reward_plan(f):
    """Layout-based free map milestone; titles are optional context, never entry authority."""
    pending=chapter_reward_pending(f)
    if not pending:return None
    header=pending['header'];chapter=pending['chapter']
    layout=chapter_reward_layout(f)
    if not layout:return None
    if any(re.fullmatch(r'确认|确定|確認|確定|取消|OK|点击关闭|點擊關閉',w['text'].strip()) for w in f.words):return None
    context=[w for w in (header,chapter) if w]
    if len(layout['labels'])!=3 and (len(context)!=2 or min(w['score'] for w in context)<.98):return None
    stars=layout['stars'];needed=pending['needed']
    if not needed<=layout['count']<=layout['total']:return None
    marker=dict(text=str(needed)+'星奖励卡片通知圆点（免费领取，不是入场）',score=1.0,x=pending['dot_x'],y=793)
    target=dict(x=pending['card_x'],y=828,text=str(needed)+'星免费章节奖励卡片',score=1.0)
    return dict(rule='chapter_star_reward',label='领取已达成的免费章节星星奖励（不入场）',target=target,
                proof=[stars,marker,*layout['labels'],*context])


def restore_offensive_basic_plan(f):
    """Iseria S2 ally-target mode: select S1, never tap a numbered ally."""
    import cv2,numpy as np
    hero=_unique(f,'伊赛丽亚',(260,770,560,835),.98)
    hp=_unique(f,r'\d{1,6}/\d{1,6}',(300,835,580,890),.98)
    wave=_unique(f,r'[xX×※]?\s*[1-9]\s*/\s*[1-9]',(155,0,310,70),.75)
    if not all((hero,hp,wave)):return None
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    glow=hsv[735:780,1335:1470]
    bright=np.count_nonzero((glow[:,:,1]<120)&(glow[:,:,2]>220))
    gold=np.count_nonzero((glow[:,:,0]>=15)&(glow[:,:,0]<=40)&(glow[:,:,1]>60)&(glow[:,:,2]>200))
    if bright<700 or gold<500 or np.std(f.image[780:880,1230:1320])<25:return None
    allies=[]
    for w in f.words:
        if not re.fullmatch(r'[1-3]',w['text']) or w['score']<.98 or not (250<w['x']<600 and 150<w['y']<600):continue
        x,y=round(w['x']),round(w['y']);tile=hsv[y-24:y+24,x-25:x+25]
        red=((tile[:,:,0]<12)|(tile[:,:,0]>170))&(tile[:,:,1]>150)&(tile[:,:,2]>110)
        if np.count_nonzero(red)>500:allies.append(w)
    if len(allies)<2:
        # A shield digit can merge with the adjacent hero level in full OCR.
        # Count only the observed red pentagon + adjacent green level/HP,
        # retaining at least one independently read 1..3 in this ally region.
        if not allies:return None
        region=hsv[150:600,250:600]
        mask=np.uint8(((region[:,:,0]<12)|(region[:,:,0]>170))&(region[:,:,1]>150)&(region[:,:,2]>110))*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        shields=[]
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if not (30<=w<=55 and 30<=h<=55 and 500<=cv2.contourArea(contour)<=1800):continue
            adjacent=hsv[y+150:y+150+h,x+250+w:x+250+w+120]
            green=(adjacent[:,:,0]>=30)&(adjacent[:,:,0]<=85)&(adjacent[:,:,1]>90)&(adjacent[:,:,2]>90)
            if np.count_nonzero(green)<250:continue
            shields.append(dict(x=x+250+w/2,y=y+150+h/2,text='当前友方红编号盾轮廓和相邻绿色等级/HP',score=1.))
        if len(shields)<2:return None
        allies+=shields
    target=dict(x=1275,y=825,text='当前伊赛丽亚第二技能选友方模式，切回已核实的第一基础技能',score=1.)
    return dict(rule='restore_offensive_basic',label='取消已识别的友方技能选取，单次切回第一基础攻击',target=target,proof=[hero,hp,wave,*allies])


def manual_combat_plan(f):
    """Observed Krau story-team basic attack only; no skills with soul/resource cost."""
    import cv2,numpy as np
    if any(w['score']>=.8 and 250<w['x']<1350 and 100<w['y']<740 and re.search(r'点击|轻触|请选择|请使用|拖动|按住',w['text']) for w in f.words):return None
    hero=_unique(f,r'[\u4e00-\u9fff·]{2,16}',(260,770,560,835),.98)
    actor_proof=[]
    if not hero:
        role=_unique(f,'护卫队长克劳乌',(260,770,560,835),.95)
        suffix=_unique(f,'克劳乌',(410,785,520,835),.98)
        if role and suffix and suffix.get('source') in ('current_fixed_actor_suffix_field_read','current_fixed_actor_suffix_dual_read'):
            hero=role;actor_proof=[suffix]
    health=_unique(f,r'\d{1,6}/\d{1,6}',(300,835,580,865),.98)
    wave=_unique(f,r'[xX×※]?\s*[1-9]\s*/\s*[1-9]',(155,0,310,70),.75)
    if not all((hero,health,wave)):return None
    current,total=map(int,re.search(r'(\d+)\s*/\s*(\d+)',wave['text']).groups())
    wave=dict(wave,observed_text=wave['text'],text=str(current)+'/'+str(total))
    if not 1<=current<=total<=3:return None
    hp,maximum=map(int,health['text'].split('/'))
    if not 0<hp<=maximum:return None
    hsv=cv2.cvtColor(f.image,cv2.COLOR_BGR2HSV)
    glow=hsv[735:775,1200:1345]
    bright=int(np.count_nonzero((glow[:,:,1]<120)&(glow[:,:,2]>220)))
    gold=int(np.count_nonzero((glow[:,:,0]>=15)&(glow[:,:,0]<=40)&(glow[:,:,1]>60)&(glow[:,:,2]>200)))
    if bright<900 or gold<700:return None
    icons=(1230,1360)  # S1/S2 HUD anchors; S3 can be absent/passive in story teams.
    if any(np.std(f.image[780:880,x:x+90])<25 for x in icons):return None
    enemies=[]
    for word in f.words:
        if not re.fullmatch(r'\d{1,2}',word['text']) or word['score']<.98 or not (970<word['x']<1500 and 180<word['y']<670):continue
        x,y=round(word['x']),round(word['y'])
        shield=hsv[max(0,y-24):y+24,x-70:x-15]
        red=((shield[:,:,0]<12)|(shield[:,:,0]>170))&(shield[:,:,1]>150)&(shield[:,:,2]>110)
        bar=hsv[y-13:y+3,x+15:min(1599,x+90)]
        green=(((bar[:,:,0]>=30)&(bar[:,:,0]<=85))|(bar[:,:,0]<12)|(bar[:,:,0]>170))&(bar[:,:,1]>90)&(bar[:,:,2]>90)
        red_count=int(np.count_nonzero(red));green_count=int(np.count_nonzero(green))
        components,_=cv2.findContours(np.uint8(green)*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        live_bar=any(cv2.contourArea(component)>=12 and cv2.boundingRect(component)[0]<=6
                     and cv2.boundingRect(component)[2]>=3 and cv2.boundingRect(component)[3]>=3 for component in components)
        if red_count>=400 and live_bar:
            enemies.append((word,green_count))
    if not enemies:
        boss=_unique(f,'噩梦看守者|佣兵丽蒂亚|佣兵雨果|佣兵艾隆|噬魂者阿格扎克斯|绿地托特思|紫苔那伽|倪尔伽|卡洛斯暗黑君主',(350,0,650,40),.95)
        level=_unique(f,r'Lv[.．]?\s*10',(940,0,1050,40),.95)
        bar=hsv[45:73,370:1040]
        life=(((bar[:,:,0]>=30)&(bar[:,:,0]<=85))|(bar[:,:,0]<12)|(bar[:,:,0]>170))&(bar[:,:,1]>90)&(bar[:,:,2]>90)
        body=hsv[260:710,1230:1590]
        red=((body[:,:,0]<12)|(body[:,:,0]>170))&(body[:,:,1]>150)&(body[:,:,2]>90)
        mercenary=hsv[415:690,1185:1335]
        clothing=(mercenary[:,:,1]<100)&(mercenary[:,:,2]>135)
        beast=hsv[400:710,940:1370]
        blue=(beast[:,:,0]>=90)&(beast[:,:,0]<=130)&(beast[:,:,1]>50)&(beast[:,:,2]>35)
        stone=hsv[300:710,940:1590]
        stone_light=(stone[:,:,1]<100)&(stone[:,:,2]>90)
        stone_green=(stone[:,:,0]>=30)&(stone[:,:,0]<=85)&(stone[:,:,1]>70)&(stone[:,:,2]>70)
        stone_purple=(stone[:,:,0]>=125)&(stone[:,:,0]<=165)&(stone[:,:,1]>20)&(stone[:,:,2]>30)
        orange=(stone[:,:,0]>=5)&(stone[:,:,0]<=30)&(stone[:,:,1]>150)&(stone[:,:,2]>80)
        purple_body=hsv[300:710,1160:1580]
        purple=(purple_body[:,:,0]>=125)&(purple_body[:,:,0]<=165)&(purple_body[:,:,1]>70)&(purple_body[:,:,2]>30)
        naga_green=(purple_body[:,:,0]>=30)&(purple_body[:,:,0]<=85)&(purple_body[:,:,1]>50)&(purple_body[:,:,2]>40)
        plant=plant_enemy_body(f,dict(x=1115,y=400)) if boss and boss['text']=='绿地托特思' else None
        body_verified=bool(boss and ((np.count_nonzero(stone_light)>10000 and np.count_nonzero(stone_purple)>1500 and np.count_nonzero(orange)>300) if boss['text']=='卡洛斯暗黑君主' else (np.count_nonzero(stone_light)>10000 and np.count_nonzero(stone_green)>3000 and np.count_nonzero(stone_purple)>3000) if boss['text']=='倪尔伽' else (np.count_nonzero(purple)>3000 and np.count_nonzero(naga_green)>1500) if boss['text']=='紫苔那伽' else plant is not None if boss['text']=='绿地托特思' else np.count_nonzero(red)>3000 if boss['text']=='噩梦看守者' else
                          np.count_nonzero(blue)>3000 if boss['text']=='噬魂者阿格扎克斯' else np.count_nonzero(clothing)>600))
        life_components,_=cv2.findContours(np.uint8(life)*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        live_boss=any(cv2.contourArea(c)>=12 and cv2.boundingRect(c)[0]<=45 and cv2.boundingRect(c)[2]>=3 and cv2.boundingRect(c)[3]>=3 for c in life_components)
        if boss and level and live_boss and body_verified:
            enemy=boss;count=int(np.count_nonzero(life))
            target=plant or dict(x=1420 if boss['text']=='卡洛斯暗黑君主' else 1240 if boss['text']=='倪尔伽' else 1420 if boss['text']=='紫苔那伽' else 1400 if boss['text']=='噩梦看守者' else 1150 if boss['text']=='噬魂者阿格扎克斯' else 1250,y=550 if boss['text']=='噬魂者阿格扎克斯' else 510,text='已核验'+boss['text']+'标题、独立BossHP条与当前敌方本体',score=boss['score'])
            readiness=dict(text='第一基础技能可用发光边框；BossHP格量'+str(count//400),score=1.0,x=1270,y=820)
            return dict(rule='krau_story_basic',label='故事队伍手操：默认基础技能攻击已核验'+boss['text'],target=target,
                        proof=[hero,health,wave,boss,level,readiness],additional_proof=actor_proof)
    if not 1<=len(enemies)<=3:return None
    enemies.sort(key=lambda item:item[0]['x']);enemy,count=enemies[0]
    target=plant_enemy_body(f,enemy) or dict(x=enemy['x']+35,y=min(710,enemy['y']+150),text='已核验红色敌方编号盾与存活HP条下方的首个敌人躯干区',score=enemy['score'])
    readiness=dict(text='第一基础技能可用发光边框；敌方HP格量'+str(count//40),score=1.0,x=1270,y=820)
    return dict(rule='krau_story_basic',label='故事队伍手操：'+hero['text']+'基础技能攻击当前存活敌人',target=target,
                proof=[hero,health,wave,enemy,readiness],additional_proof=actor_proof)


def plant_enemy_body(f,enemy):
    """Observed small forest plant: living HUD plus leafy crown AND brown body.

    Its HP is suspended far above the hittable trunk. Never use a guessed
    HP+80 offset when the current trunk/crown geometry can be verified.
    """
    import cv2,numpy as np
    x,y=round(enemy['x']),round(enemy['y'])
    if not (970<x<1450 and 180<y<600):return None
    top=y+65;left=x-35
    tile=cv2.cvtColor(f.image[top:min(850,y+270),left:min(1599,x+120)],cv2.COLOR_BGR2HSV)
    brown=np.uint8((tile[:,:,0]>=8)&(tile[:,:,0]<=35)&(tile[:,:,1]>80)&(tile[:,:,2]>25)&(tile[:,:,2]<180))*255
    n,labels,stats,centers=cv2.connectedComponentsWithStats(brown)
    matches=[(stat,center) for stat,center in zip(stats[1:],centers[1:])
             if 1500<=stat[4]<=8000 and 45<=stat[2]<=110 and 45<=stat[3]<=125 and stat[1]>=60 and .5<=stat[2]/stat[3]<=1.5]
    if len(matches)!=1:return None
    stat,center=matches[0]
    crown=tile[:min(110,int(stat[1])+20)]
    green=(crown[:,:,0]>=30)&(crown[:,:,0]<=85)&(crown[:,:,1]>70)&(crown[:,:,2]>65)
    if np.count_nonzero(green)<1200:return None
    target_y=float(top+center[1])
    if target_y>710:return None  # NEVER intersect the bottom skill bar.
    return dict(x=float(left+center[0]),y=target_y,score=1.,source='current_forest_plant_crown_and_trunk',
                text='已核实存活编号敌人的绿色树冠和独立棕色躯干；点击本帧躯干质心')


class TutorialController:
    """One current recognized target and durable once-only tutorial dispatch journal."""
    def __init__(self,runner):
        self.r=runner;self.pending=None

    def _release_combat(self,ledger,reason):
        index=ledger.get('combat_latch')
        if index is None:return
        record=ledger['actions'][index]
        if record.get('status')!='sent':return
        record['turn_transition']=dict(at=time.time(),reason=reason,evidence=self.r.evidence('tutorial-turn-transition'))
        ledger.pop('combat_latch',None)
        ledger['page']='combat-transition:'+str(time.time_ns())
        ledger['epoch']=ledger.get('epoch',0)+1
        self.pending=None

    def observe_scene(self,scene,f=None):
        # Only independently recognized pages break same-page suppression.
        # Unknown/loading/missing OCR and a restart never do.
        ledger=self.r.s.setdefault('tutorial',{'actions':[]})
        if scene=='battle' and f is not None and ledger.get('combat_latch') is not None:
            import numpy as np
            slot=f.image[775:895,1210:1340]
            if float(slot.mean())<45 and np.count_nonzero(np.max(slot,axis=2)>160)<35:
                self._release_combat(ledger,'已识别战斗HUD中基础技能按钮完整消失，非光效闪烁')
        if scene not in ('map','lobby','team','support','story','settlement','legacy_story_map','legacy_story_regions'):
            return
        self._release_combat(ledger,'独立识别的非战斗流程页 '+scene)
        ledger=self.r.s.setdefault('tutorial',{'actions':[]})
        key='scene:'+scene
        if ledger.get('page')!=key:
            ledger['page']=key;ledger['epoch']=ledger.get('epoch',0)+1

    def placement_confirmed(self,f):
        """One current positively identified placement; no extra matching frame."""
        return bool(owned_hero_placement_verified(f) and 0<=time.time()-f.at<=3)

    def _setup_gate(self,plan):
        setup=self.r.s.get('team_config') or {}
        rule=plan['rule']
        context=self.r.s.get('active') or self.r.ticket or {}
        live=[row for row in self.r.s.get('tutorial_entry_handoffs',[]) if row.get('key')==context.get('key') and row.get('status')=='configuring']
        if live and len(live)==1 and (not self.r.ticket):
            from tutorial_entry_handoff import source_chain
            from story_reopen import state_digest
            if state_digest(source_chain(self.r.s,context['key']))!=live[0]['source_chain_sha256']:
                return self.r.attention('team_setup','配置来源发生变化','保留原记录，未重开或配置。')
            self.r.ticket=dict(live[0]['map_ticket'],verified_epoch=time.time())
        def pending():
            prior=setup.get('dispatches',{}).get(rule)
            if prior and prior.get('status')!='sent':
                return self.r.attention('team_setup','教学配置发送结果不明','原配置意图已保留；未发送/发送不明均不自动重发。')
            if prior and time.time()-setup.get('at',0)<12:
                self.r.s['reason']='配置动作已发送，等待独立新结果；页面/OCR切换不解除同链防重复'
                self.r.save();return True,.25
            return self.r.attention('team_setup','教学配置步骤已发送','原配置链保留；页面切换和重载不能解除防重复。')
        if rule=='guided_owned_hero_slot':
            ticket=self.r.ticket or {}
            if not ticket.get('key') or ticket.get('phase') not in ('map','support') or time.time()-ticket.get('verified_epoch',0)>120:
                return self.r.attention('team_setup','教学配置缺少当前关验证','没有完整当前地图链，不打开队伍空位。')
            titles=[w for w in plan['proof'] if 1140<w.get('x',0)<1510 and 140<w.get('y',0)<195]
            if len(titles)!=1 or titles[0]['text']!=ticket.get('name'):
                return self.r.attention('team_setup','当前关标题不符','免费配置仍须当前完整关名与原地图链全字相同，不猜测关卡。')
            if self.r.s.get('active') and not live:
                return self.r.attention('team_setup','原入场结果尚待核实','已有入场链，不通过重新配置绕过原入场保护。')
            if setup.get('stage_key')==ticket['key'] or setup.get('phase') in ('await_selector','await_position','await_confirmation'):
                return pending()
            return None
        if not setup.get('id') or not setup.get('stage_key') or context.get('key')!=setup['stage_key']:
            return self.r.attention('team_setup','教学配置链等待核实','缺少当前空位/英雄选择的持久链或目标不符，不泛点或重发配置动作。')
        prior=setup.get('dispatches',{}).get(rule)
        if prior:return pending()
        expected='await_selector' if rule=='assign_owned_victoria' else 'await_position'
        source_rule='guided_owned_hero_slot' if rule=='assign_owned_victoria' else 'assign_owned_victoria'
        source=setup.get('dispatches',{}).get(source_rule,{})
        if setup.get('phase')!=expected or source.get('status')!='sent':
            return self.r.attention('team_setup','教学配置链等待核实','前一步未独立发送或步骤不符，未发送配置输入。')
        return None

    def step(self,f):
        plan=tutorial_plan(f)
        if plan is None:
            self.pending=None;return None
        if plan['rule'].startswith('free_victoria_acquisition_'):
            last=self.r.s.get('last_cleared') or {};key=last.get('key')
            tutorials=self.r.s.get('tutorial',{}).get('actions',[])
            sources=[a for a in tutorials if a.get('rule')=='heir_victoria_new_skill' and a.get('status')=='sent'
                     and a.get('at',0)>=last.get('start_epoch',float('inf'))]
            if (self.r.s.get('active') or not key or key not in self.r.s.get('completed',{}) or len(sources)!=1):
                return self.r.attention('tutorial_acquisition','英雄展示来源尚未核实','缺少原教学技能与独立结算链，不把未知确认当作免费获得英雄。')
        setup_action=plan['rule'] in ('guided_owned_hero_slot','assign_owned_victoria','place_selected_owned_hero')
        if setup_action:
            result=self._setup_gate(plan)
            if result is not None:self.pending=None;return result
        power_warning_source=None
        if plan['rule']=='first_entry_power_warning':
            key=(self.r.s.get('active') or {}).get('key')
            if key in self.r.s.get('entry_confirmations',{}):self.pending=None;return True,.25
            from tutorial_battle_confirmation import confirmation_source
            from runner import ROOT
            try:power_warning_source=confirmation_source(self.r.s,ROOT/'events.jsonl')
            except ValueError as exc:return self.r.attention('entry_confirmation','原入场确认来源未核实',str(exc))
        auto_configuration_source=None
        if plan['rule']=='free_team_auto_configuration':
            context=self.r.s.get('verified') or {};key=context.get('key')
            if (not key or key!=self.r.s.get('last_stage') or context.get('phase')!='map'
                or context.get('proof')!='未通关蓝色当前节点' or not context.get('evidence')
                or context.get('locked') or context.get('clear_badge') or self.r.s.get('active')
                or key in self.r.s.get('attempted',{}) or key in self.r.s.get('completed',{})):
                return self.r.attention('tutorial_team','免费配置来源未核实','不能从配置弹窗创建入场或解除旧入场保护。')
            auto_configuration_source=context
            rows=self.r.s.get('tutorial',{}).get('auto_configurations',{})
            if key in rows:self.pending=None;return True,.25
        summon_source=None
        summon_link=None
        if plan['rule'] in ('guided_free_covenant_tab','guided_free_covenant_draw','guided_free_covenant_wishlist','guided_free_covenant_recommend','guided_free_covenant_confirm_recommend','guided_free_covenant_close_wishlist','guided_free_covenant_draw_after_wishlist','guided_free_covenant_return','guided_free_covenant_episode'):
            sources=[a for a in self.r.s.get('tutorial',{}).get('actions',[]) if a.get('rule')=='guided_free_covenant_menu' and a.get('status')=='sent']
            if len(sources)!=1:return self.r.attention('tutorial_summon','免费教学召唤来源未核实','未通过0/1教学入口，不点击召唤标签。')
            summon_source=sources[0]
            summon_link={'guided_free_covenant_tab':'tab_selection','guided_free_covenant_draw':'free_draw','guided_free_covenant_wishlist':'wishlist_open','guided_free_covenant_recommend':'wishlist_recommend','guided_free_covenant_confirm_recommend':'wishlist_confirm','guided_free_covenant_close_wishlist':'wishlist_close','guided_free_covenant_draw_after_wishlist':'free_draw_after_wishlist','guided_free_covenant_return':'return_navigation','guided_free_covenant_episode':'episode_navigation'}[plan['rule']]
            if summon_link=='free_draw' and (summon_source.get('tab_selection') or {}).get('status')!='sent':
                return self.r.attention('tutorial_summon','免费召唤标签未核实','未完成当前免费标签导航，不抽取。')
            if summon_link=='wishlist_open' and (summon_source.get('free_draw') or {}).get('status')!='sent':
                self.pending=None;return None
            if summon_link=='free_draw_after_wishlist' and any((summon_source.get(k) or {}).get('status')!='sent' for k in ('tab_selection','free_draw','wishlist_open','wishlist_recommend','wishlist_confirm','wishlist_close')):
                return self.r.attention('tutorial_summon','免费配置接续来源不完整','不把缺失愿望单/原免费链当作重复抽取许可。')
            if summon_link=='wishlist_close' and (summon_source.get('wishlist_confirm') or {}).get('status')!='sent':
                return self.r.attention('tutorial_summon','愿望单推荐结果来源未核实','不关闭未知配置或推断免费抽取完成。')
            if summon_link=='wishlist_confirm' and (summon_source.get('wishlist_recommend') or {}).get('status')!='sent':
                return self.r.attention('tutorial_summon','推荐确认来源未核实','不确认未知配置/付费弹窗。')
            if summon_link=='wishlist_recommend' and (summon_source.get('wishlist_open') or {}).get('status')!='sent':
                return self.r.attention('tutorial_summon','愿望单配置来源未核实','不凭未知配置页操作推荐或抽取。')
            if summon_link=='return_navigation':
                required=('tab_selection','free_draw','wishlist_open','wishlist_recommend','wishlist_confirm','wishlist_close','free_draw_after_wishlist')
                if self.r.s.get('active') or any((summon_source.get(k) or {}).get('status')!='sent' for k in required):
                    return self.r.attention('tutorial_summon','召唤返程来源未核实','只允许原免费链上的一次返回，不推断抽取成功或重试。')
            if summon_link=='episode_navigation' and ((summon_source.get('return_navigation') or {}).get('status')!='sent' or self.r.s.get('active')):
                return self.r.attention('tutorial_summon','主线返程来源未核实','保留原召唤和返程记录，不点任务奖励或未知菜单。')
            if summon_source.get(summon_link):self.pending=None;return True,.25
        skill_source=None
        skill_link=None
        if plan['rule'] in ('heir_victoria_new_skill_target','heir_victoria_new_skill_execute'):
            context=self.r.s.get('active') or {}
            sources=[a for a in self.r.s.get('tutorial',{}).get('actions',[]) if a.get('rule')=='heir_victoria_new_skill'
                     and a.get('status')=='sent' and a.get('at',0)>=context.get('start_epoch',float('inf'))]
            if len(sources)!=1:return self.r.attention('tutorial_skill','技能教学链尚未核实','缺少本次新技能已发送步骤，不点敌方或说明。')
            skill_source=sources[0]
            skill_link='enemy_selection' if plan['rule']=='heir_victoria_new_skill_target' else 'body_selection'
            if skill_link=='body_selection' and (skill_source.get('enemy_selection') or {}).get('status')!='sent':
                return self.r.attention('tutorial_skill','新技能说明关闭链尚未核实','保留原技能步骤；未泛点敌方。')
            if skill_source.get(skill_link):
                self.pending=None;return True,.25
        target=plan['target']
        identity=json.dumps([plan['rule'],[_text(w['text']) for w in plan['proof']],
                             [int(target['x']//80),int(target['y']//80)] if plan['rule']=='krau_story_basic' else None],ensure_ascii=False)
        signature=hashlib.sha256(identity.encode()).hexdigest()
        ledger=self.r.s.setdefault('tutorial',{'actions':[]})
        combat=plan['rule']=='krau_story_basic'
        latch=ledger.get('combat_latch')
        if combat and latch is not None:
            previous=ledger['actions'][latch]
            if previous.get('status')!='sent':
                return self.r.attention('tutorial_dispatch','基础攻击发送结果不明','原教学攻击意图保留，不能因OCR或目标变化再发。')
            previous_wave=re.fullmatch(r'([1-3])/([1-3])',previous.get('proof',[{}, {}, {}])[2].get('text',''))
            current_wave=re.fullmatch(r'([1-3])/([1-3])',plan['proof'][2]['text'])
            if (previous_wave and current_wave and previous_wave[2]==current_wave[2]
                and int(current_wave[1])==int(previous_wave[1])+1):
                stamp='wave-advance:'+plan['proof'][2]['text']
                if not 0<=time.time()-f.at<=3:self.pending=None;return True,.25
                self._release_combat(ledger,'当前波次明确向前推进，当前基础技能回合重新就绪')
            elif previous.get('actor')!=plan['proof'][0]['text']:
                self._release_combat(ledger,'独立核验下一位不同故事角色的基础技能回合')
            else:
                # An enemy-selection tap can land on decoration above a tall
                # enemy. Select the independently verified FIRST basic skill
                # once, not another enemy tap or an unlocked combat latch.
                follow=previous.get('basic_skill_selection')
                if (follow is None and time.time()-previous['at']>=8
                    and previous.get('proof') and len(previous['proof'])>=3
                    and [w['text'] for w in previous['proof'][:3]]==[w['text'] for w in plan['proof'][:3]]):
                    point=(1275,825)
                    if not 0<=time.time()-f.at<=3:self.pending=None;return True,.25
                    follow=dict(status='reserved',at=time.time(),evidence=self.r.evidence('tutorial-first-basic-control'),
                                target=dict(x=point[0],y=point[1],text='已核验发光第一基础技能按钮（非魂燃/神兽/其他技能）',score=1.),
                                proof=plan['proof'])
                    previous['basic_skill_selection']=follow;self.r.save()
                    self.r.action('同回合敌方选取未触发后，单次选择已核实第一基础技能',follow['target'])
                    follow['status']='sent';self.r.save();self.pending=None;return True,.25
                if (follow and follow.get('status')=='sent' and previous.get('corrected_enemy_selection') is None
                    and len(previous.get('proof',[]))>=4
                    and [w['text'] for w in previous['proof'][:3]]==[w['text'] for w in plan['proof'][:3]]
                    and ((plan['target'].get('source')=='current_forest_plant_crown_and_trunk'
                          and max(abs(previous['proof'][3][k]-plan['proof'][3][k]) for k in ('x','y'))<=8
                          and abs(previous['target']['y']-target['y'])>80)
                         or (previous['target']['y']>710 and 970<target['x']<1590 and 180<target['y']<=710))):
                    point=(target['x'],target['y'])
                    if not 0<=time.time()-f.at<=3:self.pending=None;return True,.25
                    correction=dict(status='reserved',at=time.time(),target=target,evidence=self.r.evidence('tutorial-plant-trunk-correction'),proof=plan['proof'])
                    previous['corrected_enemy_selection']=correction;self.r.save()
                    self.r.action('选择第一基础技能后，单次选取当前核实的敌方躯干（不重发旧错位目标）',target)
                    correction['status']='sent';self.r.save();self.pending=None;return True,.25
                self.pending=None
                self.r.s['reason']='本回合基础攻击已发送，等待技能按钮完整消失或独立下一位角色回合；OCR/血条光效变化不解锁'
                self.r.save();return True,.25
        if ledger.get('page')!=signature:
            ledger['page']=signature;ledger['epoch']=ledger.get('epoch',0)+1
        epoch=ledger['epoch']
        prior=[a for a in ledger['actions'] if a['signature']==signature and a.get('epoch',0)==epoch]
        if prior:
            if prior[-1]['status']=='sent' and time.time()-prior[-1]['at']<15:
                self.r.s.update(reason='教学操作已发送，等待独立新页面；不重复点击。');self.r.save();return True,.25
            return self.r.observe_progress_evidence('tutorial_response',dict(code='tutorial_response',reason='当前教学尚未显示结果，继续读取已知控件；发送记录不代表完成或失败，不盲目重复。'))
        point=(target['x'],target['y'])
        if time.time()-f.at>3:
            self.pending=None;return True,.25
        entry=dict(rule=plan['rule'],signature=signature,epoch=epoch,status='reserved',at=time.time(),
                   target=target,proof=plan['proof'],additional_proof=plan.get('additional_proof',[]),evidence=self.r.evidence('tutorial-'+plan['rule']))
        if setup_action:
            if plan['rule']=='guided_owned_hero_slot':
                old_setup=self.r.s.get('team_config')
                if old_setup:self.r.s.setdefault('team_config_history',[]).append(copy.deepcopy(old_setup))
                setup=dict(id=uuid.uuid4().hex,stage_key=self.r.ticket['key'],hero='不成熟的维多丽卡',
                           source_evidence=entry['evidence'],dispatches={})
                self.r.s['team_config']=setup
            else:setup=self.r.s['team_config']
            setup.update(phase={'guided_owned_hero_slot':'await_selector','assign_owned_victoria':'await_position',
                                'place_selected_owned_hero':'await_confirmation'}[plan['rule']],at=time.time())
            if plan['rule']=='assign_owned_victoria':setup['hero']=plan.get('hero','不成熟的维多丽卡')
            setup['dispatches'][plan['rule']]=entry
        if combat:entry['actor']=plan['proof'][0]['text']
        if power_warning_source is not None:
            entry['entry_source']=power_warning_source
            self.r.s.setdefault('entry_confirmations',{})[power_warning_source['key']]=entry
        if auto_configuration_source is not None:
            entry['stage_key']=auto_configuration_source['key']
            entry['map_source']=copy.deepcopy(auto_configuration_source)
            ledger.setdefault('auto_configurations',{})[entry['stage_key']]=entry
        if summon_source is not None:summon_source[summon_link]=entry
        if skill_source is not None:skill_source[skill_link]=entry
        ledger['actions'].append(entry)
        if combat:ledger['combat_latch']=len(ledger['actions'])-1
        self.r.save()  # critical, before any input
        self.r.action(plan['label'],target)
        entry['status']='sent';self.r.save();self.pending=None
        return True,.25
