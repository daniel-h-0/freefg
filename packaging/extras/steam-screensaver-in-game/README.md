# Steam screensaver helper

Steam's screensaver can render behind a game and take GPU time, which makes pacing uneven. Set the screensaver
timeout to **Never** in Steam's settings, or use this helper. It turns the screensaver off only while a game runs and
restores your timeout afterwards.

| Command | Effect |
| --- | --- |
| `./install.sh` | Installs the helper in `~/.local/bin` and a user service in `~/.config/systemd/user`, and starts the service. |
| `bc250-steam-screensaver-in-game status` | Reports the helper's state. |
| `./uninstall.sh` | Stops the service, restores a timeout the helper changed and removes the helper. |

If Steam is unreachable, `./uninstall.sh` keeps the helper and the saved timeout. Open Steam, run
`bc250-steam-screensaver-in-game restore`, then run the uninstaller again.

## DevTools endpoint

The helper reads whether a game runs and writes Steam's AC and battery screensaver timeouts through Steam's local
DevTools endpoint, `127.0.0.1:8080`. Decky commonly enables it. Otherwise, create
`~/.steam/steam/.cef-enable-remote-debugging` and restart Steam.

The endpoint has no authentication: a local program that can reach it can control Steam. Use it only on a computer
where you trust those programs.
