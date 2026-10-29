# SPDX-License-Identifier: MIT
"""In-place updates of an installed enabler-free package (install.py plan, update, rollback, pin, unpin): a fixture
release "freefg-1.1.4" installed, then a newer fixture package "freefg-1.1.5" whose add-on files differ, as 1.1.4 and
1.1.5 do (the proxy, shader files and the wave table). The update changes only those files, keeps the user's settings,
the original files, OptiScaler.ini and the launcher entry, rolls back byte for byte, and survives an interruption at any
of its writes; Restore still returns every original."""
import contextlib,io,json,shutil,unittest
from pathlib import Path
from unittest.mock import patch
from test_game_install import DEPENDENCIES,set_package_file,launcher_config,m
from test_proxy_install import ProxyFixture

OLD='freefg-1.1.4';NEW='freefg-1.1.5'
SETTINGS=b'; retain comment\n[BC250]\nResolutionMode=0\nResolutionPercent=75\nResolutionLimit=1080\nDownscaleFilter=0\nUpscaleFilter=0\nExact=1\n'
# What the newer release changes: its proxy, its wave table and a shader file, and one shader file it adds.
CHANGES={'payload/libxess_fg.dll':b'BC250 proxy 1.1.5','payload/BC250-XeFG/shaders/waves.txt':b'wave config 1.1.5',
         'payload/BC250-XeFG/shaders/0123456789abcdef.dxil':b'shader 1.1.5','payload/BC250-XeFG/shaders/fedcba9876543210.dxil':b'new shader'}

class Crash(BaseException):
    """A process killed part way: nothing after it runs (not an error the installer reports and cleans up after)."""

def set_name(package,name):
    manifest=json.loads((package/'manifest.json').read_text());manifest['name']=name;(package/'manifest.json').write_text(json.dumps(manifest))

def remove_package_file(package,name):
    manifest=json.loads((package/'manifest.json').read_text());del manifest['files'][name];(package/'manifest.json').write_text(json.dumps(manifest))
    (package/name).unlink()

class UpdateFixture(ProxyFixture):
    """The proxy fixture's package as release OLD (with the scaling controls, so configure writes settings.ini), and a
    copy of it as release NEW with CHANGES."""
    def setUp(self):
        super().setUp()
        set_package_file(self.package,'payload/BC250-XeFG/shaders/freefg-scaling.required',b'1\n')
        set_package_file(self.package,'payload/BC250-XeFG/settings.ini',SETTINGS)
        set_package_file(self.package,'payload/BC250-XeFG/shaders/0123456789abcdef.dxil',b'shader 1.1.4')
        set_name(self.package,OLD)
        self.new=self.newer(CHANGES)
        for context in (patch.object(m,'UPDATES_FROM',{OLD}),):
            context.start();self.addCleanup(context.stop)
    def newer(self,changes,name=NEW,folder='package-new',base=None):
        """A copy of the installed package (or of base) as another release: changes maps a package path to its new bytes
        (None: the release no longer has the file)."""
        package=self.root/folder;shutil.copytree(base or self.package,package);set_name(package,name)
        for path,data in changes.items():
            if data is None:remove_package_file(package,path)
            else:set_package_file(package,path,data)
        return package
    def snapshot(self):
        """Every file of the game folder outside the installation's state folders, and the launcher entry, as bytes."""
        files={p.relative_to(self.game).as_posix():p.read_bytes() for p in self.game.rglob('*')
               if p.is_file() and not p.relative_to(self.game).parts[0].startswith(m.STATE)}
        return dict(files,launcher=self.config.read_bytes())
    def settings(self):
        return m.read_ini((self.game/'BC250-XeFG/settings.ini').read_bytes())
    def run_quiet(self,function,*args,**kwargs):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):result=function(*args,**kwargs)
        return result,out.getvalue()

class UpdateTests(UpdateFixture):
    def test_update_replaces_only_the_addon_and_keeps_everything_else(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67,upscale='fsr1')
        before=self.snapshot();backups=sorted((self.game/m.STATE/'backups').iterdir());prepared=list(self.prepared)
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'update');self.assertIn('Updated to '+NEW,out)
        after=self.snapshot()
        for name,data in CHANGES.items():self.assertEqual(after[name.removeprefix('payload/')],data,name)
        changed={name for name in after if after[name]!=before.get(name)}
        self.assertEqual(changed,{name.removeprefix('payload/') for name in CHANGES})
        # The user's settings, OptiScaler.ini, the launcher entry and the original files' backups are untouched.
        self.assertEqual([self.settings()[('bc250',k)] for k in ['resolutionmode','resolutionpercent','upscalefilter']],['1','67','4'])
        self.assertEqual(after['OptiScaler.ini'],before['OptiScaler.ini']);self.assertEqual(after['launcher'],before['launcher'])
        self.assertEqual(sorted((self.game/m.STATE/'backups').iterdir()),backups)
        self.assertEqual(self.prepared,prepared)  # the runtime pins are the same: nothing downloaded
        record=self.record()
        self.assertEqual((record['package'],record['status'],len(record['generations'])),(NEW,'installed',1))
        self.assertNotIn('pending_update',record)
        # Each managed file is as the record says (settings.ini as configure left it: configure records no digest).
        for item in record['files']:
            if item['path']!='BC250-XeFG/settings.ini':self.assertEqual(m.file_digest(self.game,item['path']),item['after'],item['path'])

    def test_restore_after_an_update_returns_every_original(self):
        for route in ['opti','native']:
            with self.subTest(route=route):
                m.install(self.package,self.exe,route=route);m.configure(self.exe,percent=67)
                self.run_quiet(m.update,self.exe,self.new)
                m.restore(self.exe);self.assertOriginal()
                self.assertFalse((self.game/'BC250-XeFG').exists());self.assertFalse((self.game/'bc250_xefg_original.dll').exists())
                self.assertFalse((self.game/m.STATE/m.GENERATIONS).exists())
                # The settings the user chose are kept for the next Install, as after any Restore.
                m.install(self.package,self.exe,route=route);self.assertEqual(self.settings()[('bc250','resolutionpercent')],'67')
                m.restore(self.exe)

    def test_rollback_returns_to_the_earlier_release_byte_for_byte(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)
        before=self.snapshot();record=self.record()
        self.run_quiet(m.update,self.exe,self.new)
        _,out=self.run_quiet(m.rollback,self.exe)
        self.assertIn('Rolled back from '+NEW+' to '+OLD,out)
        self.assertEqual(self.snapshot(),before)
        after=self.record()
        self.assertEqual((after['package'],after.get('generations')),(OLD,[]))
        self.assertEqual(after['created_dirs'],record['created_dirs']);self.assertFalse(list((self.game/m.STATE/m.GENERATIONS).iterdir()))
        with self.assertRaisesRegex(ValueError,'No update to roll back'):m.rollback(self.exe)
        # Updated again, it is the newer release once more; Restore still returns the originals.
        self.run_quiet(m.update,self.exe,self.new);self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),CHANGES['payload/libxess_fg.dll'])
        m.restore(self.exe);self.assertOriginal()

    def test_rollback_keeps_settings_changed_after_the_update(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)
        self.run_quiet(m.update,self.exe,self.new);m.configure(self.exe,percent=80,downscale='area')
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual([self.settings()[('bc250',k)] for k in ['resolutionpercent','downscalefilter']],['80','1'])
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'BC250 proxy')
        m.restore(self.exe);self.assertOriginal()

    def test_settings_keep_the_users_values_and_take_new_keys(self):
        # A release that adds a key to settings.ini: the user's values stay, the new key comes with its default.
        newer=self.newer({**CHANGES,'payload/BC250-XeFG/settings.ini':SETTINGS+b'NewKey=5\n'},folder='package-newkey')
        m.install(self.package,self.exe,route='opti')
        status,_=self.run_quiet(m.update,self.exe,newer);self.assertEqual(status,'update')
        self.assertEqual(self.settings()[('bc250','newkey')],'5')  # untouched settings: the new release's file as it is
        m.configure(self.exe,percent=60);self.run_quiet(m.rollback,self.exe)
        self.assertNotIn(('bc250','newkey'),self.settings());self.assertEqual(self.settings()[('bc250','resolutionpercent')],'60')
        m.configure(self.exe,percent=55);self.run_quiet(m.update,self.exe,newer)
        self.assertEqual((self.settings()[('bc250','newkey')],self.settings()[('bc250','resolutionpercent')]),('5','55'))
        self.assertIn(b'; retain comment',(self.game/'BC250-XeFG/settings.ini').read_bytes())

    def test_a_second_update_finds_nothing_to_do(self):
        m.install(self.package,self.exe,route='opti');self.run_quiet(m.update,self.exe,self.new)
        before=self.snapshot();record=self.record()
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'current');self.assertIn('Up to date',out)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_plan_changes_nothing(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)
        before=self.snapshot();record=self.record()
        status,out=self.run_quiet(m.show_plan,self.new,self.exe)
        self.assertEqual(status,'update');self.assertIn('Update '+OLD+' → '+NEW,out)
        self.assertIn('frame generation add-on: 3 replaced, 1 new files',out);self.assertIn('unchanged: original-file backups',out)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_a_file_changed_since_installation_leaves_the_game_as_it_is(self):
        m.install(self.package,self.exe,route='opti')
        (self.game/'BC250-XeFG/shaders/waves.txt').write_bytes(b'edited by another tool')
        before=self.snapshot();record=self.record()
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'blocked');self.assertIn('BC250-XeFG/shaders/waves.txt',out);self.assertIn('Restore, then Install',out)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)

    def test_a_running_game_is_not_updated(self):
        m.install(self.package,self.exe,route='opti');before=self.snapshot()
        with patch.object(m,'idle',side_effect=ValueError('Close the game before installing or restoring')):
            with self.assertRaisesRegex(ValueError,'Close the game'):m.update(self.exe,self.new)
            with self.assertRaisesRegex(ValueError,'Close the game'):m.rollback(self.exe)
            # Plan still says what would change, and that the game must be closed first.
            status,out=self.run_quiet(m.show_plan,self.new,self.exe)
        self.assertEqual(status,'update');self.assertIn('running',out);self.assertEqual(self.snapshot(),before)

    def test_a_pinned_game_stays_on_its_release(self):
        m.install(self.package,self.exe,route='opti');self.run_quiet(m.pin,self.exe)
        before=self.snapshot()
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'pinned');self.assertIn('Pinned to '+OLD,out);self.assertEqual(self.snapshot(),before)
        _,out=self.run_quiet(m.status,self.exe);self.assertIn('Pinned to '+OLD,out)
        self.run_quiet(m.pin,self.exe,False)
        status,_=self.run_quiet(m.update,self.exe,self.new);self.assertEqual(status,'update')

    def test_a_release_not_listed_needs_restore_and_install(self):
        m.install(self.package,self.exe,route='opti')
        record=self.record();record['package']='freefg-1.1.3.1';m.save_record(self.game/m.STATE,record)
        before=self.snapshot()
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'blocked');self.assertIn('freefg-1.1.3.1 is not a release this build updates in place',out)
        self.assertEqual(self.snapshot(),before)

    def test_other_launch_settings_need_restore_and_install(self):
        # A release whose launcher planning differs (here: one more variable) would have to rewrite the launcher entry.
        m.install(self.package,self.exe,route='opti');before=self.snapshot()
        planned=launcher_config.environment
        def environment(*args,**kwargs):return dict(planned(*args,**kwargs),BC250_NEW_SWITCH='1')
        with patch.object(launcher_config,'environment',side_effect=environment):
            status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'blocked');self.assertIn('other launch settings',out);self.assertEqual(self.snapshot(),before)
        # The launcher entry as it is planned now matches: the update goes ahead.
        self.assertEqual(m.launcher_changes(self.game.resolve(),self.record()),[])

    def test_another_optiscaler_build_needs_restore_and_install(self):
        # The game's own OptiScaler setup (dxgi.dll 'opti') is accepted by the installed release, not by the newer one.
        m.install(self.package,self.exe,route='opti')
        pins=json.loads((self.new/'dependencies.json').read_text());pins['payload']['ProxyHash']=m.digest(b'another OptiScaler')
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode())
        status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'blocked');self.assertIn('OptiScaler is not a build this release supports',out)
        m.restore(self.exe);self.assertOriginal()

    def test_a_fresh_optiscaler_setup_from_other_pins_needs_restore_and_install(self):
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual(self.run_quiet(m.update,self.exe,self.new)[0],'update')
        pins=json.loads((self.new/'dependencies.json').read_text());pins['payload']['Files']['OptiScaler/plugins/OptiPatcher.asi']=m.digest(b'patcher 2')
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode());set_name(self.new,'freefg-1.1.6')
        with patch.object(m,'UPDATES_FROM',{OLD,NEW}):status,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'blocked');self.assertIn('another OptiScaler build (OptiScaler/plugins/OptiPatcher.asi)',out)

    def test_a_file_the_release_no_longer_has_goes_back(self):
        newer=self.newer({**CHANGES,'payload/BC250-XeFG/shaders/winograd.required':None},folder='package-retire')
        m.install(self.package,self.exe,route='opti');before=self.snapshot()
        self.run_quiet(m.update,self.exe,newer)
        self.assertFalse((self.game/'BC250-XeFG/shaders/winograd.required').exists())
        item=next(i for i in self.record()['files'] if i['path']=='BC250-XeFG/shaders/winograd.required')
        self.assertEqual((item['before'],item['after']),(None,None))
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.run_quiet(m.update,self.exe,newer);m.restore(self.exe);self.assertOriginal()

    def test_a_new_file_over_a_game_file_keeps_the_games_file_as_its_original(self):
        # The newer release places a file the game already has beside its executable: it becomes a managed file whose
        # original is the game's, put back by rollback and by Restore.
        newer=self.newer({**CHANGES,'payload/libnew.dll':b'freefg helper'},folder='package-add')
        (self.game/'libnew.dll').write_bytes(b'the game own');self.original['libnew.dll']=b'the game own'
        m.install(self.package,self.exe,route='opti');before=self.snapshot()
        self.run_quiet(m.update,self.exe,newer);self.assertEqual((self.game/'libnew.dll').read_bytes(),b'freefg helper')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
        self.run_quiet(m.update,self.exe,newer);m.restore(self.exe);self.assertOriginal()

    def test_a_new_folder_is_removed_by_rollback_and_restore(self):
        newer=self.newer({**CHANGES,'payload/BC250-XeFG/layer/extra/new.json':b'{}'},folder='package-folder')
        m.install(self.package,self.exe,route='opti');before=self.snapshot();dirs=self.record()['created_dirs']
        self.run_quiet(m.update,self.exe,newer)
        self.assertIn('BC250-XeFG/layer/extra',self.record()['created_dirs'])
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertFalse((self.game/'BC250-XeFG/layer').exists());self.assertEqual(self.record()['created_dirs'],dirs)
        self.run_quiet(m.update,self.exe,newer);m.restore(self.exe);self.assertOriginal();self.assertFalse((self.game/'BC250-XeFG').exists())

    def test_a_new_runtime_pin_is_downloaded_and_rolled_back(self):
        runtime=dict(DEPENDENCIES['runtime'],**{'OptiScaler/libxess_fg.dll':b'Intel FG 2'})
        deps=self.root/'deps-new'
        for name,data in runtime.items():m.write(deps/name,data)
        pins=json.loads((self.new/'dependencies.json').read_text())
        pins['runtime']['Files']={name:m.digest(data) for name,data in runtime.items()}
        # A fresh OptiScaler setup's copy of the runtime is the same pin (check_pins); this game has its own OptiScaler.
        pins['payload']['Files']['OptiScaler/libxess_fg.dll']=m.digest(b'Intel FG 2')
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode())
        m.install(self.package,self.exe,route='opti');before=self.snapshot()
        status,out=self.run_quiet(m.update,self.exe,self.new,deps)
        self.assertEqual(status,'update');self.assertIn('Intel XeFG runtime: 1 replaced file',out)
        self.assertEqual((self.game/'bc250_xefg_original.dll').read_bytes(),b'Intel FG 2')
        self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)

    def test_fsr4_follows_the_release_unless_changed(self):
        pins=json.loads((self.new/'dependencies.json').read_text());deps=self.root/'deps-fsr'
        runtime=dict(DEPENDENCIES['runtime'],**{'fsr4/'+m.DLL:b'FSR 2'})
        for name,data in runtime.items():m.write(deps/name,data)
        pins['runtime']['Files']={name:m.digest(data) for name,data in runtime.items()}
        set_package_file(self.new,'dependencies.json',json.dumps(pins).encode())
        m.install(self.package,self.exe,route='opti')
        self.run_quiet(m.update,self.exe,self.new,deps);self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'FSR 2')
        self.run_quiet(m.rollback,self.exe);self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'FSR')
        # Replaced by something else since installation: FSR 4 is left as it is, the add-on is updated all the same.
        (self.game/'OptiScaler'/m.DLL).write_bytes(b'user FSR')
        status,out=self.run_quiet(m.update,self.exe,self.new,deps)
        self.assertEqual(status,'update');self.assertIn('FSR 4 not updated',out)
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'user FSR');self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),CHANGES['payload/libxess_fg.dll'])

    def test_vkd3d_cache_is_emptied_when_the_profile_changes(self):
        # As a new installation starts with an empty cache: emptied when shader files change, kept for a proxy-only release.
        m.install(self.package,self.exe,route='opti');cache=self.game/m.STATE/m.VKD3D_CACHE
        self.assertTrue(cache.is_dir());(cache/'vkd3d-proton.Game.exe.cache').write_bytes(b'pipelines')
        _,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertTrue(cache.is_dir());self.assertEqual(list(cache.iterdir()),[]);self.assertIn('shader cache for this game was emptied',out)
        (cache/'vkd3d-proton.Game.exe.cache').write_bytes(b'pipelines')
        proxy_only=self.newer({'payload/libxess_fg.dll':b'BC250 proxy 1.1.5.1'},name='freefg-1.1.5.1',folder='package-proxy',base=self.new)
        with patch.object(m,'UPDATES_FROM',{OLD,NEW}):_,out=self.run_quiet(m.update,self.exe,proxy_only)
        self.assertEqual([p.name for p in cache.iterdir()],['vkd3d-proton.Game.exe.cache']);self.assertNotIn('emptied',out)

    def test_status_names_the_update(self):
        m.install(self.package,self.exe,route='opti');self.run_quiet(m.update,self.exe,self.new)
        _,out=self.run_quiet(m.status,self.exe)
        self.assertIn('Package: '+NEW,out);self.assertIn('Updated in place from '+OLD,out);self.assertIn('Changed since installation: none',out)

    def test_only_the_last_release_is_kept_for_rollback(self):
        third=self.newer({'payload/libxess_fg.dll':b'BC250 proxy 1.1.6'},name='freefg-1.1.6',folder='package-third')
        m.install(self.package,self.exe,route='opti');self.run_quiet(m.update,self.exe,self.new)
        with patch.object(m,'UPDATES_FROM',{OLD,NEW}):self.run_quiet(m.update,self.exe,third)
        record=self.record();self.assertEqual([g['from'] for g in record['generations']],[NEW])
        self.assertEqual([p.name for p in (self.game/m.STATE/m.GENERATIONS).iterdir()],[record['generations'][0]['id']])
        self.run_quiet(m.rollback,self.exe)
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),CHANGES['payload/libxess_fg.dll']);self.assertEqual(self.record()['package'],NEW)
        with self.assertRaisesRegex(ValueError,'No update to roll back'):m.rollback(self.exe)

class InterruptionTests(UpdateFixture):
    """A crash at each write of an update or a rollback: the next update, rollback or Restore puts the game in a known state."""
    def crash_at(self,count,function,*args):
        """Run function with the installer's count-th file write never happening (the process dies there); returns
        whether it got that far."""
        real=m.write;calls=[0]
        def write(*a,**k):
            calls[0]+=1
            if calls[0]==count:raise Crash()
            return real(*a,**k)
        with patch.object(m,'write',side_effect=write),contextlib.redirect_stdout(io.StringIO()):
            try:function(*args)
            except Crash:return True
        return False

    def test_an_interrupted_update_is_undone_or_finished(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)
        before=self.snapshot()
        self.run_quiet(m.update,self.exe,self.new);updated=self.snapshot();self.run_quiet(m.rollback,self.exe)
        self.assertEqual(self.snapshot(),before)
        # Each write in turn is the one the process does not survive; then the next update finishes the job, a rollback
        # returns to the earlier release, or Restore to the originals (and the game is installed again for the next case).
        count=0;interrupted=True
        while interrupted:
            count+=1
            for then in ['update','rollback','restore']:
                with self.subTest(write=count,then=then):
                    interrupted=self.crash_at(count,m.update,self.exe,self.new)
                    if not interrupted:
                        # The update made fewer writes than count: it finished.
                        self.assertEqual(self.snapshot(),updated);self.run_quiet(m.rollback,self.exe)
                        break
                    if then=='update':
                        self.run_quiet(m.update,self.exe,self.new);self.assertEqual(self.snapshot(),updated)
                        self.assertEqual(self.record()['package'],NEW);self.run_quiet(m.rollback,self.exe)
                    elif then=='rollback':
                        try:self.run_quiet(m.rollback,self.exe)
                        except ValueError as error:self.assertIn('No update to roll back',str(error))  # before its journal
                    else:
                        m.restore(self.exe);self.assertOriginal()
                        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)
                    self.assertEqual(self.snapshot(),before)
                    self.assertNotIn('pending_update',self.record());self.assertEqual(self.record()['package'],OLD)
        self.assertGreater(count,8)

    def test_an_interrupted_rollback_is_finished(self):
        m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67)
        before=self.snapshot();self.run_quiet(m.update,self.exe,self.new);updated=self.snapshot()
        count=1
        while self.crash_at(count,m.rollback,self.exe):
            with self.subTest(write=count,then='rollback'):
                self.run_quiet(m.rollback,self.exe);self.assertEqual(self.snapshot(),before)
                self.assertEqual(self.record()['package'],OLD);self.assertNotIn('pending_update',self.record())
                self.run_quiet(m.update,self.exe,self.new);self.assertEqual(self.snapshot(),updated)
            with self.subTest(write=count,then='restore'):
                self.assertTrue(self.crash_at(count,m.rollback,self.exe))
                m.restore(self.exe);self.assertOriginal()
                m.install(self.package,self.exe,route='opti');m.configure(self.exe,percent=67);self.run_quiet(m.update,self.exe,self.new)
                self.assertEqual(self.snapshot(),updated)
            count+=1
        self.assertEqual(self.snapshot(),before);self.assertGreater(count,3)
        m.restore(self.exe);self.assertOriginal()

    def test_status_and_configure_after_an_interruption(self):
        m.install(self.package,self.exe,route='opti')
        # The first crash that leaves the journal behind (the ones before it change nothing in the game).
        count=1
        while self.crash_at(count,m.update,self.exe,self.new) and 'pending_update' not in self.record():count+=1
        self.assertIn('generation',self.record()['pending_update'])
        _,out=self.run_quiet(m.status,self.exe);self.assertIn('An update was interrupted: run install.py update again',out)
        with self.assertRaisesRegex(ValueError,'An update was interrupted'):m.configure(self.exe,percent=60)
        status,out=self.run_quiet(m.show_plan,self.new,self.exe);self.assertEqual(status,'interrupted')
        m.restore(self.exe);self.assertOriginal()

class LibraryTests(UpdateFixture):
    """Update all: the games found from the launchers' entries, each updated or left on its own."""
    def second_game(self):
        game=self.root/'game2';game.mkdir();exe=game/'Other.exe';exe.write_bytes(self.exe.read_bytes())
        for name,data in self.original.items():m.write(game/name,data)
        installed=self.root/'.config/heroic/gog_store/installed.json'
        data=json.loads(installed.read_text());data['installed'].append({'appName':'456','install_path':str(game)});installed.write_text(json.dumps(data))
        m.write(self.root/'.config/heroic/GamesConfig/456.json',json.dumps({'456':{'enviromentOptions':[]}}).encode())
        return game,exe

    def test_library_lists_installations_from_launcher_entries(self):
        game,exe=self.second_game()
        self.assertEqual(m.library(),[])
        m.install(self.package,self.exe,route='opti');m.install(self.package,exe,route='opti')
        self.assertEqual(m.library(),sorted([self.exe,exe]))
        m.restore(exe);self.assertEqual(m.library(),[self.exe])

    def test_update_all_updates_each_game_on_its_own(self):
        game,exe=self.second_game()
        m.install(self.package,self.exe,route='opti');m.install(self.package,exe,route='opti')
        (game/'BC250-XeFG/shaders/waves.txt').write_bytes(b'edited')
        out=io.StringIO();err=io.StringIO()
        with patch.object(m,'__file__',str(self.new/'install.py')),patch('sys.argv',['install.py','update','--all']),\
             contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=m.main()
        self.assertEqual(code,1)
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),CHANGES['payload/libxess_fg.dll'])
        self.assertEqual((game/'libxess_fg.dll').read_bytes(),b'BC250 proxy')
        self.assertIn('Update: 1 updated; 1 need attention (Other.exe).',out.getvalue())
        # Again: the first is up to date, the second still needs attention; plan says the same and changes nothing.
        with patch.object(m,'__file__',str(self.new/'install.py')),patch('sys.argv',['install.py','plan','--all']),\
             contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            self.assertEqual(m.main(),0)
        self.assertIn('Plan: 1 up to date; 1 need attention (Other.exe).',out.getvalue())

    def test_installation_roots_from_steam_and_lutris(self):
        steam=self.root/'.local/share/Steam';layer='VK_LAYER_PATH=/games/a/BC250-XeFG/layer:/usr/share/vulkan %command%'
        m.write(steam/'userdata/1/config/localconfig.vdf',('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
                '\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t"10"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LaunchOptions"\t\t"'+layer+'"\n\t\t\t\t\t}\n'
                '\t\t\t\t\t"20"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LaunchOptions"\t\t"gamemoderun %command%"\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n').encode())
        m.write(self.root/'.config/lutris/games/b.yml',b'game:\n  exe: /games/b/B.exe\nsystem:\n  env:\n    VK_LAYER_PATH: /games/b/BC250-XeFG/layer\n')
        self.assertEqual(launcher_config.installation_roots(self.root),[Path('/games/a'),Path('/games/b')])

if __name__=='__main__':unittest.main()
