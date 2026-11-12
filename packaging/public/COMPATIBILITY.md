# Game compatibility

FreeFG needs a 64-bit DirectX 12 game with an upscaler or frame-generation input. Motion vectors and depth come
through the inputs that OptiScaler hooks, or through the game's native XeSS FG. Detection does not prove that a game
generates frames correctly. Check a game before you install, and read its last session after you play.

## Checking a game

Check reads files and local system state. It makes no network request and changes nothing
([what it reads](PRIVACY.md#local-files)). In Setup, Check is **Compatibility** and **Compatibility report** on a
game's page, and Status is **Installation details**.

```sh
python3 install.py check GAME.exe            # verdict, plan, your steps, wiki notes, the last run
python3 install.py check GAME.exe --report   # plus issue text without paths or user name
python3 install.py check --all               # one line per installed Steam and Heroic game
python3 install.py install GAME.exe --accept protonfix-api            # a soft refusal, accepted
python3 install.py install A.exe B.exe --accept 'protonfix-api=A.exe' # accepted for one of the games only
```

## Verdicts

Check and Install reach the verdict offline, before any download or change to the game's files.

| Verdict | Meaning |
| --- | --- |
| Verified on BC-250 | A curated [recipe](#recipes) supplies the input and settings. Check shows the recorded observation. |
| Community-reported on BC-250 | A reviewed user report that no maintainer reproduced. |
| Automatic, guided by the OptiScaler wiki | Detection, supplemented by one of 739 imported wiki game entries. Most wiki reports concern Windows and other GPUs. |
| Automatic (no recipe) | Detection found a DirectX 12 input. Behavior in the game is unverified. |
| Not supported | A [refusal](#refusals) with its reason and the next step. |

Setup may ask you to select an upscaler in the game, turn on the game's frame generation or use DirectX 12. Wiki
advice is shown with whether it applies. Install writes only reviewed wiki settings by itself, and the others wait
for your [review](CONFIGURATION.md#wiki-settings). [Source precedence](ARCHITECTURE.md#source-order).

## Recipes

The package has 20 curated BC-250 recipes, which Setup labels **Verified on BC-250**. Their evidence differs: some
rest on gameplay, some on an installation check only, and some record a failed check. Check shows the matched recipe,
its recorded observation and your steps. Whether frames are generated shows only in the running game.
[`recipes.json`](https://github.com/daniel-h-0/freefg/blob/main/packaging/recipes/recipes.json) has every recorded
observation.

### GTA V Enhanced

Short Story Mode starts on GE-Proton11-11 reached the bank prologue with sustained 2× generation, including a fresh
start with XeFG enabled. The bundled OptiScaler fixes Social Club's auxiliary swapchain crash and leaves its overlay
on.

- Use OptiFG, select DLSS in GTA and leave GTA's own frame generation off.
- Factory wrapping stays at auto/false. Remove any old override that disables Social Club's DLL.
- Install adds `-nobattleye` (Story Mode only) beside any API switch you chose.
- Install sets OptiScaler's `[BC250] RequireArgument=-nobattleye`. In a start without that argument, OptiScaler
  stays a plain proxy, without hooks or frame generation. A 1.2.0 installation gets the setting with
  **Refresh recipe**.
- On the Steam route, only the game process loads OptiScaler, and it receives the argument.
- Restore FreeFG before you play GTA Online. OptiScaler's DLL still loads beside BattlEye, inactive. A start without
  `-nobattleye` was not tested.
- The [anti-cheat refusal](#anti-cheat) still applies.

[Reproduction, fix and limits](https://github.com/daniel-h-0/freefg/blob/main/research/recipes/verified/gta-v-enhanced.md).

## Refusals

A refusal stops the installation. Refusals are hard unless the table marks them. A soft one can be accepted for one
game: **Install anyway** in Setup, or `--accept CODE` on the command line. Neither lifts the anti-cheat refusal (kind
`risk`), which has an [override](#anti-cheat) of its own.

| Code | Reason | What to do |
| --- | --- | --- |
| `anticheat` (risk) | Anti-cheat files: Easy Anti-Cheat, BattlEye, nProtect GameGuard, XIGNCODE3, EA Javelin, Anti-Cheat Expert (ACE), mhyprot, EQU8, PunkBuster, Denuvo Anti-Cheat, Vanguard. Anti-cheat software may treat FreeFG's DLLs in the game process as tampering. | Nothing by default. An [override](#anti-cheat) for one game risks a ban. |
| `native-linux` | Steam installed the Linux version. | Force a Proton version in the game's Compatibility properties, let Steam download the Windows version, then check again. |
| `no-exe` | No Windows game executable was found. | Choose the game's `.exe`. |
| `32bit` | XeFG and FreeFG are 64-bit only. | Nothing. |
| `api-vulkan`, `api-opengl`, `api-dx9`, `api-dx11`, `no-dx12` | No DirectX 12 path. DirectX 11 stays refused until a game is qualified: OptiScaler's DX11-to-DX12 bridge gave a black screen under this Proton stack. | Nothing. Soft when you chose the input yourself, since detection can miss what you know. |
| `no-input` | DirectX 12, but no upscaler or frame-generation SDK. | As above. |
| `no-native-xefg` | You chose Native XeSS FG, and no `libxess_fg.dll` is beside the executable. | Choose an OptiScaler input. |
| `input-unconfirmed` (soft) | A Unity game whose only DLSS evidence is the DLL that Unity's NVIDIA module bundles. Its code never names DLSS. | Accept only if the game's menu offers DLSS. |
| `wrong-exe` | The executable is a launcher stub. | Choose the executable that Check names. |
| `no-launcher` (soft) | No Steam, Heroic or Lutris entry starts the executable. | Add the game to one of them, or accept and add the printed launch settings to your launcher ([other launchers](INSTALLATION.md#other-launchers)). |
| `required-args` | A Lutris entry lacks an argument that the game always needs. | Add the argument in Lutris. |
| `shared-entry` | The launcher entry already starts an installation in another folder. | Restore that installation first. |
| `ge-optiscaler` | GE-Proton is told to place its own OptiScaler or upscaler DLLs (`PROTON_USE_OPTISCALER`, `PROTON_*_UPGRADE`). | Remove the variable from the launch options. |
| `protonfix-api` (soft) | GE-Proton's fix for the game switches it away from DirectX 12. | Accepting adds `PROTONFIXES_DISABLE=1`, which turns off all of GE-Proton's fixes for the game. Check names what else the fix does. Restore removes the variable. |
| `wiki-not-working` (soft) | The OptiScaler wiki lists the game as not working, matched by launcher ID or by executable and title. A title-only match is a note. | Accept to try anyway. |
| `installed`, `left-installed` | The game folder has an installation that is not restored, or files that its Restore could not put back. | Restore it, or put the files back with your launcher's Verify or Repair. |
| `xessmfg`, `existing-files`, `existing-optiscaler`, `optiscaler-paths` | The game folder has another frame-generation mod, another mod's files or an OptiScaler setup that this package does not take over. | Remove or restore what Check names. |
| `helixsr-installer` | HelixSR's own installer placed HelixSR in the game folder. | Remove it with HelixSR's uninstaller. |
| `recipe-exe` | The executable is not the one a verified game renders from. | Choose the executable that Check names. |
| `ascii-path` | The game folder's path is not ASCII only. | Move the game to an ASCII-only path. |

Once a game-folder refusal is resolved, Check shows the plan that Install follows.

## Anti-cheat

FreeFG loads DLLs into the game process and does not hide itself. Anti-cheat software may refuse them or ban the
account, also in an offline mode. Check detects anti-cheat files. It cannot establish that the anti-cheat is
inactive. Restore cannot undo a ban, and the maintainers cannot reverse one.

The override applies to one game:

1. On the game's page, choose **Override…** under **Install despite anti-cheat**. In the Zenity dialogs, choose
   **Override anti-cheat refusal...**.
2. Read the warning. Cancel is the default.
3. Type `I accept that my account may be banned` exactly.

Other hard refusals still apply.

```sh
python3 install.py install GAME.exe --accept-anticheat-risk
python3 install.py install A.exe B.exe --accept-anticheat-risk=A.exe
```

At a terminal, each named game requires the typed sentence. Without a terminal, supply it:

```sh
python3 install.py install GAME.exe --accept-anticheat-risk \
    --confirm-anticheat-risk 'I accept that my account may be banned'
```

The installation record keeps the detected anti-cheat names, the time and the package. Status and Check show the
accepted risk. Restore ends the override, and a new Install requires it again.

## Game reports

A report of a game on a BC-250, working or not, can become a community recipe and later a verified one. Paste the
`check --report` text into an issue with the **Game report** form ([Contributing](CONTRIBUTING.md#game-recipes)).
