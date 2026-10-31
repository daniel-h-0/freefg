# SPDX-License-Identifier: MIT
"""Installer transactions on a fixture package (manifest runtime 'xemfg'): automatic launcher setup (a Heroic entry in a temporary home) and
the pinned upstream files (Intel runtime, FSR4, OptiScaler, DLSS helper) from a local fixture directory, so nothing is
downloaded."""
import contextlib,importlib.util,io,json,os,re,shutil,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

PACKAGING=Path(__file__).resolve().parents[1]/'packaging'
sys.path.insert(0,str(PACKAGING))
import launcher_config
spec=importlib.util.spec_from_file_location('installer',PACKAGING/'install.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

# Fixture stand-ins for the pinned upstream files, by dependencies.json group. A name in two groups has one content.
DEPENDENCIES={
    'runtime':{'OptiScaler/libxess_fg.dll':b'Intel FG','OptiScaler/libxell.dll':b'new LL','Licenses/XeSS_LICENSE.txt':b'Intel licence',
               'fsr4/'+m.DLL:b'FSR'},
    'payload':{'OptiScaler.dll':b'opti','OptiScaler.ini':b'[Upscalers]\nDx12Upscaler=auto\n','OptiScaler/'+m.DLL:b'old FSR',
               'OptiScaler/libxess_fg.dll':b'Intel FG','OptiScaler/libxell.dll':b'new LL','OptiScaler/plugins/OptiPatcher.asi':b'patcher',
               'Licenses/XeSS_LICENSE.txt':b'Intel licence'},
    'dlss':{'nvngx_dlss.dll':b'helper','Licenses/NVIDIA-DLSS-LICENSE.txt':b'NVIDIA licence'},
}
RUNTIME_PACKAGE={'fsr4/'+m.DLL:'fsr4/'+m.DLL,'payload/libxess_fg.dll':'OptiScaler/libxess_fg.dll','payload/libxell.dll':'OptiScaler/libxell.dll',
                 'payload/XeSSMFG/libxess_fg.dll':'OptiScaler/libxess_fg.dll','payload/XeSSMFG/libxell.dll':'OptiScaler/libxell.dll'}
# The package's own files: no Intel runtime, no FSR4.
PACKAGE={'payload/version.dll':b'mfg loader','payload/XeSSMFG/settings.ini':b'[XeSSMFG]\nMultiplier=2\nExposeIntelVendor=0\n',
         'payload/BC250-XeFG/settings.ini':b'[BC250]\nFrameCap=1\n','payload/OptiScaler/plugins/BC250-MFG.asi':b'addon',
         'payload/OptiScaler/plugins/BC250-XeFG/shaders/waves.txt':b'wave config'}

def pins_for(dependencies):
    return {'payload':{'ProxyHash':m.digest(dependencies['payload']['OptiScaler.dll']),'Files':{n:m.digest(d) for n,d in dependencies['payload'].items()}},
            'runtime':{'Files':{n:m.digest(d) for n,d in dependencies['runtime'].items()},'Package':dict(RUNTIME_PACKAGE)},
            'dlss':{'Files':{n:m.digest(d) for n,d in dependencies['dlss'].items()}}}

def exe_bytes():
    header=bytearray(128);header[:2]=b'MZ';struct.pack_into('<I',header,60,64);header[64:70]=b'PE\0\0d\x86';struct.pack_into('<H',header,88,0x20b)
    return bytes(header)

def set_package_file(package,name,data):
    """Add or replace one package file and its manifest digest."""
    m.write(package/name,data)
    manifest=json.loads((package/'manifest.json').read_text());manifest['files'][name]=m.digest(data)
    (package/'manifest.json').write_text(json.dumps(manifest))

def heroic(home,game):
    """A Heroic (GOG) entry for the game; returns its GamesConfig file."""
    m.write(home/'.config/heroic/gog_store/installed.json',json.dumps({'installed':[{'appName':'123','install_path':str(game)}]}).encode())
    config=home/'.config/heroic/GamesConfig/123.json'
    m.write(config,json.dumps({'123':{'enableHDR':True,'enviromentOptions':[{'key':'VKD3D_CONFIG','value':'dxr'}],
                                      'wrapperOptions':[{'exe':'/usr/bin/gamemoderun','args':''}]}}).encode())
    return config

class GameFixture(unittest.TestCase):
    """A game with an existing OptiScaler setup (dxgi.dll proxy), the fixture package and its pinned files. Other test modules
    call this setUp on their own test cases: it uses no methods of this class."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.game=self.root/'game';self.game.mkdir();self.exe=self.game/'Game.exe';self.exe.write_bytes(exe_bytes())
        self.package=self.root/'package';self.package.mkdir()
        self.ini=b'; user comment\r\n[Upscalers]\r\nDx12Upscaler=xess\r\n[FSR]\r\nFsr4EnableWatermark=true\r\n[Unrelated]\r\nValue=original\r\n'
        self.original={'libxess_fg.dll':b'original FG','libxell.dll':b'original LL','OptiScaler/'+m.DLL:b'original FSR','OptiScaler/libxell.dll':b'Opti LL',
                       'OptiScaler.ini':self.ini,'dxgi.dll':b'opti'}
        for name,data in self.original.items():m.write(self.game/name,data)
        self.deps=self.root/'deps'
        for group in DEPENDENCIES.values():
            for name,data in group.items():m.write(self.deps/name,data)
        files=dict(PACKAGE,**{'dependencies.json':json.dumps(pins_for(DEPENDENCIES)).encode()})
        for name,data in files.items():m.write(self.package/name,data)
        (self.package/'manifest.json').write_text(json.dumps({'name':'bc250-fsr4-xemfg-private-test-99','runtime':'xemfg','launcher_setup':'automatic',
                                                              'files':{name:m.digest(data) for name,data in files.items()}}))
        self.config=heroic(self.root,self.game);self.original_config=json.loads(self.config.read_text());self.original_config_bytes=self.config.read_bytes()
        # A prepared download cache: the fixture directory. Records which groups the installer asked for (each list is
        # one download step; nothing asked for means nothing would have been downloaded).
        self.prepared=[]
        def prepare(package,groups):
            self.prepared.append(list(groups));return self.deps
        for context in (patch.dict(os.environ,{'XDG_DATA_HOME':str(self.root/'.local/share'),'FREEFG_LIBRARY':str(self.root/'.local/share/freefg/library.json')}),
                        patch.object(launcher_config.Path,'home',return_value=self.root),patch.object(launcher_config,'require_stopped'),
                        patch.object(m,'prepare_dependencies',side_effect=prepare)):
            context.start();self.addCleanup(context.stop)
        self.silent=contextlib.redirect_stdout(io.StringIO());self.silent.__enter__();self.addCleanup(self.silent.__exit__,None,None,None)
    def fresh(self):
        """Remove the game's OptiScaler setup (and the other originals): the next install is a fresh OptiScaler setup."""
        for name in self.original:(self.game/name).unlink()
        return self.deps
    def env(self):
        return {e['key']:e['value'] for e in json.loads(self.config.read_text())['123']['enviromentOptions']}
    def assertOriginal(self):
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data,name)
        self.assertEqual(json.loads(self.config.read_text()),self.original_config)
        self.assertEqual(self.config.read_bytes(),self.original_config_bytes)  # the launcher's file as found, byte for byte

class EventTests(unittest.TestCase):
    def test_events_are_json_lines_beside_the_ordinary_output(self):
        # One outcome per game, among the ordinary output; nothing extra without --events.
        missing=str(Path(tempfile.mkdtemp())/'Game.exe')
        def run(*extra):
            return __import__('subprocess').run([sys.executable,'-I',str(PACKAGING/'install.py'),'status',missing,*extra],capture_output=True,text=True)
        plain,with_events=run(),run('--events')
        self.assertEqual((plain.returncode,with_events.returncode),(1,1))
        self.assertNotIn(m.EVENT_PREFIX,plain.stdout)
        events=[json.loads(line[len(m.EVENT_PREFIX):]) for line in with_events.stdout.splitlines() if line.startswith(m.EVENT_PREFIX)]
        self.assertEqual(events,[{'v':1,'type':'outcome','exe':missing,'result':'failed'}])
        self.assertEqual([line for line in with_events.stdout.splitlines() if not line.startswith(m.EVENT_PREFIX)],plain.stdout.splitlines())

    def test_output_errors_never_stop_the_installer(self):
        # A reader that went away (Setup closed or killed): output is dropped from then on, the command runs to its end.
        missing=str(Path(tempfile.mkdtemp())/'Game.exe')
        read,closed=os.pipe();os.close(read)
        try:
            run=__import__('subprocess').run([sys.executable,'-I',str(PACKAGING/'install.py'),'status',missing,'--events'],
                                             stdout=closed,stderr=__import__('subprocess').PIPE,text=True)
        finally:os.close(closed)
        self.assertEqual(run.returncode,1);self.assertIn('No such file',run.stderr);self.assertNotIn('BrokenPipeError',run.stderr)
        class Gone(io.StringIO):
            def write(self,text):raise BrokenPipeError(32,'Broken pipe')
        stream=m.Unbroken(Gone())
        with contextlib.redirect_stdout(stream):print('lost');m.say('lost too');print('and this',flush=True)
        self.assertTrue(stream.broken)

class InstallationTests(GameFixture):
    def test_round_trip(self):
        m.install(self.package,self.exe);self.assertFalse((self.game/'OptiScaler/libxell.dll').exists())
        self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('fakenvapi','usefakenvapi')],'false')
        self.assertIn('version=n,b',self.env()['WINEDLLOVERRIDES'])
        m.restore(self.exe)
        self.assertOriginal();self.assertFalse((self.game/'version.dll').exists());self.assertFalse((self.game/'XeSSMFG').exists())
    def test_runtime_and_fsr4_come_from_the_pinned_downloads(self):
        # The package carries neither: Intel's XeFG/XeLL beside the game and in XeSSMFG/, FSR4 in OptiScaler's folder.
        m.install(self.package,self.exe)
        for name in ['libxess_fg.dll','XeSSMFG/libxess_fg.dll']:self.assertEqual((self.game/name).read_bytes(),b'Intel FG')
        for name in ['libxell.dll','XeSSMFG/libxell.dll']:self.assertEqual((self.game/name).read_bytes(),b'new LL')
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'FSR')
        self.assertEqual(self.prepared,[['runtime']])  # an existing OptiScaler: only the runtime group
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertEqual({i['path']:i['after'] for i in record['files']}['libxess_fg.dll'],m.digest(b'Intel FG'))
        m.restore(self.exe);self.assertOriginal()
    def test_given_dependency_directory_is_used_without_preparing(self):
        m.install(self.package,self.exe,dependency_dir=self.deps);self.assertEqual(self.prepared,[])
        m.restore(self.exe)
    def test_dependency_directory_missing_a_file_is_prepared(self):
        # The library owner prepares the default groups; a group it lacks (here everything) comes from the cache.
        partial=self.root/'partial';partial.mkdir()
        m.install(self.package,self.exe,dependency_dir=partial);self.assertEqual(self.prepared,[['runtime']])
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'Intel FG');m.restore(self.exe)
    def test_corrupt_dependency_no_mutation(self):
        (self.deps/'fsr4'/m.DLL).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'Dependency checksum mismatch'):m.install(self.package,self.exe)
        self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_package_copy_of_a_pinned_file_must_match(self):
        # Older packages carried the runtime; such a copy must be the pinned bytes.
        set_package_file(self.package,'payload/libxess_fg.dll',b'Intel FG')
        m.install(self.package,self.exe);self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'Intel FG');m.restore(self.exe)
        set_package_file(self.package,'payload/libxess_fg.dll',b'other runtime')
        with self.assertRaisesRegex(ValueError,'differs from its pinned upstream download'):m.install(self.package,self.exe)
        self.assertEqual(json.loads((self.game/m.STATE/'state.json').read_text())['status'],'restored')
        self.assertOriginal()
    def test_package_without_pins_is_refused(self):
        manifest=json.loads((self.package/'manifest.json').read_text());del manifest['files']['dependencies.json']
        (self.package/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'dependencies.json'):m.install(self.package,self.exe)
        self.assertFalse((self.game/m.STATE).exists())
    def test_only_frame_generation_packages_with_automatic_launch(self):
        for changes in [dict(runtime=None),dict(launcher_setup=None),dict(runtime='xefg')]:
            manifest=json.loads((self.package/'manifest.json').read_text())
            for key,value in changes.items():
                if value is None:manifest.pop(key)
                else:manifest[key]=value
            path=self.package/'manifest.json';saved=path.read_text();path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'frame-generation packages with automatic launcher setup'):m.install(self.package,self.exe)
            path.write_text(saved);self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_fsr4_model_by_its_own_name_where_optiscaler_reads_none(self):
        # FSR4Support INT8 as Fsr4GpuSupport=2, the key the shipped OptiScaler reads (its old name Fsr4ForceModel counts
        # only while Fsr4GpuSupport is auto): a value OptiScaler reads there is the user's and stays.
        p=self.game/'OptiScaler.ini'
        for value,after in [(None,'2'),('auto','2'),('yes','2'),('9','2'),('4','4'),('0x1','0x1'),(' 0 ','0')]:
            with self.subTest(value=value):
                before=m.patch_ini(self.ini,{('FSR','Fsr4GpuSupport'):value.strip() if value else value})
                p.write_bytes(before);self.original['OptiScaler.ini']=before
                m.install(self.package,self.exe);ini=m.read_ini(p.read_bytes())
                self.assertEqual(ini[('fsr','fsr4gpusupport')],after);self.assertNotIn(('fsr','fsr4forcemodel'),ini)
                m.restore(self.exe);self.assertOriginal()
        self.assertEqual([m.fsr4_support(v) for v in ['2','+2','02','0x4','0X2',' 3 ','5','-1','2.0','2_0','auto','',None]],
                         [2,2,2,4,2,3,None,None,None,None,None,None,None])
    def test_every_key_the_installer_writes_is_in_the_shipped_optiscaler_ini(self):
        # The keys of the OptiScaler.ini the release ships (recipes.json optiscaler_builds of the pinned build): a key it
        # does not read (a renamed one, as Fsr4ForceModel) would change nothing. XeFG.XeFGModel is MFG Unlocker's key.
        import compat
        data=json.loads((PACKAGING/'recipes/recipes.json').read_text())
        shipped={key.lower() for key in data['optiscaler_builds'][data['sources']['optiscaler_pinned']]['keys']}
        self.assertEqual(sorted(k for k in compat.INSTALLER_KEYS if k.lower() not in shipped),['XeFG.XeFGModel'])
        written=set();p=self.game/'OptiScaler.ini'
        p.write_bytes(m.patch_ini(self.ini,{('Libraries','XeSSPath'):r'.\libxess_fg.dll'}));self.original['OptiScaler.ini']=p.read_bytes()
        for route,fg_input in [('native','upscaler'),('opti','upscaler'),('opti','dlssg'),('opti','fsrfg'),('opti','fsrfg30')]:
            m.install(self.package,self.exe,route=route,fg_input=fg_input)
            written|={(c['section']+'.'+c['key']).lower() for c in json.loads((self.game/m.STATE/'state.json').read_text())['ini_changes']}
            m.restore(self.exe);self.assertOriginal()
        self.fresh();m.install(self.package,self.exe,route='opti')
        written|={(c['section']+'.'+c['key']).lower() for c in json.loads((self.game/m.STATE/'state.json').read_text())['ini_changes']}
        self.assertEqual(sorted(written-{k.lower() for k in compat.INSTALLER_KEYS}),[])
        self.assertIn('libraries.xesspath',written)
    def test_preserve_later_ini_edits(self):
        m.install(self.package,self.exe);p=self.game/'OptiScaler.ini'
        p.write_bytes(m.patch_ini(p.read_bytes(),{('Unrelated','Value'):'later',('FSR','Fsr4EnableWatermark'):'true'}))
        m.restore(self.exe);result=m.read_ini(p.read_bytes())
        self.assertEqual(result[('unrelated','value')],'later');self.assertEqual(result[('upscalers','dx12upscaler')],'xess')
        self.assertEqual(result[('fsr','fsr4enablewatermark')],'true');self.assertNotIn(('fakenvapi','usefakenvapi'),result)
    def test_file_changed_after_install_is_kept_and_the_rest_restored(self):
        # A game update (or the user) replaced a managed file: that version is the game's own. Restore keeps it, puts
        # everything else back and says where the pre-install version is.
        m.install(self.package,self.exe);(self.game/'libxell.dll').write_bytes(b'user update')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.restore(self.exe)
        self.assertEqual((self.game/'libxell.dll').read_bytes(),b'user update')
        for name,data in self.original.items():
            if name!='libxell.dll':self.assertEqual((self.game/name).read_bytes(),data)
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertEqual(record['status'],'restored');self.assertEqual(record['kept_changed'],['libxell.dll'])
        self.assertIn('Kept libxell.dll',out.getvalue())
        self.assertIn(b'original LL',[p.read_bytes() for p in (self.game/m.STATE/'backups').iterdir()])
    def test_corrupt_package_no_mutation(self):
        (self.package/'payload/version.dll').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):m.install(self.package,self.exe)
        self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_symlink_refusal(self):
        (self.game/'libxell.dll').unlink();(self.game/'libxell.dll').symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):m.install(self.package,self.exe)
        self.assertFalse((self.root/'outside').exists());self.assertFalse((self.game/m.STATE).exists())
    def test_custom_path_refusal(self):
        p=self.game/'OptiScaler.ini';p.write_bytes(m.patch_ini(p.read_bytes(),{('Libraries','FfxDx12SRPath'):'Z:\\custom'}))
        with self.assertRaises(ValueError):m.install(self.package,self.exe)
    def test_duplicate_case_section_refusal(self):
        with self.assertRaises(ValueError):m.patch_ini(b'[FSR]\nA=1\n[fsr]\nB=2\n',{})
    def test_preview_read_only(self):
        m.install(self.package,self.exe,True);self.assertFalse((self.game/m.STATE).exists())
        self.assertOriginal()
    def test_reinstall_retains_previous_backups(self):
        m.install(self.package,self.exe);m.restore(self.exe);m.install(self.package,self.exe)
        history=list(self.game.glob(m.STATE+'-restored-*'));self.assertEqual(len(history),1)
        self.assertEqual(json.loads((history[0]/'state.json').read_text())['status'],'restored')
        m.restore(self.exe);self.assertOriginal()
    def test_interrupted_install_recoverable(self):
        original_write=m.write
        def fail(path,*args,**kwargs):
            if path==self.game/'libxell.dll':raise OSError('Injected disk error')
            return original_write(path,*args,**kwargs)
        m.write=fail
        try:
            with self.assertRaises(OSError):m.install(self.package,self.exe)
        finally:m.write=original_write
        m.restore(self.exe);self.assertOriginal()
    def during_download(self,action):
        """install() with action run while it downloads the runtime (the window between its checks and its first change)."""
        def prepare(package,groups):
            self.prepared.append(list(groups));action();return self.deps
        return patch.object(m,'prepare_dependencies',side_effect=prepare)
    def before_the_commit(self,action):
        """install() with action run at its last check, after its plan and downloads, just before its first change."""
        real,calls=m.idle,[]
        def idle(root):
            calls.append(root)
            if len(calls)==2:action()
            return real(root)
        return patch.object(m,'idle',side_effect=idle)
    def test_changes_during_the_downloads_refuse_before_any_change(self):
        # A launcher started or a launcher file rewritten while install downloaded, a game file updated after it planned:
        # install checks again just before its first change, as update does, and the game folder and the launcher stay
        # as they were. (The backups are the bytes this check read, under the plan's checksums.)
        launching=launcher_config.require_stopped
        def start():launching.side_effect=ValueError('Close heroic before installing or restoring launcher settings')
        def rewrite():self.config.write_bytes(self.config.read_bytes().replace(b'"dxr"',b'"dxr,no_upload_hvv"'))
        def update():(self.game/'libxell.dll').write_bytes(b'game update')
        for action,message,kind,hook in [(start,'Close heroic',m.Refusal,self.during_download),(rewrite,'changed since planning',ValueError,self.during_download),
                                         (update,'libxell.dll changed while',ValueError,self.before_the_commit)]:
            with self.subTest(action=action.__name__):
                config,game=self.config.read_bytes(),{name:(self.game/name).read_bytes() for name in self.original}
                with hook(action),self.assertRaisesRegex(kind,message):m.install(self.package,self.exe)
                self.assertEqual(self.prepared[-1],['runtime']);self.assertFalse(list(self.game.glob(m.STATE+'*')))
                if action is not rewrite:self.assertEqual(self.config.read_bytes(),config)
                if action is not update:self.assertEqual({name:(self.game/name).read_bytes() for name in self.original},game)
                launching.side_effect=None
        self.config.write_bytes(self.original_config_bytes);(self.game/'libxell.dll').write_bytes(self.original['libxell.dll'])
        m.install(self.package,self.exe);m.restore(self.exe);self.assertOriginal()
    def test_a_late_refusal_keeps_the_restored_record_in_place(self):
        m.install(self.package,self.exe);m.restore(self.exe);restored=(self.game/m.STATE/'state.json').read_bytes()
        with self.before_the_commit(lambda:(self.game/'libxell.dll').write_bytes(b'game update')),self.assertRaises(ValueError):
            m.install(self.package,self.exe)
        self.assertEqual((self.game/m.STATE/'state.json').read_bytes(),restored);self.assertFalse(list(self.game.glob(m.STATE+'-*')))
    def test_another_installer_at_the_launcher_file_is_a_refusal(self):
        # The per-file launcher lock update, rollback and Restore take: another installer holding it means retry.
        import fcntl,hashlib
        folder=m.freefg_library.location().parent/'locks';folder.mkdir(parents=True,exist_ok=True)
        lock=os.open(folder/(hashlib.sha256(str(self.config.absolute()).encode()).hexdigest()+'.lock'),os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with self.assertRaisesRegex(m.Refusal,'Another installer is editing this launcher'):m.install(self.package,self.exe)
        finally:os.close(lock)
        self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
        m.install(self.package,self.exe);m.restore(self.exe);self.assertOriginal()
    def test_preview_while_a_launcher_runs(self):
        # A preview reads only: it works while the launcher runs; Install refuses at once, before any download.
        launcher_config.require_stopped.side_effect=ValueError('Close heroic before installing or restoring launcher settings')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,preview=True)
        self.assertIn('Configure heroic: '+str(self.config),out.getvalue());self.assertOriginal()
        self.prepared.clear()
        with self.assertRaisesRegex(m.Refusal,'Close heroic'):m.install(self.package,self.exe)
        self.assertEqual(self.prepared,[]);self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_opti_without_native_xefg(self):
        (self.game/'libxess_fg.dll').unlink();del self.original['libxess_fg.dll']
        m.install(self.package,self.exe,route='opti')
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'Intel FG')
        self.assertFalse((self.game/'OptiScaler/libxess_fg.dll').exists());self.assertFalse((self.game/'OptiScaler/libxell.dll').exists())
        config=m.read_ini((self.game/'OptiScaler.ini').read_bytes())
        self.assertEqual(config[('framegen','fginput')],'upscaler')
        self.assertEqual(config[('framegen','fgoutput')],'xefg')
        self.assertEqual(config[('libraries','xefgpath')],r'.\libxess_fg.dll')
        self.assertEqual((self.game/'libxell.dll').read_bytes(),b'new LL')
        m.restore(self.exe)
        self.assertFalse((self.game/'libxess_fg.dll').exists());self.assertOriginal()
    def record(self):
        return json.loads((self.game/m.STATE/'state.json').read_text())
    def test_fresh_setup_keeps_the_games_own_dlss(self):
        # A game that ships nvngx_dlss.dll keeps it, beside the executable or in an engine folder: no helper, no NVIDIA
        # download, and no record entry for that file (Restore and the BC250 library's checks never meet it).
        deps=self.fresh()
        for where in ['nvngx_dlss.dll','Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll']:
            with self.subTest(where=where):
                copy=self.game/where;m.write(copy,b'game DLSS');self.prepared.clear()
                out=io.StringIO()
                with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti',fg_input='dlssg')
                self.assertEqual(self.prepared,[['payload'],['runtime']])
                self.assertEqual(copy.read_bytes(),b'game DLSS');self.assertFalse((self.game/'OptiScaler/Licenses/NVIDIA-DLSS-LICENSE.txt').exists())
                if where!='nvngx_dlss.dll':self.assertFalse((self.game/'nvngx_dlss.dll').exists())
                self.assertEqual((self.game/'dxgi.dll').read_bytes(),b'opti')
                self.assertEqual(m.read_ini((self.game/'OptiScaler.ini').read_bytes())[('plugins','loadasiplugins')],'true')
                record=self.record();self.assertNotIn('nvngx_dlss.dll',[i['path'] for i in record['files']])
                self.assertEqual(record['dlss_helper'],dict(placed=False,reason='OptiScaler finds the game’s own nvngx_dlss.dll',game_copy=where,
                                                            game_copy_found=True,searched_all=True,dlss_input=True,dxgi_spoofing=None))
                self.assertIn('OptiScaler finds the game’s own nvngx_dlss.dll ('+where+')',out.getvalue())
                m.restore(self.exe)
                self.assertFalse((self.game/'dxgi.dll').exists());self.assertFalse((self.game/'OptiScaler.ini').exists())
                self.assertEqual(copy.read_bytes(),b'game DLSS');copy.unlink()
    def test_dlss_helper_only_for_dlss_inputs(self):
        # Tester v30 placed NVIDIA's helper in every fresh setup. Now only a DLSS input in a game without its own copy
        # gets it, fetched with the runtime after every check; FSR/XeSS inputs and native XeSS FG download nothing of NVIDIA's.
        self.fresh()
        cases=[('opti','upscaler','auto',False),('opti','fsrfg','auto',False),('opti','fsrfg30','auto',False),('native','upscaler','auto',False),
               ('opti','dlssg','auto',True),('opti','dlssg','no',False),('opti','upscaler','yes',True),('native','upscaler','yes',True)]
        for route,fg_input,choice,placed in cases:
            with self.subTest(route=route,fg_input=fg_input,choice=choice):
                self.prepared.clear();(self.game/'libxess_fg.dll').write_bytes(b'native FG')
                m.install(self.package,self.exe,route=route,fg_input=fg_input,dlss_helper=choice)
                self.assertEqual(self.prepared,[['payload'],['runtime','dlss'] if placed else ['runtime']])
                self.assertEqual((self.game/'nvngx_dlss.dll').exists(),placed)
                self.assertEqual((self.game/'OptiScaler/Licenses/NVIDIA-DLSS-LICENSE.txt').exists(),placed)
                if placed:
                    self.assertEqual((self.game/'nvngx_dlss.dll').read_bytes(),b'helper')
                    self.assertEqual((self.game/'OptiScaler/Licenses/NVIDIA-DLSS-LICENSE.txt').read_bytes(),b'NVIDIA licence')
                    item=next(i for i in self.record()['files'] if i['path']=='nvngx_dlss.dll');self.assertIsNone(item['before'])
                self.assertTrue((self.game/'OptiScaler/Licenses/XeSS_LICENSE.txt').exists())
                self.assertEqual(self.record()['dlss_helper']['placed'],placed)
                m.restore(self.exe);(self.game/'libxess_fg.dll').unlink()
                self.assertFalse((self.game/'nvngx_dlss.dll').exists());self.assertFalse((self.game/'OptiScaler/Licenses').exists() and any((self.game/'OptiScaler/Licenses').iterdir()))
        with self.assertRaisesRegex(ValueError,'DLSS helper choice'):m.install(self.package,self.exe,route='opti',dlss_helper='always')
    def test_dlss_helper_for_dlss_inputs_set_in_the_ini(self):
        # A recipe (or the fresh setup's INI) that turns OptiScaler's DLSS inputs on marks a DLSS upscaler input.
        plan=m.dlss_helper_plan
        self.fresh()
        self.assertTrue(plan(self.exe,'opti','upscaler',{('inputs','enabledlssinputs'):'true'})['placed'])
        self.assertFalse(plan(self.exe,'opti','upscaler',{('inputs','enabledlssinputs'):'auto'})['placed'])
        self.assertFalse(plan(self.exe,'opti','upscaler',{})['placed'])
        self.assertTrue(plan(self.exe,'native','upscaler',{('inputs','enabledlssinputs'):' True '})['placed'])
        self.assertFalse(plan(self.exe,'opti','dlssg',{('inputs','enabledlssinputs'):'true'},'no')['placed'])
        # The game's copy wins over every reason; an installer's folders (OptiScaler's, a backup tree) are not the game's.
        m.write(self.game/'OptiScaler/nvngx_dlss.dll',b'other');m.write(self.game/(m.STATE+'-restored-0123/backups/nvngx_dlss.dll'),b'old')
        self.assertTrue(plan(self.exe,'opti','dlssg',{})['placed'])
        m.write(self.game/'bin/nvngx_dlss.dll',b'game DLSS')
        self.assertEqual(plan(self.exe,'opti','dlssg',{},'yes'),dict(placed=False,reason='OptiScaler finds the game’s own nvngx_dlss.dll',game_copy='bin/nvngx_dlss.dll',
                                                                     game_copy_found=True,searched_all=True,dlss_input=True,dxgi_spoofing=None))
    def layout(self,exe,*copies):
        """A fresh game whose executable sits at exe below the game folder, with the game's own nvngx_dlss.dll copies."""
        if (self.game/'OptiScaler.ini').exists():self.fresh()
        self.exe.unlink(missing_ok=True);exe=self.game/exe;m.write(exe,exe_bytes())
        for name in copies:m.write(self.game/name,b'game DLSS')
        return exe
    def test_dlss_helper_follows_optiscalers_search(self):
        # OptiScaler takes nvngx_dlss.dll only from the executable's folder, below it, and (for Win64, WinGDK and
        # Win64MasterMasterSteamPGO layouts) below an engine root above it (Util::FindFilePath). A copy elsewhere in the
        # game folder never reaches it: the helper goes beside the executable and the game's copy stays where it is.
        plan=m.dlss_helper_plan
        exe=self.layout('bin/x64/Game.exe','sl/nvngx_dlss.dll')
        self.assertIsNone(m.optiscaler_fallback_root(exe))
        self.assertEqual(plan(exe,'opti','dlssg',{}),dict(placed=True,reason='DLSS FG input',game_copy='../../sl/nvngx_dlss.dll',game_copy_found=False,
                                                         searched_all=True,dlss_input=True,dxgi_spoofing=None))
        self.assertFalse(plan(exe,'opti','upscaler',{})['placed'])
        self.assertIn('outside the folders OptiScaler searches',m.helper_line(plan(exe,'opti','upscaler',{})))
        shutil.rmtree(self.game/'sl');shutil.rmtree(self.game/'bin')
        for layout,exe,copy in [
                # KCD2: the engine root two levels above Bin/Win64MasterMasterSteamPGO holds Bin/Win64Shared.
                ('KCD2','KCD2/Bin/Win64MasterMasterSteamPGO/KingdomCome.exe','KCD2/Bin/Win64Shared/nvngx_dlss.dll'),
                # Unreal: <Game>/<Project>/Binaries/Win64 searches from <Game>, so Engine/Plugins is reached.
                ('Unreal','U/Proj/Binaries/Win64/Proj-Win64-Shipping.exe','U/Engine/Plugins/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll'),
                # An older Unreal layout <Game>/Binaries/Win64: OptiScaler's root lies above the game folder.
                ('older Unreal','Old/Binaries/Win64/Old.exe','Old/Engine/Plugins/nvngx_dlss.dll'),
                # GDK: WinGDK beside Win64.
                ('GDK','G/Proj/Binaries/WinGDK/Proj-WinGDK-Shipping.exe','G/Proj/Plugins/DLSS/nvngx_dlss.dll'),
                # Any case beside the executable (Wine opens it so).
                ('beside, upper case','Up/Game.exe','Up/NVNGX_DLSS.DLL')]:
            with self.subTest(layout=layout):
                if layout=='GDK':(self.game/'G/Proj/Binaries/Win64').mkdir(parents=True)
                exe=self.layout(exe,copy)
                if layout=='older Unreal':self.assertEqual(m.optiscaler_fallback_root(exe),self.game)
                for choice in ['auto','yes']:
                    result=plan(exe,'opti','dlssg',{},choice)
                    self.assertFalse(result['placed'],choice);self.assertTrue(result['game_copy_found'])
                    self.assertEqual(Path(exe.parent,result['game_copy']).resolve(),(self.game/copy).resolve())
                shutil.rmtree(self.game/copy.split('/')[0])
        # Below the executable OptiScaler matches the exact name: another case there is not reached.
        exe=self.layout('Game.exe','plugins/NVNGX_DLSS.dll')
        result=plan(exe,'opti','dlssg',{});self.assertTrue(result['placed']);self.assertEqual(result['game_copy'],'plugins/NVNGX_DLSS.dll')
    def test_helper_beside_a_game_copy_that_optiscaler_cannot_find(self):
        # The reviewer's layout: Game/bin/x64/Game.exe with the game's copy in Game/sl. The helper is placed beside the
        # executable on a DLSS FG input, the game's file is never touched, and Restore removes only the helper.
        exe=self.layout('bin/x64/Game.exe','sl/nvngx_dlss.dll');self.prepared.clear()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,exe,route='opti',fg_input='dlssg')
        self.assertEqual(self.prepared,[['payload'],['runtime','dlss']])
        self.assertEqual((exe.parent/'nvngx_dlss.dll').read_bytes(),b'helper');self.assertEqual((self.game/'sl/nvngx_dlss.dll').read_bytes(),b'game DLSS')
        self.assertNotIn('sl/nvngx_dlss.dll',[i['path'] for i in json.loads((exe.parent/m.STATE/'state.json').read_text())['files']])
        self.assertIn('the game’s own copy (../../sl/nvngx_dlss.dll) is outside the folders OptiScaler searches',out.getvalue())
        m.restore(exe)
        self.assertFalse((exe.parent/'nvngx_dlss.dll').exists());self.assertEqual((self.game/'sl/nvngx_dlss.dll').read_bytes(),b'game DLSS')
    def test_dlss_search_limit_never_hides_the_copy_beside_the_executable(self):
        # An Unreal game with many content files walked first: the executable's folder is checked before the walk, and a
        # walk that stops at its limit is reported, never read as "the game ships none".
        exe=self.layout('Proj/Binaries/Win64/Game.exe','Proj/Binaries/Win64/nvngx_dlss.dll')
        for i in range(6):m.write(self.game/'Engine/Content'/f'{i}.uasset',b'x')
        self.assertEqual(m.dlss_copies(exe,limit=3),dict(found='nvngx_dlss.dll',other=None,complete=True))
        real=m.dlss_copies
        with patch.object(m,'dlss_copies',side_effect=lambda exe:real(exe,limit=3)):
            self.assertFalse(m.dlss_helper_plan(exe,'opti','dlssg',{})['placed'])
            (exe.parent/'nvngx_dlss.dll').unlink();m.write(self.game/'Proj/Binaries/Win64/x/y/nvngx_dlss.dll',b'game DLSS')
            self.assertEqual(real(exe,limit=3)['found'],'x/y/nvngx_dlss.dll')  # below the executable's folder first
            shutil.rmtree(self.game/'Proj/Binaries/Win64/x');m.write(self.game/'Engine/Plugins/a/b/c/nvngx_dlss.dll',b'game DLSS')
            result=m.dlss_helper_plan(exe,'opti','dlssg',{})
            self.assertEqual((result['placed'],result['game_copy'],result['searched_all']),(True,None,False))
            self.assertIn('none found in the first 50,000 files',m.helper_line(result))
            self.assertNotIn('ships none',m.helper_line(result))
        self.assertTrue(m.dlss_helper_plan(exe,'opti','dlssg',{})['game_copy_found'])  # the whole walk reaches it
    def test_dxgi_spoofing_effect_is_reported(self):
        # Without a helper and without a copy OptiScaler finds, Spoofing.Dxgi=auto turns OptiScaler's DXGI spoofing off
        # (upstream's default without DLSS; tester v30's helper kept it on): said in the plan, the record and the output.
        plan=m.dlss_helper_plan
        self.fresh()
        self.assertEqual(plan(self.exe,'opti','upscaler',{})['dxgi_spoofing'],'off')
        self.assertEqual(plan(self.exe,'opti','upscaler',{('spoofing','dxgi'):' Auto '})['dxgi_spoofing'],'off')
        self.assertIsNone(plan(self.exe,'opti','upscaler',{('spoofing','dxgi'):'false'})['dxgi_spoofing'])  # a recipe's value
        self.assertIsNone(plan(self.exe,'opti','upscaler',{},'yes')['dxgi_spoofing'])  # the helper keeps it on
        self.assertIsNone(plan(self.exe,'opti','dlssg',{})['dxgi_spoofing'])
        self.assertEqual(plan(self.exe,'opti','dlssg',{},'no')['dxgi_spoofing'],'off')
        self.assertIn('DLSS input may not work',m.helper_line(plan(self.exe,'opti','dlssg',{},'no')))
        m.write(self.game/'_nvngx.dll',b'x');self.assertIsNone(plan(self.exe,'opti','upscaler',{})['dxgi_spoofing']);(self.game/'_nvngx.dll').unlink()
        m.write(self.game/'Plugins/nvngx_dlss.dll',b'game DLSS');self.assertIsNone(plan(self.exe,'opti','upscaler',{})['dxgi_spoofing'])
        (self.game/'Plugins/nvngx_dlss.dll').unlink()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti',fg_input='upscaler')
        self.assertEqual(self.record()['dlss_helper']['dxgi_spoofing'],'off')
        self.assertIn('GPU spoofing: OptiScaler finds no nvngx_dlss.dll',out.getvalue());self.assertIn('--dlss-helper yes',out.getvalue())
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        self.assertIn('GPU spoofing',out.getvalue())
        m.restore(self.exe)
    def test_helper_line_reads_records_of_the_earlier_shape(self):
        # Records written before game_copy_found/searched_all existed.
        self.assertIn('none needed',m.helper_line(dict(placed=False,reason='the game ships its own nvngx_dlss.dll',game_copy='nvngx_dlss.dll')))
        self.assertIn('the game ships none',m.helper_line(dict(placed=True,reason='DLSS FG input',game_copy=None)))
    def test_stale_dependency_directory_is_prepared_again(self):
        # A caller's prepared directory (the library owner's prepare(package) with the default groups) holding a helper
        # from another pin: the installer fetches the pinned one instead of refusing.
        self.fresh();stale=self.root/'stale';shutil.copytree(self.deps,stale);(stale/'nvngx_dlss.dll').write_bytes(b'other helper')
        m.install(self.package,self.exe,route='opti',fg_input='dlssg',dependency_dir=stale)
        self.assertEqual(self.prepared,[['runtime','dlss']]);self.assertEqual((self.game/'nvngx_dlss.dll').read_bytes(),b'helper')
        m.restore(self.exe);self.prepared.clear()
        (stale/'nvngx_dlss.dll').unlink();(stale/'nvngx_dlss.dll').symlink_to(self.deps/'nvngx_dlss.dll')
        m.install(self.package,self.exe,route='opti',fg_input='dlssg',dependency_dir=stale)
        self.assertEqual(self.prepared,[['runtime','dlss']]);m.restore(self.exe)
    def test_dlss_helper_refusal_comes_before_any_runtime_download(self):
        # A dangling link where the helper would go: refused after the fresh setup's own files, before the runtime.
        self.fresh();(self.game/'nvngx_dlss.dll').symlink_to(self.root/'nowhere')
        with self.assertRaisesRegex(ValueError,'Symlink'):m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        self.assertEqual(self.prepared,[['payload']]);self.assertFalse((self.game/m.STATE).exists())
    def test_existing_setup_never_gets_the_helper(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,route='opti',fg_input='dlssg',dlss_helper='yes')
        self.assertFalse((self.game/'nvngx_dlss.dll').exists());self.assertEqual(self.prepared,[['runtime']])
        self.assertNotIn('dlss_helper',self.record());self.assertIn('existing OptiScaler setup keeps its own files',out.getvalue())
        m.restore(self.exe);self.assertOriginal()
    def test_pins_with_the_helper_in_the_fresh_setup_are_refused(self):
        # dependencies.json of tester v30 (the helper in 'payload', no 'dlss' group) beside this installer.
        old=pins_for(DEPENDENCIES);old['payload']['Files'].update(old.pop('dlss')['Files'])
        set_package_file(self.package,'dependencies.json',json.dumps(old).encode())
        with self.assertRaisesRegex(ValueError,'no separate DLSS helper pins'):m.install(self.package,self.exe)
        self.assertEqual(self.prepared,[]);self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_preview_fetches_what_the_install_needs(self):
        # The library owner checks a move with a preview (no dependency_dir) before it changes anything, then installs:
        # the preview fetches the runtime (and a fresh setup's own files) into the cache, so the install downloads nothing
        # new partway through a move. The game is left untouched.
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.install(self.package,self.exe,preview=True)
        self.assertEqual(self.prepared,[['runtime']]);self.assertOriginal();self.assertFalse((self.game/m.STATE).exists())
        self.assertIn('libxess_fg.dll',out.getvalue().splitlines());self.assertIn('XeSSMFG/libxell.dll',out.getvalue().splitlines())
        self.prepared.clear();self.fresh();tree=sorted(self.game.rglob('*'))
        m.install(self.package,self.exe,preview=True,route='opti')
        self.assertEqual(self.prepared,[['payload'],['runtime']]);self.assertEqual(sorted(self.game.rglob('*')),tree)
        # A prepared directory holding every file is used as is, also by a preview.
        self.prepared.clear();m.install(self.package,self.exe,preview=True,route='opti',dependency_dir=self.deps)
        self.assertEqual(self.prepared,[])
    def test_preview_fails_when_the_runtime_is_unavailable(self):
        # Offline, a GitHub error or a changed release asset: the preview refuses, so the owner's check refuses the move.
        def offline(package,groups):
            self.prepared.append(list(groups))
            if 'runtime' in groups:raise ValueError('Cannot download bc250-fsr4-dll-4.0.0-rc12.zip')
            return self.deps
        with patch.object(m,'prepare_dependencies',side_effect=offline):
            with self.assertRaisesRegex(ValueError,'Cannot download'):m.install(self.package,self.exe,preview=True)
        self.assertEqual(self.prepared,[['runtime']]);self.assertOriginal();self.assertFalse((self.game/m.STATE).exists())
        # A cache that holds a changed file is refused the same way.
        (self.deps/'fsr4'/m.DLL).write_bytes(b'changed asset')
        with self.assertRaisesRegex(ValueError,'Dependency checksum mismatch'):m.install(self.package,self.exe,preview=True)
        self.assertOriginal();self.assertFalse((self.game/m.STATE).exists())
    def test_refusals_come_before_the_runtime_download(self):
        # Each of these refuses before anything is downloaded, also with an empty cache and no network.
        def refused(pattern):
            self.prepared.clear()
            with self.assertRaisesRegex(ValueError,pattern):m.install(self.package,self.exe,route='opti')
            self.assertEqual(self.prepared,[]);self.assertFalse((self.game/m.STATE).exists())
        ini=self.game/'OptiScaler.ini'
        ini.write_bytes(m.patch_ini(self.ini,{('Libraries','XeFGPath'):'Z:\\custom'}));refused('custom DLL path')
        ini.write_bytes(m.patch_ini(self.ini,{('Libraries','FfxDx12SRPath'):'missing\\'+m.DLL}));refused('configured local FSR4 DLL')
        ini.write_bytes(self.ini)
        (self.game/'libxell.dll').unlink();(self.game/'libxell.dll').symlink_to(self.root/'outside');refused('Symlink')
        (self.game/'libxell.dll').unlink();m.write(self.game/'libxell.dll',self.original['libxell.dll'])
        self.config.unlink();(self.root/'.config/heroic/gog_store/installed.json').unlink();refused('No launcher entry')
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data,name)
    def test_package_carrying_the_runtime_needs_no_download(self):
        # A package that still carries the pinned runtime (as v30 did) installs onto an existing setup offline.
        for name,group in [('payload/libxess_fg.dll','OptiScaler/libxess_fg.dll'),('payload/libxell.dll','OptiScaler/libxell.dll'),('fsr4/'+m.DLL,'fsr4/'+m.DLL)]:
            set_package_file(self.package,name,DEPENDENCIES['runtime'][group])
        m.install(self.package,self.exe);self.assertEqual(self.prepared,[])
        for name in ['libxess_fg.dll','XeSSMFG/libxess_fg.dll']:self.assertEqual((self.game/name).read_bytes(),b'Intel FG')
        self.assertEqual((self.game/'XeSSMFG/libxell.dll').read_bytes(),b'new LL')
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'FSR')
        m.restore(self.exe);self.assertOriginal()
    def test_dependency_pins_of_an_earlier_build_are_refused(self):
        # install.py beside the dependencies.json of an earlier build (no runtime downloads pinned): a clear refusal.
        old=pins_for(DEPENDENCIES);del old['runtime']
        set_package_file(self.package,'dependencies.json',json.dumps(old).encode())
        with self.assertRaisesRegex(ValueError,'come from different builds'):m.install(self.package,self.exe)
        self.assertEqual(self.prepared,[]);self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()
    def test_fresh_native_uses_root_xell(self):
        deps=self.fresh();(self.game/'libxess_fg.dll').write_bytes(b'native FG')
        m.install(self.package,self.exe,route='native',dependency_dir=deps)
        self.assertFalse((self.game/'OptiScaler/libxell.dll').exists())
        self.assertEqual((self.game/'libxell.dll').read_bytes(),b'new LL')
        m.restore(self.exe)
        self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'native FG')
        self.assertFalse((self.game/'libxell.dll').exists())
    def test_fresh_install_preserves_native_fsr_and_replaces_loaded_opti_copy(self):
        deps=self.fresh();native=self.game/m.DLL;native.write_bytes(b'game FSR')
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual(native.read_bytes(),b'game FSR')
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'FSR')
        m.restore(self.exe)
        self.assertEqual(native.read_bytes(),b'game FSR')
        self.assertFalse((self.game/'OptiScaler'/m.DLL).exists())
    def test_fresh_edited_ini_preserved_outside_game(self):
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        p=self.game/'OptiScaler.ini';edited=m.patch_ini(p.read_bytes(),{('Log','LogLevel'):'2'});p.write_bytes(edited)
        m.restore(self.exe)
        self.assertFalse(p.exists())
        saved=list((self.game/m.STATE/'preserved-ini').glob('*.ini'))
        saved=[s for s in saved if not s.name.startswith('xemfg-')]
        self.assertEqual(len(saved),1);self.assertEqual(saved[0].read_bytes(),edited)
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
    def test_restore_interrupted_after_removing_the_fresh_ini_still_names_its_copy(self):
        # The record names the copy before the INI goes: a Restore killed at its last write (the record) is completed by
        # the next one, and the next Install still carries the user's multiplier from it.
        deps=self.fresh();m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        p=self.game/'OptiScaler.ini';p.write_bytes(m.patch_ini(p.read_bytes(),{('XeFG','InterpolationCount'):'3'}))
        real=m.write
        def write(path,*args,**kwargs):
            if Path(path).name=='state.json' and not p.exists():raise OSError('killed')
            return real(path,*args,**kwargs)
        with patch.object(m,'write',side_effect=write),self.assertRaisesRegex(OSError,'killed'):m.restore(self.exe)
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertEqual((record['status'],(self.game/m.STATE/record['preserved_ini']).is_file()),('installed',True))
        m.restore(self.exe);self.assertEqual(json.loads((self.game/m.STATE/'state.json').read_text())['preserved_ini'],record['preserved_ini'])
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertEqual(m.read_ini(p.read_bytes())[('xefg','interpolationcount')],'3')
    def test_a_damaged_backup_leaves_that_file_and_restores_the_rest(self):
        # One missing or damaged copy from before installation no longer stops Restore: that file stays as installed and
        # is named, the rest comes back, and Install refuses until the game's own file is back (it would become an original).
        m.install(self.package,self.exe)
        record=json.loads((self.game/m.STATE/'state.json').read_text());index={item['path']:i for i,item in enumerate(record['files'])}
        (self.game/m.STATE/'backups'/str(index['libxell.dll'])).write_bytes(b'damaged')
        (self.game/m.STATE/'backups'/str(index['OptiScaler.ini'])).unlink()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.restore(self.exe)
        self.assertIn('Left libxell.dll as it is: its backup does not match its checksum',out.getvalue())
        self.assertIn('Left OptiScaler.ini as it is: its backup cannot be read',out.getvalue())
        self.assertEqual((self.game/'libxell.dll').read_bytes(),b'new LL')
        for name in set(self.original)-{'libxell.dll','OptiScaler.ini'}:self.assertEqual((self.game/name).read_bytes(),self.original[name],name)
        self.assertFalse((self.game/'version.dll').exists());self.assertEqual(json.loads(self.config.read_text()),self.original_config)
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertEqual((record['status'],[row['path'] for row in record['left_installed']]),('restored',['libxell.dll','OptiScaler.ini']))
        with self.assertRaisesRegex(ValueError,'could not put back the game’s own libxell.dll and OptiScaler.ini'):m.install(self.package,self.exe)
        self.assertEqual([r['code'] for r in m.preconditions(self.package,self.exe)][:1],['left-installed'])
        # Back as the game's (a launcher's Verify or Repair): Install and Restore work again.
        for name in ['libxell.dll','OptiScaler.ini']:(self.game/name).write_bytes(self.original[name])
        self.assertEqual(m.preconditions(self.package,self.exe),[])
        m.install(self.package,self.exe);m.restore(self.exe);self.assertOriginal()
    def test_existing_proxy_name_selects_context_owner(self):
        (self.game/'dxgi.dll').unlink();del self.original['dxgi.dll'];(self.game/'winmm.dll').write_bytes(b'opti')
        m.install(self.package,self.exe,route='opti')
        overrides=self.env()['WINEDLLOVERRIDES'].split(';')
        self.assertIn('winmm=n,b',overrides);self.assertNotIn('dxgi=n,b',overrides)
        m.restore(self.exe)
        self.assertEqual((self.game/'winmm.dll').read_bytes(),b'opti');self.assertOriginal()
    def test_existing_asi_loader_selects_context_owner(self):
        # OptiScaler loaded as an ASI plugin: the package's OptiScaler replaces that file, not the ASI loader.
        (self.game/'dxgi.dll').unlink();del self.original['dxgi.dll']
        (self.game/'winmm.dll').write_bytes(b'ASI loader');(self.game/'OptiScaler.asi').write_bytes(b'opti')
        set_package_file(self.package,'opti/OptiScaler.dll',b'private OptiScaler')
        m.install(self.package,self.exe,route='opti')
        self.assertEqual((self.game/'OptiScaler.asi').read_bytes(),b'private OptiScaler')
        self.assertEqual((self.game/'winmm.dll').read_bytes(),b'ASI loader')
        m.restore(self.exe)
        self.assertEqual((self.game/'winmm.dll').read_bytes(),b'ASI loader')
        self.assertEqual((self.game/'OptiScaler.asi').read_bytes(),b'opti')
    def test_fresh_proxy_collision(self):
        self.fresh();(self.game/'dxgi.dll').write_bytes(b'other mod')
        with self.assertRaisesRegex(ValueError,'manual mod chaining'):m.install(self.package,self.exe,route='opti')
        self.assertFalse((self.game/m.STATE).exists());self.assertEqual(self.prepared,[])  # refused before any download
    def test_native_requires_native_dll(self):
        (self.game/'libxess_fg.dll').unlink()
        with self.assertRaises(ValueError):m.install(self.package,self.exe,route='native')
    def test_relative_fsr_library(self):
        p=self.game/'OptiScaler.ini';p.write_bytes(m.patch_ini(p.read_bytes(),{('Libraries','FfxDx12SRPath'):'local\\'+m.DLL}))
        m.write(self.game/'local'/m.DLL,b'local FSR')
        m.install(self.package,self.exe,route='opti',fg_input='dlssg')
        self.assertEqual((self.game/'local'/m.DLL).read_bytes(),b'FSR')
        self.assertEqual((self.game/'OptiScaler'/m.DLL).read_bytes(),b'original FSR')
        self.assertFalse((self.game/'nvngx_dlss.dll').exists())  # an existing OptiScaler setup is not given the DLSS helper
        m.restore(self.exe);self.assertEqual((self.game/'local'/m.DLL).read_bytes(),b'local FSR')
    def test_non_ascii_path_refused_before_changes(self):
        target=self.root/'tést';self.game.rename(target);self.game=target;self.exe=target/'Game.exe'
        with self.assertRaisesRegex(ValueError,'ASCII'):m.install(self.package,self.exe)
        self.assertFalse((self.game/m.STATE).exists())
    def test_bad_executable(self):
        self.exe.write_bytes(b'not PE')
        with self.assertRaises(ValueError):m.install(self.package,self.exe)
    def test_backup_failure_leaves_game_and_state_untouched(self):
        original_write=m.write
        def fail(path,*args,**kwargs):
            if path.parent.name=='backups':raise OSError('Injected backup failure')
            return original_write(path,*args,**kwargs)
        m.write=fail
        try:
            with self.assertRaises(OSError):m.install(self.package,self.exe)
        finally:m.write=original_write
        self.assertFalse((self.game/m.STATE).exists());self.assertOriginal()

def optiscaler_saved(data):
    """data as OptiScaler's own Save writes it: every key line 'key = value', LF line endings, the same comments."""
    out=[]
    for line in data.decode('utf-8-sig').splitlines():
        key=m.KEY_LINE.match(line)
        out.append(key[1]+key[2]+' = '+line[key.end():].strip() if key else line)
    return ('\n'.join(out)+'\n').encode()

class RestoreFidelityTests(GameFixture):
    """Restore leaves the game folder and the launcher's files as it found them when the values are back."""
    def record(self):
        return json.loads((self.game/m.STATE/'state.json').read_text())
    def test_optiscaler_ini_keeps_its_layout(self):
        # An INI OptiScaler saved itself ('key = value', its own key spelling): the installer changes only values,
        # adds keys with the same spacing, and Restore gives back the bytes.
        p=self.game/'OptiScaler.ini'
        saved=b'; user comment\n[Upscalers]\ndx12upscaler = xess\n[FSR]\nFsr4EnableWatermark = true   \n[Unrelated]\nValue = original\n'
        p.write_bytes(saved);self.original['OptiScaler.ini']=saved
        m.install(self.package,self.exe);text=p.read_text()
        self.assertIn('\ndx12upscaler = ffx\n',text);self.assertIn('\nFsr4EnableWatermark = auto   \n',text)
        self.assertIn('\nLoadAsiPlugins = true\n',text);self.assertIn('\nUseFakenvapi = false\n',text)
        self.assertEqual([line for line in text.splitlines() if re.match(r'[^;\[\s][^=]*\S=',line)],[])  # no 'key=value' line
        m.restore(self.exe);self.assertOriginal()
        # The installer's own layout is kept just the same.
        self.assertIn(b'\r\nDx12Upscaler=xess\r\n',self.ini)
    def test_inserted_keys_follow_the_most_common_spacing(self):
        self.assertEqual(m.patch_ini(b'[A]\na = 1\nb = 2\nc=3\n',{('A','d'):'4',('B','e'):'5'}),b'[A]\na = 1\nb = 2\nc=3\nd = 4\n\n[B]\ne = 5\n')
        self.assertEqual(m.patch_ini(b'[A]\nkey  =  \n',{('A','KEY'):'v'}),b'[A]\nkey  =  v\n')
        self.assertEqual(m.patch_ini(b'[A]\nKey = v ; note\n',{('a','key'):None}),b'[A]\n')
        # An indented key line loses its indent, as it always did: indented, it would read as part of the key above.
        self.assertEqual(m.read_ini(m.patch_ini(b'[A]\nx=1\n  Key = v\n',{('A','Key'):'w'})),{('a','x'):'1',('a','key'):'w'})
    def test_a_value_never_becomes_a_line_of_its_own(self):
        # A line separator in a value (U+2028, VT, FF, NEL, RS, ...): str.splitlines split it on the next edit, and the
        # rest became a section and a key of its own (an injected [Libraries] XeFGPath). Lines are split as configparser
        # (and OptiScaler) split them, and the installer writes no value that spans lines.
        for separator in '  \x0b\x0c\x1c\x1d\x1e\x85':
            with self.subTest(separator=repr(separator)):
                data=('[A]\nKey=x'+separator+'[Libraries]'+separator+'XeFGPath=evil\n').encode()
                edited=m.patch_ini(data,{('A','Other'):'1'});again=m.patch_ini(edited,{('A','Other'):'2'})
                self.assertEqual(m.read_ini(again),{('a','key'):'x'+separator+'[Libraries]'+separator+'XeFGPath=evil',('a','other'):'2'})
                self.assertEqual(len(m.ini_content(again)),3)
                with self.assertRaisesRegex(ValueError,'not a single line'):m.patch_ini(b'[A]\nKey=1\n',{('A','Key'):'1'+separator+'XeFGPath=evil'})
        for value in ['1\n[Libraries]\nXeFGPath=evil','1\rXeFGPath=evil','1\0']:
            with self.assertRaisesRegex(ValueError,'not a single line'):m.patch_ini(b'[A]\nKey=1\n',{('A','Key'):value})
        self.assertEqual(m.patch_ini(b'[A]\r\nKey=1\r\n',{('A','Key'):'2'}),b'[A]\r\nKey=2\r\n')
    def test_optiscaler_resave_restores_the_original_bytes(self):
        # OptiScaler saved the INI while the game ran (every line 'key = value', LF): the values are the original ones
        # once Restore reverts the installation's keys, so the original bytes come back (CRLF, 'key=value').
        p=self.game/'OptiScaler.ini'
        m.install(self.package,self.exe);p.write_bytes(optiscaler_saved(p.read_bytes()))
        m.restore(self.exe);self.assertOriginal()
        # A value the user chose since installation stays, in OptiScaler's layout; so does a comment the user added.
        for name,change,check in [('value',lambda d:d.replace(b'Value = original',b'Value = later'),lambda r:r[('unrelated','value')]=='later'),
                                  ('comment',lambda d:d+b'; my note\n',lambda r:r==m.read_ini(self.ini))]:
            with self.subTest(name):
                m.install(self.package,self.exe);p.write_bytes(change(optiscaler_saved(p.read_bytes())))
                m.restore(self.exe);restored=p.read_bytes();values=m.read_ini(restored)
                self.assertNotEqual(restored,self.ini);self.assertTrue(check(values))
                self.assertEqual(values[('upscalers','dx12upscaler')],'xess');self.assertNotIn(('fakenvapi','usefakenvapi'),values)
                self.assertIn(b'\nDx12Upscaler = xess\n',restored)
                if name=='comment':self.assertTrue(restored.endswith(b'; my note\n'))
                p.write_bytes(self.ini)
    def test_heroic_file_restored_byte_for_byte(self):
        # Heroic's own layout (JSON.stringify(config, null, 2): no final line ending, UTF-8 as is).
        data=json.dumps(dict(self.original_config,**{'123':dict(self.original_config['123'],title='Café')}),indent=2,ensure_ascii=False).encode()
        self.config.write_bytes(data);self.original_config=json.loads(data);self.original_config_bytes=data
        m.install(self.package,self.exe);installed=self.config.read_bytes()
        self.assertFalse(installed.endswith(b'\n'));self.assertIn('"title": "Café"'.encode(),installed)
        copy=self.record()['launchers'][0]['file_backup']
        self.assertEqual((self.game/m.STATE/copy['path']).read_bytes(),data);self.assertEqual(copy['sha256'],m.digest(data))
        m.restore(self.exe);self.assertOriginal()
        # Heroic rewrote the file in another layout since installation, with the same settings: the copy comes back.
        m.install(self.package,self.exe);self.config.write_bytes(json.dumps(json.loads(self.config.read_bytes()),indent=4).encode()+b'\n')
        m.restore(self.exe);self.assertOriginal()
        # A damaged copy is not used: the values come back, in the layout the file has now.
        m.install(self.package,self.exe);self.config.write_bytes(json.dumps(json.loads(self.config.read_bytes()),indent=4).encode()+b'\n')
        (self.game/m.STATE/copy['path']).write_bytes(b'{}')
        m.restore(self.exe);restored=self.config.read_bytes()
        self.assertEqual(json.loads(restored),self.original_config);self.assertTrue(restored.endswith(b'}\n'));self.assertIn(b'\n        "enableHDR"',restored)
    def test_restored_files_get_their_modification_times_back(self):
        # Restore writes the original bytes back with their original modification times: the game folder and the
        # launcher's file are as found, also for tools that look at times. A file the game changed since stays as it is.
        old=1759240000_123456789
        for path in [*(self.game/name for name in self.original),self.config]:os.utime(path,ns=(old,old))
        m.install(self.package,self.exe);self.assertNotEqual(self.config.stat().st_mtime_ns,old)
        p=self.game/'OptiScaler.ini';p.write_bytes(optiscaler_saved(p.read_bytes()))  # OptiScaler's own save
        (self.game/'libxell.dll').write_bytes(b'game update');updated=(self.game/'libxell.dll').stat().st_mtime_ns
        m.restore(self.exe)
        for name in self.original:
            if name!='libxell.dll':self.assertEqual((self.game/name).stat().st_mtime_ns,old,name)
        self.assertEqual((self.game/'libxell.dll').stat().st_mtime_ns,updated)
        self.assertEqual(self.config.stat().st_mtime_ns,old);self.assertEqual(self.config.read_bytes(),self.original_config_bytes)
        record=self.record()
        self.assertEqual({i['path']:i.get('mtime_ns') for i in record['files'] if i['before'] is not None}['OptiScaler.ini'],old)
        # A file the installation gives the bytes it already has is not rewritten at all (the package's own
        # OptiScaler build already in place): same inode, same time.
        set_package_file(self.package,'opti/OptiScaler.dll',b'opti');inode=(self.game/'dxgi.dll').stat().st_ino
        m.install(self.package,self.exe)
        self.assertEqual(((self.game/'dxgi.dll').stat().st_ino,(self.game/'dxgi.dll').stat().st_mtime_ns),(inode,old))
        self.assertIn('dxgi.dll',[i['path'] for i in self.record()['files'] if i['before']==i['after']])
        m.restore(self.exe);self.assertEqual((self.game/'dxgi.dll').stat().st_mtime_ns,old)
        self.assertEqual(record['launchers'][0]['file_backup']['mtime_ns'],old)
    def test_restore_removes_the_folders_it_created(self):
        deps=self.fresh();(self.game/'OptiScaler').rmdir()
        before=sorted(str(p.relative_to(self.game)) for p in self.game.rglob('*'))
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        created=self.record()['created_dirs']
        for name in ['OptiScaler','OptiScaler/plugins','OptiScaler/plugins/BC250-XeFG/shaders','XeSSMFG','BC250-XeFG']:self.assertIn(name,created)
        self.assertEqual(created,sorted(created,key=lambda n:-n.count('/')))  # deepest first
        m.restore(self.exe)
        after=sorted(str(p.relative_to(self.game)) for p in self.game.rglob('*') if not p.relative_to(self.game).parts[0].startswith(m.STATE))
        self.assertEqual(after,before)
    def test_folders_that_were_there_or_hold_other_files_stay(self):
        # A folder the game already had stays, even empty; one the installation created stays while it holds a file
        # that is not the installation's (a log), and Restore says so.
        deps=self.fresh()
        m.install(self.package,self.exe,route='opti',dependency_dir=deps)
        self.assertNotIn('OptiScaler',self.record()['created_dirs'])
        (self.game/'OptiScaler/plugins/BC250-XeFG-fast.log').write_text('add-on log')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.restore(self.exe)
        self.assertEqual(sorted(p.name for p in (self.game/'OptiScaler').iterdir()),['plugins'])
        self.assertEqual([p.name for p in (self.game/'OptiScaler/plugins').iterdir()],['BC250-XeFG-fast.log'])
        self.assertIn('Kept folders the installation created that now hold other files: OptiScaler/plugins.',out.getvalue())
        self.assertFalse((self.game/'XeSSMFG').exists());self.assertFalse((self.game/'BC250-XeFG').exists())
    def test_symlinked_folder_is_not_removed_through(self):
        m.install(self.package,self.exe);record=self.record()
        outside=self.root/'outside';(outside/'inner').mkdir(parents=True)
        (self.game/'link').symlink_to(outside,target_is_directory=True)
        record['created_dirs']=['link/inner',*record['created_dirs']];m.write(self.game/m.STATE/'state.json',json.dumps(record).encode())
        m.restore(self.exe);self.assertTrue((outside/'inner').is_dir());self.assertOriginal()

class LegacyRecordTests(GameFixture):
    """Records written by earlier, wrapper-based builds (2x XeFG, Update): Restore and Status still handle them."""
    def legacy(self,pending):
        """A wrapper-based OptiScaler-route record as the 2x builds wrote it; pending: an interrupted Update of its
        wrapper, already written to the game."""
        state=self.game/m.STATE;(state/'backups').mkdir(parents=True)
        installed={'OptiScaler/libxess_fg.dll':b'2x proxy','OptiScaler/BC250-XeFG/run.sh':b'#!/bin/sh\nexec "$@"\n','libxell.dll':b'2x LL'}
        ini=m.patch_ini(self.ini,{('FrameGen','FGOutput'):'xefg'})
        files=[]
        for name,data in [*installed.items(),('OptiScaler.ini',ini)]:
            before=(self.game/name).read_bytes() if (self.game/name).exists() else None
            if before is not None:m.write(state/'backups'/str(len(files)),before)
            files.append(dict(path=name,before=m.digest(before) if before is not None else None,after=m.digest(data),mode=0o755 if name.endswith('.sh') else 0o644))
            m.write(self.game/name,data)
        record=dict(status='installed',runtime='xefg',route='opti',fresh=False,wrapper='OptiScaler/BC250-XeFG/run.sh',game=str(self.exe),files=files,
                    package='bc250-fsr4-xefg-private-test-05',ini_changes=[dict(section='FrameGen',key='FGOutput',value='xefg')])
        if pending:
            newer=b'#!/bin/sh\nexport VKD3D_CONFIG=no_staggered_submit\nexec "$@"\n'
            record['pending_update']=dict(files={'OptiScaler/BC250-XeFG/run.sh':dict(before=files[1]['after'],after=m.digest(newer))},package='private-test-06')
            m.write(self.game/'OptiScaler/BC250-XeFG/run.sh',newer)
        m.write(state/'state.json',json.dumps(record).encode())
    def test_wrapper_record_with_interrupted_update_restores(self):
        self.legacy(pending=True)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):m.status(self.exe)
        self.assertIn('earlier build was interrupted',out.getvalue())
        with contextlib.redirect_stdout(out):m.restore(self.exe)
        self.assertIn('run.sh launch wrapper',out.getvalue())
        self.assertFalse((self.game/'OptiScaler/BC250-XeFG/run.sh').exists());self.assertFalse((self.game/'OptiScaler/libxess_fg.dll').exists())
        self.assertOriginal()
        record=json.loads((self.game/m.STATE/'state.json').read_text())
        self.assertEqual(record['status'],'restored');self.assertNotIn('pending_update',record)
    def test_wrapper_record_restores_then_this_build_installs(self):
        self.legacy(pending=False);m.restore(self.exe);self.assertOriginal()
        m.install(self.package,self.exe,route='opti');self.assertEqual((self.game/'libxess_fg.dll').read_bytes(),b'Intel FG')
        m.restore(self.exe);self.assertOriginal()
    def test_configure_names_a_2x_record(self):
        self.legacy(pending=False)
        with self.assertRaisesRegex(ValueError,'2× only'):m.configure(self.exe,factor=3)

class DetectInputTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'Game'
        # main() looks the game up in launchers: a home without any.
        home=patch.object(launcher_config.Path,'home',return_value=Path(self.tmp.name)/'home');home.start();self.addCleanup(home.stop)
    def tearDown(self):self.tmp.cleanup()
    def make(self,exe,*files):
        exe=self.root/exe;exe.parent.mkdir(parents=True,exist_ok=True);exe.write_bytes(b'MZ')
        for name in files:path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x')
        return exe
    def test_native_beside_exe_wins(self):
        route,fg,text=m.detect_input(self.make('bin/x64/Game.exe','bin/x64/libxess_fg.dll','bin/x64/nvngx_dlssg.dll'))
        self.assertEqual((route,fg),('native','upscaler'));self.assertIn('DLSS FG',text)
    def test_other_inputs_reported_not_chosen(self):
        exe=self.make('Project/Binaries/Win64/Game-Win64-Shipping.exe','Engine/Plugins/Runtime/Nvidia/Streamline/Binaries/ThirdParty/Win64/sl.dlss_g.dll','Project/Binaries/Win64/amd_fidelityfx_dx12.dll')
        route,fg,text=m.detect_input(exe)
        self.assertEqual((route,fg),('opti','upscaler'));self.assertIn('DLSS FG',text);self.assertIn('FSR 3.1',text)
    def test_installer_folders_ignored(self):
        route,fg,text=m.detect_input(self.make('Game.exe','OptiScaler/amd_fidelityfx_framegeneration_dx12.dll','.bc250-xefg-experimental/backups/nvngx_dlssg.dll'))
        self.assertEqual((route,fg),('opti','upscaler'));self.assertNotIn('also ships',text)
    def test_installed_mfg_payload_is_not_native(self):
        self.assertEqual(m.detect_input(self.make('Game.exe','libxess_fg.dll','XeSSMFG/settings.ini'))[:2],('opti','upscaler'))
    def test_explicit_input_keeps_the_optiscaler_route(self):
        # "install GAME --fg-input dlssg" must not become a native install because the game also ships XeSS FG.
        exe=self.make('bin/x64/Game.exe','bin/x64/libxess_fg.dll');calls=[]
        for extra in [['--fg-input','dlssg'],[]]:
            with patch.object(m,'install',lambda *a,**k:calls.append(a[3:5])),patch.object(sys,'argv',['install.py','install',str(exe),*extra]),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(),0)
        self.assertEqual(calls,[('opti','dlssg'),('native','upscaler')])
    def test_game_root_stops_without_an_unreal_project_layout(self):
        # <Game>/Binaries/Win64/x.exe: the game root is <Game>, not steamapps/common.
        exe=self.make('Binaries/Win64/Game.exe');self.assertEqual(m.game_root(exe),self.root)
        exe=self.make('Proj/Binaries/Win64/Game.exe');(self.root/'Engine').mkdir();self.assertEqual(m.game_root(exe),self.root)
    def test_search_stays_inside_the_game(self):
        exe=self.make('Game.exe');(self.root.parent/'Other').mkdir();(self.root.parent/'Other'/'nvngx_dlssg.dll').write_bytes(b'x')
        self.assertNotIn('also ships',m.detect_input(exe)[2])
if __name__=='__main__':unittest.main()
