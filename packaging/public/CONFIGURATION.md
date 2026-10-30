# Configuration

Close the game before changing settings, then restart it. Settings affect generated frames; they do not raise the
game's simulation rate. The game page reports the installed route and last recorded session, not visual quality or
settings persistence.

## Upscalers

AMD FSR 4 is the default. **Change…** beside **Upscaler** on the game page also offers **HLX DLSS** and **HLX FSR 4**, from the separate
[HelixSR 3.1.0](https://github.com/lonewolf0622/HelixSR) project. FreeFG keeps AMD FSR 4 available separately and
uses FreeFG/XeFG for frame generation.

For HLX, open **Upscalers…** in the menu and select a prepared HelixSR 3.1.0 folder or choose **Prepare HLX**. Preparation verifies the official archive
and shader compilers, then runs its build-only entry point locally with networking disabled. It needs Wine,
bubblewrap, Python numpy, and these local model inputs: NVIDIA DLSS **310.7.0** and `amdxcffx64.dll` **2.4.0.4370**
from AMD Software **26.10.1**. Prepare once for all games; neither model input nor built model data is distributed by
FreeFG. [Preparation, downloads and terms](PRIVACY.md#helixsr-optional).

```sh
python3 install.py hlx --dlss-input /path/to/nvngx_dlss.dll --amd-input /path/to/amdxcffx64.dll
python3 install.py configure GAME.exe --upscaler hlx-dlss
python3 install.py configure GAME.exe --upscaler hlx-fsr4
python3 install.py configure GAME.exe --upscaler fsr4
```

Use `--helixsr /path/to/HelixSR-3.1.0` for a prepared folder elsewhere. Its complete provider files must match the
pinned build. `--upscaler helixsr` is an alias for HLX DLSS. A compatible update can advance legacy HelixSR 2.0.0
when the new provider is prepared. A current installation can reuse its own checked provider files without the cache.
A provider switch creates a rollback generation; **Rollback** undoes the latest switch or update.

## Generated-frame scaling

On the game page, choose **Generated Frame Size** and then **Apply**:

| Choice | Result |
| --- | --- |
| Match output | Generate at full output size (default). |
| Scale | 50–100% of output width and height; 75% of 2560×1440 is 1920×1080. |
| 720p / 1080p / 1440p / 2160p limit | Fit inside the selected 16:9 bounding box, preserving aspect ratio without enlarging. |

Reduced dimensions round down to even pixels, with a minimum of one. Match output, 100% and an output already within
the limit preserve odd dimensions. Real frames, game resolution, depth and motion-vector inputs stay unchanged.

**Downscale Filter** offers Bilinear and Area; **Upscale Filter** offers Bilinear, Bicubic, Lanczos2 and FSR 1 EASU without RCAS.
Bilinear is the default for both. These filters are separate from the game's upscaler and change generated-frame
detail, including in Exact mode.

```sh
python3 install.py configure GAME.exe --percent 75 --downscale area --upscale fsr1
python3 install.py configure GAME.exe --limit 1080
python3 install.py configure GAME.exe --resolution output
```

OptiScaler also exposes the choices under **Frame Generation → XeFG scaling**. Status reports actual dimensions from
the last session. An unsupported observed layout keeps full output. At 3×/4×, scaling requires MFG Unlocker's
`XeFGModel=default`. [Mechanism and evidence](ARCHITECTURE.md#generated-frame-scaling).

## 3× and 4× with MFG Unlocker

[MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker) is a separate tool that lifts Intel's non-Intel frame-count
limit; FreeFG does not ship or install it. Version 1.6.0 was tested. For full FreeFG acceleration and scaling with it,
use an **OptiScaler FG input** and **`XeFGModel=default`**; a game's native XeSS FG context is not accelerated while
the unlocker hooks Intel's runtime.

1. Install FreeFG with an OptiScaler input, verify 2×, then close the game.
2. Download `MFGUnlocker-v1.6.0.zip` and verify its `SHA256SUMS.txt`.
3. Rename `MFGUnlocker.dll` to `MFGUnlocker.asi` and put it in `OptiScaler/plugins/` beside the rendering `.exe`.
4. In `OptiScaler.ini`, set `[Plugins] LoadAsiPlugins=true` and `[XeFG] XeFGModel=default`. Fresh setups set these;
   existing explicit choices are preserved.
5. Select 3× or 4× in **Insert → Frame Generation**. OptiScaler's cap counts output frames, so 120 output FPS at 4×
   corresponds to about 30 game-rendered FPS.

With the unlocker's own model, only seven of 13 programs were replaced in the tested route; `default` retained all 13.
To remove it, delete its `.asi` and `RTXMFG-*` files, saving `RTXMFG-Universal.json` if wanted, and return to 2×.
Leave `LoadAsiPlugins` enabled for OptiPatcher. Restore does not remove third-party files it did not install.
[Mechanism](ARCHITECTURE.md#another-mod-on-intels-runtime) · [Measurements](MEASUREMENTS.md).
