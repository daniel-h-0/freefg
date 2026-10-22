# SPDX-License-Identifier: MIT
"""Exercise actual shell launch semantics and reversible launcher field edits."""
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
import launcher_config as l
from steam_config import Document


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.game = self.home/"Game's Folder"
        self.game.mkdir()
        self.exe = self.game/'Game.exe'
        self.exe.write_bytes(b'fixture')
        self.stopped = patch.object(l, 'require_stopped')
        self.stopped.start()
        self.addCleanup(self.stopped.stop)

    def write(self, path, data, mode=0o600):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)

    def heroic(self):
        base = self.home/'.config/heroic'
        index = base/'gog_store/installed.json'
        self.write(index, json.dumps({'installed':[{'appName':'123', 'install_path':str(self.game)}]}).encode())
        config = base/'GamesConfig/123.json'
        self.write(config, json.dumps({'123':{'enableHDR':True,
            'enviromentOptions':[{'key':'WINEDLLOVERRIDES','value':'dxgi=b;other=n,b'},
                                  {'key':'VKD3D_CONFIG','value':'dxr'}],
            'wrapperOptions':[{'exe':str(self.game/'BC250-XeFG/run.sh'),'args':''},
                              {'exe':'/usr/bin/gamemoderun','args':''}]}}).encode())
        return config

    def test_steam_assignment_quoting_and_arguments_execute(self):
        original = 'WINEDLLOVERRIDES="dxgi=b;other=n,b" VKD3D_CONFIG=dxr %command% --game-argument'
        result = l.steam_options(original, self.game, 'winmm.dll')
        code = 'import os,json,sys;print(json.dumps([dict(os.environ),sys.argv[1:]]))'
        command = result.replace('%command%', shlex.join([sys.executable,'-c',code]))
        env,args = json.loads(subprocess.check_output(['/bin/sh','-c',command], text=True))
        self.assertEqual(args, ['--game-argument'])
        self.assertEqual(env['WINEDLLOVERRIDES'],'dxgi=b;other=n,b;version=n,b;winmm=n,b')
        self.assertEqual(env['VKD3D_CONFIG'],'dxr,no_staggered_submit')
        self.assertEqual(env['VK_LAYER_PATH'],str(self.game/'BC250-XeFG/layer'))
        self.assertNotIn('run.sh',result)

    def test_removes_only_exact_old_wrapper(self):
        value = 'gamemoderun '+shlex.quote(str(self.game/'BC250-XeFG/run.sh'))+' %command% --intro-skip'
        result = l.steam_options(value,self.game,'dxgi.dll')
        self.assertIn('gamemoderun %command% --intro-skip',result)
        self.assertNotIn('run.sh',result)
        self.assertTrue(l.steam_options('--intro-skip',self.game,'dxgi.dll').endswith('%command% --intro-skip'))
        self.assertEqual(l.steam_options('env TEST=yes %command%',self.game,'dxgi.dll'),
                         l.steam_options('TEST=yes %command%',self.game,'dxgi.dll'))

    def test_accepts_absolute_env_and_older_optiscaler_wrapper(self):
        # Options written by host tooling ('/usr/bin/env' with a quoted 'KEY=a;b' token) and the wrapper of the older
        # OptiScaler-route layout (OptiScaler/BC250-XeFG/run.sh) become ordinary launcher fields.
        wrapper = shlex.quote(str(self.game/'OptiScaler/BC250-XeFG/run.sh'))
        value = "/usr/bin/env A=1 'WINEDLLOVERRIDES=winmm=n,b;amdxcffx64=' "+wrapper+' %command% -dx12'
        result = l.steam_options(value,self.game,'winmm.dll')
        self.assertNotIn('run.sh',result);self.assertNotIn('/usr/bin/env',result)
        self.assertTrue(result.endswith('%command% -dx12'))
        self.assertIn("WINEDLLOVERRIDES='amdxcffx64=;version=n,b;winmm=n,b'",result)
        # Still a runnable shell command.
        run = subprocess.run(['sh','-c',result.replace('%command%','true')],env={'PATH':'/usr/bin:/bin'},capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_environment_preserves_other_layers_and_overrides(self):
        values = l.environment(self.game,'dxgi.dll',dict(WINEDLLOVERRIDES='dxgi,other=b;version=b',
            VK_INSTANCE_LAYERS='another:VK_LAYER_BC250_xefg_wave',VK_LAYER_PATH='/other',
            XEFG_GAME_PROFILE='stale',XEFG_FLOW_CAP='1',BC250_XEFG_NO_STAGGERED_SUBMIT='0'))
        self.assertEqual(values['WINEDLLOVERRIDES'],'other=b;dxgi=n,b;version=n,b')
        self.assertEqual(values['VK_INSTANCE_LAYERS'],'VK_LAYER_BC250_xefg_wave:another')
        self.assertEqual(values['VK_LAYER_PATH'],str(self.game/'BC250-XeFG/layer')+':/other')
        self.assertNotIn('VKD3D_CONFIG',values)
        self.assertNotIn('XEFG_GAME_PROFILE',values)
        self.assertNotIn('XEFG_FLOW_CAP',values)
        self.assertEqual(values,l.environment(self.game,'dxgi.dll',values))

    def test_xefg_environment_has_no_loader_and_uses_the_route_layout(self):
        # Intel's 2x frame generation with the BC250 proxy: no version.dll loader, files under OptiScaler/ on that route.
        current = dict(WINEDLLOVERRIDES='version=n,b;other=b', XEFG_FLOW_CAP='1', XEFG_GAME_PROFILE='stale')
        opti = l.environment(self.game, 'dxgi.dll', current, runtime='xefg', route='opti')
        self.assertEqual(opti['WINEDLLOVERRIDES'], 'version=n,b;other=b;dxgi=n,b')
        self.assertEqual(opti['VK_LAYER_PATH'], str(self.game/'OptiScaler/BC250-XeFG/layer'))
        self.assertEqual(opti['XEFG_WAVE_CONFIG'], str(self.game/'OptiScaler/BC250-XeFG/shaders/waves.txt'))
        self.assertEqual(opti['BC250_XEFG_OWNER_MODULE'], 'dxgi.dll')
        self.assertEqual(opti['XEFG_FLOW_CAP'], '1')
        self.assertNotIn('XEFG_GAME_PROFILE', opti)
        self.assertEqual(opti, l.environment(self.game, 'dxgi.dll', opti, runtime='xefg', route='opti'))
        native = l.environment(self.game, 'dxgi.dll', dict(BC250_XEFG_OWNER_MODULE='dxgi.dll'), runtime='xefg', route='native')
        self.assertEqual(native['WINEDLLOVERRIDES'], 'dxgi=n,b')
        self.assertEqual(native['VK_LAYER_PATH'], str(self.game/'BC250-XeFG/layer'))
        self.assertEqual(native['XEFG_WAVE_CONFIG'], str(self.game/'BC250-XeFG/shaders/waves.txt'))
        self.assertNotIn('BC250_XEFG_OWNER_MODULE', native)

    def test_vkd3d_cache_settings_merge_with_the_users(self):
        # 1.1.1 (W32-2): given the installation's cache folder, vkd3d-proton caches SPIR-V there (shader module
        # identifiers off), so the layer names every pipeline; the user's own list entries and cache path stay.
        cache = self.game/'.bc250-xefg-experimental/vkd3d-cache'
        ident = l.IDENTIFIER_EXTENSION
        self.assertEqual(ident, 'VK_EXT_shader_module_identifier')
        plain = l.environment(self.game, 'dxgi.dll', {})  # other callers (no folder): neither variable
        self.assertNotIn('VKD3D_DISABLE_EXTENSIONS', plain);self.assertNotIn('VKD3D_SHADER_CACHE_PATH', plain)
        nvx = 'VK_NVX_binary_import,VK_NVX_image_view_handle'
        values = l.environment(self.game, 'dxgi.dll', dict(VKD3D_DISABLE_EXTENSIONS=nvx), vkd3d_cache=cache)
        self.assertEqual(values['VKD3D_DISABLE_EXTENSIONS'], nvx+','+ident)
        self.assertEqual(values['VKD3D_SHADER_CACHE_PATH'], str(cache))
        self.assertEqual(values['VKD3D_CONFIG'], 'no_staggered_submit')
        self.assertEqual(values, l.environment(self.game, 'dxgi.dll', values, vkd3d_cache=cache))  # applied twice: unchanged
        # vkd3d-proton's list members are separated by ',' or ';' (vkd3d_debug_list_has_member).
        for before, after in (('', ident), ('A;', 'A;'+ident), (ident+';B', ident+';B'), ('A,'+ident, 'A,'+ident),
                              (ident+'_X', ident+'_X,'+ident)):
            with self.subTest(before=before):
                self.assertEqual(l.environment(self.game, 'dxgi.dll', dict(VKD3D_DISABLE_EXTENSIONS=before),
                                               vkd3d_cache=cache)['VKD3D_DISABLE_EXTENSIONS'], after)
        # A cache path the user set is kept (0 = no disk cache); an empty one is vkd3d-proton's default and is replaced.
        for own, kept in (('0', '0'), ('/my/cache', '/my/cache'), ('', str(cache))):
            with self.subTest(own=own):
                self.assertEqual(l.environment(self.game, 'dxgi.dll', dict(VKD3D_SHADER_CACHE_PATH=own),
                                               vkd3d_cache=cache)['VKD3D_SHADER_CACHE_PATH'], kept)

    def test_vkd3d_cache_file_names_must_fit_vkd3d_protons_buffers(self):
        # Z:\<folder>\vkd3d-proton.<program>.cache.write within 259 characters, 16 to spare.
        folder = '/g/' + 'x' * 100
        name = 'Z:\\g\\' + 'x' * 100 + '\\vkd3d-proton.Game.exe.cache.write'
        self.assertTrue(l.vkd3d_cache_fits(folder, 'Game.exe'))
        spare = l.VKD3D_PATH_LIMIT - 16 - len(name)
        self.assertTrue(l.vkd3d_cache_fits(folder + 'y' * spare, 'Game.exe'))
        self.assertFalse(l.vkd3d_cache_fits(folder + 'y' * (spare + 1), 'Game.exe'))
        self.assertTrue(l.vkd3d_cache_fits(folder + 'y' * (spare + 1), 'Game.exe', margin=0))

    def test_vkd3d_cache_settings_execute_and_restore_in_each_launcher(self):
        cache = self.game/'.bc250-xefg-experimental/vkd3d-cache'  # the fixture's folder name has a space and a quote
        original = 'VKD3D_DISABLE_EXTENSIONS=VK_NVX_binary_import %command% -skip'
        result = l.steam_options(original, self.game, 'dxgi.dll', vkd3d_cache=cache)
        code = 'import os,json;print(json.dumps(dict(os.environ)))'
        env = json.loads(subprocess.check_output(['/bin/sh', '-c', result.replace('%command%', shlex.join([sys.executable, '-c', code]))],
                                                 text=True))
        self.assertEqual(env['VKD3D_SHADER_CACHE_PATH'], str(cache))
        self.assertEqual(env['VKD3D_DISABLE_EXTENSIONS'], 'VK_NVX_binary_import,'+l.IDENTIFIER_EXTENSION)
        # Restore after a later change by the user: the installation's values go, the user's entry and change stay.
        row = dict(launcher='steam', before={'LaunchOptions': original}, after={'LaunchOptions': result})
        later = l.reverse(row, {'LaunchOptions': 'USER=1 '+result})['LaunchOptions']
        self.assertEqual(l.split_steam(later)[0], dict(USER='1', VKD3D_DISABLE_EXTENSIONS='VK_NVX_binary_import'))
        # Each launcher's file: installed with both variables, restored byte for byte.
        exe, steam = self.steam_library('"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "100" { "LaunchOptions" '
                                        '"VKD3D_DISABLE_EXTENSIONS=A %command%" } } } } } }\n')
        heroic = self.heroic_js({'enviromentOptions': [{'key': 'VKD3D_SHADER_CACHE_PATH', 'value': '/my/cache'}], 'wrapperOptions': []})
        for exe, config in ((exe, steam), (self.exe, heroic)):
            with self.subTest(config=config.name):
                original = config.read_bytes()
                operations = l.plan(exe, 'dxgi.dll', self.home, vkd3d_cache=cache)
                l.apply(operations, self.write)
                env = l.planned_environment(operations[0])
                self.assertEqual(env, l.entry_environment(operations[0], config.read_bytes()))
                self.assertEqual(env['VKD3D_DISABLE_EXTENSIONS'], ('A,' if config == steam else '')+l.IDENTIFIER_EXTENSION)
                self.assertEqual(env['VKD3D_SHADER_CACHE_PATH'], str(cache) if config == steam else '/my/cache')
                l.apply(operations, self.write, restore=True)
                self.assertEqual(config.read_bytes(), original)
        # Lutris (YAML, rewritten whole; the installer writes its copy as found back when the settings are the same).
        from vendor import yaml
        heroic.unlink()
        lutris = self.home/'.config/lutris/games/test.yml'
        doc = dict(game={'exe': str(self.exe)}, system={'env': {'VKD3D_DISABLE_EXTENSIONS': 'A;B'}})
        self.write(lutris, yaml.safe_dump(doc).encode())
        operations = l.plan(self.exe, 'dxgi.dll', self.home, vkd3d_cache=cache)
        l.apply(operations, self.write)
        env = yaml.safe_load(lutris.read_text())['system']['env']
        self.assertEqual((env['VKD3D_DISABLE_EXTENSIONS'], env['VKD3D_SHADER_CACHE_PATH']), ('A;B,'+l.IDENTIFIER_EXTENSION, str(cache)))
        self.assertEqual(env, l.planned_environment(operations[0]))
        l.apply(operations, self.write, restore=True)
        self.assertEqual(yaml.safe_load(lutris.read_text()), doc)

    def test_complex_shell_rejected_without_execution(self):
        for text in ('$(touch bad) %command%', 'echo hi; %command%', '%command% | cat',
                     '%command% %command%', 'ABC=1 ABC=2 %command%',
                     'gamemoderun env WINEDLLOVERRIDES=dxgi=b %command%'):
            with self.assertRaises(ValueError):l.steam_options(text,self.game,'dxgi.dll')
        self.assertFalse((Path.cwd()/'bad').exists())
        for env in ({'INVALID KEY':'value'},{'TEST':1},{'TEST':'nul\0byte'}):
            with self.assertRaises(ValueError):l.environment(self.game,'dxgi.dll',env)

    def test_heroic_roundtrip_preserves_graphics_and_other_wrapper(self):
        config = self.heroic()
        original = json.loads(config.read_text())
        operations = l.plan(self.exe,'dxgi.dll',self.home)
        l.apply(operations,self.write)
        installed = json.loads(config.read_text())
        self.assertTrue(installed['123']['enableHDR'])
        self.assertEqual(installed['123']['wrapperOptions'],[{'exe':'/usr/bin/gamemoderun','args':''}])
        self.assertIn({'key':'VKD3D_CONFIG','value':'dxr,no_staggered_submit'},installed['123']['enviromentOptions'])
        installed['123']['userLaterSetting'] = 42
        config.write_text(json.dumps(installed))
        l.apply(operations,self.write,restore=True)
        restored = json.loads(config.read_text())
        self.assertEqual(restored.pop('123')['userLaterSetting'],42)
        current = json.loads(config.read_text())['123'];current.pop('userLaterSetting')
        self.assertEqual(current,original['123'])

    def test_heroic_user_environment_conflict_is_preserved(self):
        config = self.heroic();operations = l.plan(self.exe,'dxgi.dll',self.home)
        l.apply(operations,self.write)
        doc = json.loads(config.read_text());doc['123']['enviromentOptions'].append({'key':'USER_NEW','value':'yes'})
        config.write_text(json.dumps(doc))
        # Restore takes out only what the installation added and keeps the user's later variable.
        messages=l.apply(operations,self.write,restore=True)
        self.assertEqual(len(messages),1)
        restored=json.loads(config.read_text())['123']
        self.assertEqual(restored['enviromentOptions'],[{'key':'WINEDLLOVERRIDES','value':'dxgi=b;other=n,b'},
                                                        {'key':'VKD3D_CONFIG','value':'dxr'},{'key':'USER_NEW','value':'yes'}])
        self.assertTrue(restored['enableHDR'])

    def test_second_installation_on_one_entry_is_refused(self):
        # One Heroic entry covers the whole install folder: an installation in bin/x64_dx12 and a second one in bin/x64
        # (The Witcher 3's two executables) would share it, and the two could not both be restored exactly.
        config = self.heroic();original = config.read_bytes()
        first = self.game/'bin/x64_dx12/witcher3.exe';second = self.game/'bin/x64/witcher3.exe'
        for exe in (first, second):self.write(exe, b'fixture')
        operations = l.plan(first,'dxgi.dll',self.home);l.apply(operations,self.write)
        self.assertEqual(l.conflicts(first, l.discover(first, self.home)), [])  # its own folder: no conflict
        found = l.conflicts(second, l.discover(second, self.home))
        self.assertEqual([c['code'] for c in found], ['shared-entry'])
        self.assertIn(str((self.game/'bin/x64_dx12').resolve()), found[0]['text'])
        with self.assertRaisesRegex(ValueError, r'\[shared-entry\]'):l.plan(second,'dxgi.dll',self.home)
        l.apply(operations,self.write,restore=True)
        self.assertEqual(json.loads(config.read_bytes()), json.loads(original))
        self.assertEqual(l.conflicts(second, l.discover(second, self.home)), [])  # restored: the entry is free again

    def test_ge_proton_upscaler_variables_are_refused(self):
        config = self.heroic();doc = json.loads(config.read_text())
        doc['123']['enviromentOptions'].append({'key':'PROTON_FSR4_UPGRADE','value':'1'})
        config.write_text(json.dumps(doc))
        found = l.conflicts(self.exe, l.discover(self.exe, self.home))
        self.assertEqual([c['code'] for c in found], ['ge-optiscaler'])
        self.assertIn('PROTON_FSR4_UPGRADE', found[0]['way'])
        with self.assertRaisesRegex(ValueError, r'\[ge-optiscaler\]'):l.plan(self.exe,'dxgi.dll',self.home)
        doc['123']['enviromentOptions'][-1]['value'] = '0'  # turned off: no conflict
        config.write_text(json.dumps(doc))
        self.assertEqual(l.conflicts(self.exe, l.discover(self.exe, self.home)), [])
        found = l.conflicts(self.exe, l.discover(self.exe, self.home), environ={'PROTON_USE_OPTISCALER': '1', 'PROTON_LOG': '1'})
        self.assertEqual([(c['code'], c['way']) for c in found], [('ge-optiscaler', 'Unset PROTON_USE_OPTISCALER for this game.')])
        # Steam: the assignments before %command%.
        self.assertEqual(l._ge_variables(l.split_steam('PROTON_DLSS_UPGRADE=1 PROTON_LOG=1 %command%')[0]), ['PROTON_DLSS_UPGRADE'])

    def test_extra_environment_is_installed_and_restored(self):
        config = self.heroic();original = config.read_bytes()
        operations = l.plan(self.exe,'dxgi.dll',self.home,extra_env={'PROTONFIXES_DISABLE':'1'});l.apply(operations,self.write)
        env = {e['key']:e['value'] for e in json.loads(config.read_text())['123']['enviromentOptions']}
        self.assertEqual(env['PROTONFIXES_DISABLE'],'1')
        l.apply(operations,self.write,restore=True)
        self.assertEqual(json.loads(config.read_bytes()), json.loads(original))
        self.assertIn('PROTONFIXES_DISABLE=1', l.steam_options('%command%', self.game, 'dxgi.dll', extra_env={'PROTONFIXES_DISABLE':'1'}).split())
        with self.assertRaises(ValueError):l.environment(self.game,'dxgi.dll',{},extra={'BAD NAME':'1'})

    def test_steam_library_config_roundtrip_is_lossless(self):
        steam = self.home/'.local/share/Steam';library=self.home/'Other Library'
        game = library/'steamapps/common/Actual Game';game.mkdir(parents=True)
        exe=game/'Binaries/Win64/Game.exe';self.write(exe,b'fixture')
        self.write(steam/'steamapps/libraryfolders.vdf', ('"libraryfolders" { "1" { "path" '+json.dumps(str(library))+' } }').encode())
        self.write(library/'steamapps/appmanifest_100.acf',b'"AppState" { "appid" "100" "installdir" "Actual Game" }')
        config=steam/'userdata/42/config/localconfig.vdf'
        original=b'// Keep this comment\n"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "100" { "LaunchOptions" "--intro-skip" "other" "keep" } } } } } }\n'
        self.write(config,original)
        operations=l.plan(exe,'dxgi.dll',self.home);self.assertEqual(len(operations),1)
        l.apply(operations,self.write)
        self.assertIn('%command% --intro-skip',Document(config.read_bytes()).get(l.APP+['100','LaunchOptions']))
        l.apply(operations,self.write,restore=True)
        self.assertEqual(config.read_bytes(),original)

    def test_steam_shortcut_binary_roundtrip(self):
        def text(key,value):return b'\x01'+key.encode()+b'\0'+value.encode()+b'\0'
        game=b'\x02appid\0'+struct.pack('<I',3456789012)+text('Exe',shlex.quote(str(self.exe)))+text('LaunchOptions','--intro-skip')+text('appname','Test title')
        original=b'\x00shortcuts\0\x000\0'+game+b'\x08\x08\x08'
        config=self.home/'.local/share/Steam/userdata/42/config/shortcuts.vdf';self.write(config,original)
        operations=l.plan(self.exe,'dxgi.dll',self.home);self.assertEqual(len(operations),1)
        l.apply(operations,self.write)
        self.assertIn('%command%',l.fields(operations[0],config.read_bytes())['LaunchOptions'])
        l.apply(operations,self.write,restore=True)
        self.assertEqual(config.read_bytes(),original)

    def test_steam_missing_value_insert_restore(self):
        target=dict(launcher='steam',id='12')
        original=b'"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "12" { "name" "Test" } } } } } }'
        self.assertIsNone(l.fields(target,original)['LaunchOptions'])
        changed=l.patch(target,original,{'LaunchOptions':'test %command%'})
        restored=l.patch(target,changed,{'LaunchOptions':None})
        self.assertIsNone(l.fields(target,restored)['LaunchOptions'])
        self.assertEqual(Document(restored).get(l.APP+['12','name']),'Test')

    def steam_library(self, config_text):
        """A Steam game (AppID 100) whose localconfig.vdf is config_text; returns (exe, config path)."""
        steam = self.home/'.local/share/Steam'
        game = steam/'steamapps/common/Actual Game'
        exe = game/'Game.exe'
        self.write(exe, b'fixture')
        self.write(steam/'steamapps/appmanifest_100.acf', b'"AppState" { "appid" "100" "installdir" "Actual Game" }')
        config = steam/'userdata/42/config/localconfig.vdf'
        self.write(config, config_text.encode())
        return exe, config

    def test_steam_c_escaped_config_round_trips_byte_for_byte(self):
        # Steam writes some localconfig.vdf files with one space between key and value and Valve's C-string escapes
        # (\' and \?); the installer writes the value the same way, so Restore gives back Steam's own bytes.
        original = ('"UserLocalConfigStore"\n{\n\t"Chat"\n\t{\n\t\t"3" "Want to play\\?"\n\t}\n\t"Software"\n\t{\n\t\t"Valve"\n'
                    '\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t"100"\n\t\t\t\t\t{\n'
                    '\t\t\t\t\t\t"LaunchOptions" "PROTON_LOG=1 WINEDLLOVERRIDES=\\\'amdxcffx64=\\\' %command% -skip"\n'
                    '\t\t\t\t\t\t"LastPlayed" "1760000000"\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
        exe, config = self.steam_library(original)
        doc = Document(config.read_bytes())
        self.assertEqual(doc.get(['UserLocalConfigStore', 'Chat', '3']), 'Want to play?')
        operations = l.plan(exe, 'dxgi.dll', self.home)
        self.assertEqual(operations[0]['before']['LaunchOptions'], "PROTON_LOG=1 WINEDLLOVERRIDES='amdxcffx64=' %command% -skip")
        l.apply(operations, self.write)
        installed = config.read_text()
        line = next(x for x in installed.splitlines() if '"LaunchOptions"' in x)
        self.assertNotRegex(line, r"[^\\]'")  # every quote escaped as Steam does
        self.assertIn("WINEDLLOVERRIDES=\\'amdxcffx64=;dxgi=n,b;version=n,b\\'", line)
        self.assertIn('"3" "Want to play\\?"', installed)  # other entries untouched
        self.assertEqual(l.fields(operations[0], config.read_bytes()), operations[0]['after'])
        l.apply(operations, self.write, restore=True)
        self.assertEqual(config.read_text(), original)

    def test_steam_plain_and_mixed_escaping_kept_per_value(self):
        # The signed-in account's tab-separated file has bare quotes. In a C-escaped file, a value an earlier
        # installer wrote with bare quotes keeps its own form too, and the file's other values are not touched.
        apps = '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n%s\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
        plain = apps % "\t\t\t\t\t\"100\"\n\t\t\t\t\t{\n\t\t\t\t\t\t\"LaunchOptions\"\t\t\"A='x;y' %command%\"\n\t\t\t\t\t}\n"
        mixed = apps % ("\t\t\t\t\t\"7\"\n\t\t\t\t\t{\n\t\t\t\t\t\t\"LaunchOptions\" \"B=\\'1;2\\' %command%\"\n\t\t\t\t\t}\n"
                        "\t\t\t\t\t\"100\"\n\t\t\t\t\t{\n\t\t\t\t\t\t\"LaunchOptions\" \"A='x;y' %command%\"\n\t\t\t\t\t}\n")
        for name, original in (('plain', plain), ('mixed', mixed)):
            with self.subTest(name):
                exe, config = self.steam_library(original)
                operations = l.plan(exe, 'dxgi.dll', self.home)
                l.apply(operations, self.write)
                line = next(x for x in config.read_text().splitlines() if 'A=' in x)
                self.assertNotIn("\\'", line)
                self.assertIn("WINEDLLOVERRIDES='dxgi=n,b;version=n,b'", line)
                if name == 'mixed':
                    self.assertIn("\"B=\\'1;2\\' %command%\"", config.read_text())
                l.apply(operations, self.write, restore=True)
                self.assertEqual(config.read_text(), original)
        # A value without quotes yet takes the escaping most of the file's values show.
        doc = Document(b'"a" { "b" "x=\\\'1\\\'" "c" "y=\\\'2\\\'" "d" "z=\'3\'" "e" "plain" }')
        self.assertIn(b'"e" "w=\\\'4\\\'"', doc.set(['a', 'e'], "w='4'"))
        self.assertIn(b'"d" "z=\'4\'"', doc.set(['a', 'd'], "z='4'"))
        self.assertIn(b'"e" "w=\'4\'"', Document(b'"a" { "e" "plain" }').set(['a', 'e'], "w='4'"))

    def test_steam_inserted_value_takes_the_files_spacing_and_escaping(self):
        original = ('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n'
                    '\t\t\t\t{\n\t\t\t\t\t"100"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LastPlayed" "1760000000"\n\t\t\t\t\t}\n'
                    '\t\t\t\t\t"200"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LaunchOptions" "Q=\\\'a b\\\' %command%"\n\t\t\t\t\t}\n'
                    '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
        exe, config = self.steam_library(original)
        operations = l.plan(exe, 'dxgi.dll', self.home)
        self.assertIsNone(operations[0]['before']['LaunchOptions'])
        l.apply(operations, self.write)
        line = next(x for x in config.read_text().splitlines() if '"LaunchOptions"' in x and 'WINEDLLOVERRIDES' in x)
        self.assertRegex(line, r'^\t+"LaunchOptions" "WINEDLLOVERRIDES=\\\'dxgi=n,b;version=n,b\\\' ')
        l.apply(operations, self.write, restore=True)
        self.assertEqual(config.read_text(), original)

    def heroic_js(self, settings):
        """A GamesConfig file as Heroic writes it (JSON.stringify(config, null, 2): no final line ending, UTF-8 as is)."""
        base = self.home/'.config/heroic'
        self.write(base/'gog_store/installed.json', json.dumps({'installed':[{'appName':'123', 'install_path':str(self.game)}]}).encode())
        config = base/'GamesConfig/123.json'
        self.write(config, json.dumps({'123': settings}, indent=2, ensure_ascii=False).encode())
        return config

    def test_heroic_layout_is_kept_and_restored_byte_for_byte(self):
        config = self.heroic_js({'enableHDR': True, 'title': 'Café – Édition', 'fsr': 1.5, 'wrapperOptions': [],
                                 'enviromentOptions': [{'key': 'VKD3D_CONFIG', 'value': 'dxr'}]})
        original = config.read_bytes()
        operations = l.plan(self.exe, 'dxgi.dll', self.home)
        l.apply(operations, self.write)
        installed = config.read_bytes()
        self.assertFalse(installed.endswith(b'\n'))
        self.assertIn('"title": "Café – Édition"'.encode(), installed)
        self.assertIn(b'\n    "enviromentOptions": [', installed)  # Heroic's two-space indent
        l.apply(operations, self.write, restore=True)
        self.assertEqual(config.read_bytes(), original)
        # Other layouts are kept as well: tabs, CRLF, a final line ending, \\u escapes.
        layouts = [json.dumps({'123': {'title': 'Café', 'list': []}}, indent='\t').encode().replace(b'\n', b'\r\n') + b'\r\n',
                   json.dumps({'123': {'title': 'Café'}}).encode() + b'\n',
                   json.dumps({'123': {'title': 'Café'}}, separators=(',', ':')).encode()]
        for data in layouts:
            with self.subTest(data=data[:30]):
                config.write_bytes(data)
                operations = l.plan(self.exe, 'dxgi.dll', self.home)
                l.apply(operations, self.write)
                self.assertEqual(json.loads(config.read_bytes())['123']['title'], 'Café')
                l.apply(operations, self.write, restore=True)
                self.assertEqual(config.read_bytes(), data)

    def test_heroic_file_as_found_written_back_when_its_settings_are_back(self):
        # A layout no JSON writer reproduces (hand-edited spacing): only the copy taken at installation gives the
        # original bytes back, and only while the restored file holds the same settings in the same order.
        config = self.heroic_js({})
        original = b'{ "123" : { "enableHDR" : true ,\n "enviromentOptions" : [ { "key" : "A", "value" : "1" } ] } }'
        config.write_bytes(original)
        operations = l.plan(self.exe, 'dxgi.dll', self.home)
        l.apply(operations, self.write)
        l.apply(operations, self.write, restore=True)
        rewritten = config.read_bytes()
        self.assertNotEqual(rewritten, original)
        self.assertEqual(json.loads(rewritten), json.loads(original))
        config.write_bytes(original)
        l.apply(operations, self.write)
        l.apply(operations, self.write, restore=True, originals={0: original})
        self.assertEqual(config.read_bytes(), original)
        # Restore after an earlier Restore rewrote it: the values are back already, the layout comes back too.
        config.write_bytes(rewritten)
        l.apply(operations, self.write, restore=True, originals={0: original})
        self.assertEqual(config.read_bytes(), original)
        # Heroic changed another setting since installation: that change stays, and so does the current layout.
        l.apply(operations, self.write)
        doc = json.loads(config.read_bytes())
        doc['123']['enableHDR'] = False
        changed = json.dumps(doc, indent=2).encode()
        config.write_bytes(changed)
        l.apply(operations, self.write, restore=True, originals={0: original})
        restored = config.read_bytes()
        self.assertFalse(json.loads(restored)['123']['enableHDR'])
        self.assertEqual(json.loads(restored)['123']['enviromentOptions'], [{'key': 'A', 'value': '1'}])
        self.assertFalse(restored.endswith(b'\n'))
        # Key order counts as content: a reordered file is not "the same settings".
        self.assertFalse(l.same_settings(operations[0], b'{"a": 1, "b": 2}', b'{"b": 2, "a": 1}'))
        self.assertFalse(l.same_settings(operations[0], b'{"a": true}', b'{"a": 1}'))
        self.assertTrue(l.same_settings(operations[0], b'{"a": [1, {"b": "c"}]}', b'{ "a":[1,{"b":"c"}] }\n'))

    def test_lutris_roundtrip(self):
        from vendor import yaml
        config=self.home/'.config/lutris/games/test.yml'
        original=dict(game={'exe':str(self.exe)},system={'env':{'VKD3D_CONFIG':'dxr'},'prefix_command':'gamemoderun'},wine={'version':'custom'})
        self.write(config,yaml.safe_dump(original).encode())
        operations=l.plan(self.exe,'dxgi.dll',self.home)
        l.apply(operations,self.write)
        installed=yaml.safe_load(config.read_text())
        self.assertEqual(installed['system']['prefix_command'],'gamemoderun')
        self.assertIn('no_staggered_submit',installed['system']['env']['VKD3D_CONFIG'])
        l.apply(operations,self.write,restore=True)
        self.assertEqual(yaml.safe_load(config.read_text()),original)


class LauncherInstallationTests(unittest.TestCase):
    """The installer's launcher half, on the shared fixture (a Heroic entry in a temporary home)."""
    def setUp(self):
        import test_game_install as fixtures
        self.fixtures = fixtures
        fixtures.GameFixture.setUp(self)

    def test_install_restore_has_no_wrapper_and_materializes_runtime_copy(self):
        m = self.fixtures.m
        m.install(self.package,self.exe,route='native')
        self.assertFalse((self.game/'BC250-XeFG/run.sh').exists())
        self.assertEqual((self.game/'XeSSMFG/libxess_fg.dll').read_bytes(),(self.game/'libxess_fg.dll').read_bytes())
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertIsNone(record['wrapper']);self.assertEqual(len(record['launchers']),1)
        m.restore(self.exe)
        self.assertEqual(json.loads(self.config.read_text()),self.original_config)
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data)

    def test_missing_launcher_is_preflight_failure(self):
        m=self.fixtures.m
        self.config.unlink()
        with self.assertRaisesRegex(ValueError,'No launcher entry'):m.install(self.package,self.exe,route='native')
        self.assertFalse((self.game/m.STATE).exists())
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data)

    def test_interrupted_launcher_apply_is_recoverable(self):
        m=self.fixtures.m
        original=l.apply
        def interrupted(operations,writer,restore=False):
            original(operations,writer,restore)
            raise OSError('simulated interruption after launcher write')
        with patch.object(l,'apply',side_effect=interrupted):
            with self.assertRaises(OSError):m.install(self.package,self.exe,route='native')
        self.assertEqual(json.loads((self.game/m.STATE/'state.json').read_text())['status'],'prepared')
        m.restore(self.exe)
        self.assertEqual(json.loads(self.config.read_text()),self.original_config)
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data)


if __name__ == '__main__':unittest.main()
