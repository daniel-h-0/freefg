# SPDX-License-Identifier: MIT
"""Migration owns deltas, not whole launcher files or the user's later additions."""
import json
import unittest
from test_update import UpdateFixture, m
import launcher_migrations as lm


class LauncherMigrationTests(UpdateFixture):
    def planned(self, **kwargs):
        record=self.record()
        return lm.plan(record,self.game,'winmm.dll',cache=self.game/m.STATE/m.VKD3D_CACHE,**kwargs)

    def test_same_policy_does_not_touch_launcher_bytes(self):
        m.install(self.package,self.exe,route='opti')
        record=self.record()
        plan=lm.plan(record,self.game,'dxgi.dll',cache=self.game/m.STATE/m.VKD3D_CACHE)
        self.assertEqual(plan['operations'],[])
        self.assertEqual(plan['records'],record['launchers'])

    def test_loader_change_preserves_user_environment_and_rolls_back(self):
        m.install(self.package,self.exe,route='opti')
        doc=json.loads(self.config.read_text());doc['123']['enviromentOptions'] += [dict(key='USER_LATER',value='yes')]
        for row in doc['123']['enviromentOptions']:
            if row['key']=='WINEDLLOVERRIDES':row['value']+=';my_mod=n,b'
            if row['key']=='VK_INSTANCE_LAYERS':row['value']+=':VK_LAYER_USER'
        self.config.write_text(json.dumps(doc));before=json.loads(self.config.read_text())
        plan=self.planned();self.assertEqual(len(plan['operations']),1)
        lm.check(plan['operations']);lm.apply(plan['operations'],m.write)
        env=lm.environment(lm.lc.fields(self.record()['launchers'][0],self.config.read_bytes()),'heroic')
        self.assertEqual(env['WINEDLLOVERRIDES'],'my_mod=n,b;winmm=n,b')
        self.assertEqual(env['USER_LATER'],'yes');self.assertIn('VK_LAYER_USER',env['VK_INSTANCE_LAYERS'])
        # The permanent ledger must not claim ownership of USER_LATER.
        self.assertNotIn('USER_LATER',lm.environment(plan['records'][0]['after'],'heroic'))
        lm.apply(plan['operations'],m.write,reverse=True)
        self.assertEqual(json.loads(self.config.read_text()),before)

    def test_scalar_user_conflict_refuses_before_write(self):
        m.install(self.package,self.exe,route='opti')
        doc=json.loads(self.config.read_text())
        for row in doc['123']['enviromentOptions']:
            if row['key']=='XEFG_WAVE_CONFIG':row['value']='user-waves.txt'
        self.config.write_text(json.dumps(doc));before=self.config.read_bytes()
        with self.assertRaisesRegex(ValueError,'XEFG_WAVE_CONFIG'):
            lm.plan(self.record(),self.game/'new-location','dxgi.dll')
        self.assertEqual(self.config.read_bytes(),before)

    def test_recovery_preserves_another_games_later_edit(self):
        m.install(self.package,self.exe,route='opti');plan=self.planned()
        lm.apply(plan['operations'],m.write)
        doc=json.loads(self.config.read_text());doc['another-game']={'quality':'new'};self.config.write_text(json.dumps(doc))
        lm.apply(plan['operations'],m.write,reverse=True)
        self.assertEqual(json.loads(self.config.read_text())['another-game'],{'quality':'new'})
        self.assertEqual(lm.lc.fields(self.record()['launchers'][0],self.config.read_bytes()),plan['operations'][0]['before'])

    def test_late_file_change_blocks_the_commit_preflight(self):
        m.install(self.package,self.exe,route='opti');plan=self.planned()
        self.config.write_bytes(self.config.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'changed since planning'):lm.check(plan['operations'])

    def test_shared_file_locks_are_reentrant(self):
        m.install(self.package,self.exe,route='opti')
        with lm.locked(self.record()['launchers']):
            with lm.locked(self.record()['launchers']):self.assertTrue(lm._held)
        self.assertFalse(lm._held)

    def test_existing_heroic_arguments_become_the_original_for_new_argument_ownership(self):
        m.install(self.package,self.exe,route='opti')
        doc=json.loads(self.config.read_text());doc['123']['launcherArgs']='--user-option';self.config.write_text(json.dumps(doc))
        plan=self.planned(args=['-dx12'])
        self.assertEqual(plan['records'][0]['before']['launcherArgs'],'--user-option')
        lm.apply(plan['operations'],m.write)
        self.assertEqual(json.loads(self.config.read_text())['123']['launcherArgs'],'--user-option -dx12')
        lm.apply(plan['operations'],m.write,reverse=True)
        self.assertEqual(json.loads(self.config.read_text())['123']['launcherArgs'],'--user-option')

    def test_steam_tokens_and_quotes_are_preserved_when_policy_is_unchanged(self):
        row={'launcher':'steam'};before={'LaunchOptions':"env KEEP='two words' %command% --flag"}
        self.assertEqual(lm.merge_fields(row,before,before,before),before)

    def test_token_rollback_keeps_later_mods(self):
        old={'WINEDLLOVERRIDES':'dxgi=n,b','VK_LAYER_PATH':'/freefg:/user'}
        current={'WINEDLLOVERRIDES':'dxgi=n,b;user=n','VK_LAYER_PATH':'/freefg:/user:/later'}
        result=lm.merge_environment(current,old,{'VK_LAYER_PATH':'/user'},strict=False)
        self.assertEqual(result,{'WINEDLLOVERRIDES':'user=n','VK_LAYER_PATH':'/user:/later'})


if __name__=='__main__':unittest.main()
