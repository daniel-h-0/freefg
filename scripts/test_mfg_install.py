# SPDX-License-Identifier: MIT
"""Exercise the multi-frame package's settings, routes and launcher fields without a real game."""
import json,unittest
from test_game_install import GameFixture,set_package_file,m

class MfgTests(GameFixture):
    def enable_settings(self):
        for name in ['mfg-frame-settings.required','mfg-upscale-filters.required']:
            set_package_file(self.package,'payload/OptiScaler/plugins/BC250-XeFG/shaders/'+name,b'1\n')
    def test_settings_shared_ini(self):
        self.enable_settings();m.install(self.package,self.exe,route='opti')
        m.configure(self.exe,percent=65,upscale='fsr1')
        ini=m.read_ini((self.game/'BC250-XeFG/settings.ini').read_bytes())
        self.assertEqual(ini[('bc250','resolutionmode')],'1')
        self.assertEqual(ini[('bc250','resolutionpercent')],'65')
        self.assertEqual(ini[('bc250','upscalefilter')],'4')
        m.configure(self.exe,limit=1080)
        ini=m.read_ini((self.game/'BC250-XeFG/settings.ini').read_bytes())
        self.assertEqual(ini[('bc250','resolutionmode')],'2');self.assertEqual(ini[('bc250','resolutionlimit')],'1080')
        m.configure(self.exe,resolution='output')
        self.assertEqual(m.read_ini((self.game/'BC250-XeFG/settings.ini').read_bytes())[('bc250','resolutionmode')],'0')
    def test_settings_validation_is_transactional(self):
        self.enable_settings();m.install(self.package,self.exe,route='opti')
        before=(self.game/'OptiScaler.ini').read_bytes()
        for args in [dict(percent=49),dict(percent=80,limit=720),dict(resolution='output',percent=70),dict(downscale='area'),dict(downscale='bicubic')]:
            with self.assertRaises(ValueError):m.configure(self.exe,factor=4,**args)
            self.assertEqual((self.game/'OptiScaler.ini').read_bytes(),before)
    def test_old_addon_rejects_new_controls(self):
        m.install(self.package,self.exe,route='native')
        with self.assertRaisesRegex(ValueError,'new scaling-controls build'):m.configure(self.exe,percent=70)
    def add_custom_opti(self):
        data=b'private OptiScaler controls';set_package_file(self.package,'opti/OptiScaler.dll',data)
        return data
    def test_controls_fresh_proxy_roundtrip(self):
        self.enable_settings();deps=self.fresh();custom=self.add_custom_opti()
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual((self.game/'dxgi.dll').read_bytes(),custom)
        m.restore(self.exe);self.assertFalse((self.game/'dxgi.dll').exists())
    def test_controls_existing_proxy_roundtrip(self):
        self.enable_settings();self.fresh();custom=self.add_custom_opti()
        for owner,original in [('winmm.dll',b'opti'),('winmm.dll',custom)]:
            for name,data in self.original.items():
                if name!='dxgi.dll':m.write(self.game/name,data)
            (self.game/owner).write_bytes(original)
            m.install(self.package,self.exe,route='opti')
            self.assertEqual((self.game/owner).read_bytes(),custom)
            self.assertFalse((self.game/'dxgi.dll').exists())
            m.restore(self.exe);self.assertEqual((self.game/owner).read_bytes(),original)
    def test_controls_unknown_proxy_no_mutation(self):
        self.enable_settings();self.add_custom_opti()
        (self.game/'dxgi.dll').write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'Existing OptiScaler'):m.install(self.package,self.exe,route='opti')
        self.assertEqual((self.game/'dxgi.dll').read_bytes(),b'unknown');self.assertFalse((self.game/m.STATE).exists())
        self.assertEqual(self.prepared,[])  # refused before any download
    def test_mfg_opti_roundtrip_settings(self):
        m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        config=m.read_ini((self.game/'OptiScaler.ini').read_bytes())
        self.assertEqual(config[('plugins','loadasiplugins')],'true')
        self.assertEqual(config[('libraries','xefgpath')],r'.\libxess_fg.dll')
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'Intel FG')
        self.assertFalse((self.game/'OptiScaler/libxell.dll').exists())
        self.assertTrue((self.game/'OptiScaler/plugins/BC250-MFG.asi').is_file())
        (self.game/'XeSSMFG/settings.ini').write_text('[XeSSMFG]\nMultiplier=4\n')
        (self.game/'XeSSMFG/XeSSMFG.log').write_text('test log')
        m.restore(self.exe)
        self.assertOriginal()
        self.assertFalse((self.game/'XeSSMFG').exists());self.assertFalse((self.game/'version.dll').exists())
        self.assertTrue(list((self.game/m.STATE/'preserved-ini').glob('xemfg-*.ini')))
        self.assertTrue(list((self.game/m.STATE).glob('runtime-logs-*/XeSSMFG.log')))
        m.install(self.package,self.exe,route='opti');m.restore(self.exe)
    def test_mfg_fsrfg_disables_hudless(self):
        # The enabler turns FSR 3 FG input's HUD-less image into early copies of the next real frame; other inputs keep it.
        read=lambda:m.read_ini((self.game/'OptiScaler.ini').read_bytes())
        for fg_input,expected in [('fsrfg','true'),('fsrfg30','true'),('dlssg',None),('upscaler',None)]:
            before=read().get(('framegen','disablehudless'))
            m.install(self.package,self.exe,route='opti',fg_input=fg_input)
            self.assertEqual(read().get(('framegen','disablehudless')),expected if expected else before,fg_input)
            m.restore(self.exe);self.assertEqual(read().get(('framegen','disablehudless')),before,fg_input)
    def test_mfg_opti_forces_reflex(self):
        # OptiScaler routes force the game's Reflex on (XeLL paces frame starts); native installs and an explicit
        # "force disable" in the game's INI are left alone, and Restore returns the original value.
        read=lambda:m.read_ini((self.game/'OptiScaler.ini').read_bytes()).get(('fakenvapi','forcereflex'))
        before=read()
        for fg_input in ['upscaler','fsrfg','fsrfg30']:
            m.install(self.package,self.exe,route='opti',fg_input=fg_input);self.assertEqual(read(),'2',fg_input)
            m.restore(self.exe);self.assertEqual(read(),before,fg_input)
        # DLSS FG input already runs the game's Reflex; forcing it would also override OptiScaler's DLSS-MFG guards.
        m.install(self.package,self.exe,route='opti',fg_input='dlssg');self.assertEqual(read(),before);m.restore(self.exe)
        m.install(self.package,self.exe,route='native');self.assertEqual(read(),before);m.restore(self.exe)
        ini=self.game/'OptiScaler.ini';original=ini.read_bytes()
        for chosen in ['0','1']:  # the user's own choice (follow the game / force off) survives a reinstall
            ini.write_bytes(m.patch_ini(original,{('fakenvapi','ForceReflex'):chosen}))
            m.install(self.package,self.exe,route='opti',fg_input='upscaler');self.assertEqual(read(),chosen);m.restore(self.exe)
        ini.write_bytes(original)
    def test_opti_forces_borderless(self):
        # XeFG does not interpolate in exclusive fullscreen: every OptiScaler route keeps the swap chain borderless,
        # native installs and a value the user wrote are left alone, and Restore returns the original value.
        read=lambda:m.read_ini((self.game/'OptiScaler.ini').read_bytes()).get(('xefg','forceborderless'))
        before=read()
        for fg_input in ['upscaler','fsrfg','fsrfg30','dlssg']:
            m.install(self.package,self.exe,route='opti',fg_input=fg_input);self.assertEqual(read(),'true',fg_input)
            m.restore(self.exe);self.assertEqual(read(),before,fg_input)
        m.install(self.package,self.exe,route='native');self.assertEqual(read(),before);m.restore(self.exe)
        ini=self.game/'OptiScaler.ini';original=ini.read_bytes()
        ini.write_bytes(m.patch_ini(original,{('XeFG','ForceBorderless'):'false'}))
        m.install(self.package,self.exe,route='opti',fg_input='upscaler');self.assertEqual(read(),'false');m.restore(self.exe)
        ini.write_bytes(original)
    def test_route_switch_does_not_carry_opti_multiplier(self):
        # OptiScaler route installs keep XeSSMFG's own multiplier at 0 ("follow the game"); a later native install must
        # start from the package default instead of inheriting it.
        read=lambda:m.read_ini((self.game/'XeSSMFG/settings.ini').read_bytes())
        m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        self.assertEqual(read()[('xessmfg','multiplier')],'0');m.restore(self.exe)
        m.install(self.package,self.exe,route='native');self.assertNotEqual(read()[('xessmfg','multiplier')],'0');m.restore(self.exe)
    def test_reinstall_keeps_user_settings(self):
        # A tester upgrade is Restore then Install; choices made in the menu or with configure must survive it.
        m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        read=lambda name:m.read_ini((self.game/name).read_bytes())
        self.assertEqual(read('OptiScaler.ini')[('xefg','interpolationcount')],'1')
        ini=self.game/'OptiScaler.ini';ini.write_bytes(m.patch_ini(ini.read_bytes(),{('XeFG','InterpolationCount'):'2'}))
        (self.game/'XeSSMFG/settings.ini').write_text('[XeSSMFG]\nMultiplier=4\nExposeIntelVendor=1\nStale=1\n')
        (self.game/'BC250-XeFG/settings.ini').write_text('[BC250]\nFrameCap=0\n')
        m.restore(self.exe)
        self.assertEqual(read('OptiScaler.ini')[('xefg','interpolationcount')],'2')
        m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        self.assertEqual(read('OptiScaler.ini')[('xefg','interpolationcount')],'2')
        mfg=read('XeSSMFG/settings.ini')
        self.assertEqual(mfg[('xessmfg','multiplier')],'0')  # OptiScaler owns the count on this route
        self.assertEqual(mfg[('xessmfg','exposeintelvendor')],'1');self.assertNotIn(('xessmfg','stale'),mfg)
        self.assertEqual(read('BC250-XeFG/settings.ini')[('bc250','framecap')],'0')
        # The carried values are the installation's new baseline: an untouched restore/install cycle keeps them too.
        m.restore(self.exe);m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        self.assertEqual(read('BC250-XeFG/settings.ini')[('bc250','framecap')],'0')
        self.assertEqual(read('XeSSMFG/settings.ini')[('xessmfg','exposeintelvendor')],'1')
    def test_reinstall_carries_settings_from_older_restore(self):
        # A restore written before preserved_settings existed: copies are told apart by their sections.
        m.install(self.package,self.exe,route='opti')
        (self.game/'BC250-XeFG/settings.ini').write_text('[BC250]\nFrameCap=0\n')
        m.restore(self.exe);state=self.game/m.STATE;record=json.loads((state/'state.json').read_text())
        record.pop('preserved_settings');(state/'state.json').write_text(json.dumps(record))
        m.install(self.package,self.exe,route='opti')
        self.assertEqual(m.read_ini((self.game/'BC250-XeFG/settings.ini').read_bytes())[('bc250','framecap')],'0')
    def test_mfg_configure_opti(self):
        m.install(self.package,self.exe,route='opti')
        read=lambda name:m.read_ini((self.game/name).read_bytes())
        self.assertEqual(read('XeSSMFG/settings.ini')[('xessmfg','multiplier')],'0')
        self.assertEqual(read('OptiScaler.ini')[('xefg','interpolationcount')],'1')
        for factor in [2,3,4]:
            m.configure(self.exe,factor)
            self.assertEqual(read('OptiScaler.ini')[('xefg','interpolationcount')],str(factor-1))
            self.assertEqual(read('XeSSMFG/settings.ini')[('xessmfg','multiplier')],'0')
        m.restore(self.exe)
        self.assertFalse((self.game/'BC250-XeFG/settings.ini').exists())
    def test_mfg_configure_native(self):
        m.install(self.package,self.exe,route='native')
        m.configure(self.exe,4)
        self.assertEqual(m.read_ini((self.game/'XeSSMFG/settings.ini').read_bytes())[('xessmfg','multiplier')],'4')
        m.restore(self.exe)
    def test_mfg_conflict_no_writes(self):
        (self.game/'version.dll').write_bytes(b'other mod')
        with self.assertRaisesRegex(ValueError,'occupied'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists());self.assertEqual((self.game/'version.dll').read_bytes(),b'other mod')
    def test_mfg_fresh(self):
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertFalse((self.game/'OptiScaler/libxell.dll').exists());self.assertTrue((self.game/'libxell.dll').exists())
        overrides=self.env()['WINEDLLOVERRIDES'].split(';')
        self.assertIn('version=n,b',overrides);self.assertIn('dxgi=n,b',overrides);m.restore(self.exe)
    def test_launcher_environment_and_restore(self):
        # What the wrapper scripts of earlier builds exported now sits in the launcher's own fields, and Restore takes
        # out only that.
        m.install(self.package,self.exe,route='opti')
        env=self.env()
        self.assertEqual(env['VK_INSTANCE_LAYERS'],'VK_LAYER_BC250_xefg_wave')
        self.assertEqual(env['VK_LAYER_PATH'],str(self.game.resolve()/'BC250-XeFG/layer'))
        self.assertEqual(env['XEFG_WAVE_CONFIG'],str(self.game.resolve()/'OptiScaler/plugins/BC250-XeFG/shaders/waves.txt'))
        self.assertEqual(env['VKD3D_CONFIG'],'dxr,no_staggered_submit')
        self.assertNotIn('BC250_XEFG_OWNER_MODULE',env)
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertIsNone(record['wrapper']);self.assertEqual(len(record['launchers']),1)
        self.assertFalse((self.game/'BC250-XeFG/run.sh').exists())
        m.restore(self.exe);self.assertOriginal()
    def test_fresh_reinstall_keeps_optiscaler_multiplier_and_reflex(self):
        # Restore of a fresh OptiScaler setup removes the whole INI (saved as preserved_ini); Install of the next build
        # takes the user's multiplier and Reflex choice from it.
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        ini=self.game/'OptiScaler.ini'
        ini.write_bytes(m.patch_ini(ini.read_bytes(),{('XeFG','InterpolationCount'):'3',('fakenvapi','ForceReflex'):'0'}))
        m.restore(self.exe);self.assertFalse(ini.exists())
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        values=m.read_ini(ini.read_bytes())
        self.assertEqual(values[('xefg','interpolationcount')],'3');self.assertEqual(values[('fakenvapi','forcereflex')],'0')
        m.restore(self.exe);self.assertFalse(ini.exists())
    def test_configure_multiplier_is_undone_by_restore(self):
        m.install(self.package,self.exe,route='opti')
        m.configure(self.exe,4)
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('xefg','interpolationcount')],'3')
        m.restore(self.exe)
        self.assertNotIn(('xefg','interpolationcount'),m.read_ini((self.game/'OptiScaler.ini').read_bytes()))

if __name__=='__main__':unittest.main()
