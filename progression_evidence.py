"""Causal progression evidence: observations are not input effects.

This module never sends input or grants entry/retry permission.  A transparent
observation (including an unrecognized transition) cannot erase an earlier
milestone.  Only the current independently verified result can complete a run;
contradictory gameplay or unaccounted input still blocks that result.
"""
from dataclasses import dataclass, field
from enum import IntEnum
import hashlib
import json


class StoryPhase(IntEnum):
    OPENING = 0
    PLAYBACK = 1
    REWARD = 2
    DISMISSED = 3
    RETURNED = 4


# One semantic boundary for old and new journals.  An event's self-declared
# effect is never trusted for an action not present in this registry.
STORY_EFFECTS = {
    '观看故事（仅一次）': 'story_open',
    '跳过剧情': 'story_skip',
    '确认跳过剧情': 'story_skip_confirm',
    '关闭已发放的免费奖励遮罩': 'story_reward_close',
    '确认已免费加入的故事英雄（不配置或消耗英雄）': 'free_story_hero_accept',
}
READ_ONLY_EVENTS = frozenset({
    'preflight', 'skip_control_verified', 'skip_control_cancelled',
    'capture_display_fallback', 'navigation_input_not_sent',
    'control_pixels_changed', 'control_pixels_expired',
})
# These are positive contradictions, not a whitelist of every possible frame.
STORY_CONTRADICTIONS = frozenset({
    'defeat', 'battle', 'victory', 'settlement', 'legacy_story_clear',
    'legacy_story_exit', 'post_clear_exit', 'lobby', 'date_change_notice',
    'resource_stop', 'capacity_stop', 'chat_panel', 'team', 'support',
})


@dataclass(frozen=True)
class EvidenceDecision:
    status: str  # proven / pending / blocked; pending permits observation ONLY
    code: str
    reason: str
    phase: str
    proof: dict = field(default_factory=dict)

    @property
    def proven(self):
        return self.status == 'proven'

    def diagnostic(self):
        return dict(status=self.status, code=self.code, reason=self.reason, phase=self.phase)


def story_effect(action):
    return STORY_EFFECTS.get(action)


def story_result_trace(events, key, *, require_open=True, require_return=True, opening_messages=()):
    """Fold a scoped, ordered journal into monotonic result milestones.

    Natural playback and explicit skipping have the same result contract.
    Loading/black-frame recovery/unknown observations contribute no progress,
    but also no fictional failure. Unknown *actions*, navigation, stop and
    contradictory gameplay do invalidate the causal chain. A returned map is
    not proof of completion: the caller must ALSO verify original entry,
    same-run binding, durable evidence and current independent map markers.
    """
    events = list(events)
    phase = StoryPhase.OPENING
    opened = False
    opening_actions = ['观看故事（仅一次）', *opening_messages]
    opening_index = 0
    milestones = []

    def decision(status, code, reason):
        return EvidenceDecision(status, code, reason, phase.name.lower(), dict(
            milestones=list(milestones),
            events_sha256=hashlib.sha256(json.dumps(events, ensure_ascii=False, sort_keys=True).encode()).hexdigest()))

    for index, event in enumerate(events):
        kind = event.get('kind')
        if kind == 'screen':
            scene = event.get('screen')
            if scene in STORY_CONTRADICTIONS:
                return decision('blocked', 'contradictory_scene', '原剧情链中出现了不相符的实际流程：' + scene)
            if scene not in ('story', 'story_reward', 'map'):
                # No input is authorized on these frames. Current-page guards
                # still run first; historical observation is not an input.
                continue
            if event.get('stage') != key:
                # A pre-opening map can have no active stage yet.
                if scene == 'map' and phase == StoryPhase.OPENING and not opened:
                    continue
                return decision('blocked', 'foreign_stage', '结果观察不属于原剧情节点。')
            if scene == 'story':
                if require_open and opening_index != len(opening_actions):
                    return decision('blocked', 'playback_before_open', '剧情播放缺少对应的原入口消息。')
                if phase > StoryPhase.PLAYBACK:
                    return decision('blocked', 'playback_rewound', '奖励后再次出现剧情播放，不能认领为同一次结果。')
                if phase < StoryPhase.PLAYBACK:
                    phase = StoryPhase.PLAYBACK
                    milestones.append(dict(kind='playback', event_index=index))
            elif scene == 'story_reward':
                if phase < StoryPhase.PLAYBACK:
                    return decision('blocked', 'reward_without_playback', '免费奖励前没有本节点的播放证据。')
                if phase < StoryPhase.REWARD:
                    phase = StoryPhase.REWARD
                    milestones.append(dict(kind='reward', event_index=index))
            elif phase >= StoryPhase.DISMISSED and phase < StoryPhase.RETURNED:
                phase = StoryPhase.RETURNED
                milestones.append(dict(kind='returned_map', event_index=index))
        elif kind == 'action':
            if event.get('stage') != key:
                return decision('blocked', 'foreign_input', '存在其他节点的输入，不能归于原剧情结果。')
            action = event.get('action')
            effect = story_effect(action)
            if opening_index < len(opening_actions) and action == opening_actions[opening_index]:
                effect = 'story_open'
            if not effect or event.get('effect', effect) != effect:
                return decision('blocked', 'unaccounted_input', '存在未核实的输入效果：' + str(event.get('action')))
            if effect == 'story_open':
                if (phase != StoryPhase.OPENING or opening_index >= len(opening_actions)
                    or action != opening_actions[opening_index]):
                    return decision('blocked', 'extra_open', '同一结果链存在额外打开入口。')
                opened = True
                opening_index += 1
                milestones.append(dict(kind='opening_message', event_index=index))
            elif effect == 'story_reward_close':
                if phase < StoryPhase.REWARD:
                    return decision('blocked', 'close_without_reward', '奖励关闭缺少先行的完整奖励页。')
                if phase == StoryPhase.REWARD:
                    phase = StoryPhase.DISMISSED
                    milestones.append(dict(kind='reward_dismissal', event_index=index))
            elif phase != StoryPhase.PLAYBACK:
                return decision('blocked', 'out_of_phase_input', '剧情输入不处于对应的播放阶段。')
        elif kind in READ_ONLY_EVENTS:
            if kind == 'navigation_input_not_sent' and event.get('proof') != 'TapNotSent_before_button_down':
                return decision('blocked', 'unproved_not_sent', '输入取消没有按下前未发送的明确证明。')
        else:
            return decision('blocked', 'unaccounted_event', '存在未归类的流程或输入事件：' + str(kind))

    required = StoryPhase.RETURNED if require_return else StoryPhase.DISMISSED
    if phase < required:
        return decision('pending', 'missing_milestone', '尚缺少完整剧情奖励、关闭及返回地图的独立证据。')
    return decision('proven', 'recorded_story_result', '原剧情播放、奖励关闭与返回链完整。')
