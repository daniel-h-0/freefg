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
    os.environ.setdefault('GTK_A11Y', 'none')  # no accessibility bus needed
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
            for cancel in (True, False, "close"):
                window.install(game)
                dialog = self.dialog(window, setup_app.InstallDialog)
                yield lambda: not dialog.checking
                dialog.checked(dialog.generation, dict(blocking=[], manual_steps=[], warnings=[], line='Fixture ready'))
                self.assertIsNone(dialog.blocked())
                with patch.object(window.reader, 'call') as reader, patch.object(window, 'run') as run:
                    dialog.install()
                    self.assertTrue(dialog.install_pending)
                    callback = reader.call_args.kwargs['done']
                    if cancel == "close":
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


if __name__ == '__main__':
    unittest.main()
