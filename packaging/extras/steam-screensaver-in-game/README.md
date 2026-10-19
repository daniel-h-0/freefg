# Steam screensaver behind games (optional extra)

In Steam Game Mode, Steam starts its screensaver after the idle time under Settings > Customization > Screensaver
(5 minutes on AC by default) even while a game is running. You don't see it (the game stays in front), but every
20 seconds its slideshow cross-fades for 2 seconds and takes GPU time from the game. With frame generation that shows
as VRR flicker in bursts (refreshes alternating 8 and 21 ms). In-game controller input resets Steam's idle timer, so
you meet it in long cutscenes, when standing still to watch, or when leaving a game running.

Two ways around it:

- **Simplest:** set the screensaver timeout to *Never* in Steam's settings. That also turns it off in the Steam menus.
- **This helper:** keeps the timeout at *Never* only while a game runs and puts your own value back when the game
  exits. `./install.sh` installs it as a user service (`~/.local/bin`, `~/.config/systemd/user`); `./uninstall.sh`
  removes it and writes back any value it changed. `bc250-steam-screensaver-in-game status` shows what it sees.

The helper talks to Steam's local CEF DevTools endpoint (127.0.0.1:8080). Decky Loader turns that on; without Decky,
create the empty file `~/.steam/steam/.cef-enable-remote-debugging` and restart Steam. It only reads whether a game runs
and writes the two screensaver timeouts (AC and battery), the way Steam's settings page does. Tested on a BC-250
(CachyOS, Steam Game Mode, September 2026 client).
