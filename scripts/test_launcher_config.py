# SPDX-License-Identifier: MIT
"""Exercise actual shell launch semantics and reversible launcher field edits."""
import contextlib
import io
import json
import os
from pathlib import Path
import random
import re
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


def environment_1_2_0(root, owner, current, runtime='xemfg', route='opti', extra=None, vkd3d_cache=None):
    """launcher_config.environment() as 1.2.0 wrote it (fc70296), before the launch contract: the reference that
    contract() and apply_contract() reproduce for every input."""
    if not isinstance(current, dict) or any(not isinstance(key, str) or not l.KEY.fullmatch(key)
           or not isinstance(value, str) or '\0' in value for key, value in current.items()):
        raise ValueError('Launcher environment keys and values must be strings with valid names')
    result = dict(current)
    overrides = current.get('WINEDLLOVERRIDES', '')
    required = {owner.removesuffix('.dll').lower()} | ({'version'} if runtime == 'xemfg' else set())
    pieces = []
    for part in overrides.split(';'):
        if not part:
            continue
        if '=' not in part:
            raise ValueError('Unrecognized Wine override: '+part)
        names, value = part.split('=', 1)
        kept = [n for n in names.split(',') if n.lower().removesuffix('.dll') not in required]
        if kept:
            pieces.append(','.join(kept)+'='+value)
    pieces.extend(n+'=n,b' for n in sorted(required))
    result['WINEDLLOVERRIDES'] = ';'.join(pieces)
    base = root/'OptiScaler' if runtime == 'xefg' and route == 'opti' else root
    for key, first, separator in (('VK_LAYER_PATH', str(base/'BC250-XeFG/layer'), ':'),
                                  ('VK_INSTANCE_LAYERS', 'VK_LAYER_BC250_xefg_wave', ':')):
        result[key] = separator.join(dict.fromkeys([first, *filter(None, current.get(key, '').split(separator))]))
    result['XEFG_WAVE_CONFIG'] = str(root/'OptiScaler/plugins/BC250-XeFG/shaders/waves.txt' if runtime == 'xemfg'
                                     else base/'BC250-XeFG/shaders/waves.txt')
    if current.get('BC250_XEFG_NO_STAGGERED_SUBMIT') != '0':
        result['VKD3D_CONFIG'] = ','.join(dict.fromkeys([*filter(None, current.get('VKD3D_CONFIG', '').split(',')), 'no_staggered_submit']))
    if vkd3d_cache is not None:
        value, member = current.get('VKD3D_DISABLE_EXTENSIONS', ''), l.IDENTIFIER_EXTENSION
        result['VKD3D_DISABLE_EXTENSIONS'] = value if member in re.split(r'[,;]', value) else \
            value + (',' if value and value[-1] not in ',;' else '') + member
        if not current.get('VKD3D_SHADER_CACHE_PATH'):
            result['VKD3D_SHADER_CACHE_PATH'] = str(vkd3d_cache)
    for key, value in (extra or {}).items():
        if not l.KEY.fullmatch(key) or not isinstance(value, str) or '\0' in value:
            raise ValueError('Invalid launcher environment setting: '+str(key))
        result[key] = value
    if runtime in ('xemfg', 'xemfg-proxy'):
        for key in ('XEFG_GAME_PROFILE', 'BC250_XEFG_OWNER_MODULE', 'XEFG_FLOW_CAP'):
            result.pop(key, None)
    else:
        result.pop('XEFG_GAME_PROFILE', None)
        if route == 'opti':
            result['BC250_XEFG_OWNER_MODULE'] = owner
        else:
            result.pop('BC250_XEFG_OWNER_MODULE', None)
    return result


class ContractTests(unittest.TestCase):
    def outcome(self, function, *args):
        """(variables in order) or (error type, message): what a call gives, for comparing two implementations."""
        try:
            return ('ok', list(function(*args).items()))
        except ValueError as error:
            return ('error', type(error).__name__, str(error))

    def test_environment_is_the_contract_applied_and_equals_1_2_0_for_every_input(self):
        # Launcher variables as users and earlier tools leave them: lists with empty, repeated and foreign members,
        # Wine overrides naming the owner in any spelling or grouped with other DLLs, malformed entries, user values.
        values = {
            'WINEDLLOVERRIDES': ['', 'dxgi=b', 'dxgi,other=b;version=b', 'DXGI.dll=n,b', 'winmm=n,b;dxgi=n', 'other=n,b;;x=',
                                 'bad', ';', 'version,winmm=b;amdxcffx64='],
            'VK_LAYER_PATH': ['', '/other', '/other::/x', ':', '/game/BC250-XeFG/layer:/other'],
            'VK_INSTANCE_LAYERS': ['', 'another:VK_LAYER_BC250_xefg_wave', 'VK_LAYER_BC250_xefg_wave', 'a::a'],
            'VKD3D_CONFIG': ['', 'dxr', 'dxr,,dxr', 'no_staggered_submit,dxr', 'a;', ','],
            'VKD3D_DISABLE_EXTENSIONS': ['', 'A', 'A;', 'A,', l.IDENTIFIER_EXTENSION, l.IDENTIFIER_EXTENSION+'_X', 'A;'+l.IDENTIFIER_EXTENSION],
            'VKD3D_SHADER_CACHE_PATH': ['', '0', '/my/cache'],
            'BC250_XEFG_NO_STAGGERED_SUBMIT': ['0', '1', ''],
            'XEFG_WAVE_CONFIG': ['user-waves.txt'], 'XEFG_GAME_PROFILE': ['stale'], 'BC250_XEFG_OWNER_MODULE': ['dxgi.dll'],
            'XEFG_FLOW_CAP': ['1'], 'PROTONFIXES_DISABLE': ['0'], 'USER': ['x', 'nul\0', 'a b'],
        }
        extras = [None, {}, {'PROTONFIXES_DISABLE': '1'}, {'VKD3D_CONFIG': 'x', 'XEFG_FLOW_CAP': '1'}, {'BAD NAME': '1'},
                  {'X': 'nul\0'}, {'BC250_XEFG_OWNER_MODULE': 'winmm.dll'}]
        rng = random.Random(20261030)
        root, cache = Path('/games/A Game'), Path('/games/A Game/.bc250-xefg-experimental/vkd3d-cache')
        compared = 0
        for _ in range(4000):
            current = {key: rng.choice(options) for key, options in values.items() if rng.random() < 0.45}
            if rng.random() < 0.05:
                current['bad key'] = 'x'
            args = (root, rng.choice(['dxgi.dll', 'winmm.dll', 'DXGI.DLL', 'OptiScaler.asi', 'version.dll']), current,
                    rng.choice(['xemfg', 'xemfg-proxy']), rng.choice(['opti', 'native']),
                    rng.choice(extras), rng.choice([None, cache]))
            with self.subTest(args=args):
                self.assertEqual(self.outcome(l.environment, *args), self.outcome(environment_1_2_0, *args))
                if self.outcome(l.environment, *args)[0] == 'ok':
                    self.assertEqual(l.environment(*args), l.apply_contract(current, l.contract(*args[:2], *args[3:])))
                    compared += 1
        self.assertGreater(compared, 1000)

    def test_contract_is_data_in_a_closed_vocabulary(self):
        ops = l.contract(Path('{game}'), 'dxgi.dll', 'xemfg-proxy', 'opti', {'PROTONFIXES_DISABLE': '1'}, Path('{cache}'))
        self.assertEqual(json.loads(json.dumps(ops)), ops)  # plain JSON
        self.assertLessEqual({op['op'] for op in ops}, set(l.CONTRACT_OPS))
        self.assertEqual([(op['var'], op['op']) for op in ops], [
            ('WINEDLLOVERRIDES', 'dll-override'), ('VK_LAYER_PATH', 'prepend'), ('VK_INSTANCE_LAYERS', 'prepend'),
            ('XEFG_WAVE_CONFIG', 'replace'), ('VKD3D_CONFIG', 'append-member'), ('VKD3D_DISABLE_EXTENSIONS', 'append-member'),
            ('VKD3D_SHADER_CACHE_PATH', 'replace'), ('PROTONFIXES_DISABLE', 'replace'),
            ('XEFG_GAME_PROFILE', 'remove'), ('BC250_XEFG_OWNER_MODULE', 'remove'), ('XEFG_FLOW_CAP', 'remove')])
        self.assertEqual(ops[0]['value'], 'dxgi=n,b')
        self.assertEqual((ops[1]['value'], ops[6]['value'], ops[6]['when']), ('{game}/BC250-XeFG/layer', '{cache}', 'unset'))
        self.assertEqual(ops[4]['unless'], {'BC250_XEFG_NO_STAGGERED_SUBMIT': '0'})
        # Without a cache folder (a path too long for vkd3d-proton) neither vkd3d-proton cache setting is part of it.
        self.assertNotIn('VKD3D_SHADER_CACHE_PATH', [op['var'] for op in l.contract(Path('/g'), 'dxgi.dll', 'xemfg-proxy')])
        with self.assertRaisesRegex(ValueError, 'Unknown launch contract operation'):
            l.apply_contract({}, [dict(var='A', op='append')])
        # Only the runtimes this installer installs: the 2x builds before 0.9.0 (runtime xefg) used a wrapper script.
        for runtime in ('xefg', 'other'):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, 'Unknown add-on runtime'):
                l.environment(Path('/g'), 'dxgi.dll', {}, runtime)


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

    def test_manual_settings_are_a_new_entrys_and_read_back_as_a_command(self):
        cache = self.game/'.bc250-xefg-experimental/vkd3d-cache'
        settings = l.manual_settings(self.game, 'dxgi.dll', 'xemfg-proxy', 'opti', ['-dx12'], {'PROTONFIXES_DISABLE': '1'}, cache)
        steam = l.steam_options('', self.game, 'dxgi.dll', 'xemfg-proxy', 'opti', ['-dx12'], {'PROTONFIXES_DISABLE': '1'}, cache)
        self.assertEqual({key: settings[key] for key in ('env', 'args')}, {'env': l.split_steam(steam)[0], 'args': ['-dx12']})
        lines = l.manual_lines(settings)
        self.assertEqual(lines[-1], 'Game arguments (after the .exe): -dx12')
        # On a command line, before the command (the game folder's name has a space and a quote).
        code = 'import os,json;print(json.dumps(dict(os.environ)))'
        env = json.loads(subprocess.check_output(['/bin/sh', '-c', ' '.join(lines[:-1]+[shlex.join([sys.executable, '-c', code])])], text=True))
        self.assertEqual({key: env[key] for key in settings['env']}, settings['env'])
        # As rows of a launcher that splits its launch arguments as a shell does (Faugus joins them with newlines).
        self.assertEqual(dict(word.split('=', 1) for word in shlex.split('\n'.join(lines[:-1]))), settings['env'])
        # The forms a front end offers to copy: Steam's launch-options line reads back as the same settings, and the
        # environment table is the same pairs, unquoted.
        line = l.manual_steam_line(dict(settings, required_args=['-nobattleye', '-dx12']))
        env, rest, _ = l.split_steam(line)
        self.assertEqual((env, shlex.split(rest)), (settings['env'], ['%command%', '-dx12', '-nobattleye']))
        self.assertEqual(dict(l.manual_env_table(settings)), settings['env'])
        self.assertEqual(l.manual_removals(settings), ['XEFG_GAME_PROFILE', 'BC250_XEFG_OWNER_MODULE', 'XEFG_FLOW_CAP'])

    def test_required_arguments_are_added_beside_the_users_api_switch(self):
        # A graphics-API switch only where the user chose none; an argument the game always needs (GTA V Enhanced's
        # -nobattleye) always, once. 1.2.0's recipes and records kept it among the launch arguments: it counts as required.
        self.assertEqual(l.with_args(['-dx12'], ['-nobattleye']), ['-dx12', '-nobattleye'])
        self.assertEqual(l.with_args(['-dx11'], ['-dx12'], ['-nobattleye']), ['-dx11', '-nobattleye'])
        self.assertEqual(l.with_args(['%command%'], ['-dx12'], ['-nobattleye']), ['%command%', '-dx12', '-nobattleye'])
        self.assertEqual(l.with_args(['-NoBattlEye', '-nobattleye'], [], ['-nobattleye']), ['-NoBattlEye', '-nobattleye'])
        self.assertEqual(l.split_args(['--rendering-driver', 'd3d12', '-nobattleye', '-D3D12']),
                         (['--rendering-driver', 'd3d12', '-D3D12'], ['-nobattleye']))
        self.assertTrue(l.chooses_api(['--rendering-driver', 'vulkan']))
        self.assertEqual(l.with_args(['--rendering-driver', 'vulkan'], ['-dx12']), ['--rendering-driver', 'vulkan'])
        result = l.steam_options('-dx12', self.game, 'dxgi.dll', args=['-nobattleye'])
        self.assertTrue(result.endswith('%command% -dx12 -nobattleye'), result)
        self.assertEqual(l.steam_options(result, self.game, 'dxgi.dll', required=['-nobattleye']), result)  # once
        code = 'import sys,json;print(json.dumps(sys.argv[1:]))'
        command = result.replace('%command%', shlex.join([sys.executable, '-c', code]))
        self.assertEqual(json.loads(subprocess.check_output(['/bin/sh', '-c', command], text=True)), ['-dx12', '-nobattleye'])

    def test_heroic_arguments_keep_the_users_text(self):
        # Heroic's launcherArgs as the user wrote them (a ~ stays unquoted); the installation's words are appended and
        # taken out again by Restore.
        config = self.heroic()
        doc = json.loads(config.read_text());doc['123']['launcherArgs'] = '~/.saves -dx11';config.write_text(json.dumps(doc))
        operations = l.plan(self.exe, 'dxgi.dll', self.home, args=['-dx12'], required=['-nobattleye'])
        self.assertEqual(operations[0]['after']['launcherArgs'], '~/.saves -dx11 -nobattleye')
        self.assertEqual(l.added_args(operations), ['-nobattleye'])
        l.apply(operations, self.write)
        doc = json.loads(config.read_text());doc['123']['launcherArgs'] += ' --later';config.write_text(json.dumps(doc))
        l.apply(operations, self.write, restore=True)
        self.assertEqual(json.loads(config.read_text())['123']['launcherArgs'], '~/.saves -dx11 --later')
        self.assertEqual(l.added_to(None, [], []), None)
        self.assertEqual(l.added_to('', ['-dx12']), '-dx12')
        self.assertEqual(l.added_to("'a b' ", [], ['-x y']), "'a b' '-x y'")

    def test_lutris_entry_without_a_required_argument_is_refused(self):
        # Lutris's game arguments are not edited here: an entry that lacks a required argument is a refusal with the
        # way to fix it, never a note after the files were installed; with the argument in place it installs.
        from vendor import yaml
        config = self.home/'.config/lutris/games/test.yml'
        doc = dict(game={'exe': str(self.exe), 'args': '-dx12'}, system={'env': {}})
        self.write(config, yaml.safe_dump(doc).encode())
        found = l.conflicts(self.exe, l.discover(self.exe, self.home), required=['-nobattleye'])
        self.assertEqual([(c['code'], c['kind']) for c in found], [('required-args', 'hard')])
        self.assertIn('add -nobattleye', found[0]['way'])
        with self.assertRaisesRegex(ValueError, r'-nobattleye.*\[required-args\]'):
            l.plan(self.exe, 'dxgi.dll', self.home, args=['-nobattleye'])
        self.assertEqual(l.conflicts(self.exe, l.discover(self.exe, self.home), required=[]), [])
        doc['game']['args'] = "-dx12 -nobattleye 'a b'"
        self.write(config, yaml.safe_dump(doc).encode())
        self.assertEqual(l.conflicts(self.exe, l.discover(self.exe, self.home), required=['-nobattleye']), [])
        operations = l.plan(self.exe, 'dxgi.dll', self.home, required=['-nobattleye'])
        self.assertEqual(l.added_args(operations), [])  # Lutris's arguments are the user's
        self.assertEqual(l.lutris_arguments(config.read_bytes()), ['-dx12', '-nobattleye', 'a b'])
        self.assertEqual(l.lutris_arguments(b'game: {args: "unbalanced \'"}'), [])

    def test_manual_settings_name_every_form_and_every_change(self):
        cache = self.game/'.bc250-xefg-experimental/vkd3d-cache'  # the fixture's folder name has a space and a quote
        settings = l.manual_settings(self.game, 'dxgi.dll', 'xemfg-proxy', 'opti', ['-dx12'], None, cache, ['-nobattleye'])
        guide = l.manual_guide(settings)
        self.assertEqual(guide[0], 'As one launch-options line (Steam’s form): ' + l.manual_steam_line(settings))
        self.assertIn('  VK_LAYER_PATH: ' + str(self.game/'BC250-XeFG/layer'), guide)  # a table takes the value without quotes
        self.assertIn('Leave out -dx12 where the game’s arguments already choose a graphics API.', guide)
        self.assertEqual(l.manual_args(settings), ['-dx12', '-nobattleye'])
        # A launcher that already sets some of them: the guidance's result is the contract's.
        own = dict(WINEDLLOVERRIDES='winmm=b;DXGI=n', VK_LAYER_PATH='/mine', VKD3D_CONFIG='dxr', VKD3D_SHADER_CACHE_PATH='0', XEFG_FLOW_CAP='1')
        combined = l.apply_contract(own, settings['merge'] + [dict(var=key, op='remove') for key in settings['remove']])
        self.assertEqual(combined, l.environment(self.game, 'dxgi.dll', own, 'xemfg-proxy', 'opti', None, cache))
        self.assertEqual((combined['WINEDLLOVERRIDES'], combined['VKD3D_SHADER_CACHE_PATH']), ('winmm=b;dxgi=n,b', '0'))
        # What changes, named exactly; a record's other form (PR #8: env and args only) and notes change nothing.
        other = l.manual_settings(self.game, 'winmm.dll', 'xemfg-proxy', 'opti', [], None, None, ['-nobattleye'], [l.CACHE_PATH_NOTE])
        self.assertEqual(l.manual_change_lines(settings, other), [
            'Replace WINEDLLOVERRIDES=dxgi=n,b with WINEDLLOVERRIDES=winmm=n,b',
            'Delete VKD3D_DISABLE_EXTENSIONS=VK_EXT_shader_module_identifier',
            'Delete VKD3D_SHADER_CACHE_PATH=' + shlex.quote(str(cache)), 'Game arguments: -dx12 -nobattleye → -nobattleye'])
        self.assertEqual(l.manual_change_lines({'env': settings['env'], 'args': ['-dx12', '-nobattleye']}, dict(settings, notes=['x'])), [])
        self.assertEqual(l.manual_guide(other)[-1], l.CACHE_PATH_NOTE)
        self.assertEqual(l.manual_delete_lines(settings)[:2], ['WINEDLLOVERRIDES: dxgi=n,b', 'VK_LAYER_PATH: ' + str(self.game/'BC250-XeFG/layer')])

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

    def test_restore_reports_a_removed_steam_shortcut_and_restores_the_other_entries(self):
        def text(key,value):return b'\x01'+key.encode()+b'\0'+value.encode()+b'\0'
        game=b'\x02appid\0'+struct.pack('<I',3456789012)+text('Exe',shlex.quote(str(self.exe)))+text('appname','Test title')
        config=self.home/'.local/share/Steam/userdata/42/config/shortcuts.vdf';self.write(config,b'\x00shortcuts\0\x000\0'+game+b'\x08\x08\x08')
        heroic=self.heroic();original=json.loads(heroic.read_text())
        operations=l.plan(self.exe,'dxgi.dll',self.home);self.assertEqual([row['launcher'] for row in operations],['steam','heroic'])
        l.apply(operations,self.write)
        # The user removes the shortcut from Steam: shortcuts.vdf stays, without it.
        self.write(config,b'\x00shortcuts\0\x08\x08')
        self.assertEqual(l.apply(operations,self.write,restore=True),
                         ['Launcher entry no longer present, nothing to undo: '+str(config)+' (Steam shortcut 3456789012 no longer exists)'])
        self.assertEqual(json.loads(heroic.read_text()),original);self.assertEqual(config.read_bytes(),b'\x00shortcuts\0\x08\x08')
        # Installing is still refused: the entry it would write is gone.
        with self.assertRaisesRegex(ValueError,'Steam shortcut 3456789012 no longer exists'):l.apply(operations,self.write)

    def test_restore_reports_a_removed_heroic_game(self):
        config=self.heroic()
        operations=l.plan(self.exe,'dxgi.dll',self.home);l.apply(operations,self.write)
        self.write(config,json.dumps({'456':{'enableHDR':False}}).encode())
        self.assertEqual(l.apply(operations,self.write,restore=True),
                         ['Launcher entry no longer present, nothing to undo: '+str(config)+' (Heroic game 123 no longer exists)'])
        self.assertEqual(json.loads(config.read_text()),{'456':{'enableHDR':False}})

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

    def recipe(self, **fields):
        """A verified recipe for the fixture game (its Heroic GOG ID 123; without a launcher ID, Game.exe in its folder
        'game') in the package."""
        entry = dict(dict(title='Test Game', match=dict(gog=['123'], exe=['game.exe'], title=['game']), status='verified-bc250',
                          route='opti', fg_input='upscaler', ini={}, game_settings=[], launch_args=[]), **fields)
        self.fixtures.set_package_file(self.package, 'recipes/recipes.json', json.dumps(dict(
            schema=1, verified=[entry], wiki=[], leave_auto={}, backports={})).encode())

    def test_required_argument_is_installed_beside_the_users_api_switch(self):
        # GTA V Enhanced: -nobattleye with the user's own -dx12 in the entry, from 1.2.0's recipe form (among launch_args)
        # and from required_args. 1.2.0 left it out ("Launch option not added").
        m = self.fixtures.m
        doc = json.loads(self.config.read_text());doc['123']['launcherArgs'] = '~/.saves -dx12';self.config.write_text(json.dumps(doc))
        original = self.config.read_bytes()
        for fields in (dict(launch_args=['-nobattleye']), dict(required_args=['-nobattleye'])):
            with self.subTest(fields=fields):
                self.recipe(**fields)
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    m.install(self.package, self.exe, route='opti')
                self.assertEqual(json.loads(self.config.read_text())['123']['launcherArgs'], '~/.saves -dx12 -nobattleye')
                record = json.loads((self.game/m.STATE/'state.json').read_text())
                self.assertEqual((record['launch_args'], record['required_args'], record['launch_args_added']), ([], ['-nobattleye'], ['-nobattleye']))
                self.assertEqual(record['recipe']['required_args'], ['-nobattleye'])
                self.assertIn('Launch option added: -nobattleye', out.getvalue())
                self.assertNotIn('Launch option not added', out.getvalue())
                m.restore(self.exe)
                self.assertEqual(self.config.read_bytes(), original)

    def test_lutris_entry_without_the_required_argument_refuses_before_any_change(self):
        from vendor import yaml
        m = self.fixtures.m
        self.config.unlink()
        lutris = self.root/'.config/lutris/games/game.yml'
        doc = dict(game={'exe': str(self.exe), 'args': '-dx12'}, system={'env': {'VKD3D_CONFIG': 'dxr'}})
        m.write(lutris, yaml.safe_dump(doc).encode())
        self.recipe(required_args=['-nobattleye'])
        verdict = m.compat_verdict(self.package, self.exe, 'opti', 'upscaler')[0]
        self.assertEqual([r['code'] for r in verdict['blocking']], ['required-args'])
        with self.assertRaisesRegex(ValueError, 'add -nobattleye'):
            m.install(self.package, self.exe, route='opti')
        self.assertFalse((self.game/m.STATE).exists())
        for name, data in self.original.items():self.assertEqual((self.game/name).read_bytes(), data)
        doc['game']['args'] = '-dx12 -nobattleye'
        m.write(lutris, yaml.safe_dump(doc).encode())
        m.install(self.package, self.exe, route='opti')
        self.assertEqual(yaml.safe_load(lutris.read_text())['game']['args'], '-dx12 -nobattleye')
        m.restore(self.exe)
        self.assertEqual(yaml.safe_load(lutris.read_text()), doc)

    def test_contract_ini_keys_are_the_ones_install_writes_for_the_enabler_runtime(self):
        # The proxy packages' are checked in test_proxy_install; here the multi-frame loader's (runtime xemfg).
        m = self.fixtures.m
        for route in ('opti', 'native'):
            with self.subTest(route=route):
                m.install(self.package, self.exe, route=route, fg_input='upscaler')
                written = {c['section']+'.'+c['key']: c['value'] for c in json.loads((self.game/m.STATE/'state.json').read_text())['ini_changes']}
                m.restore(self.exe)
                contract = m.integration_contract(*m.package_contract(self.package))
                self.assertEqual([r['runtime'] for r in contract['routes']], ['xemfg', 'xemfg'])
                keys = next(r['ini'] for r in contract['routes'] if r['route'] == route)
                self.assertEqual(written, {k['key']: k['value'].replace('{fg_input}', 'upscaler') for k in keys
                                           if k['write'] != 'repair' and (not k['when'] or 'upscaler' in k['when'])})

    def test_missing_launcher_is_preflight_failure(self):
        m=self.fixtures.m
        self.config.unlink()
        with self.assertRaisesRegex(ValueError,'No launcher entry'):m.install(self.package,self.exe,route='native')
        self.assertFalse((self.game/m.STATE).exists())
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data)

    def test_status_and_restore_after_the_game_left_the_launcher(self):
        m=self.fixtures.m
        m.install(self.package,self.exe,route='native')
        self.config.write_text(json.dumps({}))  # removed from Heroic; its settings file stays
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe);m.restore(self.exe)
        self.assertIn('heroic launch settings: no longer present',out.getvalue())
        self.assertIn('Launcher entry no longer present, nothing to undo: '+str(self.config)+' (Heroic game 123 no longer exists)',out.getvalue())
        self.assertEqual(json.loads((self.game/m.STATE/'state.json').read_text())['status'],'restored')
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data)
        self.assertEqual(json.loads(self.config.read_text()),{})

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
