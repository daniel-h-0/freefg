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
        from unittest.mock import patch
        fake_spec=importlib.util.spec_from_file_location('launcher_config',self.dir/'launcher_config.py')
        fake=importlib.util.module_from_spec(fake_spec);fake_spec.loader.exec_module(fake)
        modules=patch.dict(sys.modules,{'launcher_config':fake});modules.start();self.addCleanup(modules.stop)
        self.addCleanup(lambda: sys.path.remove(str(self.dir)) if str(self.dir) in sys.path else None)

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

    def test_two_times_package_exposes_scaling_when_capable(self):
        (self.dir / 'manifest.json').write_text(json.dumps({'runtime':'xemfg', 'addon_entry':'libxess_fg-proxy',
            'max_factor':2, 'files':{'payload/BC250-XeFG/shaders/freefg-scaling.required':{}}}))
        spec=importlib.util.spec_from_file_location('bc250_setup_test_scaling', self.dir / 'setup.py')
        setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
        self.assertEqual(setup.FACTORS,['2×']);self.assertTrue(setup.SCALING)
        rows=self.menu(setup)
        self.assertIn('Settings',rows)
        self.assertIn('Choose 2× and generated-frame resolution',rows)

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
        # the form, then Install cancelled at the route list, at the upscaler list and at the confirmation, Upscaler
        # cancelled at its list, then the menu closed.
        from unittest import mock
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        answers = iter([(0, ''), (0, 'Add games'), (1, ''), (0, 'Add games'), (0, str(game / 'Game.exe')),
                        (0, 'Settings'), (1, ''), (0, 'Install'), (1, ''), (0, 'Install'), (0, 'Automatic'), (1, ''),
                        (0, 'Install'), (0, 'Automatic'), (0, 'FSR 4'), (1, ''), (0, 'Upscaler'), (1, ''), (1, '')])
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

    def test_check_runs_the_installers_check(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        calls, commands = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Check'), (0, ''), (1, '')])
        # Check prints the redacted game report too (CONTRIBUTING.md and the issue form point to Setup's Check for it).
        self.assertEqual([c[2:] for c in commands], [[str(self.dir / 'install.py'), 'check', '--report', str(game / 'Game.exe')]])
        self.assertTrue(any('--text-info' in c for c in calls))
        menu = calls[0]
        self.assertIn('Check', menu)

    def test_install_shows_verdicts_steps_and_asks_for_soft_refusals(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        verdict = dict(line='Automatic (no recipe) → DLSS FG input (needs one step from you)', needs_step=True,
                       manual_steps=['Choose the upscaler.', 'Turn on the game\'s own frame generation.'],
                       blocking=[dict(code='protonfix-api', kind='soft', text='GE-Proton11-7\'s fix switches it off DirectX 12.',
                                      way='Install anyway adds PROTONFIXES_DISABLE=1.')])

        class Installer:
            def compat_verdict(self, root, exe, route=None, fg_input=None):
                return verdict, {}, {}, {}

            def idle(self, root):
                pass
        answers = [(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Install'), (0, 'Automatic per game'), (0, 'FSR 4'), (0, ''), (0, ''), (0, ''), (1, '')]
        calls, commands = self.scripted(answers, Installer())
        route_list = next(c for c in calls if '--column=Route' in c)
        self.assertIn('Automatic per game', route_list)
        self.assertTrue(any('Game.exe: Automatic (no recipe)' in a for a in route_list))
        question = next(c for c in calls if '--ok-label=Install anyway' in c)
        self.assertTrue(any('GE-Proton11-7' in a for a in question))
        confirm = next(c for c in calls if any(a.startswith('--text=Setup will configure') for a in c))
        self.assertTrue(any("2. Turn on the game's own frame generation." in a for a in confirm))
        install = next(c for c in commands if 'install' in c)
        self.assertEqual(install[install.index('--accept') + 1], 'protonfix-api=' + str(game / 'Game.exe'))

    def test_soft_refusals_are_listed_and_accepted_per_game(self):
        # Two games share a soft code, and more games are selected than the route list shows: every one is evaluated
        # and listed, and each accept names its game. An explicit input asks for the verdicts again for that input.
        games = []
        for n in range(14):
            folder = self.dir / f'g{n}'; folder.mkdir(); (folder / f'G{n}.exe').write_bytes(b''); games.append(folder / f'G{n}.exe')
        soft = lambda name: dict(code='protonfix-api', kind='soft', text=f'{name} fix leaves DirectX 12.', way='Install anyway adds it.')
        asked = []

        class Installer:
            def compat_verdict(self, root, exe, route=None, fg_input=None):
                asked.append((exe.name, route, fg_input))
                blocking = [soft(exe.name)] if exe.name in ('G0.exe', 'G13.exe') else []
                if route == 'opti' and exe.name == 'G5.exe':
                    blocking = [dict(code='no-input', kind='soft', text='No input found.', way='Install anyway (you chose the input).')]
                return dict(line='Automatic (no recipe) → OptiFG input', needs_step=False, manual_steps=[], blocking=blocking), {}, {}, {}

            def idle(self, root):
                pass
        answers = [(0, 'Add games'), (0, '\n'.join(map(str, games))), (0, 'Install'), (0, 'OptiFG'), (0, 'FSR 4'), (0, ''), (0, ''), (0, ''), (1, '')]
        calls, commands = self.scripted(answers, Installer())
        self.assertEqual(len([a for a in asked if a[1] is None]), 14)  # Automatic, for the route list
        self.assertEqual(len([a for a in asked if a[1:] == ('opti', 'upscaler')]), 14)  # again for the input chosen
        route_list = next(c for c in calls if '--column=Route' in c)
        self.assertTrue(any('... and 2 more (Check lists every game)' in a for a in route_list))
        question = next(c for c in calls if '--ok-label=Install anyway' in c)
        text = next(a for a in question if a.startswith('--text='))
        for name in ('G0.exe: G0.exe fix', 'G13.exe: G13.exe fix', 'G5.exe: No input found.'):
            self.assertIn(name, text)
        install = next(c for c in commands if 'install' in c)
        accepts = [install[i + 1] for i, a in enumerate(install) if a == '--accept']
        self.assertEqual(sorted(accepts), sorted(['protonfix-api=' + str(games[0]), 'protonfix-api=' + str(games[13]),
                                                  'no-input=' + str(games[5])]))

    def anticheat_installer(self):
        """A fake installer: games named Cheat*.exe ship BattlEye; Both.exe ships it and is 32-bit; CheatSoft.exe and Soft.exe
        have a soft refusal; CheatDetect.exe has no input found (hard for Automatic, soft for an explicit input); others are
        clean. compat_verdict records each call; the override (accept_risk) lifts only the anti-cheat refusal."""
        class Installer:
            RISK_SENTENCE = 'I accept that my account may be banned'
            asked = []

            def compat_verdict(self, root, exe, route=None, fg_input=None, accept_risk=()):
                self.asked.append((exe.name, route, fg_input, list(accept_risk)))
                refusal = dict(code='anticheat', kind='risk', text='This game ships anti-cheat: BattlEye (BattlEye/).', names=['BattlEye'],
                               way='An override for this one game, at the risk of a ban: Override anti-cheat refusal...')
                ac = exe.name.startswith('Cheat') or exe.name == 'Both.exe'
                blocking = [refusal] if ac and 'anticheat' not in accept_risk else []
                if exe.name == 'Both.exe':
                    blocking.append(dict(code='32bit', kind='hard', text='This is a 32-bit game.', way='None.'))
                if exe.name in ('Soft.exe', 'CheatSoft.exe'):
                    blocking.append(dict(code='protonfix-api', kind='soft', text='GE fix leaves DirectX 12.', way='Install anyway adds it.'))
                if exe.name == 'CheatDetect.exe':
                    blocking.append(dict(code='no-input', kind='soft' if route else 'hard', text='No input found.',
                                         way='None inside this build.' + (' Install anyway (you chose the input).' if route else '')))
                line = ('Not supported: ' + blocking[0]['text']) if blocking and blocking[0]['kind'] != 'soft' else 'Automatic (no recipe) → OptiFG input'
                return dict(line=line, needs_step=ac, manual_steps=['Choose the upscaler.', 'Step for ' + exe.name + '.'], blocking=blocking,
                            refusals=[refusal] if ac else [], risk_accepted=['anticheat'] if ac and 'anticheat' in accept_risk else []), {}, {}, {}

            @staticmethod
            def anticheat_names(verdict):
                return next((r['names'] for r in verdict.get('refusals', []) if r['code'] == 'anticheat'), [])

            @staticmethod
            def anticheat_warning(game, names, product=None):
                return game + ' ships anti-cheat: ' + ', '.join(names) + '. ' + str(product) + ' does not hide itself.'

            @classmethod
            def risk_confirmed(cls, text):
                return isinstance(text, str) and text.strip() == cls.RISK_SENTENCE

            def idle(self, root):
                pass
        return Installer()

    def games(self, *names):
        out = []
        for name in names:
            folder = self.dir / name.lower().removesuffix('.exe'); folder.mkdir(); (folder / name).write_bytes(b''); out.append(folder / name)
        return out

    def test_install_never_offers_the_anticheat_refusal(self):
        # Install lists only soft refusals under Install anyway; an anti-cheat game stays refused (no accept, no steps).
        # The soft refusal of a game the anti-cheat keeps out is not offered either.
        cheat, soft, cheat_soft = self.games('Cheat.exe', 'Soft.exe', 'CheatSoft.exe')
        calls, runs = self.scripted([(0, 'Add games'), (0, f'{cheat}\n{soft}\n{cheat_soft}'), (0, 'Install'), (0, 'Automatic per game'),
                                     (0, 'FSR 4'), (0, ''), (0, ''), (0, ''), (1, '')], self.anticheat_installer())
        self.assertIn(self.setup.RISK_ACTION, calls[0])
        question = next(a for a in next(c for c in calls if '--ok-label=Install anyway' in c) if a.startswith('--text='))
        self.assertIn('Soft.exe: GE fix', question)
        self.assertNotIn('CheatSoft.exe', question)
        self.assertNotIn('anti-cheat', question)
        confirm = next(a for c in calls for a in c if a.startswith('--text=Setup will configure'))
        self.assertNotIn('Step for Cheat.exe', confirm)
        [run] = runs
        self.assertEqual(run[3:7], ['install', str(cheat), str(soft), str(cheat_soft)])
        self.assertNotIn('anticheat', ' '.join(run))
        self.assertIn('protonfix-api=' + str(soft), run)
        self.assertNotIn('protonfix-api=' + str(cheat_soft), run)

    def test_override_warns_asks_for_the_sentence_and_installs_one_game(self):
        cheat, cheat2, clean = self.games('Cheat.exe', 'Cheat2.exe', 'Clean.exe')
        installer = self.anticheat_installer()
        sentence = installer.RISK_SENTENCE
        calls, runs = self.scripted([(0, 'Add games'), (0, f'{cheat}\n{cheat2}\n{clean}'), (0, self.setup.RISK_ACTION), (0, str(cheat2)),
                                     (0, ''), (0, sentence), (0, 'Automatic per game'), (0, 'FSR 4'), (0, ''), (0, ''), (1, '')], installer)
        choose = next(c for c in calls if '--column=Anti-cheat' in c)  # one game at a time, from the anti-cheat games only
        self.assertIn(str(cheat), choose); self.assertIn(str(cheat2), choose); self.assertNotIn(str(clean), choose)
        warning = next(c for c in calls if '--question' in c and any('ships anti-cheat' in a for a in c))
        self.assertIn('--default-cancel', warning)
        self.assertIn('--cancel-label=Cancel', warning)
        self.assertTrue(any(a.startswith(f'--text=Cheat2.exe ships anti-cheat: BattlEye. {self.setup.NAME} does not hide itself.') for a in warning))
        entry = next(c for c in calls if '--entry' in c)
        self.assertTrue(any(sentence in a for a in entry))
        self.assertLess(calls.index(warning), calls.index(entry))
        # The Install dialogs that follow are for that game, with the override applied to its verdict only.
        self.assertIn(('Cheat2.exe', None, None, ['anticheat']), installer.asked)
        self.assertNotIn(('Cheat.exe', None, None, ['anticheat']), installer.asked)
        confirm = next(a for c in calls for a in c if a.startswith('--text=Setup will configure'))
        self.assertIn('Step for Cheat2.exe', confirm)
        self.assertIn('overridden for this game only', confirm)
        [run] = runs
        self.assertEqual(run[3:], ['install', str(cheat2), '--route', 'auto', '--fg-input', 'auto', '--upscaler', 'fsr4',
                                   '--accept-anticheat-risk=' + str(cheat2), '--confirm-anticheat-risk', sentence])

    def test_override_cancelled_or_mismatched_installs_nothing(self):
        cheat, = self.games('Cheat.exe')
        start = [(0, 'Add games'), (0, str(cheat)), (0, self.setup.RISK_ACTION)]
        for answers in ([(1, '')],                                   # Cancel at the warning (its default button)
                        [(0, ''), (1, '')],                          # the sentence dialog cancelled
                        [(0, ''), (0, 'I accept'), (0, '')],         # a mismatch, then its notice
                        [(0, ''), (0, 'i accept that my account may be banned'), (0, '')],
                        [(0, ''), (0, 'I accept that my account may be banned'), (1, '')]):  # matched, then the input list cancelled
            calls, runs = self.scripted(start + answers + [(1, '')], self.anticheat_installer())
            self.assertEqual(runs, [], answers)

    def test_override_needs_a_game_refused_only_for_anticheat(self):
        clean, both = self.games('Clean.exe', 'Both.exe')
        for game, kind in ((clean, '--info'), (both, '--error')):
            calls, runs = self.scripted([(0, 'Add games'), (0, str(game)), (0, self.setup.RISK_ACTION), (0, ''), (1, '')], self.anticheat_installer())
            self.assertEqual(runs, [])
            self.assertIn(kind, calls[-2])
            self.assertFalse(any('--entry' in c for c in calls))
        self.assertTrue(any('32-bit' in a for a in calls[-2]))

    def test_override_offers_the_soft_refusals_of_that_game(self):
        # A soft refusal beside the anti-cheat is no reason to turn the override away: after the warning and the sentence,
        # Install anyway lists it for that game, and the run carries both its accept and the override.
        cheat_soft, = self.games('CheatSoft.exe')
        sentence = self.anticheat_installer().RISK_SENTENCE
        calls, runs = self.scripted([(0, 'Add games'), (0, str(cheat_soft)), (0, self.setup.RISK_ACTION), (0, ''), (0, sentence),
                                     (0, 'Automatic per game'), (0, 'FSR 4'), (0, ''), (0, ''), (0, ''), (1, '')], self.anticheat_installer())
        self.assertFalse(any('--error' in c for c in calls))
        question = next(a for a in next(c for c in calls if '--ok-label=Install anyway' in c) if a.startswith('--text='))
        self.assertIn('CheatSoft.exe: GE fix', question)
        [run] = runs
        self.assertEqual(run[3:], ['install', str(cheat_soft), '--route', 'auto', '--fg-input', 'auto', '--upscaler', 'fsr4',
                                   '--accept', 'protonfix-api=' + str(cheat_soft),
                                   '--accept-anticheat-risk=' + str(cheat_soft), '--confirm-anticheat-risk', sentence])

    def test_override_leaves_detection_refusals_to_the_input_chosen(self):
        # No input found: refused for Automatic (after the sentence, saying how to go on), soft once the input is chosen.
        game, = self.games('CheatDetect.exe')
        sentence = self.anticheat_installer().RISK_SENTENCE
        start = [(0, 'Add games'), (0, str(game)), (0, self.setup.RISK_ACTION), (0, ''), (0, sentence)]
        calls, runs = self.scripted(start + [(0, 'Automatic per game'), (0, 'FSR 4'), (0, ''), (1, '')], self.anticheat_installer())
        self.assertEqual(runs, [])
        error = next(c for c in calls if '--error' in c)
        self.assertTrue(any('also refused for another reason: No input found.' in a and 'instead of Automatic' in a for a in error))
        calls, runs = self.scripted(start + [(0, 'OptiFG'), (0, 'FSR 4'), (0, ''), (0, ''), (0, ''), (1, '')], self.anticheat_installer())
        [run] = runs
        self.assertEqual(run[3:], ['install', str(game), '--route', 'opti', '--fg-input', 'upscaler', '--upscaler', 'fsr4',
                                   '--accept', 'no-input=' + str(game), '--accept-anticheat-risk=' + str(game), '--confirm-anticheat-risk', sentence])

    def scripted(self, answers, installer=None, returncode=0):
        """Run Setup's menu on scripted zenity answers, with a fake installer or none (load_installer fails); returns
        (zenity calls, install.py runs). install.py runs (subprocess.run or Popen) take no answer and end with returncode;
        nothing may open a network connection. self.shown: the texts the text-info dialogs showed."""
        from unittest import mock
        import socket
        answers = iter(answers); calls = []; runs = []; self.shown = []
        def run(args, **kw):
            if args[0] == sys.executable:
                runs.append(args); return mock.Mock(returncode=0)
            calls.append(args); code, out = next(answers)
            if '--text-info' in args:
                self.shown += [Path(a.split('=', 1)[1]).read_text() for a in args if a.startswith('--filename=')]
            return mock.Mock(returncode=code, stdout=out)
        class Process:
            def __init__(self, args, **kw):
                runs.append(args)
            def wait(self):
                return returncode
            def communicate(self, *a, **k):
                return b'', b''
        def no_network(*a, **k):
            raise AssertionError('Setup opened a network connection')
        with mock.patch.object(self.setup.shutil, 'which', return_value='/usr/bin/zenity'), \
             mock.patch.object(self.setup.subprocess, 'run', side_effect=run), \
             mock.patch.object(self.setup.subprocess, 'Popen', side_effect=Process), \
             mock.patch.object(socket, 'create_connection', no_network), mock.patch.object(socket.socket, 'connect', no_network), \
             mock.patch.object(self.setup, 'load_installer', return_value=installer) if installer else \
             mock.patch.object(self.setup, 'load_installer', side_effect=ImportError):
            self.assertEqual(self.setup.main(), 0)
        self.assertEqual(next(answers, None), None)
        return calls, [r for r in runs if 'install.py' in ' '.join(map(str, r))]

    def helix_installer(self, state):
        class HelixSR:
            LABEL = 'HelixSR (by lonewolf0622)'
            @staticmethod
            def find(root):
                return dict(state=state, pinned='2.0.0', folder='/cache/HelixSR-2.0.0', message='m')
            @staticmethod
            def pins(root):
                return {'input': {'size': 136997025}}
            @staticmethod
            def guidance(found):
                return 'cd /cache/HelixSR-2.0.0 && ./helixsr-setup.sh --no-fg'
        class Installer:
            helixsr = HelixSR
            def idle(self, root):
                pass
            def detect_input(self, exe):
                return ('opti', 'upscaler', 'OptiFG')
        return Installer()

    def test_install_with_helixsr_ready_passes_the_choice(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        calls, runs = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Install'), (0, 'OptiFG'),
                                     (0, 'HelixSR (by lonewolf0622)'), (0, ''), (0, ''), (1, '')], self.helix_installer('ready'))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][-6:], ['--route', 'opti', '--fg-input', 'upscaler', '--upscaler', 'helixsr'])
        listing = next(c for c in calls if '--column=Upscaler' in c)
        self.assertIn('HelixSR (by lonewolf0622)', listing)
        self.assertTrue(any('separate project by lonewolf0622' in a for a in listing))

    def test_helixsr_missing_downloads_on_request_and_installs_nothing(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        # HelixSR chosen, download confirmed (install.py helixsr runs), its output shown; back at the menu, nothing installed.
        calls, runs = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Install'), (0, 'OptiFG'),
                                     (0, 'HelixSR (by lonewolf0622)'), (0, ''), (0, ''), (1, '')], self.helix_installer('missing'))
        self.assertEqual([r[-1] for r in runs], ['helixsr'])
        question = next(c for c in calls if '--question' in c)
        self.assertTrue(any('github.com/lonewolf0622/HelixSR' in a and '137 MB' in a for a in question))
        # Declined: nothing runs at all.
        calls, runs = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Install'), (0, 'OptiFG'),
                                     (0, 'HelixSR (by lonewolf0622)'), (1, ''), (1, '')], self.helix_installer('missing'))
        self.assertEqual(runs, [])

    def test_helixsr_unknown_offers_the_official_download(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        # Only another HelixSR on this computer: Setup offers the official release (and says which folder is not used).
        calls, runs = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Upscaler'),
                                     (0, 'HelixSR (by lonewolf0622)'), (0, ''), (0, ''), (1, '')], self.helix_installer('unknown'))
        self.assertEqual([r[-1] for r in runs], ['helixsr'])
        question = next(c for c in calls if '--question' in c)
        self.assertTrue(any(a.startswith('--text=Not used: m') for a in question))

    def test_helixsr_unbuilt_shows_the_setup_command(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        calls, runs = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Upscaler'),
                                     (0, 'HelixSR (by lonewolf0622)'), (0, ''), (1, '')], self.helix_installer('unbuilt'))
        self.assertEqual(runs, [])
        self.assertTrue(any('--text-info' in c for c in calls))

    def test_upscaler_switch_runs_configure(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        calls, runs = self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Upscaler'), (0, 'FSR 4'), (0, ''), (1, '')],
                                    self.helix_installer('missing'))
        self.assertEqual(len(runs), 1); self.assertIn('configure', runs[0]); self.assertEqual(runs[0][-2:], ['--upscaler', 'fsr4'])

    def library_installer(self, games):
        class Installer:
            def library(self):
                return list(games)
            def idle(self, root):
                pass
        return Installer()

    def test_update_all_shows_the_plan_then_updates_every_installed_game(self):
        # No selection needed: the installer's library and the selected games, the plan first, then one confirmation.
        installed = self.dir / 'installed'; installed.mkdir(); (installed / 'A.exe').write_bytes(b'')
        chosen = self.dir / 'chosen'; chosen.mkdir(); (chosen / 'B.exe').write_bytes(b'')
        games = sorted([str(installed / 'A.exe'), str(chosen / 'B.exe')])
        calls, runs = self.scripted([(0, 'Add games'), (0, str(chosen / 'B.exe')), (0, 'Update all'), (0, ''), (0, ''), (0, ''), (1, '')],
                                    self.library_installer([installed / 'A.exe']))
        self.assertEqual([r[2:] for r in runs], [[str(self.dir / 'install.py'), 'plan', *games], [str(self.dir / 'install.py'), 'update', *games]])
        self.assertTrue(any('--question' in c and '--ok-label=Update' in c for c in calls))
        # Back at the confirmation: the plan was shown, nothing is updated.
        calls, runs = self.scripted([(0, 'Update all'), (0, ''), (1, ''), (1, '')], self.library_installer([installed / 'A.exe']))
        self.assertEqual([r[3] for r in runs], ['plan'])

    def test_update_all_with_no_installed_game_says_so(self):
        calls, runs = self.scripted([(0, 'Update all'), (0, ''), (1, '')], self.library_installer([]))
        self.assertEqual(runs, []); self.assertTrue(any('--info' in c and any('No game with' in a for a in c) for c in calls))

    def test_update_upscalers_uses_the_same_scope_for_preview_and_apply(self):
        game = self.dir / 'installed'; game.mkdir(); (game / 'A.exe').write_bytes(b'')
        calls, runs = self.scripted([(0, 'Update upscalers'), (0, ''), (0, ''), (0, ''), (1, '')],
                                    self.library_installer([game / 'A.exe']))
        self.assertEqual([r[3] for r in runs], ['plan', 'update'])
        for run in runs:
            self.assertEqual(run[run.index('--component')+1], 'upscaler')
            self.assertIn(str(game / 'A.exe'), run)

    def test_a_refusal_says_that_nothing_was_changed(self):
        # install.py's exit status 3: refused before anything changed (a running game, a refusal), which the closing
        # note says instead of pointing at interrupted updates.
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        for code, words in ((3, 'Nothing was changed in the games named above'), (1, 'Some games could not complete')):
            self.scripted([(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Rollback'), (0, ''), (1, '')],
                          self.library_installer([]), returncode=code)
            self.assertIn(words, self.shown[-1])

    def test_a_window_toolkit_that_does_not_load_leaves_the_dialogs(self):
        # gi's RepositoryError is an Exception of its own (neither ImportError nor ValueError): the dialogs are Setup.
        import io
        from unittest import mock
        (self.dir / 'setup_app.py').write_text("class RepositoryError(Exception):\n    pass\n"
                                               "raise RepositoryError('Typelib file for namespace Adw does not load')\n")
        (self.dir / 'setup_model.py').write_text('')
        with mock.patch.dict(sys.modules), mock.patch.dict('os.environ', {'FREEFG_SETUP_UI': ''}), \
                mock.patch('sys.stderr', io.StringIO()) as err:
            sys.modules.pop('setup_app', None); sys.modules.pop('setup_model', None)
            self.assertIsNone(self.setup.desktop_app(None, None))
        self.assertIn('RepositoryError', err.getvalue())

    def wiki_installer(self, rows):
        class Installer:
            def wiki_settings_plan(self, root, exe):
                return dict(format=1, digest='c' * 64, rows=rows)
            def idle(self, root):
                pass
        return Installer()

    def test_wiki_settings_checklist_applies_the_rows_chosen(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        rows = [dict(id='r1', key='Hotfix.A', value='1', current=None, action='prefill', reason='Optional'),
                dict(id='r2', key='FrameGen.B', value='2', current='auto', action='conditional', reason='Confirm first',
                     confirmations=['The game renders with DirectX 12']),
                dict(id='r3', key='Hotfix.C', value='1', current='1', action='prefill', reason='Already set'),
                dict(id='r4', key='Libraries.X', value='y', current=None, action='advice', reason='Not offered'),
                dict(id='r5', key='hotfix.a', value='2', current=None, action='prefill', reason='Another value')]
        start = [(0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Wiki settings')]
        calls, runs = self.scripted(start + [(0, 'r1\nr2'), (0, ''), (0, ''), (1, '')], self.wiki_installer(rows))
        checklist = next(c for c in calls if '--checklist' in c)
        self.assertIn('r1', checklist); self.assertIn('Hotfix.A = 1', checklist)
        self.assertNotIn('r3', checklist); self.assertNotIn('r4', checklist)  # already set, or not offered
        question = next(c for c in calls if '--question' in c)
        self.assertTrue(any('FrameGen.B: The game renders with DirectX 12' in a for a in question))
        self.assertEqual([r[3:] for r in runs], [['wiki-apply', str(game / 'Game.exe'), '--wiki-plan-digest', 'c' * 64,
                                                  '--wiki-setting', 'r1', '--wiki-setting', 'r2', '--wiki-confirm', 'r2']])
        # Two values for one setting, the conditions not confirmed, or nothing chosen: nothing runs.
        for answers in ([(0, 'r1\nr5'), (0, '')], [(0, 'r2'), (1, '')], [(1, '')]):
            calls, runs = self.scripted(start + answers + [(1, '')], self.wiki_installer(rows))
            self.assertEqual(runs, [], answers)
        self.assertEqual(self.scripted(start + [(0, '')] + [(1, '')], self.wiki_installer([]))[1], [])

    def test_rollback_runs_on_the_selected_games(self):
        game = self.dir / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'')
        calls, runs = self.scripted([(0, 'Rollback'), (0, ''), (0, 'Add games'), (0, str(game / 'Game.exe')), (0, 'Rollback'), (0, ''), (1, '')],
                                    self.library_installer([]))
        self.assertEqual([r[2:] for r in runs], [[str(self.dir / 'install.py'), 'rollback', str(game / 'Game.exe')]])


if __name__ == '__main__':
    unittest.main()
