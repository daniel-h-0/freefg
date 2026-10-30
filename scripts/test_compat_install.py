# SPDX-License-Identifier: MIT
"""The installer with the compatibility verdict (install.py + compat.py + gamescan.py) on a synthetic Unreal game in a
Steam library: refusals before any download or write, keys from promoted wiki items and detection's DX12 switch
applied and restored exactly, a soft refusal accepted, verified recipes installed exactly as without the verdict, a
community recipe's game setting applied and restored, Check writing nothing and naming every refusal Install would
make for the game folder's state, and Automatic taking the verdict's input, with accepts given per game."""
import contextlib, hashlib, io, json, os, re, sys, unittest
from pathlib import Path
from unittest.mock import patch

from test_game_install import GameFixture, m
from test_gamescan import unreal, write
import launcher_config
from steam_config import Document

WIKI = dict(title='Hero', match=dict(title=['hero'], exe=['hero-win64-shipping.exe']), pages=['https://example.invalid/wiki/Hero'],
            promoted=[dict(key='Hotfix.ColorResourceBarrier', value='4')], ini=[dict(key='Hotfix.ColorResourceBarrier', value='4')])


class CompatFixture(GameFixture):
    """GameFixture's package and pinned files, with the game replaced by an Unreal game in a Steam library (AppID 4242,
    launch options '--skip-intro') whose OptiScaler setup sits beside its shipping executable."""
    def setUp(self):
        super().setUp()
        self.steam = self.root/'.local/share/Steam'
        hero = unreal(self.steam/'steamapps/common/Hero', inputs=('dlss',))
        self.game = hero/'Hero/Binaries/Win64'
        self.exe = self.game/'Hero-Win64-Shipping.exe'
        del self.original['libxess_fg.dll']  # no native XeSS FG: the OptiScaler route
        for name, data in self.original.items():
            m.write(self.game/name, data)
        write(self.steam, {'steamapps/appmanifest_4242.acf': '"AppState" { "appid" "4242" "name" "Hero" "installdir" "Hero" "StateFlags" "4" }'})
        (self.root/'.config/heroic/gog_store/installed.json').unlink()
        self.config.unlink()
        self.config = self.steam/'userdata/42/config/localconfig.vdf'
        self.set_options('--skip-intro')
        self.recipes(wiki=[WIKI])

    def set_options(self, options):
        self.config_bytes = ('"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "4242" { "LaunchOptions" "'
                             + options + '" } } } } } }\n').encode()
        m.write(self.config, self.config_bytes)

    def recipes(self, verified=(), wiki=(), quirk_keys=None, community=()):
        m.write(self.package/'recipes/recipes.json', json.dumps(dict(schema=1, verified=list(verified), wiki=list(wiki), leave_auto={},
                                                                     backports={}, quirk_keys=quirk_keys or {},
                                                                     community=list(community))).encode())

    def options(self):
        return Document(self.config.read_bytes()).get(launcher_config.APP + ['4242', 'LaunchOptions'])

    def current_ini(self):
        return m.read_ini((self.game/'OptiScaler.ini').read_bytes())

    def record(self):
        return json.loads((self.game/m.STATE/'state.json').read_text())

    def assertOriginal(self):
        for name, data in self.original.items():
            self.assertEqual((self.game/name).read_bytes(), data, name)
        self.assertEqual(self.config.read_bytes(), self.config_bytes)

    def snapshot(self):
        return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None, p.stat().st_mtime_ns)
                for p in sorted(self.root.rglob('*')) if not p.is_symlink()}


class VerdictInstallTests(CompatFixture):
    def test_wiki_key_and_detected_switch_are_restored_exactly(self):
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertEqual(self.current_ini()[('hotfix', 'colorresourcebarrier')], '4')
        self.assertTrue(self.options().endswith('%command% --skip-intro -dx12'))  # Unreal 4: -dx12 from detection
        record = self.record()
        self.assertEqual(record['compat']['tier'], 'C')
        self.assertEqual(record['compat']['ini_sources'], {'Hotfix.ColorResourceBarrier': 'OptiScaler wiki (Hero), promoted'})
        self.assertEqual(record['launch_args_added'], ['-dx12'])
        self.assertIn(dict(section='Hotfix', key='ColorResourceBarrier', value='4'), record['ini_changes'])
        m.restore(self.exe)
        self.assertOriginal()
        # The user's own value is kept, and nothing of the wiki's is recorded for it.
        ini = self.game/'OptiScaler.ini'
        mine = m.patch_ini(ini.read_bytes(), {('Hotfix', 'ColorResourceBarrier'): '2'})
        ini.write_bytes(mine)
        self.original['OptiScaler.ini'] = mine
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertEqual(self.current_ini()[('hotfix', 'colorresourcebarrier')], '2')
        m.restore(self.exe)
        self.assertOriginal()

    def test_a_key_an_optiscaler_quirk_sets_is_never_written(self):
        self.recipes(wiki=[WIKI], quirk_keys={'hero-win64-shipping.exe': {'Hotfix.ColorResourceBarrier': '8'}})
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertNotIn(('hotfix', 'colorresourcebarrier'), self.current_ini())
        m.restore(self.exe)
        self.assertOriginal()

    def test_refusals_come_before_any_download_or_write(self):
        def refused(code, **install):
            self.prepared.clear()
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, r'\[' + code + r'\]'):
                m.install(self.package, self.exe, route='opti', fg_input='upscaler', **install)
            self.assertEqual(self.prepared, [], code)
            self.assertEqual(self.snapshot(), before, code)
        fresh = self.fresh()  # a fresh OptiScaler setup would download first: the refusals still come before it
        self.original = {}
        anticheat = self.game.parents[2]/'EasyAntiCheat/EasyAntiCheat_x64.dll'
        write(anticheat.parent, {anticheat.name: b'x'})
        refused('anticheat', dependency_dir=fresh)
        anticheat.unlink()
        anticheat.parent.rmdir()
        self.set_options('PROTON_FSR4_UPGRADE=1 %command%')
        refused('ge-optiscaler')
        self.set_options('VK_LAYER_PATH=/elsewhere/Game/BC250-XeFG/layer %command%')
        refused('shared-entry')
        self.set_options('--skip-intro')
        plugin = self.game.parents[2]/'Engine/Plugins/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll'
        plugin.unlink()
        self.exe.write_bytes(self.exe.read_bytes().replace(b'r.NGX.DLSS.Enable', b'r.NOT.ANY.Thing'))
        refused('no-input')

    def test_protonfix_refusal_accepted_and_restored(self):
        write(self.steam, {'config/config.vdf': '"InstallConfigStore" { "Software" { "Valve" { "Steam" { "CompatToolMapping" { '
                                                '"4242" { "name" "GE-Proton11-7" } } } } } }',
                           'compatibilitytools.d/GE-Proton11-7/protonfixes/gamefixes-steam/4242.py':
                           "from protonfixes import util\ndef main():\n    util.append_argument('-dx11')\n"})
        with self.assertRaisesRegex(ValueError, r'\[protonfix-api\]'):
            m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertFalse((self.game/m.STATE).exists())
        m.install(self.package, self.exe, route='opti', fg_input='upscaler', accept=['protonfix-api'])
        self.assertIn('PROTONFIXES_DISABLE=1', self.options().split())
        self.assertEqual(self.record()['compat']['accepted'], ['protonfix-api'])
        m.restore(self.exe)
        self.assertOriginal()

    def test_dlss_only_game_gets_the_helper_from_detection(self):
        plugin = self.game.parents[2]/'Engine/Plugins/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll'
        plugin.unlink()  # the game calls DLSS (its code says so) but ships no copy OptiScaler finds
        deps = self.fresh()
        self.original = {}
        m.install(self.package, self.exe, route='opti', fg_input='upscaler', dependency_dir=deps)
        helper = self.record()['dlss_helper']
        self.assertTrue(helper['placed'])
        self.assertIn('detection', helper['reason'])
        self.assertTrue((self.game/'nvngx_dlss.dll').is_file())
        m.restore(self.exe)
        self.assertFalse((self.game/'nvngx_dlss.dll').exists())
        self.assertEqual(self.config.read_bytes(), self.config_bytes)

    def test_verified_recipe_installs_exactly_as_without_the_verdict(self):
        verified = dict(title='Hero', match=dict(exe=['hero-win64-shipping.exe'], steam=['4242']), status='verified-bc250', route='opti',
                        fg_input='upscaler', ini={'FrameGen.FTInput': '2'}, game_settings=[], launch_args=['-d3d12'], note='n')
        self.recipes(verified=[verified], wiki=[WIKI])
        results = []
        for with_verdict in (True, False):
            context = contextlib.nullcontext() if with_verdict else patch.object(m, 'compat_verdict', return_value=None)
            with context:
                m.install(self.package, self.exe, route='opti', fg_input='upscaler')
            record = self.record()
            results.append(((self.game/'OptiScaler.ini').read_bytes(), self.config.read_bytes(), record['launch_args'],
                            record['ini_changes'], record.get('recipe')))
            self.assertEqual('compat' in record, with_verdict)
            m.restore(self.exe)
            self.assertOriginal()
        self.assertEqual(results[0], results[1])
        self.assertNotIn(b'ColorResourceBarrier', results[0][0])  # the wiki key stays out under a verified recipe

    def test_check_writes_nothing_and_reports_without_paths(self):
        before = self.snapshot()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch('doctor.checks', return_value=[('INFO', 'Kernel', '7.2.8')]):
            m.check(self.package, self.exe, report=True)
        text = out.getvalue()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(text.startswith('Automatic, guided by the OptiScaler wiki: detected Unreal Engine UE4, DLSS → OptiFG input'))
        self.assertIn('Launch option: -dx12 (detection (likely needed))', text)
        self.assertIn('OptiScaler.ini Hotfix.ColorResourceBarrier=4', text)
        report = text[text.index('### Game report'):]
        self.assertNotIn(str(self.root), report)
        self.assertIn('- Kernel: 7.2.8', report)

    def test_automatic_takes_the_verdicts_input(self):
        calls = []
        with patch.object(m, 'install', side_effect=lambda *a, **k: calls.append((a[3:5], k['verdict']['tier']))), \
             patch.object(sys, 'argv', ['install.py', 'install', str(self.exe)]):
            self.assertEqual(m.main(), 0)
        # main() reads the recipes beside install.py (the source tree's, which do not know this game): detection decides.
        self.assertEqual(calls, [(('opti', 'upscaler'), 'D')])

    def test_explicit_input_installs_despite_a_detection_refusal_once_accepted(self):
        # Detection finds no input (a packed executable could hide one): the user's explicit choice is refused unless
        # accepted, then installed and restored exactly.
        plugin = self.game.parents[2]/'Engine/Plugins/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll'
        plugin.unlink()
        self.exe.write_bytes(self.exe.read_bytes().replace(b'r.NGX.DLSS.Enable', b'r.NOT.ANY.Thing'))
        with self.assertRaisesRegex(ValueError, r'Install anyway \(you chose the input\).*\[no-input\]'):
            m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertFalse((self.game/m.STATE).exists())
        m.install(self.package, self.exe, route='opti', fg_input='upscaler', accept=['no-input'])
        self.assertEqual(self.record()['compat']['accepted'], ['no-input'])
        m.restore(self.exe)
        self.assertOriginal()

    def test_community_recipe_game_setting_applied_and_restored(self):
        user = self.steam/'steamapps/compatdata/4242/pfx/drive_c/users/steamuser'
        settings = user/'AppData/Local/Hero/Saved/Config/Windows/GameUserSettings.ini'
        original = b'[/Script/Hero.HeroSettings]\r\nFrameGenerationMode=Off\r\nResolutionQuality=100\r\n'
        m.write(settings, original)
        community = dict(title='Hero', match=dict(steam=['4242']), status='community-bc250', route='opti', fg_input='dlssg', ini={},
                         game_settings=[dict(file='AppData/Local/Hero/Saved/Config/Windows/GameUserSettings.ini', format='ini-replace',
                                             section=None, values={'FrameGenerationMode': 'DLSS'})],
                         launch_args=['-dx12'], manual_steps=['Choose DLSS in Video.'], reports=1)
        self.recipes(wiki=[WIKI], community=[community])
        m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        self.assertIn(b'FrameGenerationMode=DLSS\r\n', settings.read_bytes())
        record = self.record()
        self.assertEqual((record['compat']['tier'], record['recipe']['status'], record['recipe']['title']), ('B', 'community-bc250', 'Hero'))
        self.assertEqual(record['game_settings'][0]['status'], 'applied')
        m.restore(self.exe)
        self.assertEqual(settings.read_bytes(), original)
        self.assertOriginal()
        # Another input than the recipe's: its game settings belong to its input, so none is written.
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertEqual(settings.read_bytes(), original)
        m.restore(self.exe)
        self.assertOriginal()

    def test_check_does_not_read_another_setups_logs(self):
        # An OptiScaler log with no installation of this build recorded (an earlier OptiScaler, Luma) says nothing
        # about this build's last run.
        (self.game/'OptiScaler.log').write_text('[E] something failed\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            m.check(self.package, self.exe)
        self.assertNotIn('After the last run', out.getvalue())
        self.assertIn('Logs from another setup are in the game folder (not read', out.getvalue())
        (self.game/'OptiScaler.log').unlink()
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        (self.game/'OptiScaler.log').write_text('[I] FrameGen.FGInput: upscaler\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            m.check(self.package, self.exe)
        self.assertIn('After the last run', out.getvalue())
        (self.game/'OptiScaler.log').unlink()
        m.restore(self.exe)
        self.assertOriginal()

    def test_check_names_mfg_unlocker_cases(self):
        # MFG Unlocker's plugin in the game folder: Check names what it means for this installation (XeFGModel on the
        # OptiScaler route; stepping aside on the native route) and, after a partial run, says the fix once.
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        ini = self.game/'OptiScaler.ini'
        installed = ini.read_bytes()
        m.write(self.game/'OptiScaler/plugins/MFGUnlocker.asi', b'placeholder')

        def check():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                m.check(self.package, self.exe)
            return out.getvalue()
        self.assertNotIn('XeFGModel is', check())  # Install wrote default
        ini.write_bytes(m.patch_ini(installed, {('XeFG', 'XeFGModel'): 'auto'}))
        self.assertIn('MFG Unlocker (OptiScaler/plugins/MFGUnlocker.asi) is in this game folder and XeFGModel is auto', check())
        (self.game/'BC250-MFG.log').write_text("MFG proxy ready\nFAST_COEXIST another module hooks Intel's XeFG runtime (x: y; jumps to "
                                               'MFGUnlocker.asi): z\nFAST_OWNER first initialized context selected\n')
        (self.game/'BC250-XeFG-fast.log').write_text(''.join(f'REPLACE {i:016x} 56888\n' for i in range(7)))
        text = check()
        self.assertIn("Acceleration: partial (this build's shaders ran on 7 of 13 programs): MFG Unlocker's own model replaced the rest.", text)
        self.assertEqual(text.count('set XeFGModel=default'), 1)
        for name in ('BC250-MFG.log', 'BC250-XeFG-fast.log', 'OptiScaler/plugins/MFGUnlocker.asi'):
            (self.game/name).unlink()
        ini.write_bytes(installed)
        m.restore(self.exe)
        self.assertOriginal()

    def test_an_accept_naming_a_game_applies_to_that_game_only(self):
        other = self.root/'Other/Other.exe'
        m.write(other, self.exe.read_bytes())
        calls = []
        argv = ['install.py', 'install', str(self.exe), str(other), '--route', 'opti', '--fg-input', 'upscaler',
                '--accept', 'protonfix-api=' + str(self.exe), '--accept', 'wiki-not-working']
        with patch.object(m, 'install', side_effect=lambda *a, **k: calls.append((a[1].name, k['accept']))), patch.object(sys, 'argv', argv):
            self.assertEqual(m.main(), 0)
        self.assertEqual(calls, [('Hero-Win64-Shipping.exe', ['protonfix-api', 'wiki-not-working']), ('Other.exe', ['wiki-not-working'])])

    def test_check_command_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(sys, 'argv', ['install.py', 'check', str(self.exe)]):
            self.assertEqual(m.main(), 0)
        self.assertIn('Your steps:', out.getvalue())


if __name__ == '__main__':
    unittest.main()


class FolderStateTests(CompatFixture):
    """Every refusal install() makes for the game folder's state before it downloads or writes anything is named by
    Check first (install.preconditions, which repeats install()'s own conditions): the same games refuse in both."""

    def check_text(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            m.check(self.package, self.exe)
        return out.getvalue()

    def assertBoth(self, code, install_error):
        """Check names code with the plan; Install refuses with it before any change; and install()'s own check (no
        verdict at all) refuses the same folder with install_error: the two lists agree."""
        text = self.check_text()
        self.assertIn(f'[{code}, hard, before Install, refused]', text)
        self.assertIn('. Before Install: ', text.splitlines()[0])
        self.assertIn('Plan: OptiFG input', text)  # what Install will do once that is resolved
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, r'\[' + code + r'\]|' + install_error):  # preflight, or install()'s own check first
            m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        with patch.object(m, 'compat_verdict', return_value=None), self.assertRaisesRegex(ValueError, install_error):
            m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertEqual(self.snapshot(), before, code)

    def test_a_clean_folder_has_none(self):
        self.assertNotIn('before Install', self.check_text())
        self.assertEqual(m.preconditions(self.package, self.exe), [])

    def test_an_installation_not_restored(self):
        m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertBoth('installed', r'installation record already exists')
        m.restore(self.exe)
        self.assertNotIn('before Install', self.check_text())  # a restored record is no obstacle
        self.assertOriginal()

    def test_another_mods_files(self):
        m.write(self.game/'XeSSMFG/settings.ini', b'[XeSSMFG]\r\n')
        self.assertBoth('xessmfg', r'XeSSMFG folder')
        (self.game/'XeSSMFG/settings.ini').unlink()
        (self.game/'XeSSMFG').rmdir()
        m.write(self.game/'version.dll', b'another mod')  # this package's XeSSMFG enabler loads as version.dll
        self.assertBoth('version-dll', r'version.dll is occupied')

    def test_an_optiscaler_setup_from_elsewhere(self):
        m.write(self.game/'dxgi.dll', b'another OptiScaler build')
        self.assertBoth('existing-optiscaler', r'Existing OptiScaler must be')
        m.write(self.game/'dxgi.dll', self.original['dxgi.dll'])
        ini = self.game/'OptiScaler.ini'
        m.write(ini, m.patch_ini(ini.read_bytes(), {('Libraries', 'XeFGPath'): r'C:\elsewhere\libxess_fg.dll'}))
        self.assertBoth('optiscaler-paths', r'custom DLL path')
        m.write(ini, self.original['OptiScaler.ini'])
        (self.game/'OptiScaler'/m.DLL).unlink()  # the setup's FSR4 DLL is missing
        self.assertBoth('optiscaler-paths', r'configured local FSR4 DLL')
        m.write(self.game/'OptiScaler'/m.DLL, self.original['OptiScaler/'+m.DLL])
        self.assertEqual(m.preconditions(self.package, self.exe), [])

    def test_helixsrs_own_installation(self):
        # HelixSR's own installer (not this package's HelixSR choice) left its record where the upscaler DLL goes.
        m.write(self.game/'OptiScaler'/m.helixsr.HELIXSR_MARKER, b'{}')
        self.assertBoth('helixsr-installer', r'HelixSR’s own installer placed HelixSR')
        (self.game/'OptiScaler'/m.helixsr.HELIXSR_MARKER).unlink()
        self.assertEqual(m.preconditions(self.package, self.exe), [])

    def test_an_optiscaler_setup_linked_from_elsewhere(self):
        # A shared payload linked into the game folder (the maintainers' older FSR4 owner): an accepted build, but a
        # symlink, which install() does not follow.
        shared = self.root/'shared/dxgi.dll'
        m.write(shared, self.original['dxgi.dll'])
        (self.game/'dxgi.dll').unlink()
        (self.game/'dxgi.dll').symlink_to(shared)
        self.assertBoth('existing-optiscaler', r'Symlink needs a manual installation')
        self.assertIn('(dxgi.dll is a symlink)', self.check_text())

    def test_a_folder_path_that_is_not_ascii(self):
        common = self.steam/'steamapps/common'
        (common/'Hero').rename(common/'Héro')
        write(self.steam, {'steamapps/appmanifest_4242.acf': '"AppState" { "appid" "4242" "name" "Hero" "installdir" "Héro" "StateFlags" "4" }'})
        self.game = common/'Héro/Hero/Binaries/Win64'
        self.exe = self.game/'Hero-Win64-Shipping.exe'
        self.assertBoth('ascii-path', r'shader loader needs an ASCII-only')

    def test_a_partial_setup_without_its_ini(self):
        self.fresh()
        self.original = {}
        m.write(self.game/'dxgi.dll', b'another proxy mod')  # where a fresh setup puts OptiScaler
        self.assertBoth('existing-files', r'manual mod chaining')

    def test_a_verified_games_other_executable(self):
        verified = dict(title='Hero', match=dict(steam=['4242'], exe=['hero-shipping.exe']), status='verified-bc250', route='opti',
                        fg_input='upscaler', ini={}, game_settings=[], launch_args=[], note=None)
        self.recipes(verified=[verified], wiki=[WIKI])
        text = self.check_text()
        self.assertIn('[recipe-exe, hard, before Install, refused]', text)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'hero-shipping.exe'):
            m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertEqual(self.snapshot(), before)

    def test_install_refuses_nothing_check_does_not_name(self):
        # The other direction: every condition install() checks before its downloads has a precondition code. A game
        # folder that passes preconditions() installs (the round trips above), and each install() refusal message of
        # the folder's state is matched by one assertBoth case here.
        source = (Path(m.__file__).read_text())
        start = source.index('def install(')
        body = source[start:source.index('    dependencies={}', start)]
        refusals = re.findall(r"raise ValueError\('([^']+)", body)
        covered = ('installation record already exists', 'shader loader needs an ASCII-only', 'version.dll is occupied', 'XeSSMFG folder',
                   'Installation state is a symlink', 'For ' "(a verified game's other executable: recipe-exe)", 'This build needs a game with native',
                   'Unknown integration route', 'Unknown DLSS helper', 'Unknown upscaler', 'Choose the actual game', 'This installer installs only',
                   'Unknown add-on entry', 'Package lacks', 'install.py and dependencies.json', 'Package file differs')
        self.assertEqual([r for r in refusals if not any(c.startswith(r) or r in c or c in r for c in covered)], [])


SENTENCE = 'I accept that my account may be banned'


class AntiCheatOverrideTests(CompatFixture):
    """The anti-cheat override (install.py --accept-anticheat-risk): refused without it whatever is accepted; with it,
    installed and recorded, shown by Status and Check, cleared by Restore and asked for again by the next Install; on the
    command line only after the warning and the typed sentence, and only for the game it names."""

    def setUp(self):
        super().setUp()
        anticheat = self.game.parents[2]/'EasyAntiCheat/EasyAntiCheat_x64.dll'
        write(anticheat.parent, {anticheat.name: b'x'})

    def output(self, function, *args, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            function(*args, **kwargs)
        return out.getvalue()

    def main(self, *argv, typed=None, tty=True):
        """main() with install() replaced: (exit status, [(exe name, accept_risk, accept, verdict)], stdout, stderr). typed is
        what the user types at the terminal (None: asking at all fails the test)."""
        calls, out, err = [], io.StringIO(), io.StringIO()

        def ask(prompt=''):
            if typed is None:
                raise AssertionError('asked for the sentence')
            if isinstance(typed, BaseException):
                raise typed
            return typed
        with patch.object(m, 'install', side_effect=lambda *a, **k: calls.append((a[1].name, k['accept_risk'], k['accept'], k['verdict']))), \
             patch.object(m, 'terminal', return_value=tty), patch('builtins.input', side_effect=ask), \
             patch.object(sys, 'argv', ['install.py', *map(str, argv)]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = m.main()
        self.assertNotIn('Unexpected error', err.getvalue())
        return code, calls, out.getvalue(), err.getvalue()

    def test_the_installer_offers_what_setup_calls(self):
        for name in ('RISK_SENTENCE', 'risk_confirmed', 'anticheat_names', 'anticheat_warning', 'compat_verdict'):
            self.assertTrue(hasattr(m, name), name)
        self.assertTrue(m.risk_confirmed('  ' + SENTENCE + ' '))
        for wrong in ('', 'yes', SENTENCE.lower(), SENTENCE + '.', 'I accept', None):
            self.assertFalse(m.risk_confirmed(wrong), wrong)

    def test_refused_whatever_is_accepted(self):
        before = self.snapshot()
        for accept in ([], ['anticheat'], ['anticheat', 'protonfix-api', 'wiki-not-working', 'no-input', 'input-unconfirmed']):
            with self.assertRaisesRegex(ValueError, r'--accept-anticheat-risk.*\[anticheat\]'):
                m.install(self.package, self.exe, route='opti', fg_input='upscaler', accept=accept)
        err = io.StringIO()
        with patch.object(sys, 'argv', ['install.py', 'install', str(self.exe), '--accept', 'anticheat']), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(m.main(), 1)
        self.assertIn('[anticheat]', err.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_override_recorded_shown_and_cleared_by_restore(self):
        before = self.snapshot()
        preview = self.output(m.install, self.package, self.exe, preview=True, route='opti', fg_input='upscaler', accept_risk=['anticheat'])
        self.assertIn('Anti-cheat refusal overridden at your request (risk accepted): This game ships anti-cheat: Easy Anti-Cheat', preview)
        self.assertEqual(self.snapshot(), before)
        out = self.output(m.install, self.package, self.exe, route='opti', fg_input='upscaler', accept_risk=['anticheat'])
        self.assertIn('Anti-cheat refusal overridden at your request (risk accepted)', out)
        [entry] = self.record()['risk_accepted']
        self.assertEqual({k: entry[k] for k in ('code', 'anticheat', 'package')},
                         dict(code='anticheat', anticheat=['Easy Anti-Cheat'], package='bc250-fsr4-xemfg-private-test-99'))
        self.assertRegex(entry['accepted_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        self.assertEqual(self.record()['compat']['accepted'], [])
        line = f'Installed despite anti-cheat (Easy Anti-Cheat), risk accepted on {entry["accepted_at"][:10]}.'
        self.assertIn(line, self.output(m.status, self.exe).splitlines())
        check = self.output(m.check, self.package, self.exe)
        self.assertIn(line, check.splitlines())
        # Check says what a new Install would meet: the refusal, with the override named.
        self.assertTrue(check.startswith('Not supported: This game ships anti-cheat'))
        self.assertIn('[anticheat, risk, refused]', check)
        with patch('doctor.checks', return_value=[]):
            report = self.output(m.check, self.package, self.exe, report=True)
        self.assertIn('- ' + line, report[report.index('### Game report'):])
        restored = self.output(m.restore, self.exe)
        self.assertIn('The anti-cheat override ended with this installation', restored)
        self.assertOriginal()
        self.assertNotIn('risk_accepted', self.record())
        self.assertNotIn('Installed despite', self.output(m.status, self.exe))
        self.assertNotIn('Installed despite', self.output(m.check, self.package, self.exe))
        # Not carried: the next Install is refused again until the override is given again.
        with self.assertRaisesRegex(ValueError, r'\[anticheat\]'):
            m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.output(m.install, self.package, self.exe, route='opti', fg_input='upscaler', accept_risk=['anticheat'])
        self.assertEqual(len(self.record()['risk_accepted']), 1)
        self.output(m.restore, self.exe)
        self.assertOriginal()

    def test_a_game_without_anticheat_records_nothing(self):
        (self.game.parents[2]/'EasyAntiCheat/EasyAntiCheat_x64.dll').unlink()
        (self.game.parents[2]/'EasyAntiCheat').rmdir()  # the folder alone is anti-cheat evidence too
        self.output(m.install, self.package, self.exe, route='opti', fg_input='upscaler', accept_risk=['anticheat'])
        self.assertNotIn('risk_accepted', self.record())
        self.assertNotIn('anti-cheat', self.output(m.status, self.exe))
        self.output(m.restore, self.exe)
        self.assertOriginal()

    def test_command_line_at_a_terminal(self):
        code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', typed=SENTENCE)
        self.assertEqual(code, 0, err)
        [(name, risk, accept, verdict)] = calls
        self.assertEqual((name, risk, accept), ('Hero-Win64-Shipping.exe', ['anticheat'], []))
        # Automatic: install() gets the verdict with the override applied.
        self.assertEqual((verdict['blocking'], verdict['risk_accepted']), ([], ['anticheat']))
        for fact in ('Hero-Win64-Shipping.exe ships anti-cheat: Easy Anti-Cheat.', 'This build loads DLLs into the game process',
                     'a ban of your account or a refusal to start the game', 'does not hide itself from anti-cheat and will not try to',
                     'at most in offline or single-player modes; the anti-cheat can run in those modes too',
                     'The maintainers cannot help with bans.',
                     'Restore removes the DLLs and launch settings this build added; its backup folder .bc250-xefg-experimental',
                     'Restore cannot undo a ban.', 'type this sentence exactly', SENTENCE):
            self.assertIn(fact, out)
        self.assertLess(out.index('ships anti-cheat'), out.index('type this sentence exactly'))
        # Blanks around the sentence are allowed; anything else cancels before install() is called.
        self.assertEqual(self.main('install', self.exe, '--accept-anticheat-risk', typed='  ' + SENTENCE + '  ')[:2][0], 0)
        for wrong in ('', 'yes', SENTENCE.lower(), SENTENCE + '.'):
            code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', typed=wrong)
            self.assertEqual((code, calls), (1, []), wrong)
            self.assertIn('does not match the sentence', err)
        # An explicit input: install() makes the verdict itself, with the override.
        code, calls, out, err = self.main('preview', self.exe, '--route', 'opti', '--fg-input', 'upscaler', '--accept-anticheat-risk', typed=SENTENCE)
        self.assertEqual((code, [c[:3] for c in calls], calls[0][3]), (0, [('Hero-Win64-Shipping.exe', ['anticheat'], [])], None))

    def test_command_line_without_a_terminal_needs_the_sentence_spelled_out(self):
        code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', tty=False)
        self.assertEqual((code, calls), (1, []))
        self.assertIn('--confirm-anticheat-risk "' + SENTENCE + '"', err)
        self.assertIn('ships anti-cheat: Easy Anti-Cheat', out)  # the warning comes first either way
        code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', '--confirm-anticheat-risk', 'I accept', tty=False)
        self.assertEqual((code, calls), (1, []))
        self.assertIn('does not match the sentence', err)
        # Without a terminal, the sentence given on the command line confirms it.
        code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk=' + str(self.exe), '--confirm-anticheat-risk', SENTENCE, tty=False)
        self.assertEqual((code, [c[:2] for c in calls]), (0, [('Hero-Win64-Shipping.exe', ['anticheat'])]))
        self.assertNotIn('type this sentence', out)
        # At a terminal it is typed all the same: a pasted command with the sentence does not skip the prompt.
        for typed, result in ((SENTENCE, (0, [('Hero-Win64-Shipping.exe', ['anticheat'])])), ('', (1, []))):
            code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', '--confirm-anticheat-risk', SENTENCE, typed=typed)
            self.assertEqual((code, [c[:2] for c in calls]), result, typed)
            self.assertIn('At a terminal the sentence is typed', out)
            self.assertIn('type this sentence exactly', out)

    def test_command_line_scopes_the_override_to_one_game(self):
        other = self.root/'Other/Other.exe'
        m.write(other, self.exe.read_bytes())
        both = ['install', self.exe, other]
        code, calls, out, err = self.main(*both, '--accept-anticheat-risk=' + str(self.exe), '--confirm-anticheat-risk', SENTENCE, tty=False)
        self.assertEqual((code, [c[:2] for c in calls]), (0, [('Hero-Win64-Shipping.exe', ['anticheat']), ('Other.exe', [])]))
        # A game without anti-cheat: the override changes nothing there.
        code, calls, out, err = self.main('install', other, '--accept-anticheat-risk', '--confirm-anticheat-risk', SENTENCE, tty=False)
        self.assertEqual((code, [c[:2] for c in calls]), (0, [('Other.exe', [])]))
        self.assertIn('No anti-cheat found in this game', out)
        # Refused before any game is touched: a bare option for two games, a game the command does not name, the option
        # swallowing the only game, the confirmation alone, another command.
        for argv in ([*both, '--accept-anticheat-risk', '--confirm-anticheat-risk', SENTENCE],
                     ['install', other, '--accept-anticheat-risk=' + str(self.exe), '--confirm-anticheat-risk', SENTENCE],
                     ['install', '--accept-anticheat-risk', self.exe],
                     ['install', self.exe, '--confirm-anticheat-risk', SENTENCE],
                     ['check', self.exe, '--accept-anticheat-risk'], ['restore', self.exe, '--accept-anticheat-risk']):
            with self.assertRaises(SystemExit) as stopped:
                self.main(*argv, tty=False)
            self.assertEqual(stopped.exception.code, 2, argv)

    def test_another_refusal_comes_first_without_asking(self):
        self.set_options('PROTON_FSR4_UPGRADE=1 %command%')
        code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk')
        self.assertEqual((code, calls), (1, []))
        self.assertIn('[ge-optiscaler]', err)
        self.assertNotIn('type this sentence', out)

    def test_terminal_needs_both_stdin_and_stdout(self):
        class Stream(io.StringIO):
            def __init__(self, tty):
                super().__init__()
                self.tty = tty

            def isatty(self):
                return self.tty
        for stdin, stdout in ((True, True), (True, False), (False, True), (False, False)):
            with patch.object(sys, 'stdin', Stream(stdin)), patch.object(sys, 'stdout', Stream(stdout)):
                self.assertEqual(m.terminal(), stdin and stdout, (stdin, stdout))

    def test_end_of_input_or_ctrl_c_at_the_prompt_cancels(self):
        for stop in (EOFError(), KeyboardInterrupt()):
            code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', typed=stop)
            self.assertEqual((code, calls), (1, []), stop)
            self.assertIn('Anti-cheat override cancelled', err)
            self.assertNotIn('Traceback', err)

    def test_a_running_game_is_named_before_the_sentence(self):
        with patch.object(m, 'idle', side_effect=ValueError('Close the game before installing or restoring')):
            code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk')  # typed=None: asking fails
        self.assertEqual((code, calls), (1, []))
        self.assertIn('Close the game', err)
        self.assertNotIn('ships anti-cheat', out)

    def test_without_a_compatibility_check_the_override_is_refused(self):
        # compat_verdict None: the modules are missing or the scan failed, so nothing says whether the game ships anti-cheat.
        with patch.object(m, 'compat_verdict', return_value=None):
            code, calls, out, err = self.main('install', self.exe, '--accept-anticheat-risk', '--confirm-anticheat-risk', SENTENCE, tty=False)
        self.assertEqual((code, calls), (1, []))
        self.assertIn('the compatibility check did not run, so anti-cheat was not checked', err)
        self.assertNotIn('No anti-cheat found', out)

    def test_the_option_without_a_game_says_where_the_game_goes(self):
        err = io.StringIO()
        with patch.object(sys, 'argv', ['install.py', 'install', '--accept-anticheat-risk', str(self.exe)]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            m.main()
        self.assertIn('name the game before the option: install.py install GAME.exe --accept-anticheat-risk[=GAME.exe]', err.getvalue())

    def test_settings_keep_the_override_and_an_interrupted_one_shows(self):
        self.output(m.install, self.package, self.exe, route='opti', fg_input='upscaler', accept_risk=['anticheat'])
        entry = self.record()['risk_accepted']
        # Settings rewrite the record of the same installation: the override stays, and Status still shows it.
        self.output(m.configure, self.exe, factor=3)
        self.assertEqual(self.record()['risk_accepted'], entry)
        line = f'Installed despite anti-cheat (Easy Anti-Cheat), risk accepted on {entry[0]["accepted_at"][:10]}.'
        self.assertIn(line, self.output(m.status, self.exe).splitlines())
        # check --all names it beside the verdict, which stays the refusal.
        with patch('gamescan.installed_games', return_value=[dict(path=str(self.steam/'steamapps/common/Hero'), name='Hero', store='steam', id='4242')]):
            listing = self.output(m.check_all, self.package, home=self.root)
        self.assertIn('Hero [steam 4242]: Not supported: This game ships anti-cheat', listing)
        self.assertIn(line, listing)
        # An interrupted installation (its DLLs may be in place) shows it too, and Restore clears it.
        record = self.record()
        record['status'] = 'prepared'
        m.write(self.game/m.STATE/'state.json', json.dumps(record).encode())
        interrupted = 'Interrupted installation despite anti-cheat (Easy Anti-Cheat), risk accepted on ' + entry[0]['accepted_at'][:10] + '.'
        self.assertIn(interrupted, self.output(m.status, self.exe).splitlines())
        self.assertIn(interrupted, self.output(m.check, self.package, self.exe).splitlines())
        self.assertIn('The anti-cheat override ended with this installation', self.output(m.restore, self.exe))
        self.assertNotIn('risk_accepted', self.record())
        self.assertOriginal()

    def test_the_upscaler_switch_keeps_the_override(self):
        from test_helixsr_install import add_pins, built, make_release
        cache = patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root/'cache')})
        cache.start()
        self.addCleanup(cache.stop)
        add_pins(self.package)
        make_release(self.root/'HelixSR-2.0.0', built())
        self.output(m.install, self.package, self.exe, route='opti', fg_input='upscaler', accept_risk=['anticheat'])
        entry = self.record()['risk_accepted']
        self.output(m.configure, self.exe, upscaler='helixsr', package=self.package)
        self.assertEqual((self.record()['upscaler']['name'], self.record()['risk_accepted']), ('helixsr', entry))
        self.assertIn(f'Installed despite anti-cheat (Easy Anti-Cheat), risk accepted on {entry[0]["accepted_at"][:10]}.',
                      self.output(m.status, self.exe).splitlines())
        self.output(m.restore, self.exe)
        self.assertNotIn('risk_accepted', self.record())
        self.assertOriginal()


from test_proxy_install import ProxyFixture


class WikiPrefillInstallTests(ProxyFixture):
    def setUp(self):
        super().setUp()
        self.ini_path = self.game / 'OptiScaler.ini'
        text = self.ini_path.read_bytes() + b'\n; Wiki test preference\n[Hotfix]\nColorResourceBarrier=auto\n'
        self.ini_path.write_bytes(text)
        self.original['OptiScaler.ini'] = text
        self.catalog = dict(schema=1, verified=[], leave_auto={}, backports={}, quirk_keys={}, wiki=[dict(
            title='Test game', match={'gog':['123']}, pages=['https://example.invalid/wiki/Test'],
            ini=[dict(key='Hotfix.ColorResourceBarrier', value='4')])])
        self.write_catalog()
        m.install(self.package, self.exe, route='opti')

    def write_catalog(self):
        from test_game_install import set_package_file
        set_package_file(self.package, 'recipes/recipes.json', json.dumps(self.catalog).encode())

    def selected(self):
        plan = m.wiki_settings_plan(self.package, self.exe)
        return plan, next(row for row in plan['rows'] if row['key']=='Hotfix.ColorResourceBarrier')

    def test_prefill_writes_ini_and_rollback_is_exact(self):
        before = self.ini_path.read_bytes()
        plan, row = self.selected()
        self.assertEqual(row['action'], 'prefill')
        self.assertEqual(self.ini_path.read_bytes(), before)
        prepared, launcher = list(self.prepared), self.config.read_bytes()
        self.assertEqual(m.apply_wiki_settings(self.exe, [row['id']], package=self.package, expected=plan['digest']), 'update')
        self.assertEqual(m.read_ini(self.ini_path.read_bytes())[('hotfix','colorresourcebarrier')], '4')
        self.assertEqual(self.prepared, prepared)
        self.assertEqual(self.config.read_bytes(), launcher)
        self.assertTrue(self.record()['wiki_settings']['selected'])
        m.rollback(self.exe)
        self.assertEqual(self.ini_path.read_bytes(), before)
        self.assertNotIn('wiki_settings', self.record())
        m.restore(self.exe)
        self.assertOriginal()

    def test_unknown_condition_requires_confirmation_and_false_cannot_be_overridden(self):
        self.catalog['wiki'][0]['ini'][0]['when'] = {'condition':'white screen occurs'}
        self.write_catalog()
        plan, row = self.selected()
        self.assertEqual(row['action'], 'conditional')
        with self.assertRaisesRegex(ValueError, 'confirm'):
            m.apply_wiki_settings(self.exe, [row['id']], package=self.package, expected=plan['digest'])
        m.apply_wiki_settings(self.exe, [row['id']], [row['id']], package=self.package, expected=plan['digest'])
        m.rollback(self.exe)
        self.catalog['wiki'][0]['ini'][0]['when'] = {'gpu':'NVIDIA'}
        self.write_catalog()
        plan, row = self.selected()
        with self.assertRaisesRegex(ValueError, 'NVIDIA'):
            m.apply_wiki_settings(self.exe, [row['id']], [row['id']], package=self.package, expected=plan['digest'])

    def test_stale_preview_and_unsupported_key_keep_current_bytes(self):
        plan, row = self.selected()
        self.ini_path.write_bytes(m.patch_ini(self.ini_path.read_bytes(), {('Hotfix','ColorResourceBarrier'):'8'}))
        before = self.ini_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'preview changed'):
            m.apply_wiki_settings(self.exe, [row['id']], package=self.package, expected=plan['digest'])
        self.assertEqual(self.ini_path.read_bytes(), before)
        self.catalog['wiki'][0]['ini'].append(dict(key='Unknown.Key', value='1'))
        self.write_catalog()
        plan = m.wiki_settings_plan(self.package, self.exe)
        unknown = next(row for row in plan['rows'] if row['key']=='Unknown.Key')
        with self.assertRaisesRegex(ValueError, 'does not define'):
            m.apply_wiki_settings(self.exe, [unknown['id']], package=self.package, expected=plan['digest'])
        self.assertEqual(self.ini_path.read_bytes(), before)

    def test_later_player_edit_survives_rollback(self):
        plan, row = self.selected()
        m.apply_wiki_settings(self.exe, [row['id']], package=self.package, expected=plan['digest'])
        self.ini_path.write_bytes(m.patch_ini(self.ini_path.read_bytes(), {('Hotfix','ColorResourceBarrier'):'8'}))
        m.rollback(self.exe)
        self.assertEqual(m.read_ini(self.ini_path.read_bytes())[('hotfix','colorresourcebarrier')], '8')
