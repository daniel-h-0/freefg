# SPDX-License-Identifier: MIT
"""Selected-provider updates share core update recovery, preserve selection, and identify archive revisions."""
import json
import os
import unittest
from unittest.mock import patch
from test_update import UpdateFixture, OLD, NEW, Crash, m
from test_game_install import set_package_file
from test_helixsr_install import BASE, H, built, make_release, add_pins

NEW_BASE=BASE+b' newer official revision'


class ComponentUpdateTests(UpdateFixture):
    def setUp(self):
        super().setUp()
        cache=patch.dict(os.environ,{'XDG_CACHE_HOME':str(self.root/'cache')});cache.start();self.addCleanup(cache.stop)
        add_pins(self.package)
        add_pins(self.new,releases={m.digest(BASE):'2.0.0',m.digest(NEW_BASE):'2.0.0'},archive=b'new official archive')
        pins=json.loads((self.new/'dependencies.json').read_text())
        pins['helixsr']['PreferredBaseHash']=m.digest(NEW_BASE)
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode())
        self.old_release=make_release(self.root/'HelixSR-2.0.0',built())
        self.next_release=make_release(self.root/'HelixSR-next',built(NEW_BASE))

    def install_helix(self):
        m.install(self.package,self.exe,route='opti',upscaler='helixsr',helixsr_dir=self.old_release)

    def test_all_updates_both_components_and_rolls_them_back(self):
        self.install_helix();m.configure(self.exe,percent=67,factor=2)
        before=self.snapshot();provider=self.record()['upscaler']
        status,_=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'update')
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),built(NEW_BASE))
        after=self.snapshot()
        for name in ('OptiScaler.ini','OptiScaler/helixsr.ini','BC250-XeFG/settings.ini','launcher'):
            self.assertEqual(after[name],before[name],name)
        record=self.record();self.assertEqual(record['package'],NEW)
        self.assertEqual(record['upscaler']['source_archive_sha256'],m.digest(b'new official archive'))
        self.assertEqual(record['upscaler']['version'],'2.0.0')
        self.assertEqual(record['components']['upscaler']['sha256'],m.digest(built(NEW_BASE)))
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record()['upscaler'],provider)
        m.restore(self.exe);self.assertOriginal()

    def test_upscaler_only_keeps_core_version_and_bytes(self):
        self.install_helix();before=self.snapshot()
        status,_=self.run_quiet(m.update,self.exe,self.new,component='upscaler')
        self.assertEqual(status,'update');self.assertEqual(self.record()['package'],OLD)
        after=self.snapshot();changed={name for name in after if after[name]!=before.get(name)}
        self.assertEqual(changed,{'OptiScaler/'+m.DLL})
        self.assertEqual(self.record()['components']['core']['package'],OLD)
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)

    def test_core_only_does_not_advance_the_upscaler(self):
        self.install_helix();provider=self.record()['upscaler']
        status,_=self.run_quiet(m.update,self.exe,self.new,component='core')
        self.assertEqual(status,'update');self.assertEqual(self.record()['package'],NEW)
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),built())
        self.assertEqual(self.record()['upscaler'],provider)

    def test_current_provider_needs_no_prepared_release_folder(self):
        self.install_helix();self.run_quiet(m.update,self.exe,self.new)
        with patch.object(m.upscaler_updates.helixsr,'candidates',return_value=[]):
            status,_=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'current')

    def test_core_rollback_keeps_a_later_provider_switch(self):
        self.install_helix()
        self.run_quiet(m.update,self.exe,self.new,component='core')
        self.run_quiet(m.configure,self.exe,upscaler='fsr4',package=self.new)
        provider=self.record()['upscaler'];data=(self.game/'OptiScaler'/m.DLL).read_bytes()
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.record()['upscaler'],provider)
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),data)
        self.assertEqual(self.record()['components']['upscaler']['provider'],'fsr4')
        self.assertEqual(self.record()['components']['core']['package'],OLD)

    def test_invalid_component_recovery_metadata_blocks_before_writes(self):
        self.install_helix();self.run_quiet(m.update,self.exe,self.new)
        before=self.snapshot();record=self.record()
        path=self.game/m.STATE/m.GENERATIONS/record['generations'][-1]['id']/'generation.json'
        generation=json.loads(path.read_text());generation['metadata_before']={'unknown':'bad'}
        path.write_text(json.dumps(generation))
        with self.assertRaisesRegex(ValueError,'component metadata'):
            self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_unbuilt_revision_defers_provider_but_core_can_finish(self):
        self.install_helix();make_release(self.next_release,NEW_BASE)
        before=self.snapshot();provider=self.record()['upscaler']
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'partial');self.assertIn('Prepare HelixSR',out)
        self.assertEqual(self.record()['package'],NEW);self.assertEqual(self.record()['upscaler'],provider)
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),built())
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)

    def test_unbuilt_upscaler_only_operation_changes_nothing(self):
        self.install_helix();make_release(self.next_release,NEW_BASE)
        before=self.snapshot();record=self.record()
        status,_=self.run_quiet(m.update,self.exe,self.new,component='upscaler')
        self.assertEqual(status,'deferred');self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_changed_provider_is_preserved(self):
        self.install_helix();path=self.game/'OptiScaler'/m.DLL;path.write_bytes(b'user provider')
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'partial');self.assertEqual(path.read_bytes(),b'user provider')
        self.assertIn('HelixSR not updated',out)

    def test_same_version_reissue_needs_an_unambiguous_preferred_revision(self):
        self.install_helix();pins=json.loads((self.new/'dependencies.json').read_text());pins['helixsr'].pop('PreferredBaseHash')
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode())
        before=self.snapshot()
        status,out=self.run_quiet(m.update,self.exe,self.new,component='upscaler')
        self.assertEqual(status,'deferred');self.assertIn('preferred archive revision',out);self.assertEqual(self.snapshot(),before)

    def test_new_adapter_is_not_treated_as_a_compatible_dll(self):
        self.install_helix();pins=json.loads((self.new/'dependencies.json').read_text())
        pins['upscalers']={'helixsr':{'adapter':'hlx-ngx-new-layout'}}
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode());before=self.snapshot()
        status,out=self.run_quiet(m.update,self.exe,self.new,component='upscaler')
        self.assertEqual(status,'deferred');self.assertIn('newer integration adapter',out);self.assertEqual(self.snapshot(),before)

    def test_interruption_after_provider_write_restores_prior_component(self):
        self.install_helix();before=self.snapshot();provider=self.record()['upscaler'];real=m.write
        def crash(path,*args,**kwargs):
            result=real(path,*args,**kwargs)
            if path==self.game/'OptiScaler'/m.DLL:raise Crash()
            return result
        with patch.object(m,'write',side_effect=crash):
            with self.assertRaises(Crash):self.run_quiet(m.update,self.exe,self.new)
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record()['upscaler'],provider)
        self.assertEqual(self.record()['package'],OLD)


if __name__=='__main__':unittest.main()
