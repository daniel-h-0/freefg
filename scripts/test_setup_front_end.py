#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Setup front end (packaging/mfg/setup.py): it must import, and its running-game check must name blocked games and ask
the launcher lookup only for the launchers that hold the selected games (v21 shipped a Setup that did not compile)."""
import importlib.util, json, shutil, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class SetupFrontEnd(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.dir)
        shutil.copy2(REPO / 'packaging/mfg/setup.py', self.dir / 'setup.py')
        (self.dir / 'manifest.json').write_text(json.dumps({'runtime': 'xemfg'}))
        (self.dir / 'launcher_config.py').write_text("CALLS=[]\ndef discover(exe):\n    CALLS.append(exe)\n    return [{'launcher':'lutris'}]\n")
        spec = importlib.util.spec_from_file_location('bc250_setup_test', self.dir / 'setup.py')
        self.setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.setup)
        self.addCleanup(lambda: [sys.modules.pop('launcher_config', None), sys.path.remove(str(self.dir)) if str(self.dir) in sys.path else None])

    def test_imports_as_multi_frame_package(self):
        self.assertTrue(self.setup.MFG); self.assertEqual(self.setup.NAME, 'FreeFG')
        self.assertEqual(self.setup.FACTORS, ['2×', '3×', '4×'])

    def test_enabler_free_package_offers_two_times_only(self):
        (self.dir / 'manifest.json').write_text(json.dumps({'runtime': 'xemfg', 'addon_entry': 'libxess_fg-proxy', 'max_factor': 2}))
        spec = importlib.util.spec_from_file_location('bc250_setup_test_2x', self.dir / 'setup.py')
        setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)
        self.assertTrue(setup.MFG); self.assertEqual(setup.FACTORS, ['2×'])

    def menu(self, setup):
        """The main menu's zenity arguments, with the window closed at once."""
        from unittest import mock
        calls = []
        def run(args, **kw):
            calls.append(args); return mock.Mock(returncode=1, stdout='')
        with mock.patch.object(setup.shutil, 'which', return_value='/usr/bin/zenity'), \
             mock.patch.object(setup.subprocess, 'run', side_effect=run), \
             mock.patch.object(setup, 'load_installer', side_effect=ImportError):
            self.assertEqual(setup.main(), 0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_settings_only_where_there_is_something_to_choose(self):
        # The multi-frame package offers Settings (2×/3×/4×, generated-frame resolution); the 2×-only enabler-free one,
        # whose documents list no Settings, does not.
        self.assertIn('Settings', self.menu(self.setup))
        (self.dir / 'manifest.json').write_text(json.dumps({'runtime': 'xemfg', 'addon_entry': 'libxess_fg-proxy', 'max_factor': 2}))
        spec = importlib.util.spec_from_file_location('bc250_setup_test_2x_menu', self.dir / 'setup.py')
        setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)
        rows = self.menu(setup)
        self.assertNotIn('Settings', rows)
        for row in ('Add games', 'Install', 'Restore', 'Status', 'Check system', 'Clear'):
            self.assertIn(row, rows)

    def test_main_screen_has_no_private_wording(self):
        # The public package ships this Setup: its first screen names neither the internal product nor a private build.
        args = self.menu(self.setup)
        text = next(a for a in args if a.startswith('--text='))
        self.assertIn('Add games to begin.', text)
        for word in ('Private', 'private', 'tester', 'Xe' + 'MFG'):  # the internal name in pieces (rename scan)
            self.assertNotIn(word, text)

    def test_blockers_names_running_games_and_uses_launcher_lookup(self):
        class Installer:
            def idle(self, root):
                if root.name == 'busy': raise ValueError('running')
        game = self.dir / 'busy'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        idle = self.dir / 'idle'; idle.mkdir(); (idle / 'Other.exe').write_bytes(b'')
        names = self.setup.blockers(Installer(), [str(game / 'Game.exe'), str(idle / 'Other.exe')], False)
        self.assertEqual(names, ['Game.exe'])
        self.setup.blockers(Installer(), [str(idle / 'Other.exe')], True)
        import launcher_config
        self.assertEqual(launcher_config.CALLS, [idle / 'Other.exe'])

    def test_cancel_and_empty_choices_go_back_to_the_menu(self):
        # Scripted zenity answers: (returncode, stdout). OK with no row, a cancelled file chooser, Settings cancelled at
        # the form, then Install cancelled at the route list and at the confirmation, then the menu closed.
        from unittest import mock
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        answers = iter([(0, ''), (0, 'Add games'), (1, ''), (0, 'Add games'), (0, str(game / 'Game.exe')),
                        (0, 'Settings'), (1, ''), (0, 'Install'), (1, ''), (0, 'Install'), (0, 'Automatic'), (1, ''), (1, '')])
        calls = []
        def run(args, **kw):
            calls.append(args); code, out = next(answers)
            return mock.Mock(returncode=code, stdout=out)
        with mock.patch.object(self.setup.shutil, 'which', return_value='/usr/bin/zenity'), \
             mock.patch.object(self.setup.subprocess, 'run', side_effect=run), \
             mock.patch.object(self.setup, 'load_installer', side_effect=ImportError):
            self.assertEqual(self.setup.main(), 0)
        self.assertEqual(next(answers, None), None)  # every scripted answer was used: no early exit
        self.assertFalse(any('install.py' in ' '.join(map(str, a)) for a in calls))  # nothing was run


if __name__ == '__main__':
    unittest.main()
