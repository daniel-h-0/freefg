# Troubleshooting

Use a game's **Installation details** (`install.py status`) for installed files and the last session; use
**System Check** (`install.py doctor`) for host and HelixSR prerequisites. If a game update replaced a managed file,
the game's page says so under **Health**; follow the installation details' instructions. Use the new release’s
**Update All Games** for compatible installations. For an interrupted update, choose **Finish Update** or
**Undo Update…** on the game's page (`install.py update` or `rollback`). If Restore refuses a changed file, keep the backup and resolve
the reported conflict before reinstalling.

## Startup and provider checks

A successful launch does not establish upscaler operation or frame generation. Check the current session's logs:

- HLX DLSS must report `network running` in its `helixsr.log`. `NOT RUNNING` or a red-frame placeholder indicates failure.
- HLX FSR 4 must report `own runtime active` in `HLX_FSR.log`; selecting the provider does not rule out AMD fallback.
- `MFG_STATUS XeFG generates` in `BC250-MFG.log` reports generated frames from the SDK. Initialization alone is not enough.

<a id="cyberpunk-25-with-helixsr-stops-at-the-first-rendered-frames"></a>

For Cyberpunk 2.5, the scoped HLX recipe disables the reactive mask after an HDR fault with HLX FSR 4's default.
Its cause and the mask's image-quality effect remain unresolved; explicit user values are preserved.

## Logs

FreeFG's logs are beside the game's `.exe`. They do not show whether the picture or the pacing looked right, so
describe what you saw when you [report a problem](CONTRIBUTING.md#reporting-a-problem). Report HelixSR's own problems at
its [issues page](https://github.com/lonewolf0622/HelixSR/issues) with its `helixsr.log`.

| Log | Line | Meaning |
| --- | --- | --- |
| `BC250-MFG.log` | `MFG proxy ready` | Intel's runtime was found and verified. |
| | `bc250_xefg_original.dll is missing or is not the pinned Intel XeFG runtime` | The runtime is missing or altered. Check Status; Restore and reinstall if its checks permit. |
| | `FAST_COEXIST another module hooks Intel's XeFG runtime (…; jumps to MODULE)` | Another module hooks Intel's runtime. Supported network-layout mismatches can step aside; other integrity failures still stop the game. |
| | `FAST_SKIP … only OptiScaler's own contexts are accelerated` | Beside a hooking mod, the game's native context is not accelerated. OptiScaler's context can still be selected (`FAST_OWNER`). |
| | `MFG_FACTOR`, `MFG_STATUS` | Requested factor and SDK-reported presentation status; initialization alone does not prove generation. |
| | `FAST_OWNER` | FreeFG selected the context it accelerates. |
| | `FAST_FALLBACK …`, other `FAST_SKIP …` lines | Why Intel's shaders are used instead. |
| `BC250-XeFG-fast.log` | `MODEL_SEALED`, `PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed` (fixed text compiled into the DLL) | The accelerated path is active. |
| | `FAST_ASIDE …` | FreeFG stepped aside for the rest of that context, because another mod changed the runtime's work in a way it has not verified. |
| | `F4Q_CONFIG mode=… source=…` | F4Q mode and source. `layout` means the network layout is unsupported; `F4Q_FALLBACK` names a pipeline using its F(2×2) form. |
| | `F4Q2_CONFIG mode=… source=… layers=…` | F4Q2 mode, source and layer bitmask (7 means all three). `dropped_by_layout` names excluded layers; `source=F4Q` means F4Q disabled it. |
| | `FP16_CONFIG mode=… source=… forms=…` | Approximate forms: `on` by default, or `off` with the source. `forms=3` enables both groups. `FP16_REPLACE` names loaded forms; `FP16_FALLBACK` and `F4Q_FALLBACK` report fallback. Status/Check summarize them in `Output:`. |
| | `F4Q3_CONFIG mode=… layers=…` | F4Q3's state for the row layers `60edebbb` and `b3ddf030`: `on` by default and with the exact switch, `shadow` in the diagnostic, `off` with `source=F4Q` while F4Q is off. |
| | `FAIL` | FreeFG closed the game because the runtime did something it does not recognise. Report it. |
| The game's standard error (for Steam: launch option `PROTON_LOG=1 %command%`, then `$HOME/steam-<appid>.log`) | `BC250_PACE on …` | Pacing is active. |
| | `BC250_PACE holding: XeFG generates frames`, `BC250_PACE passing presents through` | The layer holds presents, or passes them through. |

## Problems

| Problem | What to try |
| --- | --- |
| Frame generation adds fewer frames than expected | See [below](#frame-generation-adds-little). |
| Only real frames are shown; the frame rate does not go up | Turn the game's frame generation on (DLSS FG and FSR FG inputs); make sure the game is not in exclusive fullscreen; check `BC250-MFG.log` and `BC250-XeFG-fast.log`. |
| Uneven pacing or VRR flicker | Give gamescope realtime priority ([Extras](INSTALLATION.md#uninstall-and-extras)); rule out Steam's screensaver (below); stay below the refresh rate; check the `BC250_PACE` lines. |
| Bursts of VRR flicker after some idle minutes, in long cutscenes or with a game left running | Check Steam's screensaver. On the tested client it rendered behind games and periodically consumed GPU time. Set its timeout to **Never** or use the `steam-screensaver-in-game` extra. |
| The first start after installing (or reinstalling) loads for longer | Setup normally creates a private vkd3d-proton cache; the first start fills it. See [shader-cache behavior](#shader-cache-behavior). |
| A game installed despite its anti-cheat does not start, or reports tampering | Restore the game; anti-cheat may be refusing the injected DLLs. See [anti-cheat risks](COMPATIBILITY.md#anti-cheat). |
| `Existing OptiScaler must be a supported pinned build …` | Restore or update the game's OptiScaler first. |
| `Cannot download …` | The first installation needs internet access, or the file already in `~/.cache/bc250-xefg-testers`. |
| `version.dll is occupied` or `An existing XeSSMFG folder …` | Another mod, or a test build of this project from before its public release, occupies those files; restore it with its own installer first. |
| Setup opens Zenity dialogs instead of its window, or its window misbehaves | The window needs PyGObject, GTK 4 and libadwaita 1.5 or newer (`python-gobject gtk4 libadwaita` on Arch-based systems); started from a terminal, Setup prints what is missing. `FREEFG_SETUP_UI=zenity ./Start-freefg.sh` chooses the dialogs. |
| System Check: `Pacing layer` WARN | The Vulkan loader cannot load FreeFG's layer: the system's glibc is older than the layer needs (2.34), or the line names the loader's reason. Presents are not paced and the layer's wave sizes are not applied; frame generation still runs. |
| Setup does not find HLX | Prepare HelixSR 3.1.0 once, select a matching prepared folder with `--helixsr`, or reuse a checked game-local provider. See [upscalers](CONFIGURATION.md#upscalers). |

## Shader-cache behavior

Setup normally uses `.bc250-xefg-experimental/vkd3d-cache`. Status shows its size; Restore deletes this private cache.
An explicit `VKD3D_SHADER_CACHE_PATH` (including `0`, which disables caching) is preserved. If the private path is too
long for vkd3d-proton, Setup leaves the game's cache settings in place and reports that exception.
[Why a new cache is used](MEASUREMENTS.md#shader-caches).

<a id="cyberpunk-25-resets-settings"></a>

[Earlier troubleshooting notes](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/TROUBLESHOOTING.md#cyberpunk-25-resets-settings)
are retained with the 1.1.6 record.

## Frame generation adds little

Status reports full, partial or skipped acceleration and the installed route/model. Interpret only the current
session's logs; a fast log can remain from an earlier run.

| Installation's input | `BC250-MFG.log` | `BC250-XeFG-fast.log` | Meaning | What to do |
| --- | --- | --- | --- | --- |
| any | `FAST_OWNER` | 13 lines that start with `REPLACE` | All 13 replacement programs are active. | If gains remain small, check the factor, frame caps and refresh limit. |
| OptiScaler | `FAST_OWNER` | 7 lines that start with `REPLACE` | MFG Unlocker's own model: FreeFG's shaders run on part of the network, at every frame count. | Set `XeFGModel=default` under `[XeFG]` in `OptiScaler.ini` ([Configuration](CONFIGURATION.md#3-and-4-with-mfg-unlocker)). |
| native XeSS FG (or the game's XeSS FG chosen in the game) | `FAST_SKIP beside another module …`, no `FAST_OWNER` or `CONTEXT_CALLER` | none or earlier | The game's own XeSS frame generation beside MFG Unlocker: FreeFG does not accelerate it. | Use OptiScaler's frame generation (install with an OptiScaler input), or remove MFG Unlocker for 2×. |
| any | `FAST_ASIDE …` | `FAST_ASIDE …` | FreeFG stepped aside during the session ([Logs](#logs)). | Use MFG Unlocker 1.6.0 with `XeFGModel=default`, or remove the other mod. |
| any other case | no `FAST_OWNER` | none or earlier | `BC250_XEFG_DISABLE=1`, or the reason in a `FAST_FALLBACK` or `FAST_SKIP` line ([Logs](#logs)). | Remove `BC250_XEFG_DISABLE` from the launch options, or act on that line. |

`BC250-XeFG-fast.log` is written only in a session with `FAST_OWNER`; "earlier" is a log left by an earlier session,
which **Status** names as such; **Status** reads only the logs beside the `.exe` written since the installation.
`F4Q_REPLACE` lines are not counted. Beside MFG Unlocker, `BC250-MFG.log` also
has `FAST_COEXIST` lines, and on an OptiScaler input a `FAST_SKIP` line for the game's own context, whatever the model.
**Status** shows the installation's input.

FreeFG defaults to full output size. To reduce generation cost, choose a scale or resolution limit in
[Settings](CONFIGURATION.md#generated-frame-scaling), then restart the game. Status reports actual dimensions: a request
alone does not prove scaling was active. `FREEFG_SCALE fallback:` explains an observed unsupported layout.

## Environment variables

For troubleshooting, as launch options before `%command%`. Setup keeps them on reinstall; Restore leaves them in place.

| Variable | Effect |
| --- | --- |
| `BC250_XEFG_DISABLE=1` | Intel's original shaders instead of the accelerated path. Presents are still held while XeFG generates. |
| `BC250_XELL_PACE=0` | Disable the bundled OptiScaler's adaptive 3×/4× game-frame correction for comparison. |
| `BC250_XEFG_FRAME_CAP=0` / `=1` | Override saved scaling with Match output / a 1080p bounding box. Leave unset to use Settings. |
| `BC250_XEFG_PACE=0` / `=1` | Output pacing off / hold every present, also while XeFG is not generating. |
| `BC250_XEFG_PACE_NUDGE=0` / `=1` | The X nudge for stock gamescope off / on. |
| `BC250_XEFG_PACE_QUEUE=app` | Present from the game's own queue even when a compute queue exists. |
| `BC250_XEFG_ANY_GPU=1` | The accelerated path on a GPU other than the BC-250 (untested; [below](#other-gpus)). |
| `BC250_XEFG_STATUS_POLL=0` | No status read per frame for the pacing signal; only the caller's own status queries count. |
| `BC250_XEFG_F4Q=0` | F4Q, F4Q2, F4Q3 and the FP16 forms off: the F(2×2) and 1D kernels of the U-Net layers run, as in 1.0.x ([ARCHITECTURE.md](ARCHITECTURE.md#f4q-rounding-and-tested-equivalence)). `F4Q=0` under `[BC250]` in `BC250-XeFG/settings.ini` does the same; `BC250_XEFG_F4Q=1` wins over the file. |
| `BC250_XEFG_EXACT=1` | Disable approximate FP16 forms. Tested images match Intel's; F4Q equivalence is not proven for all inputs ([ARCHITECTURE.md](ARCHITECTURE.md#fp16-forms-approximate-output-by-default)). `Exact=1` under `[BC250]` in `BC250-XeFG/settings.ini` does the same; `BC250_XEFG_EXACT=0` wins over the file. |
| `BC250_XEFG_F4Q2=0` | With F4Q on, disables F4Q2 for three encoder layers: they use F(2×2) kernels, as in 1.1.1, without their FP16 forms. F4Q2 is enabled by default. `F4Q2=0` under `[BC250]` in `BC250-XeFG/settings.ini` does the same; `BC250_XEFG_F4Q2=1` turns it on whatever that file says. |
| `BC250_XEFG_F4Q_SHADOW=1` | Diagnostic: the F4Q kernels (F4Q2's while it is on, and F4Q3's) run beside the F(2×2) and 1D ones, which keep the output, and `BC250-XeFG-fast.log` gets `F4Q_COUNT` lines with equal and differing outputs per layer. Costs GPU time; for checks and bug reports only. The FP16 forms are off while it runs. |
| `BC250_XEFG_SETTINGS=PATH` | Read and save the settings in that file instead of `BC250-XeFG/settings.ini` beside the game's `.exe` (a Windows path, or a Unix path that Wine maps). `BC250-MFG.log` names the file. |
| `BC250_CAPTURE_TAG_FRAMES=1` | For latency measurements: turns on the debug marker that Intel's XeFG API draws on generated frames, so capture tools can tell them apart. Leave unset for play. |

## Other GPUs

Everything is built and measured on the BC-250. On another GPU under Proton, Setup installs the same files, and:

- By default, FreeFG passes everything through to Intel's runtime (Intel's shaders, generated frames at output
  resolution). The pacing layer still holds presents while XeFG generates. `BC250-MFG.log` says
  `FAST_FALLBACK requires BC250 adapter (this one is vvvv:dddd; …)`.
- `BC250_XEFG_ANY_GPU=1` runs the accelerated path on that GPU. This override is unqualified. Runtime contract checks can stop the game with `FAIL`; they are not a
  visual-quality test. Performance on GPUs with native integer dot products may differ from the BC-250.
- The FSR 4 DLL is a BC-250 build, untested on other GPUs.
- Intel GPUs are not a target. Without another mod hooking Intel's runtime, FreeFG accelerates only 2× contexts.
