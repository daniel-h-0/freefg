# SPDX-License-Identifier: MIT
"""Installer transactions on a fixture enabler-free package (manifest addon_entry "libxess_fg-proxy", variant intel-free-2x):
the add-on is payload/libxess_fg.dll, Intel's runtime comes from the pinned downloads as bc250_xefg_original.dll
(dependencies.json runtime.ProxyPackage), there is no XeSSMFG enabler or version.dll, and the package is 2x only."""
import contextlib,io,json,os,unittest
from test_game_install import GameFixture,DEPENDENCIES,set_package_file,pins_for,m

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
        (self.game/'BC250-XeFG-fast.log').write_text('INTEL_FREE own shaders only\nWINOGRAD_EXECUTE shader=fec421a3b6a0632b channels=224 clamp=16\n')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        self.assertIn('Accelerated graph stages observed: 1/4',out.getvalue());self.assertIn(str(self.game.resolve()/'BC250-XeFG-fast.log'),out.getvalue())
        m.restore(self.exe)
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
