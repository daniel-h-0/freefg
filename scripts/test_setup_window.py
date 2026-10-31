#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Setup's window (packaging/mfg/setup_app.py) on GTK 4 and libadwaita, driven on a virtual display over real
installations of the fixture packages: the library, every page and dialog builds, nothing raises in a callback, and its
install.py commands change exactly the games they name (settings, pin and unpin, update, rollback, restore).

Skipped where PyGObject, GTK 4, libadwaita 1.5 or a display are missing (without DISPLAY the test starts Xvfb). CI
installs them (release/ci/ci.lock.json extra_packages), so there the window is always exercised."""
import json, os, shutil, subprocess, sys, time, unittest
from pathlib import Path
from unittest.mock import patch
from test_update import UpdateFixture, OLD, NEW, m

REPO = Path(__file__).resolve().parents[1]
SKIP = None
XVFB = None
Gtk = Adw = GLib = setup_app = None


def setUpModule():
    global SKIP, XVFB, Gtk, Adw, GLib, setup_app
    os.environ.setdefault('GSK_RENDERER', 'cairo')  # no GPU needed
    os.environ.setdefault('GTK_A11Y', 'test')  # no accessibility bus needed; accessible names can be read back
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        xvfb = shutil.which('Xvfb')
        if xvfb is None:
            SKIP = 'no display, and Xvfb is not installed'
            return
        number = next(n for n in range(91, 400) if not Path(f'/tmp/.X{n}-lock').exists() and
                      not Path(f'/tmp/.X11-unix/X{n}').exists())
        XVFB = subprocess.Popen([xvfb, f':{number}', '-screen', '0', '1280x800x24', '-nolisten', 'tcp'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while not Path(f'/tmp/.X11-unix/X{number}').exists() and time.monotonic() < deadline:
            if XVFB.poll() is not None:
                SKIP = 'Xvfb did not start'
                return
            time.sleep(0.05)
        os.environ['DISPLAY'] = f':{number}'
    try:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw, GLib, Gtk
    except (ImportError, ValueError) as error:
        SKIP = 'PyGObject with GTK 4 and libadwaita is not installed (' + str(error) + ')'
        return
    if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 5):
        SKIP = 'libadwaita 1.5 or newer is not installed'
        return
    if not Gtk.init_check():
        SKIP = 'GTK cannot open the display'
        return
    sys.path.insert(0, str(REPO / 'packaging/mfg'))
    import setup_app


def tearDownModule():
    if XVFB is not None:
        XVFB.terminate()
        XVFB.wait()


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from descendants(child)
        child = child.get_next_sibling()


def groups(widget):
    """{title: group} of the preferences groups under widget."""
    return {found.get_title(): found for found in descendants(widget) if isinstance(found, Adw.PreferencesGroup)}


def rows(widget):
    """{title: row} of the action rows under widget."""
    return {found.get_title(): found for found in descendants(widget) if isinstance(found, Adw.ActionRow)}


class SetupWindow(UpdateFixture):
    """Release OLD installed in the fixture game, and a game added in the session; Setup runs from release NEW's package,
    which holds the real installer (as a release does), so the window's install.py commands run for real."""

    def setUp(self):
        if SKIP:
            self.skipTest(SKIP)
        super().setUp()
        for path in (REPO / 'packaging').glob('*.py'):
            shutil.copy2(path, self.new / path.name)
        shutil.copytree(REPO / 'packaging/vendor', self.new / 'vendor')
        (self.new / 'recipes').mkdir(exist_ok=True)
        shutil.copy2(REPO / 'packaging/recipes/recipes-runtime.json', self.new / 'recipes/recipes.json')
        for name in ('setup.py', 'setup_app.py', 'setup_model.py'):
            shutil.copy2(REPO / 'packaging/mfg' / name, self.new / name)
        # The window's install.py processes find the fixture's launcher entry through HOME.
        context = patch.dict(os.environ, {'HOME': str(self.root)})
        context.start(); self.addCleanup(context.stop)
        m.install(self.package, self.exe, route='opti')
        self.other = self.root / 'other' / 'Other.exe'
        self.other.parent.mkdir()
        self.other.write_bytes(self.exe.read_bytes())
        import importlib.util
        spec = importlib.util.spec_from_file_location('setup_under_test', self.new / 'setup.py')
        self.setup_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.setup_module)
        manifest = json.loads((self.new / 'manifest.json').read_text())
        self.ctx = setup_app.model.Context(self.new, 'FreeFG', manifest, m, None, ['2×'], True,
                                           self.setup_module.HELIXSR_ABOUT, self.setup_module.blockers)
        self.errors = []
        hook = patch.object(sys, 'excepthook', lambda *exc: self.errors.append(exc))
        hook.start(); self.addCleanup(hook.stop)

    def drive(self, script):
        """Run the window with script: a generator that yields conditions to wait for; it resumes once each holds."""
        app = setup_app.Application(self.ctx)
        failures = []

        def resume(steps):
            try:
                condition = next(steps)
            except StopIteration:
                finish()
                return
            except BaseException as error:  # noqa: BLE001 - reported after the main loop ends
                failures.append(error)
                finish()
                return
            started = time.monotonic()

            def poll():
                try:
                    ready = condition()
                except BaseException as error:  # noqa: BLE001
                    failures.append(error)
                    finish()
                    return GLib.SOURCE_REMOVE
                if ready:
                    resume(steps)
                    return GLib.SOURCE_REMOVE
                if time.monotonic() - started > 90:
                    failures.append(AssertionError('timed out waiting in ' + steps.gi_code.co_name + ' at line ' +
                                                   str(steps.gi_frame.f_lineno)))
                    finish()
                    return GLib.SOURCE_REMOVE
                return GLib.SOURCE_CONTINUE
            GLib.timeout_add(40, poll)

        def finish():
            window = app.window
            if window is not None:
                while window.get_visible_dialog() is not None:
                    window.get_visible_dialog().set_can_close(True)
                    window.get_visible_dialog().force_close()
                window.operations = 0
                window.close()
            app.quit()
        app.connect_after('activate', lambda *_: resume(script(app.window)))
        app.run([])
        if app.window is not None:
            # Pending reads must finish before the disposable installation is
            # removed; late GTK deliveries are suppressed by Reader.close().
            app.window.reader.close(wait=True)
        if failures:
            raise failures[0]
        self.assertEqual(self.errors, [], 'an exception was raised in a window callback')

    @staticmethod
    def dialog(window, kind):
        found = window.get_visible_dialog()
        assert isinstance(found, kind), (kind, found)
        return found

    @staticmethod
    def answer(window, response):
        alert = window.get_visible_dialog()
        assert isinstance(alert, Adw.AlertDialog), alert
        alert.emit('response', response)
        alert.force_close()

    def record(self):
        return json.loads((self.game / m.STATE / 'state.json').read_text())

    def test_manual_install_status_and_restore_through_the_window(self):
        from test_game_install import DEPENDENCIES, set_package_file
        from test_proxy_install import PROXY_PACKAGE
        m.restore(self.exe)
        self.config.unlink()
        # Carry the fixture runtime in the package, just as a release does, so the
        # real installer subprocess needs no downloads or dependency mocks.
        for target, source in PROXY_PACKAGE.items():
            set_package_file(self.new, target, DEPENDENCIES['runtime'][source])

        def script(window):
            window.added = [self.exe]
            window.refresh()
            yield lambda: window.loaded and window.providers is not None
            window.install(window.game_by_key(str(self.exe)))
            install = self.dialog(window, setup_app.InstallDialog)
            install.input_row.set_selected([key for key, *_ in setup_app.model.INPUTS].index('upscaler'))
            yield lambda: not install.checking
            refusals = setup_app.model.refusals(install.verdict, 'soft')
            self.assertIn('no-launcher', [r['code'] for r in refusals])
            self.assertFalse(install.install_button.get_sensitive())
            # Manual mode is explained once it can be accepted; what Setup changes follows the switch.
            self.assertTrue(install.manual_group.get_visible())
            self.assertEqual(install.changes_row.get_title(), 'Files, launch settings and downloads')
            for refusal, row in zip(refusals, install.soft_rows):
                if refusal['code'] != 'no-launcher':
                    row.set_active(True)
            self.assertFalse(install.install_button.get_sensitive())
            install.soft_rows[[r['code'] for r in refusals].index('no-launcher')].set_active(True)
            self.assertTrue(install.install_button.get_sensitive(), install.blocked())
            self.assertEqual(install.changes_row.get_title(), 'Files and downloads')
            self.assertIn('No launcher entry is changed', install.launcher_change.get_title())
            self.assertEqual(install.hint.get_text(), 'Setup checks again that the game is closed, then installs.')
            with patch.object(window.reader, 'call', wraps=window.reader.call) as reads:
                install.install()
                self.assertIs(reads.call_args.args[3], False)  # no launcher to check for a game without an entry
            yield lambda: isinstance(window.get_visible_dialog(), setup_app.OperationDialog)
            operation = self.dialog(window, setup_app.OperationDialog)
            yield lambda: operation.done_button.get_visible()
            self.assertTrue(all(r.ok for r in operation.results), operation.results)
            self.assertNotIn('Reopen your launcher and play normally.', operation.extra_steps)
            self.assertTrue(any(s.startswith('In your launcher: set ') for s in
                                setup_app.model.next_steps(operation.results[0].lines)))
            # install.py --events: its event lines are read (one outcome per game), never shown among its output.
            self.assertEqual([(e['type'], e.get('result')) for e in operation.results[0].events if e['type'] == 'outcome'],
                             [('outcome', 'install')])
            log = operation.log.get_buffer()
            self.assertNotIn(setup_app.model.EVENT_PREFIX, log.get_text(log.get_start_iter(), log.get_end_iter(), False))
            settings = self.record()['manual_launch']
            env = settings['env']
            self.assertEqual(env['WINEDLLOVERRIDES'], 'dxgi=n,b')
            self.assertFalse(self.config.exists())
            # The launch settings, ready to copy in both forms, and Setup's step pointing at them.
            import launcher_config
            shown = groups(operation.outcome)
            self.assertIn('Launch settings to add', shown)
            found = rows(shown['Launch settings to add'])
            self.assertEqual(found['Launch options (%command% stands for the game)'].get_subtitle(),
                             launcher_config.manual_steam_line(settings))
            self.assertEqual(found['WINEDLLOVERRIDES'].get_subtitle(), 'dxgi=n,b')
            steps = [row.get_title() for row in descendants(operation.outcome) if isinstance(row, Adw.ActionRow)
                     and row.get_parent() is not None and any(isinstance(w, Gtk.Label) and 'step-number' in w.get_css_classes()
                                                               for w in descendants(row))]
            self.assertEqual(steps[0], setup_app.LAUNCH_STEPS['set'])
            self.assertFalse(any(step.startswith('In your launcher:') for step in steps))
            operation.close()
            yield lambda: window.operations == 0 and setup_app.model.state(
                window.game_by_key(str(self.exe)), self.ctx) == 'installed'
            game = window.game_by_key(str(self.exe))
            self.assertTrue(game.tracked)
            # Health: launch settings the player added, never "None recorded"; Show… has them ready to copy.
            window.show_game(game)
            page = window.split.get_content()
            health = rows(groups(page)['Health'])
            self.assertTrue(health['Launch settings'].get_subtitle().startswith('Not yet confirmed: no session since installation'))
            for change, activation, title, text in (
                    (None, (True, 'MFG proxy ready in the last session.'), 'Launch settings', 'Manual: added by you\nMFG proxy ready in the last session.'),
                    (None, (False, 'No session since installation.'), 'Launch settings', 'Not yet confirmed\nNo session since installation.'),
                    (dict(launch_changed=dict(to=NEW, at='2026-10-30')), None, 'Launch line changed', 'The update to 1.1.5 on 2026-10-30')):
                game.change, game.activation = change, activation
                window.show_game(game)
                found = rows(groups(window.split.get_content())['Health'])
                self.assertIn(title, found)
                self.assertTrue(found[title].get_subtitle().startswith(text), found[title].get_subtitle())
            game.change = game.activation = None
            window.show_game(game)
            next(button for button in descendants(groups(window.split.get_content())['Health'])
                 if isinstance(button, Gtk.Button) and button.get_label() == '_Show…').emit('clicked')
            launch = self.dialog(window, setup_app.LaunchDialog)
            self.assertIn('Launch settings', groups(launch))
            launch.close()
            yield lambda: window.get_visible_dialog() is None
            window.status(game)
            details = self.dialog(window, setup_app.TextDialog)
            yield lambda: details.copy_button.get_sensitive()
            self.assertIn('    WINEDLLOVERRIDES=dxgi=n,b', details.lines)
            self.assertTrue(any(line.startswith('In your launcher: keep ') for line in details.lines))
            self.assertFalse(any(line.startswith(setup_app.model.EVENT_PREFIX) for line in details.lines))
            details.close()
            yield lambda: window.get_visible_dialog() is None
            window.restore(game)
            # The confirmation names the text to delete; it does not claim to remove launch settings.
            alert = window.get_visible_dialog()
            self.assertNotIn('its launch settings', alert.get_body())
            self.assertIn('delete these from your launcher', alert.get_body())
            texts = [w.get_label() for w in descendants(alert.get_extra_child()) if isinstance(w, Gtk.Label)]
            self.assertTrue(any('WINEDLLOVERRIDES=dxgi=n,b' in text for text in texts), texts)
            self.answer(window, 'go')
            yield lambda: isinstance(window.get_visible_dialog(), setup_app.OperationDialog)
            operation = self.dialog(window, setup_app.OperationDialog)
            yield lambda: operation.done_button.get_visible()
            self.assertTrue(all(r.ok for r in operation.results), operation.results)
            self.assertTrue(any(s.startswith('In your launcher: remove ') for s in
                                setup_app.model.next_steps(operation.results[0].lines)))
            self.assertNotIn('Reopen your launcher and play normally.', operation.extra_steps)
            self.assertIn('Launch settings to remove', groups(operation.outcome))
            self.assertEqual(self.record()['status'], 'restored')
            for name, data in self.original.items():
                self.assertEqual((self.game / name).read_bytes(), data, name)
            self.assertFalse(self.config.exists())
            operation.close()
        self.drive(script)

    def test_library_pages_and_changes(self):
        def script(window):
            window.added = [self.other]
            window.refresh()
            yield lambda: window.loaded and window.system is not None and window.providers is not None and \
                all(g.checked for g in window.games if setup_app.model.state(g, self.ctx) == 'available')
            states = {g.exe: setup_app.model.state(g, self.ctx) for g in window.games}
            self.assertEqual(states, {self.exe: 'update', self.other: 'available'})
            rows = []
            row = window.list.get_first_child()
            while row is not None:
                rows.append(row)
                row = row.get_next_sibling()
            self.assertEqual([r.game.exe for r in rows if isinstance(r, setup_app.GameRow)], [self.exe, self.other])
            self.assertTrue(window.banner.get_revealed())
            # The installed game's page: its state, then its files hashed off the window's thread.
            game = window.game_by_key(str(self.exe))
            window.list.select_row(rows[0])
            page = window.split.get_content()
            self.assertIsInstance(page, setup_app.GamePage)
            self.assertEqual(page.state, 'update')
            yield lambda: window.integrity.get(game.key) is not None
            self.assertEqual(window.integrity[game.key]['changed'], [])
            # Settings: Apply runs install.py configure with what changed only.
            page = window.split.get_content()
            page.size_row.set_selected([key for key, _ in setup_app.model.SIZES].index('1440'))
            self.assertTrue(page.apply_button.get_visible())
            page.apply()
            yield lambda: window.operations == 0 and self.settings()[('bc250', 'resolutionmode')] == '2'
            self.assertEqual(self.settings()[('bc250', 'resolutionlimit')], '1440')
            # Pin, then unpin.
            yield lambda: window.operations == 0
            window.set_pin(window.game_by_key(str(self.exe)), True)
            yield lambda: window.operations == 0 and 'update_pin' in self.record()
            yield lambda: setup_app.model.state(window.game_by_key(str(self.exe)), self.ctx) == 'pinned'
            window.set_pin(window.game_by_key(str(self.exe)), False)
            yield lambda: window.operations == 0 and 'update_pin' not in self.record()
            yield lambda: setup_app.model.state(window.game_by_key(str(self.exe)), self.ctx) == 'update'
            # Update All: the plan, then the update of the one game that has one.
            window.update_all()
            review = self.dialog(window, setup_app.UpdateDialog)
            yield lambda: review.stack.get_visible_child_name() == 'review'
            self.assertEqual([(item.exe, item.status) for item in review.items], [(self.exe, 'update')])
            self.assertTrue(review.update_button.get_sensitive())
            review.update()
            operation = self.dialog(window, setup_app.OperationDialog)
            yield lambda: operation.done_button.get_visible()
            self.assertTrue(all(result.ok for result in operation.results), operation.results)
            self.assertEqual(self.record()['package'], NEW)
            operation.close()
            yield lambda: setup_app.model.state(window.game_by_key(str(self.exe)), self.ctx) == 'installed'
            # Every other dialog builds over real data.
            game = window.game_by_key(str(self.exe))
            other = window.game_by_key(str(self.other))
            window.install(other)
            install = self.dialog(window, setup_app.InstallDialog)
            yield lambda: not install.checking
            self.assertEqual(install.install_button.get_sensitive(), install.blocked() is None)
            install.close()
            window.change_upscaler(game)
            self.dialog(window, setup_app.UpscalerDialog).close()
            window.show_upscalers()
            self.dialog(window, setup_app.UpscalersDialog).close()
            window.show_system()
            system = self.dialog(window, setup_app.SystemDialog)
            yield lambda: system.stack.get_visible_child_name() == 'page'
            system.close()
            window.browse()
            browse = self.dialog(window, setup_app.BrowseDialog)
            yield lambda: browse.stack.get_visible_child_name() in ('list', 'empty')
            browse.close()
            window.sentence(other)
            self.answer(window, 'cancel')
            # Roll Back asks first, then returns the game to release OLD.
            window.rollback(game)
            self.answer(window, 'go')
            operation = None
            yield lambda: isinstance(window.get_visible_dialog(), setup_app.OperationDialog)
            operation = window.get_visible_dialog()
            yield lambda: operation.done_button.get_visible()
            self.assertEqual(self.record()['package'], OLD)
            operation.close()
            # Restore asks first, then returns the original files; the game stays listed, as not installed.
            yield lambda: window.operations == 0 and setup_app.model.state(window.game_by_key(str(self.exe)), self.ctx) == 'update'
            window.restore(window.game_by_key(str(self.exe)))
            self.answer(window, 'go')
            yield lambda: isinstance(window.get_visible_dialog(), setup_app.OperationDialog)
            operation = window.get_visible_dialog()
            yield lambda: operation.done_button.get_visible()
            self.assertEqual(self.record()['status'], 'restored')
            self.assertOriginal()
            operation.close()
            yield lambda: window.game_by_key(str(self.exe)) is not None and \
                setup_app.model.state(window.game_by_key(str(self.exe)), self.ctx) == 'available'
        self.drive(script)

    def test_a_missing_installer_leaves_a_page_that_says_so(self):
        self.ctx.installer, self.ctx.load_error = None, 'SyntaxError: invalid syntax (install.py, line 1)'

        def script(window):
            yield lambda: True
            page = window.split.get_content()
            self.assertEqual(page.get_tag(), 'broken')
            self.assertFalse(window.lookup_action('update-all').get_enabled())
        self.drive(script)


    def test_cancel_or_changed_input_invalidates_pending_install_check(self):
        def script(window):
            yield lambda: window.loaded and window.providers is not None
            game = setup_app.model.Game(self.other, title='Fixture game')
            for cancel in (True, False, "close", "provider"):
                window.install(game)
                dialog = self.dialog(window, setup_app.InstallDialog)
                yield lambda: not dialog.checking
                dialog.checked(dialog.generation, dict(blocking=[], manual_steps=[], warnings=[], line='Fixture ready'))
                self.assertIsNone(dialog.blocked())
                with patch.object(window.reader, 'call') as reader, patch.object(window, 'run') as run:
                    dialog.install()
                    self.assertTrue(dialog.install_pending)
                    callback = reader.call_args.kwargs['done']
                    if cancel == "provider":
                        dialog.providers = [*dialog.providers, setup_app.model.Provider('fixture-ready','Fixture provider','ready')]
                        dialog.choose_provider('fixture-ready')
                        self.assertIsNone(dialog.blocked())
                    elif cancel == "close":
                        dialog.close()
                    elif cancel:
                        dialog.cancel()
                    else:
                        dialog.input_row.set_selected(1)
                    callback([])
                    run.assert_not_called()
                    self.assertFalse((self.other.parent / m.STATE / 'state.json').exists())
                dialog.close()
                yield lambda: window.get_visible_dialog() is None
        self.drive(script)

    def test_newer_installation_page_exposes_diagnostics_without_mutations(self):
        record = self.record(); record['package'] = 'freefg-9999.0'
        (self.game / m.STATE / 'state.json').write_text(json.dumps(record))
        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            window.show_game(game)
            page = window.split.get_content()
            self.assertEqual(page.state, 'newer')
            self.assertFalse(hasattr(page, 'settings_group'))
            def walk(widget):
                yield widget
                child = widget.get_first_child()
                while child is not None:
                    yield from walk(child)
                    child = child.get_next_sibling()
            labels = [w.get_label() for w in walk(page) if isinstance(w, Gtk.Button)]
            self.assertFalse({'_Change…','_Restore…','_Roll Back…','_Apply'} & set(labels))
            self.assertIn('_Show…', labels)
        self.drive(script)

    def test_legacy_helix_can_switch_to_distinct_hlx_successor(self):
        from dataclasses import replace
        def script(window):
            yield lambda: window.loaded and window.providers is not None
            game = window.game_by_key(str(self.exe))
            game.record['upscaler']['name'] = 'helixsr'
            provider = setup_app.model.Provider('hlx-dlss','HLX DLSS','fixture',state='unprepared')
            window.providers = [provider]
            with patch.object(setup_app.model, 'game_providers', return_value=[replace(provider, state='ready')]):
                window.change_upscaler(game)
                dialog = self.dialog(window, setup_app.UpscalerDialog)
                yield lambda: dialog.providers is not None
                self.assertEqual(dialog.current, 'helixsr')
                self.assertEqual(dialog.chosen, 'hlx-dlss')
                self.assertTrue(dialog.switch_button.get_sensitive())
                dialog.close()
        self.drive(script)


    def test_process_check_failure_keeps_settings_unchanged(self):
        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            before = self.settings()
            with patch.object(window.reader, 'call') as reader, patch.object(window, 'quietly') as mutate:
                window.apply_settings(game, setup_app.model.Settings(), setup_app.model.Settings(size='1440'))
                reader.call_args.kwargs['failed'](OSError('process list unavailable'))
                mutate.assert_not_called()
                self.assertEqual(self.settings(), before)
                alert = window.get_visible_dialog()
                self.assertEqual(alert.get_heading(), 'Could not check running processes')
                self.answer(window, 'close')
        self.drive(script)


    def test_a_refusal_is_not_a_failure_and_events_shape_the_outcome(self):
        settings = dict(env={'WINEDLLOVERRIDES': 'dxgi=n,b'}, args=['-dx12'])
        event = lambda **fields: setup_app.model.EVENT_PREFIX + json.dumps(dict(v=1, **fields))
        printed = [event(type='changed', text='OptiScaler.ini: 2 settings'), 'Frame-generation input: OptiFG',
                   'In game: open OptiScaler with Insert.', event(type='step', where='game', text='turn on DLSS FG.'),
                   event(type='manual', action='replace', settings=settings), event(type='outcome', exe='/g/A.exe', result='update')]
        commands = {'refuse': "import sys; print('Close Game.exe first.', file=sys.stderr); sys.exit(3)",
                    'fail': "import sys; print('Original backup is missing or damaged: x', file=sys.stderr); sys.exit(1)",
                    'events': 'print(' + repr('\n'.join(printed)) + ')'}
        self.ctx.command = lambda args: [sys.executable, '-c', commands[args[0]]]
        Step = setup_app.Step

        def finished(operation):
            return lambda: operation.done_button.get_visible()

        def script(window):
            yield lambda: window.loaded
            # Refused (exit 3): nothing changed, which is no failure; the installer's reason says what to do.
            window.run('Refused', [Step('Game', ['refuse'])], working='Working', success='Done')
            operation = self.dialog(window, setup_app.OperationDialog)
            yield finished(operation)
            self.assertEqual((operation.title_label.get_text(), operation.detail_label.get_text()),
                             ('Nothing was changed', 'Close Game.exe first.'))
            self.assertIn('warning', operation.status_icon.get_child_by_name('done').get_css_classes())
            self.assertFalse(operation.expander.get_expanded())
            operation.close()
            yield lambda: window.get_visible_dialog() is None
            window.run('Mixed', [Step('A', ['refuse']), Step('B', ['fail']), Step('C', ['events'])], working='Working',
                       success='Done')
            operation = self.dialog(window, setup_app.OperationDialog)
            yield finished(operation)
            self.assertEqual(operation.title_label.get_text(), '1 of 3 completed')
            found = rows(operation.outcome)
            self.assertEqual((found['A'].get_subtitle(), found['B'].get_subtitle(), found['C'].get_subtitle()),
                             ('Close Game.exe first.', 'Original backup is missing or damaged: x', 'Done'))
            self.assertIn('Launch line changed · C', groups(operation.outcome))
            operation.close()
            yield lambda: window.get_visible_dialog() is None
            # One game: what changed and the next steps are the installer's events, its text where it sent none.
            window.run('Events', [Step('C', ['events'])], working='Working', success='Done')
            operation = self.dialog(window, setup_app.OperationDialog)
            yield finished(operation)
            titles = [row.get_title() for row in descendants(operation.outcome) if isinstance(row, Adw.ActionRow)]
            self.assertIn('OptiScaler.ini: 2 settings', titles)
            self.assertNotIn('Frame-generation input: OptiFG', titles)
            self.assertIn(setup_app.LAUNCH_STEPS['replace'], titles)
            self.assertIn('In game: turn on DLSS FG.', titles)
            self.assertNotIn('In game: open OptiScaler with Insert.', titles)
            log = operation.log.get_buffer()
            self.assertNotIn(setup_app.model.EVENT_PREFIX, log.get_text(log.get_start_iter(), log.get_end_iter(), False))
            operation.close()
        self.drive(script)

    def test_output_arrives_in_batches(self):
        self.ctx.command = lambda args: [sys.executable, '-c', 'for n in range(3000): print("line", n)']
        batches, finished = [], []
        operation = setup_app.Operation(self.ctx, [setup_app.Step('Many', ['many'])],
                                        on_lines=lambda index, lines: batches.append(lines), on_done=finished.append)
        operation.start()
        context, deadline = GLib.MainContext.default(), time.monotonic() + 60
        while not finished and time.monotonic() < deadline:
            if not context.iteration(False):
                time.sleep(0.01)
        self.assertEqual([line for batch in batches for _, line in batch], [f'line {n}' for n in range(3000)])
        self.assertLess(len(batches), 300)  # one callback per idle cycle, never one per line
        self.assertEqual(finished[0][0].returncode, 0)

    def test_closing_ends_the_processes_reads_started(self):
        reader = setup_app.Reader()
        self.assertTrue(all(thread.daemon for thread in reader.threads))  # never keeps Setup running after its window
        future = reader.call(lambda run: run([sys.executable, '-c', 'import time; time.sleep(120)'], capture_output=True,
                                             timeout=180), reader.run, probe=True)
        deadline = time.monotonic() + 30
        while not reader.processes and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        reader.close(wait=True)
        self.assertLess(time.monotonic() - started, 20)
        self.assertNotEqual(future.result().returncode, 0)
        with self.assertRaises(OSError):
            reader.run([sys.executable, '-c', 'pass'])
        self.assertIsNone(reader.call(lambda: None))
        self.assertFalse(any(t.is_alive() for t in reader.threads))

    def test_keep_this_release_waits_for_its_change_and_reads_the_record_again(self):
        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            window.list.select_row(window.row_for(game.key))
            page = window.split.get_content()
            with patch.object(window, 'quietly', wraps=window.quietly) as changes:
                page.pin_row.set_active(True)
                self.assertFalse(page.pin_row.get_sensitive())  # no second pin while the first runs
                window.set_pin(game, False)
                window.set_pin(game, True)  # the position asked for last is the one compared with the record
                yield lambda: not window.pending and window.operations == 0
                self.assertEqual(len(changes.call_args_list), 1)
            self.assertIn('update_pin', self.record())
            yield lambda: window.split.get_content() is not page
            page = window.split.get_content()
            self.assertTrue(page.pin_row.get_active() and page.pin_row.get_sensitive())
            # The page is older than the record (pinned elsewhere since): asking for what the record already says
            # runs nothing.
            self.run_quiet(m.pin, self.exe, False)
            game = window.game_by_key(str(self.exe))
            with patch.object(window, 'quietly', wraps=window.quietly) as changes:
                window.set_pin(game, False)
                yield lambda: not window.pending
                changes.assert_not_called()
            yield lambda: not window.split.get_content().pin_row.get_active()
            # Another change of the game runs: the switch shows the record again and nothing waits to be applied later.
            self.assertTrue(window.claim([game]))
            window.set_pin(game, True)
            self.assertNotIn(game.key, window.pin_intent)
            page = window.split.get_content()
            self.assertFalse(page.pin_row.get_active() or page.pin_row.get_sensitive())
            window.release([game])
        self.drive(script)

    def test_unsaved_settings_survive_a_refresh_and_apply_runs_once(self):
        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            window.list.select_row(window.row_for(game.key))
            page = window.split.get_content()
            sizes = [key for key, _ in setup_app.model.SIZES]
            page.size_row.set_selected(sizes.index('1440'))
            window.refresh()
            yield lambda: window.split.get_content() is not page
            page = window.split.get_content()
            self.assertEqual(sizes[page.size_row.get_selected()], '1440')
            self.assertTrue(page.apply_button.get_visible())
            before = self.settings()
            with patch.object(window, 'when_closed', side_effect=lambda games, launchers, then, cancelled=None: then()), \
                    patch.object(window, 'quietly') as configure:
                page.apply()
                page.apply()
                window.apply_settings(game, page.before, page.chosen())
                self.assertEqual(len(configure.call_args_list), 1)  # one configure at a time
                self.assertFalse(page.apply_button.get_sensitive())
                configure.call_args.kwargs['then'](False)  # not saved: the edit stays to apply again
            self.assertEqual(self.settings(), before)
            yield lambda: window.split.get_content() is not page and not window.pending
            page = window.split.get_content()
            self.assertEqual(sizes[page.size_row.get_selected()], '1440')
            self.assertTrue(page.apply_button.get_sensitive())
            page.revert()
            self.assertNotIn(game.key, window.drafts)
        self.drive(script)

    def test_reads_that_fail_never_leave_a_spinner(self):
        def script(window):
            window.added = [self.other]
            window.refresh()
            yield lambda: window.loaded and window.providers is not None
            game = window.game_by_key(str(self.exe))
            with patch.object(setup_app.model, 'integrity', side_effect=RuntimeError('boom')):
                window.integrity.clear()
                game.integrity = None
                window.list.select_row(window.row_for(game.key))
                page = window.split.get_content()
                yield lambda: page.files_icon.get_child_by_name('done') is not None
            self.assertEqual(page.files_row.get_subtitle(), 'Could not be checked: boom')
            other = window.game_by_key(str(self.other))
            with patch.object(setup_app.model, 'check_game', side_effect=RuntimeError('boom')):
                window.verdicts.clear()
                other.checked = False
                window.check_game(other)
                yield lambda: other.checked
            self.assertIsNone(other.verdict)
            with patch.object(setup_app.model, 'plan_game', side_effect=RuntimeError('no plan')):
                window.update_all([game])
                review = self.dialog(window, setup_app.UpdateDialog)
                yield lambda: review.stack.get_visible_child_name() == 'review'
            self.assertIsInstance(review.page, Adw.StatusPage)
            self.assertFalse(review.update_button.get_sensitive())
            review.close()
            yield lambda: window.get_visible_dialog() is None
            with patch.object(setup_app.model, 'game_providers', side_effect=AttributeError('record gone')):
                window.change_upscaler(game)
                dialog = self.dialog(window, setup_app.UpscalerDialog)
                yield lambda: dialog.providers is not None
            self.assertEqual([p.id for p in dialog.providers], [p.id for p in window.providers])
            dialog.close()
        self.drive(script)

    def test_the_list_changes_rows_in_place(self):
        def script(window):
            window.added = [self.other]
            window.refresh()
            yield lambda: window.loaded and all(g.checked for g in window.games if setup_app.model.state(g, self.ctx) == 'available')
            before = [row for row in descendants(window.list) if isinstance(row, setup_app.GameRow)]
            window.list.select_row(before[0])
            window.game_checked(str(self.other), dict(tier='A', blocking=[], refusals=[], route='opti', fg_input='upscaler'))
            old = window.games[0]
            window.refresh()
            yield lambda: window.games[0] is not old
            after = [row for row in descendants(window.list) if isinstance(row, setup_app.GameRow)]
            self.assertEqual([id(row) for row in after], [id(row) for row in before])  # the same rows, drawn again
            self.assertIs(window.list.get_selected_row(), after[0])
            self.assertEqual(setup_app.model.badge(after[1].game, self.ctx), ('Verified', 'success'))
            # A game that leaves the list takes only its row with it.
            window.forget(after[1].game)
            yield lambda: len([row for row in descendants(window.list) if isinstance(row, setup_app.GameRow)]) == 1
            self.assertIs([row for row in descendants(window.list) if isinstance(row, setup_app.GameRow)][0], after[0])
        self.drive(script)

    def test_wiki_entries_for_one_setting_are_selected_one_at_a_time(self):
        source = dict(title='Example Game', pages=[])
        plan = dict(format=1, digest='b' * 64, rows=[
            dict(id='a', key='FrameGen.Example', value='1', current='auto', action='prefill', reason='Optional', source=source),
            dict(id='b', key='framegen.example', value='2', current='auto', action='prefill', reason='Optional', source=source)])

        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            with patch.object(setup_app.model, 'wiki_settings_plan', return_value=plan):
                window.review_wiki(game)
                dialog = self.dialog(window, setup_app.WikiSettingsDialog)
                yield lambda: dialog.plan is not None
            self.assertTrue(all('selecting one clears the other' in row.get_subtitle() for row in descendants(dialog)
                                if isinstance(row, Adw.ExpanderRow) and row.get_title().lower().startswith('framegen.example')))
            dialog.choices['a'].set_active(True)
            dialog.choices['b'].set_active(True)
            self.assertEqual(dialog.selected(), ['b'])
            self.assertTrue(dialog.apply_button.get_sensitive())
            with patch.object(window, 'request') as request:
                dialog.apply()
            self.assertEqual(request.call_count, 1)
        self.drive(script)

    def test_icon_buttons_have_names_and_light_badges_are_readable(self):
        if os.environ.get('GTK_A11Y') != 'test':
            self.skipTest('reading accessible names back needs GTK_A11Y=test')
        from gi.repository import Gdk, Graphene
        if not hasattr(Gdk, 'TextureDownloader') or not hasattr(Gtk.Widget, 'get_color'):
            self.skipTest('needs GTK 4.10')
        manager = Adw.StyleManager.get_default()
        self.addCleanup(manager.set_color_scheme, Adw.ColorScheme.DEFAULT)

        def luminance(rgb):
            channel = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
            return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])

        def contrast(widget, root, pixels, stride):
            # The text's colour over the background drawn just inside the badge (its left padding).
            ok, bounds = widget.compute_bounds(root)
            x, y = int(bounds.get_x() + 4), int(bounds.get_y() + bounds.get_height() / 2)
            background = [v / 255 for v in pixels[y * stride + x * 4:y * stride + x * 4 + 3]]
            color = widget.get_color()
            text = [min(1, max(0, color.alpha * c + (1 - color.alpha) * b))
                    for c, b in zip((color.red, color.green, color.blue), background)]
            high, low = sorted((luminance(text), luminance(background)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        def script(window):
            window.added = [self.other]
            window.refresh()
            yield lambda: window.loaded and window.system is not None and window.providers is not None
            window.list.select_row(window.row_for(str(self.exe)))
            window.show_system()
            system = self.dialog(window, setup_app.SystemDialog)
            unnamed = [w for root in (window, system) for w in descendants(root)
                       if isinstance(w, (Gtk.Button, Gtk.MenuButton)) and w.get_tooltip_text() and not w.get_label()
                       and not Gtk.test_accessible_has_property(w, Gtk.AccessibleProperty.LABEL)]
            self.assertEqual([w.get_tooltip_text() for w in unnamed], [])
            self.assertFalse(window.banner.get_use_markup())
            system.close()
            yield lambda: window.get_visible_dialog() is None
            # Every badge style on a row of a library sidebar, in the light style. A window of its own, filled before it is
            # shown: its first frame lays everything out (a display without a viewer, as Broadway's, may draw no later one).
            manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class('navigation-sidebar')
            shown = {}
            for style in ('accent', 'success', 'warning', 'error', 'dim'):
                line = Gtk.Box(spacing=12)
                line.append(Gtk.Label(label='Game', hexpand=True, xalign=0))
                shown[style] = setup_app.badge('Sample', style)
                line.append(shown[style])
                listing.append(Gtk.ListBoxRow(child=line))
            split = Adw.NavigationSplitView(sidebar=Adw.NavigationPage(child=listing, title='Library'),
                                            content=Adw.NavigationPage(child=Gtk.Label(label='Game'), title='Game'))
            probe = Adw.ApplicationWindow(application=window.get_application(), content=split, default_width=900,
                                          default_height=400)
            self.addCleanup(probe.destroy)
            probe.present()
            yield lambda: all(widget.get_width() > 0 for widget in shown.values())
            width, height = probe.get_width(), probe.get_height()
            snapshot = Gtk.Snapshot()
            Gtk.WidgetPaintable.new(probe).snapshot(snapshot, width, height)
            texture = probe.get_renderer().render_texture(snapshot.to_node(), Graphene.Rect().init(0, 0, width, height))
            downloader = Gdk.TextureDownloader.new(texture)
            downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
            pixels, stride = downloader.download_bytes()
            measured = {style: round(contrast(widget, probe, pixels.get_data(), stride), 2) for style, widget in shown.items()}
            self.assertTrue(all(value >= 4.5 for value in measured.values()), measured)
            probe.close()
        self.drive(script)

    def test_closed_reader_finishes_work_without_delivering_to_destroyed_window(self):
        import threading
        reader = setup_app.Reader()
        started, release = threading.Event(), threading.Event()
        delivered = []
        def read():
            started.set()
            release.wait(timeout=5)
            return 'finished'
        future = reader.call(read, done=delivered.append)
        self.assertTrue(started.wait(timeout=5))
        reader.close()
        release.set()
        reader.close(wait=True)
        self.assertEqual(future.result(), 'finished')
        context = GLib.MainContext.default()
        while context.pending():context.iteration(False)
        self.assertEqual(delivered, [])

    def test_wiki_review_starts_unselected_and_requires_condition_confirmation(self):
        rows = [dict(id='a', key='Hotfix.Example', value='true', current='auto', action='prefill',
                     reason='Optional wiki setting', source=dict(title='Example Game', pages=[])),
                dict(id='b', key='FrameGen.Example', value='false', current='auto', action='conditional',
                     reason='Confirm the renderer', confirmations=['The game uses the listed renderer'],
                     source=dict(title='Example Game', pages=[])),
                dict(id='c', key='Libraries.DLL', value='example.dll', current='auto', action='advice',
                     reason='Library wiring belongs to the installer', source=dict(title='Example Game', pages=[])),
                dict(id='d', key='Hotfix.AlreadySet', value='true', current='true', action='prefill',
                     reason='Optional wiki setting', source=dict(title='Example Game', pages=[]))]
        plan = dict(format=1, digest='a' * 64, rows=rows, requirements=[dict(
            title='Fixture requirement', text='The wiki requires an extra runtime for this setting.', pages=[])])
        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            before = self.snapshot()
            with patch.object(setup_app.model, 'wiki_settings_plan', return_value=plan):
                window.review_wiki(game)
                dialog = self.dialog(window, setup_app.WikiSettingsDialog)
                yield lambda: dialog.plan is not None
                self.assertEqual(dialog.selected(), [])
                def descendants(widget):
                    yield widget
                    child = widget.get_first_child()
                    while child is not None:
                        yield from descendants(child)
                        child = child.get_next_sibling()
                titles = [widget.get_title() for widget in descendants(dialog) if isinstance(widget, Adw.ActionRow)]
                self.assertIn('Fixture requirement', titles)
                self.assertFalse(dialog.apply_button.get_sensitive())
                self.assertNotIn('c', dialog.choices)
                self.assertNotIn('d', dialog.choices)
                dialog.choices['b'].set_active(True)
                self.assertFalse(dialog.apply_button.get_sensitive())
                dialog.confirmations['b'].set_active(True)
                self.assertTrue(dialog.apply_button.get_sensitive())
                with patch.object(window, 'when_closed', side_effect=lambda games, launchers, then, cancelled=None: then()), \
                        patch.object(window, 'run') as run:
                    dialog.apply()
                    run.assert_called_once()
                    steps = run.call_args.args[1]
                    self.assertEqual(steps[0].args, ['wiki-apply', str(game.exe), '--wiki-plan-digest', 'a' * 64,
                                                   '--wiki-setting', 'b', '--wiki-confirm', 'b'])
                self.assertEqual(self.snapshot(), before)
        self.drive(script)

    def test_wiki_selection_runs_installer_and_rolls_back_exactly(self):
        from test_game_install import set_package_file
        catalogue = dict(schema=1, verified=[], leave_auto={}, backports={}, quirk_keys={}, wiki=[dict(
            title='Fixture wiki game', match={'gog':['123']}, pages=[],
            ini=[dict(key='Hotfix.ColorResourceBarrier', value='4')])])
        set_package_file(self.new, 'recipes/recipes.json', json.dumps(catalogue).encode())
        ini = self.game / 'OptiScaler.ini'
        ini.write_bytes(ini.read_bytes() + b'\n; later player comment\n[Hotfix]\nColorResourceBarrier=auto\n')
        before = self.snapshot()
        release = self.record()['package']

        def script(window):
            yield lambda: window.loaded
            game = window.game_by_key(str(self.exe))
            window.review_wiki(game)
            dialog = self.dialog(window, setup_app.WikiSettingsDialog)
            yield lambda: dialog.plan is not None
            row = next(row for row in dialog.plan['rows'] if row['key']=='Hotfix.ColorResourceBarrier')
            self.assertEqual(row['action'], 'prefill')
            self.assertEqual(self.snapshot(), before)
            dialog.choices[row['id']].set_active(True)
            dialog.apply()
            yield lambda: isinstance(window.get_visible_dialog(), setup_app.OperationDialog)
            operation = window.get_visible_dialog()
            yield lambda: operation.done_button.get_visible()
            self.assertTrue(all(result.ok for result in operation.results), operation.results)
            self.assertEqual(m.read_ini(ini.read_bytes())[('hotfix', 'colorresourcebarrier')], '4')
            self.assertEqual(self.record()['package'], release)
            after = self.snapshot()
            self.assertEqual(set(before), set(after))
            self.assertEqual({name for name in after if before[name] != after[name]}, {'OptiScaler.ini'})
            operation.close()
            yield lambda: window.operations == 0 and window.get_visible_dialog() is None and \
                (window.game_by_key(str(self.exe)).change or {}).get('kind') == 'settings'
            # Roll Back names what it undoes: these wiki settings, not a release.
            game = window.game_by_key(str(self.exe))
            window.list.select_row(window.row_for(game.key))
            self.assertIn('Undo wiki settings (Hotfix.ColorResourceBarrier = 4)', rows(groups(window.split.get_content())['Recovery']))
            window.rollback(game)
            self.assertEqual(window.get_visible_dialog().get_heading(), 'Undo wiki settings?')
            self.answer(window, 'go')
            yield lambda: isinstance(window.get_visible_dialog(), setup_app.OperationDialog)
            operation = window.get_visible_dialog()
            yield lambda: operation.done_button.get_visible()
            self.assertTrue(all(result.ok for result in operation.results), operation.results)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.record()['package'], release)
            operation.close()
        self.drive(script)


if __name__ == '__main__':
    unittest.main()
