# gamescope realtime priority (optional)

SteamOS ships gamescope with the `CAP_SYS_NICE` capability; Arch, CachyOS and most other distributions do not. Without
it gamescope logs `No CAP_SYS_NICE, falling back to regular-priority compute and threads`, and while a game keeps the GPU
busy its composition and page flips queue behind the game's work. With frame generation that shows as uneven VRR
refresh (measured on a BC-250 before this extra was added; `install.py doctor` reports whether it is set).

`./install.sh` (asks for sudo once) sets the capability on the installed gamescope and, on pacman-based systems, adds a
hook that sets it again after every gamescope update. Restart Steam Game Mode afterwards.

`./uninstall.sh` removes the hook and gives gamescope back the capability it had before: `install.sh` records it (the
distribution's, one you set, or none) in `/var/lib/bc250-xemfg-gamescope-cap/previous` the first time it runs. A
gamescope package update in between changes nothing about that: uninstall restores the state recorded before the first
install. Without that record (never installed, or already uninstalled) it changes nothing.

## Side effect: nested gamescope loses LD_PRELOAD

A file capability puts gamescope in glibc's secure-execution mode (`AT_SECURE`), as for a setuid program. The dynamic
loader then ignores `LD_PRELOAD` and `LD_LIBRARY_PATH` for gamescope and removes them (and a few other variables such
as `TMPDIR`) from its environment, so the programs gamescope starts do not inherit them either.

- Steam Game Mode is unaffected: gamescope starts first and Steam, its child, sets its own preloads (the overlay) for
  each game it launches.
- A nested launch such as the Steam launch option `gamescope -- %command%` on a desktop session, or
  `mangohud gamescope -- %command%`, loses the preloads set before gamescope: Steam's in-game overlay and preload-based
  tools (MangoHud's OpenGL mode, `LD_PRELOAD` shims) are missing in the game. Start such tools inside the nested
  command instead (`gamescope -- mangohud %command%`); Vulkan layers enabled by environment variables (`MANGOHUD=1`,
  `ENABLE_VKBASALT=1`) still pass through, since only the loader's `LD_*` family and similar variables are removed.
- If that matters more than composition priority, run `./uninstall.sh`.
