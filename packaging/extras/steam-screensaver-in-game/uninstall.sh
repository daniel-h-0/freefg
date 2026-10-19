#!/bin/sh
# Stops the helper (its stop step writes back any timeout it changed) and removes it. If Steam was not reachable to
# write the value back, the helper stays installed so it can still be done.
set -eu
helper="$HOME/.local/bin/bc250-steam-screensaver-in-game"
state="${XDG_STATE_HOME:-$HOME/.local/state}/bc250-steam-screensaver-in-game.json"
systemctl --user disable --now bc250-steam-screensaver-in-game.service 2>/dev/null || true
if [ -f "$state" ] && [ -x "$helper" ]; then "$helper" restore || true; fi
if [ -f "$state" ]; then
  echo "Steam was not reachable, so your screensaver timeout is still 'Never' (saved in $state)."
  echo "With Steam open, run: $helper restore   then run this uninstaller again."
  exit 1
fi
rm -f "$HOME/.config/systemd/user/bc250-steam-screensaver-in-game.service" "$helper"
systemctl --user daemon-reload
echo "Removed."
