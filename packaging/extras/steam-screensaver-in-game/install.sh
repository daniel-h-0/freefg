#!/bin/sh
# Installs the helper for the current user and starts it. Undo: uninstall.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
install -D -m 0755 "$here/bc250-steam-screensaver-in-game.py" "$HOME/.local/bin/bc250-steam-screensaver-in-game"
install -D -m 0644 "$here/bc250-steam-screensaver-in-game.service" "$HOME/.config/systemd/user/bc250-steam-screensaver-in-game.service"
systemctl --user daemon-reload
systemctl --user enable --now bc250-steam-screensaver-in-game.service
if ! "$HOME/.local/bin/bc250-steam-screensaver-in-game" status >/dev/null 2>&1; then
  echo "Installed, but Steam's DevTools endpoint is not reachable yet (127.0.0.1:8080)."
  echo "It is there with Decky Loader; otherwise: touch ~/.steam/steam/.cef-enable-remote-debugging and restart Steam."
else
  echo "Installed and connected to Steam."
fi
