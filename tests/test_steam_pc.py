"""Steam/STOVE compatibility regression. Fakes only; never send live game input."""
from contextlib import nullcontext
import ctypes
from ctypes import wintypes
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from assistant_transport import UnifiedTransport
from assistant_worker import discover
from pc_backend import PcBackend, PcSafetyError, Win32Api, WindowSnapshot
from pc_clients import pc_distribution
from pc_message_backend import MessageWin32Api


class ClientRegistryTests(unittest.TestCase):
    def test_exact_verified_game_names_and_case_are_supported(self):
        for path, expected in (
            ('EpicSeven.exe', 'STOVE'), ('EPICSEVEN.EXE', 'STOVE'),
            ('EpicSeven_Steam.exe', 'Steam'), ('EPICSEVEN_STEAM.EXE', 'Steam'),
            (r'C:\Steam Library\steamapps\common\Epic Seven\EpicSeven_Steam.exe', 'Steam'),
            ('/games/Epic Seven/EpicSeven_Steam.exe', 'Steam'),
            (Path('EpicSeven.exe'), 'STOVE'),
        ):
            with self.subTest(path=path):
                self.assertEqual(pc_distribution(path), expected)

    def test_launcher_overlay_suffix_and_title_spoofs_are_not_game_clients(self):
        for path in ('', 'steam.exe', 'steamwebhelper.exe', 'GameOverlayUI.exe',
                     'EpicSevenLauncher.exe', 'EpicSeven_Steam.exe.bak',
                     'fake_EpicSeven_Steam.exe', 'EpicSeven_Steam2.exe',
                     r'C:\EpicSeven_Steam.exe\steam.exe', '第七史诗.exe'):
            with self.subTest(path=path):
                self.assertIsNone(pc_distribution(path))


class NativeDiscoveryTests(unittest.TestCase):
    """Exercise the real windows() filter, replacing only native API calls."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.steam = str(base/'Steam Library'/'EpicSeven_Steam.exe')
        self.other_steam = str(base/'Other'/'EpicSeven_Steam.exe')
        self.stove = str(base/'STOVE'/'EpicSeven.exe')
        self.rows = {
            10: dict(pid=20, exe=self.steam, title='第七史诗'),
            11: dict(pid=21, exe=self.stove, title='第七史诗'),
            12: dict(pid=22, exe=str(base/'steam.exe'), title='第七史诗'),
            13: dict(pid=23, exe=self.other_steam, title='第七史诗'),
            14: dict(pid=24, exe=self.steam, title='Steam'),
        }
        self.api = Win32Api.__new__(Win32Api)
        self.api.c = ctypes; self.api.w = wintypes
        self.api.dpi = lambda: nullcontext()
        self.api._windows = Mock(side_effect=lambda: list(self.rows))
        self.api._process = Mock(side_effect=lambda pid: next(
            ((r['exe'], pid*100) for r in self.rows.values() if r['pid']==pid), None))
        def title(hwnd, buf, size):
            buf.value = self.rows[hwnd]['title']; return len(buf.value)
        def pid(hwnd, ptr):
            ptr._obj.value = self.rows[hwnd]['pid']; return 1
        def rect(hwnd, ptr):
            ptr._obj.right = 1280; ptr._obj.bottom = 720; return True
        def point(hwnd, ptr):
            ptr._obj.x = -1280; ptr._obj.y = 80; return True
        self.api.u = SimpleNamespace(
            IsWindowVisible=Mock(return_value=True), IsIconic=Mock(return_value=False),
            GetWindowTextW=Mock(side_effect=title), GetWindowThreadProcessId=Mock(side_effect=pid),
            GetClientRect=Mock(side_effect=rect), ClientToScreen=Mock(side_effect=point),
            GetDpiForWindow=Mock(return_value=144),
        )

    def test_discovery_includes_both_distributions_but_not_steam_launcher(self):
        rows = self.api.windows('', '第七史诗')
        self.assertEqual([r.hwnd for r in rows], [10,11,13])
        self.assertEqual((rows[0].x, rows[0].width, rows[0].dpi), (-1280,1280,144))
        self.assertEqual(rows[0].created, 2000)

    def test_selected_steam_path_cannot_switch_to_other_install_or_stove(self):
        self.assertEqual([r.hwnd for r in self.api.windows(self.steam, '第七史诗')], [10])

    def test_selected_stove_path_does_not_match_steam(self):
        self.assertEqual([r.hwnd for r in self.api.windows(self.stove, '第七史诗')], [11])

    def test_steam_named_title_is_not_a_game_window(self):
        self.assertNotIn(14, [r.hwnd for r in self.api.windows('', '第七史诗')])

    def test_unapproved_selected_exe_is_rejected_before_enumeration(self):
        with self.assertRaises(PcSafetyError):
            self.api.windows(str(Path(self.tmp.name)/'steam.exe'), '第七史诗')
        self.api._windows.assert_not_called()

    def test_minimized_and_hidden_games_are_not_candidates(self):
        self.api.u.IsIconic.side_effect = lambda h: h==10
        self.api.u.IsWindowVisible.side_effect = lambda h: h!=13
        self.assertEqual([r.hwnd for r in self.api.windows('', '第七史诗')], [11])

    def test_unreadable_process_is_not_accepted_on_title_alone(self):
        self.api._process.return_value = None; self.api._process.side_effect = None
        self.assertEqual(self.api.windows('', '第七史诗'), [])

    def test_failed_geometry_query_is_not_a_candidate(self):
        self.api.u.GetClientRect.return_value = False; self.api.u.GetClientRect.side_effect = None
        self.assertEqual(self.api.windows('', '第七史诗'), [])


class SteamSelectionTests(unittest.TestCase):
    def setUp(self):
        self.steam = WindowSnapshot(10,20,'EpicSeven_Steam.exe',30,100,200,1280,720)
        self.stove = replace(self.steam, hwnd=11, pid=21, exe='EpicSeven.exe', created=31)
        self.api = Mock()
        self.api.windows.return_value = [self.steam, self.stove]
        self.api.ready.return_value = True
        self.api.capture.return_value = np.full((720,1280,3), 100, dtype=np.uint8)
        self.target = dict(client='pc', hwnd=10, pid=20, created=30,
                           exe=self.steam.exe, title='第七史诗')

    def transport(self):
        with patch('pc_message_backend.MessageWin32Api', return_value=self.api):
            return UnifiedTransport({'pc_input':'messages'}, self.target)

    def assert_no_input(self):
        self.api.move.assert_not_called(); self.api.button.assert_not_called()
        self.api.escape.assert_not_called()

    def test_unified_discovery_labels_steam_and_stove_as_experimental(self):
        self.api.windows.side_effect = lambda exe,title: [self.steam,self.stove] if title=='第七史诗' else []
        with patch('pc_backend.Win32Api', return_value=self.api), patch('launcher.find_adb', return_value=None):
            result = discover({})
        self.assertEqual([r['client'] for r in result], ['pc','pc'])
        self.assertIn('Steam', result[0]['label']); self.assertIn('STOVE', result[1]['label'])
        self.assertTrue(all('实验性' in r['label'] for r in result))
        self.assertEqual(result[0]['exe'], self.steam.exe)
        self.assert_no_input()

    def test_refresh_label_does_not_change_target_or_profile_identity(self):
        from assistant_selection import target_identity
        from assistant_instances import target_key, history_key
        updated = {**self.target, 'label':'Steam 桌面端（实验性）'}
        self.assertEqual(target_identity(self.target), target_identity(updated))
        self.assertEqual(target_key(self.target), target_key(updated))
        self.assertEqual(history_key(self.target), history_key(updated))
        other = {**self.target, 'hwnd':11, 'pid':21, 'created':31, 'exe':self.stove.exe}
        self.assertNotEqual(history_key(self.target), history_key(other))
        self.assertNotEqual(target_identity(self.target), target_identity({**self.target,'exe':self.stove.exe}))

    def test_steam_capture_uses_shared_background_transport_without_input(self):
        transport = self.transport()
        frame = transport.capture()
        self.assertEqual(frame.image.size, (1280,720))
        self.assertEqual(frame.binding, self.steam)
        self.assertTrue(transport.background)
        self.assert_no_input()

    def test_steam_disappears_does_not_select_stove(self):
        transport = self.transport(); self.api.windows.return_value = [self.stove]
        with self.assertRaises(PcSafetyError): transport.capture()
        self.assert_no_input()

    def test_recycled_steam_window_is_rejected(self):
        self.api.windows.return_value = [replace(self.steam,created=99), self.stove]
        with self.assertRaises(PcSafetyError): self.transport()
        self.assert_no_input()

    def test_new_process_lifetime_invalidates_bound_steam(self):
        transport = self.transport()
        self.api.windows.return_value = [replace(self.steam,created=99), self.stove]
        with self.assertRaises(PcSafetyError): transport.capture()
        self.assert_no_input()

    def test_changed_geometry_after_capture_does_not_authorize_input(self):
        transport = self.transport(); frame = transport.capture()
        self.api.windows.return_value = [replace(self.steam,x=101), self.stove]
        with self.assertRaises(PcSafetyError): transport._fresh(frame)
        self.assert_no_input()

    def test_steam_does_not_restore_foreground_mode(self):
        with self.assertRaises(PcSafetyError): UnifiedTransport({'pc_input':'foreground'}, self.target)
        self.assert_no_input()

    def test_mainline_uses_same_exact_selected_steam_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = dict(game_exe=self.steam.exe, selected_window=self.steam.identity(),
                       authorization_mode='selected_target', experimental_input_enabled=True)
            backend = PcBackend(cfg, Path(folder)/'STOP', api=self.api)
            backend.authorize_selected_target(self.steam.identity())
            self.assertEqual(backend.capture().shape, (720,1280,3))
            self.api.windows.return_value = [self.stove]
            with self.assertRaises(PcSafetyError): backend.capture()
        self.assert_no_input()

    def test_mainline_read_only_steam_cannot_send_input(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = PcBackend(dict(game_exe=self.steam.exe,selected_window=self.steam.identity()),
                                Path(folder)/'STOP', api=self.api, read_only=True)
            backend.capture()
            with self.assertRaises(PcSafetyError): backend.tap(800,450)
        self.assert_no_input()

    def test_mainline_stop_still_blocks_steam(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = Path(folder)/'STOP'; stop.write_text('user stop')
            backend = PcBackend(dict(game_exe=self.steam.exe), stop, api=self.api)
            with self.assertRaises(PcSafetyError): backend.capture()
        self.assert_no_input()


class SteamWindowClassTests(unittest.TestCase):
    def ready(self, class_name='GLFW30', foreground=False, minimized=False):
        snap = WindowSnapshot(10,20,'EpicSeven_Steam.exe',30,100,200,1280,720)
        api = MessageWin32Api.__new__(MessageWin32Api)
        api.target = None; api.u = Mock()
        api.u.IsWindowVisible.return_value = True
        api.u.IsIconic.return_value = minimized
        api.windows = Mock(return_value=[snap])
        probe = Mock()
        probe.inspect.return_value = SimpleNamespace(class_name=class_name,width=1280,height=720,
                                                     title='第七史诗',foreground=foreground)
        with patch('pc_message_backend.MessageProbe', return_value=probe):
            result = api.ready(snap)
        api.u.PostMessageW.assert_not_called(); api.u.SetForegroundWindow.assert_not_called()
        api.u.SetCursorPos.assert_not_called(); api.u.SendInput.assert_not_called()
        return result

    def test_verified_steam_glfw_window_can_be_unfocused(self):
        self.assertTrue(self.ready())

    def test_unknown_steam_window_class_is_not_allowed(self):
        self.assertFalse(self.ready(class_name='Chrome_WidgetWin_1'))

    def test_minimized_steam_is_not_allowed(self):
        self.assertFalse(self.ready(minimized=True))


class SteamLegacyAndPackagingTests(unittest.TestCase):
    def test_legacy_settings_accept_steam_without_changing_history(self):
        from pc_launcher import load_settings
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = dict(attempted={'old':{'outcome':'defeat'}},completed={},active={'key':'old'})
            path = root/'state.json'; path.write_text(json.dumps(state),encoding='utf-8')
            before = path.read_bytes()
            cfg = dict(backend='stove_pc',data_dir=str(root),
                       pc=dict(game_exe=str(root/'EpicSeven_Steam.exe'), server='test', account_id='123'))
            settings = root/'config.json'; settings.write_text(json.dumps(cfg),encoding='utf-8')
            result, data, history = load_settings(settings)
            self.assertEqual(result['backend'], 'stove_pc')
            self.assertEqual(data, root.resolve()); self.assertEqual(history, state)
            self.assertEqual(path.read_bytes(), before)

    def test_registry_is_in_complete_and_incremental_package_allowlist(self):
        import build_portable
        self.assertEqual(build_portable.SOURCES.count('pc_clients.py'), 1)


if __name__=='__main__': unittest.main()
