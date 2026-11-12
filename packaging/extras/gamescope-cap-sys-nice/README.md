# gamescope scheduling priority

This optional extra grants gamescope `CAP_SYS_NICE`. Use it when `install.py doctor` or gamescope reports that the
capability is missing. It can reduce contention between gamescope and a busy game.

## Install

1. Run `./install.sh` and approve sudo.
2. Restart Game Mode.

The script records the capability that gamescope had before in `/var/lib/bc250-xemfg-gamescope-cap/previous`. For
`/usr/bin/gamescope` on a pacman system it also installs an update hook. On other systems, run the script again after
a gamescope update. If `gamescope` on your PATH is a wrapper, name the real ELF binary:
`GAMESCOPE=/path/to/gamescope ./install.sh`.

## Remove

Run `./uninstall.sh` and restart Game Mode. The script removes the hook and restores the recorded capability. Without
that record it leaves gamescope's capability as it is.

## Nested gamescope and LD_PRELOAD

A file capability can trigger glibc's secure execution, which strips `LD_PRELOAD`, `LD_LIBRARY_PATH` and related
variables before gamescope starts its children. In a nested desktop launch, an overlay or preload tool placed before
gamescope may disappear. Start the tool inside gamescope, for example `gamescope -- mangohud %command%`.

In Steam Game Mode, Steam starts below gamescope and sets the game's preloads itself. Vulkan layers that the
environment enables are not affected by the loader's `LD_*` filtering. Remove the extra if this tradeoff does not
suit your nested launches.
