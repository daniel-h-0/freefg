# SPDX-License-Identifier: MIT
import json
import unittest
from unittest.mock import patch
from test_update import UpdateFixture,m
import library_view


class LibraryViewTests(UpdateFixture):
    def test_integrity_and_runtime_evidence_are_not_conflated(self):
        m.install(self.package,self.exe,route='opti')
        with patch.object(m,'library_inventory',return_value=[dict(exe=self.exe,status='installed',package='release',upscaler='fsr4',pinned=False)]):
            row=library_view.rows(m)[0]
        self.assertEqual(row['files'],'Check with Status')
        self.assertEqual(row['runtime'],'No recent log')
        self.assertEqual(row['recovery'],'None')

    def test_pending_recovery_and_unavailable_drive_remain_visible(self):
        m.install(self.package,self.exe,route='opti');record=self.record();record['pending_update']={'generation':'incomplete'}
        (self.game/m.STATE/'state.json').write_text(json.dumps(record))
        unavailable=dict(exe=self.root/'offline/Game.exe',status='unavailable',package='release',upscaler='fsr4',pinned=True)
        with patch.object(m,'library_inventory',return_value=[dict(unavailable,exe=self.exe,status='installed'),unavailable]):rows=library_view.rows(m)
        self.assertEqual(rows[0]['recovery'],'Interrupted update');self.assertEqual(rows[0]['files'],'Recovery needed')
        self.assertEqual(rows[1]['files'],'Unavailable');self.assertEqual(rows[1]['pin'],'Pinned')


if __name__=='__main__':unittest.main()
