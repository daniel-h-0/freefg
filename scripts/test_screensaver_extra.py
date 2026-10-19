# SPDX-License-Identifier: MIT
"""extras/steam-screensaver-in-game: the user's timeout is saved before it is changed and forgotten only after it is
written back; unreadable settings and failed writes keep it."""
import importlib.util, json, tempfile, unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / 'packaging/extras/steam-screensaver-in-game/bc250-steam-screensaver-in-game.py'


class FakeSteam:
    def __init__(self, running, settings, fail_writes=False):
        self.running, self.settings, self.fail_writes, self.writes = running, dict(settings), fail_writes, []

    def evaluate(self, script):
        if 'SetSetting' in script:
            if self.fail_writes:
                return None
            self.writes.append(script)
            return 'ok'
        return json.dumps(dict(running=self.running, settings=self.settings))


class ScreensaverExtra(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('bc250_screensaver', HELPER)
        self.h = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.h)
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.h.STATE = Path(self.dir.name) / 'state.json'
        self.names = list(self.h.FIELDS)

    def test_saved_before_change_and_written_back_after_the_game(self):
        steam = FakeSteam(True, {self.names[0]: 300, self.names[1]: 0})
        self.h.step(steam)
        self.assertEqual(json.loads(self.h.STATE.read_text()), {self.names[0]: 300})
        self.assertEqual(len(steam.writes), 1)
        steam.running, steam.settings[self.names[0]] = False, 0
        self.h.step(steam)
        self.assertEqual(len(steam.writes), 2)
        self.assertFalse(self.h.STATE.exists())

    def test_unreadable_settings_keep_the_saved_value(self):
        self.h.save({self.names[0]: 300})
        steam = FakeSteam(False, {self.names[0]: None, self.names[1]: None})
        self.h.step(steam)
        self.assertEqual(steam.writes, [])
        self.assertEqual(self.h.saved(), {self.names[0]: 300})

    def test_failed_write_back_keeps_the_saved_value(self):
        self.h.save({self.names[0]: 300})
        steam = FakeSteam(False, {self.names[0]: 0, self.names[1]: 0}, fail_writes=True)
        with self.assertRaises(self.h.Unavailable):
            self.h.step(steam)
        self.assertEqual(self.h.saved(), {self.names[0]: 300})

    def test_value_the_user_chose_meanwhile_is_left(self):
        self.h.save({self.names[0]: 300})
        steam = FakeSteam(False, {self.names[0]: 600, self.names[1]: 0})
        self.h.step(steam)
        self.assertEqual(steam.writes, [])
        self.assertFalse(self.h.STATE.exists())

    def test_no_reply_from_the_ui_is_unavailable_not_a_crash(self):
        class Silent:
            def evaluate(self, script):
                return None
        with self.assertRaises(self.h.Unavailable):
            self.h.read_state(Silent())

    def test_corrupt_state_file_is_ignored(self):
        self.h.STATE.write_text('{"system_idle_screensaver_ac_sec": "x", "other": 1')
        self.assertEqual(self.h.saved(), {})


if __name__ == '__main__':
    unittest.main()
