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


if __name__=='__main__':unittest.main()
