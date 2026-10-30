# SPDX-License-Identifier: MIT
"""A release can migrate its integration DLL, defaults and launcher fields in one recoverable operation."""
import json
import unittest
from unittest.mock import patch
from test_update import UpdateFixture, Crash, m
from test_game_install import set_package_file


class IntegrationUpdateTests(UpdateFixture):
    def setUp(self):
        super().setUp()
        set_package_file(self.package,'opti/OptiScaler.dll',b'custom OptiScaler old')
        set_package_file(self.new,'opti/OptiScaler.dll',b'custom OptiScaler new')
        set_package_file(self.new,'opti/OptiScaler.ini',b'; new defaults\n[NewVersion]\nNewDefault=auto\n[Upscalers]\nDx12Upscaler=auto\n')

    def install_old(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)

    def test_loader_migration_does_not_replace_an_unowned_mod(self):
        self.install_old();(self.game/'winmm.dll').write_bytes(b'other mod');before=self.snapshot()
        status,_=self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertEqual(status,'blocked');self.assertEqual(self.snapshot(),before)

    def test_integration_defaults_and_loader_change_round_trip(self):
        self.install_old();before=self.snapshot()
        status,out=self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertEqual(status,'update');self.assertEqual((self.game/'winmm.dll').read_bytes(),b'custom OptiScaler new')
        self.assertEqual((self.game/'dxgi.dll').read_bytes(),b'opti')
        self.assertEqual(self.record()['opti_owner'],'winmm.dll')
        ini=m.read_ini((self.game/'OptiScaler.ini').read_bytes())
        self.assertEqual(ini[('newversion','newdefault')],'auto')
        self.assertEqual(ini[('upscalers','dx12upscaler')],m.read_ini(before['OptiScaler.ini'])[('upscalers','dx12upscaler')])
        self.assertIn('winmm=n,b',self.config.read_text());self.assertNotIn('dxgi=n,b',self.config.read_text())
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll');m.restore(self.exe);self.assertOriginal()

    def test_loader_change_removes_even_an_original_override_until_restore(self):
        doc=json.loads(self.config.read_text());doc['123']['enviromentOptions'].append(dict(key='WINEDLLOVERRIDES',value='dxgi=n,b'))
        self.config.write_text(json.dumps(doc));self.original_config_bytes=self.config.read_bytes();self.original_config=json.loads(self.original_config_bytes)
        self.install_old();self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertNotIn('dxgi=n,b',self.config.read_text());self.assertIn('winmm=n,b',self.config.read_text())
        m.restore(self.exe);self.assertOriginal()

    def test_interruption_after_launcher_write_recovers_both_resources(self):
        self.install_old();before=self.snapshot();real=m.write
        def crash(path,*args,**kwargs):
            result=real(path,*args,**kwargs)
            if path==self.config:raise Crash()
            return result
        with patch.object(m,'write',side_effect=crash):
            with self.assertRaises(Crash):self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.assertNotIn('pending_update',self.record())

    def test_retry_after_interruption_keeps_a_complete_rollback_generation(self):
        self.install_old();before=self.snapshot();real=m.write
        def crash(path,*args,**kwargs):
            if path==self.config:raise Crash()
            return real(path,*args,**kwargs)
        with patch.object(m,'write',side_effect=crash):
            with self.assertRaises(Crash):self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)

    def test_corrupt_launcher_snapshot_blocks_rollback_before_any_runtime_write(self):
        self.install_old();self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        state=self.game/m.STATE;record=self.record();before=self.snapshot()
        saved=state/m.GENERATIONS/record['generations'][-1]['id']/'external/0';saved.write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError,'launcher checksum'):
            self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_later_unrelated_launcher_entry_survives_rollback(self):
        self.install_old();before=self.snapshot();self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        doc=json.loads(self.config.read_text());doc['another']={'argument':'later'};self.config.write_text(json.dumps(doc))
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual(json.loads(self.config.read_text())['another'],{'argument':'later'})
        after=self.snapshot();before.pop('launcher');after.pop('launcher');self.assertEqual(after,before)

    def test_later_ini_choices_survive_integration_rollback(self):
        self.install_old();self.run_quiet(m.update,self.exe,self.new)
        ini=self.game/'OptiScaler.ini';ini.write_bytes(m.patch_ini(ini.read_bytes(),{('NewVersion','UserAdded'):'yes',('Unrelated','Value'):'later'}))
        self.run_quiet(m.rollback,self.exe)
        values=m.read_ini(ini.read_bytes());self.assertEqual(values[('unrelated','value')],'later')
        self.assertEqual(values[('newversion','useradded')],'yes');self.assertNotIn(('newversion','newdefault'),values)


if __name__=='__main__':unittest.main()
