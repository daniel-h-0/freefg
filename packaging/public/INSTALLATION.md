# Installation and recovery

Setup is `Start-freefg.sh` in the extracted release folder. `python3 install.py` there offers the same actions as
[commands](#command-line). **System Check** (`doctor`) reports what the computer lacks, and a game's page shows its
compatibility. Neither changes a file or downloads anything.

## Install a game

1. In Desktop Mode, run `Start-freefg.sh`.
2. Choose **Add a Game** and pick an installed Steam or Heroic game, or **Choose a Game Executable…** for any other
   game. Many Unreal games render from an `.exe` under `Binaries/Win64`.
3. On the game's page, read the verdict and choose **Install…**. Keep **Automatic** or choose an [input](#inputs),
   and choose an [upscaler](CONFIGURATION.md#upscalers). **Before installing** lists what Setup downloads and builds
   first for an HLX upscaler that is not on the computer yet.
4. Turn on each item under **Needs your OK** that you accept, then choose **Install**. Close the game and its
   launcher when Setup asks, and keep them closed until it is done.
5. Reopen the launcher. In the game, follow the steps that Setup listed under **After installing**.

Use borderless or windowed mode: XeFG does not interpolate in exclusive fullscreen. The first start after an install
or an input change takes longer while shaders compile. With VRR, keep the output below the display's refresh rate.

### Inputs

**Automatic** takes a verified recipe's input, or else the input that detection finds.

| Input | Option | In the game |
| --- | --- | --- |
| **DLSS FG** | `--fg-input dlssg` | Turn on DLSS frame generation. Streamline 2 or newer is required. |
| **FSR 3.1 FG**, **FSR 3.0 FG** | `--fg-input fsrfg`, `fsrfg30` | Turn on the game's FSR frame generation. HUD elements can be interpolated. |
| **OptiFG** | `--fg-input upscaler` | Choose the game's upscaler and turn its own frame generation off. HUD elements can be interpolated. |
| **Native XeSS FG** | `--route native` | Turn on the game's XeSS frame generation. |

### Changed files

Setup checks its downloads, backs up each file it replaces and puts the runtime and its configuration beside the
rendering `.exe`. It keeps your launch options and wrappers. The installation record and the original backups are in
`.bc250-xefg-experimental` in the game folder.

A supported OptiScaler installation keeps its loader file name. Unknown DLLs, custom DLL paths and other proxy mods
can require manual integration.

### Zenity dialogs

Setup's window needs PyGObject, GTK 4 and libadwaita 1.5 or newer. Without them Setup uses Zenity dialogs, and
`FREEFG_SETUP_UI=zenity ./Start-freefg.sh` selects them. There, choose **Add games**, then **Install** and
**Automatic per game**. An input you choose there applies to every selected game.

## Other launchers

Setup writes its launch settings into the game's Steam, Heroic or Lutris entry. It adds a recipe's graphics-API
switch only where the game's arguments choose no API. It also adds an argument that the game always needs (GTA V
Enhanced: `-nobattleye`). Setup does not edit Lutris's game arguments. Add such an argument there first, or the
install is refused (`required-args`).

### Manual launch settings

A game that only another launcher starts (Faugus, Bottles, umu-run or a script) gets the soft refusal `no-launcher`.

1. Accept it: under **Needs your OK** in Setup's window, with **Install anyway** in the Zenity dialogs, or with
   `--accept no-launcher`.
2. Setup installs the files and changes no launcher entry. Add the launch settings it prints to your launcher. In
   Setup's window they open ready to copy, and **Show…** on the game's **Launch settings** row shows them again.

The settings come as:

- `KEY=value` lines, then the game's arguments. In Faugus, put the lines under **Launch Arguments**. On a command
  line, put them before the command.
- One launch-options line in Steam's form (`KEY=value … %command% arguments`).
- Values without their quotes, for a launcher that takes each variable's name and value separately.
- Variables to delete where present, and how to combine a variable that the launcher already sets: keep your other
  Wine overrides, put FreeFG's layer first, add a list member.

Setup cannot read or edit that launcher:

- Faugus's global environment variables override a game's own. Keep `WINEDLLOVERRIDES` out of them.
- Leave GE-Proton's `PROTON_USE_OPTISCALER` and `PROTON_*_UPGRADE` unset for the game.
- Game settings that a recipe would write into the Proton prefix stay pending. Set them in the game.
- Status (`install.py status`) shows the settings again. It says `added by you` once the last session's logs show
  OptiScaler, the proxy and a frame-generation context, and `not yet confirmed` until then.
- An update or Rollback that changes the settings names each value to replace. Restore names what to remove.
- Update All finds the game through the local index. `install.py register GAME.exe` adds it again if the index was
  lost.

For integrators, `integration.json` in the release folder (`python3 install.py contract --json`) states the same
settings, the `OptiScaler.ini` keys and the file layout as data.

## Command line

```sh
python3 install.py doctor                 # host checks
python3 install.py check GAME.exe        # offline verdict
python3 install.py preview GAME.exe      # preview; may download dependencies
python3 install.py install GAME.exe       # automatic input and upscaler
python3 install.py status GAME.exe       # installed files and last session
python3 install.py library               # discovered and registered installations
python3 install.py plan GAME.exe         # preview an update
python3 install.py update GAME.exe       # apply it
python3 install.py rollback GAME.exe     # undo the most recent update, upscaler switch, recipe refresh or wiki settings
python3 install.py restore GAME.exe      # restore the original installation
```

`install` accepts an [input](#inputs) option,
`--upscaler auto|fsr4|hlx-dlss|hlx-dlss-k|hlx-fsr4|hlx-fsr4-full` ([upscalers](CONFIGURATION.md#upscalers)) and
`--dlss-helper auto|no|yes`. A named HLX upscaler is [prepared first](CONFIGURATION.md#preparation) when it is not
ready, which downloads and can build for many minutes; `--no-prepare` refuses instead, and `auto` never prepares one.
`--help` lists every option.

## Updates and recovery

Extract the new release before you update. Installations of 1.1.3.1 and later update in place. An earlier one needs
Restore, then Install. FreeFG installs no background updater and downloads no FreeFG release itself.

Setup's sidebar lists the games by state. A game's page shows its upscaler, its last session and its recovery
actions.

### Update

Choose **Update…** on a game's page or **Update All Games…** in the menu, review the grouped plan and apply it.
Close a launcher when the plan changes its entry.

An update covers FreeFG and Intel's runtime, the game's upscaler, the OptiScaler integration and the launcher fields
that FreeFG owns. It keeps your additions and the original backups.

- **Upscalers only** in the review leaves the FreeFG core as it is. The command line has `--component core|upscaler`.
- When a release brings a newer HelixSR, the review's **Before updating** switch prepares it first and then updates
  (`install.py hlx`, then `update`). Turned off, that upscaler is left as it is and the rest is updated.
- A managed binary that changed blocks the update of its game.
- `--loader winmm.dll` on `plan` or `update` moves the OptiScaler loader and its Wine override together. A name that
  another file uses is refused.
- If an update is interrupted, choose **Finish Update** or **Undo Update…** on the game's page (`update` or
  `rollback`).

**Update All Games…** covers every installation that Steam, Heroic and Lutris discovery or the local index finds,
also games you did not select. To limit the scope, use a game's **Update…** or name executables. There is no
transaction across games: running, missing, blocked, pinned and deferred games are reported separately, and the
games that succeeded stay updated.

```sh
python3 install.py plan --all
python3 install.py update --all --expect-plan DIGEST
```

`plan` prints the digest. With `--expect-plan`, the update changes nothing if any game's plan differs from the one
shown. The exit status is 3 when a game needs attention first (blocked or running) and none failed, and 1 for failed
or deferred work. A deployment job of your own may run `install.py update --all` after it extracts a verified
release.

### Game page actions

| Action | Command | Effect |
| --- | --- | --- |
| **Keep this release** | `pin GAME.exe`, `unpin GAME.exe` | Holds the game on its installed release, or lets it update again. |
| **Track** | `register GAME.exe` | Adds an installation that Update All does not find to the local index. The index is optional and can be rebuilt. Game files and recovery do not depend on it. |
| **Refresh recipe**, **Preview…** | `plan GAME.exe --refresh-recipe`, then `update GAME.exe --refresh-recipe` | Applies the gameplay-qualified input and launcher recipe in place. Game settings stay manual and saves are not changed. For another input, use OptiScaler's menu and restart the game. |

**Roll Back…** (`rollback GAME.exe`) undoes the most recent update, upscaler switch, recipe refresh or wiki settings.
Each game keeps one saved state of each kind: an update or upscaler switch, a recipe refresh, and wiki settings. A
recipe refresh or wiki settings applied after an update therefore keep the way back to the release before it.
Rollback keeps settings you edited since where possible and refuses when a managed binary changed since.

**Restore…** (`restore GAME.exe`) removes FreeFG's files, launch settings and private shader cache and puts the
original files back. It keeps your later edits where possible and reports each file it kept or could not put back.
Backups and logs stay in `.bc250-xefg-experimental`. The next Install renames that folder to
`.bc250-xefg-experimental-restored-…`.

## Uninstall and extras

Restore each game and run the `uninstall.sh` of each extra you installed. Then delete the extracted release folder,
the backups you no longer need and the download cache, normally `~/.cache/bc250-xefg-testers`.

The release has two optional extras under `extras/`, each with a README for its installation and removal:

- `gamescope-cap-sys-nice` grants gamescope scheduling priority. It needs sudo and affects nested gamescope
  launches. [Security](SECURITY.md#the-gamescope-capability-extra).
- `steam-screensaver-in-game` turns Steam's screensaver off while a game runs, through Steam's local DevTools
  endpoint. [Security](SECURITY.md#the-steam-screensaver-extra).
