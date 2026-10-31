#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Setup's desktop app: its model (packaging/mfg/setup_model.py) against real installations of the fixture packages,
and the window module (setup_app.py), which must compile wherever the tests run (GTK or not: v21 shipped a Setup that
did not compile). The model decides what each game's page says and which install.py command each choice runs, so these
tests pin both."""
import importlib.util, json, os, py_compile, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from test_update import UpdateFixture, OLD, NEW, m

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_model', REPO / 'packaging/mfg/setup_model.py')
model = importlib.util.module_from_spec(spec); spec.loader.exec_module(model)


def context(package, installer=m, **kw):
    path = Path(package) / 'manifest.json'
    manifest = json.loads(path.read_text()) if path.is_file() else {'name': 'freefg-1.1.6'}
    return model.Context(package, 'FreeFG', manifest, installer, factors=['2×'], scaling=True, **kw)


class Words(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(model.version('freefg-1.1.6'), '1.1.6')
        self.assertEqual(model.version('freefg-1.1.3.1'), '1.1.3.1')
        self.assertEqual(model.version('lumen-pace-2.0'), '2.0')  # a renamed product keeps its numbers
        self.assertEqual(model.version('bc250-fsr4-xemfg-private-test-25'), 'bc250-fsr4-xemfg-private-test-25')
        self.assertEqual(model.version(None), 'unknown release')

    def test_preview_labels_and_order_match_installer(self):
        self.assertEqual(model.version('freefg-1.2.0-preview'),'1.2.0-preview')
        ordered=['freefg-1.1.6','freefg-1.2.0-preview','freefg-1.2.0','freefg-1.2.0.1-preview','freefg-1.2.0.1']
        for name in ordered:
            self.assertEqual(model.release_number(name),m.release_number(name))
        self.assertEqual(sorted(ordered,key=model.release_number),ordered)
        self.assertIsNone(model.release_number('freefg-1.2.0-preview-extra'))
        ctx=model.Context(Path('/package'),'FreeFG',{'name':'freefg-1.2.0-preview'},m)
        final=model.Game(Path('/game/Game.exe'),record={'status':'installed','package':'freefg-1.2.0'})
        self.assertEqual(model.state(final,ctx),'newer')

    def test_install_arguments_name_each_game_for_its_accepts_and_override(self):
        exe = Path('/games/A/A.exe')
        self.assertEqual(model.install_args(exe, model.InstallChoice()),
                         ['install', str(exe), '--route', 'auto', '--fg-input', 'auto', '--upscaler', 'fsr4'])
        choice = model.InstallChoice('dlssg', 'hlx-dlss', ['--helixsr', '/prepared'], ['protonfix-api'],
                                     'I accept that my account may be banned')
        self.assertEqual(model.install_args(exe, choice),
                         ['install', str(exe), '--route', 'opti', '--fg-input', 'dlssg', '--upscaler', 'hlx-dlss', '--helixsr',
                          '/prepared', '--accept', 'protonfix-api=' + str(exe), '--accept-anticheat-risk=' + str(exe),
                          '--confirm-anticheat-risk', 'I accept that my account may be banned'])
        self.assertEqual(model.install_args(exe, model.InstallChoice('native'))[2:4], ['--route', 'native'])
        self.assertEqual(model.input_choice('fsrfg30'), ('opti', 'fsrfg30'))
        self.assertEqual(model.input_choice('auto'), (None, None))

    def test_settings_arguments_carry_only_what_changed(self):
        before = model.Settings()
        self.assertEqual(model.settings_args(before, model.Settings()), [])
        self.assertEqual(model.settings_args(before, model.Settings(size='scale', percent=67)), ['--percent', '67'])
        self.assertEqual(model.settings_args(model.Settings(size='scale', percent=67), model.Settings(size='scale', percent=80)),
                         ['--percent', '80'])
        self.assertEqual(model.settings_args(model.Settings(size='scale'), model.Settings()), ['--resolution', 'output'])
        self.assertEqual(model.settings_args(before, model.Settings(size='1440', downscale='area', upscale='fsr1')),
                         ['--limit', '1440', '--downscale', 'area', '--upscale', 'fsr1'])
        self.assertEqual(model.settings_args(before, model.Settings(factor=3)), ['--factor', '3'])

    def test_verdict_words(self):
        hard = dict(code='32bit', kind='hard', text='This is a 32-bit game.', way='Nothing.')
        risk = dict(code='anticheat', kind='risk', text='This game ships anti-cheat: BattlEye.', way='Override…', names=['BattlEye'])
        soft = dict(code='protonfix-api', kind='soft', text='A fix leaves DirectX 12.', way='Install anyway adds it.')
        self.assertEqual(model.verdict_badge(dict(tier='R', blocking=[risk, hard], refusals=[risk, hard])), ('Not supported', 'error'))
        self.assertEqual(model.verdict_badge(dict(tier='R', blocking=[risk], refusals=[risk])), ('Anti-cheat', 'error'))
        self.assertEqual(model.verdict_badge(dict(tier='D', blocking=[soft], refusals=[soft])), ('Needs your OK', 'warning'))
        self.assertEqual(model.verdict_badge(dict(tier='A', blocking=[], refusals=[])), ('Verified', 'success'))
        self.assertIsNone(model.verdict_badge(dict(tier='D', blocking=[], refusals=[])))
        self.assertEqual(model.verdict_view(dict(tier='R', blocking=[hard], refusals=[hard]))[:2], ('error', 'Not supported'))
        self.assertEqual(model.anticheat(dict(refusals=[soft, risk])), risk)
        self.assertEqual(model.verdict_view(None)[1], 'Not checked')

    def test_a_game_not_installed_says_whether_install_can_run(self):
        ok = dict(tier='A', blocking=[], refusals=[], route='opti', fg_input='dlssg', needs_step=True)
        self.assertEqual(model.ready_view(ok), ('success', 'Verified on BC-250',
                                                'Ready to install · DLSS FG input · needs one step from you'))
        self.assertEqual(model.ready_view(dict(ok, tier='D', route='native', needs_step=False)),
                         ('accent', 'Ready to install', 'Automatic · Native XeSS FG'))
        soft = dict(code='protonfix-api', kind='soft', text='A fix leaves DirectX 12.', way='w')
        # A verdict that a soft refusal blocks has tier R; it is still not "Not supported" (the player can accept it).
        self.assertEqual(model.ready_view(dict(ok, tier='R', blocking=[soft], refusals=[soft]))[:2], ('warning', 'Needs your OK'))
        self.assertEqual(model.verdict_view(dict(ok, tier='R', name='Not supported', blocking=[soft], refusals=[soft]))[1],
                         'Needs your OK')

    def test_the_anticheat_override_is_offered_only_where_it_can_help(self):
        risk = dict(code='anticheat', kind='risk', text='t', way='w', names=['BattlEye'])
        detected = dict(code='no-input', kind='hard', text='No input found.', way='w')
        other = dict(code='32bit', kind='hard', text='This is a 32-bit game.', way='w')
        self.assertTrue(model.override_available(dict(blocking=[risk], refusals=[risk])))
        self.assertTrue(model.override_available(dict(blocking=[risk, detected], refusals=[risk, detected])))
        self.assertFalse(model.override_available(dict(blocking=[risk, other], refusals=[risk, other])))
        self.assertFalse(model.override_available(dict(blocking=[], refusals=[])))
        self.assertTrue(model.detection_only(dict(code='api-dx11')))
        self.assertEqual(model.joined(['Game.exe', 'Steam']), 'Game.exe and Steam')
        self.assertEqual(model.joined(['A', 'B', 'C']), 'A, B and C')

    def test_results_name_the_installers_reason_and_steps(self):
        lines = [('out', 'Frame-generation input: OptiFG'), ('err', 'Close the game before installing, updating or restoring'),
                 ('out', '')]
        self.assertEqual(model.failure_reason(lines), 'Close the game before installing, updating or restoring')
        self.assertEqual(model.failure_reason([('out', 'Done.')]), 'Done.')
        self.assertEqual(model.next_steps([('out', 'In game: open OptiScaler with Insert.'), ('out', 'Installed.'),
                                           ('out', 'Game setting pending: x (start the game once)')]),
                         ['In game: open OptiScaler with Insert.', 'Game setting pending: x (start the game once)'])
        # What a finished update or install changed: the plan's change lines and the lines naming what was set.
        update = [('out', 'Game.exe'), ('out', '  frame generation add-on: 3 replaced, 1 new file'), ('out', '    menu.blur: x'),
                  ('out', '  original-file backups and user settings are retained'),
                  ('out', 'Updated to freefg-1.1.6. Launch the game as before.'), ('err', '  not from stdout')]
        self.assertEqual(model.summary_lines(update), ['frame generation add-on: 3 replaced, 1 new file',
                                                       'original-file backups and user settings are retained'])
        install = [('out', 'Frame-generation input: OptiFG (Automatic)'), ('out', 'Installed. Open your launcher.'),
                   ('out', 'Launch option added: -dx12'), ('out', 'Upscaler: FSR 4 (BC-250 build RC12).')]
        self.assertEqual(model.summary_lines(install), ['Frame-generation input: OptiFG (Automatic)',
                                                        'Launch option added: -dx12', 'Upscaler: FSR 4 (BC-250 build RC12).'])

    def test_a_game_without_a_launcher_entry_asks_for_its_launch_settings(self):
        # Installed with no-launcher accepted: the installer's 'In your launcher:' step is one of the next steps, and the
        # settings below it are not counted among what changed.
        settings = dict(env={'WINEDLLOVERRIDES': 'dxgi=n,b', 'VK_LAYER_PATH': '/games/My Game/BC250-XeFG/layer'}, args=['-dx12'])
        lines = [('out', 'Installed. No launcher entry was changed.'),
                 *[('out', line) for line in m.manual_launch_lines('set these for the game before you play:', settings)],
                 ('out', 'Upscaler: FSR 4 (BC-250 build RC12).'), ('out', 'In game: open OptiScaler with Insert.')]
        self.assertEqual(model.next_steps(lines), ['In your launcher: set these for the game before you play:',
                                                   'In game: open OptiScaler with Insert.'])
        self.assertEqual(model.summary_lines(lines), ['Upscaler: FSR 4 (BC-250 build RC12).'])
        self.assertEqual([line for _, line in lines[2:5]], ['    WINEDLLOVERRIDES=dxgi=n,b', "    VK_LAYER_PATH='/games/My Game/BC250-XeFG/layer'",
                                                           '    Game arguments (after the .exe): -dx12'])

    def test_plan_lines_split_into_changes_and_notes(self):
        lines = ['Update freefg-1.1.5 → freefg-1.1.6:', '  OptiScaler integration: 1 replaced file', '  OptiScaler.ini: update owned settings',
                 '    upscalers.dx12upscaler: ffx → hlx-dlss', '    menu.blur: (unset) → auto', '  original-file backups and user settings are retained',
                 'Recipe refresh: Dead as Disco; opti/fsrfg.']
        changes, notes = model.split_plan(lines)
        self.assertEqual(changes, [('OptiScaler integration: 1 replaced file', []),
                                   ('OptiScaler.ini: update owned settings', ['upscalers.dx12upscaler: ffx → hlx-dlss', 'menu.blur: (unset) → auto']),
                                   ('original-file backups and user settings are retained', [])])
        self.assertEqual(notes, ['Recipe refresh: Dead as Disco; opti/fsrfg.'])

    def test_system_check_runs_apart_and_summarises(self):
        rows = [['OK', 'GPU', 'AMD BC-250'], ['WARN', 'gamescope', '3.15 (older)'], ['INFO', 'Kernel', '7.3']]
        run = Mock(return_value=Mock(stdout='noise\n' + json.dumps(rows) + '\n'))
        ctx = context(REPO / 'packaging')
        found = model.system_checks(ctx, run=run)
        self.assertEqual(found, [tuple(r) for r in rows])
        command = run.call_args[0][0]
        self.assertEqual(command[:2], [sys.executable, '-c'])  # never in Setup's own process (Vulkan through ctypes)
        self.assertEqual(model.system_summary(found, 'FreeFG')[:2], ('warning', '1 item needs attention'))
        self.assertEqual(model.system_summary([('OK', 'GPU', 'x')], 'FreeFG')[:2], ('success', 'Ready for FreeFG'))
        broken = model.system_checks(ctx, run=Mock(side_effect=OSError('no')))
        self.assertEqual(broken[0][0], 'WARN')

    def test_providers_follow_the_package_and_preparation(self):
        class HLX:
            NAMES = {'hlx-dlss': 'HLX DLSS', 'hlx-fsr4': 'HLX FSR 4'}
            @staticmethod
            def catalog(root):
                return {'format': 1}
            @staticmethod
            def find(root, provider, explicit=None):
                if provider == 'hlx-fsr4':
                    raise ValueError('Prepare HLX 3.1.0 once: missing /cache/x')
                return {'version': '3.1.0'}, Path('/cache/HelixSR-3.1.0'), {}
        found = model.providers(context(REPO / 'packaging', installer=Mock(hlx=HLX)))
        self.assertEqual([(p.id, p.state, p.version) for p in found],
                         [('fsr4', 'ready', None), ('hlx-dlss', 'ready', '3.1.0'), ('hlx-fsr4', 'unprepared', None)])
        self.assertIn('missing', found[2].detail)

        class Helix:
            @staticmethod
            def find(root):
                return dict(state='unbuilt', pinned='2.0.0', folder='/cache/HelixSR-2.0.0', message='Run its setup once.')
        legacy = model.providers(context(REPO / 'packaging', installer=Mock(hlx=None, helixsr=Helix)))
        self.assertEqual([(p.id, p.state) for p in legacy], [('fsr4', 'ready'), ('helixsr', 'unbuilt')])

    def test_window_module_compiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            py_compile.compile(str(REPO / 'packaging/mfg/setup_app.py'), cfile=str(Path(temporary) / 'app.pyc'), doraise=True)

    def test_events_are_read_and_the_text_is_the_fallback(self):
        line = lambda **fields: model.EVENT_PREFIX + json.dumps(dict(v=1, **fields))
        self.assertEqual(model.parse_event(line(type='outcome', exe='/g/A.exe', result='install')),
                         dict(v=1, type='outcome', exe='/g/A.exe', result='install'))
        for other in ('Installed.', model.EVENT_PREFIX + '{not json', model.EVENT_PREFIX + '[1]',
                      model.EVENT_PREFIX + json.dumps(dict(v=2, type='step', text='x')), model.EVENT_PREFIX + '{"v": 1}'):
            self.assertIsNone(model.parse_event(other), other)
        # The installer's lines as an installer without events prints them: Setup reads them as before.
        lines = [('out', 'Frame-generation input: OptiFG (Automatic)'), ('out', 'Upscaler: FSR 4 (BC-250 build RC12).'),
                 ('out', 'In game: open OptiScaler with Insert.'), ('out', 'Game setting pending: x (start the game once)')]
        plain = model.outcome(lines)
        self.assertEqual((plain['result'], plain['manual']), (None, []))
        self.assertEqual(plain['changed'], ['Frame-generation input: OptiFG (Automatic)', 'Upscaler: FSR 4 (BC-250 build RC12).'])
        self.assertEqual(plain['steps'], ['In game: open OptiScaler with Insert.', 'Game setting pending: x (start the game once)'])
        # With events, each type the installer sends replaces the reading of its lines; a type it sends none of does not.
        settings = dict(env={'WINEDLLOVERRIDES': 'dxgi=n,b'}, args=['-dx12'])
        events = [dict(v=1, type='changed', text='OptiScaler.ini: 3 settings'), dict(v=1, type='step', where='game', text='open OptiScaler with Insert.'),
                  dict(v=1, type='step', where='launcher', text='In your launcher: add the settings.'),
                  dict(v=1, type='step', where='setting', text='Game setting pending: y'),
                  dict(v=1, type='manual', action='set', settings=settings), dict(v=1, type='manual', action='set', settings=dict(env=[])),
                  dict(v=1, type='manual', action='erase', settings=settings), dict(v=1, type='outcome', exe='/g/A.exe', result='install')]
        found = model.outcome(lines, events)
        self.assertEqual(found['result'], 'install')
        self.assertEqual(found['changed'], ['OptiScaler.ini: 3 settings'])
        self.assertEqual(found['steps'], ['In game: open OptiScaler with Insert.', 'In your launcher: add the settings.', 'Game setting pending: y'])
        self.assertEqual(found['manual'], [('set', settings)])  # malformed settings and unknown actions are not shown
        only_outcome = model.outcome(lines, [dict(v=1, type='outcome', exe='/g/A.exe', result='install')])
        self.assertEqual((only_outcome['changed'], only_outcome['steps']), (plain['changed'], plain['steps']))

    def test_commands_ask_for_events_where_the_installer_prints_them(self):
        ctx = context(REPO / 'packaging')
        command = ctx.command(['install', '/g/A.exe', '--route', 'auto'])
        self.assertEqual(command[3:], ['install', '/g/A.exe', '--route', 'auto', '--events'])  # last: never among the games
        older = context(REPO / 'packaging', installer=Mock(spec=['STATE']))
        self.assertEqual(older.command(['status', '/g/A.exe'])[3:], ['status', '/g/A.exe'])

    def test_launch_forms_come_from_the_launcher_helpers(self):
        import launcher_config
        settings = dict(env={'WINEDLLOVERRIDES': 'dxgi=n,b', 'VK_LAYER_PATH': '/games/My Game/BC250-XeFG/layer'}, args=['-dx12'],
                        required_args=['-nobattleye'], remove=['XEFG_GAME_PROFILE'])
        forms = model.launch_forms(settings)
        self.assertEqual(forms['line'], launcher_config.manual_steam_line(settings))
        self.assertEqual(forms['table'], list(settings['env'].items()))
        self.assertEqual((forms['args'], forms['remove'], forms['merge']), (['-dx12', '-nobattleye'], ['XEFG_GAME_PROFILE'], False))
        self.assertEqual(forms['text'], launcher_config.manual_lines(settings))
        self.assertTrue(model.launch_forms(dict(settings, merge=[dict(var='VK_LAYER_PATH', op='prepend', value='x', sep=':')]))['merge'])
        self.assertIsNone(model.launch_forms(dict(args=[])))
        self.assertEqual(model.manual_settings(dict(manual_launch=settings)), settings)
        self.assertIsNone(model.manual_settings(dict(manual_launch=settings, launchers=[dict(launcher='steam')])))
        self.assertIsNone(model.manual_settings(dict(manual_launch=dict(env='x'))))

    def test_manual_activation_is_the_installers_reading(self):
        record = dict(status='installed', manual_launch=dict(env={'A': '1'}, args=[]))
        reading = Mock(return_value=(False, 'Not yet confirmed: no session since installation.'))
        ctx = context(REPO / 'packaging', installer=Mock(manual_activation=reading))
        self.assertEqual(model.manual_activation(ctx, record, {'found': False}), (False, 'Not yet confirmed: no session since installation.'))
        reading.assert_called_once_with(record, {'found': False})
        self.assertIsNone(model.manual_activation(ctx, dict(record, manual_launch=None), None))  # a launcher installation
        self.assertIsNone(model.manual_activation(context(REPO / 'packaging', installer=Mock(spec=['STATE'])), record, None))
        reading.side_effect = ValueError('unreadable log')
        self.assertIsNone(model.manual_activation(ctx, record, None))

    def test_wiki_rows_that_set_one_key_are_rivals(self):
        rows = [dict(id='a', key='FrameGen.Mode', value='1'), dict(id='b', key='framegen.mode', value='2'),
                dict(id='c', key='FrameGen.Mode', value='1'), dict(id='d', key='Hotfix.Other', value='1')]
        self.assertEqual(model.wiki_rivals(rows), {'a': ['b'], 'b': ['a', 'c'], 'c': ['b'], 'd': []})

    def test_rollback_words_name_what_it_undoes(self):
        release = dict(kind='release', release='freefg-1.1.4', settings=[], upscaler=None, missing=False)
        self.assertEqual(model.change_words(release)[0], 'Roll back to 1.1.4')
        self.assertEqual(model.change_words(release)[2], 'Roll back to 1.1.4?')
        wiki = dict(release, kind='settings', settings=[('Hotfix.ColorResourceBarrier', '4')])
        self.assertEqual(model.change_words(wiki)[0], 'Undo wiki settings (Hotfix.ColorResourceBarrier = 4)')
        self.assertIn('Hotfix.ColorResourceBarrier = 4', model.change_words(wiki)[3])
        many = dict(wiki, settings=[(f'K.{n}', str(n)) for n in range(5)])
        self.assertEqual(model.change_words(many)[0], 'Undo wiki settings (K.0 = 0, K.1 = 1, K.2 = 2 and 2 more)')
        provider = dict(release, kind='provider', upscaler='FSR 4')
        self.assertEqual(model.change_words(provider)[:3], ('Undo the upscaler switch', 'Back to FSR 4, byte for byte. Your settings are kept.',
                                                            'Undo the upscaler switch?'))
        self.assertIsNone(model.change_words(dict(release, missing=True))[2])


class Installations(UpdateFixture):
    """Real installations of the fixture's release OLD, seen by Setup running from the package of release NEW."""
    def setUp(self):
        super().setUp()
        m.install(self.package, self.exe, route='opti')
        self.ctx = context(self.new)

    def load(self, **kw):
        return model.load_game(self.ctx, self.exe, titles={}, **kw)

    def state_file(self):
        return self.exe.parent / m.STATE / 'state.json'

    def test_an_earlier_release_is_offered_as_an_update(self):
        game = self.load(tracked=True)
        self.assertTrue(game.installed)
        self.assertEqual(model.state(game, self.ctx), 'update')
        self.assertEqual(model.badge(game, self.ctx), ('Update', 'accent'))
        self.assertEqual(model.subtitle(game, self.ctx), '1.1.4 · FSR 4')
        level, title, text = model.headline(game, self.ctx)
        self.assertEqual((level, title), ('accent', 'Update available'))
        self.assertIn('1.1.4 → 1.1.5', text)
        self.assertEqual(model.input_label(game.record), 'OptiFG')

    def test_the_current_release_needs_nothing(self):
        ctx = context(self.package)
        game = model.load_game(ctx, self.exe, titles={})
        self.assertEqual(model.state(game, ctx), 'installed')
        self.assertIsNone(model.badge(game, ctx))
        self.assertEqual(model.headline(game, ctx)[1], 'FreeFG 1.1.4 is installed')

    def test_pinned_interrupted_unavailable_and_restored_games(self):
        record = self.record(); record['update_pin'] = dict(package=OLD, at='now')
        self.state_file().write_text(json.dumps(record))
        self.assertEqual(model.state(self.load(), self.ctx), 'pinned')
        self.assertIn('although 1.1.5 is available', model.headline(self.load(), self.ctx)[2])
        record.pop('update_pin'); record['pending_update'] = {'generation': 'g', 'kind': 'update'}
        self.state_file().write_text(json.dumps(record))
        game = self.load()
        self.assertEqual((model.state(game, self.ctx), model.badge(game, self.ctx)), ('recovery', ('Needs recovery', 'error')))
        self.assertEqual(model.headline(game, self.ctx)[1], 'An update was interrupted')
        record.pop('pending_update'); self.state_file().write_text(json.dumps(record))
        self.exe.rename(self.exe.with_suffix('.moved'))
        game = self.load()
        self.assertEqual(model.state(game, self.ctx), 'unavailable')
        self.assertIn('drive connected', game.reason)
        self.exe.with_suffix('.moved').rename(self.exe)
        m.restore(self.exe)
        game = self.load()
        self.assertEqual(model.state(game, self.ctx), 'available')
        self.assertEqual(model.headline(game, self.ctx)[1], 'Checking compatibility…')
        game.checked, game.verdict = True, dict(tier='D', blocking=[], refusals=[], route='opti', fg_input='upscaler')
        self.assertEqual(model.headline(game, self.ctx)[1:], ('Original files restored', 'Install FreeFG again any time.'))

    def test_settings_are_read_from_the_game_folder(self):
        m.configure(self.exe, percent=67, upscale='fsr1', downscale='area')
        game = self.load()
        self.assertEqual(game.settings, model.Settings(size='scale', percent=67, downscale='area', upscale='fsr1', factor=2))
        m.configure(self.exe, limit=1440)
        self.assertEqual(self.load().settings.size, '1440')
        support = model.settings_support(game.record, 2)
        self.assertEqual((support['scaling'], support['area'], support['upscale'], support['factors']), (True, True, True, [2]))

    def test_integrity_names_changed_program_files_only(self):
        game = self.load()
        self.assertEqual(model.integrity(self.ctx, game)['changed'], [])
        m.configure(self.exe, percent=60)  # settings are the user's to change
        self.assertEqual(model.integrity(self.ctx, game)['changed'], [])
        (self.game / 'libxess_fg.dll').write_bytes(b'another tool')
        self.assertEqual(model.integrity(self.ctx, game)['changed'], ['libxess_fg.dll'])
        self.assertEqual(model.integrity(self.ctx, game)['launchers'], [('Heroic', 'installed')])

    def test_integrity_names_each_launcher_entry_state(self):
        # A removed entry is not found (not "changed"); a launcher file of another shape is a finding, never a check
        # that does not end (Health's spinner).
        game = self.load()
        doc = json.loads(self.config.read_text())
        states = []
        for change in (lambda d: d['123']['enviromentOptions'].append(dict(key='MY_OWN', value='1')), lambda d: d.pop('123'),
                       lambda d: d.__setitem__('123', [])):
            data = json.loads(json.dumps(doc)); change(data); self.config.write_text(json.dumps(data))
            states.append(model.integrity(self.ctx, game)['launchers'])
        self.config.write_text('{"123": ')
        states.append(model.integrity(self.ctx, game)['launchers'])
        self.config.unlink()
        states.append(model.integrity(self.ctx, game)['launchers'])
        self.assertEqual(states, [[('Heroic', 'changed')], [('Heroic', 'missing')], [('Heroic', 'unreadable')],
                                  [('Heroic', 'unreadable')], [('Heroic', 'missing')]])
        lutris = self.root / 'lutris.yml'
        for text in ('system: {env: [', '- a list\n'):
            lutris.write_text(text)
            game.record['launchers'] = [dict(launcher='lutris', path=str(lutris), after={})]
            self.assertEqual(model.integrity(self.ctx, game)['launchers'], [('Lutris', 'unreadable')], text)

    def test_hlx_reuse_check_ends_without_a_record(self):
        # The page was drawn before a Restore or a removed record: the dialog shows the shared preparation, no error.
        game = self.load()
        unprepared = [model.Provider('hlx-fsr4', 'HLX FSR 4', 'local', state='unprepared')]
        with patch.object(m.hlx, 'catalog', return_value=dict(version='3.1.0', providers={})):
            self.state_file().unlink()
            self.assertEqual(model.game_providers(self.ctx, game, unprepared), unprepared)

    def test_launch_settings_of_a_manual_installation_come_from_events_or_the_record(self):
        m.restore(self.exe); self.config.unlink()
        self.run_quiet(m.install, self.package, self.exe, route='opti', accept=('no-launcher',))
        settings = self.record()['manual_launch']
        printed = [('out', line) for line in m.manual_launch_lines('set these.', settings)]
        # An installer without manual events: its step in the player's launcher, and the record names the settings.
        for command, action in (('install', 'set'), ('restore', 'remove'), ('update', 'replace'), ('rollback', 'replace')):
            found = model.command_outcome(self.ctx, [command, str(self.exe)], printed)
            self.assertEqual(found['manual'], [(action, settings)], command)
        self.assertEqual(model.command_outcome(self.ctx, ['install', str(self.exe)], [('out', 'Installed.')])['manual'], [])
        self.assertEqual(model.command_outcome(self.ctx, ['hlx', '--dlss-input', 'x'], printed)['manual'], [])
        # Manual events are the installer's word, also when they name none.
        event = dict(v=1, type='manual', action='replace', settings=dict(settings, env={'WINEDLLOVERRIDES': 'winmm=n,b'}))
        self.assertEqual(model.command_outcome(self.ctx, ['update', str(self.exe)], printed, [event])['manual'],
                         [('replace', event['settings'])])
        game = self.load()
        self.assertEqual(model.manual_settings(game.record), settings)
        # The installer's own reading of the last session (install.manual_activation), as Status prints it.
        self.assertEqual(game.activation, (False, 'Not yet confirmed: no session since installation shows them. Start the game '
                                                  'with them and frame generation on.'))

    def test_plan_digest_reaches_the_update_where_the_installer_checks_it(self):
        game = self.load()
        self.assertIsNone(model.plan_game(self.ctx, game).digest)
        with patch.object(m, 'plan_digest', create=True, return_value='ab' * 32) as digest:
            item = model.plan_game(self.ctx, game)
        self.assertEqual(digest.call_args.args[0]['status'], 'update')
        self.assertEqual(model.update_args(self.exe, expect=item.digest)[2:], ['--expect-plan', 'ab' * 32])
        with patch.object(m, 'plan_digest', create=True, return_value='not a digest'):
            self.assertIsNone(model.plan_game(self.ctx, game).digest)

    def test_update_plan_lists_changes_and_running_games(self):
        game = self.load()
        item = model.plan_game(self.ctx, game)
        self.assertEqual((item.status, item.source, item.target, item.group), ('update', OLD, NEW, 'update'))
        self.assertTrue(any('frame generation add-on' in change for change, _ in item.changes))
        self.assertEqual(model.plan_reason(item, self.ctx), '1.1.4 → 1.1.5')
        with patch.object(m, 'idle', side_effect=m.GameRunningError('Close the game')):
            running = model.plan_game(self.ctx, game)
        self.assertEqual((running.status, running.group), ('running', 'running'))
        self.assertIn('close the game first', model.plan_reason(running, self.ctx))
        self.run_quiet(m.update, self.exe, self.new)
        current = model.plan_game(self.ctx, self.load())
        self.assertEqual((current.status, current.group), ('current', 'current'))
        self.assertEqual(model.plan_reason(current, self.ctx), 'Up to date (1.1.5)')
        # A change within the same release (a recipe refresh) names the release once.
        same = model.PlanItem(self.exe, 'Game', 'update', source=NEW, target=NEW)
        self.assertEqual(model.plan_reason(same, self.ctx), 'Changes within 1.1.5')
        self.assertEqual(model.state(self.load(), self.ctx), 'installed')
        self.assertEqual(model.update_args(self.exe, 'upscaler'), ['update', str(self.exe), '--component', 'upscaler'])
        self.assertEqual(model.update_args(self.exe, refresh=True), ['update', str(self.exe), '--refresh-recipe'])

    def test_library_lists_installations_then_games_added_here(self):
        other = self.root / 'other'; other.mkdir(); (other / 'Other.exe').write_bytes(b'MZ')
        games, notes = model.load_library(self.ctx, added=[other / 'Other.exe', self.exe], titles={})
        self.assertEqual(notes, [])
        self.assertEqual([(g.exe.name, g.tracked, g.added, model.state(g, self.ctx)) for g in games],
                         [('Game.exe', True, False, 'update'), ('Other.exe', False, True, 'available')])
        self.assertEqual([model.section(g, self.ctx) for g in games], ['installed', 'available'])
        titled = model.title_for(self.exe, games[0].record, {self.game.resolve(): 'Fixture Game'})
        self.assertEqual(titled, 'Fixture Game')

    def test_an_unreadable_index_is_reported_and_launchers_still_list_the_game(self):
        Path(os.environ['FREEFG_LIBRARY']).write_text('{"format": 99}')
        with patch('sys.stderr'):
            games, notes = model.load_library(self.ctx, titles={})
        self.assertEqual(len(notes), 1); self.assertIn('library index needs attention', notes[0])
        self.assertEqual([g.exe for g in games], [self.exe])


class Changes(UpdateFixture):
    """What Rollback would undo, read from the saved generations of real updates (model.last_change)."""
    def setUp(self):
        super().setUp()
        from test_game_install import set_package_file
        set_package_file(self.package, 'opti/OptiScaler.dll', b'custom OptiScaler old')
        set_package_file(self.new, 'opti/OptiScaler.dll', b'custom OptiScaler new')
        self.ctx = context(self.new)

    def change(self):
        return model.load_game(self.ctx, self.exe, titles={}).change

    def test_an_update_to_another_release(self):
        m.install(self.package, self.exe, route='opti')
        self.assertIsNone(self.change())
        self.run_quiet(m.update, self.exe, self.new)
        change = self.change()
        self.assertEqual((change['kind'], change['release'], change['to'], change['launch'], change['launch_changed'],
                          change['missing']), ('release', OLD, NEW, None, None, False))
        self.assertEqual(model.change_words(change)[0], 'Roll back to 1.1.4')
        # Its saved files gone, Rollback cannot run: the page says so instead of offering it.
        import shutil
        shutil.rmtree(self.game / m.STATE / m.GENERATIONS)
        self.assertTrue(self.change()['missing'])
        self.assertIn('Restore', model.change_words(self.change())[1])

    def test_an_update_that_changes_the_launch_settings_of_a_manual_installation(self):
        self.config.unlink()
        self.run_quiet(m.install, self.package, self.exe, route='opti', accept=('no-launcher',))
        before = self.record()['manual_launch']
        self.run_quiet(m.update, self.exe, self.new, loader='winmm.dll')
        change = self.change()
        self.assertEqual(change['launch'], before)  # what Rollback sets back, shown in its confirmation
        self.assertEqual(change['launch_changed']['to'], NEW)
        self.assertEqual(self.record()['manual_launch']['env']['WINEDLLOVERRIDES'], 'winmm=n,b')

    def test_kinds_an_installer_records_and_those_read_from_the_generation(self):
        m.install(self.package, self.exe, route='opti')
        self.run_quiet(m.update, self.exe, self.new)
        record = self.record()
        state = self.game / m.STATE
        path = state / m.GENERATIONS / record['generations'][-1]['id'] / 'generation.json'
        saved = json.loads(path.read_text())
        # A provider switch keeps the release; wiki settings name what they set; a kind the installer records wins.
        for after, entry, kind in (({'upscaler': {'name': 'hlx-dlss'}}, dict(to=OLD), 'provider'),
                                   ({'wiki_settings': {'settings': {'Hotfix.ColorResourceBarrier': '4'}}}, dict(to=OLD), 'settings'),
                                   ({}, dict(to=OLD), 'change'), ({}, dict(kind='ini'), 'settings'), ({}, dict(kind='provider'), 'provider')):
            path.write_text(json.dumps(dict(saved, metadata_before=dict(saved['metadata_before'], upscaler={'name': 'fsr4'}),
                                            metadata_after=after)))
            self.state_file().write_text(json.dumps(dict(record, generations=[dict(record['generations'][-1], **entry)])))
            change = self.change()
            self.assertEqual(change['kind'], kind, after)
        self.assertEqual(change['upscaler'], 'FSR 4')

    def state_file(self):
        return self.exe.parent / m.STATE / 'state.json'


class ReviewRegressions(UpdateFixture):
    def setUp(self):
        super().setUp()
        m.install(self.package, self.exe, route='opti')
        self.ctx = context(self.new)

    def load(self):
        return model.load_game(self.ctx, self.exe, titles={})

    def state_file(self):
        return self.exe.parent / m.STATE / 'state.json'

    def test_malformed_record_does_not_hide_other_registered_games(self):
        m.register_installation(self.exe)
        bad = self.root / 'bad/Game.exe';bad.parent.mkdir();bad.touch()
        (bad.parent / m.STATE).mkdir()
        (bad.parent / m.STATE / 'state.json').write_text('[]')
        index = m.freefg_library.load()
        index['games'][str(bad)] = dict(exe=str(bad), package=OLD)
        m.freefg_library.location().write_text(json.dumps(index))
        found = m.library_inventory()
        self.assertEqual({str(x['exe']) for x in found}, {str(self.exe), str(bad)})
        self.assertEqual(next(x for x in found if x['exe'] == bad)['status'], 'unavailable')
        loaded = model.load_game(self.ctx, bad)
        self.assertEqual(model.state(loaded, self.ctx), 'attention')

    def test_nested_invalid_record_has_an_attention_page(self):
        record = self.record();record['recipe'] = ['invalid']
        self.state_file().write_text(json.dumps(record))
        game = self.load()
        self.assertEqual(model.state(game, self.ctx), 'attention')
        self.assertIn('recipe', game.reason)

    def test_missing_logs_do_not_claim_the_game_was_never_played(self):
        self.assertEqual(model.session_view(None)[1], 'No recorded session')

    def test_game_local_hlx_requires_owned_pinned_files_without_preparation_cache(self):
        import hashlib
        target = 'OptiScaler/custom/hlx-fsr4/ffx/provider.dll'
        companion = 'OptiScaler/custom/hlx-fsr4/ffx/companion.dll'
        entries = {}
        record = self.record()
        for path in (target, companion):
            data = path.encode();file = self.game / path;file.parent.mkdir(parents=True, exist_ok=True);file.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            entries[Path(path).name] = dict(sha256=digest)
            record['files'].append(dict(path=path, after=digest))
        self.state_file().write_text(json.dumps(record))
        spec = dict(version='3.1.0', providers={'hlx-fsr4':dict(api='ffx', files=entries)})
        unprepared = [model.Provider('hlx-fsr4','HLX FSR 4','local',state='unprepared')]
        with patch.object(m.hlx, 'catalog', return_value=spec):
            game = self.load()
            self.assertTrue(model.game_providers(self.ctx, game, unprepared)[0].ready)
            (self.game / companion).write_bytes(b'drift')
            self.assertFalse(model.game_providers(self.ctx, game, unprepared)[0].ready)
            (self.game / companion).write_bytes(companion.encode())
            record['files'] = [x for x in record['files'] if x['path'] != companion]
            self.state_file().write_text(json.dumps(record))
            self.assertFalse(model.game_providers(self.ctx, game, unprepared)[0].ready)

if __name__ == "__main__":
    unittest.main()
