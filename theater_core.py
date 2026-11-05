"""Moonlight Theater recognition and planning; no input or persistence here."""
from dataclasses import dataclass
import re
import unicodedata
from abyss_core import Token
from task_blockers import capacity_blocker, TaskAttention


def norm(text):
    return re.sub(r'[\s，。！？：:,.!?·…（）()]+', '', unicodedata.normalize('NFKC', text)).translate(
        str.maketrans('劇場觀覽門張確觀看錄購買換復敗關閉', '剧场观览门张确观看录购买换复败关闭')).casefold()


@dataclass(frozen=True)
class Episode:
    series: str
    number: int
    season: int | None = None

    @property
    def key(self):
        season = '|season:' + str(self.season) if self.season is not None else ''
        return self.series + season + '|episode:' + str(self.number)

    @property
    def history_keys(self):
        return {self.key, self.series + '|episode:' + str(self.number)}


@dataclass(frozen=True)
class Reading:
    scene: str
    target: Token | None = None
    episode: Episode | None = None
    completed: tuple[int, ...] = ()
    reason: str = ''
    ticket_cost: int | None = None
    ticket_stock: int | None = None
    next_episode: Episode | None = None
    reward_episode: Episode | None = None


def confident(token):
    return token.score is not None and token.score >= .85


def unique(o, labels, region):
    rows = [t for t in o.tokens if norm(t.text) in labels]
    if len(rows) == 1 and confident(rows[0]) and o.in_region(rows[0], region):
        return rows[0]


def selected_episode(o):
    """Accept an explicit title and a unique episode in the selected detail pane.

    Multiple row numbers, generic Theater headings and artwork never identify
    an episode. Unsupported layouts remain unknown instead of making new keys.
    """
    numbers = set()
    combined_titles = set()
    for t in o.tokens:
        if not confident(t) or not o.in_region(t, (.50, .10, .99, .83)):
            continue
        text = norm(t.text)
        match = re.fullmatch(r'(.*?)第(\d{1,3})集(.*)', text)
        if match and 0 < int(match[2]) < 1000:
            numbers.add(int(match[2]))
            if match[1].startswith('剧目') and len(match[1][2:]) >= 2:
                combined_titles.add(match[1][2:])
    titles = set(combined_titles)
    for t in o.tokens:
        if not confident(t) or not o.in_region(t, (.04, .02, .96, .36)):
            continue
        match = re.fullmatch(r'(?:剧目名称|当前剧目|剧目)[「『《]?(.+?)[」』》]?', norm(t.text))
        if match and len(match[1]) >= 2:
            titles.add(match[1])
    if not titles:
        # Some clients render an unlabelled production heading. Require one
        # large, isolated heading above the selected episode, not a list row,
        # currency counter or arbitrary dialogue text.
        excluded = ('月光剧场', '进行观览', '观览指南', '剧场门票', '下一集', '已观览', '已观看',
                    '观看故事', '故事目录', '观览记录', '观览完成', '选择剧目', '返回', '说明')
        titles = {norm(t.text).strip('《》「」『』') for t in o.tokens
                  if confident(t) and o.in_region(t, (.35, .08, .95, .33))
                  and .022*o.height <= t.h <= .08*o.height
                  and re.fullmatch(r'[《》「」『』\u3400-\u9fff·]{3,25}', norm(t.text))
                  and not any(v in norm(t.text) for v in excluded)}
    if len(numbers) == len(titles) == 1:
        return Episode(next(iter(titles)), next(iter(numbers)))


def completed_episodes(o):
    numbers = set()
    for t in o.tokens:
        if not confident(t):
            continue
        match = re.fullmatch(r'第(\d{1,3})集(?:已观览|已观看|观览完成)', norm(t.text))
        if match:
            numbers.add(int(match[1]))
    return tuple(sorted(numbers))


def immediate_ticket_stock(o):
    """Observed ticket dialog: isolate the cost sentence from item/stock text.

    This is not a general confirmation matcher. The exact title, one whole
    cost question and one inventory field must be present in their own bands;
    cost is never inferred from the inventory or the underlying directory.
    """
    title = unique(o, ('使用剧场门票',), (.35, .15, .66, .29))
    questions = [t for t in o.tokens
                 if o.in_region(t, (.24, .28, .77, .39))
                 and any(v in norm(t.text) for v in ('使用', '消耗', '观览吗'))]
    stocks = [t for t in o.tokens if norm(t.text).startswith('持有')
              and o.in_region(t, (.36, .50, .65, .60))]
    refined = [t for t in stocks if t.source == 'theater_ticket_stock_ocr']
    primary = [t for t in stocks if t.source != 'theater_ticket_stock_ocr']
    if not title or len(questions) != 1 or len(primary) != 1 or len(refined) > 1:
        return None
    stock = primary[0]
    if refined:
        if not confident(refined[0]) or refined[0].score < .90:
            return None
        a = re.fullmatch(r'持有([0-9]{1,6})', norm(stock.text))
        b = re.fullmatch(r'持有([0-9]{1,6})', norm(refined[0].text))
        if not a or not b or int(a[1]) != int(b[1]):
            return None
        stock = refined[0]
    question = questions[0]
    if not confident(question) or not confident(stock):
        return None
    if norm(question.text) != '确定要使用1张剧场门票来立即观览吗':
        return None
    count = re.fullmatch(r'持有([0-9]{1,6})', norm(stock.text))
    if count:
        return int(count[1])


def narrative_revive_line(o, token):
    """Exclude only two observed necromancy dialogue lines, never revive UI/costs.

    The story strip alone is insufficient: retain all blockers unless this is
    a confident full sentence in the dialogue band with its separate speaker,
    and no modal/action hint (including weak OCR) exists anywhere in the frame.
    """
    value = norm(token.text)
    if ('theater_story' not in o.visuals or 'theater_battle' in o.visuals
            or not confident(token) or token.score < .94 or len(value) < 16
            or not (('死尸复活' in value and '降灵术' in value)
                    or value == '可以重新手术复活他们但每次都会缩短几周的寿命')
            or not o.in_region(token, (.18, .79, .90, .94))):
        return False
    speakers = [t for t in o.tokens if t is not token and confident(t)
                and re.fullmatch(r'[\u3400-\u9fff]{2,15}', norm(t.text))
                and o.in_region(t, (.28, .70, .74, .78))]
    if len(speakers) != 1:
        return False
    hints = ('确认', '确定', '取消', '关闭', '好的', '重试', '是否', '消耗',
             '购买', '兑换', '天空石', '补充门票', '门票不足', '票券不足',
             '体力不足', '没有足够', '重新连接', '连接失败', '立即复活')
    return not any(any(h in norm(t.text) for h in hints)
                   or norm(t.text) in ('ok', '是', '否', '复活') for t in o.tokens)


def classify(o):
    texts = [norm(t.text) for t in o.tokens]
    text = ''.join(texts)
    blocker = capacity_blocker(t.text for t in o.tokens)
    if blocker:
        return Reading('theater_blocked', reason=blocker.reason)
    risk_text = ''.join(norm(t.text).replace('复活', '') if narrative_revive_line(o, t)
                        else norm(t.text) for t in o.tokens)
    if any(v in risk_text for v in ('购买', '兑换', '复活', '天空石', '补充门票', '门票不足',
                                    '票券不足', '体力不足', '没有足够', '重新连接', '连接失败')):
        return Reading('theater_blocked', reason='资源、购买或网络提示需要手动处理。')
    if any(v in text for v in ('战斗失败', '挑战失败', '任务失败', '闯关失败', 'defeat', '重新挑战')):
        return Reading('theater_defeat', reason='战败或重新挑战提示；保留入场记录，不重试。')
    confirms = [t for t in o.tokens if norm(t.text) in ('确认', '确定')]
    cancels = [t for t in o.tokens if norm(t.text) == '取消']
    confirm = unique(o, ('确认', '确定'), (.48, .48, .83, .85))
    cancel_ok = not cancels or (len(cancels) == 1 and confident(cancels[0])
                               and o.in_region(cancels[0], (.18, .48, .52, .85)))
    modal = ''.join(norm(t.text) for t in o.tokens if confident(t)
                    and o.in_region(t, (.18, .15, .84, .78)))
    # Only this specific one-ticket cost is authorized; stock counts do not
    # prove a cost. A guide is a separate, free confirmation after payment.
    if confirms or cancels:
        if confirm and cancel_ok and all(v in modal for v in
                ('观览指南', '月光剧场的故事无法跳过', '是否要开始观览')):
            return Reading('theater_guide', confirm)
        stock = immediate_ticket_stock(o)
        if (stock is not None and confirm and len(cancels) == 1 and cancel_ok
                and o.in_region(confirm, (.50, .66, .68, .82))
                and o.in_region(cancels[0], (.32, .66, .49, .82))
                and not any(v in text for v in ('其他道具', '额外消耗', '金币', '钻石'))):
            if stock < 1:
                return Reading('theater_blocked', reason='本帧剧场门票持有数量不足；不购买或兑换。')
            return Reading('theater_ticket', confirm, ticket_cost=1, ticket_stock=stock)
        caption = ''.join(norm(t.text) for t in o.tokens if confident(t)
                          and o.in_region(t, (.18, .32, .84, .58))
                          and norm(t.text) not in ('确认', '确定', '取消'))
        one_ticket = re.fullmatch(r'(?:是否(?:要)?)?(?:使用|消耗)(?:剧场门票1张|1张剧场门票)(?:进行观览|开始观览|观览)(?:吗)?', caption)
        if (confirm and cancel_ok and '剧场门票' in modal and one_ticket
                and not any(v in modal for v in ('其他道具', '额外消耗'))):
            return Reading('theater_ticket', confirm)
        return Reading('theater_unknown_dialog', reason='未完整核实的一张门票或观览指南确认；零输入。')
    reward_title = unique(o, ('获得奖励',), (.30,.16,.72,.30))
    reward_closed = unique(o, ('点击关闭',), (.30,.65,.72,.82))
    reward_texts = [norm(t.text) for t in o.tokens if confident(t) and o.in_region(t,(.20,.28,.80,.40))]
    if (reward_title and reward_closed and '已领取奖励' in reward_texts
            and '若有未领取的观览奖励则将汇总后统一领取' in reward_texts):
        return Reading('theater_reward_notice', reward_closed)
    if (any(v in text for v in ('点击关闭', '轻触后关闭', '是否使用', '是否消耗'))
            or any(v in texts for v in ('关闭', '好的', 'ok', '重试', '是', '否'))):
        return Reading('theater_unknown_dialog', reason='未识别的覆盖提示，不能点击底层。')
    from theater_directory import read_directory
    directory = read_directory(o)
    if directory is not None:
        completed = tuple(row.number for row in directory.rows if row.completed)
        episode = directory.episode
        if episode is None:
            return Reading('theater_list', directory.view, reason='目录当前集、金色选框、剧目或选中季数未完整核实。')
        rewards = [r for r in directory.rows if r.reward_ready]
        claim = [t for t in o.tokens if t.source == 'theater_reward_claim']
        if len(rewards) == 1 and len(claim) == 1:
            return Reading('theater_reward_ready', claim[0], episode, completed,
                           reward_episode=Episode(episode.series, rewards[0].number, episode.season))
        row = next(row for row in directory.rows if row.number == episode.number)
        if row.completion_unknown:
            return Reading('theater_blocked', episode=episode, reason='当前集出现完成文字，但完成勾或行关联未完整核实；不重复观览。')
        if row.locked:
            return Reading('theater_blocked', episode=episode, completed=completed, reason='当前选中集明确无法观览；不点击后续锁定行。')
        if row.completed:
            next_rows = [r for r in directory.rows if r.number == episode.number+1
                         and not r.locked and not r.completed and not r.completion_unknown]
            if len(next_rows) == 1:
                following = Episode(episode.series, next_rows[0].number, episode.season)
                return Reading('theater_select_episode', next_rows[0].token, episode, completed,
                               next_episode=following)
            return Reading('theater_empty', episode=episode, completed=completed,
                           reason='本集已完成；当前未见可核验的下一新集。')
        if not directory.view:
            return Reading('theater_empty', episode=episode, completed=completed,
                           reason='没有唯一的本帧进行观览控件。')
        if directory.cost != 1 or directory.stock is None or directory.stock < 1:
            return Reading('theater_blocked', episode=episode, reason='未核实本帧1张门票/持有数量，或门票不足；不购买。')
        return Reading('theater_list', directory.view, episode, completed,
                       ticket_cost=directory.cost, ticket_stock=directory.stock)
    if any(any(v in norm(t.text) for v in ('未解锁', '尚未开放', '不可观览', '未开放', '无法观览'))
           and o.in_region(t, (.50, .10, .99, .83)) for t in o.tokens):
        return Reading('theater_blocked', reason='当前集未解锁或不可观览；不尝试解锁或入场。')
    title = unique(o, ('月光剧场',), (0, 0, .65, .24))
    view = unique(o, ('进行观览',), (.50, .40, .99, .99))
    if title:
        episode = selected_episode(o)
        completed = completed_episodes(o)
        if episode and any(norm(t.text) in ('已观览', '已观看', '观览完成') and confident(t)
                           and o.in_region(t, (.50, .10, .99, .83)) for t in o.tokens):
            completed = tuple(sorted(set(completed) | {episode.number}))
        next_episode = unique(o, ('下一集',), (.50, .40, .99, .99))
        if episode and episode.number in completed and next_episode:
            return Reading('theater_next', next_episode, episode, completed)
        return Reading('theater_list' if view else 'theater_empty', view, episode, completed,
                       '' if episode else '剧目名称或当前集数未完整识别，不猜测身份。')
    if 'theater_clear_overlay' in o.visuals:
        clear = unique(o, ('clear',), (.40, .33, .62, .45))
        if clear and clear.score >= .94:
            return Reading('theater_clear_overlay', clear)
    # CLEAR by itself is a transition, never an input or completion license.
    if any(v in texts for v in ('clear', 'victory', '战斗胜利')):
        advance = unique(o, ('点击继续', '轻触继续'), (.25, .65, .80, .99))
        if advance and 'theater_battle' in o.visuals:
            return Reading('theater_victory', advance)
        return Reading('theater_transition', reason='胜利/过渡证据尚未完整核实；零输入观察，不计完成。')
    if 'theater_battle' in o.visuals:
        return Reading('theater_battle')
    if 'theater_story' in o.visuals:
        # The center is a story-advance surface only while the complete,
        # positively matched replay/log/pause strip is visible in this frame.
        return Reading('theater_story', Token('verified_story_surface', o.width*.5-1,
                                             o.height*.5-1, 2, 2, source='theater_story', score=1.0))
    return Reading('theater_unknown')


def plan(reading, state, run_id):
    scene = reading.scene
    if scene in ('theater_blocked', 'theater_defeat', 'theater_unknown_dialog'):
        raise TaskAttention(scene, '月光剧场等待处理', reading.reason)
    if scene in ('theater_battle', 'theater_transition', 'theater_unknown'):
        return None
    active = state.get('active')
    if scene in ('theater_list', 'theater_empty', 'theater_next', 'theater_select_episode'):
        if active:
            raise TaskAttention('theater_unresolved', '上一集结果尚未核实', '未见对应集数的独立已观览证据；保留记录，不重新观览。')
        if scene == 'theater_empty':
            raise TaskAttention('theater_empty', '没有已核实的可观览按钮', '请手动选择已解锁剧目；不购买门票、不点击未知位置。')
        if not reading.episode:
            raise TaskAttention('theater_identity', '剧目或集数未读清', reading.reason)
        if scene == 'theater_next':
            if reading.episode.number not in reading.completed:
                raise TaskAttention('theater_next_unverified', '尚未核实本集已观览', '不猜测下一集。')
            return 'next'
        if scene == 'theater_select_episode':
            following = reading.next_episode
            if (reading.episode.number not in reading.completed or following is None
                    or following.number != reading.episode.number+1
                    or following.series != reading.episode.series or following.season != reading.episode.season):
                raise TaskAttention('theater_next_unverified', '下一集校验不完整', '不跳过未完成或未核实的当前集。')
            from entry_journal import can_enter
            if not all(can_enter(state, key) for key in following.history_keys):
                raise TaskAttention('theater_repeated', '下一集已有原入场或完成记录', '不重复、不跳过结果不明剧集。')
            return 'select'
        if reading.episode.number in reading.completed:
            raise TaskAttention('theater_already_watched', '当前集已有明确已观览状态', '不重复观看已完成剧集；请选择下一新集。')
        from entry_journal import can_enter
        if not all(can_enter(state, key) for key in reading.episode.history_keys):
            from theater_journal import ticket_recovery_permission
            if ticket_recovery_permission(state, reading) is not None:
                return 'recover_open'
            raise TaskAttention('theater_repeated', '该集已有入场或完成记录', '不能重看已尝试、失败、结果不明或已完成的剧集；请选择新集。')
        return 'open'
    if scene == 'theater_reward_notice':
        # The complete, position-verified ALREADY-CLAIMED notice is a free
        # dismissal, not a claim, entry or completion. Current-screen starts
        # may legitimately have no active playback chain; keep their original
        # archives intact rather than forcing a replay to close this notice.
        if (reading.target is None or not confident(reading.target)
                or norm(reading.target.text) != '点击关闭'):
            raise TaskAttention('theater_reward_control', '观览奖励关闭控件未完整核实',
                                '不使用缺失、弱识别或未知控件。')
        return 'close_reward_notice'
    if scene == 'theater_reward_ready':
        if (not active or active.get('run_id') != run_id or active.get('phase') != 'story'
                or not active.get('playback_evidence') or reading.reward_episode is None
                or reading.reward_episode.key != active.get('key')):
            raise TaskAttention('theater_reward_chain', '免费观览奖励缺少本轮对应集数', '不领取未知归属奖励或记完成。')
        return 'claim_reward'
    if scene == 'theater_clear_overlay':
        if (not active or active.get('run_id') != run_id or active.get('phase') != 'story'
                or not active.get('playback_evidence')):
            raise TaskAttention('theater_clear_chain', '胜利遮罩缺少本轮播放链', '只观察，不猜测关闭、不补记通关。')
        return 'dismiss_clear'
    if scene == 'theater_free_ready':
        if (active or reading.episode is None or reading.ticket_cost != 0 or reading.target is None
                or reading.episode.number in reading.completed):
            raise TaskAttention('theater_free_chain', '免费新集入场条件不完整', '不丢弃旧入场链、不重新扣票。')
        from entry_journal import can_enter
        if not all(can_enter(state, key) for key in reading.episode.history_keys):
            raise TaskAttention('theater_repeated', '该集已有入场或完成记录', '免费按钮也不能绕过原尝试、失败或完成记录。')
        return 'open_free'
    if scene == 'theater_paid_ready':
        payments=[r for r in state.get('actions',[]) if r.get('key')==(active or {}).get('key') and r.get('kind')=='ticket']
        if (not active or active.get('run_id')!=run_id or active.get('phase')!='await_guide'
                or reading.episode is None or reading.episode.key!=active.get('key')
                or len(payments)!=1 or payments[0].get('status')!='sent' or payments[0].get('run_id')!=run_id):
            raise TaskAttention('theater_paid_chain','免费播放页缺少单次扣票链','不重新确认门票、不猜测播放。')
        return 'play'
    if scene == 'theater_ticket':
        if not active or active['run_id'] != run_id or active['phase'] != 'await_ticket':
            raise TaskAttention('theater_ticket_chain', '门票确认缺少当前集校验', '保留当前确认页与原入场记录；未关联原待确认链前不花票，不取消重开或换空记录。')
        if active.get('confirmation_continuation_id'):
            from theater_pending_confirmation import ticket_permission
            if ticket_permission(state, run_id, reading) is None:
                raise TaskAttention('theater_confirmation_consumed', '原已打开门票接续已消费或校验失效', '保留授权、原入口与确认意图；不重新扣票或打开入口。')
        if active.get('recovery_id'):
            grants = [g for g in state.get('pending_ticket_recoveries', []) if g.get('id') == active['recovery_id']]
            if (len(grants) != 1 or grants[0].get('status') != 'sent'
                    or grants[0].get('claimed_run_id') != run_id
                    or reading.ticket_cost != 1 or reading.ticket_stock != grants[0]['expected_stock']):
                raise TaskAttention('theater_recovery_ticket', '恢复后的门票费用或库存不一致', '不确认门票，保留原记录等待处理。')
        return 'ticket'
    if scene == 'theater_guide':
        if active and (active['run_id'] != run_id or active['phase'] != 'await_guide'):
            raise TaskAttention('theater_guide_chain', '观览指南校验链不一致', '不重复确认已发送或结果不明的动作。')
        return 'guide'
    if scene in ('theater_story', 'theater_victory'):
        if active and (active['run_id'] != run_id or active['phase'] not in ('story', 'await_guide')):
            raise TaskAttention('theater_story_chain', '剧情入场结果未核实', '当前画面与本轮入场步骤不一致；保留现场。')
        return 'advance' if scene == 'theater_story' else 'victory'
    return None
