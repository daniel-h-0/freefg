#!/bin/sh
# Grant gamescope CAP_SYS_NICE now and, on pacman systems, after every gamescope update. Needs sudo once.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# The real binary: a wrapper script or symlink on PATH (~/.local/bin, distrobox exports) cannot hold a capability.
gs=${GAMESCOPE:-$(command -v gamescope)} || { echo "gamescope not found"; exit 1; }
gs=$(readlink -f "$gs")
if [ "$(head -c4 "$gs" 2>/dev/null | od -An -c | tr -d ' ')" != '177ELF' ]; then
    echo "$gs is not the gamescope program (a script or wrapper). Run: GAMESCOPE=/path/to/real/gamescope sh $0"
    exit 1
fi
command -v setcap >/dev/null || { echo "setcap not found (install libcap)"; exit 1; }
state=/var/lib/bc250-xemfg-gamescope-cap/previous
hook=/etc/pacman.d/hooks/bc250-xemfg-gamescope-cap.hook
# Remember, once, the capability gamescope had before (its distribution's, yours, or none) so uninstall.sh can put it back.
if ! sudo test -e "$state"; then
    current=$(getcap "$gs" 2>/dev/null || true)
    previous=$(printf '%s' "${current#"$gs"}" | sed 's/^[[:space:]]*//')
    sudo install -d -m755 "$(dirname "$state")"
    printf '%s\n%s\n' "$gs" "$previous" | sudo tee "$state" >/dev/null
    [ -z "$previous" ] || echo "gamescope already had $previous (from your distribution or set earlier); uninstall.sh keeps it."
fi
if [ -d /etc/pacman.d ] && [ "$gs" = /usr/bin/gamescope ]; then
    sudo install -Dm644 "$here/bc250-xemfg-gamescope-cap.hook" "$hook"
else
    echo "No update hook for this system: after a gamescope update, run this again."
fi
sudo setcap cap_sys_nice=eip "$gs"
getcap "$gs"
echo "Restart Steam Game Mode (or reboot) so the running gamescope picks it up."
