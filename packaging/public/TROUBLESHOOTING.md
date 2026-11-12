# Troubleshooting

Start with Status, which is **Installation details** on a game's page or `install.py status`. It covers the
installed files and the last recorded session. **System Check** (`install.py doctor`) covers the host and the HLX
upscalers. Update a game that is on an earlier release first ([updates](INSTALLATION.md#updates-and-recovery)).

## Session checks

A game that starts does not prove that the upscaler runs or that frames are generated. Read the current session's
logs. Status prints the path of the upscaler's log.

| Component | Log | Line |
| --- | --- | --- |
| HLX DLSS Model E, HLX DLSS Preset K | `helixsr.log` beside its DLL | `network running`. `NOT RUNNING` or a red placeholder frame means failure. |
| HLX FSR 4 | `HLX_FSR.log` beside its DLL | `own runtime active`. |
| HLX FSR 4 Full | `hlx_fsr4.log` beside its DLL | An `own runtime:` line, then `frame` lines while it upscales. |
| Frame generation | `BC250-MFG.log` beside the `.exe` | `MFG_STATUS XeFG generates`: the SDK reports generated frames. Initialization alone is not enough. |

Selecting HLX FSR 4 or HLX FSR 4 Full does not rule out a fallback to AMD's FSR 4.

For Cyberpunk 2.5, the recipe disables the reactive mask with the HLX upscalers. HLX FSR 4's default caused a fault
in HDR. The cause and the mask's effect on image quality are unresolved. A value you set yourself is kept.

## Logs

FreeFG's logs are beside the game's `.exe`. They do not show whether the picture or the pacing looked right, so
describe what you saw when you [report a problem](CONTRIBUTING.md#reporting-a-problem). Report HelixSR's own problems
at its [issues page](https://github.com/lonewolf0622/HelixSR/issues) with the upscaler's log.

| Log | Line | Meaning |
| --- | --- | --- |
| `BC250-MFG.log` | `MFG proxy ready` | Intel's runtime was found and verified. |
| | `bc250_xefg_original.dll is missing or is not the pinned Intel XeFG runtime` | The runtime is missing or altered. Check Status. Restore and reinstall if its checks permit. |
| | `FAST_COEXIST another module hooks Intel's XeFG runtime (…; jumps to MODULE)` | Another module hooks Intel's runtime. FreeFG can step aside for supported network-layout mismatches. Other integrity failures still stop the game. |
| | `FAST_SKIP … only OptiScaler's own contexts are accelerated` | Beside a hooking mod, the game's native context is not accelerated. OptiScaler's context can still be selected (`FAST_OWNER`). |
| | `MFG_FACTOR`, `MFG_STATUS` | The requested factor and the presentation status that the SDK reports. Initialization alone does not prove generation. |
| | `FAST_DECISION candidate: …`, `FAST_DECISION not accelerated: …` | One line per context that reaches FreeFG's check: whether it can be accelerated, or why not. The reasons are `BC250_XEFG_DISABLE=1`, another context already accelerated, another GPU, a profile file missing or altered, and a fast log that is not writable. |
| | `FAST_OWNER` | FreeFG selected the context it accelerates. |
| | `FAST_FALLBACK …`, other `FAST_SKIP …` lines | Why Intel's shaders are used instead. |
| `BC250-XeFG-fast.log` | `MODEL_SEALED`, `PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed` (fixed text compiled into the DLL) | The accelerated path is active. |
| | `FAST_ASIDE …` | FreeFG stepped aside for the rest of that context, and Intel's shaders run from then on. Either another mod changed the runtime's work in a way FreeFG has not verified, or the runtime's model census at the context's set-up was not one FreeFG verified (`FAST_ASIDE …: this context now runs Intel's shaders`, no other mod). Report the second case with the logs. |
| | `F4Q_CONFIG mode=… source=…` | F4Q's mode and source. `layout` means that the network layout is unsupported. `F4Q_FALLBACK` names a pipeline that uses its F(2×2) form. |
| | `F4Q2_CONFIG mode=… source=… layers=…` | F4Q2's mode, source and layer bitmask (7 means all three). `dropped_by_layout` names excluded layers. `source=F4Q` means that F4Q disabled it. |
| | `FP16_CONFIG mode=… source=… forms=…` | The approximate forms: `on` by default, or `off` with the source. `forms=3` enables both groups. `FP16_REPLACE` names loaded forms. `FP16_FALLBACK` and `F4Q_FALLBACK` report a fallback. Status and Check summarise them in `Output:`. |
| | `F4Q3_CONFIG mode=… layers=…` | F4Q3's state for the row layers `60edebbb` and `b3ddf030`: `on` by default and with the exact switch, `shadow` in the diagnostic, `off` with `source=F4Q` while F4Q is off. |
| | `FAIL` | FreeFG closed the game because the runtime did something it does not recognise. Report it. |
| The game's standard error | `BC250_PACE on …`, `BC250_PACE off (…)` | The layer can pace this process (a Wine game under gamescope), or why not. |
| | `BC250_PACE the BC250 add-on answered …` | Presents go through the pacer from here. Before it they go straight to the driver. |
| | `BC250_PACE holding: XeFG generates frames`, `BC250_PACE passing presents through` | The layer holds presents, or passes them through. |
| `OptiScaler.log` | `… inactive in GAME.exe: the command line has no -nobattleye ([BC250] RequireArgument) …` | OptiScaler stays a plain proxy in that process, without hooks or frame generation. The launch options lack the argument that the game's recipe requires. |

For a Steam game, the launch option `PROTON_LOG=1 %command%` writes the standard error to `$HOME/steam-<appid>.log`.
OptiScaler writes `OptiScaler.log` with `LogToFile=true` under `[Log]` in `OptiScaler.ini`.

## Problems

| Problem | What to try |
| --- | --- |
| Frame generation adds fewer frames than expected | See [Partial acceleration](#partial-acceleration). |
| Only real frames are shown and the frame rate does not go up | Turn on the game's frame generation (DLSS FG and FSR FG inputs). Leave exclusive fullscreen. Check `BC250-MFG.log` and `BC250-XeFG-fast.log`. |
| Uneven pacing or VRR flicker | Grant gamescope scheduling priority ([extras](INSTALLATION.md#uninstall-and-extras)). Rule out Steam's screensaver (next row). Stay below the display's refresh rate. Check the `BC250_PACE` lines. |
| Bursts of VRR flicker after some idle minutes, in long cutscenes or with a game left running | Check Steam's screensaver. On the tested client it rendered behind games and periodically took GPU time. Set its timeout to **Never** or use the `steam-screensaver-in-game` extra. |
| The first start after an install loads for longer | Setup normally creates a private vkd3d-proton cache, and the first start fills it. See [Shader cache](#shader-cache). |
| A game installed despite its anti-cheat does not start, or reports tampering | Restore the game. The anti-cheat may be refusing the injected DLLs ([anti-cheat](COMPATIBILITY.md#anti-cheat)). |
| **Program files** under **Health** names changed files | A game update or another tool replaced managed files. Restore, then install again. |
| An update was interrupted | Choose **Finish Update** or **Undo Update…** on the game's page (`install.py update` or `install.py rollback`). |
| Restore kept or left a file | Restore keeps a file that changed after installation. The earlier version stays in the backups. A file whose backup is damaged also stays: put it back with your launcher's Verify or Repair before you install again. |
| `Existing OptiScaler must be a supported pinned build …` | Restore or update the game's OptiScaler first. |
| `Cannot download …` | The first installation needs internet access, or the file already in `~/.cache/bc250-xefg-testers`. |
| `An existing XeSSMFG folder …` | Another mod, or a test build of this project from before its public release, has that folder. Restore it with its own installer first. |
| Setup opens Zenity dialogs instead of its window, or its window misbehaves | The window needs PyGObject, GTK 4 and libadwaita 1.5 or newer (`python-gobject gtk4 libadwaita` on Arch-based systems). Started from a terminal, Setup prints what is missing. `FREEFG_SETUP_UI=zenity ./Start-freefg.sh` selects the dialogs. |
| **System Check** warns about `Pacing layer` | The Vulkan loader cannot load FreeFG's layer. Either the system's glibc is older than 2.34, or the line names the loader's reason. Presents are not paced and the layer's wave sizes are not applied. Frame generation still runs. |
| Setup does not find an HLX upscaler | Download or prepare HelixSR 3.3.0 once (**Upscalers…**), select a matching prepared folder with `--helixsr`, or reuse the checked files that a game already has ([upscalers](CONFIGURATION.md#upscalers)). |

## Shader cache

Setup normally gives the game a private vkd3d-proton cache in `.bc250-xefg-experimental/vkd3d-cache`. Status shows
its size, and Restore deletes it. Setup keeps a `VKD3D_SHADER_CACHE_PATH` that you set, including `0`, which disables
caching. If the private path is too long for vkd3d-proton, Setup leaves the game's cache settings in place and says
so. [Why a new cache is used](MEASUREMENTS.md#shader-caches).

## Partial acceleration

Status reports full, partial or skipped acceleration and the installed input and model. Read only the current
session's logs: a fast log can remain from an earlier run.

| Installation's input | `BC250-MFG.log` | `BC250-XeFG-fast.log` | Meaning | What to do |
| --- | --- | --- | --- | --- |
| any | `FAST_OWNER` | 13 lines that start with `REPLACE` | All 13 replacement programs are active. | If gains remain small, check the factor, frame caps and refresh limit. |
| OptiScaler | `FAST_OWNER` | 7 lines that start with `REPLACE` | MFG Unlocker's own model: FreeFG's shaders run on part of the network, at every frame count. | Set `XeFGModel=default` under `[XeFG]` in `OptiScaler.ini` ([Configuration](CONFIGURATION.md#3-and-4-with-mfg-unlocker)). |
| native XeSS FG (or the game's XeSS FG chosen in the game) | `FAST_SKIP beside another module …`, no `FAST_OWNER` or `CONTEXT_CALLER` | none or earlier | The game's own XeSS frame generation beside MFG Unlocker: FreeFG does not accelerate it. | Use OptiScaler's frame generation (install with an OptiScaler input), or remove MFG Unlocker for 2×. |
| any | `FAST_ASIDE …` | `FAST_ASIDE …` | FreeFG stepped aside during the session ([Logs](#logs)). | Use MFG Unlocker 1.6.0 with `XeFGModel=default`, or remove the other mod. |
| any other case | no `FAST_OWNER` | none or earlier | `BC250_XEFG_DISABLE=1`, or the reason in a `FAST_DECISION`, `FAST_FALLBACK` or `FAST_SKIP` line ([Logs](#logs)). | Remove `BC250_XEFG_DISABLE` from the launch options, or act on that line. |

- `BC250-XeFG-fast.log` is written only in a session with `FAST_OWNER`. "Earlier" is a log left by an earlier
  session, which Status names as such.
- Status reads only the logs beside the `.exe` that were written since the installation. It also shows the
  installation's input.
- `F4Q_REPLACE` lines are not counted.
- Beside MFG Unlocker, `BC250-MFG.log` also has `FAST_COEXIST` lines. On an OptiScaler input it has a `FAST_SKIP`
  line for the game's own context, whatever the model.

FreeFG generates at full output size by default. To reduce the cost, choose a scale or a resolution limit
([scaling](CONFIGURATION.md#generated-frame-scaling)), then restart the game. Status reports the actual dimensions: a
request alone does not prove that scaling was active. A `FREEFG_SCALE fallback:` line explains a layout that FreeFG
does not support.

## Environment variables

Set these for troubleshooting, as launch options before `%command%`. Setup keeps them on reinstall, and Restore
leaves them in place.

| Variable | Effect |
| --- | --- |
| `BC250_XEFG_DISABLE=1` | Intel's original shaders instead of the accelerated path. Presents are still held while XeFG generates. |
| `BC250_XELL_PACE=0` | The bundled OptiScaler's adaptive 3×/4× game-frame correction off, for comparison. |
| `BC250_XEFG_FRAME_CAP=0` / `=1` | Match output / a 1080p bounding box instead of the saved scaling. Leave it unset to use Settings. |
| `BC250_XEFG_PACE=0` / `=1` | Output pacing off / hold every present, also while XeFG is not generating. |
| `BC250_XEFG_PACE_NUDGE=0` / `=1` | The X nudge for stock gamescope off / on. |
| `BC250_XEFG_PACE_QUEUE=app` | Presents from the game's own queue even when a compute queue exists. |
| `BC250_XEFG_ANY_GPU=1` | The accelerated path on a GPU other than the BC-250. Untested ([Other GPUs](#other-gpus)). |
| `BC250_XEFG_STATUS_POLL=0` | No status read per frame for the pacing signal. Only the caller's own status queries count. |
| `BC250_XEFG_F4Q=0` | F4Q, F4Q2, F4Q3 and the FP16 forms off: the F(2×2) and 1D kernels of the U-Net layers run, as in 1.0.x ([Architecture](ARCHITECTURE.md#f4q)). `F4Q=0` under `[BC250]` in `BC250-XeFG/settings.ini` does the same. `BC250_XEFG_F4Q=1` wins over the file. |
| `BC250_XEFG_EXACT=1` | The approximate FP16 forms off. Tested images match Intel's. F4Q's equivalence is not proven for all inputs ([Architecture](ARCHITECTURE.md#fp16-forms)). `Exact=1` under `[BC250]` in `BC250-XeFG/settings.ini` does the same. `BC250_XEFG_EXACT=0` wins over the file. |
| `BC250_XEFG_F4Q2=0` | With F4Q on, F4Q2 off for three encoder layers: they use F(2×2) kernels, as in 1.1.1, without their FP16 forms. F4Q2 is on by default. `F4Q2=0` under `[BC250]` in `BC250-XeFG/settings.ini` does the same. `BC250_XEFG_F4Q2=1` turns it on whatever that file says. |
| `BC250_XEFG_F4Q_SHADOW=1` | Diagnostic. The F4Q kernels (F4Q2's while it is on, and F4Q3's) run beside the F(2×2) and 1D ones, which keep the output. `BC250-XeFG-fast.log` gets `F4Q_COUNT` lines with equal and differing outputs per layer. It costs GPU time and turns the FP16 forms off. Use it for checks and bug reports only. |
| `BC250_XEFG_SETTINGS=PATH` | The settings are read from and saved in that file instead of `BC250-XeFG/settings.ini` beside the game's `.exe`. PATH is a Windows path, or a Unix path that Wine maps. `BC250-MFG.log` names the file. |
| `BC250_CAPTURE_TAG_FRAMES=1` | For latency measurements: the debug marker that Intel's XeFG API draws on generated frames, so capture tools can tell them apart. Leave it unset for play. |

## Other GPUs

FreeFG is built and measured on the BC-250. On another GPU under Proton, Setup installs the same files.

- By default, FreeFG passes everything through to Intel's runtime: Intel's shaders, and generated frames at output
  resolution. The pacing layer still holds presents while XeFG generates. `BC250-MFG.log` says
  `FAST_FALLBACK requires BC250 adapter (this one is vvvv:dddd; …)`.
- `BC250_XEFG_ANY_GPU=1` runs the accelerated path on that GPU. This override is unqualified. Runtime contract checks
  can stop the game with `FAIL`. They do not test visual quality. Performance on GPUs with native integer dot
  products may differ from the BC-250.
- The FSR 4 DLL is a BC-250 build, untested on other GPUs.
- Intel GPUs are not a target. Without another mod that hooks Intel's runtime, FreeFG accelerates only 2× contexts.

[Earlier troubleshooting notes](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/TROUBLESHOOTING.md#cyberpunk-25-resets-settings)
are retained with the 1.1.6 record.
