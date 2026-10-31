# SPDX-License-Identifier: MIT
import copy
import unittest
from pathlib import Path
from unittest.mock import patch
from test_update import UpdateFixture,m


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
