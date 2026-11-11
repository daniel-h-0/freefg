# SPDX-License-Identifier: MIT
"""HLX provider migrations are atomic with the loader and configuration and keep model data local."""
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from test_game_install import set_package_file
from test_update import UpdateFixture, Crash, m


class HlxUpdates(UpdateFixture):
    def setUp(self):
        super().setUp()
        self.hlx_release=self.root/'HLX';self.hlx_release.mkdir()
        self.contents={'DLSS.dll':b'qualified DLSS model','K.dll':b'qualified Preset K code','K.pak':b'Preset K kernels','K.bin':b'Preset K weights',
                       'K.ini':b'[Network]\r\nModel = K\r\nDeepReuse = Exact\r\n','FSR.dll':b'qualified FSR model','AMD.dll':b'qualified AMD companion',
                       'FULL.dll':b'qualified full FSR model','FULL.ini':b'[HLX]\r\nDeepReuse = exact\r\n'}
        for name,data in self.contents.items():(self.hlx_release/name).write_bytes(data)
        pin=lambda name:{'source':name,'sha256':m.digest(self.contents[name])}
        self.spec={'format':2,'version':'3.3.0','folder':'HLX','archive':{'sha256':m.digest(b'archive')},'model_inputs':{'dlss':m.digest(b'dlss input')},
                   'compilers':{},'suggested':'hlx-dlss','providers':{
            'hlx-dlss':{'api':'dlss','entry':'helixsr.dll','build':'network','log':'helixsr.log','settings':{'name':'helixsr.ini'},'files':{'helixsr.dll':pin('DLSS.dll')}},
            'hlx-dlss-k':{'api':'dlss','entry':'helixsr.dll','build':'preset-k','log':'helixsr.log','settings':dict(pin('K.ini'),name='helixsr.ini'),
                          'files':{'helixsr.dll':pin('K.dll'),'helixsr_modelk_kernels.pak':pin('K.pak'),'helixsr_modelk_weights.bin':pin('K.bin')}},
            'hlx-fsr4':{'api':'ffx','entry':m.DLL,'log':'HLX_FSR.log','files':{m.DLL:pin('FSR.dll'),'amd_fidelityfx_upscaler_dx12.amd.dll':pin('AMD.dll')}},
            'hlx-fsr4-full':{'api':'ffx','entry':m.DLL,'log':'HLX_FSR.log','settings':dict(pin('FULL.ini'),name='hlx_fsr4.ini'),
                             'files':{m.DLL:pin('FULL.dll'),'amd_fidelityfx_upscaler_dx12.amd.dll':pin('AMD.dll')}}}}
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
        self.assertEqual((self.game/old['target']).read_bytes(),b'FSR')
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

    def test_previously_installed_provider_can_be_selected_without_preparation_cache(self):
        self.install_old();self.select()
        self.run_quiet(m.configure,self.exe,upscaler='hlx-fsr4',package=self.new,helixsr_dir=self.hlx_release)
        shutil.rmtree(self.hlx_release)
        self.run_quiet(m.configure,self.exe,upscaler='hlx-dlss',package=self.new)
        self.assertEqual(self.record()['upscaler']['name'],'hlx-dlss')
        self.run_quiet(m.configure,self.exe,upscaler='hlx-fsr4',package=self.new)
        self.assertEqual(self.record()['upscaler']['name'],'hlx-fsr4')

    def test_changed_companion_blocks_entire_transaction(self):
        self.install_old();self.select('hlx-fsr4')
        path=self.game/'OptiScaler/custom/hlx-fsr4/ffx/amd_fidelityfx_upscaler_dx12.amd.dll'
        path.write_bytes(b'changed companion');before=self.snapshot();record=self.record()
        status,_=self.select('hlx-fsr4');self.assertEqual(status,'blocked')
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_restore_retains_runtime_log_evidence_and_removes_provider_directories(self):
        self.install_old();self.select('hlx-fsr4')
        log=self.game/self.record()['upscaler']['log'];log.write_bytes(b'own runtime active')
        self.run_quiet(m.restore,self.exe)
        self.assertFalse(log.exists());self.assertFalse(log.parent.exists())
        self.assertEqual((self.game/m.STATE/'runtime-logs/HLX_FSR.log').read_bytes(),b'own runtime active')
        self.assertOriginal()

    def test_unowned_provider_logs_are_not_overwritten(self):
        self.install_old();path=self.game/'OptiScaler/custom/hlx-fsr4/ffx/HLX_FSR.log';path.parent.mkdir(parents=True);path.write_bytes(b'original log')
        before=self.snapshot();self.assertEqual(self.select('hlx-fsr4')[0],'blocked');self.assertEqual(self.snapshot(),before)

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

    def test_preset_k_and_fsr4_full_bring_their_own_files_and_settings(self):
        # Preset K: its DLL, kernels and weights and HelixSR's helixsr.ini (Model = K) with Helix's own frame generation
        # off; HLX FSR 4 Full: its DLL, AMD's companion and hlx_fsr4.ini as HelixSR ships it. Rollback and Restore exact.
        self.install_old();before=self.snapshot()
        self.assertEqual(self.select('hlx-dlss-k')[0],'update')
        base=self.game/'OptiScaler/custom/hlx-dlss-k/dlss'
        self.assertEqual({p.name:p.read_bytes() for p in base.iterdir() if p.suffix!='.ini'},
                         {'helixsr.dll':self.contents['K.dll'],'helixsr_modelk_kernels.pak':self.contents['K.pak'],'helixsr_modelk_weights.bin':self.contents['K.bin']})
        ini=m.read_ini((base/'helixsr.ini').read_bytes())
        self.assertEqual((ini[('network','model')],ini[('dlssframegeneration','enabled')]),('K','false'))
        record=self.record()['upscaler'];self.assertEqual((record['name'],record['version'],Path(record['log']).name),('hlx-dlss-k','3.3.0','helixsr.log'))
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('upscalers','dx12upscaler')],'hlx-dlss-k')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.select('hlx-fsr4-full')[0],'update')
        base=self.game/'OptiScaler/custom/hlx-fsr4-full/ffx'
        self.assertEqual({p.name:p.read_bytes() for p in base.iterdir()},{m.DLL:self.contents['FULL.dll'],
                         'amd_fidelityfx_upscaler_dx12.amd.dll':self.contents['AMD.dll'],'hlx_fsr4.ini':self.contents['FULL.ini']})
        self.run_quiet(m.restore,self.exe);self.assertOriginal()

    def test_a_providers_edited_settings_survive_switches_and_stay_its_own(self):
        # Preset K's helixsr.ini is not Model E's: a switch between them carries neither file into the other folder, and
        # an edit (DeepReuse) is there again when the provider is selected again.
        self.install_old();self.select('hlx-dlss-k')
        k=self.game/'OptiScaler/custom/hlx-dlss-k/dlss/helixsr.ini';k.write_bytes(k.read_bytes().replace(b'Exact',b'1:2'))
        self.run_quiet(m.configure,self.exe,upscaler='hlx-dlss',package=self.new,helixsr_dir=self.hlx_release)
        e=m.read_ini((self.game/'OptiScaler/custom/hlx-dlss/dlss/helixsr.ini').read_bytes())
        self.assertNotIn(('network','model'),e);self.assertEqual(e[('dlssframegeneration','enabled')],'false')
        full=self.game/'OptiScaler/custom/hlx-fsr4-full/ffx/hlx_fsr4.ini'
        self.run_quiet(m.configure,self.exe,upscaler='hlx-fsr4-full',package=self.new,helixsr_dir=self.hlx_release)
        full.write_bytes(full.read_bytes().replace(b'exact',b'1:4'))
        for name in ('hlx-dlss-k','hlx-fsr4-full'):
            self.run_quiet(m.configure,self.exe,upscaler=name,package=self.new,helixsr_dir=self.hlx_release)
        self.assertEqual(m.read_ini(k.read_bytes())[('network','deepreuse')],'1:2')
        self.assertEqual(m.read_ini(full.read_bytes())[('hlx','deepreuse')],'1:4')
        m.restore(self.exe);self.assertOriginal()

    def test_every_provider_installs_fresh_and_names_its_recipe_family(self):
        for name,family in (('hlx-dlss','helixsr'),('hlx-dlss-k','helixsr'),('hlx-fsr4','hlx-fsr4'),('hlx-fsr4-full','hlx-fsr4')):
            with self.subTest(provider=name):
                self.assertEqual(m.hlx.recipe_name(name),family)
                self.run_quiet(m.install,self.new,self.exe,route='opti',upscaler=name,helixsr_dir=self.hlx_release)
                record=self.record()['upscaler'];self.assertEqual(record['name'],name)
                self.assertTrue((self.game/record['target']).is_file())
                _,out=self.run_quiet(m.status,self.exe);self.assertIn('Upscaler: '+m.hlx.NAMES[name]+' 3.3.0',out)
                m.restore(self.exe);self.assertOriginal()
        self.assertEqual(m.hlx.recipe_name('fsr4'),'fsr4')

    def test_the_suggested_upscaler_is_model_e_once_it_is_prepared(self):
        # No upscaler named: HLX DLSS Model E when it is prepared on this computer, FSR 4 otherwise; a named one is kept.
        for name in (None,'auto'):
            self.assertEqual(self.run_quiet(m.chosen_upscaler,self.new,name,self.hlx_release),
                             ('hlx-dlss','Suggested upscaler, prepared on this computer: HLX DLSS Model E.\n'))
        (self.hlx_release/'DLSS.dll').unlink()
        found,out=self.run_quiet(m.chosen_upscaler,self.new,None,self.hlx_release)
        self.assertEqual(found,'fsr4');self.assertIn('HLX DLSS Model E is suggested once it is prepared',out)
        self.assertEqual(self.run_quiet(m.chosen_upscaler,self.new,'hlx-fsr4',self.hlx_release),('hlx-fsr4',''))
        # A package without the Helix catalog suggests nothing else and says nothing.
        self.assertEqual(self.run_quiet(m.chosen_upscaler,self.package,None),('fsr4',''))

    def test_rollback_preserves_later_setting_ownership(self):
        self.install_old();self.select();m.configure(self.exe,factor=2)
        record=self.record();wanted=next(x for x in record['ini_changes'] if x['key']=='InterpolationCount')
        self.run_quiet(m.rollback,self.exe)
        self.assertIn(wanted,self.record()['ini_changes'])


if __name__=='__main__':unittest.main()
