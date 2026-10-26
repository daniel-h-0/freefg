# Suppress Steam's screensaver during games

In the tested September 2026 Steam Game Mode client, the screensaver continued rendering behind games. Its periodic
cross-fades consumed GPU time and caused bursts of uneven VRR refresh. Long cutscenes and idle gameplay could trigger
it.

You can set the screensaver timeout to **Never** in Steam settings, or use this helper to suppress it only while a game
runs and restore your timeout afterwards.

- `./install.sh` installs and starts a user service under `~/.local/bin` and `~/.config/systemd/user`.
- `bc250-steam-screensaver-in-game status` reports its state.
- `./uninstall.sh` removes it and restores any timeout it changed.

The helper reads game-running state and writes Steam's AC/battery screensaver timeouts through the local DevTools
endpoint at `127.0.0.1:8080`. Decky commonly enables it. Otherwise, create
`~/.steam/steam/.cef-enable-remote-debugging` and restart Steam. This endpoint is unauthenticated; local programs that
can reach it can control Steam. Use it only on a machine where you trust those programs.
