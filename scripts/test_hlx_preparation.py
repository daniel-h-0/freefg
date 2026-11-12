# SPDX-License-Identifier: MIT
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch,Mock
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'packaging'))
import hlx


class PreparationTests(unittest.TestCase):
    def test_all_archive_members_are_checked_before_any_extraction(self):
        for bad in ('../escape','Helix/../../escape','/absolute','Helix/file:stream'):
            with self.subTest(member=bad),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);archive=root/'archive.zip';target=root/'out';target.mkdir()
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('Helix/good.txt','good');z.writestr(bad,'bad')
                with self.assertRaises(ValueError):hlx.unpack(archive,target,'Helix')
                self.assertEqual(list(target.iterdir()),[])

    def test_archive_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'archive.zip';target=root/'out';target.mkdir()
            with zipfile.ZipFile(archive,'w') as z:
                item=zipfile.ZipInfo('Helix/link');item.create_system=3;item.external_attr=0o120777<<16
                z.writestr(item,'/outside')
            with self.assertRaises(ValueError):hlx.unpack(archive,target,'Helix')
            self.assertEqual(list(target.iterdir()),[])

    def test_windows_compiler_archive_paths_stay_inside_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'archive.zip';target=root/'out';target.mkdir()
            with zipfile.ZipFile(archive,'w') as z:z.writestr('bin\\x64\\dxc.exe',b'compiler');z.writestr('bin/x86/other.exe',b'ignored')
            hlx.unpack(archive,target,compiler=True)
            self.assertEqual({x.name:x.read_bytes() for x in target.iterdir()},{'dxc.exe':b'compiler'})

    def test_concurrent_preparation_is_refused_before_download_or_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=root/'input.dll';model.write_bytes(b'local input');digest=hashlib.sha256(model.read_bytes()).hexdigest()
            spec=dict(spec_for({}),model_inputs={'dlss':digest});download=Mock()
            descriptor=os.open(root/'.prepare.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(descriptor,fcntl.LOCK_EX)
            try:
                with patch.object(hlx,'catalog',return_value=spec),patch.object(hlx,'cache',return_value=root),patch.object(hlx.shutil,'which',return_value='/fake/tool'),patch.dict(sys.modules,{'numpy':types.ModuleType('numpy')}):
                    with self.assertRaisesRegex(ValueError,'already running'):hlx.prepare(root,model,download=download)
                download.assert_not_called()
            finally:os.close(descriptor)


# A stand-in for HelixSR's build-only entry point: it writes what the real one builds (the network into HelixSR's DLL,
# Preset K into HelixSR/k) from its --dlss input, records its arguments, and exits 5 when asked to fail Preset K.
SETUP='''import sys,shutil
from pathlib import Path
a=sys.argv[1:];release=Path(a[0]);out=release/'HelixSR'
(release/'arguments.txt').write_text(' '.join(a[1:]))
model=Path(a[a.index('--dlss')+1]).read_bytes()
if '--fg-only' not in a:(out/'helixsr.dll').write_bytes(b'code+network:'+model)
if '--preset-k' in a:
    if (release/'fail-k').exists():sys.exit(5)
    (out/'k').mkdir(exist_ok=True)
    shutil.copyfile(release/'setup/preset-k/helixsr.dll',out/'k/helixsr.dll');shutil.copyfile(release/'setup/preset-k/helixsr.ini',out/'k/helixsr.ini')
    (out/'k/helixsr_modelk_kernels.pak').write_bytes(b'kernels:'+model);(out/'k/helixsr_modelk_weights.bin').write_bytes(b'weights:'+model)
'''
MODEL=b'NVIDIA DLSS input'
ARCHIVE={'HelixSR/helixsr.dll':b'code only','HelixSR/helixsr.ini':b'[Log]\r\nEnabled = true\r\n','HLX-FSR4/fsr.dll':b'HLX FSR 4, built',
         'helixsr-scaler/OptiScaler/amd.dll':b'AMD FSR','helixsr-scaler/OptiScaler/custom/HLX FSR 4 Full/ffx/full.dll':b'HLX FSR 4 Full, built',
         'helixsr-scaler/OptiScaler/custom/HLX FSR 4 Full/ffx/hlx_fsr4.ini':b'[HLX]\r\nDeepReuse = exact\r\n',
         'setup/helixsr_setup.py':SETUP.encode(),'setup/preset-k/helixsr.dll':b'Preset K code','setup/preset-k/helixsr.ini':b'[Network]\r\nModel = K\r\n'}


def spec_for(files):
    """A format 2 catalog over ARCHIVE whose built files are those the stand-in setup writes from MODEL."""
    pin=lambda source,data:{'source':source,'sha256':hlx.sha(data)}
    return {'format':2,'version':'3.3.0','folder':'HelixSR-3.3.0','archive':{'sha256':'a'*64,'file':'HelixSR-3.3.0.zip'},
            'model_inputs':{'dlss':hlx.sha(MODEL)},'compilers':{},'suggested':'hlx-dlss','providers':{
        'hlx-dlss':{'api':'dlss','entry':'helixsr.dll','build':'network','log':'helixsr.log','settings':{'name':'helixsr.ini'},
                    'files':{'helixsr.dll':pin('HelixSR/helixsr.dll',b'code+network:'+MODEL)}},
        'hlx-dlss-k':{'api':'dlss','entry':'helixsr.dll','build':'preset-k','log':'helixsr.log',
                      'settings':dict(pin('HelixSR/k/helixsr.ini',ARCHIVE['setup/preset-k/helixsr.ini']),name='helixsr.ini'),
                      'files':{'helixsr.dll':pin('HelixSR/k/helixsr.dll',ARCHIVE['setup/preset-k/helixsr.dll']),
                               'helixsr_modelk_kernels.pak':pin('HelixSR/k/helixsr_modelk_kernels.pak',b'kernels:'+MODEL),
                               'helixsr_modelk_weights.bin':pin('HelixSR/k/helixsr_modelk_weights.bin',b'weights:'+MODEL)}},
        'hlx-fsr4':{'api':'ffx','entry':'fsr.dll','log':'HLX_FSR.log','files':{'fsr.dll':pin('HLX-FSR4/fsr.dll',ARCHIVE['HLX-FSR4/fsr.dll']),
                    'amd.dll':pin('helixsr-scaler/OptiScaler/amd.dll',ARCHIVE['helixsr-scaler/OptiScaler/amd.dll'])}},
        'hlx-fsr4-full':{'api':'ffx','entry':'full.dll','log':'hlx_fsr4.log',
                         'settings':dict(pin('helixsr-scaler/OptiScaler/custom/HLX FSR 4 Full/ffx/hlx_fsr4.ini',ARCHIVE['helixsr-scaler/OptiScaler/custom/HLX FSR 4 Full/ffx/hlx_fsr4.ini']),name='hlx_fsr4.ini'),
                         'files':{'full.dll':pin('helixsr-scaler/OptiScaler/custom/HLX FSR 4 Full/ffx/full.dll',ARCHIVE['helixsr-scaler/OptiScaler/custom/HLX FSR 4 Full/ffx/full.dll'])}}}}


class PrepareFlow(unittest.TestCase):
    """Prepare Helix with a stand-in archive and build: what comes built needs no input or build tool; Model E and Preset K
    are built from the local DLSS input, each once; a Preset K that fails leaves the rest prepared."""
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        self.work=self.root/'cache';self.work.mkdir();self.archive=self.root/'HelixSR-3.3.0.zip'
        with zipfile.ZipFile(self.archive,'w') as z:
            for name,data in ARCHIVE.items():z.writestr('HelixSR-3.3.0/'+name,data)
        self.model=self.root/'nvngx_dlss.dll';self.model.write_bytes(MODEL);self.spec=spec_for({});self.lines=[];self.runs=[]
        real=hlx.subprocess.run
        def run(command,**kw):
            self.runs.append(command);return real(command,**kw)
        for context in (patch.object(hlx,'catalog',return_value=self.spec),patch.object(hlx,'cache',return_value=self.work),
                        patch.object(hlx,'sandbox',return_value=[]),patch.object(hlx,'requirements',return_value=[]),
                        patch.object(hlx.shutil,'which',return_value='/fake/wine'),patch.object(hlx.subprocess,'run',side_effect=run),
                        patch.dict(sys.modules,{'numpy':types.SimpleNamespace(__file__=str(self.root/'numpy/__init__.py'))})):
            context.start();self.addCleanup(context.stop)
    def prepare(self,**kw):
        return hlx.prepare(self.root,download=lambda pin,work:self.archive,report=self.lines.append,**kw)
    def ready(self):
        found=[]
        for name in hlx.NAMES:
            try:hlx.check(self.work/'HelixSR-3.3.0',self.spec,name);found.append(name)
            except ValueError:pass
        return found
    def arguments(self):
        return (self.work/'HelixSR-3.3.0/arguments.txt').read_text().split()

    def test_download_only_needs_no_input_and_builds_nothing(self):
        with patch.object(hlx,'requirements',return_value=['bwrap','wine','Python numpy']):
            self.prepare(build=False)
        self.assertEqual(self.ready(),['hlx-fsr4','hlx-fsr4-full']);self.assertEqual(self.runs,[])
        self.assertIn('HLX FSR 4, HLX FSR 4 Full',self.lines[-1]);self.assertNotIn('Model E',self.lines[-1])

    def test_a_replaced_upstream_archive_is_named_as_such(self):
        """The real download check (dependencies.download) against an archive of another size, then of another content:
        both are refused as a replaced archive, the first before its body is read."""
        import dependencies
        real=dependencies.urllib.request.urlopen;reads=[]
        class Counted:
            """The real response, counting the reads of its body."""
            def __init__(self,response):self.response=response;self.headers=response.headers
            def __enter__(self):return self
            def __exit__(self,*a):self.response.close()
            def read(self,size=-1):reads.append(size);return self.response.read(size)
        pin=dict(file='HelixSR-3.3.0.zip',url=self.archive.as_uri(),sha256=hlx.sha(self.archive.read_bytes()),size=self.archive.stat().st_size)
        for changed,how in ((dict(pin,size=pin['size']+1),'size'),(dict(pin,sha256='0'*64),'checksum')):
            reads.clear()
            with patch.object(hlx,'catalog',return_value=dict(self.spec,archive=changed)),contextlib.redirect_stdout(io.StringIO()), \
                 patch.object(dependencies.urllib.request,'urlopen',side_effect=lambda *a,**k:Counted(real(*a,**k))):
                with self.assertRaisesRegex(ValueError,'Download '+how+' mismatch.*replaced the 3.3.0 archive.*newer FreeFG release.*AMD FSR 4'):
                    hlx.prepare(self.root,download=dependencies.download,report=self.lines.append,build=False)
            self.assertEqual(bool(reads),how=='checksum')  # another size is refused before the body is read
            self.assertEqual(self.ready(),[]);self.assertEqual([p.name for p in self.work.iterdir() if p.name.startswith('.prepare-') or p.suffix=='.zip'],[])
        def offline(pin,work):raise ValueError('Cannot download HelixSR-3.3.0.zip')
        with self.assertRaisesRegex(ValueError,'^Cannot download'):hlx.prepare(self.root,download=offline,report=self.lines.append,build=False)

    def test_model_e_is_built_from_the_local_input_without_the_optional_preset_k(self):
        self.prepare(dlss=self.model)
        self.assertEqual(self.ready(),['hlx-dlss','hlx-fsr4','hlx-fsr4-full'])
        flags=self.arguments();self.assertEqual([f for f in flags if f.startswith('--')],['--no-fg','--yes','--no-hlx','--no-cache','--dlss','--dxc'])
        self.assertEqual(flags[flags.index('--dlss')+1],str(self.model.resolve()))

    def test_preset_k_alone_is_built_beside_an_earlier_model_e(self):
        self.prepare(dlss=self.model);self.prepare(dlss=self.model,preset_k=True)
        self.assertEqual(self.ready(),list(hlx.NAMES));self.assertEqual(len(self.runs),2)
        self.assertIn('--fg-only',self.arguments());self.assertIn('--preset-k',self.arguments())
        # Nothing left to build: no input, build tool or run is needed, and what was built stays.
        with patch.object(hlx,'requirements',return_value=['wine']):self.prepare(preset_k=True)
        self.prepare(build=False)
        self.assertEqual(self.ready(),list(hlx.NAMES));self.assertEqual(len(self.runs),2)

    def test_a_failed_preset_k_keeps_the_rest(self):
        with zipfile.ZipFile(self.archive,'a') as z:z.writestr('HelixSR-3.3.0/fail-k','')
        with self.assertRaisesRegex(ValueError,'HLX DLSS Preset K was not built'):self.prepare(dlss=self.model,preset_k=True)
        self.assertEqual(self.ready(),['hlx-dlss','hlx-fsr4','hlx-fsr4-full'])

    def test_a_build_that_differs_from_the_qualified_one_replaces_nothing(self):
        self.prepare(build=False);other=self.root/'other.dll';other.write_bytes(b'another DLSS build')
        with patch.object(hlx,'dlss_input',return_value=other):
            with self.assertRaisesRegex(ValueError,'not the qualified build'):self.prepare(dlss=other)
        self.assertEqual(self.ready(),['hlx-fsr4','hlx-fsr4-full']);self.assertEqual([p.name for p in self.work.glob('.prepare-*')],[])

    def test_a_build_needs_its_tools_and_an_input_the_user_gave_or_agreed_to(self):
        with patch.object(hlx,'requirements',return_value=['wine']):
            with self.assertRaisesRegex(ValueError,'requires wine'):self.prepare(dlss=self.model)
        wrong=self.root/'wrong.dll';wrong.write_bytes(b'not it')
        with self.assertRaisesRegex(ValueError,'SHA-256 '+hlx.sha(MODEL)):self.prepare(dlss=wrong)
        self.assertEqual(self.runs,[]);self.assertFalse((self.work/'HelixSR-3.3.0').exists())


class DlssInput(unittest.TestCase):
    """HLX DLSS is built from NVIDIA's DLSS DLL as a local file: the one given, else the copy this installer's cache
    already holds; a download from NVIDIA's repository only when the user agreed to it."""
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        self.cache=self.root/'cache';self.cache.mkdir()
        pins={'inputs':{'dlss':{'url':'https://example.invalid/nvngx_dlss.dll','file':'nvngx_dlss.dll','sha256':hlx.sha(MODEL)}},'hlx':spec_for({})}
        (self.root/'dependencies.json').write_text(json.dumps(pins))
        import dependencies
        context=patch.object(dependencies,'cache_dir',return_value=str(self.cache));context.start();self.addCleanup(context.stop)

    def test_given_cached_and_agreed_download(self):
        download=Mock(side_effect=lambda pin,cache:(Path(cache)/pin['file']).write_bytes(MODEL) and Path(cache)/pin['file'])
        with self.assertRaisesRegex(ValueError,'--no-download-dlss'):hlx.dlss_input(self.root,download=download)
        download.assert_not_called()
        self.assertEqual(hlx.dlss_input(self.root,fetch=True,download=download),self.cache/'nvngx_dlss.dll');download.assert_called_once()
        # The copy in the cache now serves without a download or an agreement; a changed copy does not.
        self.assertEqual(hlx.dlss_input(self.root,download=download),self.cache/'nvngx_dlss.dll');download.assert_called_once()
        (self.cache/'nvngx_dlss.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'--no-download-dlss'):hlx.dlss_input(self.root,download=download)
        given=self.root/'mine.dll';given.write_bytes(MODEL);self.assertEqual(hlx.dlss_input(self.root,given),given.resolve())
        with self.assertRaisesRegex(ValueError,'Select NVIDIA'):hlx.dlss_input(self.root,self.cache/'nvngx_dlss.dll')


class CatalogTests(unittest.TestCase):
    def test_the_packaged_catalog_names_every_provider_and_only_complete_pins(self):
        spec=hlx.catalog(Path(__file__).resolve().parents[1]/'packaging')
        self.assertEqual((spec['format'],spec['version'],spec['suggested'],list(spec['providers'])),(2,'3.3.0',hlx.SUGGESTED,list(hlx.NAMES)))
        self.assertEqual({name:hlx.built(spec,name) for name in hlx.NAMES},{'hlx-dlss':'network','hlx-dlss-k':'preset-k','hlx-fsr4':None,'hlx-fsr4-full':None})
        for name,descriptor in spec['providers'].items():
            self.assertIn(descriptor['entry'],descriptor['files'],name);self.assertIn(descriptor['api'],('dlss','ffx'))
            pins=[item['sha256'] for item in descriptor['files'].values()]+([descriptor['settings']['sha256']] if descriptor.get('settings',{}).get('source') else [])
            for value in pins:self.assertRegex(value,'^[0-9a-f]{64}$');self.assertNotEqual(value,'0'*64,name)
        self.assertRegex(spec['archive']['sha256'],'^[0-9a-f]{64}$')

    def test_an_earlier_catalog_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'dependencies.json').write_text(json.dumps({'hlx':{'format':1,'providers':{'hlx-dlss':{},'hlx-fsr4':{}}}}))
            with self.assertRaisesRegex(ValueError,'Unsupported HLX catalog'):hlx.catalog(folder)
            (Path(folder)/'dependencies.json').write_text('{}');self.assertIsNone(hlx.catalog(folder))


class SandboxTests(unittest.TestCase):
    """Prepare HLX runs upstream's build with namespaces of its own, an empty environment, the home folder and the
    session's sockets out of sight, and only its staging folder writable."""
    def layout(self,root):
        home=root/'home';staging=home/'.cache/hlx/.prepare-x';(staging/'tmp').mkdir(parents=True)
        (home/'secret.txt').write_text('private');model=home/'Downloads/model.dll';model.parent.mkdir();model.write_bytes(b'model')
        return home,staging,model

    def test_command(self):
        with tempfile.TemporaryDirectory() as folder:
            home,staging,model=self.layout(Path(folder))
            command=hlx.sandbox(staging,[model,Path('/usr/lib')],{'PATH':'/usr/bin','SSH_AUTH_SOCK':'/run/user/1/agent','DBUS_SESSION_BUS_ADDRESS':'x'},home,uid=1)
        self.assertEqual(command[:5],['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv']);self.assertEqual(command[-1],'--')
        self.assertNotIn('--dev-bind',command);self.assertIn(['--dev','/dev'],[command[i:i+2] for i in range(len(command))])
        pairs=[command[i:i+3] for i in range(len(command)) if command[i] in ('--tmpfs','--bind','--ro-bind','--setenv')]
        env={value[1]:value[2] for value in pairs if value[0]=='--setenv'}
        self.assertEqual(sorted(env),['HELIXSR_SETUP_JOBS','HOME','LANG','PATH','PYTHONDONTWRITEBYTECODE','PYTHONUNBUFFERED','TMPDIR','WINEDEBUG','XDG_CACHE_HOME'])
        self.assertEqual((env['HOME'],env['PATH'],env['TMPDIR']),(str(home),'/usr/bin','/tmp'))
        mounts=[value if value[0]!='--tmpfs' else value[:2] for value in pairs if value[0]!='--setenv']
        # The home folder emptied, then only the input inside it (read-only) and staging (writable) seen again.
        self.assertLess(mounts.index(['--tmpfs',str(home)]),mounts.index(['--ro-bind',str(model),str(model)]))
        self.assertLess(mounts.index(['--ro-bind',str(model),str(model)]),mounts.index(['--bind',str(staging),str(staging)]))
        self.assertIn(['--bind',str(staging/'tmp'),'/tmp'],mounts);self.assertNotIn(['--ro-bind','/usr/lib','/usr/lib'],mounts)

    def test_what_runs_inside_sees(self):
        # A trivial program with the same mounts: no home folder, no network, no session sockets, a clean environment,
        # the input readable, and writes only in staging. It needs bubblewrap with unprivileged namespaces, which the CI
        # container has not (installer_tests --fail-on-skip): there test_command alone checks the sandbox.
        import subprocess
        if not hlx.shutil.which('bwrap') or subprocess.run(['bwrap','--unshare-all','--ro-bind','/','/','true'],capture_output=True).returncode:return
        with tempfile.TemporaryDirectory() as folder:
            home,staging,model=self.layout(Path(folder))
            probe=('import json,os,socket,sys\nfrom pathlib import Path\nout={}\n'
                   'out["secret"]=Path(sys.argv[1]).exists();out["model"]=Path(sys.argv[2]).read_bytes().decode()\n'
                   'out["env"]=sorted(os.environ)\nout["runtime"]=sorted(os.listdir(sys.argv[4])) if os.path.isdir(sys.argv[4]) else []\n'
                   'try:socket.create_connection(("1.1.1.1",53),timeout=2);out["network"]=True\nexcept OSError:out["network"]=False\n'
                   'Path(sys.argv[3],"written").write_text("x")\n'
                   'try:Path(sys.argv[2]).write_bytes(b"changed");out["input_writable"]=True\nexcept OSError:out["input_writable"]=False\n'
                   'print(json.dumps(out))\n')
            runtime='/run/user/'+str(os.getuid())
            command=hlx.sandbox(staging,[model,Path(sys.executable).resolve().parent],home=home)+[sys.executable,'-I','-c',probe,str(home/'secret.txt'),str(model),str(staging),runtime]
            result=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            seen=json.loads(result.stdout.splitlines()[-1])
            self.assertEqual((seen['secret'],seen['model'],seen['network'],seen['runtime'],seen['input_writable']),(False,'model',False,[],False))
            self.assertNotIn('SSH_AUTH_SOCK',seen['env']);self.assertNotIn('DBUS_SESSION_BUS_ADDRESS',seen['env'])
            self.assertEqual((staging/'written').read_text(),'x');self.assertEqual(model.read_bytes(),b'model')


class OnDemand(unittest.TestCase):
    """install and configure with a HelixSR upscaler named prepare it first when it is not ready (install.py
    prepare_named_upscaler): the archive alone for the two that come built, the build for the two HLX DLSS forms."""
    def setUp(self):
        import install
        self.m=install
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.package=Path(self.tmp.name)
        (self.package/'opti').mkdir();(self.package/'opti/OptiScaler.dll').write_bytes(b'opti')
        self.spec=spec_for({})
        for target,value in (('catalog',Mock(return_value=self.spec)),('prepare',Mock()),('find',Mock(side_effect=ValueError('not prepared')))):
            context=patch.object(hlx,target,value);context.start();self.addCleanup(context.stop)
        context=patch.object(install,'say',Mock());self.say=context.start();self.addCleanup(context.stop)
        context=patch.object(install,'note',Mock());self.note=context.start();self.addCleanup(context.stop)

    def test_nothing_to_prepare(self):
        for name in (None,'auto','fsr4'):self.assertFalse(self.m.prepare_named_upscaler(self.package,name))
        hlx.find.side_effect=None;hlx.find.return_value=(self.spec,self.package,{})
        self.assertFalse(self.m.prepare_named_upscaler(self.package,'hlx-dlss'))
        hlx.catalog.return_value=None;hlx.find.side_effect=ValueError('x')
        self.assertFalse(self.m.prepare_named_upscaler(self.package,'hlx-dlss'))
        hlx.prepare.assert_not_called();self.say.assert_not_called();self.note.assert_not_called()

    def test_what_each_upscaler_prepares(self):
        for name,build,preset_k in (('hlx-dlss',True,False),('helixsr',True,False),('hlx-dlss-k',True,True),('hlx-fsr4',False,False),('hlx-fsr4-full',False,False)):
            hlx.prepare.reset_mock();self.note.reset_mock()
            self.assertTrue(self.m.prepare_named_upscaler(self.package,name))
            hlx.prepare.assert_called_once_with(self.package,None,report=self.m.say,progress=self.m.note,preset_k=preset_k,build=build,fetch_dlss=True)
            said=self.note.call_args[0][0];self.say.assert_not_called()  # what was prepared is hlx.prepare's own line
            self.assertIn('Preparing it first',said);self.assertEqual('built here' in said,build);self.assertEqual('many minutes' in said,preset_k)

    def test_a_local_copy_and_no_download(self):
        self.m.prepare_named_upscaler(self.package,'hlx-dlss',Path('/x/nvngx_dlss.dll'),False)
        hlx.prepare.assert_called_once_with(self.package,Path('/x/nvngx_dlss.dll'),report=self.m.say,progress=self.m.note,preset_k=False,build=True,fetch_dlss=False)

    def game(self,name=None):
        """A game folder with an installation record; with name, that upscaler's files in its own custom folder."""
        root=self.package/('game-'+(name or 'none'));(root/self.m.STATE).mkdir(parents=True);(root/'Game.exe').write_bytes(b'')
        (root/self.m.STATE/'state.json').write_text(json.dumps({'upscaler':{'name':'fsr4','target':'OptiScaler/fsr.dll'}}))
        if name:
            descriptor=self.spec['providers'][name];base=root/'OptiScaler/custom'/name/descriptor['api'];base.mkdir(parents=True)
            data={'fsr.dll':ARCHIVE['HLX-FSR4/fsr.dll'],'amd.dll':ARCHIVE['helixsr-scaler/OptiScaler/amd.dll']}
            for file in descriptor['files']:(base/file).write_bytes(data[file])
        return root/'Game.exe'

    def test_a_switch_in_games_that_hold_the_files_prepares_nothing(self):
        held,other=self.game('hlx-fsr4'),self.game()
        self.assertFalse(self.m.prepare_named_upscaler(self.package,'hlx-fsr4',games=[held],switch=True));hlx.prepare.assert_not_called()
        # An installation, a second game without the files, or a changed file: prepared as before.
        self.assertTrue(self.m.prepare_named_upscaler(self.package,'hlx-fsr4',games=[held]))
        self.assertTrue(self.m.prepare_named_upscaler(self.package,'hlx-fsr4',games=[held,other],switch=True))
        (held.parent/'OptiScaler/custom/hlx-fsr4/ffx/fsr.dll').write_bytes(b'changed')
        self.assertTrue(self.m.prepare_named_upscaler(self.package,'hlx-fsr4',games=[held],switch=True))
        self.assertEqual(hlx.prepare.call_count,3)

    def test_a_running_game_refuses_before_the_preparation(self):
        exe=self.game()
        with patch.object(self.m,'idle',side_effect=self.m.GameRunningError('Close the game before installing, updating or restoring')) as idle:
            with self.assertRaises(self.m.Refusal):self.m.prepare_named_upscaler(self.package,'hlx-dlss',games=[exe])
            idle.assert_called_once_with(exe.parent.resolve())
        hlx.prepare.assert_not_called();self.note.assert_not_called()
        # An upscaler that is ready checks nothing here: the installation makes its own check.
        hlx.find.side_effect=None;hlx.find.return_value=(self.spec,self.package,{})
        with patch.object(self.m,'idle') as idle:
            self.assertFalse(self.m.prepare_named_upscaler(self.package,'hlx-dlss',games=[exe]));idle.assert_not_called()

    def test_a_package_without_optiscaler_prepares_nothing(self):
        (self.package/'opti/OptiScaler.dll').unlink()
        self.assertFalse(self.m.prepare_named_upscaler(self.package,'hlx-dlss'));hlx.prepare.assert_not_called()




class OnDemandMain(unittest.TestCase):
    """install.py's command line around the preparation: which commands prepare, in which order with the game's own
    checks, what each game's outcome is when it fails, and what hlx passes on. install(), configure() and hlx.prepare are
    stand-ins; the rest of main() is real."""
    def setUp(self):
        import install
        self.m=install
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.spec=spec_for({});self.steps=[]
        def installed(package,exe,preview=False,route=None,fg_input=None,**kw):
            self.steps.append(('preview' if preview else 'install',exe.name,kw.get('upscaler')))
            if self.refuse and preview:raise self.refuse
        self.refuse=None
        for target,name,value in ((hlx,'catalog',Mock(return_value=self.spec)),(hlx,'find',Mock(side_effect=ValueError('not prepared'))),
                                  (hlx,'prepare',Mock(side_effect=lambda *a,**k:self.steps.append(('prepare',k['preset_k'],k['build'],k['fetch_dlss'])))),
                                  (install,'bundles_optiscaler',Mock(return_value=True)),(install,'install',Mock(side_effect=installed)),
                                  (install,'configure',Mock(side_effect=lambda exe,*a,**k:self.steps.append(('configure',exe.name,k.get('upscaler'))))),
                                  (install,'idle',Mock())):
            context=patch.object(target,name,value);context.start();self.addCleanup(context.stop)
    def game(self,name='Game',installed=False):
        folder=self.root/name;folder.mkdir();exe=folder/(name+'.exe');exe.write_bytes(b'MZ')
        if installed:
            (folder/self.m.STATE).mkdir()
            (folder/self.m.STATE/'state.json').write_text(json.dumps({'status':'installed','runtime':'xemfg','upscaler':{'name':'fsr4','target':'OptiScaler/fsr.dll'}}))
        return exe
    def run_main(self,*argv):
        out,err=io.StringIO(),io.StringIO()
        with patch.object(sys,'argv',['install.py',*map(str,argv)]),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:code=self.m.main()
            except SystemExit as stop:code='exit '+str(stop.code)
        events=[json.loads(line[len(self.m.EVENT_PREFIX):]) for line in out.getvalue().splitlines() if line.startswith(self.m.EVENT_PREFIX)]
        self.assertNotIn('Unexpected error',err.getvalue())
        return code,[(e['exe'].rsplit('/',1)[-1],e['result']) for e in events if e['type']=='outcome'],err.getvalue()

    def test_install_checks_the_game_then_prepares_then_installs(self):
        exe=self.game()
        code,outcomes,_=self.run_main('install',exe,'--route','opti','--fg-input','dlssg','--upscaler','hlx-dlss','--events')
        self.assertEqual(code,0);self.assertEqual(outcomes,[('Game.exe','install')])
        self.assertEqual(self.steps,[('preview','Game.exe','fsr4'),('prepare',False,True,True),('install','Game.exe','hlx-dlss')])

    def test_what_never_prepares(self):
        exe=self.game();folder=self.root/'prepared';folder.mkdir()
        for argv in (['install',exe,'--upscaler','hlx-dlss','--no-prepare'],['install',exe,'--upscaler','hlx-dlss','--helixsr',folder],
                     ['install',exe,'--upscaler','fsr4'],['install',exe],['preview',exe,'--upscaler','hlx-dlss']):
            self.steps.clear();self.run_main(*argv,'--route','opti','--fg-input','dlssg')
            self.assertEqual([step[0] for step in self.steps],['preview' if argv[0]=='preview' else 'install'],argv)
        hlx.find.side_effect=None;hlx.find.return_value=(self.spec,folder,{})  # ready: no silent preview either
        self.steps.clear();self.run_main('install',exe,'--route','opti','--fg-input','dlssg','--upscaler','hlx-dlss')
        self.assertEqual(self.steps,[('install','Game.exe','hlx-dlss')])

    def test_a_game_that_is_refused_starts_no_preparation(self):
        exe=self.game();self.refuse=self.m.Refusal('This game ships anti-cheat')
        code,outcomes,err=self.run_main('install',exe,'--route','opti','--fg-input','dlssg','--upscaler','hlx-dlss','--events')
        self.assertEqual((code,outcomes),(self.m.EXIT_REFUSED,[('Game.exe','refused')]));self.assertIn('anti-cheat',err)
        self.assertEqual(self.steps,[('preview','Game.exe','fsr4')])
        # No game, or a game that does not exist: the parser's and the installation's own errors, nothing prepared.
        self.steps.clear();self.assertEqual(self.run_main('install','--upscaler','hlx-dlss')[0],'exit 2');self.assertEqual(self.steps,[])

    def test_a_failed_preparation_is_each_games_outcome_and_runs_once(self):
        a,b=self.game('A'),self.game('B')
        hlx.prepare.side_effect=ValueError('HelixSR’s download is not the file this FreeFG release was checked with')
        code,outcomes,err=self.run_main('install',a,b,'--route','opti','--fg-input','dlssg','--upscaler','hlx-fsr4','--events')
        self.assertEqual((code,outcomes),(self.m.EXIT_FAILED,[('A.exe','failed'),('B.exe','failed')]))
        self.assertEqual(hlx.prepare.call_count,1);self.assertEqual(err.count('not the file this FreeFG release'),2)
        hlx.prepare.reset_mock();hlx.prepare.side_effect=hlx.Busy('HLX preparation is already running; wait for it to finish')
        code,outcomes,_=self.run_main('install',a,'--route','opti','--fg-input','dlssg','--upscaler','hlx-fsr4','--events')
        self.assertEqual((code,outcomes),(self.m.EXIT_REFUSED,[('A.exe','refused')]))

    def test_a_running_game_is_its_own_outcome_and_the_other_game_goes_on(self):
        a,b=self.game('A'),self.game('B')
        self.m.idle.side_effect=lambda root:(_ for _ in ()).throw(self.m.GameRunningError('Close the game before installing, updating or restoring')) if root.name=='B' else None
        code,outcomes,_=self.run_main('install',a,b,'--route','opti','--fg-input','dlssg','--upscaler','hlx-fsr4','--events')
        self.assertEqual((code,outcomes),(self.m.EXIT_REFUSED,[('A.exe','install'),('B.exe','running')]))
        self.assertEqual([step[0] for step in self.steps],['preview','prepare','install','preview'])

    def test_configure_prepares_for_an_installation_only(self):
        missing,exe=self.game('Bare'),self.game('Installed',installed=True)
        code,outcomes,err=self.run_main('configure',missing,'--upscaler','hlx-dlss-k','--events')
        self.assertEqual((code,outcomes),(self.m.EXIT_FAILED,[('Bare.exe','failed')]));self.assertIn('Install this build first',err);self.assertEqual(self.steps,[])
        code,outcomes,_=self.run_main('configure',exe,'--upscaler','hlx-dlss-k','--no-download-dlss','--events')
        self.assertEqual((code,outcomes),(0,[('Installed.exe','configure')]))
        self.assertEqual(self.steps,[('prepare',True,True,False),('configure','Installed.exe','hlx-dlss-k')])
        self.steps.clear();self.run_main('configure',exe,'--upscaler','hlx-dlss-k','--no-prepare')
        self.assertEqual(self.steps,[('configure','Installed.exe','hlx-dlss-k')])

    def test_hlx_downloads_the_dll_unless_told_not_to(self):
        for argv,fetch in ((['hlx'],True),(['hlx','--download-dlss'],True),(['hlx','--no-download-dlss'],False)):
            self.steps.clear();self.assertEqual(self.run_main(*argv)[0],0,argv);self.assertEqual(self.steps,[('prepare',False,True,fetch)])
        self.assertEqual(self.run_main('update','--all','--no-prepare')[0],'exit 2')
        self.assertEqual(self.run_main('status',self.game('S'),'--no-download-dlss')[0],'exit 2')


class HeldByTheGame(unittest.TestCase):
    """install.game_holds_upscaler says "held" only where hlx.layout then takes the game's own files (no preparation)."""
    def test_agrees_with_layout(self):
        import install
        spec=spec_for({})
        with tempfile.TemporaryDirectory() as folder, patch.object(hlx,'catalog',return_value=spec), \
             patch.object(hlx,'find',side_effect=ValueError('not prepared')),patch.object(hlx,'folders',return_value=[]):
            data={'fsr.dll':ARCHIVE['HLX-FSR4/fsr.dll'],'amd.dll':ARCHIVE['helixsr-scaler/OptiScaler/amd.dll']}
            cases=[('held',dict(data),{'name':'fsr4','target':'OptiScaler/fsr.dll'}),('root target',dict(data),{'name':'fsr4','target':'fsr.dll'}),
                   ('library root',dict(data),{'name':'fsr4','target':'x/fsr.dll','library_root':'OptiScaler'}),
                   ('changed',dict(data,**{'fsr.dll':b'other'}),{'name':'fsr4','target':'OptiScaler/fsr.dll'}),
                   ('missing',{'fsr.dll':data['fsr.dll']},{'name':'fsr4','target':'OptiScaler/fsr.dll'}),('no target',dict(data),{'name':'fsr4'})]
            held=[]
            for n,(label,files,current) in enumerate(cases):
                root=Path(folder)/str(n);(root/install.STATE).mkdir(parents=True);exe=root/'Game.exe';exe.write_bytes(b'')
                (root/install.STATE/'state.json').write_text(json.dumps({'upscaler':current}))
                library=current.get('library_root') or str(Path(current.get('target','OptiScaler/x')).parent)
                base=root/library/'custom/hlx-fsr4/ffx';base.mkdir(parents=True)
                for name,value in files.items():(base/name).write_bytes(value)
                says=install.game_holds_upscaler(spec,exe,'hlx-fsr4')
                try:hlx.layout(root,'hlx-fsr4',library,None,current,root);takes=True
                except (OSError,ValueError):takes=False
                if says:self.assertTrue(takes,label)
                held.append((label,says))
            self.assertEqual(held,[('held',True),('root target',True),('library root',True),('changed',False),('missing',False),('no target',False)])

if __name__=='__main__':unittest.main()
