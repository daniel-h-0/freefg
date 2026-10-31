# SPDX-License-Identifier: MIT
import fcntl
import hashlib
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
            spec={'model_inputs':{'dlss':digest,'amd':digest}};download=Mock()
            descriptor=os.open(root/'.prepare.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(descriptor,fcntl.LOCK_EX)
            try:
                with patch.object(hlx,'catalog',return_value=spec),patch.object(hlx,'cache',return_value=root),patch.object(hlx.shutil,'which',return_value='/fake/tool'),patch.dict(sys.modules,{'numpy':types.ModuleType('numpy')}):
                    with self.assertRaisesRegex(ValueError,'already running'):hlx.prepare(root,model,model,download=download)
                download.assert_not_called()
            finally:os.close(descriptor)


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
        self.assertEqual(sorted(env),['HELIXSR_SETUP_JOBS','HOME','LANG','PATH','PYTHONDONTWRITEBYTECODE','TMPDIR','WINEDEBUG','XDG_CACHE_HOME'])
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


if __name__=='__main__':unittest.main()
