# SPDX-License-Identifier: MIT
"""Per-game recipes: matching, INI keys only where auto, reversible game settings and launch arguments."""
import contextlib, copy, hashlib, io, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
import launcher_config as l
import recipes as r
from steam_config import Document

RENDERER = b'{\n\t"objectType": "rend::UserRendererSettings",\n\t"m_eDLSSFGMode": 0,\n\t"m_eWindowMode": 1\n}'


class EditTests(unittest.TestCase):
    def test_json_keeps_tab_layout(self):
        out = r.edit(RENDERER, 'json', None, {'m_eDLSSFGMode': 1})
        self.assertIn(b'\n\t"m_eDLSSFGMode": 1,', out)
        self.assertEqual(json.loads(out)['m_eWindowMode'], 1)
        self.assertIsNone(r.edit(RENDERER, 'json', None, {'missing': 1}))

    def test_json_options(self):
        data = json.dumps({'data': [{'group_name': 'g', 'options': [{'name': 'FrameGeneration', 'value': 'DLSS'}]}]}).encode()
        out = json.loads(r.edit(data, 'json-options', None, {'FrameGeneration': 'XESS'}))
        self.assertEqual(out['data'][0]['options'][0]['value'], 'XESS')
        self.assertIsNone(r.edit(data, 'json-options', None, {'Other': 1}))

    def test_xml_option(self):
        data = b'<Options>\n<OptionBool Name="_enableFrameGeneration" _value="False"/>\n</Options>\n'
        out = r.edit(data, 'xml-option', None, {'_enableFrameGeneration': 'True'})
        self.assertIn(b'<OptionBool Name="_enableFrameGeneration" _value="True"/>', out)
        self.assertTrue(r.values_in(out, 'xml-option', None, {'_enableFrameGeneration': 'True'}))

    def test_ini_replace_needs_existing_line(self):
        data = b'[/Script/Game.MyGameUserSettings]\r\nbAMDFrameGeneration=False\r\n'
        self.assertEqual(r.edit(data, 'ini-replace', None, {'bAMDFrameGeneration': 'True'}),
                         b'[/Script/Game.MyGameUserSettings]\r\nbAMDFrameGeneration=True\r\n')
        self.assertIsNone(r.edit(data, 'ini-replace', None, {'DLSS_FG': 'True'}))
        self.assertEqual(r.edit(b'[A]\nFGInput = fsrfg\n', 'ini-replace', None, {'FGInput': 'dlssg'}), b'[A]\nFGInput = dlssg\n')

    def test_ini_adds_section_or_key(self):
        self.assertEqual(r.edit(b'', 'ini', 'SystemSettings', {'r.A': '0'}), b'[SystemSettings]\nr.A=0\n')
        self.assertEqual(r.edit(b'[SystemSettings]\nr.B=1\n', 'ini', 'SystemSettings', {'r.A': '0'}),
                         b'[SystemSettings]\nr.A=0\nr.B=1\n')
        self.assertEqual(r.edit(b'[Core.Log]\n', 'ini', 'SystemSettings', {'r.A': '0'}), b'[Core.Log]\n[SystemSettings]\nr.A=0\n')

    def test_ini_crlf_spaced_key_and_section_scope(self):
        crlf = b'[Core.System]\r\nPaths=x\r\n[SystemSettings]\r\nr.B=1\r\n'
        self.assertEqual(r.edit(crlf, 'ini', 'SystemSettings', {'r.A': '0'}),
                         b'[Core.System]\r\nPaths=x\r\n[SystemSettings]\r\nr.A=0\r\nr.B=1\r\n')
        self.assertEqual(r.edit(b'[SystemSettings]\nr.A = 1\n', 'ini', 'SystemSettings', {'r.A': '0'}), b'[SystemSettings]\nr.A = 0\n')
        # The same key in another section is another setting: left alone.
        self.assertEqual(r.edit(b'[Other]\nr.A=1\n[SystemSettings]\nr.B=1\n', 'ini', 'SystemSettings', {'r.A': '0'}),
                         b'[Other]\nr.A=1\n[SystemSettings]\nr.A=0\nr.B=1\n')
        self.assertEqual(r.edit(b'[systemsettings]', 'ini', 'SystemSettings', {'r.A': '0', 'r.B': '1'}), b'[systemsettings]\nr.A=0\nr.B=1')

    def test_ini_replace_scope_case_and_all_or_nothing(self):
        data = b'[A]\n  dlss_fg = False\n[B]\nDLSS_FG=False\n'
        self.assertEqual(r.edit(data, 'ini-replace', 'a', {'DLSS_FG': 'True'}), b'[A]\n  dlss_fg = True\n[B]\nDLSS_FG=False\n')
        self.assertEqual(r.edit(data, 'ini-replace', None, {'DLSS_FG': 'True'}), b'[A]\n  dlss_fg = True\n[B]\nDLSS_FG=True\n')
        self.assertIsNone(r.edit(b'; DLSS_FG=False\n[A]\n', 'ini-replace', None, {'DLSS_FG': 'True'}))
        mixed = r.change(b'[A]\nMode=Off\n[B]\nMode=On\n', 'ini-replace', None, {'Mode': 'FSR'})
        self.assertIsNone(mixed['after'])
        self.assertIn('several places: Mode', mixed['reason'])
        # A multi-key entry is one verified combination: nothing is applied while a key is missing, and it is named.
        partial = r.change(b'[S]\nUpscalingMethod=0\n', 'ini-replace', None, {'UpscalingMethod': '2', 'NvidiaFrameGeneration': '1'})
        self.assertIsNone(partial['after'])
        self.assertIn('not in the file yet: NvidiaFrameGeneration (', partial['reason'])

    def test_values_in_effect_are_not_rewritten(self):
        cases = [(b'\xef\xbb\xbf[S]\r\nDLSS_FG=True\r\n', 'ini-replace', None, {'DLSS_FG': 'True'}),
                 (b'<Options><OptionBool Name="_enableFrameGeneration" _value="True" Min="0"/></Options>', 'xml-option', None,
                  {'_enableFrameGeneration': 'True'}),
                 (b'{"a": 1, "m_eDLSSFGMode": 1}\r\n', 'json', None, {'m_eDLSSFGMode': 1}),
                 (b'\xef\xbb\xbf[SystemSettings]\r\nr.A = 0\r\n', 'ini', 'SystemSettings', {'r.A': '0'})]
        for data, fmt, section, values in cases:
            self.assertIs(r.edit(data, fmt, section, values), data)
            self.assertTrue(r.values_in(data, fmt, section, values))
        self.assertEqual(r.edit(b'{"m": true}', 'json', None, {'m': 1}), b'{"m": 1}')  # JSON types count

    def test_edits_change_only_the_values(self):
        self.assertEqual(r.edit(b'{"a": 1, "m_eDLSSFGMode": 0}\r\n', 'json', None, {'m_eDLSSFGMode': 1}),
                         b'{"a": 1, "m_eDLSSFGMode": 1}\r\n')
        data = json.dumps({'version': 2, 'data': [{'group_name': 'g', 'options': [
            {'name': 'FrameGeneration', 'type': 'name', 'value': 'DLSS', 'index': 0}, {'name': 'WindowMode', 'value': 'Fullscreen'}]}]}).encode()
        self.assertEqual(r.edit(data, 'json-options', None, {'FrameGeneration': 'XESS', 'WindowMode': 'BorderlessWindowed'}),
                         data.replace(b'"DLSS"', b'"XESS"').replace(b'"Fullscreen"', b'"BorderlessWindowed"'))
        xml = b'<Options>\r\n<OptionBool _value="False" Name="_enableFrameGeneration" Min="0"/>\r\n</Options>'
        self.assertEqual(r.edit(xml, 'xml-option', None, {'_enableFrameGeneration': 'True'}), xml.replace(b'False', b'True'))

    def test_utf16_bom_ini_round_trip(self):
        text = '[/Script/Pagoda.Settings]\r\nFrameGenerationMode=Off\r\nPlayerName=Jos\u00e9\r\n'
        for bom, codec in ((b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')):
            data = bom + text.encode(codec)
            plan = r.change(data, 'ini-replace', None, {'FrameGenerationMode': 'FSR'})
            self.assertEqual(plan['after'], bom + text.replace('=Off', '=FSR').encode(codec))
            self.assertEqual(plan['originals'], {'FrameGenerationMode': {'value': 'Off'}})
            game = plan['after'] + '[New]\r\n'.encode(codec)  # the game saved its settings since
            self.assertEqual(r.revert(game, 'ini-replace', None, {'FrameGenerationMode': 'FSR'}, plan['originals']),
                             (data + '[New]\r\n'.encode(codec), {}))
        with self.assertRaises(r.Unreadable):
            r.edit(b'[S]\nPlayerName=Jos\xe9\n', 'ini-replace', None, {'PlayerName': 'x'})  # ANSI, not UTF-8
        self.assertFalse(r.values_in(b'\xff\xfe\x00', 'ini', 'S', {'A': '1'}))

    def test_revert_by_key(self):
        values = {'DLSS_FG': 'True', 'Other': '1'}
        plan = r.change(b'[S]\r\nDLSS_FG=False\r\nOther=0\r\n', 'ini-replace', None, values)
        # The game rewrote the file since (a new key) and the user chose another value for Other: that one is theirs.
        game = plan['after'].replace(b'Other=1', b'Other=5') + b'New=1\r\n'
        self.assertEqual(r.revert(game, 'ini-replace', None, values, plan['originals']),
                         (b'[S]\r\nDLSS_FG=False\r\nOther=5\r\nNew=1\r\n', {'Other': 'changed'}))
        # A key and section the 'ini' format added go again; a key the game dropped is reported.
        plan = r.change(b'[Core.Log]\n', 'ini', 'SystemSettings', {'r.A': '0'})
        self.assertTrue(plan['created_section'])
        self.assertEqual(r.revert(plan['after'], 'ini', 'SystemSettings', {'r.A': '0'}, plan['originals'], True), (b'[Core.Log]\n', {}))
        self.assertEqual(r.revert(b'[S]\n', 'ini-replace', None, values, {'DLSS_FG': {'value': 'False'}, 'Other': {'value': '0'}})[1],
                         {'DLSS_FG': 'missing', 'Other': 'missing'})

    def test_previous_originals_carried_while_the_recipe_value_stays(self):
        previous = {'DLSS_FG': dict(recipe='True', original={'value': 'False'})}
        plan = r.change(b'[S]\nDLSS_FG=True\n', 'ini-replace', None, {'DLSS_FG': 'True'}, previous)
        self.assertEqual((plan['after'], plan['carried'], plan['originals']), (b'[S]\nDLSS_FG=True\n', ['DLSS_FG'], {'DLSS_FG': {'value': 'False'}}))
        # The user set another value since: that is the original now.
        plan = r.change(b'[S]\nDLSS_FG=Auto\n', 'ini-replace', None, {'DLSS_FG': 'True'}, previous)
        self.assertEqual((plan['carried'], plan['originals']), ([], {'DLSS_FG': {'value': 'Auto'}}))


class MatchTests(unittest.TestCase):
    DATA = dict(verified=[dict(title='CONTROL Resonant', match=dict(exe=['controlresonant.exe'], steam=['3669870']))],
                wiki=[dict(title='Crimson Desert', match=dict(title=['crimson desert'], exe=['crimsondesert.exe']))],
                leave_auto={'granblue_fantasy_relink.exe': [dict(key='fakenvapi.UseFakenvapi', quirk='DisableFakenvapi')]},
                backports={'fbcfirebreak.exe': {'Spoofing.Dxgi': dict(value='false')}})

    def ids(self, exe, steam=(), titles=()):
        return dict(exe=exe, steam=set(steam), gog=set(), epic=set(), titles=set(titles))

    def test_verified_by_launcher_id_or_exe_and_folder(self):
        self.assertEqual(r.match(self.DATA, self.ids('controlresonant.exe', ['3669870']))[0]['title'], 'CONTROL Resonant')
        # Same exe name under another Steam app: not this recipe.
        self.assertIsNone(r.match(self.DATA, self.ids('controlresonant.exe', ['1']))[0])
        # No launcher ID (Lutris, a non-Steam shortcut): the exe name alone is not enough; the title or a folder is.
        self.assertIsNone(r.match(self.DATA, self.ids('controlresonant.exe'))[0])
        self.assertIsNotNone(r.match(self.DATA, self.ids('controlresonant.exe', titles=['control resonant']))[0])
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp)/'Games/CONTROL Resonant/bin/ControlResonant.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'MZ')
            ids = r.identity(exe, (), home=tmp)
            self.assertEqual(r.match(self.DATA, ids)[0]['title'], 'CONTROL Resonant')
            other = Path(tmp)/'Games/Something Else/ControlResonant.exe'
            other.parent.mkdir(parents=True)
            other.write_bytes(b'MZ')
            self.assertIsNone(r.match(self.DATA, r.identity(other, (), home=tmp))[0])

    def test_wiki_by_title_and_quirk_lists(self):
        _, wiki, leave, back = r.match(self.DATA, self.ids('game.exe', titles=['crimson desert']))
        self.assertEqual([w['title'] for w in wiki], ['Crimson Desert'])
        self.assertEqual(r.match(self.DATA, self.ids('granblue_fantasy_relink.exe'))[2][0]['quirk'], 'DisableFakenvapi')
        self.assertIn('Spoofing.Dxgi', r.match(self.DATA, self.ids('fbcfirebreak.exe'))[3])

    def test_ini_changes_only_auto_and_input(self):
        verified = dict(ini={'FrameGen.FTInput': '2', 'Spoofing.Dxgi': 'false'})
        parsed = {('spoofing', 'dxgi'): 'true'}
        self.assertEqual(r.ini_changes(verified, {}, parsed, 'dlssg', 'dlssg'), {('FrameGen', 'FTInput'): '2'})
        self.assertEqual(r.ini_changes(verified, {}, {}, 'upscaler', 'dlssg'), {('Spoofing', 'Dxgi'): 'false'})
        # Frame-generation keys of a native-route recipe are not written when the user chose an OptiScaler route.
        native = dict(verified, route='native')
        self.assertEqual(r.ini_changes(native, {}, {}, 'upscaler', None, 'opti'), {('Spoofing', 'Dxgi'): 'false'})
        self.assertEqual(len(r.ini_changes(native, {}, {}, 'upscaler', None, 'native')), 2)

    def test_game_settings_follow_the_recipe_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp)
            (user/'s.json').write_bytes(b'{"m": 0}')
            game = [dict(file='s.json', format='json', values={'m': 1}, requires_fg_input=None)]
            native = dict(route='native', fg_input=None, game_settings=game)
            self.assertEqual(r.settings_plan(native, user, 'opti', 'upscaler'), [])
            self.assertEqual(r.settings_plan(native, user, 'native', None)[0]['after'], b'{"m": 1}')
            opti = dict(route='opti', fg_input='dlssg', game_settings=[dict(game[0], requires_fg_input='dlssg')])
            self.assertEqual(r.settings_plan(opti, user, 'native', None), [])
            self.assertEqual(r.settings_plan(opti, user, 'opti', 'upscaler'), [])
            self.assertEqual(len(r.settings_plan(opti, user, 'opti', 'dlssg')), 1)

    def test_upscaler_specific_ini_keeps_explicit_choices(self):
        verified=dict(ini={},upscaler_ini={'helixsr':{'InitFlags.DisableReactiveMask':'true'}})
        args=(verified,{}, {},'upscaler','upscaler','opti')
        self.assertEqual(r.ini_changes(*args,upscaler='fsr4'),{})
        self.assertEqual(r.ini_changes(*args,upscaler='helixsr'),{('InitFlags','DisableReactiveMask'):'true'})
        self.assertEqual(r.ini_changes(verified,{}, {('initflags','disablereactivemask'):'false'},
                                      'upscaler','upscaler','opti','helixsr'),{})

    def test_launch_args(self):
        self.assertEqual(r.launch_args(dict(launch_args=['-force-d3d12']), [dict(launch_args=['-dx12'])]), ['-force-d3d12'])
        self.assertEqual(r.launch_args(None, [dict(launch_args=['-dx12', '-d3d12'])]), ['-dx12'])
        self.assertEqual(l.with_args(['%command%', '-dx11'], ['-dx12']), ['%command%', '-dx11'])
        # Only an API switch: an argument the game always needs is a required argument (I-3), never taken from the wiki.
        gta = dict(launch_args=[], required_args=['-nobattleye'])
        self.assertEqual((r.launch_args(gta, []), r.required_args(gta)), ([], ['-nobattleye']))
        self.assertEqual(r.launch_args(dict(launch_args=['-nobattleye']), [dict(launch_args=['-dx12'])]), [])
        self.assertEqual(r.required_args(None), [])
        self.assertEqual(r.launch_args(None, [dict(launch_args=['-dx12'], required_args=['-x'])]), ['-dx12'])

    def test_shipped_recipe_file(self):
        data = r.load()
        self.assertEqual(data['schema'], 1)
        control = next(v for v in data['verified'] if v['title'] == 'CONTROL Resonant')
        self.assertEqual(control['fg_input'], 'dlssg')
        self.assertEqual(control['game_settings'][0]['values'], {'m_eDLSSFGMode': 1})
        self.assertNotIn('controlresonant.exe', data['backports'])  # RULES.md Q2: the local recipe decides
        self.assertIn('granblue_fantasy_relink.exe', data['leave_auto'])


class BuildTests(unittest.TestCase):
    """research/recipes/build_recipes.py: what the shipped recipe file keeps, and what the build refuses."""
    ROOT = Path(__file__).resolve().parents[1]

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_recipes', cls.ROOT/'research/recipes/build_recipes.py')
        cls.b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.b)
        cls.data = r.load(cls.ROOT/'packaging/recipes/recipes.json')
        import compat
        cls.compat = compat

    def test_every_condition_survives(self):
        # 0.9.0 kept six condition keys, so Hellraiser's AlwaysCaptureFSRFGSwapchain=true lost "if stuck on boot".
        hell = next(w for w in self.data['wiki'] if w['title'].startswith("Clive Barker's Hellraiser"))
        item = next(i for i in hell['ini'] if i['key'] == 'OptiFG.AlwaysCaptureFSRFGSwapchain')
        self.assertEqual(item['when']['condition'], 'stuck on boot')
        extra = [i for w in self.data['wiki'] for i in w.get('ini', []) if set(i.get('when', {})) - {'fg_input', 'gpu', 'upscaler_input', 'os', 'api', 'fg_output'}]
        self.assertGreaterEqual(len(extra), 49)
        # A conditional DX12 argument is not L1 (ODDRoom: "if DLSS input doesn't work").
        odd = next(w for w in self.data['wiki'] if w['title'] == 'ODDRoom')
        self.assertNotIn('launch_args', odd)
        self.assertIn('-dx12', odd['other_launch_args'])

    def test_sources_and_backports_follow_the_shipped_build(self):
        root = Path(__file__).resolve().parents[1]
        spec = json.loads((root/'release/package.json').read_text())
        self.assertEqual(self.data['sources']['optiscaler_pinned'], spec['manifest']['optiscaler']['source_commit'])
        review = json.loads((root/'research/recipes/utilization-review-20261030.json').read_text())
        self.assertTrue(self.data['sources']['wiki'].startswith(review['wiki']))
        # The October 25 build includes the previous BeamNG backport.
        self.assertEqual(self.data['backports'], {})
        self.assertEqual(sorted(self.data['leave_auto']), ['dcs.exe', 'endfield.exe', 'granblue_fantasy_relink.exe'])
        # Q2 answered: the shipped build itself keeps CONTROL Resonant's FG swap chain unpreserved (a runtime quirk).
        control = self.data['quirk_keys']['controlresonant.exe']
        self.assertEqual([v for k, v in control.items() if 'PreserveSwapChain' in k], ['false'])

    def test_store_ids_unlock_all_six_existing_promotions(self):
        count = 0
        for entry in self.data['wiki']:
            if not entry.get('promoted'):
                continue
            identities = {'steam': entry['match']['steam'], 'exe': 'unidentified.exe'}
            plan = self.compat.wiki_plan(self.data, identities, {'fg_input': 'upscaler'})
            for item in entry['promoted']:
                self.assertEqual(plan['automatic'].get(item['key']), item['value'], entry['title'])
                count += 1
        self.assertEqual(count, 6)
        plan = self.compat.wiki_plan(self.data, {'steam': ['2322010']})
        self.assertIn('upscaler', plan['vetoes'])

    def test_refreshed_data_survives_runtime_compaction(self):
        compact = self.b.compact(self.data, 'test')
        for title in ('Kena: Bridge of Spirits', 'FINAL FANTASY XIV: Dawntrail', 'METRO Redux', 'Gears of War: E-Day'):
            full = next(w for w in self.data['wiki'] if w['title'] == title)
            runtime = next(w for w in compact['wiki'] if w['title'] == title)
            self.assertEqual(runtime.get('ini'), full.get('ini'))
            self.assertEqual(runtime.get('requirements'), full.get('requirements'))
        kena = next(w for w in compact['wiki'] if w['title'] == 'Kena: Bridge of Spirits')
        self.assertTrue(any(i.get('when', {}).get('gpu') == 'non-nvidia' for i in kena['ini']))
        # Each OptiScaler.ini's keys once (two builds share one INI); recipes.load gives every build its list again.
        self.assertEqual(len(compact['optiscaler_ini_keys']), len({b['ini_sha256'] for b in self.data['optiscaler_builds'].values()}))
        self.assertEqual({c: dict(b, keys=compact['optiscaler_ini_keys'][b['ini_sha256']]) for c, b in compact['optiscaler_builds'].items()},
                         self.data['optiscaler_builds'])
        self.assertEqual(len(self.data['wiki']), 761)

    def test_dependency_missing_cannot_be_confirmed_away(self):
        ids = {'exe': 'ffxiv_dx11.exe', 'titles': ['final fantasy xiv dawntrail']}
        base = {'upscaler_input': 'fsr31_12', 'files': []}
        missing = self.compat.wiki_plan(self.data, ids, base)
        row = next(r for r in missing['rows'] if r['key'] == 'FSR.FsrAgilitySDKUpgrade')
        self.assertEqual(row['action'], 'inapplicable')
        with self.assertRaisesRegex(ValueError, 'required file'):
            self.compat.select_wiki_settings(missing, [row['id']], [row['id']])
        present = self.compat.wiki_plan(self.data, ids, dict(base, files=['D3D12_Optiscaler/D3D12Core.dll']))
        row = next(r for r in present['rows'] if r['key'] == 'FSR.FsrAgilitySDKUpgrade')
        self.assertEqual(row['action'], 'conditional')  # symptom still needs the player's confirmation
        self.assertTrue(present['requirements'])

    def test_context_uses_actual_api_proxy_and_upscaler_input(self):
        for key, expected, actual in [('api', 'dx12', 'dx11'), ('proxy', 'dxgi.dll', 'winmm.dll'),
                                      ('upscaler_input', 'dlss', 'fsr2')]:
            self.assertIs(self.compat.evaluate({key: expected}, {key: actual})[0], False)
            self.assertIs(self.compat.evaluate({key: expected}, {key: expected})[0], True)

    FULL = ROOT/'packaging/recipes/recipes.json'
    COMPACT = ROOT/'packaging/recipes/recipes-runtime.json'

    def test_the_shipped_files_are_what_the_inputs_build(self):
        # Offline and from this tree alone: a refresh can only change what its own input says.
        full = self.b.dumps(self.b.build())
        self.assertEqual(self.FULL.read_text(), full, 'stale: run research/recipes/build_recipes.py')
        self.assertEqual(self.COMPACT.read_text(), self.b.compact_text(full), 'stale: run research/recipes/build_recipes.py')

    def test_one_format(self):
        for path, dump in ((self.FULL, self.b.dumps), (self.COMPACT, self.b.dumps_compact)):
            raw = path.read_text()
            self.assertEqual(dump(json.loads(raw)), raw, path.name)
        inputs = self.ROOT/'research/recipes'
        for name in ('optiscaler.json', 'catalogue.json', 'wiki-curation.json'):
            self.assertEqual(self.b.dumps(json.loads((inputs/name).read_text())), (inputs/name).read_text(), name)
        raw = (inputs/'wiki.json').read_text()
        self.assertEqual(self.b.dumps_rows(json.loads(raw), 'entries'), raw)
        self.assertEqual(sum(1 for line in raw.splitlines() if line.startswith('    {')), len(json.loads(raw)['entries']))  # one line each

    def inputs(self, tmp):
        """A copy of the committed inputs (refresh tests write only the copy)."""
        folder = Path(tmp)/'recipes'
        shutil.copytree(self.ROOT/'research/recipes', folder, ignore=shutil.ignore_patterns('*.py', '*.md', '__pycache__'))
        return folder

    # Research drafts (research SCHEMA.md) for one wiki title: a page with INI and launch items, and its compatibility row.
    DRAFTS = dict(entries=[
        dict(title='Soulstice', source=dict(kind='wiki-page', page='Soulstice', line=3), tested=dict(optiscaler=['0.9'], gpu=['RX 7900 XTX']),
             upscaler_inputs=['dlss'], items=[dict(type='ini', key='Hotfix.ColorResourceBarrier', value='4', confidence='high'),
                                               dict(type='ini', key='Not.AKey', value='1', confidence='high'),
                                               dict(type='launch', args=['-dx12'], confidence='high'),
                                               dict(type='launch', args=['-skipintro', '-dx12'], when=dict(condition='crash at start'), confidence='high'),
                                               dict(type='issue', quote='prose stays in the drafts', confidence='high')]),
        dict(title='Soulstice', source=dict(kind='compat-list', line=40), compat='working', optipatcher=False, items=[])])

    def refresh(self, folder, drafts):
        path = folder.parent/'drafts'
        path.mkdir(exist_ok=True)
        (path/'pages-00.json').write_text(json.dumps(drafts))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.b.refresh_wiki(path, '0123456789abcdef0123456789abcdef01234567', '2026-11-01', folder)
        return out.getvalue()

    def test_a_wiki_refresh_keeps_the_curated_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.inputs(tmp)
            curation = json.loads((folder/'wiki-curation.json').read_text())
            curation['entries'] = {'Soulstice': curation['entries']['Soulstice']}
            (folder/'wiki-curation.json').write_text(json.dumps(curation))
            review = json.loads((folder/'wiki_promote.json').read_text())
            review['items'] = [i for i in review['items'] if i['title'] == 'Soulstice']
            (folder/'wiki_promote.json').write_text(json.dumps(review))
            self.assertIn('dropped 1 INI items no shipped key reads: Soulstice: Not.AKey', self.refresh(folder, self.DRAFTS))
            data = self.b.build(folder)
            entry, = data['wiki']
            self.assertEqual(entry['match'], dict(title=['soulstice'], exe=['soulstice.exe'], steam=['1602080']))
            self.assertEqual(entry['identity_sources'][0]['appid'], '1602080')
            self.assertEqual(entry['promoted'], [dict(key='Hotfix.ColorResourceBarrier', value='4')])
            self.assertEqual((entry['launch_args'], entry['other_launch_args']), (['-dx12'], ['-skipintro', '-dx12']))
            self.assertEqual((entry['compat'], entry['optipatcher'], entry['counts']), ('working', False, {'ini': 2, 'launch': 2, 'issue': 1}))
            self.assertEqual(entry['pages'], ['https://github.com/optiscaler/OptiScaler/wiki/Soulstice',
                                              'https://github.com/optiscaler/OptiScaler/wiki/Compatibility-List'])
            self.assertEqual(data['sources']['wiki'], '0123456789abcdef0123456789abcdef01234567 (2026-11-01)')
            self.assertEqual(data['optiscaler_builds'], self.data['optiscaler_builds'])  # not the wiki's to change
            self.assertNotIn('prose', json.dumps(data))

    def test_a_refresh_that_loses_a_curated_or_promoted_title_refuses_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.inputs(tmp)
            self.refresh(folder, self.DRAFTS)
            with self.assertRaisesRegex(SystemExit, "no wiki entry is titled 'Apocalypse 2.0'"):
                self.b.build(folder)
            (folder/'wiki-curation.json').write_text(json.dumps(dict(entries={})))
            with self.assertRaisesRegex(SystemExit, 'Apocalypse 2.0 InitFlags.DisplayResolution=false is not an INI item'):
                self.b.build(folder)

    def test_add_build_records_digests_and_one_key_list_per_ini(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.inputs(tmp)
            ini = Path(tmp)/'OptiScaler.ini'
            ini.write_bytes(b'\xef\xbb\xbf[FrameGen]\nEnabled=auto\nFGInput=auto\n[XeFG]\nXeFGModel=auto\n')
            before = json.loads((folder/'optiscaler.json').read_text())
            with contextlib.redirect_stdout(io.StringIO()):
                self.b.add_build('a' * 40, 'b' * 64, ini, folder)
                self.b.add_build('c' * 40, 'd' * 64, ini, folder)
            after = json.loads((folder/'optiscaler.json').read_text())
            sha = hashlib.sha256(ini.read_bytes()).hexdigest()
            self.assertEqual(after['builds']['a' * 40], dict(dll_sha256='b' * 64, ini_sha256=sha))
            self.assertEqual(after['ini_keys'][sha], ['FrameGen.enabled', 'FrameGen.fginput', 'XeFG.xefgmodel'])
            self.assertEqual(len(after['ini_keys']), len(before['ini_keys']) + 1)  # both new builds share one list
            built = self.b.build(folder)['optiscaler_builds']
            self.assertEqual(built['c' * 40]['keys'], after['ini_keys'][sha])
            self.assertEqual(built[before['pinned']], self.data['optiscaler_builds'][before['pinned']])
            ini.write_bytes(b'[FrameGen]\nEnabled=auto\n')
            with contextlib.redirect_stdout(io.StringIO()):
                self.b.add_build('a' * 40, 'b' * 64, ini, folder)
                self.b.add_build('c' * 40, 'd' * 64, ini, folder)
            self.assertNotIn(sha, json.loads((folder/'optiscaler.json').read_text())['ini_keys'])  # no build uses it now
            with self.assertRaisesRegex(SystemExit, 'full commit'):
                self.b.add_build('abc', 'b' * 64, ini, folder)

    def test_a_quirk_refresh_derives_the_tables(self):
        pinned_commit = '03db4f8692878e65748769ebe583c053cae96360'
        level = {'set:Spoofing.Dxgi=false': [dict(ini='Spoofing.Dxgi', value='false', respects_user=True, condition=None)],
                 'set:fakenvapi.UseFakenvapi=false': [dict(ini='fakenvapi.UseFakenvapi', value='false', respects_user=True, condition=None)],
                 'set:Hotfix.ColorResourceBarrier=4': [dict(ini='Hotfix.ColorResourceBarrier', value='4', respects_user=True, condition=None)]}
        game = dict(exes=['game.exe'], quirks=['set:Spoofing.Dxgi=false', 'set:fakenvapi.UseFakenvapi=false'], comment=['Some Game'])
        other = dict(exes=['other.exe'], quirks=['set:Hotfix.ColorResourceBarrier=4'], comment=['Other Game: Remastered', 'detail'])
        quirks = dict(pinned=dict(commit=pinned_commit, entries=[game], config_level=level),
                      upstream=dict(commit='e' * 40, entries=[game, other], config_level=level))
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.inputs(tmp)
            (Path(tmp)/'quirks.json').write_text(json.dumps(quirks))
            with contextlib.redirect_stdout(io.StringIO()):
                self.b.refresh_quirks(Path(tmp)/'quirks.json', folder)
            q = json.loads((folder/'optiscaler.json').read_text())['quirks']
            self.assertEqual((q['pinned'], q['upstream']), (pinned_commit, 'e' * 40))
            self.assertEqual(q['leave_auto'], {'game.exe': [dict(key='fakenvapi.UseFakenvapi', quirk='set:fakenvapi.UseFakenvapi=false', value='false')]})
            self.assertEqual(q['backports'], {'other.exe': {'Hotfix.ColorResourceBarrier': dict(value='4', quirk='set:Hotfix.ColorResourceBarrier=4',
                                                                                              comment=['Other Game: Remastered'])}})
            self.assertEqual(q['quirk_keys'], {'game.exe': {'Spoofing.Dxgi': 'false', 'fakenvapi.UseFakenvapi': 'false'}})
            self.assertEqual(q['titles'], {'game.exe': 'some game', 'other.exe': 'other game'})
            quirks['pinned']['commit'] = 'f' * 40
            (Path(tmp)/'quirks.json').write_text(json.dumps(quirks))
            with self.assertRaisesRegex(SystemExit, 'pinned side'):
                self.b.refresh_quirks(Path(tmp)/'quirks.json', folder)

    def test_every_verified_recipe_has_its_evidence(self):
        for v in self.data['verified']:
            self.assertIn(v['evidence'], ('gameplay', 'generates', 'startup', 'installed', 'fails'), v['title'])
            self.assertTrue(v['observed'], v['title'])

    def test_installer_keys_alike(self):
        self.assertEqual(self.compat.INSTALLER_KEYS, self.b.INSTALLER_KEYS)

    def test_promotion_needs_the_drafts_item_and_an_allowed_key(self):
        wk = [dict(title='Game', match=dict(title=['game']), ini=[dict(key='Hotfix.ColorResourceBarrier', value='4'),
                                                                 dict(key='OptiFG.HUDFix', value='true')])]
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp)/'review.json'
            review.write_text(json.dumps(dict(items=[dict(title='Game', key='Hotfix.ColorResourceBarrier', value='4', decision='promote'),
                                                     dict(title='Game', key='OptiFG.HUDFix', value='true', decision='reject')])))
            self.assertEqual(self.b.promote(wk, review), 1)
            self.assertEqual(wk[0]['promoted'], [dict(key='Hotfix.ColorResourceBarrier', value='4')])
            for item, message in [(dict(title='Game', key='Hotfix.ColorResourceBarrier', value='8', decision='promote'), 'not an INI item'),
                                  (dict(title='Game', key='OptiFG.HUDFix', value='true', decision='promote'), 'H1')]:
                review.write_text(json.dumps(dict(items=[item])))
                with self.assertRaisesRegex(SystemExit, message):
                    self.b.promote([dict(wk[0], promoted=[])], review)
        shipped = [(w['title'], p['key']) for w in self.data['wiki'] for p in w.get('promoted', [])]
        self.assertIn(('Soulstice', 'Hotfix.ColorResourceBarrier'), shipped)
        self.assertNotIn('Alan Wake II', [t for t, _ in shipped])  # its condition ("if crashing") was missed: rejected

    GOOD = dict(title='Game', match=dict(steam=['42'], exe=['game-win64-shipping.exe']), status='community-bc250', route='opti',
                fg_input='upscaler', ini={'Hotfix.ColorResourceBarrier': '4'}, game_settings=[], launch_args=['-dx12'],
                manual_steps=['Choose DLSS.'], reports=[dict(issue=1, freefg='0.9.1', proton='GE-Proton11-7', ratio=2.0, minutes=30,
                                                             starts=3, restore_checked=True, date='2026-11-02')],
                reviewed_by='maintainer', reviewed='2026-11-03')

    def test_community_recipes_are_checked(self):
        self.assertEqual(self.b.check_community(self.GOOD), [])
        cases = [(dict(ini={'OptiFG.HUDFix': 'true'}), 'H1'), (dict(ini={'fakenvapi.ForceReflex': '0'}), 'installer'), (dict(ini={'fakenvapi.EnableLogs': 'true'}), 'R1'),
                 (dict(ini={'Spoofing.Dxgi': 'false'}), 'D1'), (dict(fg_input='fsrfg30'), 'FSR 3.0'),
                 (dict(fg_input='dlssg', manual_steps=[]), 'F2'), (dict(launch_args=['-dx11']), 'DX12 switches'),
                 (dict(game_settings=[dict(file='/tmp/a.ini', format='ini', section='S', values={'a': '1'})]), 'relative'),
                 (dict(reports=[dict(self.GOOD['reports'][0], ratio=1.0)]), 'below the bar'), (dict(status='verified-bc250'), 'status'),
                 (dict(match=dict(exe=['game.exe']), title=''), 'missing title')]
        for change, message in cases:
            self.assertTrue(any(message in p for p in self.b.check_community(dict(self.GOOD, **change))), (change, message))
        quirks = {'game-win64-shipping.exe': {'Hotfix.ColorResourceBarrier': '4'}}
        self.assertTrue(any('Q1' in p for p in self.b.check_community(self.GOOD, quirks)))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'42.json').write_text(json.dumps(dict(self.GOOD, ini={'OptiFG.HUDFix': 'true'})))
            with self.assertRaisesRegex(SystemExit, '42.json'):
                self.b.community(Path(tmp))
            (Path(tmp)/'42.json').write_text(json.dumps(self.GOOD))
            self.assertEqual([c['title'] for c in self.b.community(Path(tmp))], ['Game'])
            built = self.b.compact(dict(schema=1, sources=dict(wiki_url='u/'), verified=[], community=self.b.community(Path(tmp)),
                                        leave_auto={}, backports={}, wiki=[]), '0')
            self.assertEqual(built['community'][0]['reports'], 1)


class RecipeInstallTests(unittest.TestCase):
    """The installer with a Steam library layout, a Proton prefix and a recipe."""
    def setUp(self):
        import test_mfg_install as fixtures
        self.fixtures = fixtures
        self.m = fixtures.m
        fixtures.GameFixture.setUp(self)
        fixtures.MfgTests.enable_settings(self)
        steam = self.root/'.local/share/Steam'
        common = steam/'steamapps/common'
        common.mkdir(parents=True)
        self.game.rename(common/'Test Game')
        self.game = common/'Test Game'
        self.exe = self.game/'Game.exe'
        (steam/'steamapps/appmanifest_4242.acf').write_bytes(b'"AppState" { "appid" "4242" "name" "Test Game" "installdir" "Test Game" }')
        self.config = steam/'userdata/42/config/localconfig.vdf'
        self.config.parent.mkdir(parents=True)
        self.original_config = b'"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "4242" { "LaunchOptions" "--skip-intro" } } } } } }\n'
        self.config.write_bytes(self.original_config)
        self.user = steam/'steamapps/compatdata/4242/pfx/drive_c/users/steamuser'
        self.renderer = self.user/'AppData/Local/Remedy/Test/renderer.ini'
        self.renderer.parent.mkdir(parents=True)
        self.renderer.write_bytes(RENDERER)
        self.recipes(dict(title='Test Game', match=dict(exe=['game.exe'], steam=['4242']), status='verified-bc250', route='opti',
                          fg_input='dlssg', ini={'FrameGen.FTInput': '2', 'Spoofing.Dxgi': 'false'},
                          game_settings=[dict(file='AppData/Local/Remedy/Test/renderer.ini', base='steamuser', format='json',
                                              values={'m_eDLSSFGMode': 1})],
                          launch_args=['-dx12'], note='Test note.'))
        for context in (patch.object(l.Path, 'home', return_value=self.root), patch.object(l, 'require_stopped')):
            context.start()
            self.addCleanup(context.stop)

    def recipes(self, verified, leave_auto=None):
        path = self.package/'recipes/recipes.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(dict(schema=1, verified=[verified] if verified else [], wiki=[], leave_auto=leave_auto or {},
                                        backports={})))

    def current_ini(self):
        return self.m.read_ini((self.game/'OptiScaler.ini').read_bytes())

    def options(self):
        return Document(self.config.read_bytes()).get(l.APP+['4242', 'LaunchOptions'])

    def assertOriginal(self):
        self.assertEqual(self.config.read_bytes(), self.original_config)
        for name, data in self.original.items():
            self.assertEqual((self.game/name).read_bytes(), data)

    def test_gta_recipe_enables_optifg_and_restores_originals(self):
        catalog = r.load(Path(__file__).resolve().parents[1]/'packaging/recipes/recipes.json')
        entry = copy.deepcopy(next(v for v in catalog['verified'] if '3240220' in v['match'].get('steam', [])))
        entry['match'] = dict(exe=['game.exe'], steam=['4242'])
        self.recipes(entry)
        self.install_quietly(fg_input='upscaler')
        ini = self.current_ini()
        self.assertEqual(ini[('framegen', 'enabled')], 'true')
        self.assertEqual(ini[('framegen', 'fginput')].lower(), 'upscaler')
        self.assertEqual(ini[('framegen', 'fgoutput')].lower(), 'xefg')
        self.assertNotEqual(ini.get(('spoofing', 'dxgifactorywrapping')), 'true')
        self.assertNotIn('socialclub', self.options().lower())
        self.assertEqual(self.renderer.read_bytes(), RENDERER)
        self.restore_quietly()
        self.assertOriginal()

    @unittest.skipUnless('required_args' in (Path(__file__).resolve().parents[1]/'packaging/install.py').read_text(),
                         'install.py adds a recipe\'s required arguments with the launch contract work (I-3, WP-L)')
    def test_gta_recipe_adds_its_required_argument(self):
        catalog = r.load(Path(__file__).resolve().parents[1]/'packaging/recipes/recipes.json')
        entry = copy.deepcopy(next(v for v in catalog['verified'] if '3240220' in v['match'].get('steam', [])))
        entry['match'] = dict(exe=['game.exe'], steam=['4242'])
        self.recipes(entry)
        self.install_quietly(fg_input='upscaler')
        self.assertIn('-nobattleye', self.options().split())
        self.restore_quietly()
        self.assertOriginal()

    def test_install_applies_recipe_and_restore_reverts(self):
        self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        ini = self.current_ini()
        self.assertEqual(ini[('framegen', 'ftinput')], '2')
        self.assertEqual(ini[('spoofing', 'dxgi')], 'false')
        self.assertEqual(json.loads(self.renderer.read_bytes())['m_eDLSSFGMode'], 1)
        self.assertTrue(self.options().endswith('%command% --skip-intro -dx12'))
        record = json.loads((self.game/self.m.STATE/'state.json').read_text())
        self.assertEqual(record['launch_args_added'], ['-dx12'])
        self.assertEqual(record['recipe']['title'], 'Test Game')
        self.assertEqual(record['game_settings'][0]['status'], 'applied')
        self.m.restore(self.exe)
        self.assertEqual(self.renderer.read_bytes(), RENDERER)
        self.assertOriginal()

    def test_launcher_bootstrap_exe_is_refused(self):
        # The Steam ID matches the recipe, but the chosen .exe is not the one the game renders from.
        stub = self.game/'Launcher.exe'; stub.write_bytes(self.exe.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Game.exe'):
            self.m.install(self.package, stub, route='opti', fg_input='dlssg')
        self.assertFalse((self.game/self.m.STATE).exists())
        self.assertOriginal()

    def test_restore_keeps_launch_options_the_user_added(self):
        self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        doc = Document(self.config.read_bytes())
        self.config.write_bytes(doc.set(l.APP+['4242', 'LaunchOptions'], 'BC250_XEFG_PACE=0 '+self.options()))
        self.m.restore(self.exe)
        self.assertEqual(self.options(), 'BC250_XEFG_PACE=0 %command% --skip-intro')
        for name, data in self.original.items():
            self.assertEqual((self.game/name).read_bytes(), data)

    def test_restore_completes_when_a_launcher_config_is_gone(self):
        self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        self.config.unlink()
        self.m.restore(self.exe)
        for name, data in self.original.items():
            self.assertEqual((self.game/name).read_bytes(), data)

    def test_restore_removes_the_app_entry_it_created(self):
        self.original_config = b'"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { } } } } }\n'
        self.config.write_bytes(self.original_config)
        self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        self.assertTrue(self.options().endswith('%command% -dx12'))
        self.m.restore(self.exe)
        # No empty "4242" { } object is left behind (whitespace inside "apps" may differ; Steam rewrites the file).
        self.assertEqual(Document(self.config.read_bytes()).keys(l.APP), [])
        self.assertEqual(self.config.read_bytes().split(), self.original_config.split())
        for name, data in self.original.items():
            self.assertEqual((self.game/name).read_bytes(), data)

    def test_user_ini_value_is_kept(self):
        ini = self.game/'OptiScaler.ini'
        ini.write_bytes(self.m.patch_ini(ini.read_bytes(), {('Spoofing', 'Dxgi'): 'true'}))
        self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        self.assertEqual(self.current_ini()[('spoofing', 'dxgi')], 'true')

    def test_other_input_skips_fg_parts(self):
        self.m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        ini = self.current_ini()
        self.assertNotIn(('framegen', 'ftinput'), ini)
        self.assertEqual(ini[('spoofing', 'dxgi')], 'false')
        self.assertEqual(self.renderer.read_bytes(), RENDERER)
        self.assertIn('-dx12', self.options())

    def test_pending_setting_applied_by_configure(self):
        self.renderer.unlink()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        self.assertIn('Game setting pending', out.getvalue())
        self.renderer.write_bytes(RENDERER)
        self.m.configure(self.exe)
        self.assertEqual(json.loads(self.renderer.read_bytes())['m_eDLSSFGMode'], 1)
        self.m.restore(self.exe)
        self.assertEqual(self.renderer.read_bytes(), RENDERER)
        self.assertOriginal()

    def record(self):
        return json.loads((self.game/self.m.STATE/'state.json').read_text())

    def install_quietly(self, **options):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.m.install(self.package, self.exe, **dict(dict(route='opti', fg_input='dlssg'), **options))
        return out.getvalue()

    def restore_quietly(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.m.restore(self.exe)
        return out.getvalue()

    def v26_record(self):
        """Make the installation record look like v26's: no per-key originals."""
        path = self.game/self.m.STATE/'state.json'
        record = json.loads(path.read_text())
        for item in record['game_settings']:
            for key in ('originals', 'carried', 'created_section', 'previous', 'reason', 'left'):
                item.pop(key, None)
        path.write_text(json.dumps(record))

    def game_saves(self, **changes):
        """The game rewrites renderer.ini in its own layout (4 spaces), with other values changed."""
        doc = json.loads(self.renderer.read_bytes())
        doc.update(changes)
        self.renderer.write_bytes(json.dumps(doc, indent=4).encode())
        return doc

    def test_game_rewritten_file_reverted_by_key(self):
        self.install_quietly()
        self.game_saves(m_eWindowMode=2)
        self.assertEqual(self.restore_quietly().count('Left'), 0)
        self.assertEqual(json.loads(self.renderer.read_bytes()), dict(json.loads(RENDERER), m_eWindowMode=2))
        self.assertIn(b'\n    "m_eDLSSFGMode": 0,', self.renderer.read_bytes())  # the game's layout stays
        self.assertEqual(self.record()['game_settings'][0]['status'], 'restored')
        self.assertOriginal()

    def test_recipe_key_the_user_changed_is_left(self):
        self.install_quietly()
        self.game_saves(m_eDLSSFGMode=2)
        out = self.restore_quietly()
        self.assertIn('Left AppData/Local/Remedy/Test/renderer.ini m_eDLSSFGMode=1 (changed since installation; kept)', out)
        self.assertEqual(json.loads(self.renderer.read_bytes())['m_eDLSSFGMode'], 2)
        self.assertEqual(self.record()['game_settings'][0]['left'], {'m_eDLSSFGMode': 'changed'})
        # Reinstalled, the user's value is the original.
        self.install_quietly()
        self.assertEqual(self.record()['game_settings'][0]['originals'], {'m_eDLSSFGMode': {'value': 2}})
        self.restore_quietly()
        self.assertEqual(json.loads(self.renderer.read_bytes())['m_eDLSSFGMode'], 2)
        self.assertOriginal()

    def test_restore_reinstall_restore_with_game_rewrites(self):
        for _ in range(2):
            self.install_quietly()
            self.assertEqual(self.record()['game_settings'][0]['status'], 'applied')
            self.assertEqual(self.record()['game_settings'][0]['originals'], {'m_eDLSSFGMode': {'value': 0}})
            self.game_saves(m_eWindowMode=2)
            self.restore_quietly()
            self.assertEqual(json.loads(self.renderer.read_bytes())['m_eDLSSFGMode'], 0)
        self.assertOriginal()

    def test_reinstall_over_v26_restore_that_left_the_file(self):
        self.install_quietly()
        self.v26_record()
        self.game_saves(m_eWindowMode=2)
        # v26's Restore left a file the game had rewritten as it was: the recipe value stayed, the item 'applied'.
        with patch.object(self.m, 'plan_restore_settings', return_value=([], [])):
            self.restore_quietly()
        self.assertEqual(json.loads(self.renderer.read_bytes())['m_eDLSSFGMode'], 1)
        self.install_quietly()
        item = self.record()['game_settings'][0]
        self.assertEqual((item['status'], item['carried'], item['originals']), ('applied', ['m_eDLSSFGMode'], {'m_eDLSSFGMode': {'value': 0}}))
        self.game_saves(m_eWindowMode=3)
        self.restore_quietly()
        self.assertEqual(json.loads(self.renderer.read_bytes()), dict(json.loads(RENDERER), m_eWindowMode=3))
        self.assertOriginal()

    def test_reinstall_after_another_installers_record_carries_originals(self):
        # The BC250 library moves between tester builds through its 2x package: v26's Restore left the rewritten file,
        # then the 2x installer archived that record under its own; the next tester install must still find the originals.
        self.install_quietly()
        self.v26_record()
        self.game_saves(m_eWindowMode=2)
        with patch.object(self.m, 'plan_restore_settings', return_value=([], [])):
            self.restore_quietly()
        state = self.game/self.m.STATE
        state.rename(self.game/(self.m.STATE + '-restored-tester0'))
        state.mkdir()
        (state/'state.json').write_text(json.dumps(dict(status='restored', files=[])))
        self.install_quietly()
        item = self.record()['game_settings'][0]
        self.assertEqual((item['status'], item['originals']), ('applied', {'m_eDLSSFGMode': {'value': 0}}))
        self.restore_quietly()
        self.assertEqual(json.loads(self.renderer.read_bytes()), dict(json.loads(RENDERER), m_eWindowMode=2))

    def test_v26_record_restored_by_key_from_its_backup(self):
        self.install_quietly()
        self.v26_record()
        self.game_saves(m_eWindowMode=2)
        self.restore_quietly()
        self.assertEqual(json.loads(self.renderer.read_bytes()), dict(json.loads(RENDERER), m_eWindowMode=2))
        self.assertOriginal()

    def test_v26_setting_without_its_backup_is_left_and_restore_completes(self):
        self.install_quietly()
        self.v26_record()
        (self.game/self.m.STATE/'game-settings/0').unlink()
        installed = self.renderer.read_bytes()
        out = self.restore_quietly()
        self.assertIn('backup is missing or damaged; set these back by hand', out)
        self.assertEqual(self.renderer.read_bytes(), installed)
        self.assertEqual(self.record()['status'], 'restored')
        self.assertOriginal()

    def test_unreadable_settings_file_is_left_and_restore_completes(self):
        self.install_quietly()
        installed = self.renderer.read_bytes()
        self.renderer.chmod(0)
        try:
            out = self.restore_quietly()
        finally:
            self.renderer.chmod(0o644)
        self.assertIn('cannot read it', out)
        self.assertEqual(self.renderer.read_bytes(), installed)
        self.assertEqual(self.record()['status'], 'restored')
        self.assertOriginal()

    def test_two_entries_on_one_file_are_undone_in_turn(self):
        # Install wrote entry 0 (A -> B), a later configure entry 1 (B -> C); Restore must end at A.
        ini = self.user/'AppData/Local/Test/Engine.ini'
        ini.parent.mkdir(parents=True)
        a, b, c = b'[S]\nx=0\ny=0\n', b'[S]\nx=1\ny=0\n', b'[S]\nx=1\ny=1\n'
        state = self.game/self.m.STATE
        (state/'game-settings').mkdir(parents=True)
        (state/'game-settings/0').write_bytes(a)
        (state/'game-settings/1').write_bytes(b)
        item = lambda key, before, after: dict(file='AppData/Local/Test/Engine.ini', path=str(ini), format='ini', section='S', values={key: '1'},
                                               status='applied', before=self.m.digest(before), after=self.m.digest(after),
                                               originals={key: {'value': '0'}}, carried=[], created_section=False)
        record = dict(game_settings=[item('x', a, b), item('y', b, c)])
        ini.write_bytes(c)
        writes, messages = self.m.plan_restore_settings(self.game, copy.deepcopy(record))
        self.assertEqual((writes, messages), ([(ini, c, a, 0o644)], []))
        ini.write_bytes(c + b'[Other]\nz=5\n')  # the game rewrote it: key by key, still both
        writes, messages = self.m.plan_restore_settings(self.game, copy.deepcopy(record))
        self.assertEqual([w[2] for w in writes], [a + b'[Other]\nz=5\n'])

    def test_restore_write_skips_a_file_changed_meanwhile(self):
        ini = self.user/'AppData/Local/Test/Engine.ini'
        ini.parent.mkdir(parents=True)
        ini.write_bytes(b'new')
        messages = self.m.write_restored_settings([(ini, b'planned from', b'restored', 0o644)])
        self.assertEqual(ini.read_bytes(), b'new')
        self.assertIn('changed while Restore ran', messages[0])

    def test_restore_by_key_without_a_backup(self):
        self.install_quietly()
        (self.game/self.m.STATE/'game-settings/0').unlink()
        self.restore_quietly()
        self.assertEqual(self.renderer.read_bytes(), RENDERER)
        self.assertOriginal()

    def test_created_settings_file_removed_only_if_untouched(self):
        engine = self.user/'AppData/Local/Test/Engine.ini'
        engine.parent.mkdir(parents=True)
        verified = dict(route='opti', fg_input='dlssg', game_settings=[dict(file='AppData/Local/Test/Engine.ini', format='ini',
                        section='SystemSettings', values={'r.A': '0'}, requires_fg_input=None)])
        plan = r.settings_plan(verified, self.user, 'opti', 'dlssg', create_ini=True)[0]
        self.assertEqual((plan['before'], plan['after']), (None, b'[SystemSettings]\nr.A=0\n'))
        record = dict(game_settings=[self.m.settings_record(plan)])
        engine.write_bytes(plan['after'])
        self.assertEqual(self.m.plan_restore_settings(self.game, copy.deepcopy(record))[0], [(engine, plan['after'], None, 0o644)])
        engine.write_bytes(plan['after'] + b'[Core.Log]\nLogX=1\n')  # the game added its own settings
        self.assertEqual(self.m.plan_restore_settings(self.game, record)[0], [(engine, plan['after'] + b'[Core.Log]\nLogX=1\n', b'[Core.Log]\nLogX=1\n', 0o644)])

    def test_utf16_settings_file_install_and_restore(self):
        text = '[/Script/Test.Settings]\r\nFrameGenerationMode=Off\r\nPlayerName=Jos\u00e9\r\n'
        original = b'\xff\xfe' + text.encode('utf-16-le')
        ini = self.user/'AppData/Local/Test/GameUserSettings.ini'
        ini.parent.mkdir(parents=True)
        ini.write_bytes(original)
        self.recipes(dict(title='Test Game', match=dict(exe=['game.exe'], steam=['4242']), status='verified-bc250', route='opti',
                          fg_input='dlssg', ini={}, launch_args=[], game_settings=[dict(file='AppData/Local/Test/GameUserSettings.ini',
                          base='steamuser', format='ini-replace', section=None, values={'FrameGenerationMode': 'FSR'})]))
        self.install_quietly()
        self.assertEqual(ini.read_bytes(), b'\xff\xfe' + text.replace('=Off', '=FSR').encode('utf-16-le'))
        ini.write_bytes(ini.read_bytes() + 'Saved=1\r\n'.encode('utf-16-le'))
        self.restore_quietly()
        self.assertEqual(ini.read_bytes(), original + 'Saved=1\r\n'.encode('utf-16-le'))

    def test_unreadable_settings_file_never_fails_install_or_configure(self):
        self.renderer.write_bytes(b'{"m_eDLSSFGMode": 0, "name": "Jos\xe9"}')  # not UTF-8
        out = self.install_quietly()
        self.assertIn('Game setting pending: AppData/Local/Remedy/Test/renderer.ini m_eDLSSFGMode=1 (cannot read it (not UTF-8', out)
        self.assertEqual(self.record()['status'], 'installed')
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()) as configured:
                self.m.configure(self.exe, factor=3)
            self.assertIn('Game setting pending: AppData/Local/Remedy/Test/renderer.ini m_eDLSSFGMode=1 (cannot read it', configured.getvalue())
        self.renderer.write_bytes(RENDERER)
        with contextlib.redirect_stdout(io.StringIO()) as configured:
            self.m.configure(self.exe)
        self.assertIn('Game setting applied', configured.getvalue())
        self.restore_quietly()
        self.assertEqual(self.renderer.read_bytes(), RENDERER)  # (OptiScaler.ini keeps the multiplier chosen above)

    def test_missing_keys_named_at_configure(self):
        self.renderer.write_bytes(b'{"m_eWindowMode": 1}')
        self.install_quietly()
        with contextlib.redirect_stdout(io.StringIO()) as configured:
            self.m.configure(self.exe)
        self.assertIn('renderer.ini m_eDLSSFGMode=1 (not in the file yet: m_eDLSSFGMode', configured.getvalue())

    def test_native_recipe_settings_skipped_on_optiscaler_route(self):
        self.recipes(dict(title='Test Game', match=dict(exe=['game.exe'], steam=['4242']), status='verified-bc250', route='native',
                          fg_input=None, ini={'FrameGen.FTInput': '2'}, launch_args=[], game_settings=[dict(
                          file='AppData/Local/Remedy/Test/renderer.ini', base='steamuser', format='json', section=None,
                          values={'m_eDLSSFGMode': 1}, requires_fg_input=None)]))
        self.install_quietly(fg_input='upscaler')
        self.assertEqual(self.renderer.read_bytes(), RENDERER)
        self.assertEqual(self.record()['game_settings'], [])
        self.assertNotIn(('framegen', 'ftinput'), self.current_ini())

    def test_user_api_argument_wins(self):
        self.original_config = self.original_config.replace(b'--skip-intro', b'-dx11')
        self.config.write_bytes(self.original_config)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.m.install(self.package, self.exe, route='opti', fg_input='dlssg')
        self.assertNotIn('-dx12', self.options())
        # Said as it is: the recipe's switch was not added (0.9.0 printed "Launch option added: -dx12").
        self.assertNotIn('Launch option added', out.getvalue())
        self.assertIn('Launch option not added: -dx12', out.getvalue())
        self.assertEqual(self.record()['launch_args_added'], [])
        self.m.restore(self.exe)
        self.assertOriginal()

    def test_quirk_key_left_auto(self):
        self.recipes(None, leave_auto={'game.exe': [dict(key='fakenvapi.UseFakenvapi', quirk='DisableFakenvapi', value='false')]})
        self.m.install(self.package, self.exe, route='opti', fg_input='upscaler')
        self.assertNotIn(('fakenvapi', 'usefakenvapi'), self.current_ini())
        self.assertEqual(self.current_ini()[('fakenvapi', 'forcereflex')], '2')
        self.m.restore(self.exe)
        self.assertOriginal()

    def test_extra_args_from_caller(self):
        self.recipes(None)
        self.m.install(self.package, self.exe, route='opti', fg_input='upscaler', extra_args=['-force-d3d12'])
        self.assertTrue(self.options().endswith('--skip-intro -force-d3d12'))
        self.m.restore(self.exe)
        self.assertOriginal()

    def test_extra_api_argument_replaces_the_recipes(self):
        self.install_quietly(extra_args=['-force-d3d12'])  # the recipe asks for -dx12
        self.assertTrue(self.options().endswith('--skip-intro -force-d3d12'))
        self.assertNotIn('-dx12', self.options().split())
        self.assertEqual(self.record()['launch_args'], ['-force-d3d12'])
        self.restore_quietly()
        self.assertOriginal()

    def test_automatic_input_follows_recipe(self):
        calls = []
        found = self.m.recipe_for(self.package, self.exe)
        self.assertEqual(found[1]['fg_input'], 'dlssg')
        with patch.object(self.m, 'install', side_effect=lambda *a, **k: calls.append(a[3:5])), \
             patch.object(self.m, 'recipe_for', return_value=found), \
             patch.object(sys, 'argv', ['install.py', 'install', str(self.exe)]):
            self.m.main()
        self.assertEqual(calls, [('opti', 'dlssg')])


class CompactRecipeTests(unittest.TestCase):
    """packaging/recipes/recipes-runtime.json, the compact file a package ships as recipes/recipes.json, against the full
    provenance file it is built from: every game the full file knows resolves to the same installer decisions."""
    ROOT = Path(__file__).resolve().parents[1]
    FULL = ROOT/'packaging/recipes/recipes.json'
    COMPACT = ROOT/'packaging/recipes/recipes-runtime.json'
    INPUTS = ('upscaler', 'dlssg', 'fsrfg', 'fsrfg30')

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_recipes', cls.ROOT/'research/recipes/build_recipes.py')
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)
        import test_game_install
        cls.installer = test_game_install.m
        cls.full, cls.compact = r.load(cls.FULL), r.load(cls.COMPACT)

    def test_compact_file_is_built_from_the_full_file(self):
        import hashlib
        raw = self.FULL.read_bytes()
        built = json.dumps(self.builder.compact(json.loads(raw), hashlib.sha256(raw).hexdigest()), ensure_ascii=False,
                           separators=(',', ':')) + '\n'
        self.assertEqual(self.COMPACT.read_text(), built, 'stale: run research/recipes/build_recipes.py --compact')
        self.assertLess(len(self.COMPACT.read_bytes()), len(raw) // 2)
        self.assertLess(len(self.COMPACT.read_bytes()), 256 * 1024)  # the runtime file's budget

    def test_both_loaders_give_every_build_its_keys(self):
        self.assertEqual(self.compact['optiscaler_builds'], self.full['optiscaler_builds'])
        self.assertNotIn('optiscaler_ini_keys', self.compact)
        self.assertTrue(all(len(b['keys']) > 300 for b in self.compact['optiscaler_builds'].values()))

    @staticmethod
    def ids(exe, steam=(), gog=(), epic=(), titles=(), folders=()):
        return dict(exe=exe, steam=set(steam), gog=set(gog), epic=set(epic), titles=set(titles), folders=set(folders))

    def identities(self):
        """Every way a game in the full file can be matched, plus one game it does not know."""
        out = [self.ids('unknown.exe'), self.ids('unknown.exe', titles=['unknown game'])]
        for v in self.full['verified']:
            m = v['match']
            stores = dict(steam=m.get('steam', []), gog=m.get('gog', []), epic=m.get('epic', []))
            for exe in m.get('exe', []):
                out += [self.ids(exe, **stores), self.ids(exe, titles=[r.norm(v['title'])]), self.ids(exe, folders=[r.norm(v['title'])]),
                        self.ids(exe)]
            out.append(self.ids('launcher.exe', **stores))
        for w in self.full['wiki']:
            out += [self.ids('game.exe', titles=[t]) for t in w['match'].get('title', [])]
            out += [self.ids(exe) for exe in w['match'].get('exe', [])]
        out += [self.ids(exe) for exe in [*self.full['leave_auto'], *self.full['backports']]]
        return out

    def user_dir(self, base):
        """A Proton user folder holding every verified game's settings files, each with other values than the recipe's."""
        for v in self.full['verified']:
            for s in v['game_settings']:
                keys = list(s['values'])
                text = {'json': lambda: json.dumps({k: 0 for k in keys}),
                        'json-options': lambda: json.dumps({'data': [{'options': [{'name': k, 'value': 0} for k in keys]}]}),
                        'xml-option': lambda: '<Options>' + ''.join(f'<Option Name="{k}" _value="0"/>' for k in keys) + '</Options>',
                        }.get(s['format'], lambda: (f"[{s['section']}]\n" if s['section'] else '') + ''.join(f'{k}=0\n' for k in keys))()
                path = base/s['file']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        return base

    def resolve(self, data, ids, user):
        """What the installer and the library owner take from a recipe file for one game."""
        verified, wiki, leave, backports = r.match(data, ids)
        out = dict(verified=verified and dict(title=verified['title'], route=verified['route'], fg_input=verified.get('fg_input'),
                                              exe=verified.get('match', {}).get('exe'), settings=bool(verified.get('game_settings'))),
                   wiki=[w['title'] for w in wiki], leave=[(i['key'], i['quirk']) for i in leave],
                   launch_args=r.launch_args(verified, wiki))
        for route in ('native', 'opti'):
            for fg_input in self.INPUTS:
                plan = r.settings_plan(verified, user, route, fg_input if route == 'opti' else None)
                out[route + '/' + fg_input] = dict(
                    ini=sorted(r.ini_changes(verified, backports, {}, fg_input, (verified or {}).get('fg_input'), route).items()),
                    upscaler_ini={u:sorted(r.ini_changes(verified,backports,{},fg_input,(verified or {}).get('fg_input'),route,u).items())
                                  for u in ('fsr4','helixsr')},
                    suggestions=r.suggestions(verified, wiki, fg_input, route),
                    settings=[(self.installer.settings_record(item), item['reason']) for item in plan])
        return out

    def test_every_game_resolves_alike(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = self.user_dir(Path(tmp))
            identities = self.identities()
            self.assertGreaterEqual(len(identities), len(self.full["wiki"]) + len(self.full["verified"]))
            applied = 0
            for ids in identities:
                for folder in (None, user):
                    full = self.resolve(self.full, ids, folder)
                    self.assertEqual(self.resolve(self.compact, ids, folder), full, ids)
                    applied += sum(1 for k, v in full.items() if '/' in k for s, _ in v['settings'] if s['status'] == 'applied')
            self.assertGreater(applied, 0)  # the settings fixture exercised real edits, not only pending ones

    def test_library_owner_inputs_alike(self):
        # The maintainers' library tool (its mfg_inputs) reads verified[].match (steam/gog/epic), route and fg_input.
        def inputs(data):
            return {prefix + i: (v['route'], v.get('fg_input') or 'native') for v in data['verified']
                    for key, prefix in (('steam', ''), ('gog', 'gog-'), ('epic', 'epic-')) for i in v['match'].get(key, [])}
        self.assertEqual(inputs(json.loads(self.COMPACT.read_text())), inputs(json.loads(self.FULL.read_text())))
        self.assertEqual(len(inputs(self.full)), len(self.full['verified']))

    def test_installer_reads_the_compact_file_from_a_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package/'recipes').mkdir()
            (package/'recipes/recipes.json').write_bytes(self.COMPACT.read_bytes())
            exe = package/'game/Game.exe'
            exe.parent.mkdir()
            exe.write_bytes(b'MZ')
            control = next(v for v in self.full['verified'] if v['title'] == 'CONTROL Resonant')
            with patch.object(self.installer, 'recipes_module', return_value=r), \
                 patch.object(r, 'identity', return_value=self.ids(control['match']['exe'][0], steam=control['match']['steam'])), \
                 patch.object(l, 'discover', return_value=[]):
                found = self.installer.recipe_for(package, exe)
            self.assertEqual(found[1]['title'], 'CONTROL Resonant')
            self.assertEqual(found[1]['fg_input'], 'dlssg')



class GtaQualificationTests(unittest.TestCase):
    def test_recipe_identity_preserves_anticheat_refusal_and_other_rows(self):
        import compat
        from test_compat import scan, ids
        root = Path(__file__).resolve().parents[1]
        data = r.load(root/'packaging/recipes/recipes.json')
        entry = next(v for v in data['verified'] if '3240220' in v['match'].get('steam', []))
        self.assertEqual(entry, json.loads((root/'research/recipes/verified/gta-v-enhanced.json').read_text()))
        self.assertEqual((entry['launch_args'], r.required_args(entry)), ([], ['-nobattleye']))
        self.assertTrue(any('GTA Online' in step for step in entry['manual_steps']))  # Restore first: BattlEye
        runtime = r.load(root/'packaging/recipes/recipes-runtime.json')
        self.assertEqual(r.required_args(next(v for v in runtime['verified'] if '3240220' in v['match'].get('steam', []))), ['-nobattleye'])
        self.assertEqual(len(data['verified']), 20)
        self.assertEqual(sum(len(w.get('promoted', [])) for w in data['wiki']), 6)
        identity = ids('gta5_enhanced.exe', ('3240220',), ('grand theft auto v',))
        verdict = compat.decide(scan(exe=dict(name='GTA5_Enhanced.exe'),
            anticheat=[dict(name='BattlEye', evidence=['BattlEye/BEClient_x64.cfg'])]), data, identity)
        self.assertTrue(any(item['code']=='anticheat' for item in verdict['blocking']))
        self.assertEqual(verdict['fg_input'], 'upscaler')
        self.assertEqual(verdict['launch_args'], [])  # no API switch; -nobattleye is required, not an API choice
        self.assertNotIn(('Spoofing','DxgiFactoryWrapping'), verdict['ini'])
        self.assertIsNone(r.match(data, ids('gta5.exe', ('271590',), ('grand theft auto v',)))[0])

if __name__ == '__main__':
    unittest.main()
