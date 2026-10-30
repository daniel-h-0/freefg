# Suppress Steam's screensaver during games

Steam's screensaver can render behind a game and consume GPU time, causing uneven pacing.

You can set the screensaver timeout to **Never** in Steam settings, or use this helper to suppress it only while a game
runs and restore your timeout afterwards.

- `./install.sh` installs and starts a user service under `~/.local/bin` and `~/.config/systemd/user`.
- `bc250-steam-screensaver-in-game status` reports its state.
- `./uninstall.sh` stops the service and restores any timeout it changed before removing the helper. If Steam is
  unreachable, it keeps the helper and saved timeout; open Steam, run `bc250-steam-screensaver-in-game restore`, then
  run the uninstaller again.

The helper reads game-running state and writes Steam's AC/battery screensaver timeouts through the local DevTools
endpoint at `127.0.0.1:8080`. Decky commonly enables it. Otherwise, create
`~/.steam/steam/.cef-enable-remote-debugging` and restart Steam. This endpoint is unauthenticated; local programs that
can reach it can control Steam. Use it only on a machine where you trust those programs.
