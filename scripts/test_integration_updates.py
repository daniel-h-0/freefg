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

    def test_loader_names_no_game_loads_are_refused(self):
        # OptiScaler.dll and OptiScaler.asi are not loaded by a game itself: moving there would stop OptiScaler loading.
        self.install_old();before=self.snapshot()
        for loader in ('OptiScaler.asi','OptiScaler.dll'):
            status,out=self.run_quiet(m.update,self.exe,self.new,loader=loader)
            self.assertEqual(status,'blocked');self.assertIn('No game loads '+loader+' by itself',out)
        self.assertEqual(self.snapshot(),before)

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

    def test_manual_launch_settings_follow_a_loader_change_and_its_rollback(self):
        # An installation in a launcher this installer does not edit (an accepted no-launcher refusal).
        self.config.unlink()
        m.install(self.package,self.exe,route='opti',accept=('no-launcher',))
        self.assertEqual(self.record()['manual_launch']['env']['WINEDLLOVERRIDES'],'dxgi=n,b')
        status,out=self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertEqual(status,'update');self.assertEqual(self.record()['manual_launch']['env']['WINEDLLOVERRIDES'],'winmm=n,b')
        self.assertIn('  launch settings change; set these in the game’s launcher (this installer does not edit it):\n    WINEDLLOVERRIDES=winmm=n,b\n',out)
        self.assertIn('\nIn your launcher: change the game’s launch settings to those this update lists (in Setup: the game’s Launch settings, Show…).\n',out)
        self.assertFalse(self.config.exists())
        _,out=self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.record()['manual_launch']['env']['WINEDLLOVERRIDES'],'dxgi=n,b')
        self.assertIn('In your launcher: set the game’s launch settings back to those listed below (in Setup: the game’s Launch settings, Show…).\n'
                      '    WINEDLLOVERRIDES=dxgi=n,b\n',out)
        # An update that leaves them as they are does not name them.
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'update');self.assertNotIn('launch settings',out)
        _,out=self.run_quiet(m.restore,self.exe)
        self.assertIn('In your launcher: remove the launch settings listed below from the game (in Setup: the game’s Launch settings, Show…).\n'
                      '    WINEDLLOVERRIDES=dxgi=n,b\n',out)
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data,name)

    def test_manual_settings_changes_are_named_exactly_with_their_events(self):
        # Update and Rollback say exactly what to replace in the launcher this installer does not edit, and emit the
        # settings (manual: replace, with the earlier ones) and the step (where: launcher).
        self.config.unlink()
        m.install(self.package,self.exe,route='opti',accept=('no-launcher',))
        before=self.record()['manual_launch']
        def run(function,*args,**kwargs):
            with patch.object(m,'EVENTS',True):_,out=self.run_quiet(function,*args,**kwargs)
            return out,[json.loads(line[len(m.EVENT_PREFIX):]) for line in out.splitlines() if line.startswith(m.EVENT_PREFIX)]
        out,events=run(m.update,self.exe,self.new,loader='winmm.dll')
        after=self.record()['manual_launch']
        self.assertIn('\n    Replace WINEDLLOVERRIDES=dxgi=n,b with WINEDLLOVERRIDES=winmm=n,b\n',out)
        self.assertEqual([(e['action'],e['settings'],e['previous']) for e in events if e['type']=='manual'],[('replace',after,before)])
        self.assertEqual([e['where'] for e in events if e['type']=='step'],['launcher'])
        out,events=run(m.rollback,self.exe)
        self.assertIn('\n    Replace WINEDLLOVERRIDES=winmm=n,b with WINEDLLOVERRIDES=dxgi=n,b\n',out)
        self.assertEqual([(e['action'],e['settings'],e['previous']) for e in events if e['type']=='manual'],[('replace',before,after)])
        self.assertEqual([e['text'] for e in events if e['type']=='step'],
                         ['In your launcher: set the game’s launch settings back to those listed below (in Setup: the game’s Launch settings, Show…).'])

    def test_first_manual_records_update_without_naming_unchanged_settings(self):
        # PR #8 recorded env and args only (GTA's -nobattleye among args): an update that leaves the launcher's settings
        # as they are names none and keeps the record's form.
        self.config.unlink()
        m.install(self.package,self.exe,route='opti',accept=('no-launcher',))
        record=self.record();record['manual_launch']={'env':record['manual_launch']['env'],'args':['-nobattleye']}
        record['launch_args']=['-nobattleye'];record.pop('required_args')
        (self.game/m.STATE/'state.json').write_text(json.dumps(record))
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'update');self.assertNotIn('launch settings',out)
        self.assertEqual(self.record()['manual_launch'],record['manual_launch'])
        # A change in them is named: the loader's override (the game's argument stays).
        status,out=self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertIn('    Replace WINEDLLOVERRIDES=dxgi=n,b with WINEDLLOVERRIDES=winmm=n,b\n',out);self.assertNotIn('Game arguments:',out)
        self.assertEqual(self.record()['manual_launch']['required_args'],['-nobattleye'])

    def test_a_launcher_entry_removed_after_an_update_never_blocks_its_undoing(self):
        # The user removes the game from Heroic after an update that changed its entry: Rollback puts the files back and
        # says the entry has nothing to undo; a later update that would change it needs attention (blocked, with the
        # remedy), and Restore still returns every original file.
        self.install_old();before={k:v for k,v in self.snapshot().items() if k!='launcher'}
        self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.config.write_text(json.dumps({}))
        _,out=self.run_quiet(m.rollback,self.exe)
        self.assertIn('Launcher entry no longer present, nothing to undo: '+str(self.config)+' (Heroic game 123 no longer exists)\n',out)
        self.assertEqual({k:v for k,v in self.snapshot().items() if k!='launcher'},before);self.assertEqual(json.loads(self.config.read_text()),{})
        status,out=self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertEqual(status,'blocked');self.assertIn('Launcher entry is no longer present; use Restore, then Install again',out)
        m.restore(self.exe)
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data,name)

    def test_an_interrupted_update_is_undone_when_its_launcher_file_is_gone(self):
        # The pending journal's recovery (here through Restore) undoes the files and reports the launcher file it cannot.
        self.install_old();real=m.write
        def crash(path,*args,**kwargs):
            result=real(path,*args,**kwargs)
            if path==self.config:raise Crash()
            return result
        with patch.object(m,'write',side_effect=crash):
            with self.assertRaises(Crash):self.run_quiet(m.update,self.exe,self.new,loader='winmm.dll')
        self.assertIn('pending_update',self.record())
        self.config.unlink()
        _,out=self.run_quiet(m.restore,self.exe)
        self.assertIn('was interrupted: undone, back to',out)
        self.assertIn('Launcher entry no longer present, nothing to undo: '+str(self.config)+'\n',out)
        record=self.record();self.assertEqual(record['status'],'restored');self.assertNotIn('pending_update',record)
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data,name)

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
