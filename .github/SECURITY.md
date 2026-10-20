<!-- Copy of packaging/public/SECURITY.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/SECURITY.md instead. -->
# Security

## Reporting a vulnerability

Report security problems privately, not in a public issue: use **Report a vulnerability** in the repository's
**Security** tab (GitHub's private vulnerability reporting,
<https://github.com/daniel-h-0/freefg/security/advisories/new>). Only the maintainers can read these reports.

- Describe the problem, the affected file or step, and how to reproduce it.
- You will get an answer within a week.
- Fixes are released as soon as they are ready, and credited to you unless you prefer otherwise.
- Only the latest release is supported.

## Concerns from rights holders

Rights holders (Intel, AMD, NVIDIA or others) can raise a concern about FreeFG:

- privately, through the same **Report a vulnerability** form;
- publicly, in an issue at <https://github.com/daniel-h-0/freefg/issues>;
- through GitHub's own
  [DMCA process](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy).

The maintainers answer promptly and take the release down on a credible request.

## What runs on your computer

This section lists what each part of FreeFG runs and with which rights, as a basis for judging a report.

### The installer

- It runs as your user and needs no root. [PRIVACY.md](../packaging/public/PRIVACY.md#what-the-installer-reads-and-writes-on-your-computer)
  lists what it reads and writes.
- It downloads only the pinned files listed in [PRIVACY.md](../packaging/public/PRIVACY.md#what-the-installer-downloads), over HTTPS, and
  rejects any file whose size or SHA-256 differs.
- It extracts archive members by their exact names to standard output, so an archive cannot choose where files are
  written, create links or set permissions. The HelixSR archive is unpacked whole: only regular files and folders below
  its release folder, with the archive's executable bits; any other member is refused.
- It executes nothing it downloads. The game later loads the DLLs, as it loads any game DLL.

### The proxy

`libxess_fg.dll` runs inside the game, under Proton.

- Before it loads Intel's runtime, it checks the runtime's size and FNV-1a hash, and it loads the runtime by absolute
  path. The FNV-1a hash catches accidental replacement; it is not a cryptographic check. Anyone who can write to the
  game folder can already replace any DLL the game loads.
- It opens no network connections and imports only `kernel32.dll` and `ucrtbase.dll`.

### The pacing layer

`libxefg_wave.so` runs inside the game's process.

- It creates a small shared-memory page in `/dev/shm` with permissions `0600`, and removes it when the game exits
  normally. A page left by a crash is removed at the next start.
- It connects to the game's own X display.

### The gamescope capability extra

`extras/gamescope-cap-sys-nice` asks for `sudo` once to give the gamescope binary the `CAP_SYS_NICE` file capability.

- gamescope can then raise its own scheduling priority.
- As for any program with file capabilities, gamescope's environment loses `LD_PRELOAD` and similar variables, also for
  the programs it starts.
- On pacman systems the extra adds a hook that applies the capability again after updates.
- `uninstall.sh` restores the earlier state.

### The Steam screensaver extra

`extras/steam-screensaver-in-game` needs Steam's CEF remote-debugging port on 127.0.0.1:8080.

- Decky Loader turns the port on. Without Decky, creating `~/.steam/steam/.cef-enable-remote-debugging` turns it on.
- The port is unauthenticated: any program, running as any local user, that can reach 127.0.0.1 can control the Steam
  client through it. Enable it only on a computer where you trust every local program.
- The helper's own use of the port is described in [PRIVACY.md](../packaging/public/PRIVACY.md#extras).

## Supply chain

- Release archives are built by the release tooling from a tagged commit. A `.sha256` file is published with each
  archive.
- The proxy and the pacing layer can be rebuilt from source and compared byte for byte ([BUILDING.md](../packaging/public/BUILDING.md)).
- The installer's dependencies are pinned by URL, size and SHA-256 in `dependencies.json`. Intel's runtime is signed by
  Intel; the pins identify the exact files, signed or not.
- The bundled OptiScaler build is built from public source at a pinned commit
  ([NOTICE.md](../NOTICE.md#optiscaler-source)).
- CI uses actions pinned by commit and a container image pinned by digest. A scheduled, informational run also builds
  with current packages. CI uploads build records and reports, not binaries.
