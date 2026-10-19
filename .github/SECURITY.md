<!-- Copy of packaging/public/SECURITY.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/SECURITY.md instead. -->
# Security

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use **Report a vulnerability** in the
repository's **Security** tab (GitHub's private vulnerability reporting,
<https://github.com/daniel-h-0/freefg/security/advisories/new>), which only the maintainers can read. Describe the
problem, the affected file or step, and how to reproduce it. You will get an answer within a week. Fixes are released
as soon as they are ready and credited to you unless you prefer otherwise.

Only the latest release is supported.

## Concerns from rights holders

Rights holders (Intel, AMD, NVIDIA or others) can raise a concern about FreeFG privately through the same
**Report a vulnerability** form, or publicly in an issue at <https://github.com/daniel-h-0/freefg/issues>. GitHub's own
[DMCA process](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy) is open to them
too. We will answer promptly, and we will take the release down on a credible request.

## What FreeFG does on your computer

Knowing what it does helps you judge what would count as a vulnerability:

- **The installer** runs as your user and needs no root. It writes only to the game folders you select, its download
  cache, the selected games' entries in Steam, Heroic and Lutris, and, where a recipe needs it, the game's own settings
  file in its Proton prefix. It downloads only the pinned files in
  [PRIVACY.md](../packaging/public/PRIVACY.md), over HTTPS, and rejects any file whose size or SHA-256 differs. Archive members are
  extracted by their exact names to standard output, so an archive cannot choose where files are written, create
  links or set permissions. Nothing downloaded is executed by the installer. The game later loads the DLLs, as it would
  load any game DLL.
- **The proxy** (`libxess_fg.dll`) runs inside the game, under Proton. Before loading Intel's runtime, it checks the
  runtime's size and an FNV-1a hash and loads it by absolute path. The FNV-1a hash catches accidental replacement but
  is not a cryptographic check: anyone who can write to the game folder can already replace any DLL the game loads.
  The proxy opens no network connections and imports only `kernel32.dll` and `ucrtbase.dll`.
- **The pacing layer** (`libxefg_wave.so`) runs inside the game's process. It creates a small shared-memory page in
  `/dev/shm` with permissions `0600` and removes it when the game exits normally; a page left by a crash is removed at
  the next start. It connects to the game's own X display.
- **`extras/gamescope-cap-sys-nice`** asks for `sudo` once to give the gamescope binary the `CAP_SYS_NICE` file
  capability, and on pacman systems it adds a hook that re-applies it after updates. gamescope can then raise its own
  scheduling priority. Its environment loses `LD_PRELOAD` and similar variables, as for any program with file
  capabilities. `uninstall.sh` restores the earlier state.
- **`extras/steam-screensaver-in-game`** needs Steam's CEF remote-debugging port on 127.0.0.1:8080. Decky Loader turns
  it on; otherwise it is turned on by creating `~/.steam/steam/.cef-enable-remote-debugging`. That port is
  unauthenticated: any program running as any local user who can reach 127.0.0.1 can control the Steam client through
  it. Enable it only on a computer where you trust every local program. The helper itself only reads whether a game is
  running and sets the screensaver timeouts.

## Supply chain

- Release archives are built by the release tooling from a tagged commit. A `.sha256` file is published with each
  archive. The proxy and the pacing layer can be rebuilt from source and compared byte for byte ([BUILDING.md](../packaging/public/BUILDING.md)).
- The installer's dependencies are pinned by URL, size and SHA-256 in `dependencies.json`. Intel's runtime is signed by
  Intel; the pins identify the exact files, signed or not.
- The bundled OptiScaler build is built from public source at a pinned commit ([NOTICE.md](../NOTICE.md)).
- CI runs on pinned actions (by commit) and a pinned container image (by digest). It uploads reports, not binaries.
