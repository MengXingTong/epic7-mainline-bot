"""One explicitly approved already-open ticket modal, never an entry retry.

The operator writes a private receipt only after human consent. The worker
consumes it under the ordinary exclusive profile locks; no UI creates receipts.
"""
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

from entry_journal import attempt_digest
from task_blockers import TaskAttention

CONFIRMATION_KEY = '没落大地|season:2|episode:7'
RECEIPT_NAME = 'pending-ticket-confirmation.json'
TARGET_FIELDS = ('client', 'hwnd', 'pid', 'created', 'exe', 'title')


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pending_source(state, *, attached=False):
    """The original immutable attempt/archive/sole sent opening, no payment."""
    key = CONFIRMATION_KEY
    legacy = '没落大地|episode:7'
    if ((not attached and state.get('active') is not None)
            or any(k in state.get('completed', {}) for k in (key, legacy))
            or legacy in state.get('attempted', {})
            or state.get('entry_dispatches', {}).get(legacy)):
        return None
    attempt = state.get('attempted', {}).get(key)
    if (not isinstance(attempt, dict) or attempt.get('key') != key
            or (attempt.get('series'), attempt.get('season'), attempt.get('number')) != ('没落大地', 2, 7)):
        return None
    archives = [a for a in state.get('unresolved_entries', []) if a.get('entry', {}).get('key') == key]
    if (len(archives) != 1 or archives[0].get('entry') != {**attempt, 'phase': 'await_ticket', 'steps': {}}):
        return None
    dispatches = state.get('entry_dispatches', {}).get(key, [])
    if len(dispatches) != 1:
        return None
    opened = dispatches[0]
    if (opened.get('kind') != 'open' or opened.get('status') != 'sent'
            or opened.get('key') != key or opened.get('episode') != key
            or opened.get('entry') != attempt or opened.get('run_id') != attempt.get('run_id')
            or opened.get('evidence') != attempt.get('evidence')
            or opened.get('original_sha256') != attempt_digest(attempt)):
        return None
    # `episode` stores the frame's selection, not the action's owning entry.
    # The previous independently completed episode may claim while row 7 is
    # already selected. Only that exact prior claim is excluded, never a
    # foreign ticket/guide/play or an uncompleted/ambiguous previous entry.
    previous_key = '没落大地|season:2|episode:6'
    completed = state.get('completed', {}).get(previous_key) or {}
    def previous_claim(action):
        return (action.get('kind') == 'claim_reward' and action.get('status') == 'sent'
                and action.get('key') == previous_key and action.get('episode') == key
                and action.get('run_id') == attempt.get('run_id')
                and 0 < action.get('finished_at', 0) <= opened.get('reserved_at', 0)
                and completed.get('key') == previous_key and completed.get('number') == 6
                and completed.get('series') == '没落大地' and completed.get('season') == 2
                and completed.get('run_id') == attempt.get('run_id')
                and completed.get('phase') == 'story' and bool(completed.get('playback_evidence'))
                and completed.get('completion_evidence') == attempt.get('evidence')
                and 0 < completed.get('completed_at', 0) <= opened.get('reserved_at', 0))
    matches = [a for a in state.get('actions', []) if a.get('key') in (key, legacy)
               or a.get('episode') in (key, legacy)]
    excluded = [a for a in matches if previous_claim(a)]
    if len(excluded) > 1:
        return None
    actions = [a for a in matches if not previous_claim(a)]
    if (actions.count(opened) != 1 or (not attached and
            (actions != [opened] or not state.get('actions') or state['actions'][-1] != opened))):
        return None
    return attempt, archives[0], opened


def continuation_grant(state, run_id):
    """Validate attached provenance without restoring or mutating anything."""
    active = state.get('active') or {}
    grants = state.get('open_ticket_continuations', [])
    if (len(grants) != 1 or active.get('run_id') != run_id
            or active.get('key') != CONFIRMATION_KEY):
        return None
    grant = grants[0]
    source = pending_source(state, attached=True)
    if (not source or grant.get('id') != active.get('confirmation_continuation_id')
            or grant.get('run_id') != run_id or grant.get('key') != CONFIRMATION_KEY
            or not grant.get('authorization') or grant.get('scope') != 'continue_existing_open_ticket_once'
            or active.get('source_run_id') != source[0].get('run_id')
            or any(active.get(k) != v for k, v in source[0].items() if k != 'run_id')
            or any(grant.get(k) != attempt_digest(v) for k, v in zip(
                ('attempt_sha256', 'archive_sha256', 'open_sha256'), source))):
        return None
    relevant = [a for a in state.get('actions', []) if a.get('key') == CONFIRMATION_KEY]
    if any(a is not source[2] and a != source[2] and a.get('run_id') != run_id for a in relevant):
        return None
    return grant


def ticket_permission(state, run_id, reading):
    grant = continuation_grant(state, run_id)
    if (not grant or grant.get('status') != 'attached'
            or not grant.get('authorized_at', 0) <= time.time() <= grant.get('expires_at', 0)
            or reading.scene != 'theater_ticket' or reading.ticket_cost != 1
            or reading.ticket_stock != grant.get('expected_stock')
            or any(a.get('key') == CONFIRMATION_KEY and a.get('kind') != 'open'
                   for a in state.get('actions', []))):
        return None
    return grant


def continued_opening(state, run_id, opened):
    """Only the validated imported opening can supply zero-input return context."""
    grant = continuation_grant(state, run_id)
    if not grant or grant.get('status') != 'sent' or attempt_digest(opened) != grant.get('open_sha256'):
        return False
    payments = [a for a in state.get('actions', []) if a.get('key') == CONFIRMATION_KEY and a.get('kind') == 'ticket']
    return (len(payments) == 1 and payments[0].get('status') == 'sent'
            and payments[0].get('run_id') == run_id and payments[0].get('id') == grant.get('record_id')
            and payments[0].get('confirmation_continuation_id') == grant.get('id'))



def opening_reading(state, evidence_root, attempt, opened, observation, reading):
    """Recompute an immutable source's existing reward-season provenance.

    A historical, read-only view of the independently completed previous
    entry is not an active restoration and cannot authorize any game input.
    """
    if reading.episode is not None:
        return reading, {'method': 'direct'}
    from theater_directory import reward_return_reading
    try:
        actions = state['actions']
        index = next(i for i, a in enumerate(actions) if a == opened)
        if index < 2:
            return reading, None
        claim, close = actions[index-2:index]
        previous = state['completed']['没落大地|season:2|episode:6']
        if ({v for v in observation.visuals if v.startswith('theater_reward_context:')}
                != {'theater_reward_context:'+claim['id']}
                or claim.get('key') != previous.get('key') or close.get('key') != previous.get('key')
                or previous.get('completion_evidence') != attempt.get('evidence')):
            return reading, None
        historical = dict(state, active=copy.deepcopy(previous), actions=copy.deepcopy(actions[:index]))
        resolved = reward_return_reading(observation, reading, historical, attempt['run_id'], evidence_root)
        source = (Path(evidence_root)/claim['evidence']).resolve()
        if not source.is_relative_to((Path(evidence_root)/'evidence').resolve()):
            return reading, None
        return resolved, dict(method='verified_historical_reward_return', claim_id=claim['id'],
            evidence=claim['evidence'], image_sha256=file_sha256(source),
            metadata_sha256=file_sha256(source.with_suffix('.json')))
    except (OSError, KeyError, ValueError, TypeError, StopIteration):
        return reading, None


def attach_receipt(journal, request, reading, proof, binding):
    """Worker-only, under its normal locks, before any intent/input.

    An absent receipt does nothing. Applied receipts never restore a second
    time, including after errors, not_sent, completion or another new Start.
    """
    if not request.get('run_dir'):
        return False
    path = Path(request['run_dir']) / RECEIPT_NAME
    if not path.exists():
        return False
    def deny():
        raise TaskAttention('theater_pending_confirmation', '已打开门票的单次接续校验失败',
                            '保留当前弹窗、授权及全部历史；不取消、不重开、不扣票。')
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
        state = journal.state
        prior = state.get('open_ticket_continuations', [])
        if prior:
            # Never reattach, even when the old active has since been archived.
            if len(prior) == 1 and prior[0].get('id') == receipt.get('id'):
                return False
            deny()
        source = pending_source(state)
        now = time.time()
        target = {k: request['target'].get(k) for k in TARGET_FIELDS}
        folder = Path(request['run_dir']).resolve()
        home = Path(request['home']).resolve()
        if (source is None or receipt.get('schema') != 1
                or receipt.get('scope') != 'continue_existing_open_ticket_once'
                or receipt.get('key') != CONFIRMATION_KEY or not receipt.get('authorization')
                or not re.fullmatch(r'[0-9a-f]{32}', receipt.get('id', ''))
                or journal.run_id != request['run_id'] or receipt.get('run_id') != journal.run_id
                or folder != home/'runs'/journal.run_id
                or not receipt.get('authorized_at', 0) <= now <= receipt.get('expires_at', 0)
                or not 0 < receipt['expires_at']-receipt['authorized_at'] <= 900
                or target.get('client') != 'pc' or any(v is None for v in target.values())
                or receipt.get('target') != target or receipt.get('binding') != asdict(binding)
                or request['settings'].get('pc_input') != 'messages' or request['settings'].get('observe') is not False
                or receipt.get('state_sha256') != file_sha256(journal.path)
                or attempt_digest(json.loads(journal.path.read_text(encoding='utf-8'))) != attempt_digest(state)
                or receipt.get('request_sha256') != file_sha256(folder/'request.json')
                or any(a.get('run_id') == journal.run_id for a in state['actions'])
                or reading.scene != 'theater_ticket' or reading.ticket_cost != 1
                or type(receipt.get('expected_stock')) is not int or receipt['expected_stock'] < 1
                or reading.ticket_stock != receipt['expected_stock']
                or any(receipt.get(k) != attempt_digest(v) for k, v in zip(
                    ('attempt_sha256', 'archive_sha256', 'open_sha256'), source))):
            deny()
        attempt, archive, opened = source
        old_run = attempt.get('run_id', '')
        if not re.fullmatch(r'[0-9a-f]{32}', old_run) or old_run == journal.run_id:
            deny()
        old_request_path = home/'runs'/old_run/'request.json'
        old_request = json.loads(old_request_path.read_text(encoding='utf-8'))
        if (receipt.get('source_request_sha256') != file_sha256(old_request_path)
                or old_request.get('run_id') != old_run
                or {k: old_request.get('target', {}).get(k) for k in TARGET_FIELDS} != target
                or Path(old_request['settings']['data_dir']).resolve() != journal.root.parent.resolve()):
            deny()
        original = (journal.root/attempt['evidence']).resolve()
        if not original.is_relative_to((journal.root/'evidence').resolve()):
            deny()
        meta_path = original.with_suffix('.json')
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        from abyss_core import Observation, Token
        from theater_core import classify
        source_observation = Observation(meta['width'], meta['height'], [Token(**t) for t in meta['tokens']],
                                         visuals=set(meta['visuals']))
        observed, resolution = opening_reading(state, journal.root, attempt, opened, source_observation, classify(source_observation))
        if (receipt.get('source_image_sha256') != file_sha256(original)
                or meta.get('image_sha256') != receipt['source_image_sha256']
                or receipt.get('source_metadata_sha256') != file_sha256(meta_path)
                or meta.get('run_id') != old_run or meta.get('scene') != 'theater_list'
                or meta.get('episode') != {k: attempt[k] for k in ('series', 'number', 'season')}
                or observed.scene != 'theater_list' or observed.episode is None
                or observed.episode.key != CONFIRMATION_KEY or observed.episode.number in observed.completed
                or observed.ticket_cost != 1 or observed.ticket_stock != receipt['expected_stock']):
            deny()
    except TaskAttention:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        deny()
    grant = {**copy.deepcopy(receipt), 'status': 'attached', 'attached_at': now,
             'receipt_sha256': file_sha256(path), 'attachment_evidence': proof, 'source_resolution': resolution}
    state['open_ticket_continuations'] = [grant]
    state['active'] = {**copy.deepcopy(archive['entry']), 'run_id': journal.run_id,
                       'source_run_id': old_run, 'confirmation_continuation_id': grant['id']}
    journal.save()  # Critical failure propagates: no input after unsuccessful persistence.
    return True
