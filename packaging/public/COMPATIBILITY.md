# Game compatibility

FreeFG needs a 64-bit DirectX 12 game with a supported upscaler or frame-generation input. Motion vectors and
depth come through OptiScaler's hooked inputs or the game's native XeSS FG. Detection alone does not prove that a
game will generate correctly; use Check before installation and Status after a run.

## Recipe observations

The package has **19 curated BC-250 recipes**. Setup labels them **Verified on BC-250**, but their evidence ranges
from gameplay to installation-only or failed checks. Run **Check** for the matched recipe, observation and manual
steps; check the running game for actual frame generation. The complete recorded observations are in
[`recipes.json`](https://github.com/daniel-h-0/freefg/blob/main/packaging/recipes/recipes.json).

## Verdicts

Check and Install produce an offline verdict before dependency downloads or game-file writes.

| Verdict | Meaning |
| --- | --- |
| Verified on BC-250 | A curated recipe supplies the input/settings; Check shows the recorded observation. |
| Community-reported on BC-250 | A reviewed user report, not reproduced by a maintainer. |
| Automatic, guided by the OptiScaler wiki | Detection is supplemented by one of 758 imported wiki entries. Most reports concern Windows and other GPUs. |
| Automatic (no recipe) | Detection found a DirectX 12 input; in-game behavior is unverified. |
| Not supported | A refusal with a reason and suggested next step. |

Setup may ask you to select an upscaler, enable the game's FG option, or use DirectX 12. Wiki advice is shown with its
applicability; only selected rules are applied automatically. After a run, Check also summarises the installation's
logs. [Source precedence](ARCHITECTURE.md#which-source-decides).

## Refusals

A soft refusal can be accepted per game: **Install anyway** in Setup, `--accept CODE` on the command line. Neither
lifts the anti-cheat refusal (kind `risk`), which has an [override](#anti-cheat) of its own.

| Code | Reason | What to do |
| --- | --- | --- |
| `anticheat` (risk) | Anti-cheat files (Easy Anti-Cheat, BattlEye, GameGuard, XIGNCODE3, EA Javelin, ACE, mhyprot, EQU8, PunkBuster, Vanguard); FreeFG loads DLLs into the game process, which anti-cheat software may treat as tampering. | Nothing by default; an [override](#anti-cheat) for one game risks a ban. |
| `native-linux` | Steam installed the Linux version. | Force a Proton version in the game's Compatibility properties, let Steam download the Windows version, Check again. |
| `32bit` | XeFG and FreeFG are 64-bit only. | Nothing. |
| `api-vulkan`, `api-opengl`, `api-dx11`, `no-dx12` | No DirectX 12 path. DirectX 11 stays refused until qualified: OptiScaler's DX11-to-DX12 bridge gave a black screen under this Proton stack. | Nothing; soft when you chose the input yourself, since detection can miss what you know. |
| `no-input` | DirectX 12, but no upscaler or frame-generation SDK. | As above. |
| `input-unconfirmed` (soft) | A Unity game whose only DLSS evidence is the DLL Unity's NVIDIA module bundles; its code never names DLSS. | Accept only if the game's menu offers DLSS. |
| `wrong-exe` | The executable is a launcher stub. | Choose the executable Check names. |
| `no-launcher` (soft) | No Steam, Heroic or Lutris entry starts the executable. | Add the game to one of them, or accept and set the printed launch settings in your launcher ([other launchers](INSTALLATION.md#other-launchers)). |
| `shared-entry` | The launcher entry already starts an installation in another folder. | Restore that installation first. |
| `ge-optiscaler` | GE-Proton is told to place its own OptiScaler or upscaler DLLs (`PROTON_USE_OPTISCALER`, `PROTON_*_UPGRADE`). | Remove the variable from the launch options. |
| `protonfix-api` (soft) | GE-Proton's fix for the game switches it away from DirectX 12. | Accepting adds `PROTONFIXES_DISABLE=1`, turning off all of GE-Proton's fixes for the game (Check names what else the fix does); Restore removes it. |
| `wiki-not-working` (soft) | The OptiScaler wiki lists the game as not working (matched by launcher ID, or by executable and title; a title-only match is a note). | Accept to try anyway. |
| `installed`, `xessmfg`, `version-dll`, `existing-files`, `existing-optiscaler`, `optiscaler-paths`, `helixsr-installer`, `recipe-exe`, `ascii-path` | The game folder: an installation not yet restored, another frame-generation mod, an OptiScaler setup this package does not take over, HelixSR installed by its own installer, the wrong executable of a verified game, a path that is not ASCII. Check shows the plan Install follows once resolved. | What Check names: Restore, remove the other mod (HelixSR: with its own uninstaller), or choose the other executable. |

## Anti-cheat

FreeFG loads DLLs into the game process. Anti-cheat software may refuse them or ban the account, including in an
offline mode. Check detects files; it cannot establish that anti-cheat is inactive. FreeFG does not hide itself,
and Restore cannot undo a ban.

The override is **per game**. In Setup, choose **Override anti-cheat refusal...**, read the warning, then type
`I accept that my account may be banned` exactly. Cancel is the default. Other hard refusals still apply.

```sh
python3 install.py install GAME.exe --accept-anticheat-risk
python3 install.py install A.exe B.exe --accept-anticheat-risk=A.exe
```

At a terminal, each named game requires the typed sentence. Without a terminal, supply it explicitly:

```sh
python3 install.py install GAME.exe --accept-anticheat-risk \
    --confirm-anticheat-risk 'I accept that my account may be banned'
```

The record keeps the detected anti-cheat names, time and package. Status and Check display the accepted risk.
Restore ends the override; a new Install requires it again. The maintainers cannot reverse account bans.

## Checking a game

Check reads files and local system state; it makes no external network requests or persistent changes
([PRIVACY.md](PRIVACY.md#what-the-installer-reads-and-writes-on-your-computer) lists what it reads).

```sh
python3 install.py check GAME.exe            # verdict, plan, your steps, wiki notes, the last run
python3 install.py check GAME.exe --report   # plus issue text without paths or user name
python3 install.py check --all               # one line per installed Steam and Heroic game
python3 install.py install GAME.exe --accept protonfix-api            # a soft refusal, accepted
python3 install.py install A.exe B.exe --accept 'protonfix-api=A.exe' # accepted for one of the games only
```

## From report to recipe

Any report of a game on a BC-250, working or not, can become a community recipe and then a verified one: paste the
`--report` text into an issue with the **Game report** form ([CONTRIBUTING.md](CONTRIBUTING.md#game-recipes)).
