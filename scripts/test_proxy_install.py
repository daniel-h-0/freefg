# SPDX-License-Identifier: MIT
"""Installer transactions on a fixture enabler-free package (manifest addon_entry "libxess_fg-proxy", variant intel-free-2x):
the add-on is payload/libxess_fg.dll, Intel's runtime comes from the pinned downloads as bc250_xefg_original.dll
(dependencies.json runtime.ProxyPackage), there is no XeSSMFG enabler or version.dll, and the package is 2x only."""
import contextlib,io,json,os,shlex,unittest
from pathlib import Path
from unittest.mock import patch
from test_game_install import GameFixture,DEPENDENCIES,set_package_file,pins_for,heroic,m

PROXY_PACKAGE={'fsr4/'+m.DLL:'fsr4/'+m.DLL,'payload/bc250_xefg_original.dll':'OptiScaler/libxess_fg.dll','payload/libxell.dll':'OptiScaler/libxell.dll'}
PROXY_FILES={'payload/libxess_fg.dll':b'BC250 proxy','payload/BC250-XeFG/settings.ini':b'[BC250]\nResolutionMode=0\n',
             'payload/BC250-XeFG/shaders/waves.txt':b'wave config','payload/BC250-XeFG/shaders/winograd.required':b'3\n'}

class ProxyFixture(GameFixture):
    """GameFixture with its package turned into an enabler-free one: same game, launcher and pinned files."""
    def setUp(self):
        super().setUp()
        manifest=json.loads((self.package/'manifest.json').read_text())
        for name in list(manifest['files']):
            if name.startswith('payload/'):(self.package/name).unlink();del manifest['files'][name]
        manifest.update(addon_entry=m.PROXY_ENTRY,max_factor=2);(self.package/'manifest.json').write_text(json.dumps(manifest))
        pins=pins_for(DEPENDENCIES);pins['runtime']['ProxyPackage']=dict(PROXY_PACKAGE)
        set_package_file(self.package,'dependencies.json',json.dumps(pins).encode())
        for name,data in PROXY_FILES.items():set_package_file(self.package,name,data)
    def opti_ini(self):
        return m.read_ini((self.game/'OptiScaler.ini').read_bytes())
    def record(self):
        return json.loads((self.game/m.STATE/'state.json').read_text())

class ProxyInstallTests(ProxyFixture):
    def test_upgrade_repairs_saved_fg_and_latency_paths_without_losing_custom_sr_paths(self):
        original=self.original['OptiScaler.ini']
        for route in ['native','opti']:
            for path in [r'.\libxess_fg.dll',r'.\libxell.dll','CUSTOM/LIBXESS_FG.DLL',r'custom\real-upscaler.dll']:
                with self.subTest(route=route,path=path):
                    before=m.patch_ini(original,{('Libraries','XeSSPath'):path})
                    self.original['OptiScaler.ini']=before
                    (self.game/'OptiScaler.ini').write_bytes(before)
                    m.install(self.package,self.exe,route=route)
                    expected=path if 'real-upscaler' in path else 'auto'
                    self.assertEqual(self.opti_ini()[('libraries','xesspath')],expected)
                    self.assertEqual(self.opti_ini()[('libraries','xefgpath')],r'.\libxess_fg.dll')
                    self.assertEqual(self.opti_ini()[('libraries','xellpath')],r'.\libxell.dll')
                    m.restore(self.exe);self.assertOriginal()

    def test_configure_repairs_saved_path_and_keeps_factor_and_unrelated_keys(self):
        m.install(self.package,self.exe,route='opti')
        ini=self.game/'OptiScaler.ini'
        ini.write_bytes(m.patch_ini(ini.read_bytes(),{('Libraries','XeSSPath'):r'.\libxess_fg.dll',('Other','Keep'):'yes'}))
        m.configure(self.exe,factor=2)
        values=self.opti_ini()
        self.assertEqual(values[('libraries','xesspath')],'auto')
        self.assertEqual(values[('xefg','interpolationcount')],'1')
        self.assertEqual(values[('other','keep')],'yes')
        self.assertIn(dict(section='Libraries',key='XeSSPath',value='auto'),self.record()['ini_changes'])
        # A later genuine SR override is still the user's; configure and Restore leave it alone.
        ini.write_bytes(m.patch_ini(ini.read_bytes(),{('Libraries','XeSSPath'):'custom/real-upscaler.dll'}))
        m.configure(self.exe)
        m.restore(self.exe)
        self.assertEqual(self.opti_ini()[('libraries','xesspath')],'custom/real-upscaler.dll')
        self.assertEqual(self.opti_ini()[('other','keep')],'yes')

    def test_opti_roundtrip(self):
        m.install(self.package,self.exe,route='opti')
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'BC250 proxy')
        self.assertEqual((self.game/'bc250_xefg_original.dll').read_bytes(),b'Intel FG')
        self.assertEqual((self.game/'libxell.dll').read_bytes(),b'new LL')
        self.assertEqual((self.game/'BC250-XeFG/shaders/waves.txt').read_bytes(),b'wave config')
        for absent in ['version.dll','XeSSMFG','OptiScaler/plugins/BC250-MFG.asi','OptiScaler/libxess_fg.dll','OptiScaler/libxell.dll']:
            self.assertFalse((self.game/absent).exists(),absent)
        ini=self.opti_ini()
        self.assertEqual(ini[('libraries','xefgpath')],r'.\libxess_fg.dll');self.assertEqual(ini[('xefg','interpolationcount')],'1')
        self.assertNotIn(('plugins','loadasiplugins'),ini)  # no OptiScaler plugin to load
        env=self.env()
        self.assertEqual(env['WINEDLLOVERRIDES'],'dxgi=n,b')  # no version.dll loader
        self.assertEqual(env['XEFG_WAVE_CONFIG'],str(self.game.resolve()/'BC250-XeFG/shaders/waves.txt'))
        self.assertEqual(env['VK_LAYER_PATH'],str(self.game.resolve()/'BC250-XeFG/layer'))
        self.assertNotIn('BC250_XEFG_OWNER_MODULE',env)
        record=self.record();self.assertEqual((record['addon_entry'],record['max_factor'],record['runtime']),(m.PROXY_ENTRY,2,'xemfg'))
        # The proxy writes its logs beside it; Restore keeps them with the backups.
        for name in m.PROXY_LOGS:(self.game/name).write_text('log '+name)
        m.restore(self.exe);self.assertOriginal()
        for name in ['libxess_fg.dll','libxell.dll']:self.assertEqual((self.game/name).read_bytes(),self.original[name])
        for name in ['bc250_xefg_original.dll',*m.PROXY_LOGS]:self.assertFalse((self.game/name).exists(),name)
        self.assertFalse((self.game/'BC250-XeFG').exists())  # created by the installation: removed once empty
        kept=list((self.game/m.STATE).glob('runtime-logs-*/BC250-XeFG-fast.log'))
        self.assertEqual(len(kept),1);self.assertEqual(kept[0].read_text(),'log BC250-XeFG-fast.log')
    def test_an_earlier_log_is_set_aside_and_put_back(self):
        # The lib2x add-on wrote BC250-XeFG-fast.log in the game folder (Cyberpunk, Sep 27): the proxy's log of the
        # same name never overwrites it, and Restore takes only the proxy's own logs.
        earlier=self.game/'BC250-XeFG-fast.log';earlier.write_text('lib2x log');os.utime(earlier,(1758950000,1758950000))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,preview=True,route='opti')
        self.assertIn('Set aside until Restore: BC250-XeFG-fast.log',out.getvalue());self.assertEqual(earlier.read_text(),'lib2x log')
        m.install(self.package,self.exe,route='opti')
        self.assertFalse(earlier.exists());self.assertEqual(self.record()['displaced_logs'],['BC250-XeFG-fast.log'])
        self.assertEqual((self.game/m.STATE/'displaced-logs/BC250-XeFG-fast.log').read_text(),'lib2x log')
        for name in m.PROXY_LOGS:(self.game/name).write_text('proxy '+name)
        m.restore(self.exe);self.assertOriginal()
        self.assertEqual(earlier.read_text(),'lib2x log');self.assertEqual(earlier.stat().st_mtime,1758950000)
        self.assertFalse((self.game/'BC250-MFG.log').exists());self.assertFalse((self.game/m.STATE/'displaced-logs').exists())
        logs={p.name:p.read_text() for p in (self.game/m.STATE).glob('runtime-logs-*/*')}
        self.assertEqual(logs,{name:'proxy '+name for name in m.PROXY_LOGS})
        # The game never ran: the earlier log comes back the same, and there is nothing of the proxy's to keep.
        m.install(self.package,self.exe,route='opti');m.restore(self.exe)
        self.assertEqual(earlier.read_text(),'lib2x log');self.assertEqual(len(list(self.game.glob(m.STATE+'*/runtime-logs-*'))),1)
    def test_a_log_never_set_aside_is_left_alone(self):
        # An installation interrupted before it set the earlier log aside: the log in the game folder is still the
        # earlier one, so Restore leaves it.
        earlier=self.game/'BC250-XeFG-fast.log';earlier.write_text('lib2x log')
        m.install(self.package,self.exe,route='opti')
        os.replace(self.game/m.STATE/'displaced-logs/BC250-XeFG-fast.log',earlier)
        m.restore(self.exe);self.assertEqual(earlier.read_text(),'lib2x log')
        self.assertEqual(list((self.game/m.STATE).glob('runtime-logs-*')),[])
    def test_an_enabler_folder_it_did_not_create_is_left_alone(self):
        # A proxy installation places nothing in XeSSMFG/ (it refuses a game that has one): one there at Restore is
        # another tool's, with its logs.
        m.install(self.package,self.exe,route='opti')
        m.write(self.game/'XeSSMFG/XeSSMFG.log',b'enabler log')
        m.restore(self.exe);self.assertOriginal()
        self.assertEqual((self.game/'XeSSMFG/XeSSMFG.log').read_bytes(),b'enabler log')
    def test_optiscaler_resave_after_an_earlier_restore_round_trips(self):
        # The live check's case (Echo Point Nova, Oct 18): an INI OptiScaler saved ('key = value'), with one line an
        # earlier Restore wrote back as 'key=value'. OptiScaler saves again while the game runs; Restore gives back
        # the INI as it was before the installation, both spacings included.
        ini=self.game/'OptiScaler.ini'
        mixed=(b'; OptiScaler\n[Upscalers]\nDx12Upscaler = xess\n\n[FSR]\nFsr4EnableWatermark = true\n\n[FrameGen]\nEnabled = auto\n'
               b'\n[XeFG]\nForceBorderless = auto\n\n[Plugins]\nLoadAsiPlugins=true\n')
        ini.write_bytes(mixed);self.original['OptiScaler.ini']=mixed
        m.install(self.package,self.exe,route='opti')
        installed=ini.read_bytes();self.assertIn(b'\nLoadAsiPlugins=true\n',installed);self.assertIn(b'\nForceBorderless = true\n',installed)
        self.assertIn(b'\nInterpolationCount = 1\n',installed)
        ini.write_bytes(installed.replace(b'LoadAsiPlugins=true',b'LoadAsiPlugins = true'))  # OptiScaler's save
        m.restore(self.exe);self.assertOriginal()
    def test_native_route_replaces_and_restores_the_games_runtime(self):
        m.install(self.package,self.exe,route='native')
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'BC250 proxy')
        self.assertEqual((self.game/'bc250_xefg_original.dll').read_bytes(),b'Intel FG')
        self.assertNotIn(('xefg','interpolationcount'),self.opti_ini())  # the game asks for its frames itself
        m.restore(self.exe);self.assertOriginal();self.assertFalse((self.game/'bc250_xefg_original.dll').exists())
    def test_two_times_only(self):
        # A count chosen for an enabler build (3x/4x) would ask Intel's runtime for frames it does not generate here.
        ini=self.game/'OptiScaler.ini';ini.write_bytes(m.patch_ini(ini.read_bytes(),{('XeFG','InterpolationCount'):'3'}));before=ini.read_bytes()
        m.install(self.package,self.exe,route='opti');self.assertEqual(self.opti_ini()[('xefg','interpolationcount')],'1')
        for factor in [3,4]:
            with self.assertRaisesRegex(ValueError,'2× only'):m.configure(self.exe,factor)
        self.assertEqual(self.opti_ini()[('xefg','interpolationcount')],'1')
        m.configure(self.exe,2);self.assertEqual(self.opti_ini()[('xefg','interpolationcount')],'1')
        with self.assertRaisesRegex(ValueError,'new scaling-controls build'):m.configure(self.exe,percent=70)
        m.restore(self.exe);self.assertEqual(ini.read_bytes(),before)
    def test_messages_carry_no_private_wording(self):
        # The public package shares this installer: what it prints for an enabler-free package names neither the
        # internal product name nor the enabler of the private builds.
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            m.install(self.package,self.exe,route='opti')
            with self.assertRaises(ValueError) as refused:m.configure(self.exe,3)
            m.restore(self.exe)
        text=out.getvalue()+str(refused.exception)
        self.assertIn('2× only',str(refused.exception))
        # The internal name written in pieces, so that the rename scan does not list this test.
        for word in ['Xe'+'MFG','XeSSMFG enabler','Private','tester']:self.assertNotIn(word,text)
    def test_fresh_reinstall_does_not_carry_a_multiplier(self):
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        ini=self.game/'OptiScaler.ini';ini.write_bytes(m.patch_ini(ini.read_bytes(),{('XeFG','InterpolationCount'):'3',('fakenvapi','ForceReflex'):'0'}))
        m.restore(self.exe);m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        values=self.opti_ini();self.assertEqual(values[('xefg','interpolationcount')],'1');self.assertEqual(values[('fakenvapi','forcereflex')],'0')
        self.assertEqual(self.env()['WINEDLLOVERRIDES'],'dxgi=n,b')
        m.restore(self.exe);self.assertFalse(ini.exists())
    def test_reinstall_keeps_the_exact_switch(self):
        # 1.1.2: the package's settings.ini (release/files/BC250-XeFG-settings.ini) ships Exact=0, F4Q=1 and F4Q2=1, so a
        # user's Exact=1 (output identical to Intel's in every test) and F4Q2=0 are carried across Restore and Install,
        # and stay the installation's baseline through a later untouched cycle.
        shipped=(Path(__file__).resolve().parents[1]/'release/files/BC250-XeFG-settings.ini').read_bytes()
        self.assertIn(b'\nExact=0\n',shipped);set_package_file(self.package,'payload/BC250-XeFG/settings.ini',shipped)
        settings=self.game/'BC250-XeFG/settings.ini';read=lambda:m.read_ini(settings.read_bytes())
        m.install(self.package,self.exe,route='opti');self.assertEqual(read()[('bc250','exact')],'0')
        settings.write_bytes(m.patch_ini(settings.read_bytes(),{('BC250','Exact'):'1',('BC250','F4Q2'):'0'}))
        for cycle in (1,2):
            with self.subTest(cycle=cycle):
                m.restore(self.exe);m.install(self.package,self.exe,route='opti')
                self.assertEqual((read()[('bc250','exact')],read()[('bc250','f4q2')],read()[('bc250','f4q')]),('1','0','1'))
        m.restore(self.exe);self.assertFalse(settings.exists())
    def test_fresh_setup_loads_optipatcher(self):
        # A fresh setup places OptiPatcher (dependencies.json payload) and must let OptiScaler load it: the pinned INI's
        # LoadAsiPlugins=auto means false, which left OptiPatcher unloaded in 0.9.0's proxy packages.
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertTrue((self.game/'OptiScaler/plugins/OptiPatcher.asi').is_file())
        self.assertEqual(self.opti_ini()[('plugins','loadasiplugins')],'true')
        self.assertIn(dict(section='Plugins',key='LoadAsiPlugins',value='true'),self.record()['ini_changes'])
        m.restore(self.exe);self.assertFalse((self.game/'OptiScaler.ini').exists())
        self.assertFalse((self.game/'OptiScaler/plugins/OptiPatcher.asi').exists())
    def test_fresh_setup_keeps_an_explicit_plugin_choice(self):
        # A pinned INI that already says something other than auto is OptiScaler's own choice: left alone.
        pins=json.loads((self.package/'dependencies.json').read_text());ini=b'[Plugins]\nLoadAsiPlugins=false\n'
        m.write(self.deps/'OptiScaler.ini',ini);pins['payload']['Files']['OptiScaler.ini']=m.digest(ini)
        set_package_file(self.package,'dependencies.json',json.dumps(pins).encode())
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual(self.opti_ini()[('plugins','loadasiplugins')],'false');m.restore(self.exe)
    def test_another_mods_version_dll_is_left_alone(self):
        (self.game/'version.dll').write_bytes(b'other mod')
        m.install(self.package,self.exe,route='opti');self.assertEqual((self.game/'version.dll').read_bytes(),b'other mod')
        m.restore(self.exe);self.assertEqual((self.game/'version.dll').read_bytes(),b'other mod')
    def test_leftover_enabler_folder_still_refused(self):
        (self.game/'XeSSMFG').mkdir()
        with self.assertRaisesRegex(ValueError,'XeSSMFG folder'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists())
    def test_status_reads_the_game_folder_log(self):
        m.install(self.package,self.exe,route='opti')
        (self.game/'BC250-MFG.log').write_text("MFG proxy ready: Intel's XeFG runtime unmodified beside it\nFAST_OWNER first initialized context selected\n")
        (self.game/'BC250-XeFG-fast.log').write_text('INTEL_FREE own shaders only\nWINOGRAD_EXECUTE shader=fec421a3b6a0632b channels=224 clamp=16\n'
                                                     +''.join(f'REPLACE {i:016x} 56888\n' for i in range(13)))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        text=out.getvalue()
        self.assertIn('Last log: '+str(self.game.resolve()/'BC250-XeFG-fast.log')+' (no FAIL marker)',text)
        # One statement of how much was accelerated (the stage count of earlier builds is not repeated beside it).
        self.assertIn("Last run: Acceleration: full (this build's shaders ran on 13 of 13 programs).",text)
        self.assertNotIn('stages',text)
        # The next session accelerated nothing (BC250-MFG.log is new, without FAST_OWNER; the fast log is the earlier one).
        (self.game/'BC250-MFG.log').write_text("MFG proxy ready: Intel's XeFG runtime unmodified beside it\nMFG_FACTOR context initialised for up to 2x\n")
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        text=out.getvalue()
        self.assertIn('Last log: '+str(self.game.resolve()/'BC250-XeFG-fast.log')+' (from an earlier session: the last session accelerated nothing)',text)
        self.assertIn('Last run: Acceleration: none (no acceleration log from this session).',text)
        self.assertNotIn('full',text)
        m.restore(self.exe)
    def test_status_ignores_logs_from_before_the_installation(self):
        # Live check of 2026-10-21: before the first start, Status reported an older private test build's logs under
        # OptiScaler/ (16 and 19 programs) as the last run. This build's logs are beside the .exe and newer than the install.
        old_fast=''.join(f'REPLACE {i:016x} 56888\n' for i in range(16))
        m.write(self.game/'OptiScaler/plugins/BC250-MFG.log',b'MFG addon ready\nFAST_OWNER first initialized context selected\n')
        m.write(self.game/'OptiScaler/plugins/BC250-XeFG-fast.log',old_fast.encode())
        m.write(self.game/'OptiScaler/BC250-XeFG-fast.log',old_fast.encode())
        m.install(self.package,self.exe,route='opti')
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertIsInstance(record.get('installed_at'),float)
        # An OptiScaler.log beside the .exe from a session before the installation (Restore of an earlier build leaves it).
        (self.game/'OptiScaler.log').write_text('[I] XeFG swapchain created\n')
        past=record['installed_at']-60
        for name in ('OptiScaler.log','OptiScaler/plugins/BC250-MFG.log','OptiScaler/plugins/BC250-XeFG-fast.log','OptiScaler/BC250-XeFG-fast.log'):
            os.utime(self.game/name,(past,past))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        text=out.getvalue()
        self.assertIn('No acceleration log yet.',text)
        self.assertNotIn('Acceleration:',text)
        self.assertNotIn('16 programs',text)
        self.assertNotIn('swap chain created',text)
        # The first session of this build: its logs beside the .exe are read.
        (self.game/'BC250-MFG.log').write_text("MFG proxy ready: Intel's XeFG runtime unmodified beside it\nFAST_OWNER first initialized context selected\n")
        (self.game/'BC250-XeFG-fast.log').write_text(''.join(f'REPLACE {i:016x} 56888\n' for i in range(13)))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        self.assertIn("Last run: Acceleration: full (this build's shaders ran on 13 of 13 programs).",out.getvalue())
        m.restore(self.exe)
    def test_status_names_mfg_unlocker_cases(self):
        # MFG Unlocker's plugin with XeFGModel unset: Status says so before any run; after a partial run it says it once.
        m.install(self.package,self.exe,route='opti')
        ini=self.game/'OptiScaler.ini';ini.write_bytes(m.patch_ini(ini.read_bytes(),{('XeFG','XeFGModel'):None}))
        m.write(self.game/'OptiScaler/plugins/MFGUnlocker.asi',b'placeholder')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        self.assertIn('MFG Unlocker (OptiScaler/plugins/MFGUnlocker.asi) is in this game folder and XeFGModel is not set',out.getvalue())
        (self.game/'BC250-MFG.log').write_text("MFG proxy ready\nFAST_COEXIST another module hooks Intel's XeFG runtime (x: y; jumps to MFGUnlocker.asi): z\n"
                                               'FAST_OWNER first initialized context selected\n')
        (self.game/'BC250-XeFG-fast.log').write_text(''.join(f'REPLACE {i:016x} 56888\n' for i in range(7)))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        text=out.getvalue()
        self.assertIn("Last run: Acceleration: partial (this build's shaders ran on 7 of 13 programs): MFG Unlocker's own model replaced the rest.",text)
        self.assertEqual(text.count('set XeFGModel=default'),1)
        (self.game/'OptiScaler/plugins/MFGUnlocker.asi').unlink()
        m.restore(self.exe)
    def test_xefg_model_written_kept_and_restored(self):
        # MFG Unlocker reads [XeFG] XeFGModel (no OptiScaler build does); unset, on its own model this build's shaders
        # run on 7 of their 13 programs. Every route writes default where the INI has no value (absent, empty, auto);
        # a value the user wrote stays; Restore gives back the INI byte for byte, and keeps edits made since.
        ini=self.game/'OptiScaler.ini'
        model=lambda:self.opti_ini().get(('xefg','xefgmodel'))
        for route in ['opti','native']:
            for start in [None,'','auto','Auto']:
                with self.subTest(route=route,start=start):
                    original=self.ini if start is None else m.patch_ini(self.ini,{('XeFG','XeFGModel'):start})
                    ini.write_bytes(original)
                    m.install(self.package,self.exe,route=route);self.assertEqual(model(),'default')
                    self.assertIn(dict(section='XeFG',key='XeFGModel',value='default'),self.record()['ini_changes'])
                    m.restore(self.exe);self.assertEqual(ini.read_bytes(),original)
            with self.subTest(route=route,start='xess'):
                original=m.patch_ini(self.ini,{('XeFG','XeFGModel'):'xess'});ini.write_bytes(original)
                m.install(self.package,self.exe,route=route);self.assertEqual(model(),'xess')
                self.assertNotIn('XeFGModel',[c['key'] for c in self.record()['ini_changes']])
                m.restore(self.exe);self.assertEqual(ini.read_bytes(),original)
            with self.subTest(route=route,start='edited later'):
                ini.write_bytes(self.ini);m.install(self.package,self.exe,route=route)
                ini.write_bytes(m.patch_ini(ini.read_bytes(),{('Unrelated','Value'):'edited'}))
                m.restore(self.exe);values=self.opti_ini()
                self.assertNotIn(('xefg','xefgmodel'),values);self.assertEqual(values[('unrelated','value')],'edited')
        ini.write_bytes(self.ini)
    def test_fresh_reinstall_carries_a_users_xefg_model(self):
        # A fresh OptiScaler setup's INI goes with Restore (saved as preserved_ini): the next Install writes default again
        # without calling it the user's, and keeps a model the user chose, once.
        deps=self.fresh();ini=self.game/'OptiScaler.ini'
        m.install(self.package,self.exe,route='opti',dependency_dir=deps);self.assertEqual(self.opti_ini()[('xefg','xefgmodel')],'default')
        m.restore(self.exe);self.assertFalse(ini.exists())
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual(self.opti_ini()[('xefg','xefgmodel')],'default');self.assertNotIn('XeFGModel',out.getvalue())
        ini.write_bytes(m.patch_ini(ini.read_bytes(),{('XeFG','XeFGModel'):'xess'}))
        m.restore(self.exe);out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual(self.opti_ini()[('xefg','xefgmodel')],'xess');self.assertEqual(ini.read_bytes().lower().count(b'xefgmodel'),1)
        self.assertIn('OptiScaler.ini XeFG.XeFGModel=xess',out.getvalue())
        m.restore(self.exe);self.assertFalse(ini.exists())
    def user_env(self,values):
        """The fixture's Heroic entry with the user's own variables added before installation."""
        doc=json.loads(self.config.read_text());doc['123']['enviromentOptions']+=[dict(key=k,value=v) for k,v in values.items()]
        m.write(self.config,json.dumps(doc).encode())
        self.original_config=json.loads(self.config.read_text());self.original_config_bytes=self.config.read_bytes()
    def test_vkd3d_cache_is_the_installations_own_and_restore_removes_it(self):
        # 1.1.1 (W32-2): vkd3d-proton caches SPIR-V (shader module identifiers off) in a new folder in the state folder,
        # so the layer names every pipeline on every start; Restore puts the user's variables back and deletes the cache.
        nvx='VK_NVX_binary_import,VK_NVX_image_view_handle';self.user_env(dict(VKD3D_DISABLE_EXTENSIONS=nvx))
        cache=self.game.resolve()/m.STATE/m.VKD3D_CACHE
        for attempt in (1,2):  # install, Restore, install again: the same variables, a new empty folder
            with self.subTest(attempt=attempt):
                out=io.StringIO()
                with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti')
                self.assertIn('shader cache in '+str(cache)+': the first start fills it',out.getvalue())
                self.assertTrue(cache.is_dir());self.assertEqual(list(cache.iterdir()),[])
                env=self.env();self.assertEqual(self.record()['vkd3d_cache'],m.VKD3D_CACHE)
                self.assertEqual((env['VKD3D_SHADER_CACHE_PATH'],env['VKD3D_DISABLE_EXTENSIONS']),(str(cache),nvx+',VK_EXT_shader_module_identifier'))
                self.assertEqual(env['VKD3D_CONFIG'],'dxr,no_staggered_submit')
                # What vkd3d-proton writes there (cache.c: vkd3d-proton.<program>.cache, .write, .merge).
                for name in ['vkd3d-proton.Game.exe.cache','vkd3d-proton.Game.exe.cache.write']:(cache/name).write_bytes(b'\0'*1500000)
                out=io.StringIO()
                with contextlib.redirect_stdout(out):m.status(self.exe)
                self.assertIn('vkd3d-proton shader cache: '+str(cache)+' (3.0 MB)',out.getvalue())
                m.restore(self.exe);self.assertOriginal();self.assertFalse(cache.exists())
                self.assertFalse((self.game/'BC250-XeFG').exists())
    def test_vkd3d_cache_path_set_by_the_user_is_kept(self):
        self.user_env(dict(VKD3D_SHADER_CACHE_PATH='0'))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti')
        self.assertNotIn('the first start fills it',out.getvalue())
        env=self.env();self.assertEqual((env['VKD3D_SHADER_CACHE_PATH'],env['VKD3D_DISABLE_EXTENSIONS']),('0','VK_EXT_shader_module_identifier'))
        m.restore(self.exe);self.assertOriginal();self.assertFalse((self.game/m.STATE/m.VKD3D_CACHE).exists())
    def test_restore_of_an_earlier_record_leaves_a_folder_of_that_name(self):
        # Records of 1.1.0 and earlier have no vkd3d_cache: their Restore deletes nothing it did not create.
        m.install(self.package,self.exe,route='opti');record=self.record();record.pop('vkd3d_cache')
        (self.game/m.STATE/'state.json').write_text(json.dumps(record));(self.game/m.STATE/m.VKD3D_CACHE/'other').write_text('kept')
        m.restore(self.exe);self.assertEqual((self.game/m.STATE/m.VKD3D_CACHE/'other').read_text(),'kept')
    def test_game_path_too_long_for_vkd3d_protons_cache_names(self):
        # Neither setting (1.1.0's environment), no folder, a note; Restore as always.
        import launcher_config
        out=io.StringIO()
        with patch.object(launcher_config,'vkd3d_cache_fits',return_value=False),contextlib.redirect_stdout(out):
            m.install(self.package,self.exe,route='opti')
        self.assertIn('Game folder path too long for vkd3d-proton',out.getvalue());self.assertNotIn('the first start fills it',out.getvalue())
        env=self.env();self.assertNotIn('VKD3D_SHADER_CACHE_PATH',env);self.assertNotIn('VKD3D_DISABLE_EXTENSIONS',env)
        self.assertNotIn('vkd3d_cache',self.record());self.assertFalse((self.game/m.STATE/m.VKD3D_CACHE).exists())
        m.restore(self.exe);self.assertOriginal()
    def test_pins_without_the_proxy_layout_are_refused(self):
        set_package_file(self.package,'dependencies.json',json.dumps(pins_for(DEPENDENCIES)).encode())
        with self.assertRaisesRegex(ValueError,'no proxy runtime layout'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_unknown_addon_entry_is_refused(self):
        manifest=json.loads((self.package/'manifest.json').read_text());manifest['addon_entry']='something-else'
        (self.package/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'Unknown add-on entry'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists())
    def test_package_copy_of_the_original_must_be_the_pinned_runtime(self):
        set_package_file(self.package,'payload/bc250_xefg_original.dll',b'other runtime')
        with self.assertRaisesRegex(ValueError,'differs from its pinned upstream download'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()

if __name__=='__main__':unittest.main()

class ScalingControls(ProxyFixture):
    def scaling_package(self):
        set_package_file(self.package,'payload/BC250-XeFG/shaders/freefg-scaling.required',b'1\n')
        set_package_file(self.package,'payload/BC250-XeFG/settings.ini',b'; retain comment\n[BC250]\nResolutionMode=0\nResolutionPercent=75\nResolutionLimit=1080\nDownscaleFilter=0\nUpscaleFilter=0\nExact=1\n')

    def test_scaling_settings_on_both_proxy_routes_and_restore(self):
        self.scaling_package()
        for route in ['native','opti']:
            with self.subTest(route=route):
                m.install(self.package,self.exe,route=route)
                m.configure(self.exe,percent=67,downscale='area',upscale='fsr1')
                path=self.game/'BC250-XeFG/settings.ini';data=path.read_bytes();values=m.read_ini(data)
                self.assertEqual([values[('bc250',key)] for key in ['resolutionmode','resolutionpercent','downscalefilter','upscalefilter','exact']],['1','67','1','4','1'])
                self.assertIn(b'; retain comment',data)
                for filter in ['bilinear','bicubic','lanczos2','fsr1']:m.configure(self.exe,upscale=filter)
                m.configure(self.exe,limit=720)
                self.assertEqual(m.read_ini(path.read_bytes())[('bc250','resolutionmode')],'2')
                m.configure(self.exe,resolution='output')
                self.assertEqual(m.read_ini(path.read_bytes())[('bc250','resolutionmode')],'0')
                m.restore(self.exe);self.assertOriginal()

    def test_unmanaged_marker_does_not_enable_old_runtime(self):
        m.install(self.package,self.exe,route='native')
        path=self.game/'BC250-XeFG/settings.ini';before=path.read_bytes()
        m.write(self.game/'BC250-XeFG/shaders/freefg-scaling.required',b'1\n')
        with self.assertRaisesRegex(ValueError,'scaling-controls'):m.configure(self.exe,percent=73)
        self.assertEqual(path.read_bytes(),before)

    def test_invalid_scaling_request_leaves_every_managed_file_unchanged(self):
        self.scaling_package();m.install(self.package,self.exe,route='opti')
        before={p:p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        for args in [dict(percent=49),dict(percent=101),dict(limit=1000),dict(percent=67,limit=720),dict(upscale='area'),dict(downscale='bicubic')]:
            with self.subTest(args=args),self.assertRaises(ValueError):m.configure(self.exe,**args)
        self.assertEqual({p:p.read_bytes() for p in before},before)

class IntegrationContractTests(ProxyFixture):
    """install.py contract and integration.json (integration_contract): what an installation does, as data. It must say
    what install() does: the same launcher variables and the same OptiScaler.ini keys."""
    def contract(self,**options):
        return m.integration_contract(*m.package_contract(self.package),**options)
    def test_ini_keys_are_the_ones_install_writes(self):
        # A fresh setup last: Restore takes the fresh OptiScaler setup out again.
        for route,fg_input,fresh in (('opti','upscaler',False),('opti','fsrfg',False),('native','upscaler',False),('opti','dlssg',True)):
            with self.subTest(route=route,fg_input=fg_input,fresh=fresh):
                if fresh:
                    for name in ('dxgi.dll','OptiScaler.ini','OptiScaler/'+m.DLL,'OptiScaler/libxell.dll'):(self.game/name).unlink()
                m.install(self.package,self.exe,route=route,fg_input=fg_input)
                written={c['section']+'.'+c['key']:c['value'] for c in self.record()['ini_changes']}
                m.restore(self.exe)
                keys=next(r['ini'] for r in self.contract()['routes'] if r['route']==route)
                expected={k['key']:k['value'].replace('{fg_input}',fg_input) for k in keys if k['write']!='repair' and
                          (not k['when'] or ('fresh' in k['when'] and fresh) or fg_input in k['when'].replace(',',' ').split())}
                self.assertEqual(written,expected)
    def test_environment_operations_are_what_install_writes(self):
        # The contract's operations with its placeholders filled in give the launcher entry install() writes.
        import launcher_config
        before=self.env()
        m.install(self.package,self.exe,route='opti')
        root,cache=self.game.resolve(),self.game.resolve()/m.STATE/m.VKD3D_CACHE
        ops=[dict(op,value=op['value'].replace('{game}',str(root)).replace('{cache}',str(cache))) if 'value' in op else op
             for op in next(r for r in self.contract()['routes'] if r['route']=='opti')['environment']]
        self.assertEqual(launcher_config.apply_contract(before,ops),self.env())
        m.restore(self.exe);self.assertOriginal()
    def test_contract_command_prints_the_contract(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.show_contract(self.package,True)
        self.assertEqual(out.getvalue(),m.integration_text(*m.package_contract(self.package)))
        contract=json.loads(out.getvalue())
        self.assertEqual((contract['format'],contract['package'],contract['optiscaler'],contract['host']),(1,'bc250-fsr4-xemfg-private-test-99',None,{}))
        self.assertEqual(contract['files']['downloads'],[
            dict(target='OptiScaler/'+m.DLL,file='fsr4/'+m.DLL,sha256=m.digest(DEPENDENCIES['runtime']['fsr4/'+m.DLL])),
            dict(target='bc250_xefg_original.dll',file='OptiScaler/libxess_fg.dll',sha256=m.digest(DEPENDENCIES['runtime']['OptiScaler/libxess_fg.dll'])),
            dict(target='libxell.dll',file='OptiScaler/libxell.dll',sha256=m.digest(DEPENDENCIES['runtime']['OptiScaler/libxell.dll']))])
        self.assertNotIn('OptiScaler/libxess_fg.dll',[f['target'] for f in contract['files']['optiscaler']['fresh_setup']])
        self.assertIn(dict(target='dxgi.dll',file='OptiScaler.dll',sha256=m.digest(DEPENDENCIES['payload']['OptiScaler.dll'])),
                      contract['files']['optiscaler']['fresh_setup'])
        self.assertEqual(contract['settings'],['OptiScaler.ini','BC250-XeFG/settings.ini'])
        one=self.contract(route='native',owner='winmm.dll')
        self.assertEqual([(r['route'],r['owner'],r['environment'][0]['value']) for r in one['routes']],[('native','winmm.dll','winmm=n,b')])
        # The command itself, run as Setup and integrators run it (here from the source tree: no manifest).
        run=__import__('subprocess').run([__import__('sys').executable,'-I',str(m.Path(m.__file__)),'contract','--json','--route','opti'],
                                         capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual([r['route'] for r in json.loads(run.stdout)['routes']],['opti'])
        run=__import__('subprocess').run([__import__('sys').executable,'-I',str(m.Path(m.__file__)),'contract'],capture_output=True,text=True)
        self.assertIn('  WINEDLLOVERRIDES dll-override dxgi=n,b (separator ;)\n',run.stdout)

class ManualLaunchTests(ProxyFixture):
    """A game no Steam, Heroic or Lutris entry starts (one in Faugus, Bottles or a script): Install refuses unless the
    no-launcher refusal is accepted; accepted, it installs the files as usual, writes no launcher file, and records and
    prints the launch settings, which Status and Restore name again."""
    def setUp(self):
        super().setUp()
        self.config.unlink()
    def quiet(self,function,*args,**kwargs):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):function(*args,**kwargs)
        return out.getvalue()
    def expected(self):
        root=self.game.resolve()
        env={'WINEDLLOVERRIDES':'dxgi=n,b','VK_LAYER_PATH':str(root/'BC250-XeFG/layer'),'VK_INSTANCE_LAYERS':'VK_LAYER_BC250_xefg_wave',
             'XEFG_WAVE_CONFIG':str(root/'BC250-XeFG/shaders/waves.txt'),'VKD3D_CONFIG':'no_staggered_submit',
             'VKD3D_DISABLE_EXTENSIONS':'VK_EXT_shader_module_identifier','VKD3D_SHADER_CACHE_PATH':str(root/m.STATE/m.VKD3D_CACHE)}
        return env,''.join('    '+key+'='+shlex.quote(value)+'\n' for key,value in env.items())
    def test_refused_unless_accepted(self):
        with self.assertRaisesRegex(ValueError,r'No launcher entry found.*Install anyway.*\[no-launcher\]'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists())
    def test_preview_names_the_settings_and_writes_nothing(self):
        out=self.quiet(m.install,self.package,self.exe,preview=True,route='opti',accept=('no-launcher',))
        self.assertIn('In your launcher: set the launch settings listed below for the game (no launcher entry is changed).\n'+self.expected()[1],out)
        self.assertFalse((self.game/m.STATE).exists());self.assertFalse(self.config.exists())
    def test_install_status_restore(self):
        env,block=self.expected()
        out=self.quiet(m.install,self.package,self.exe,route='opti',accept=('no-launcher',))
        self.assertIn('Installed. No launcher entry was changed.\nIn your launcher: set the launch settings listed below for the game '
                      'before you play (in Setup: under Installer output; on a command line: before the command). Status shows '
                      'them again.\n'+block,out)
        self.assertNotIn('Open your launcher and play normally',out)
        record=self.record()
        self.assertEqual((record['launchers'],{key:record['manual_launch'][key] for key in ('env','args')},record['compat']['accepted']),
                         ([],{'env':env,'args':[]},['no-launcher']))
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'BC250 proxy');self.assertTrue((self.game/m.STATE/m.VKD3D_CACHE).is_dir())
        self.assertFalse(self.config.exists())
        # No launcher entry names it: Update all finds it through the library index.
        self.assertEqual([(row['exe'],row['status']) for row in m.library_inventory()],[(self.exe.resolve(),'installed')])
        out=self.quiet(m.status,self.exe)
        self.assertIn('In your launcher: keep the launch settings listed below for the game (this installer does not edit it).\n'+block,out)
        self.assertIn('Launch normally with FG active.',out)
        out=self.quiet(m.restore,self.exe)
        self.assertIn('In your launcher: remove the launch settings listed below from the game (in Setup: under Installer output).\n'+block,out);self.assertNotIn('run.sh',out)
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data,name)
        self.assertFalse((self.game/'bc250_xefg_original.dll').exists());self.assertFalse(self.config.exists())
    def events(self,function,*args,**kwargs):
        """(output, events) of a call with --events on."""
        with patch.object(m,'EVENTS',True):out=self.quiet(function,*args,**kwargs)
        return out,[json.loads(line[len(m.EVENT_PREFIX):]) for line in out.splitlines() if line.startswith(m.EVENT_PREFIX)]
    def recipe(self,**fields):
        """A verified recipe for the fixture game (no launcher ID: Game.exe in its folder 'game')."""
        entry=dict(dict(title='Test Game',match=dict(exe=['game.exe'],title=['game']),status='verified-bc250',route='opti',fg_input='upscaler',
                        ini={},game_settings=[],launch_args=[]),**fields)
        set_package_file(self.package,'recipes/recipes.json',json.dumps(dict(schema=1,verified=[entry],wiki=[],leave_auto={},backports={})).encode())
    def test_settings_are_complete_and_printed_in_every_form(self):
        import launcher_config
        env,block=self.expected()
        self.recipe(required_args=['-nobattleye'])
        out,events=self.events(m.install,self.package,self.exe,route='opti',accept=('no-launcher',))
        settings=self.record()['manual_launch']
        self.assertEqual((settings['format'],settings['env'],settings['args'],settings['required_args'],settings['remove'],settings['notes']),
                         (launcher_config.MANUAL_FORMAT,env,[],['-nobattleye'],['XEFG_GAME_PROFILE','BC250_XEFG_OWNER_MODULE','XEFG_FLOW_CAP'],[]))
        self.assertEqual([op['var'] for op in settings['merge']],list(env))
        # Read back by the launch contract: a new entry gets env, and the user's own values combine as merge says.
        self.assertEqual(launcher_config.apply_contract({},settings['merge']),env)
        self.assertEqual(launcher_config.apply_contract({'WINEDLLOVERRIDES':'dxgi=b;mine=n','VKD3D_SHADER_CACHE_PATH':'0'},settings['merge'])
                         ['WINEDLLOVERRIDES'],'mine=n;dxgi=n,b')
        steam=launcher_config.manual_steam_line(settings)
        self.assertIn(block+'    Game arguments (after the .exe): -nobattleye\n    As one launch-options line (Steam’s form): '+steam+'\n',out)
        self.assertEqual(launcher_config.split_steam(steam)[0],env);self.assertTrue(steam.endswith(' %command% -nobattleye'))
        self.assertNotIn('In a table of variables',out)  # no value here needs quotes
        self.assertIn('    Delete where present: XEFG_GAME_PROFILE, BC250_XEFG_OWNER_MODULE, XEFG_FLOW_CAP\n',out)
        self.assertIn('    Where the launcher already sets one of these, combine them:\n      WINEDLLOVERRIDES: keep your entries without any '
                      'for dxgi, then add dxgi=n,b (entries separated by ;)\n',out)
        self.assertIn('      VKD3D_SHADER_CACHE_PATH: keep yours where you set one (0 included)\n',out)
        step='In your launcher: set the launch settings listed below for the game before you play (in Setup: under Installer output; on a command line: before the command). Status shows them again.'
        self.assertIn({'v':1,'type':'manual','action':'set','settings':settings},events)
        self.assertIn({'v':1,'type':'step','where':'launcher','text':step},events)
        # Restore: what to delete, also from values the user combined with their own; the same events with remove.
        out,events=self.events(m.restore,self.exe)
        self.assertIn('    Where you combined them with your own values, take out only these parts:\n      WINEDLLOVERRIDES: dxgi=n,b\n',out)
        self.assertIn('      VKD3D_SHADER_CACHE_PATH: only where it is '+env['VKD3D_SHADER_CACHE_PATH']+'\n',out)
        self.assertEqual([e['action'] for e in events if e['type']=='manual'],['remove'])
        self.assertEqual([e['text'] for e in events if e['type']=='step'],
                         ['In your launcher: remove the launch settings listed below from the game (in Setup: under Installer output).'])
    def test_a_path_too_long_for_vkd3d_protons_cache_is_noted_with_the_settings(self):
        import launcher_config
        with patch.object(launcher_config,'vkd3d_cache_fits',return_value=False):
            out=self.quiet(m.install,self.package,self.exe,route='opti',accept=('no-launcher',))
        settings=self.record()['manual_launch']
        self.assertEqual(settings['notes'],[launcher_config.CACHE_PATH_NOTE]);self.assertNotIn('VKD3D_SHADER_CACHE_PATH',settings['env'])
        self.assertEqual(out.count(launcher_config.CACHE_PATH_NOTE),1);self.assertIn('    '+launcher_config.CACHE_PATH_NOTE+'\n',out)
    def test_status_confirms_the_settings_from_the_last_session(self):
        m.install(self.package,self.exe,route='opti',accept=('no-launcher',))
        out=self.quiet(m.status,self.exe)
        self.assertIn('Manual launch settings: not yet confirmed: no session since installation shows them. Start the game with them and '
                      'frame generation on.\n',out)
        self.assertNotIn('library index',out)
        (self.game/'OptiScaler.log').write_text('[I] OptiScaler loaded\n')
        self.assertIn('Manual launch settings: not yet confirmed (the last session: OptiScaler loaded).',self.quiet(m.status,self.exe))
        (self.game/'BC250-MFG.log').write_text("MFG proxy ready: Intel's XeFG runtime unmodified beside it\nFAST_OWNER first initialized context selected\n")
        self.assertIn('Manual launch settings: added by you; the last session ran with them (OptiScaler loaded, MFG proxy ready, '
                      'frame-generation context selected).\n',self.quiet(m.status,self.exe))
        # No launcher entry names the game: without its index entry Update all would not find it.
        index=self.root/'.local/share/freefg/library.json';index.unlink()
        self.assertEqual(m.library_inventory(),[])
        self.assertIn('Not in the library index, so Update all does not find this game: install.py register '+str(self.exe)+' adds it.',
                      self.quiet(m.status,self.exe))
        self.quiet(m.register_installation,self.exe)
        self.assertEqual([row['exe'] for row in m.library_inventory()],[self.exe.resolve()])
        self.assertNotIn('library index',self.quiet(m.status,self.exe))
    def test_records_of_the_first_manual_installations_stay_valid(self):
        # PR #8 recorded env and args only, GTA's -nobattleye among args: Status and Restore show them as they are.
        self.recipe(launch_args=['-nobattleye'])
        m.install(self.package,self.exe,route='opti',accept=('no-launcher',))
        self.assertEqual(self.record()['manual_launch']['required_args'],['-nobattleye'])
        record=self.record();record['manual_launch']={'env':record['manual_launch']['env'],'args':['-nobattleye']}
        (self.game/m.STATE/'state.json').write_text(json.dumps(record))
        out=self.quiet(m.status,self.exe)
        self.assertIn('    Game arguments (after the .exe): -nobattleye\n',out);self.assertNotIn('Leave out',out)
        self.assertNotIn('Delete where present',out)
        out=self.quiet(m.restore,self.exe)
        self.assertIn('    Game arguments (after the .exe): -nobattleye\n',out);self.assertNotIn('take out only',out)
    def test_a_launcher_entry_found_after_all_is_configured(self):
        # Accepting the refusal only allows an installation without an entry: an entry the installer finds is configured.
        self.config=heroic(self.root,self.game)
        m.install(self.package,self.exe,route='opti',accept=('no-launcher',))
        record=self.record();self.assertEqual(len(record['launchers']),1);self.assertNotIn('manual_launch',record)
        self.assertEqual(self.env()['WINEDLLOVERRIDES'],'dxgi=n,b')
        m.restore(self.exe);self.assertOriginal()
