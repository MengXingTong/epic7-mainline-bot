"""Experimental PC Theater worker; fresh recognition authorizes one input."""
from pathlib import Path
import time
from abyss_core import Observation, Token
from theater_core import classify, plan
from theater_journal import TheaterJournal
from theater_vision import TheaterVision, final_wave_counter
from task_blockers import TaskAttention
from task_timing import ObservationCycle, ScreenStabilityGate

STORY_PRESS_SECONDS = .01


def read_observation(image, ocr, captured_at):
    import numpy as np
    from PIL import Image, ImageEnhance
    sampled = image if image.size == (1600, 900) else image.resize((1600, 900), Image.Resampling.LANCZOS)
    results, _ = ocr(np.asarray(sampled)[:, :, ::-1].copy())
    sx, sy = image.width / 1600, image.height / 900
    tokens = []
    for box, text, score in results or []:
        x, y = min(p[0] for p in box), min(p[1] for p in box)
        tokens.append(Token(text, x*sx, y*sy, (max(p[0] for p in box)-x)*sx,
                            (max(p[1] for p in box)-y)*sy, score=float(score)))
    # Full-frame OCR misses the dark, tiny final-wave counter under CLEAR.
    # Only read this position-limited crop when the banner text is present.
    from theater_core import norm
    if any(norm(t.text) == 'clear' and t.score >= .94 for t in tokens):
        crop = ImageEnhance.Brightness(sampled.crop((195, 0, 272, 50)).resize((308, 200))).enhance(3)
        wave_results, _ = ocr(np.asarray(crop)[:, :, ::-1].copy())
        for box, text, score in wave_results or []:
            if not final_wave_counter(text) or score < .94:
                continue
            x, y = min(p[0] for p in box)/4+195, min(p[1] for p in box)/4
            tokens.append(Token(text, x*sx, y*sy, (max(p[0] for p in box)-min(p[0] for p in box))*sx/4,
                                (max(p[1] for p in box)-min(p[1] for p in box))*sy/4,
                                source='theater_wave_ocr', score=float(score)))
    from theater_ticket_ocr import refine_ticket_stock
    tokens = refine_ticket_stock(sampled, tokens, image.width, image.height, ocr)
    return Observation(image.width, image.height, tokens, captured_at)


def paid_return_pending(reading, state, run_id):
    """Bounded zero-input observation only; never authorizes free play or re-pay."""
    active = state.get('active')
    if (reading.scene != 'theater_list' or not active
            or active.get('run_id') != run_id or active.get('phase') != 'await_guide'
            or active.get('playback_evidence')):
        return False
    if reading.episode is not None:
        if (reading.episode.key != active.get('key')
                or reading.episode.number in reading.completed):
            return False
    actions = [a for a in state.get('actions', []) if a.get('key') == active.get('key')]
    payments = [a for a in actions if a.get('kind') == 'ticket']
    if (len(payments) != 1 or payments[0].get('status') != 'sent'
            or payments[0].get('run_id') != run_id):
        return False
    # An already-reserved/sent/unknown play or guide must reach its ordinary
    # transition/dedup guard, not gain a fresh grace period after an input.
    return not any(a.get('kind') in ('play', 'guide') for a in actions)


def story_return_pending(o, reading, state, run_id):
    """Only observe an incomplete same-production result return; never input."""
    import re
    from theater_core import confident, norm
    active = state.get('active')
    if (reading.scene != 'theater_list' or not active or active.get('run_id') != run_id
            or active.get('phase') != 'story' or not active.get('playback_evidence')
            or not isinstance(active.get('number'), int) or active['number'] in reading.completed):
        return False
    actions = [a for a in state.get('actions', []) if a.get('key') == active.get('key')]
    opened = [a for a in actions if a.get('kind') in ('open', 'open_free', 'recover_open')]
    from theater_pending_confirmation import continued_opening
    if (len(opened) != 1 or opened[0].get('status') != 'sent'
            or (opened[0].get('run_id') != run_id and not continued_opening(state, run_id, opened[0]))
            or any(a.get('kind') == 'claim_reward' for a in actions)
            or any(a.get('status') not in ('sent', 'not_sent') for a in actions)):
        return False
    if reading.episode is not None:
        ep = reading.episode
        if (ep.series != active.get('series') or ep.season != active.get('season')
                or ep.number not in (active['number'], active['number']+1)):
            return False
    logo = [t for t in o.tokens if confident(t) and o.in_region(t, (.02,.10,.33,.40))
            and .06*o.height <= t.h <= .20*o.height
            and re.fullmatch(r'[㐀-鿿]{1,12}', norm(t.text))]
    selected = {int(v.split(':')[1]) for v in o.visuals
                if re.fullmatch(r'theater_(?:soft_)?selected:\d+', v)}
    # A first return frame can lack the selection outline altogether. That
    # missing marker permits bounded ZERO-INPUT observation, never a target.
    return (''.join(norm(t.text) for t in sorted(logo, key=lambda t:(t.y,t.x))) == active.get('series')
            and (not selected or (len(selected) == 1 and selected <= {active['number'], active['number']+1})))


def reward_return_pending(reading, state, run_id):
    """Same sent reward's list transition only: observe, never replay/complete."""
    from theater_core import Episode
    active = state.get('active')
    if (reading.scene != 'theater_list' or not active
            or active.get('run_id') != run_id or active.get('phase') != 'story'
            or not active.get('playback_evidence')
            or active.get('number') in reading.completed):
        return False
    actions = [a for a in state.get('actions', []) if a.get('key') == active.get('key')]
    claims = [a for a in actions if a.get('kind') == 'claim_reward']
    closes = [a for a in actions if a.get('kind') == 'close_reward_notice']
    if (len(claims) != 1 or claims[0].get('status') != 'sent'
            or claims[0].get('run_id') != run_id or len(closes) > 1
            or any(a.get('run_id') != run_id or a.get('status') != 'sent' for a in closes)
            or any(a.get('status') not in ('sent', 'not_sent') for a in actions)):
        return False
    source = claims[0].get('episode')
    if not isinstance(active.get('number'), int) or not active.get('series'):
        return False
    following = Episode(active['series'], active['number']+1, active.get('season')).key
    if source not in (active.get('key'), following):
        return False
    return reading.episode is None or reading.episode.key == source


def free_return_pending(image, observation, reading, state, run_id):
    """Observe a sent free entry's original directory only; never replay it."""
    from theater_directory import free_play_reading
    active = state.get('active')
    if (not active or active.get('run_id') != run_id or active.get('phase') != 'await_guide'
            or active.get('playback_evidence')):
        return False
    actions = [a for a in state.get('actions', []) if a.get('key') == active.get('key')]
    opened = [a for a in actions if a.get('kind') == 'open_free']
    if (len(opened) != 1 or opened[0].get('status') != 'sent'
            or opened[0].get('run_id') != run_id or opened[0].get('episode') != active.get('key')
            or any(a.get('kind') in ('ticket', 'guide', 'play') for a in actions)):
        return False
    if reading.scene == 'theater_list' and reading.episode is None:
        return True  # Partial native return: bounded observation, zero inputs.
    if reading.episode is None or reading.episode.key != active.get('key'):
        return False
    return free_play_reading(image, observation, reading, pressed_observation=True).scene == 'theater_free_pending'


def run(request, control):
    from assistant_config import validate_run
    from assistant_transport import UnifiedTransport
    from assistant_worker import capture_fresh, wait_for_input, client_attention, PauseRun, StopRun
    from pc_backend import PcSafetyError, TapNotSent
    from rapidocr_onnxruntime import RapidOCR
    settings = request['settings']
    root, _ = validate_run(settings, request['target'], allow_reconcile=True)

    def check():
        control.check()
        if (Path(root) / 'STOP').exists():
            raise StopRun()

    transport = UnifiedTransport(settings, request['target'], check)
    binding = transport.ensure()

    def capture_same_target():
        if transport.ensure() != binding:
            raise PcSafetyError('游戏窗口位置或尺寸已变化；请点处理后继续，重新核验同一实例与当前画面。')
        return transport.capture()

    def refresh_after_resume():
        nonlocal binding
        # Control.attention/paused returns only after an explicit fresh Run.
        # ensure() still pins HWND/PID/process lifetime; this accepts geometry
        # only, never a replacement target or an old frame/input reservation.
        control.check()
        transport.frame = None
        binding = transport.ensure()
    ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    vision = TheaterVision()
    journal = None if settings.get('observe') else TheaterJournal(root, request['run_id'])
    wins = 0
    last_scene = None
    last_sent = None
    cycle = ObservationCycle()
    dialog_stability = ScreenStabilityGate()
    paid_wait_since = None
    reward_wait_since = None
    confirmation_receipt_checked = False
    while True:
        try:
            cycle.begin()
            check()
            # Fades may last longer than normal navigation; target/geometry
            # exceptions still escape immediately, and every retry is zero input.
            snap = capture_fresh(capture_same_target, control, blank_budget=300)
            obs = vision.apply(snap.image, read_observation(snap.image, ocr, snap.captured_at))
            reading = classify(obs)
            if journal is not None:
                from theater_directory import paid_play_reading, free_start_reading, reward_return_reading
                reading = paid_play_reading(snap.image, obs, reading, journal.state, request['run_id'], journal.root)
                reading = free_start_reading(snap.image, obs, reading, journal.state)
                reading = reward_return_reading(obs, reading, journal.state, request['run_id'], journal.root)
            control.preview(snap.image)
            message = reading.reason or ('当前页面未完整识别；零输入观察。' if reading.scene == 'theater_unknown'
                                         else '逐帧核验；剧情翻页，战斗等待，门票不足不购买。')
            control.status('月光剧场：' + message,
                mode=('observe' if settings.get('observe') else
                      'waiting_scene' if reading.scene in ('theater_transition', 'theater_unknown') else 'run'), scene=reading.scene,
                wins=wins, stage=(reading.episode.key if reading.episode else ''))
            if reading.scene != last_scene:
                control.log('识别：' + reading.scene)
                last_scene = reading.scene
            if settings.get('observe'):
                if request.get('once'):
                    return
                cycle.wait(control)
                continue
            # No cached classification is used for a later frame. Slow OCR
            # discards its frame before evidence, reservations or input.
            if time.monotonic() - snap.captured_at > 5:
                continue
            pending_paid_page = paid_return_pending(reading, journal.state, request['run_id'])
            pending_free_page = free_return_pending(snap.image, obs, reading, journal.state, request['run_id'])
            if pending_paid_page or pending_free_page:
                # The exact same paid episode can be fully readable while
                # its old ticket-cost/stock is still rendered. Partial rows
                # and that stale paid return get the same bounded zero-input
                # wait; a different episode/season and higher-priority pages
                # never borrow this context. Verified play/guide ran first.
                now = time.monotonic()
                if paid_wait_since is None:
                    paid_wait_since = now
                if now-paid_wait_since < 15:
                    message = ('免费观览已发送；等待同一集指南或播放，不重复入口。' if pending_free_page
                               else '门票确认已发送；等待同一集的免费播放页完整核实，不再扣票。')
                    control.status(message, mode='waiting_scene', scene=reading.scene)
                    cycle.wait(control)
                    continue
                if pending_free_page:
                    raise TaskAttention('theater_free_no_transition', '免费观览后的新页面尚未核实',
                                        '已零输入观察15秒，保留已发送入口，不重开或扣票；等待明确继续。')
            else:
                paid_wait_since = None
            pending_story_result = story_return_pending(obs, reading, journal.state, request['run_id'])
            if pending_story_result or reward_return_pending(reading, journal.state, request['run_id']):
                now = time.monotonic()
                if reward_wait_since is None:
                    reward_wait_since = now
                if now-reward_wait_since < 15:
                    message = ('剧情已返回同剧目目录；等待完整奖励/完成证据，不入下一集。' if pending_story_result
                               else '领奖已发送；等待奖励提示或独立完成行，不重发、不入下一集。')
                    control.status(message,
                                   mode='waiting_scene', scene=reading.scene)
                    cycle.wait(control)
                    continue
                raise TaskAttention('theater_reward_no_transition', '观览返回后的独立结果尚未核实',
                                    '已零输入观察15秒；保留原发送与播放记录，不重发或预记完成。')
            else:
                reward_wait_since = None
            if reading.scene == 'theater_unknown_dialog':
                if wait_for_input(control, transport, snap):
                    dialog_stability.reset()
                    continue
                words = [dict(text=t.text, x=t.center[0], y=t.center[1], score=t.score)
                         for t in obs.tokens]
                if dialog_stability.waiting('unknown_dialog', snap.image, words, obs.width, obs.height):
                    control.status('月光剧场：正在等待未识别弹窗稳定；不点击底层。',
                                   mode='waiting_scene', scene=reading.scene)
                    cycle.wait(control)
                    continue
            else:
                # Known complete ticket/guide controls do not wait for the
                # whole screen to settle; all business/dispatch guards remain.
                dialog_stability.reset()
            if reading.scene in ('theater_defeat', 'theater_blocked', 'theater_unknown_dialog'):
                proof = journal.evidence(snap, obs, reading)
                journal.observe(reading, proof)
                plan(reading, journal.state, request['run_id'])
            if reading.scene in ('theater_unknown', 'theater_transition', 'theater_battle'):
                if reading.scene == 'theater_battle' and journal.state['active']:
                    if not journal.state['active'].get('playback_evidence'):
                        journal.observe(reading, journal.evidence(snap, obs, reading))
                cycle.wait(control)
                continue
            if wait_for_input(control, transport, snap):
                continue
            if last_sent and reading.scene == last_sent[0] and last_sent[2] in ('open', 'open_free', 'recover_open', 'ticket', 'guide', 'victory', 'dismiss_clear', 'claim_reward', 'close_reward_notice', 'play', 'next', 'select'):
                if time.monotonic() - last_sent[1] < 6:
                    cycle.wait(control)
                    continue
                raise TaskAttention('theater_no_transition', '操作后的新页面尚未确认', '没有重复点击；处理后继续将重新核验并保留已发送记录。')
            proof = journal.evidence(snap, obs, reading)
            if not confirmation_receipt_checked:
                from theater_pending_confirmation import attach_receipt
                attach_receipt(journal, request, reading, proof, binding)
                confirmation_receipt_checked = True
            if journal.observe(reading, proof):
                wins += 1
                control.status('本集已由独立已观览状态确认。',wins=wins,scene=reading.scene)
            kind = plan(reading, journal.state, request['run_id'])
            if kind is None:
                cycle.wait(control)
                continue
            if kind == 'recover_open':
                from theater_journal import ticket_recovery_permission
                grant = ticket_recovery_permission(journal.state, reading)
                if grant is None or any(request['target'].get(k) != v for k, v in grant['target'].items()):
                    raise TaskAttention('theater_recovery_target', '恢复授权的原窗口不匹配', '不消耗单次授权或发送输入。')
            record = journal.reserve(kind, reading, proof)
            check()
            try:
                if kind == 'advance':
                    transport.tap(snap, reading.target, press_seconds=STORY_PRESS_SECONDS)
                else:
                    transport.tap(snap, reading.target)
            except TapNotSent as exc:
                journal.finish(record, 'not_sent', '后端明确证明按下未发送：' + str(exc))
                raise TaskAttention('theater_not_sent', '本次点击尚未发送', '移出鼠标后点处理后继续；重新识别，保留原意图。') from exc
            journal.finish(record, 'sent')
            last_sent = (reading.scene, time.monotonic(), kind)
            cycle.wait(control)
        except PauseRun:
            control.paused()
            refresh_after_resume()
            dialog_stability.reset()
            paid_wait_since = None
            reward_wait_since = None
            last_sent = None
        except TaskAttention as exc:
            control.attention(exc)
            refresh_after_resume()
            dialog_stability.reset()
            paid_wait_since = None
            reward_wait_since = None
            last_sent = None
        except PcSafetyError as exc:
            control.attention(client_attention(exc))
            refresh_after_resume()
            dialog_stability.reset()
            paid_wait_since = None
            reward_wait_since = None
            last_sent = None
