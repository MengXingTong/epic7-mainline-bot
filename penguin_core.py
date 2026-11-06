"""Strict, side-effect-free Penguin Nest page recognition and quantity planning."""
from dataclasses import dataclass
import re
from abyss_core import Token, Observation
from task_blockers import TaskAttention, capacity_blocker
from theater_core import norm


def quantity(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,5}', str(value)):
        raise ValueError('买企鹅数量必须为 1～999999 的整数（总只数，不是购买次数）。')
    return int(value)


def one(o, text, region, threshold=.94):
    rows = [t for t in o.tokens if norm(t.text) == norm(text) and o.in_region(t, region)]
    if len(rows) == 1 and rows[0].score is not None and rows[0].score >= threshold:
        return rows[0]


def numeric(o, region, pattern=r'[0-9]{1,9}'):
    rows = [t for t in o.tokens if o.in_region(t, region)
            and re.fullmatch(pattern, t.text.replace(',', '').replace('，', ''))]
    if not rows or any(t.score is None or t.score < .98 for t in rows):
        return None
    values = {t.text.replace(',', '').replace('，', '') for t in rows}
    return next(iter(values)) if len(values) == 1 else None


@dataclass(frozen=True)
class Reading:
    scene: str = 'penguin_unknown'
    target: Token | None = None
    stock: int | None = None
    unit: int | None = None
    selected: int | None = None
    maximum: int | None = None
    total: int | None = None
    currency: str | None = None
    minimum: Token | None = None
    most: Token | None = None
    plus: Token | None = None
    minus: Token | None = None
    cancel: Token | None = None


def classify(o):
    texts = [t.text for t in o.tokens]
    blocker = capacity_blocker(texts)
    if blocker:
        raise TaskAttention(blocker.code, blocker.title, blocker.reason)
    if any(any(w in norm(t) for w in ('资源不足', '圣叶不足', '数量不足', '持有不足', '行动力不足',
            '复活', '兑换', '战斗失败', '购买天空石', '购买行动力')) for t in texts):
        raise TaskAttention('penguin_resource', '资源或风险提示', '请手动处理；不购买其他资源、不兑换、不复活。')
    # Modal precedence is mandatory: never use dimmed controls behind a dialog.
    title = one(o, '购买商品', (.40,.13,.61,.22), .98)
    if title:
        if any(norm(t.text) in ('确认','确定','点击关闭','兑换') for t in o.tokens):
            return Reading()
        item = one(o, '企鹅巢穴', (.49,.39,.64,.47), .98)
        prompt = one(o, '确定要购买该商品吗？', (.37,.24,.63,.32), .98)
        kind = one(o, '英雄升等材料', (.49,.36,.66,.42), .98)
        buy = one(o, '购买', (.61,.77,.70,.87), .98)
        cancel = one(o, '取消', (.32,.77,.42,.87), .98)
        least = one(o, '最少', (.26,.62,.32,.70), .98)
        most = one(o, '最多', (.67,.62,.75,.70), .98)
        q = numeric(o, (.44,.55,.57,.63), r'[1-9][0-9]{0,5}/[1-9][0-9]{0,5}')
        total = numeric(o, (.49,.78,.58,.86))
        if not all((item, prompt, kind, buy, cancel, least, most, q, total)):
            return Reading()
        n, maximum = map(int, q.split('/'))
        currency = next((v.split(':',1)[1] for v in o.visuals if v.startswith('penguin_currency:')), None)
        if n > maximum or not currency:
            return Reading()
        return Reading('penguin_dialog', buy, selected=n, maximum=maximum, total=int(total),
            currency=currency, minimum=least, most=most,
            plus=one(o, '+1', (.62,.62,.68,.70), .98),
            minus=one(o, '-1', (.32,.62,.38,.70), .98), cancel=cancel)
    altar = one(o, '成长祭坛', (.05,.18,.18,.27), .98)
    if altar:
        if any(norm(t.text) in ('取消','确认','确定','最多','最少','购买商品') for t in o.tokens):
            return Reading()
        buys=[t for t in o.tokens if norm(t.text)=='购买']
        if (len(buys)!=4 or any(t.score is None or t.score<.98 or not o.in_region(t,(.17,.69,.92,.80)) for t in buys)
                or not one(o,'点击关闭',(.43,.92,.59,.99),.98)):
            return Reading()
        item = one(o, '企鹅巢穴', (.10,.28,.23,.35), .98)
        flowers = one(o, '精灵之泉', (.54,.28,.70,.35), .98)
        desc = any(norm(t.text).startswith('使用企鹅可提升英雄经验值') and t.score >= .98
                   and o.in_region(t, (.04,.50,.28,.59)) for t in o.tokens)
        buy = one(o, '购买', (.17,.69,.24,.80), .98)
        price = numeric(o, (.108,.70,.158,.79))
        stock = numeric(o, (.866,.19,.95,.26))
        currency = next((v.split(':',1)[1] for v in o.visuals if v.startswith('penguin_currency:')), None)
        if all((item, flowers, desc, buy, price, stock is not None, currency)):
            return Reading('penguin_altar', buy, stock=int(stock), unit=int(price), currency=currency)
        return Reading()
    # Any other foreground modal prevents navigation through it.
    if any(norm(t.text) in ('取消','确认','确定','购买','点击关闭','购买商品','最多','最少') for t in o.tokens):
        return Reading()
    forest = one(o, '精灵之森', (.04,.02,.20,.08))
    altar_button = one(o, '成长祭坛', (.78,.84,.95,.96), .98)
    if forest and altar_button and one(o, '企鹅巢穴', (.74,.29,.90,.37), .98):
        return Reading('penguin_forest', altar_button)
    sanctuary = one(o, '圣域', (.04,.02,.12,.08), .98)
    forest_button = one(o, '精灵之森', (.87,.20,.98,.29), .98)
    if sanctuary and forest_button and one(o, '欧勒毕斯之心', (.82,.33,.99,.43), .98):
        return Reading('penguin_sanctuary', forest_button)
    lobby = one(o, '圣域', (.01,.22,.09,.29), .98)
    if lobby and one(o, '秘密商店', (.00,.44,.11,.51), .98) and one(o, '商店', (.90,.68,.98,.76), .98):
        return Reading('penguin_lobby', lobby)
    return Reading()


@dataclass(frozen=True)
class Action:
    kind: str
    target: Token | None = None
    desired: int | None = None


def plan(r, phase, remaining, baseline=None, pending=None):
    if pending:
        return Action('wait_result')  # A sent/unknown purchase never re-enters quantity planning.
    if remaining <= 0:
        return Action('done')
    if r.scene in ('penguin_lobby','penguin_sanctuary','penguin_forest'):
        if phase != 'navigate':
            raise TaskAttention('penguin_chain', '购买流程已变化', '页面离开原购买链；保留记录，不自动重开。')
        return Action('navigate', r.target)
    if r.scene == 'penguin_altar':
        if phase != 'navigate':
            return Action('wait')
        if not r.unit or r.stock < remaining*r.unit:
            raise TaskAttention('penguin_resource', '祭坛资源不足', '不会兑换或补买资源。')
        return Action('open', r.target)
    if r.scene != 'penguin_dialog':
        return Action('wait')
    if phase == 'navigate':
        # Start on a pre-existing modal: return to inspect its actual altar price/balance.
        return Action('cancel', r.cancel)
    if phase not in ('opening','dialog') or not baseline:
        raise TaskAttention('penguin_chain', '缺少原购买链', '不在外来弹窗直接扣资源。')
    from penguin_vision import same_currency
    if not same_currency(r.currency, baseline['currency']):
        raise TaskAttention('penguin_currency', '购买币种核验失败', '与本次祭坛资源图标不符；不购买。')
    if r.total != r.selected * baseline['unit'] or r.maximum * baseline['unit'] > baseline['stock']:
        raise TaskAttention('penguin_price', '数量或费用不符', '总价、单价或可购买数与当前库存不符；不购买。')
    desired = min(remaining, r.maximum)
    if r.selected == desired:
        return Action('purchase', r.target, desired)
    # Full batches always use Most. Partial batches use bounded +/-1, one fresh read per step.
    options = [(abs(desired-r.selected), None, None),
               (1+desired-1, 'minimum', r.minimum),
               (1+r.maximum-desired, 'most', r.most)]
    if desired == r.maximum:
        return Action('most', r.most, desired)
    _, kind, token = min(options, key=lambda x: x[0])
    if kind:
        return Action(kind, token, desired)
    token = r.plus if desired > r.selected else r.minus
    if token is None:
        return Action('wait')
    return Action('plus' if desired > r.selected else 'minus', token, desired)
