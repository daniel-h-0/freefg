# SPDX-License-Identifier: MIT
"""HLX provider migrations are atomic with the loader and configuration and keep model data local."""
import json
import shutil
import unittest
from unittest.mock import patch
from test_game_install import set_package_file
from test_update import UpdateFixture, Crash, m


class HlxUpdates(UpdateFixture):
    def setUp(self):
        super().setUp()
        self.hlx_release=self.root/'HLX';self.hlx_release.mkdir()
        self.contents={'DLSS.dll':b'qualified DLSS model','FSR.dll':b'qualified FSR model','AMD.dll':b'qualified AMD companion'}
        for name,data in self.contents.items():(self.hlx_release/name).write_bytes(data)
        self.spec={'format':1,'version':'3.1.0','folder':'HLX','archive':{'sha256':m.digest(b'archive')},'providers':{
            'hlx-dlss':{'api':'dlss','entry':'helixsr.dll','files':{'helixsr.dll':{'source':'DLSS.dll','sha256':m.digest(self.contents['DLSS.dll'])}}},
            'hlx-fsr4':{'api':'ffx','entry':m.DLL,'files':{m.DLL:{'source':'FSR.dll','sha256':m.digest(self.contents['FSR.dll'])},'amd_fidelityfx_upscaler_dx12.amd.dll':{'source':'AMD.dll','sha256':m.digest(self.contents['AMD.dll'])}}}}}
        pins=json.loads((self.new/'dependencies.json').read_text());pins['hlx']=self.spec
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode())
        set_package_file(self.new,'opti/OptiScaler.dll',b'new HLX integration')
        self.dlss='OptiScaler/custom/hlx-dlss/dlss/helixsr.dll'
        self.fsr='OptiScaler/custom/hlx-fsr4/ffx/'+m.DLL

    def install_old(self):m.install(self.package,self.exe,route='opti')

    def select(self,name='hlx-dlss',**kw):
        return self.run_quiet(m.update,self.exe,self.new,helixsr_dir=self.hlx_release,upscaler=name,**kw)

    def test_legacy_helixsr_advances_to_hlx_dlss_and_restores_exactly(self):
        from test_helixsr_install import add_pins,make_release,built
        add_pins(self.package);legacy=make_release(self.root/'HelixSR-old',built())
        self.run_quiet(m.install,self.package,self.exe,route='opti',upscaler='helixsr',helixsr_dir=legacy)
        before=self.snapshot();old=self.record()['upscaler']
        status,_=self.run_quiet(m.update,self.exe,self.new,helixsr_dir=self.hlx_release)
        self.assertEqual(status,'update');self.assertEqual(self.record()['upscaler']['name'],'hlx-dlss')
        self.assertEqual(self.record()['upscaler']['legacy_helixsr'],old)
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.run_quiet(m.update,self.exe,self.new,helixsr_dir=self.hlx_release)
        self.run_quiet(m.restore,self.exe);self.assertOriginal()

    def test_hlx_fsr4_gets_the_scoped_cyberpunk_mask_workaround(self):
        self.install_old()
        recipe={'upscaler_ini':{'hlx-fsr4':{'InitFlags.DisableReactiveMask':'true'}}}
        with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
            self.select('hlx-fsr4')
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('initflags','disablereactivemask')],'true')
        self.run_quiet(m.rollback,self.exe)
        self.assertNotIn(('initflags','disablereactivemask'),m.read_ini((self.game/'OptiScaler.ini').read_bytes()))

    def test_explicit_mask_choice_is_preserved_and_reported(self):
        ini=self.game/'OptiScaler.ini';ini.write_bytes(m.patch_ini(ini.read_bytes(),{('InitFlags','DisableReactiveMask'):'false'}))
        self.install_old()
        recipe={'upscaler_ini':{'hlx-fsr4':{'InitFlags.DisableReactiveMask':'true'}}}
        with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
            status,out=self.select('hlx-fsr4')
        self.assertEqual(status,'update');self.assertIn('your explicit false is preserved',out)
        self.assertEqual(m.read_ini(ini.read_bytes())[('initflags','disablereactivemask')],'false')

    def test_fresh_install_and_restore_are_one_plan(self):
        self.run_quiet(m.install,self.new,self.exe,route='opti',upscaler='hlx-dlss',helixsr_dir=self.hlx_release)
        self.assertEqual((self.game/self.dlss).read_bytes(),self.contents['DLSS.dll'])
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('upscalers','dx12upscaler')],'hlx-dlss')
        m.restore(self.exe);self.assertOriginal()

    def test_preview_and_bad_preparation_leave_fresh_game_untouched(self):
        before=self.snapshot()
        self.run_quiet(m.install,self.new,self.exe,preview=True,route='opti',upscaler='hlx-fsr4',helixsr_dir=self.hlx_release)
        self.assertEqual(self.snapshot(),before)
        (self.hlx_release/'AMD.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'qualified'):
            self.run_quiet(m.install,self.new,self.exe,route='opti',upscaler='hlx-fsr4',helixsr_dir=self.hlx_release)
        self.assertEqual(self.snapshot(),before);self.assertFalse((self.game/m.STATE).exists())

    def test_provider_loader_and_core_update_roll_back_exactly(self):
        self.install_old();before=self.snapshot()
        self.assertEqual(self.select(loader='winmm.dll')[0],'update')
        self.assertEqual(self.record()['opti_owner'],'winmm.dll')
        self.assertEqual(self.record()['upscaler']['name'],'hlx-dlss')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.select('hlx-fsr4');m.restore(self.exe);self.assertOriginal()

    def test_switches_and_current_install_without_cache(self):
        self.install_old();self.select()
        for name in ('hlx-fsr4','fsr4','hlx-dlss'):
            self.run_quiet(m.configure,self.exe,upscaler=name,package=self.new,helixsr_dir=self.hlx_release)
            self.assertEqual(self.record()['upscaler']['name'],name)
        shutil.rmtree(self.hlx_release)
        status,_=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'current')
        m.restore(self.exe);self.assertOriginal()

    def test_changed_companion_blocks_entire_transaction(self):
        self.install_old();self.select('hlx-fsr4')
        path=self.game/'OptiScaler/custom/hlx-fsr4/ffx/amd_fidelityfx_upscaler_dx12.amd.dll'
        path.write_bytes(b'changed companion');before=self.snapshot();record=self.record()
        status,_=self.select('hlx-fsr4');self.assertEqual(status,'blocked')
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_existing_unowned_provider_is_never_overwritten(self):
        self.install_old();path=self.game/self.dlss;path.parent.mkdir(parents=True);path.write_bytes(b'other mod')
        before=self.snapshot();self.assertEqual(self.select()[0],'blocked');self.assertEqual(self.snapshot(),before)

    def test_each_write_interruption_can_rollback_or_restore(self):
        self.install_old();before=self.snapshot();real=m.write
        targets=[self.game/self.dlss,self.game/'OptiScaler.ini',self.game/'winmm.dll',self.config]
        for target in targets:
            with self.subTest(target=target):
                def crash(path,*args,**kwargs):
                    result=real(path,*args,**kwargs)
                    if path==target:raise Crash()
                    return result
                with patch.object(m,'write',side_effect=crash):
                    with self.assertRaises(Crash):self.select(loader='winmm.dll')
                self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        with patch.object(m,'write',side_effect=crash):
            with self.assertRaises(Crash):self.select(loader='winmm.dll')
        self.run_quiet(m.restore,self.exe);self.assertOriginal()

    def test_rollback_preserves_later_setting_ownership(self):
        self.install_old();self.select();m.configure(self.exe,factor=2)
        record=self.record();wanted=next(x for x in record['ini_changes'] if x['key']=='InterpolationCount')
        self.run_quiet(m.rollback,self.exe)
        self.assertIn(wanted,self.record()['ini_changes'])


if __name__=='__main__':unittest.main()
