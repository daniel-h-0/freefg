# Configuration

Close the game before you change a setting. The change applies when the game starts again. A game's page shows the
installed input and the last recorded session. It does not show visual quality or whether settings persisted.

## Upscalers

Each game uses one upscaler. Frame generation is XeFG with each of them.

| Upscaler | `--upscaler` | What it is | Before first use |
| --- | --- | --- | --- |
| **HLX DLSS Model E** (suggested) | `hlx-dlss` | The DLSS Model E network as compute shaders. | Built once on your computer. |
| **HLX DLSS Preset K** | `hlx-dlss-k` | The DLSS 4 Preset K network. Sharper than Model E and a little slower. | An optional second build that takes many minutes. |
| **HLX FSR 4** | `hlx-fsr4` | HelixSR's fast FSR 4-class upscaler. | HelixSR's download. |
| **HLX FSR 4 Full** | `hlx-fsr4-full` | The full FSR 4.1.2 network on HelixSR's kernels. Sharper and slower than HLX FSR 4. | HelixSR's download. |
| **FSR 4** | `fsr4` | AMD FSR 4, BC-250 build. | Nothing. |

The four HLX upscalers belong to [HelixSR 3.3.0](https://github.com/lonewolf0622/HelixSR), a separate project by
lonewolf0622. A new installation takes HLX DLSS Model E when it is prepared on your computer and AMD FSR 4 otherwise
(`--upscaler auto`, the default). AMD FSR 4 stays installed beside an HLX upscaler.

### Preparation

**Upscalers…** in the menu makes the HLX upscalers ready once, for every game.

| Button | Result |
| --- | --- |
| **Download…** | Fetches and checks HelixSR's official archive (about 280 MB). HLX FSR 4 and HLX FSR 4 Full come built in it. |
| **Prepare…** | Also builds HLX DLSS Model E from NVIDIA's DLSS 310.7.0 DLL. The build runs on your computer with networking disabled and needs Wine, bubblewrap and Python numpy. **Also build HLX DLSS Preset K** in that dialog adds Preset K. |
| **Choose…** | Takes a HelixSR 3.3.0 release folder that is already prepared (`--helixsr /path/to/HelixSR-3.3.0`). An upscaler's files must all match the pinned build. |

The build takes NVIDIA's DLL from your computer: a copy you select, or the one FreeFG downloaded earlier as its DLSS
input helper. Without a copy, Setup asks before it downloads the DLL from NVIDIA's repository. FreeFG distributes
neither the DLL nor built model data. [Downloads and terms](PRIVACY.md#helixsr-optional).

```sh
python3 install.py hlx                           # download HelixSR and build Model E from a local DLSS DLL
python3 install.py hlx --dlss-input /path/to/nvngx_dlss.dll
python3 install.py hlx --download-dlss           # agree to the download of NVIDIA's DLL when none is local
python3 install.py hlx --preset-k                # also build Preset K
python3 install.py hlx --no-build                # only the download: HLX FSR 4 and HLX FSR 4 Full
```

### Switching

On the game's page, choose **Change…** beside **Upscaler**, pick an upscaler and choose **Switch**. **Roll Back…**
undoes the latest switch or update.

```sh
python3 install.py configure GAME.exe --upscaler hlx-dlss
python3 install.py configure GAME.exe --upscaler fsr4
```

- `--upscaler helixsr` is an alias of `hlx-dlss`.
- An update moves an earlier HLX or HelixSR 2.0.0 installation to 3.3.0 once that upscaler is prepared. Until then
  the installation stays as it is.
- A game that already holds an upscaler's current files can use them without the preparation cache.

### DeepReuse

HLX DLSS Preset K and HLX FSR 4 Full each read a `DeepReuse` setting (`exact`, `1:2` or `1:4`) from a file of their
own in the game folder:

| Upscaler | File |
| --- | --- |
| HLX DLSS Preset K | `OptiScaler/custom/hlx-dlss-k/dlss/helixsr.ini` |
| HLX FSR 4 Full | `OptiScaler/custom/hlx-fsr4-full/ffx/hlx_fsr4.ini` |

FreeFG installs HelixSR's files with HelixSR's default, `exact`, and keeps your edits across updates and switches.
HelixSR's release notes list the known issues of the faster settings.

## Generated-frame scaling

On the game's page, choose a **Generated-frame size** and then **Apply**.

| Choice | Result |
| --- | --- |
| **Match output** | Generate at full output size (default). |
| **Scale** | 50–100% of the output's width and height. 75% of 2560×1440 is 1920×1080. |
| **720p limit**, **1080p limit**, **1440p limit**, **2160p limit** | Fit inside that 16:9 bounding box. The aspect ratio is kept and nothing is enlarged. |

Reduced dimensions round down to even pixels, with a minimum of one. Match output, 100% and an output already within
the limit keep odd dimensions. Real frames, the game's resolution and the depth and motion-vector inputs stay
unchanged.

| Filter | Choices |
| --- | --- |
| **Downscale filter** | **Bilinear** (default), **Area** |
| **Upscale filter** | **Bilinear** (default), **Bicubic**, **Lanczos2**, **FSR1 (EASU)**, which is FSR 1's EASU pass without RCAS |

The filters are separate from the game's upscaler. They change the detail of generated frames, also in Exact mode.

```sh
python3 install.py configure GAME.exe --percent 75 --downscale area --upscale fsr1
python3 install.py configure GAME.exe --limit 1080
python3 install.py configure GAME.exe --resolution output
```

OptiScaler's menu has the same choices under **Frame Generation → XeFG scaling**. Status reports the actual dimensions
of the last session. A layout that FreeFG does not support keeps full output. At 3× and 4×, scaling requires MFG
Unlocker's `XeFGModel=default`. [Mechanism and evidence](ARCHITECTURE.md#generated-frame-scaling).

## 3× and 4× with MFG Unlocker

[MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker) is a separate tool that lifts Intel's frame-count limit on
non-Intel GPUs. FreeFG does not ship or install it. Version 1.6.0 was tested.

For full acceleration and scaling beside it, use an **OptiScaler input** and **`XeFGModel=default`**. While the
unlocker hooks Intel's runtime, a game's native XeSS FG context is not accelerated.

1. Install FreeFG with an OptiScaler input, verify 2×, then close the game.
2. Download `MFGUnlocker-v1.6.0.zip` and verify its `SHA256SUMS.txt`.
3. Rename `MFGUnlocker.dll` to `MFGUnlocker.asi` and put it in `OptiScaler/plugins/` beside the rendering `.exe`.
4. In `OptiScaler.ini`, set `[Plugins] LoadAsiPlugins=true` and `[XeFG] XeFGModel=default`. A fresh setup has both
   already, and Setup keeps a value you set yourself.
5. In the game, press Insert and select 3× or 4× under **Frame Generation**. OptiScaler's cap counts output frames:
   120 output FPS at 4× is about 30 game-rendered FPS.

With the unlocker's own model, FreeFG replaced only seven of 13 programs in the tested route. `default` kept all 13.

To remove it, delete its `.asi` and its `RTXMFG-*` files and return to 2×. Save `RTXMFG-Universal.json` first if you
want it. Leave `LoadAsiPlugins` enabled for OptiPatcher. Restore does not remove third-party files that FreeFG did
not install. [Mechanism](ARCHITECTURE.md#another-mod-on-intels-runtime) · [Measurements](MEASUREMENTS.md).

## Wiki settings

The OptiScaler wiki suggests OptiScaler settings for some games. You review them before any is written.

1. On an installed game's page, choose **Review…** beside **Wiki settings**. Setup reads the bundled OptiScaler wiki
   catalogue and the game's current INI.
2. Read the wiki's requirements and caveats, which come first. Then select the settings you want. Each shows its
   value, the current value, its source page, the pinned wiki revision, the reported test context and its conditions.
3. Where a suggestion rests on a title-only match or an unknown condition, confirm the displayed facts.
4. Choose **Apply Selected**. The button shows the number of settings you selected.

Setup checks that the plan and the current values still match, then writes only the selected `OptiScaler.ini` keys.
The installed release and runtime stay in place. **Roll Back…** undoes the last applied selection. Restore handles
original values and later edits as usual.

You cannot select a setting that a recipe or runtime fix already handles, an unsupported key or a setting known not
to apply. A value that is already set needs no change. Wiki suggestions are community reports. They are not tested
per game on your hardware.

In the Zenity dialogs, **Wiki settings** lists the same suggestions as a checklist for one selected game and asks you
to confirm their conditions. On the command line:

```sh
python3 install.py wiki-plan GAME.exe
python3 install.py wiki-apply GAME.exe --wiki-plan-digest DIGEST --wiki-setting ROW_ID
```

Take the digest and the row IDs from the current JSON plan. Add `--wiki-confirm ROW_ID` only for a selected row whose
identity and conditions you have checked. A stale plan is refused: review it again.
