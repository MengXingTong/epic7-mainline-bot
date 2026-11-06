"""Entry response grace is input-free; a held-key wait never authorizes replay."""
import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import runner
from assistant_worker import mainline_run
from task_timing import INTERRUPTS, TransitionPacer


class EntryResponseTimingTests(unittest.TestCase):
    def test_temporary_key_wait_preserves_original_entry_deadline(self):
        clock = Mock(return_value=100)
        pacer = TransitionPacer(clock)
        pacer.applied('team', entry=True)
        clock.return_value = 106
        pacer.input_wait_finished()
        self.assertEqual(pacer.until, 115)
        clock.return_value = 108
        self.assertTrue(pacer.waiting('team'))
        clock.return_value = 115
        self.assertFalse(pacer.waiting('team'))

    def test_repeated_input_waits_never_restart_or_extend_deadline(self):
        clock = Mock(return_value=100)
        pacer = TransitionPacer(clock)
        pacer.applied('team', entry=True)
        for instant in (105, 108, 114, 116):
            clock.return_value = instant
            pacer.input_wait_finished()
            self.assertEqual(pacer.until, 115)
        self.assertFalse(pacer.waiting('team'))

    def test_ordinary_ui_cooldown_can_still_replan_after_input_wait(self):
        pacer = TransitionPacer(lambda: 100)
        pacer.applied('support')
        pacer.input_wait_finished()
        self.assertFalse(pacer.waiting('support'))
        self.assertFalse(pacer.entry)

    def test_all_business_interrupts_outrank_preserved_entry_wait(self):
        for scene in INTERRUPTS:
            with self.subTest(scene=scene):
                pacer = TransitionPacer(lambda: 100)
                pacer.applied('team', entry=True)
                pacer.input_wait_finished()
                self.assertFalse(pacer.waiting(scene))
                self.assertFalse(pacer.entry)
                self.assertEqual(pacer.until, 0)

    def test_new_scene_or_explicit_reset_never_resurrects_old_entry_wait(self):
        for mode in ('scene', 'reset'):
            with self.subTest(mode=mode):
                pacer = TransitionPacer(lambda: 100)
                pacer.applied('team', entry=True)
                if mode == 'scene':
                    self.assertFalse(pacer.waiting('battle'))
                else:
                    pacer.reset()
                pacer.input_wait_finished()
                self.assertFalse(pacer.waiting('team'))
                self.assertFalse(pacer.entry)

    def run_worker(self, instants, expected_steps):
        instances = []
        clock = Mock(return_value=100)
        original = dict(key='synthetic-original', cost=8, stamina_before=46)
        class FakeRunner:
            def __init__(self, **kwargs):
                self.pc = None
                self.s = dict(completed={}, attempted={'keep-failure': {'outcome': 'defeat'}},
                              active=None, screen='team')
                self.ticket = None
                self.mode_since = 0
                self.input_sequence = 0
                self.frames = []
                self.steps = []
                instances.append(self)
            def start_current_screen(self):
                pass
            def capture(self):
                clock.return_value = instants[len(self.frames)]
                f = runner.Frame(runner.np.full((900, 1600, 3), 22, runner.np.uint8), [])
                self.frames.append(f)
                return f
            def step(self, f):
                self.steps.append(len(self.frames))
                if len(self.steps) == 1:
                    self.s['attempted'][original['key']] = copy.deepcopy(original)
                    self.s['active'] = copy.deepcopy(original)
                    self.s['entry_dispatches'] = {original['key']: [{'status': 'sent'}]}
                    self.input_sequence += 1
                    return True, .25
                return False, 0
            def save(self):
                pass
        control = Mock()
        story = SimpleNamespace(total_wins=lambda: 0, context=False, stage_label=lambda: '')
        pacer = TransitionPacer(clock)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=False):
            root = Path(folder)
            request = dict(run_dir=folder, settings=dict(observe=False, task='mainline', mumu={}),
                           target=dict(client='mumu', serial='fake', package='fake'))
            with patch('assistant_worker.validate_run', return_value=(root, {})), \
                 patch.object(runner, 'ROOT', root), patch.object(runner, 'Runner', FakeRunner), \
                 patch.object(runner, 'classify', return_value='team'), \
                 patch('story_core.StoryController', return_value=story), \
                 patch('assistant_worker.TransitionPacer', return_value=pacer), \
                 patch('assistant_worker.wait_for_input', side_effect=[False, True] + [False] * (len(instants) - 2)):
                mainline_run(request, control)
        current = instances[0]
        self.assertEqual(current.steps, expected_steps)
        self.assertEqual(current.input_sequence, 1)
        self.assertEqual(current.s['active'], original)
        self.assertEqual(current.s['attempted'][original['key']], original)
        self.assertEqual(current.s['attempted']['keep-failure'], {'outcome': 'defeat'})
        self.assertEqual(current.s['completed'], {})
        self.assertEqual(current.s['entry_dispatches'][original['key']], [{'status': 'sent'}])
        self.assertEqual(len(current.frames), len(instants))
        control.attention.assert_not_called()

    def test_real_worker_recaptures_after_key_wait_and_keeps_remaining_grace(self):
        self.run_worker([100, 106, 108, 116], [1, 4])

    def test_real_worker_does_not_grant_new_grace_after_long_key_wait(self):
        self.run_worker([100, 106, 116], [1, 3])


if __name__ == '__main__':
    unittest.main()
