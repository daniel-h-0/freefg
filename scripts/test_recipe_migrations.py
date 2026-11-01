# SPDX-License-Identifier: MIT
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from test_update import NEW,OLD,UpdateFixture,m


class RecipeMigrationTests(UpdateFixture):
    def test_gta_refresh_writes_require_argument_with_exact_rollback(self):
        # GTA V Enhanced's recipe sets [BC250] RequireArgument=-nobattleye: an installation of an earlier release gets it
        # from an explicit refresh; rollback and Restore take it out again.
        rm=m.recipes_module()
        catalog=rm.load(Path(__file__).resolve().parents[1]/'packaging/recipes/recipes.json')
        recipe=copy.deepcopy(next(v for v in catalog['verified'] if '3240220' in v['match'].get('steam',[])))
        self.assertEqual(recipe['ini']['BC250.RequireArgument'],'-nobattleye')
        m.install(self.package,self.exe,route='opti',fg_input='upscaler');before=self.snapshot()
        def ini():
            return m.read_ini((self.game/'OptiScaler.ini').read_bytes())
        self.assertNotIn(('bc250','requireargument'),ini())
        with patch.object(m,'recipe_for',return_value=(rm,recipe,[],[],{},[])):
            result,_=self.run_quiet(m.update,self.exe,self.new,refresh_recipe=True)
        self.assertEqual(result,'update');self.assertEqual(ini()[('bc250','requireargument')],'-nobattleye')
        self.assertIn('-nobattleye',self.config.read_text())
        # A refresh that comes with a release update is that update's generation.
        self.assertEqual([g['kind'] for g in self.record()['generations']],['release'])
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        with patch.object(m,'recipe_for',return_value=(rm,recipe,[],[],{},[])):
            self.assertEqual(self.run_quiet(m.update,self.exe,self.new,refresh_recipe=True)[0],'update')
        m.restore(self.exe);self.assertOriginal();self.assertNotIn(('bc250','requireargument'),ini())

    def test_explicit_refresh_migrates_input_and_arguments_with_exact_rollback(self):
        m.install(self.package,self.exe,route='opti',fg_input='fsrfg');before=self.snapshot();record=self.record()
        recipe=dict(title='Fixture game',route='opti',fg_input='upscaler',evidence='gameplay',ini={},
                    launch_args=['-dx12'],game_settings=[],manual_steps=['Select FSR Native; Quality failed on the tested build.'])
        with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
            plan=m.update_plan(self.new,self.game,record,refresh_recipe=True)
            self.assertEqual(plan['status'],'update');self.assertTrue(any('FSR Native' in n for n in plan['notes']))
            self.assertEqual(self.snapshot(),before)
            result,_=self.run_quiet(m.update,self.exe,self.new,refresh_recipe=True)
        self.assertEqual(result,'update');self.assertEqual(self.record()['fg_input'],'upscaler')
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('framegen','fginput')],'upscaler')
        self.assertIn('-dx12',self.config.read_text())
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.record().get('fg_input'),record.get('fg_input'))
        m.restore(self.exe);self.assertOriginal()

    def refresh(self,recipe):
        with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
            return self.run_quiet(m.update,self.exe,self.new,refresh_recipe=True)

    def test_a_refresh_within_a_release_keeps_the_way_back_to_the_release_before(self):
        # 1.3.0's GTA case: an update, then a recipe refresh on that release. The refresh is its own kind of generation:
        # Rollback undoes it, then the update, each named.
        recipe=dict(title='Fixture game',route='opti',fg_input='upscaler',evidence='gameplay',ini={'BC250.RequireArgument':'-nobattleye'},
                    launch_args=['-dx12'],game_settings=[])
        m.install(self.package,self.exe,route='opti',fg_input='upscaler');original=self.snapshot()
        self.run_quiet(m.update,self.exe,self.new);updated=self.snapshot()
        with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
            plan=m.update_plan(self.new,self.game,self.record(),refresh_recipe=True)
        self.assertEqual((plan['status'],plan.get('operation')),('update','recipe'))
        self.assertEqual(m.plan_lines(plan)[0],'Refresh the recipe within '+NEW+':')
        result,out=self.refresh(recipe)
        self.assertEqual(result,'update');self.assertIn('Recipe refreshed within '+NEW+'.',out);self.assertIn('-dx12',self.config.read_text())
        self.assertEqual([(g['kind'],g['from'],g['to']) for g in self.record()['generations']],[('release',OLD,NEW),('recipe',NEW,NEW)])
        self.assertEqual(len(list((self.game/m.STATE/m.GENERATIONS).iterdir())),2)
        _,out=self.run_quiet(m.status,self.exe)
        self.assertIn('install.py rollback undoes the recipe refresh of',out);self.assertIn('After that, install.py rollback undoes the update from '+OLD,out)
        _,out=self.run_quiet(m.rollback,self.exe)
        self.assertIn('Rolled back the recipe refresh of',out);self.assertIn('install.py rollback can still undo the update from '+OLD,out)
        self.assertEqual(self.snapshot(),updated);self.assertEqual(self.record()['package'],NEW)
        _,out=self.run_quiet(m.rollback,self.exe)
        self.assertIn('Rolled back from '+NEW+' to '+OLD,out);self.assertEqual(self.snapshot(),original)
        with self.assertRaisesRegex(ValueError,'No update to roll back'):m.rollback(self.exe)
        m.restore(self.exe);self.assertOriginal()

    def test_a_second_refresh_replaces_only_the_first(self):
        # The newest refresh is kept beside the update; the first refresh's values stay after both rollbacks, as a later
        # edit would, and Restore still returns every original.
        first=dict(title='Fixture game',route='opti',fg_input='upscaler',evidence='gameplay',ini={'BC250.RequireArgument':'-nobattleye'},
                   launch_args=['-dx12'],game_settings=[])
        second=dict(first,ini=dict(first['ini'],**{'Hotfix.ColorResourceBarrier':'4'}))
        m.install(self.package,self.exe,route='opti',fg_input='upscaler')
        self.run_quiet(m.update,self.exe,self.new);self.refresh(first);refreshed=self.snapshot()
        self.assertEqual(self.refresh(second)[0],'update')
        self.assertEqual([g['kind'] for g in self.record()['generations']],['release','recipe'])
        self.assertEqual(len(list((self.game/m.STATE/m.GENERATIONS).iterdir())),2)
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),refreshed)
        _,out=self.run_quiet(m.rollback,self.exe)
        self.assertIn('Rolled back from '+NEW+' to '+OLD,out);self.assertEqual(self.record()['package'],OLD)
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('bc250','requireargument')],'-nobattleye')
        m.restore(self.exe);self.assertOriginal()

    def test_status_and_rollback_name_an_earlier_builds_refresh_as_a_change(self):
        # 1.3.0 recorded a refresh within a release as a release update: from and to name the same release.
        recipe=dict(title='Fixture game',route='opti',fg_input='upscaler',evidence='gameplay',ini={'BC250.RequireArgument':'-nobattleye'},
                    launch_args=[],game_settings=[])
        m.install(self.package,self.exe,route='opti',fg_input='upscaler');self.run_quiet(m.update,self.exe,self.new)
        self.refresh(recipe);record=self.record()
        record['generations']=[dict(record['generations'][-1],kind='release')]
        (self.game/m.STATE/'state.json').write_text(json.dumps(record,indent=2)+'\n')
        _,out=self.run_quiet(m.status,self.exe);self.assertIn('install.py rollback undoes the change of',out);self.assertIn('within '+NEW,out)
        _,out=self.run_quiet(m.rollback,self.exe);self.assertIn('Rolled back the change of',out)
        self.assertNotIn(('bc250','requireargument'),m.read_ini((self.game/'OptiScaler.ini').read_bytes()))

    def test_no_qualified_recipe_refuses_before_writing(self):
        m.install(self.package,self.exe,route='opti');before=self.snapshot()
        with patch.object(m,'recipe_for',return_value=None):
            result,_=self.run_quiet(m.update,self.exe,self.new,refresh_recipe=True)
        self.assertEqual(result,'blocked');self.assertEqual(self.snapshot(),before)

    def test_obsolete_pending_game_settings_are_retired_without_rewriting_them(self):
        m.install(self.package,self.exe,route='opti');record=self.record()
        record['game_settings']=[dict(status='pending',file='obsolete.ini',format='ini',section='Old',values={'FG':'On'},path=None)]
        recipe=dict(title='Fixture',route='opti',fg_input='dlssg',evidence='gameplay',ini={},launch_args=[],game_settings=[])
        with patch.object(m,'recipe_for',return_value=(m.recipes_module(),recipe,[],[],{},[])):
            _,metadata,_=m.recipe_migration(self.new,self.game,record,(self.game/'OptiScaler.ini').read_bytes())
        self.assertFalse(metadata['game_settings'][0]['active'])
        updated=dict(record,**metadata)
        with patch.object(m,'recipes_module',side_effect=AssertionError('No game setting should be read')):
            self.assertEqual(m.apply_pending_settings(self.exe,self.game,updated),([],[]))


if __name__=='__main__':unittest.main()
