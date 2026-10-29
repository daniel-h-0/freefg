# SPDX-License-Identifier: MIT
"""Library discovery is optional and rebuildable; its failures must not invalidate a game transaction."""
import fcntl
import io
import os
import unittest
from unittest.mock import patch
from test_update import UpdateFixture, OLD, NEW, m, launcher_config


class LibraryIndexTests(UpdateFixture):
    def test_install_registers_and_restore_removes_only_its_entry(self):
        m.install(self.package,self.exe,route='opti')
        rows=m.freefg_library.entries()
        self.assertEqual([row['exe'] for row in rows],[str(self.exe)])
        self.assertEqual(rows[0]['installation_id'],self.record()['installation_id'])
        self.assertEqual(m.freefg_library.location().stat().st_mode&0o777,0o600)
        m.restore(self.exe)
        self.assertEqual(m.freefg_library.entries(),[])

    def test_registered_game_survives_removed_launcher_entry(self):
        m.install(self.package,self.exe,route='opti');self.config.unlink()
        self.assertEqual(m.library(),[self.exe])
        self.assertEqual(self.run_quiet(m.update,self.exe,self.new)[0],'update')
        self.assertEqual(m.freefg_library.entries()[0]['package'],NEW)

    def test_index_can_be_deleted_and_rebuilt_without_touching_game_files(self):
        m.install(self.package,self.exe,route='opti');before=self.snapshot();record=self.record()
        m.freefg_library.location().unlink()
        self.assertEqual(m.library(),[self.exe])
        self.run_quiet(m.register_installation,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.record(),record)
        self.assertEqual(m.freefg_library.entries()[0]['exe'],str(self.exe))

    def test_legacy_registration_assigns_identity_without_reinstalling(self):
        m.install(self.package,self.exe,route='opti');record=self.record();record.pop('installation_id')
        m.save_record(self.game/m.STATE,record);m.freefg_library.location().unlink();before=self.snapshot()
        self.run_quiet(m.register_installation,self.exe)
        self.assertEqual(self.snapshot(),before);self.assertTrue(self.record()['installation_id'])
        with patch.object(launcher_config,'installation_roots',return_value=[]):
            self.assertEqual(m.library(),[self.exe])

    def test_offline_entry_is_reported_and_retained(self):
        m.install(self.package,self.exe,route='opti');self.exe.unlink()
        rows=m.library_inventory();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'unavailable');self.assertEqual(m.library(),[])
        self.assertEqual(len(m.freefg_library.entries()),1)
        with patch.object(m,'__file__',str(self.new/'install.py')),patch('sys.argv',['install.py','update','--all']):
            code,out=self.run_quiet(m.main)
        self.assertEqual(code,1);self.assertIn('Unavailable',out)
        self.assertEqual(self.record()['package'],OLD)

    def test_damaged_index_is_not_overwritten_and_launcher_discovery_still_works(self):
        m.install(self.package,self.exe,route='opti');path=m.freefg_library.location();path.write_bytes(b'broken index')
        before=path.read_bytes()
        with patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(m.library(),[self.exe])
        result,out=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(result,'update');self.assertIn('registration needs attention',out)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.record()['package'],NEW)

    def test_busy_index_does_not_fail_a_completed_update(self):
        m.install(self.package,self.exe,route='opti')
        lock=os.open(m.freefg_library.location().with_suffix('.lock'),os.O_RDWR)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            status,out=self.run_quiet(m.update,self.exe,self.new)
        finally:os.close(lock)
        self.assertEqual(status,'update');self.assertEqual(self.record()['package'],NEW)
        self.assertIn('registration needs attention',out)
        self.assertEqual(m.library_inventory()[0]['package'],NEW)

    def test_index_symlink_is_not_followed(self):
        m.install(self.package,self.exe,route='opti');path=m.freefg_library.location();path.unlink()
        other=self.root/'other.json';other.write_text('untouched');path.symlink_to(other)
        with self.assertRaisesRegex(ValueError,'symlink'):m.freefg_library.load()
        status,_=self.run_quiet(m.update,self.exe,self.new)
        self.assertEqual(status,'update');self.assertEqual(other.read_text(),'untouched')


if __name__=='__main__':unittest.main()
