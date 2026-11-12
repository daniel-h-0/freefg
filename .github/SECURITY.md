<!-- Copy of packaging/public/SECURITY.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/SECURITY.md instead. -->
# Security

## Reporting a vulnerability

Use GitHub's private [Report a vulnerability](https://github.com/daniel-h-0/freefg/security/advisories/new) form, not
a public issue. Name the affected component, the impact and the steps to reproduce it. Maintainers aim to answer
within a week, release a fix when it is ready and credit the reporter unless asked not to. Only the latest release is
supported.

## Rights holders

Rights holders can use the same private form, a [public issue](https://github.com/daniel-h-0/freefg/issues) or GitHub's
[DMCA process](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy). Maintainers
answer and take a release down on a credible request.

## Components

### The installer

The installer runs as your user, without root. It edits the selected game's files, its launcher entry and the game
settings a recipe names. [Privacy](../packaging/public/PRIVACY.md) lists what it reads, writes and downloads.

- Downloads use pinned HTTPS URLs and SHA-256 hashes, and sizes where pinned. Files inside an archive are extracted
  by their expected name and checked one by one.
- HelixSR's archive is checked as a whole. Only regular files and folders beneath its release folder are unpacked,
  up to a size limit.
- Prepare Helix runs the pinned archive’s build script under bubblewrap, in namespaces and a session of its own: no
  network, no other processes, no terminal input, and an empty environment apart from its build settings. The host
  is read-only. Your home folder, `/tmp`, the session’s runtime folder (D-Bus, PipeWire, Wayland and agent sockets)
  and the system bus are hidden, except for the files the build reads. Only its staging folder is writable. Its
  inputs are the pinned DLSS DLL and a checked shader compiler. HelixSR's game installer and package setup never run.
- The installed DLLs run when the game runs.

### The proxy

`libxess_fg.dll` runs in the game under Proton. It checks Intel's runtime by size and FNV-1a and loads it by absolute
path. That check catches an accidental replacement and is no cryptographic guarantee; installation checks SHA-256.
Anyone who can write the game folder can replace its DLLs. The proxy imports only `kernel32.dll` and `ucrtbase.dll`
and has no network client.

### The pacing layer

The native Vulkan layer runs in the game process. It creates one shared-memory page in `/dev/shm` with mode `0600`,
which the proxy uses to signal that frames are being generated. The layer removes the page on a normal exit and
clears stale pages at later starts. It also connects to the game's X display to wake gamescope.

### The gamescope capability extra

`extras/gamescope-cap-sys-nice` uses sudo to grant `CAP_SYS_NICE` to the gamescope binary and, on supported pacman
installations, add an update hook. It records the previous capability for `uninstall.sh` to restore. File capabilities
can strip loader variables such as `LD_PRELOAD` from nested gamescope launches; see the extra's README.

### The Steam screensaver extra

`extras/steam-screensaver-in-game` runs as your user. It reads game-running state and changes screensaver timeouts
through Steam's local DevTools endpoint, `127.0.0.1:8080`.

That endpoint has no authentication: any local program or user that can reach it can control Steam. Decky usually
enables it, and the helper's README describes the manual setup. Enable it only where you trust the local programs.
The helper restores your timeout when the game exits, and on removal if Steam is reachable. If removal cannot restore
it, the helper and the saved value stay in place for another try.

## Supply chain

- Release archives come with SHA-256 files, source and build records and a qualification receipt. Their source is
  the release tag. Main can be ahead of an archive by documentation-only commits.
- The proxy, the layer and the shaders rebuild to the same bytes with the pinned tools ([Building](../packaging/public/BUILDING.md)).
- The installer's inputs are pinned in `dependencies.json`. A matching pin identifies a file. It says nothing about
  what the file does.
- The bundled OptiScaler has a pinned public source and build route ([Notices](../NOTICE.md#optiscaler-source)).
- CI pins its actions and container image, compares the built hashes with the pinned ones and uploads reports, no
  binaries. A second, informational job builds with current packages.
