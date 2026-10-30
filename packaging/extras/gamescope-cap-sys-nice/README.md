# gamescope scheduling priority

This optional extra grants gamescope `CAP_SYS_NICE`. Use it when `install.py doctor` or gamescope reports that the
capability is missing. It can reduce contention between gamescope and a busy game.

Run `./install.sh` and approve sudo. Restart Game Mode afterwards. The script records the original capability in
`/var/lib/bc250-xemfg-gamescope-cap/previous` and, when using `/usr/bin/gamescope` on a pacman system, installs an update
hook. Other installations need the script rerun after a gamescope update. For a wrapper on PATH, select the real ELF
binary with `GAMESCOPE=/path/to/gamescope ./install.sh`.

`./uninstall.sh` removes the hook and restores the capability recorded on the first install. Without that record it
makes no change.

## Nested gamescope and LD_PRELOAD

File capabilities can trigger glibc secure execution, stripping `LD_PRELOAD`, `LD_LIBRARY_PATH` and related variables
before gamescope starts its children. In a nested desktop launch, overlays or preload tools placed before gamescope
may disappear. Start the tool inside it, for example `gamescope -- mangohud %command%`.

In Steam Game Mode, Steam starts below gamescope and sets game preloads itself. Environment-enabled Vulkan layers
are not affected by the loader's `LD_*` filtering. Remove the extra if the nested-launch tradeoff is unsuitable.
