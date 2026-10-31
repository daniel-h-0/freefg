# SPDX-License-Identifier: MIT
"""Migration owns deltas, not whole launcher files or the user's later additions."""
import json
import unittest
from unittest.mock import patch
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

    def test_a_removed_entry_blocks_with_its_remedy(self):
        m.install(self.package,self.exe,route='opti')
        self.config.write_text(json.dumps({}))
        with self.assertRaisesRegex(ValueError,r'Launcher entry is no longer present; use Restore, then Install again: .* \(Heroic game 123 no longer exists\)'):
            self.planned()

    def test_undoing_skips_an_entry_that_is_gone(self):
        # Undoing (gone given) reports an entry or file removed since instead of refusing; installing still refuses.
        m.install(self.package,self.exe,route='opti');plan=self.planned();lm.apply(plan['operations'],m.write)
        self.config.write_text(json.dumps({'other':{}}))
        gone=[];self.assertEqual(lm.prepare_apply(plan['operations'],reverse=True,gone=gone),[(self.config,self.config.read_bytes(),self.config.read_bytes())])
        self.assertEqual(gone,['Launcher entry no longer present, nothing to undo: '+str(self.config)+' (Heroic game 123 no longer exists)'])
        with self.assertRaises(lm.lc.Missing):lm.prepare_apply(plan['operations'],reverse=True)
        self.config.unlink();gone=[]
        self.assertEqual(lm.prepare_apply(plan['operations'],reverse=True,gone=gone),[])
        self.assertEqual(gone,['Launcher entry no longer present, nothing to undo: '+str(self.config)])
        # Steam: an app entry whose launch options went (Steam's own app settings reset) has nothing to undo either.
        config=self.root/'localconfig.vdf'
        config.write_bytes(b'"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "100" { "LastPlayed" "1" } } } } } }')
        row=dict(target=dict(launcher='steam',path=str(config),id='100'),before={'LaunchOptions':'A=1 %command%'},
                 after={'LaunchOptions':'B=2 %command%'})
        gone=[];lm.apply([row],m.write,reverse=True,gone=gone)
        self.assertEqual(gone,['Launcher entry no longer present, nothing to undo: '+str(config)+' (no launch options for Steam app 100)'])
        self.assertNotIn(b'LaunchOptions',config.read_bytes())

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

    def test_a_1_2_0_record_gets_its_required_argument_once(self):
        # GTA V Enhanced as 1.2.0 installed it: -nobattleye among launch_args, kept out of the entry by the user's -dx12.
        # The update adds it, as a required argument, once; Rollback and Restore take it out again.
        doc=json.loads(self.config.read_text());doc['123']['launcherArgs']='~/saves -dx12';self.config.write_text(json.dumps(doc))
        original=self.config.read_bytes()
        m.install(self.package,self.exe,route='opti')
        record=self.record();record.update(launch_args=['-nobattleye'],launch_args_added=[]);record.pop('required_args',None)
        row=record['launchers'][0];row['before']['launcherArgs']=row['after']['launcherArgs']='~/saves -dx12'
        (self.game/m.STATE/'state.json').write_text(json.dumps(record))
        self.assertEqual(m.record_arguments(record),([],['-nobattleye']))
        args=lambda:json.loads(self.config.read_text())['123']['launcherArgs']
        self.assertEqual(self.run_quiet(m.update,self.exe,self.new)[0],'update')
        self.assertEqual(args(),'~/saves -dx12 -nobattleye')
        self.assertEqual(self.record()['launchers'][0]['after']['launcherArgs'],'~/saves -dx12 -nobattleye')
        self.assertEqual(self.run_quiet(m.update,self.exe,self.new)[0],'current');self.assertEqual(args(),'~/saves -dx12 -nobattleye')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(args(),'~/saves -dx12')
        self.run_quiet(m.update,self.exe,self.new);m.restore(self.exe)
        self.assertEqual(self.config.read_bytes(),original)

    def test_an_update_needs_a_lutris_entry_to_carry_the_required_argument(self):
        # GTA V Enhanced in Lutris under 1.2.0 ("Launch option not added"): Lutris's arguments are the user's, so the
        # update needs attention until the entry has it.
        from vendor import yaml
        self.config.unlink()
        lutris=self.root/'.config/lutris/games/game.yml'
        doc=dict(game={'exe':str(self.exe),'args':'-dx12'},system={'env':{}});m.write(lutris,yaml.safe_dump(doc).encode())
        m.install(self.package,self.exe,route='opti')
        record=self.record();record['launch_args']=['-nobattleye'];record.pop('required_args',None)
        (self.game/m.STATE/'state.json').write_text(json.dumps(record))
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'blocked');self.assertIn('In Lutris, add -nobattleye to the game\'s Arguments',out)
        doc['game']['args']='-dx12 -nobattleye';m.write(lutris,yaml.safe_dump(doc).encode())
        self.assertEqual(self.run_quiet(m.update,self.exe,self.new)[0],'update')

    def test_recipe_refresh_keeps_a_required_argument_once(self):
        m.install(self.package,self.exe,route='opti')
        record=self.record();record.update(launch_args=['-nobattleye'],recipe=dict(title='GTA',launch_args=['-nobattleye']))
        record.pop('required_args',None)
        recipe=dict(title='GTA',route='opti',fg_input='upscaler',evidence='gameplay',ini={},launch_args=[],required_args=['-nobattleye'],
                    game_settings=[])
        def refreshed(record):
            with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
                return m.recipe_migration(self.new,self.game,record,(self.game/'OptiScaler.ini').read_bytes())[1]
        metadata=refreshed(record)
        self.assertEqual((metadata['launch_args'],metadata['required_args'],metadata['recipe']['required_args']),([],['-nobattleye'],['-nobattleye']))
        # An argument of the installation's own (a caller's, not the earlier recipe's) stays beside the recipe's.
        self.assertEqual(refreshed(dict(record,required_args=['-skipintro']))['required_args'],['-nobattleye','-skipintro'])

    def test_user_arguments_keep_their_text(self):
        # A migration adds or takes out only its own words: what the user wrote (a ~ the shell expands, quoting) stays.
        self.assertEqual(lm._arguments('~/mods -dx12','-dx12','-dx12 -nobattleye'),'~/mods -dx12 -nobattleye')
        self.assertEqual(lm._arguments("~/mods 'a b' -old",'-old',''),"~/mods 'a b'")
        self.assertEqual(lm._arguments('-dx11 ~/x','','-dx12 -nobattleye'),'-dx11 ~/x -nobattleye')  # the user's API switch stays
        self.assertEqual(lm._arguments('~/x','-a','-a'),'~/x')
        row={'launcher':'steam'}
        old={'LaunchOptions':'A=1 ~/bin/wrap %command% -dx12'};new={'LaunchOptions':'A=1 ~/bin/wrap %command% -dx12 -nobattleye'}
        self.assertEqual(lm.merge_fields(row,old,old,new)['LaunchOptions'],'A=1 ~/bin/wrap %command% -dx12 -nobattleye')

    def test_steam_tokens_and_quotes_are_preserved_when_policy_is_unchanged(self):
        row={'launcher':'steam'};before={'LaunchOptions':"env KEEP='two words' %command% --flag"}
        self.assertEqual(lm.merge_fields(row,before,before,before),before)

    def test_token_rollback_keeps_later_mods(self):
        old={'WINEDLLOVERRIDES':'dxgi=n,b','VK_LAYER_PATH':'/freefg:/user'}
        current={'WINEDLLOVERRIDES':'dxgi=n,b;user=n','VK_LAYER_PATH':'/freefg:/user:/later'}
        result=lm.merge_environment(current,old,{'VK_LAYER_PATH':'/user'},strict=False)
        self.assertEqual(result,{'WINEDLLOVERRIDES':'user=n','VK_LAYER_PATH':'/user:/later'})


if __name__=='__main__':unittest.main()
