"""A single exact, free team-configuration modal; no generic confirmation."""


def auto_configuration_plan(f,unique):
    anchors=[unique(f,p,region,.98) for p,region in (
        ('自动配置',(650,210,950,330)),
        ('新的队伍栏位尚未配置英雄[。.]?',(450,380,1150,442)),
        ('可自动配置高战斗力的英雄[。.]?',(450,435,1150,464)),
        ('是否进行配置[？?]',(600,465,1000,515)),
        ('取消',(500,565,790,665)),('确认',(810,565,1100,665)))]
    if not all(anchors):return None
    allowed={w['text'] for w in anchors}
    if any(w['text'] not in allowed and w['score']>=.90 for w in f.words if 450<w['x']<1150 and 210<w['y']<680):return None
    return dict(rule='free_team_auto_configuration',label='按完整免费队伍配置说明，配置已有高战斗力英雄（不强化/消耗/入场）',target=anchors[-1],proof=anchors)
