#!/bin/sh
# Remove the pacman hook and give gamescope back the capability install.sh found (the distribution's, yours, or none).
set -eu
state=/var/lib/bc250-xemfg-gamescope-cap/previous
hook=/etc/pacman.d/hooks/bc250-xemfg-gamescope-cap.hook
if ! sudo test -f "$state"; then
    # Without install.sh's record there is nothing of ours to undo; never touch a capability someone else set.
    sudo rm -f "$hook"
    echo "Nothing to undo: install.sh has not run here, or uninstall.sh already did."
    exit 0
fi
gs=$(sudo sed -n 1p "$state")
previous=$(sudo sed -n 2p "$state")
sudo rm -f "$hook"
if [ -n "$gs" ] && [ -e "$gs" ]; then
    if [ -n "$previous" ]; then
        sudo setcap "$previous" "$gs"
        echo "Restored gamescope's previous capability: $previous"
    else
        sudo setcap -r "$gs" 2>/dev/null || true
        echo "Removed gamescope's capability."
    fi
fi
sudo rm -f "$state"
sudo rmdir "$(dirname "$state")" 2>/dev/null || true
echo "Removed. Restart Steam Game Mode to apply."
