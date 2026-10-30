<!-- Copy of packaging/public/SECURITY.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/SECURITY.md instead. -->
# Security

## Reporting a vulnerability

Use GitHub's private [Report a vulnerability](https://github.com/daniel-h-0/freefg/security/advisories/new) form rather
than a public issue. Describe the affected component, impact and reproduction steps. Maintainers aim to respond
within a week, release fixes when ready and credit reporters unless they prefer otherwise. Only the latest release
is supported.

## Concerns from rights holders

Rights holders can use the same private form, a [public issue](https://github.com/daniel-h-0/freefg/issues), or GitHub's
[DMCA process](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy). Maintainers will
respond and take a release down on a credible request.

## What runs on your computer

### The installer

The installer runs as your user, without root. It edits selected game files, launcher entries and recipe settings;
[PRIVACY.md](../packaging/public/PRIVACY.md) lists its reads, writes and downloads.

Downloads use pinned HTTPS URLs, sizes and SHA-256 hashes. Pinned dependency members are extracted by expected name and
checked individually. The optional HelixSR download is verified as a complete archive; its extraction is restricted to
regular files and directories beneath its release folder, with an extraction-size limit. Prepare HLX runs the
pinned archive’s build-only Python entry point under bubblewrap, with the host read-only and network disabled.
Only its staging directory is writable. It uses local model inputs and checked shader compilers, never the upstream
game installer or package-manager setup. Game DLLs execute when the game runs.

### The proxy

`libxess_fg.dll` runs in the game under Proton. It verifies Intel's runtime size/FNV-1a identity and loads it by absolute
path. FNV-1a detects accidental replacement; it is not a cryptographic trust check. Installation uses SHA-256, and a
user who can write the game folder can replace its DLLs. The proxy imports only `kernel32.dll` and `ucrtbase.dll` and
has no network client.

### The pacing layer

The native Vulkan layer runs in the game process. It creates a `0600` shared-memory page in `/dev/shm` for the proxy's
generation signal, removes it on normal exit and cleans stale pages on later starts. It also connects to the game's
X display to wake gamescope.

### The gamescope capability extra

`extras/gamescope-cap-sys-nice` uses sudo to grant `CAP_SYS_NICE` to the gamescope binary and, on supported pacman
installations, add an update hook. It records the previous capability for `uninstall.sh` to restore. File capabilities
can strip loader variables such as `LD_PRELOAD` from nested gamescope launches; see the extra's README.

### The Steam screensaver extra

`extras/steam-screensaver-in-game` runs as your user. It reads game-running state and changes screensaver timeouts
through Steam's local DevTools endpoint, `127.0.0.1:8080`.

That endpoint is unauthenticated. Any local program or user able to reach it can control Steam. Decky commonly enables
it; the helper's README describes manual setup. Enable it only where you trust local programs. The helper restores
your timeout after the game exits or on removal when Steam is reachable. If removal cannot restore it, the helper
and saved value remain in place for a retry.

## Supply chain

- Release archives have SHA-256 sidecars, source/build records and a qualification receipt. Their source is represented
  by the corresponding release tag; documentation-only main-branch changes can be newer than an archive.
- Proxy, layer and shader builds can be reproduced with the pinned tools ([BUILDING.md](../packaging/public/BUILDING.md)).
- Installer inputs are pinned in `dependencies.json`. Runtime signature/identity and download hashes serve different
  purposes; a matching pin identifies a file, not its behavior.
- The bundled OptiScaler has a pinned public source/build route ([NOTICE.md](../NOTICE.md#optiscaler-source)).
- CI pins actions and its container image, compares runtime hashes, and uploads reports rather than binaries.
  A separate informational job uses current packages.
