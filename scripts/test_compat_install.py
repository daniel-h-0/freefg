# SPDX-License-Identifier: MIT
"""The installer with the compatibility verdict (install.py + compat.py + gamescan.py) on a synthetic Unreal game in a
Steam library: refusals before any download or write, keys from promoted wiki items and detection's DX12 switch
applied and restored exactly, a soft refusal accepted, verified recipes installed exactly as without the verdict, a
community recipe's game setting applied and restored, Check writing nothing and naming every refusal Install would
make for the game folder's state, and Automatic taking the verdict's input, with accepts given per game."""
import contextlib, hashlib, io, json, re, sys, unittest
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
