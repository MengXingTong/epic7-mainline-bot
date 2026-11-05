"""Private Theater ledger; critical evidence and intents precede every input."""
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from assistant_config import read_json
from entry_journal import reserve_entry, finish_dispatch, attempt_digest
from task_blockers import TaskAttention


def durable_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


# A human-approved, single-incident exception; never a general retry policy.
TICKET_RECOVERY_KEY = '没落大地|season:1|episode:9'


def pending_ticket_source(state, key):
    """Only the archived, sent OPEN with no ticket/playback/defeat is eligible."""
    if key != TICKET_RECOVERY_KEY or state.get('active') is not None:
        return None
    legacy = '没落大地|episode:9'
    if any(k in state.get('completed', {}) for k in (key, legacy)):
        return None
    if legacy in state.get('attempted', {}) or state.get('entry_dispatches', {}).get(legacy):
        return None
    attempt = state.get('attempted', {}).get(key)
    if not attempt or (attempt.get('series'), attempt.get('season'), attempt.get('number')) != ('没落大地', 1, 9):
        return None
    archives = [r for r in state.get('unresolved_entries', []) if r.get('entry', {}).get('key') == key]
    if len(archives) != 1:
        return None
    archive = archives[0]
    entry = archive['entry']
    if (entry.get('phase') != 'await_ticket' or entry.get('steps') != {}
            or any(k in entry for k in ('playback_evidence', 'defeat_evidence', 'completed_at', 'recovery_id'))
            or any(entry.get(k) != v for k, v in attempt.items())):
        return None
    actions = [r for r in state.get('actions', []) if r.get('key') in (key, legacy)
               or r.get('episode') in (key, legacy)]
    dispatches = state.get('entry_dispatches', {}).get(key, [])
    if len(actions) != 1 or len(dispatches) != 1 or actions[0] != dispatches[0]:
        return None
    opened = actions[0]
    if (opened.get('kind') != 'open' or opened.get('status') != 'sent'
            or opened.get('run_id') != attempt.get('run_id')
            or opened.get('original_sha256') != attempt_digest(attempt)
            or opened.get('entry') != attempt):
        return None
    return attempt, archive, opened


def ticket_recovery_permission(state, reading):
    """Return one unused explicit grant, only on the matching fresh directory."""
    if (reading.scene != 'theater_list' or reading.episode is None
            or reading.episode.key != TICKET_RECOVERY_KEY
            or reading.episode.number in reading.completed or reading.ticket_cost != 1):
        return None
    grants = [g for g in state.get('pending_ticket_recoveries', []) if g.get('key') == TICKET_RECOVERY_KEY]
    if len(grants) != 1:
        return None
    grant = grants[0]
    if (grant.get('status') != 'authorized' or not grant.get('authorization')
            or not grant.get('authorized_at', 0) <= time.time() <= grant.get('expires_at', 0)
            or not isinstance(grant.get('expected_stock'), int)
            or grant['expected_stock'] < 1 or reading.ticket_stock != grant['expected_stock']):
        return None
    source = pending_ticket_source(state, TICKET_RECOVERY_KEY)
    if source is None:
        return None
    if any(grant.get(field) != attempt_digest(value) for field, value in zip(
            ('attempt_sha256', 'archive_sha256', 'open_sha256'), source)):
        return None
    return grant



def current_pending_ticket(state, run_id):
    """Read-only same-run reload of a still-open, never-confirmed modal.

    No foreign archive, grant, recovered entry or already-paid/unknown intent
    qualifies. This only reloads code for the current original OPEN.
    """
    active = state.get('active')
    if (state.get('schema') != 1 or not isinstance(state.get('registration_id'), str)
            or not state['registration_id'] or not isinstance(active, dict) or active.get('run_id') != run_id):
        return False
    key = active.get('key')
    attempt = state.get('attempted', {}).get(key)
    if (not attempt or attempt.get('run_id') != run_id
            or active != {**attempt, 'phase': 'await_ticket', 'steps': {}}
            or not isinstance(attempt.get('number'), int) or not isinstance(attempt.get('season'), int)
            or not isinstance(attempt.get('series'), str) or not attempt['series']
            or attempt['number'] < 1 or attempt['season'] < 1
            or any(a.get('entry', {}).get('key') == key for a in state.get('unresolved_entries', []))):
        return False
    from theater_core import Episode
    episode = Episode(attempt['series'],attempt['number'],attempt['season'])
    if (episode.key != key or any(k in state.get('completed', {}) for k in episode.history_keys)
            or any(k != key and k in state.get('attempted', {}) for k in episode.history_keys)):
        return False
    actions = [a for a in state.get('actions', []) if a.get('key') == key]
    if len(actions) != 1 or state.get('entry_dispatches', {}).get(key) != actions:
        return False
    opened = actions[0]
    return (state.get('actions', [])[-1] == opened and opened.get('kind') == 'open'
            and opened.get('status') == 'sent' and opened.get('run_id') == run_id
            and opened.get('episode') == key and opened.get('entry') == attempt
            and opened.get('original_sha256') == attempt_digest(attempt)
            and opened.get('evidence') == attempt.get('evidence') and bool(attempt.get('evidence')))


class TheaterJournal:
    def __init__(self, profile, run_id):
        self.root = Path(profile) / 'theater'
        self.root.mkdir(exist_ok=True)
        self.path = self.root / 'state.json'
        self.run_id = run_id
        # Keep registration outside the mode directory, so deleting that
        # directory cannot silently replace the mode's existing history.
        registration = Path(profile) / 'theater-registration.json'
        if not registration.exists():
            if any(self.root.iterdir()):
                raise RuntimeError('月光剧场已有未登记记录；不创建空历史替代。')
            identity = uuid.uuid4().hex
            durable_json(registration, {'schema': 1, 'id': identity})
            durable_json(self.path, {'schema': 1, 'registration_id': identity,
                'attempted': {}, 'completed': {}, 'entry_dispatches': {}, 'active': None,
                'last_cleared': None, 'unresolved_entries': [], 'actions': []})
        reg = read_json(registration)
        self.state = read_json(self.path)
        s = self.state
        if (not isinstance(reg, dict) or reg.get('schema') != 1 or not isinstance(s, dict)
                or s.get('schema') != 1 or s.get('registration_id') != reg.get('id')
                or any(not isinstance(s.get(k), dict) for k in ('attempted', 'completed', 'entry_dispatches'))
                or any(not isinstance(s.get(k), list) for k in ('actions', 'unresolved_entries'))
                or not {'active', 'last_cleared'} <= s.keys()
                or (s['active'] is not None and not isinstance(s['active'], dict))):
            raise RuntimeError('月光剧场原记录丢失或损坏；不重建、不清空。')
        (self.root / 'evidence').mkdir(exist_ok=True)
        active = s['active']
        if active and active.get('run_id') != run_id:
            s['unresolved_entries'].append({'at': time.time(), 'entry': copy.deepcopy(active),
                'reason': '显式新开始，从当前画面继续；不补记旧集成功。'})
            s['active'] = None
            self.save()

    def authorize_pending_ticket_recovery(self, reading, proof, authorization, target):
        """Operator-only: call AFTER explicit human consent and a fresh audit.

        No UI automatically creates this grant. Original attempts, dispatches
        and the complete archive remain unchanged. A later failure consumes the
        exception; it cannot turn into a retry loop or a not_sent reclassification.
        """
        source = pending_ticket_source(self.state, TICKET_RECOVERY_KEY)
        if (not authorization or source is None or self.state.get('pending_ticket_recoveries')
                or reading.scene != 'theater_list' or reading.episode is None
                or reading.episode.key != TICKET_RECOVERY_KEY or reading.episode.number in reading.completed
                or reading.ticket_cost != 1 or not isinstance(reading.ticket_stock, int)
                or reading.ticket_stock < 1 or target.get('client') != 'pc'
                or any(k not in target for k in ('hwnd', 'pid', 'created', 'exe', 'title'))):
            raise TaskAttention('theater_recovery_ineligible', '本次门票恢复条件不完整', '不更改原记录，不开放重试。')
        now = time.time()
        grant = dict(id=uuid.uuid4().hex, key=TICKET_RECOVERY_KEY, status='authorized',
                     authorized_at=now, expires_at=now+900, authorization=authorization,
                     proof=proof, expected_stock=reading.ticket_stock,
                     target={k: target[k] for k in ('client', 'hwnd', 'pid', 'created', 'exe', 'title')})
        for field, value in zip(('attempt_sha256', 'archive_sha256', 'open_sha256'), source):
            grant[field] = attempt_digest(value)
        self.state.setdefault('pending_ticket_recoveries', []).append(grant)
        self.save()
        return grant

    def save(self):
        durable_json(self.path, self.state)

    def evidence(self, snapshot, observation, reading):
        path = self.root / 'evidence' / (str(time.time_ns()) + '-' + uuid.uuid4().hex[:8] + '.png')
        temporary = path.with_suffix('.png.tmp')
        with temporary.open('xb') as stream:
            snapshot.image.save(stream, format='PNG')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        durable_json(path.with_suffix('.json'), {'at': time.time(), 'captured_at': snapshot.captured_at,
            'run_id': self.run_id, 'scene': reading.scene,
            'episode': vars(reading.episode) if reading.episode else None,
            'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'width': observation.width, 'height': observation.height,
            'tokens': [vars(t) for t in observation.tokens], 'visuals': sorted(observation.visuals)})
        return str(path.relative_to(self.root))

    def observe(self, reading, proof):
        active = self.state['active']
        if not active or active['run_id'] != self.run_id:
            return False
        if reading.scene == 'theater_defeat':
            active.update(phase='failed', defeat_evidence=proof)
            self.save()
        if (reading.scene in ('theater_story', 'theater_battle')
                and active['phase'] in ('await_guide', 'story')):
            if not active.get('playback_evidence'):
                active.update(phase='story', playback_evidence=proof)
                self.save()
        if (reading.scene in ('theater_list', 'theater_empty', 'theater_next', 'theater_select_episode', 'theater_blocked') and reading.episode
                and reading.episode.series == active['series'] and active['phase'] == 'story'
                and reading.episode.season == active.get('season')
                and active['number'] in reading.completed and active.get('playback_evidence')):
            key = active['key']
            self.state['completed'][key] = {**copy.deepcopy(active), 'completed_at': time.time(),
                                           'completion_evidence': proof}
            self.state['last_cleared'] = copy.deepcopy(self.state['completed'][key])
            self.state['active'] = None
            self.save()
            return True
        return False

    def clear_operator_dispatch_path(self):
        key = (self.state.get('active') or {}).get('key', '')
        suffix = hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
        return self.root / 'overlay-dispatches' / (self.run_id + '-' + suffix + '-clear.json')

    def reward_operator_dispatch_path(self):
        path = self.clear_operator_dispatch_path()
        return path.with_name(path.name.replace('-clear.json', '-reward.json'))

    def reserve(self, kind, reading, proof):
        active = self.state['active']
        if kind == 'claim_reward' and self.reward_operator_dispatch_path().exists():
            raise TaskAttention('theater_reward_reserved', '本轮观览奖励已发送或结果不明', '保留独立领奖发送记录，不重复点击。')
        if kind == 'dismiss_clear' and self.clear_operator_dispatch_path().exists():
            raise TaskAttention('theater_clear_reserved', '本轮胜利遮罩已发送或结果不明', '保留独立遮罩发送记录，不重复点击。')
        if kind == 'recover_open':
            grant = ticket_recovery_permission(self.state, reading)
            if grant is None:
                raise TaskAttention('theater_recovery_ineligible', '单次恢复授权失效', '保留原记录，不重新入场。')
            source = pending_ticket_source(self.state, reading.episode.key)
            original = source[1]['entry']
            active = {**copy.deepcopy(original), 'run_id': self.run_id, 'phase': 'recovery_opening',
                      'recovery_id': grant['id'], 'source_run_id': original['run_id']}
            record = dict(id=uuid.uuid4().hex, status='reserved', reserved_at=time.time(),
                          recovery_id=grant['id'], source_open_sha256=grant['open_sha256'])
            # Consume before input; any unknown result must not reuse the grant.
            grant.update(status='reserved', claimed_run_id=self.run_id, record_id=record['id'], evidence=proof)
            self.state['active'] = active
        elif kind in ('open', 'open_free'):
            if kind == 'open_free':
                from theater_core import plan
                if plan(reading, self.state, self.run_id) != 'open_free':
                    raise TaskAttention('theater_free_chain', '免费入场复核失败', '不创建入场或发送输入。')
            episode = reading.episode
            details = {'key': episode.key, **vars(episode), 'run_id': self.run_id,
                       'evidence': proof, 'at': time.time()}
            record = reserve_entry(self.state, episode.key, details)
            active = {**details, 'phase': 'opening', 'steps': {}}
            self.state['active'] = active
        else:
            # A sent/unknown ticket or guide is never dispatched again. Only
            # affirmative TapNotSent proof permits an explicit resume to retry.
            previous = [r for r in self.state['actions'] if r['kind'] == kind
                        and r['run_id'] == self.run_id and r.get('key') == (active or {}).get('key')]
            if kind in ('ticket', 'guide', 'next', 'select', 'victory', 'dismiss_clear', 'claim_reward', 'close_reward_notice', 'play') and any(r['status'] != 'not_sent' for r in previous
                    if kind not in ('next', 'select') or r.get('episode') == reading.episode.key):
                raise TaskAttention('theater_dispatch_unknown', '该确认已经发送或结果不明', '保留意图与证据，不重复确认。')
            record = {'id': uuid.uuid4().hex, 'status': 'reserved', 'reserved_at': time.time()}
        record.update(kind=kind, run_id=self.run_id, key=(active or {}).get('key'), evidence=proof)
        record['episode'] = reading.episode.key if reading.episode else None
        if kind == 'ticket' and (active or {}).get('confirmation_continuation_id'):
            from theater_pending_confirmation import ticket_permission
            grant = ticket_permission(self.state, self.run_id, reading)
            if grant is None:
                raise TaskAttention('theater_confirmation_consumed', '原已打开门票接续不可重用', '不发送第二次确认。')
            record['confirmation_continuation_id'] = grant['id']
            grant.update(status='reserved', record_id=record['id'], confirmation_evidence=proof)
        self.state['actions'].append(record)
        self.save()
        return record

    def finish(self, record, status, reason=''):
        finish_dispatch(record, status, reason)
        active = self.state['active']
        if record['kind'] in ('open', 'open_free') and status == 'not_sent':
            self.state['unresolved_entries'].append({'at': time.time(), 'entry': copy.deepcopy(active),
                                                    'reason': reason})
            self.state['active'] = None
        elif status == 'sent' and active:
            phase = {'open': 'await_ticket', 'open_free': 'await_guide', 'recover_open': 'await_ticket', 'ticket': 'await_guide', 'guide': 'story'}.get(record['kind'])
            if phase:
                active['phase'] = phase
        if record.get('confirmation_continuation_id'):
            grant = next(g for g in self.state['open_ticket_continuations']
                         if g['id'] == record['confirmation_continuation_id'])
            grant.update(status=status, finished_at=time.time())
        if record['kind'] == 'recover_open':
            grant = next(g for g in self.state['pending_ticket_recoveries'] if g['id'] == record['recovery_id'])
            grant.update(status=status, finished_at=time.time())
        self.save()
