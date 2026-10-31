# Installation and recovery

Use Setup in the extracted release folder, or run `python3 install.py` there. **Check system** (`doctor`) checks host
dependencies; **Check** reports a game's compatibility without changing files or downloading dependencies.

## Install a game

1. In Desktop Mode run `Start-freefg.sh`, select **Add games**, and choose the rendering `.exe`. For many Unreal
   games it is under `Binaries/Win64` rather than the game-root launcher.
2. Select **Install** → **Automatic per game**, choose an upscaler and read the verdict. Close the game and its
   launcher when prompted. Explicit input choices apply to every selected game; install different inputs separately.
3. Reopen the launcher. In the game, choose the upscaler input and frame-generation setting named by Setup:

| Input | In-game setting |
| --- | --- |
| DLSS FG | Enable DLSS frame generation; Streamline 2 or newer is required. |
| FSR 3.1/3.0 FG | Enable the game's FSR frame generation; HUD elements can be interpolated. |
| OptiFG | Enable the selected upscaler and disable the game's own frame generation. |
| Native XeSS FG | Enable the game's XeSS frame generation. |

Use borderless or windowed mode: XeFG does not interpolate in exclusive fullscreen. The first start after install or
an input change can take longer while shaders compile. For VRR, keep output below the display's refresh ceiling.

Setup verifies dependencies, backs up replaced files and adds the runtime, configuration and launcher settings beside
the rendering executable. It preserves existing launcher options and wrappers. Supported OptiScaler installations keep
their loader filename; unknown DLLs, custom paths and other proxy mods can require manual integration. The installation
record and original backups are in `.bc250-xefg-experimental`.

## Other launchers

Setup writes its launch settings into the game's Steam, Heroic or Lutris entry. A game that only another launcher
starts (Faugus, Bottles, umu-run or a script) is refused with `no-launcher`. Choose **Install anyway**
(`--accept no-launcher`): Setup installs the files as usual, changes no launcher entry and prints the environment
variables, and any game arguments, to add to that launcher. In Faugus, put the `KEY=value` lines under **Launch
Arguments**; on a command line, put them before the command; where a launcher takes each name and value separately,
leave out the quotes around a value. Faugus's global environment variables override a game's own, so keep
`WINEDLLOVERRIDES` out of them.

Status shows the settings again, an update or Rollback that changes them prints the new values, and Restore lists them
for removal. Setup cannot check that launcher for GE-Proton's `PROTON_USE_OPTISCALER` or `PROTON_*_UPGRADE`; leave them
unset for the game. Game settings a recipe would write into the Proton prefix stay pending: set them in the game.

## Command line

```sh
python3 install.py doctor                 # host checks
python3 install.py check GAME.exe        # offline verdict
python3 install.py preview GAME.exe      # preview; may download dependencies
python3 install.py install GAME.exe       # automatic input, AMD FSR 4
python3 install.py status GAME.exe       # installed files and last session
python3 install.py library               # discovered and registered installations
python3 install.py plan GAME.exe         # preview an update
python3 install.py update GAME.exe       # apply it
python3 install.py rollback GAME.exe     # undo the most recent update or provider switch
python3 install.py restore GAME.exe      # restore the original installation
```

`install` accepts `--fg-input dlssg|upscaler|fsrfg|fsrfg30`, `--route native`,
`--upscaler fsr4|hlx-dlss|hlx-fsr4` and `--dlss-helper auto|no|yes`. Use `--help` for the full interface.
[Preparing and changing upscalers](CONFIGURATION.md#upscalers).

## Updates and recovery

Extract the new release before updating. Setup's **Library** shows versions, providers, last-session logs and recovery
state. Select entries and choose **Update selected**, or preview **Update all**. On the command line, run
`python3 install.py plan --all` followed by `python3 install.py update --all` to apply the plan.

Update all combines Steam, Heroic and Lutris discovery with the optional local index; it can find installations you
did not select. Use **Update selected** or name specific executables to limit the scope. Running, missing, blocked,
pinned or deferred games are reported separately. Successful games remain updated; a nonzero update exit status
signals deferred or failed work. There is no atomic transaction across games.

Compatible 1.1.3.1, 1.1.4 and 1.1.5 installations update in place. Updates cover the compatible FreeFG/Intel set,
selected upscaler, OptiScaler integration and owned launcher fields while retaining user additions and original
backups. Close launchers if the plan changes their entries. **Update upscalers** keeps the FreeFG core; the CLI
supports `--component core|upscaler`. Unprepared providers can be deferred, and changed owned binaries block the
coupled transaction. `--loader winmm.dll` on `plan` or `update` moves the loader and its Wine override together;
an occupied name is refused.

- **Pin** / **Unpin** holds or resumes all updates for a game (`pin GAME.exe` / `unpin GAME.exe`).
- **Register** adds an existing installation to the optional index. The index can be rebuilt; game files and recovery
  do not depend on it.
- **Rollback** restores the saved state before the most recent update **or provider switch**. Each game retains one
  completed generation; later settings edits are preserved where possible, and conflicting binary edits are refused.
- **Restore** removes owned files and launcher changes and restores originals, preserving later user edits where
  possible. It reports conflicts and leaves backups and logs in a `.bc250-xefg-experimental-restored-…` folder.

If an update is interrupted, retry Update or use Rollback. Use **Refresh recipe** for a gameplay-qualified input and
launcher recipe; the equivalent is `plan GAME.exe --refresh-recipe`, then `update GAME.exe --refresh-recipe`. Game
settings are manual and saves are not changed by refresh. For a custom input, use OptiScaler's menu and restart.

FreeFG installs no background updater and does not download new FreeFG releases itself. A user-managed deployment
job may invoke `install.py update --all` after extracting a verified release.

## Uninstall and extras

Restore each game, run any installed extra's `uninstall.sh`, then remove the extracted package and unneeded backups
and cache. Downloaded files are normally under `~/.cache/bc250-xefg-testers`.

The release offers two optional extras:

- **gamescope-cap-sys-nice** grants scheduling priority; it requires sudo and affects nested-launch environments.
- **steam-screensaver-in-game** suppresses Steam's screensaver during games through its local DevTools endpoint.

Each extra includes its own install and removal instructions. [Privileges and local interfaces](SECURITY.md#what-runs-on-your-computer).
