# SPDX-License-Identifier: MIT
"""The optional HelixSR upscaler (packaging/helixsr.py, install.py --upscaler helixsr, configure --upscaler, install.py
helixsr): finding an official HelixSR release whose network HelixSR's own setup built, refusing anything else before a
game changes, placing HelixSR's DLL where OptiScaler loads its FidelityFX upscaler with helixsr.ini beside it (HelixSR's
own DLSS frame generation off), Restore of exactly what was placed, switching between FSR 4 and HelixSR, the download
of the official release archive into the cache (unpacked as it is), and the credit lines. HelixSR's files here are
stand-ins: a fake DLL whose SHA-256 the fixture pins, with a network appended behind HelixSR's footer layout."""
import contextlib, io, json, os, shutil, stat, struct, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from test_game_install import GameFixture, set_package_file, m
from test_proxy_install import ProxyFixture

H = m.helixsr
BASE = b'MZ stand-in for an official HelixSR DLL'


def built(base=BASE, weights=b'w' * 10, kernels=b'k' * 6):
    """A DLL as HelixSR's setup leaves it: the official bytes, the network appended and the footer."""
    return base + weights + kernels + H.MAGIC + struct.pack('<QQQ', len(weights), len(kernels), 1)


def make_release(folder, dll):
    m.write(folder / H.RELEASE_DLL, dll)
    m.write(folder / H.SETUP_SCRIPT, b'#!/bin/sh\nexit 1\n', 0o755)
    return folder


def add_pins(package, releases=None, archive=None):
    """Pin a HelixSR release in the fixture package's dependencies.json (and its download input)."""
    pins = json.loads((package / 'dependencies.json').read_text())
    data = archive or b'zip'
    pins.setdefault('inputs', {})['helixsr'] = dict(url='https://github.com/lonewolf0622/HelixSR/releases/download/v2.0.0/HelixSR-2.0.0.zip',
                                                    file='HelixSR-2.0.0.zip', sha256=m.digest(data), size=len(data))
    pins['helixsr'] = dict(Version='2.0.0', Input='helixsr', Folder='HelixSR-2.0.0',
                           Releases=releases or {m.digest(BASE): '2.0.0'}, Project=H.PROJECT, Author=H.AUTHOR)
    set_package_file(package, 'dependencies.json', json.dumps(pins).encode())


class HelixFixture(GameFixture):
    def setUp(self):
        super().setUp()
        cache = patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root / 'cache')})
        cache.start(); self.addCleanup(cache.stop)
        add_pins(self.package)
        self.release = make_release(self.root / 'HelixSR-2.0.0', built())

    def record(self):
        return json.loads((self.game / m.STATE / 'state.json').read_text())

    def out(self, function, *args, **kwargs):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            function(*args, **kwargs)
        return text.getvalue()


class Detection(HelixFixture):
    def test_states(self):
        pinned = H.pins(self.package)
        self.assertEqual(H.check_release(self.release, pinned)['state'], 'ready')
        self.assertEqual(H.check_release(self.release, pinned)['version'], '2.0.0')
        make_release(self.root / 'unbuilt', BASE)
        self.assertEqual(H.check_release(self.root / 'unbuilt', pinned)['state'], 'unbuilt')
        make_release(self.root / 'changed', built(base=BASE + b'!'))
        self.assertEqual(H.check_release(self.root / 'changed', pinned)['state'], 'unknown')
        # A footer whose sizes do not fit the file is no network: the whole file is hashed, which is no official DLL.
        make_release(self.root / 'bad', BASE + H.MAGIC + struct.pack('<QQQ', 1 << 20, 4, 1))
        self.assertEqual(H.check_release(self.root / 'bad', pinned)['state'], 'unknown')
        self.assertEqual(H.check_release(self.root / 'nothing', pinned)['state'], 'missing')

    def test_found_in_home_downloads_and_preferred_when_ready(self):
        make_release(self.root / 'Downloads/HelixSR-2.0.0', BASE)  # extracted, not built
        found = H.find(self.package, home=self.root)
        self.assertEqual((found['state'], found['folder']), ('ready', str(self.release)))  # HelixSR-2.0.0 in the home folder is built
        shutil.rmtree(self.release)
        found = H.find(self.package, home=self.root)
        self.assertEqual((found['state'], found['folder']), ('unbuilt', str(self.root / 'Downloads/HelixSR-2.0.0')))
        self.assertIn(H.setup_command(found['folder']), H.guidance(found))

    def test_remembered_folder(self):
        elsewhere = make_release(self.root / 'games/tools/helix', built())
        shutil.rmtree(self.release)
        self.assertEqual(H.find(self.package, home=self.root)['state'], 'missing')
        H.remember(elsewhere)
        self.assertEqual(H.find(self.package, home=self.root)['folder'], str(elsewhere.resolve()))

    def test_command_with_a_given_folder_remembers_it(self):
        elsewhere = make_release(self.root / 'games/tools/helix', BASE)
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            self.assertEqual(m.helixsr_command(self.package, elsewhere, download=self.fail), 0)  # not built: the command to run
        self.assertIn(H.setup_command(elsewhere), text.getvalue())
        self.assertEqual(H._remembered(), elsewhere.resolve())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.helixsr_command(self.package, self.root / 'nowhere', download=self.fail), 1)

    def test_package_without_pin(self):
        pins = json.loads((self.package / 'dependencies.json').read_text()); del pins['helixsr']
        set_package_file(self.package, 'dependencies.json', json.dumps(pins).encode())
        self.assertEqual(H.find(self.package)['state'], 'unsupported')

    def test_ini(self):
        self.assertIn(b'[DlssFrameGeneration]\r\nEnabled = false\r\n', H.ini_bytes())
        self.assertIn(b'lonewolf0622', H.ini_bytes())
        user = b'[Upscaling]\nInt8 = auto\n\n[DlssFrameGeneration]\n; switch\nEnabled = true\nPreset = c\n\n[Log]\nEnabled = true\n'
        self.assertEqual(H.ini_bytes(user), b'[Upscaling]\nInt8 = auto\n\n[DlssFrameGeneration]\n; switch\nEnabled = false\nPreset = c\n\n[Log]\nEnabled = true\n')
        self.assertEqual(H.ini_bytes(b'[Upscaling]\r\nInt8 = on\r\n'), b'[Upscaling]\r\nInt8 = on\r\n\r\n[DlssFrameGeneration]\r\nEnabled = false\r\n')
        self.assertEqual(H.ini_bytes(b'[DlssFrameGeneration]\nPreset = full\n'), b'[DlssFrameGeneration]\nPreset = full\nEnabled = false\n')
        # A header with a comment after it is the same section (no second [DlssFrameGeneration]).
        self.assertEqual(H.ini_bytes(b'[DlssFrameGeneration] ; DLSS FG\nEnabled = true\n[Log] # x\nEnabled = true\n'),
                         b'[DlssFrameGeneration] ; DLSS FG\nEnabled = false\n[Log] # x\nEnabled = true\n')
        self.assertEqual(H.ini_bytes(H.INI_TEXT.encode('ascii')), H.INI_TEXT.encode('ascii'))

    def test_guidance_warns_about_enter_in_helixsr_game_list(self):
        text = H.guidance(dict(state='unbuilt', folder='/x', message='m', pinned='2.0.0'))
        self.assertIn('Ctrl+C', text); self.assertIn('Enter installs HelixSR its own way', text)
        self.assertIn('HelixSR Scaler in place of', text)
        unknown = H.guidance(dict(state='unknown', folder='/x', message='m', pinned='2.0.0'))
        self.assertIn('without --helixsr', unknown)


class Install(HelixFixture):
    def check_installed(self, folder='OptiScaler'):
        self.assertEqual((self.game / folder / m.DLL).read_bytes(), built())
        ini = (self.game / folder / H.INI).read_bytes()
        self.assertIn(b'[DlssFrameGeneration]\r\nEnabled = false', ini)
        self.assertFalse((self.game / folder / 'helixsr-fg').exists())  # HelixSR's frame generation never goes in
        self.assertFalse((self.game / folder / 'amd_fidelityfx_dx12.dll').exists())
        upscaler = self.record()['upscaler']
        self.assertEqual((upscaler['name'], upscaler['version'], upscaler['target']), ('helixsr', '2.0.0', folder + '/' + m.DLL))
        values = m.read_ini((self.game / 'OptiScaler.ini').read_bytes())
        self.assertEqual(values[('upscalers', 'dx12upscaler')], 'ffx')  # OptiScaler's FidelityFX upscaler: HelixSR
        self.assertEqual(values[('fsr', 'upscalerindex')], '0')

    def test_existing_optiscaler_round_trip(self):
        text = self.out(m.install, self.package, self.exe, route='opti', upscaler='helixsr')
        self.check_installed()
        self.assertIn('HelixSR 2.0.0, a separate project by lonewolf0622', text)
        self.assertIn(H.PROJECT, text)
        (self.game / 'OptiScaler' / H.LOG).write_text('helixsr log')  # the game ran
        status = self.out(m.status, self.exe)
        self.assertIn('Upscaler: HelixSR 2.0.0', status); self.assertIn('HelixSR log: ', status)
        self.assertIn('Changed since installation: none', status)
        m.restore(self.exe); self.assertOriginal()
        for name in (H.INI, H.LOG):
            self.assertFalse((self.game / 'OptiScaler' / name).exists(), name)
        logs = list((self.game / m.STATE).glob('runtime-logs-*/' + H.LOG))
        self.assertEqual([p.read_text() for p in logs], ['helixsr log'])

    def test_fresh_setup_native_route_round_trip(self):
        deps = self.fresh(); (self.game / 'OptiScaler').rmdir()
        m.write(self.game / 'libxess_fg.dll', b'game FG'); self.original = {'libxess_fg.dll': b'game FG'}
        m.install(self.package, self.exe, route='native', dependency_dir=deps, upscaler='helixsr')
        self.check_installed()
        (self.game / 'OptiScaler' / H.LOG).write_text('run')
        m.restore(self.exe); self.assertOriginal()
        self.assertFalse((self.game / 'OptiScaler').exists())  # created by the installation; HelixSR's log moved out

    def test_missing_helixsr_refused_before_anything(self):
        shutil.rmtree(self.release)
        with self.assertRaises(ValueError) as refused:
            m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.assertIn('install.py helixsr', str(refused.exception)); self.assertIn('lonewolf0622', str(refused.exception))
        self.assertFalse((self.game / m.STATE).exists()); self.assertOriginal()
        self.assertEqual(self.prepared, [])  # nothing downloaded

    def test_unbuilt_helixsr_refused_with_the_setup_command(self):
        (self.release / H.RELEASE_DLL).write_bytes(BASE)
        with self.assertRaises(ValueError) as refused:
            m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.assertIn(H.setup_command(self.release), str(refused.exception))
        self.assertIn('asks before it downloads NVIDIA', str(refused.exception))
        self.assertFalse((self.game / m.STATE).exists()); self.assertOriginal()

    def test_changed_dll_refused(self):
        (self.release / H.RELEASE_DLL).write_bytes(built(base=b'MZ another DLL'))
        with self.assertRaisesRegex(ValueError, 'not an official HelixSR release'):
            m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.assertOriginal()

    def test_given_folder(self):
        other = make_release(self.root / 'tools/x', built())
        shutil.rmtree(self.release)
        m.install(self.package, self.exe, route='opti', upscaler='helixsr', helixsr_dir=other)
        self.check_installed(); self.assertEqual(self.record()['upscaler']['release'], str(other))
        self.assertEqual(H._remembered(), other.resolve())  # named once: later runs find it without --helixsr
        m.restore(self.exe); self.assertOriginal()
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.check_installed(); m.restore(self.exe); self.assertOriginal()

    def test_edited_ini_kept_by_restore_and_carried_into_the_next_install(self):
        deps = self.fresh(); (self.game / 'OptiScaler').rmdir(); self.original = {}
        m.install(self.package, self.exe, route='opti', dependency_dir=deps, upscaler='helixsr')
        edited = (self.game / 'OptiScaler' / H.INI).read_bytes() + b'\r\n[Upscaling]\r\nInt8 = on\r\n'
        (self.game / 'OptiScaler' / H.INI).write_bytes(edited)
        text = self.out(m.restore, self.exe); self.assertOriginal()
        self.assertFalse((self.game / 'OptiScaler').exists())  # the created folder is gone, no edited ini left behind
        self.assertNotIn('Kept OptiScaler/' + H.INI, text); self.assertIn('Your edited ' + H.INI + ' is kept', text)
        kept = list((self.game / m.STATE).glob('preserved-ini/helixsr-*.ini'))
        self.assertEqual([p.read_bytes() for p in kept], [edited])
        m.install(self.package, self.exe, route='opti', dependency_dir=deps, upscaler='helixsr')
        self.assertEqual((self.game / 'OptiScaler' / H.INI).read_bytes(), edited)  # the user's settings, FG still off
        m.restore(self.exe); self.assertOriginal()

    def test_symlinked_log_does_not_stop_status_or_restore(self):
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        target = self.root / 'elsewhere.log'; target.write_text('not ours')
        (self.game / 'OptiScaler' / H.LOG).symlink_to(target)
        self.assertIn('not a regular file', self.out(m.status, self.exe))
        text = self.out(m.restore, self.exe)
        self.assertEqual(self.record()['status'], 'restored'); self.assertIn('Left OptiScaler/' + H.LOG + ' as it is', text)
        self.assertTrue((self.game / 'OptiScaler' / H.LOG).is_symlink()); self.assertEqual(target.read_text(), 'not ours')
        (self.game / 'OptiScaler' / H.LOG).unlink(); self.assertOriginal()

    def test_existing_helixsr_ini_patched_and_restored(self):
        user = b'[Upscaling]\nNetworkResolution = full\n[DlssFrameGeneration]\nEnabled = true\n'
        m.write(self.game / 'OptiScaler' / H.INI, user); self.original['OptiScaler/' + H.INI] = user
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.assertEqual((self.game / 'OptiScaler' / H.INI).read_bytes(), b'[Upscaling]\nNetworkResolution = full\n[DlssFrameGeneration]\nEnabled = false\n')
        m.restore(self.exe); self.assertOriginal()

    def test_earlier_log_set_aside_and_put_back(self):
        m.write(self.game / 'OptiScaler' / H.LOG, b'earlier'); self.original['OptiScaler/' + H.LOG] = b'earlier'
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.assertFalse((self.game / 'OptiScaler' / H.LOG).exists())
        (self.game / 'OptiScaler' / H.LOG).write_text('ours')
        m.restore(self.exe); self.assertOriginal()
        self.assertEqual([p.read_text() for p in (self.game / m.STATE).glob('runtime-logs-*/' + H.LOG)], ['ours'])

    def test_helixsr_own_install_refused(self):
        m.write(self.game / 'OptiScaler' / H.HELIXSR_MARKER, b'{}')
        for upscaler in ('helixsr', 'fsr4'):
            with self.assertRaisesRegex(ValueError, 'HelixSR’s uninstaller'):
                m.install(self.package, self.exe, route='opti', upscaler=upscaler)
        self.assertFalse((self.game / m.STATE).exists())

    def test_preview_names_the_upscaler_and_changes_nothing(self):
        text = self.out(m.install, self.package, self.exe, preview=True, route='opti', upscaler='helixsr')
        self.assertIn('OptiScaler/' + H.INI, text); self.assertIn('Upscaler: HelixSR 2.0.0', text)
        self.assertFalse((self.game / m.STATE).exists()); self.assertOriginal()

    def test_default_stays_fsr4(self):
        text = self.out(m.install, self.package, self.exe, route='opti')
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'FSR')
        self.assertFalse((self.game / 'OptiScaler' / H.INI).exists())
        self.assertEqual(self.record()['upscaler'], dict(name='fsr4', target='OptiScaler/' + m.DLL))
        self.assertIn('Upscaler: FSR 4', text)
        with self.assertRaisesRegex(ValueError, 'Unknown upscaler'):
            m.restore(self.exe); m.install(self.package, self.exe, upscaler='dlss')

    def test_credit_wording(self):
        # HelixSR is credited as lonewolf0622's separate project, never as part of this project.
        text = self.out(m.install, self.package, self.exe, route='opti', upscaler='helixsr')
        text += self.out(m.status, self.exe) + H.guidance(dict(state='unbuilt', folder='/x', message='m', pinned='2.0.0'))
        text += H.INI_TEXT + H.LABEL
        for word in ('collaborat', 'co-author', 'contributor', 'in partnership', 'together with'):
            self.assertNotIn(word, text.lower())
        self.assertIn('separate project by lonewolf0622', text)


class FSR4Builds(HelixFixture):
    """Status names the FSR 4 build a game has by its DLL's SHA-256: the one the package pins (RC12) or the one earlier
    builds placed (RC11). Records of builds without an upscaler record that placed RC11 stay identifiable."""
    RC12 = '4b0df27761d7ced52c30dcbd1641c55bdcf4d2ae10d59f7e5b4b2f895b6bba79'
    RC11 = '8192ea97620f8e6407bff346bf905f0d555ff73d89fe14616eb1fa5e41ab3175'

    def test_line_names_the_build(self):
        pins = json.loads((Path(m.__file__).parent / 'dependencies.json').read_text())
        self.assertEqual(m.FSR4_BUILDS[pins['runtime']['Files']['fsr4/' + m.DLL]], 'RC12')
        self.assertEqual(m.upscaler_line(dict(name='fsr4'), self.RC12), 'Upscaler: FSR 4 (BC-250 build RC12).')
        self.assertEqual(m.upscaler_line({}, self.RC11), 'Upscaler: FSR 4 (BC-250 build RC11).')
        self.assertEqual(m.upscaler_line({}, m.digest(b'FSR')), 'Upscaler: FSR 4 (BC-250 build).')

    def test_status_names_rc11_of_an_earlier_installation(self):
        m.install(self.package, self.exe, route='opti')
        state = self.game / m.STATE / 'state.json'; record = self.record()
        for item in record['files']:
            if item['path'] == 'OptiScaler/' + m.DLL:item['after'] = self.RC11
        state.write_text(json.dumps(record))
        self.assertIn('Upscaler: FSR 4 (BC-250 build RC11).', self.out(m.status, self.exe))
        record.pop('upscaler'); state.write_text(json.dumps(record))  # a build from before HelixSR: no upscaler record
        self.assertIn('Upscaler: FSR 4 (BC-250 build RC11).', self.out(m.status, self.exe))
        self.assertEqual(m.upscaler_target(record, dict(runtime=dict(Files={'fsr4/' + m.DLL: self.RC12}))),
                         dict(name='fsr4', target='OptiScaler/' + m.DLL))


class Switching(HelixFixture):
    def test_fsr4_to_helixsr_and_back(self):
        m.install(self.package, self.exe, route='opti')
        text = self.out(m.configure, self.exe, upscaler='helixsr', package=self.package)
        self.assertIn('Upscaler switched. Upscaler: HelixSR 2.0.0', text); self.assertNotIn('Nothing to change', text)
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), built())
        self.assertIn(b'Enabled = false', (self.game / 'OptiScaler' / H.INI).read_bytes())
        self.assertIn('Changed since installation: none', self.out(m.status, self.exe))
        self.assertIn('already uses HelixSR', self.out(m.configure, self.exe, upscaler='helixsr', package=self.package))
        (self.game / 'OptiScaler' / H.LOG).write_text('ran')
        m.configure(self.exe, upscaler='fsr4', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'FSR')
        for name in (H.INI, H.LOG):
            self.assertFalse((self.game / 'OptiScaler' / name).exists(), name)
        self.assertEqual(self.record()['upscaler']['name'], 'fsr4')
        self.assertIn('Changed since installation: none', self.out(m.status, self.exe))
        m.configure(self.exe, upscaler='helixsr', package=self.package)
        m.restore(self.exe); self.assertOriginal()
        self.assertFalse((self.game / 'OptiScaler' / H.INI).exists())

    def test_helixsr_to_fsr4_after_a_helixsr_install(self):
        user = b'[Log]\nEnabled = false\n'
        m.write(self.game / 'OptiScaler' / H.INI, user); self.original['OptiScaler/' + H.INI] = user
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        m.configure(self.exe, upscaler='fsr4', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / H.INI).read_bytes(), user)  # the user's file as it was
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'FSR')
        m.restore(self.exe); self.assertOriginal()

    def test_edited_ini_never_blocks_a_switch(self):
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        edited = (self.game / 'OptiScaler' / H.INI).read_bytes() + b'\r\n[Upscaling]\r\nNetworkResolution = full\r\n'
        (self.game / 'OptiScaler' / H.INI).write_bytes(edited)
        text = self.out(m.configure, self.exe, upscaler='fsr4', package=self.package)
        self.assertIn('Upscaler switched. Upscaler: FSR 4', text); self.assertIn('Your edited OptiScaler/' + H.INI + ' is kept', text)
        self.assertFalse((self.game / 'OptiScaler' / H.INI).exists())  # as before installation
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'FSR')
        self.assertEqual([p.read_bytes() for p in (self.game / m.STATE).glob('preserved-ini/helixsr-*.ini')], [edited])
        m.configure(self.exe, upscaler='helixsr', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / H.INI).read_bytes(), edited)  # back with the user's settings
        # Edited while on HelixSR, then the same HelixSR again: kept as it is (frame generation still forced off).
        (self.game / 'OptiScaler' / H.INI).write_bytes(edited.replace(b'Enabled = false', b'Enabled = true'))
        self.out(m.configure, self.exe, upscaler='helixsr', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / H.INI).read_bytes(), edited)
        self.assertIn('Changed since installation: none', self.out(m.status, self.exe))
        m.restore(self.exe); self.assertOriginal()

    def test_switch_to_missing_helixsr_changes_nothing(self):
        m.install(self.package, self.exe, route='opti'); before = self.record()
        shutil.rmtree(self.release)
        with self.assertRaisesRegex(ValueError, 'not on this computer'):
            m.configure(self.exe, upscaler='helixsr', package=self.package)
        self.assertEqual(self.record(), before); self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'FSR')

    def test_switch_refused_when_the_dll_changed(self):
        m.install(self.package, self.exe, route='opti')
        (self.game / 'OptiScaler' / m.DLL).write_bytes(b'game update')
        with self.assertRaisesRegex(ValueError, 'changed since installation'):
            m.configure(self.exe, upscaler='helixsr', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'game update')

    def test_interrupted_switch_is_resolved_by_restore(self):
        m.install(self.package, self.exe, route='opti')
        original_write = m.write
        def fail(path, *args, **kwargs):
            if Path(path).name == H.INI:
                raise OSError('Injected disk error')
            return original_write(path, *args, **kwargs)
        with patch.object(m, 'write', side_effect=fail):
            with self.assertRaises(OSError):
                m.configure(self.exe, upscaler='helixsr', package=self.package)
        self.assertIn('pending_update', self.record())
        m.restore(self.exe); self.assertOriginal()
        self.assertFalse((self.game / 'OptiScaler' / H.INI).exists())

    def test_record_of_an_earlier_build_switches(self):
        # Records written before the upscaler choice existed carry no 'upscaler': their FSR 4 DLL is found by its pin.
        m.install(self.package, self.exe, route='opti')
        record = self.record(); del record['upscaler']
        (self.game / m.STATE / 'state.json').write_text(json.dumps(record))
        m.configure(self.exe, upscaler='helixsr', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), built())
        m.restore(self.exe); self.assertOriginal()


class EnablerFreePackage(ProxyFixture):
    """The public package (libxess_fg.dll proxy) takes HelixSR the same way."""
    def setUp(self):
        super().setUp()
        cache = patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root / 'cache')})
        cache.start(); self.addCleanup(cache.stop)
        add_pins(self.package)
        make_release(self.root / 'HelixSR-2.0.0', built())

    def test_round_trip_and_switch(self):
        m.install(self.package, self.exe, route='opti', upscaler='helixsr')
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), built())
        self.assertEqual((self.game / 'libxess_fg.dll').read_bytes(), b'BC250 proxy')  # frame generation unchanged
        m.configure(self.exe, upscaler='fsr4', package=self.package)
        self.assertEqual((self.game / 'OptiScaler' / m.DLL).read_bytes(), b'FSR')
        m.restore(self.exe); self.assertOriginal()


class Download(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(__import__('tempfile').TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root / 'cache')}))
        self.package = self.root / 'package'; self.package.mkdir()
        (self.package / 'manifest.json').write_text(json.dumps({'files': {}}))
        (self.package / 'dependencies.json').write_text('{}')
        self.fetched = []

    def archive(self, members):
        path = self.root / 'archive.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name, data, mode in members:
                info = zipfile.ZipInfo(name); info.external_attr = (stat.S_IFREG | mode) << 16
                zf.writestr(info, data)
        data = path.read_bytes(); add_pins(self.package, archive=data)
        return data

    def download(self, item, cache):
        self.fetched.append(item['url'])
        self.assertEqual(item['url'], 'https://github.com/lonewolf0622/HelixSR/releases/download/v2.0.0/HelixSR-2.0.0.zip')
        dest = Path(cache) / item['file']; dest.write_bytes((self.root / 'archive.zip').read_bytes())
        self.assertEqual(m.digest(dest.read_bytes()), item['sha256'])
        return dest

    def test_unpacked_as_it_is_and_never_run(self):
        self.archive([('HelixSR-2.0.0/' + H.RELEASE_DLL, BASE, 0o644), ('HelixSR-2.0.0/helixsr-setup.sh', b'#!/bin/sh\n', 0o755),
                      ('HelixSR-2.0.0/LICENSE', b'HelixSR Freeware License', 0o644)])
        text = io.StringIO()
        with contextlib.redirect_stdout(text), patch('subprocess.run', side_effect=AssertionError('ran something')), \
                patch('subprocess.Popen', side_effect=AssertionError('ran something')), patch('os.system', side_effect=AssertionError):
            self.assertEqual(m.helixsr_command(self.package, None, self.download), 0)
        folder = H.cache_root() / 'HelixSR-2.0.0'
        self.assertEqual((folder / H.RELEASE_DLL).read_bytes(), BASE)
        self.assertEqual((folder / 'LICENSE').read_bytes(), b'HelixSR Freeware License')
        self.assertTrue(os.stat(folder / 'helixsr-setup.sh').st_mode & 0o100)
        self.assertFalse(os.stat(folder / 'LICENSE').st_mode & 0o111)
        self.assertEqual(list(H.cache_root().parent.glob('*.zip')), [])  # the archive is not kept twice
        self.assertIn(H.setup_command(folder), text.getvalue())
        # Already there: nothing downloaded again.
        with contextlib.redirect_stdout(io.StringIO()):
            m.helixsr_command(self.package, None, self.download)
        self.assertEqual(len(self.fetched), 1)

    def test_unknown_release_does_not_block_the_download(self):
        self.archive([('HelixSR-2.0.0/' + H.RELEASE_DLL, BASE, 0o644), ('HelixSR-2.0.0/helixsr-setup.sh', b'#!/bin/sh\n', 0o755)])
        self.enterContext(patch.dict(os.environ, {'HOME': str(self.root)}))
        make_release(self.root / 'Downloads/HelixSR-2.1.0', built(base=b'MZ a newer HelixSR'))
        self.assertEqual(H.find(self.package)['state'], 'unknown')
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            self.assertEqual(m.helixsr_command(self.package, None, self.download), 0)
        self.assertEqual(len(self.fetched), 1)
        self.assertIn('Not used: ', text.getvalue())
        found = H.find(self.package)
        self.assertEqual((found['state'], found['folder']), ('unbuilt', str(H.cache_root() / 'HelixSR-2.0.0')))
        self.assertEqual((self.root / 'Downloads/HelixSR-2.1.0' / H.RELEASE_DLL).read_bytes(), built(base=b'MZ a newer HelixSR'))
        # A folder named with --helixsr is never replaced by a download.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.helixsr_command(self.package, self.root / 'Downloads/HelixSR-2.1.0', self.download), 1)
        self.assertEqual(len(self.fetched), 1)

    def test_unsafe_or_unexpected_archives_refused(self):
        for members in ([('HelixSR-2.0.0/../evil', b'x', 0o644)], [('Other/' + H.RELEASE_DLL, BASE, 0o644)],
                        [('HelixSR-2.0.0/' + H.RELEASE_DLL, b'MZ not the pinned DLL', 0o644)]):
            self.archive(members)
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                m.helixsr_command(self.package, None, self.download)
            self.assertFalse((H.cache_root() / 'HelixSR-2.0.0').exists())
            self.assertFalse((self.root / 'evil').exists()); self.assertFalse((H.cache_root().parent / 'evil').exists())


class Doctor(HelixFixture):
    def test_rows(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('bc250_doctor_helixsr', Path(m.__file__).parent / 'doctor.py')
        doctor = importlib.util.module_from_spec(spec); spec.loader.exec_module(doctor)
        self.assertEqual(doctor.helixsr_row(self.root, self.package)[:2], ('OK', 'HelixSR'))
        (self.release / H.RELEASE_DLL).write_bytes(BASE)
        level, _, text = doctor.helixsr_row(self.root, self.package)
        self.assertEqual(level, 'INFO'); self.assertIn('./helixsr-setup.sh --no-fg', text); self.assertIn('lonewolf0622', text)
        shutil.rmtree(self.release)
        self.assertIn('not on this computer', doctor.helixsr_row(self.root, self.package)[2])
        self.assertIsNone(doctor.helixsr_row(self.root, self.root / 'no-package'))


if __name__ == '__main__':
    unittest.main()
