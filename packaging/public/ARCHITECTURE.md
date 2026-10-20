# How FreeFG works

FreeFG has four parts that run with a game: a proxy DLL for Intel's XeFG runtime, a shader profile, a Vulkan
pacing layer, and the OptiScaler build that connects games to FSR 4 and XeFG. An installer puts them in place and takes
them out again. This page describes each part, then states exactly what FreeFG changes while Intel's runtime runs
and what it leaves alone.

```
game (DirectX 12, under Proton)
 ├─ OptiScaler (dxgi.dll proxy, GPL-3.0 build) ── FSR 4 DLL (upscaling)
 │      └─ loads .\libxess_fg.dll for frame generation   (native XeSS FG games load it themselves)
 ├─ libxess_fg.dll  = FreeFG's proxy
 │      ├─ 49 entry points forwarded by the Windows loader ──┐
 │      └─  8 entry points wrapped ───────────────────────────┴─> bc250_xefg_original.dll
 │             (scoped D3D12 objects, own shaders)               = Intel's XeFG runtime, unmodified
 ├─ BC250-XeFG/shaders/  (the shader profile: 33 own shaders + tables)
 └─ Vulkan: vkd3d-proton → libxefg_wave.so (pacing layer) → Mesa RADV → gamescope
```

## The proxy: `libxess_fg.dll`

Games with native XeSS frame generation, and OptiScaler when it uses XeFG as its frame generator, load a DLL named
`libxess_fg.dll` from the game folder. The installer puts FreeFG's DLL under that name. It puts Intel's runtime,
downloaded and checked by SHA-256 (see [PRIVACY.md](PRIVACY.md)), beside it as `bc250_xefg_original.dll`.

- **Exports.** The proxy exports the same 57 entry points as Intel's runtime 1.3.1.78, at the same ordinals. 49 of them
  are export forwarders: the Windows loader binds them straight to Intel's DLL, and FreeFG's code never sees those
  calls. 8 are implemented by the proxy: `xefgSwapChainD3D12CreateContext`, `xefgSwapChainD3D12InitFromSwapChain`,
  `xefgSwapChainD3D12InitFromSwapChainDesc`, `xefgSwapChainDestroy`, `xefgSwapChainGetLastPresentStatus`,
  `xefgSwapChainSetNumInterpolatedFrames` (the frame count, for retiring what the old count used),
  `xefgSwapChainD3D12GetSwapChainPtr` and `xefgSwapChainTagFrameConstants` (these two and the two before them run work
  deferred past an initialisation, below; the last also reads the status below once per frame). Each
  one does FreeFG's bookkeeping and calls Intel's function of the same name through Intel's export table. Four more
  exports after Intel's last ordinal are FreeFG's own: a small settings interface and an initialisation call. The
  build checks this table against Intel's DLL ordinal by ordinal.
- **Loading Intel's runtime.** On the first call, the proxy checks `bc250_xefg_original.dll` beside itself against the
  size and FNV-1a hash of the pinned file, then loads it by its absolute path. A missing or different file makes every
  wrapped entry return `XEFG_SWAPCHAIN_RESULT_ERROR_CANT_LOAD_LIBRARY`, so no XeFG context is created, and
  `BC250-MFG.log` says why.
- **No patching.** The proxy imports only `kernel32.dll` and `ucrtbase.dll`. It installs no function hooks, writes
  nothing into Intel's module, and does not touch the game's own Direct3D objects or their method tables.
- **Which contexts are accelerated.** Only on the BC-250 (PCI ID `1002:13fe`, or any GPU with `BC250_XEFG_ANY_GPU=1`),
  only when the shader profile beside the proxy matches the manifest built into it (size and hash of every file), and
  only the first XeFG context of the process. On its own, the proxy accelerates a context only when the runtime
  generates one frame per real frame, as the 2× build does (Intel's runtime allows more on its own only on Intel GPUs).
  Beside another mod that hooks Intel's runtime (below) it accelerates OptiScaler's own context at whatever frame count
  the runtime runs. Any other context runs entirely on Intel's shaders, and `BC250-MFG.log` or `BC250-XeFG-fast.log`
  says why (`FAST_FALLBACK`, `FAST_SKIP`).

### Another mod on Intel's runtime

A tool such as MFG Unlocker hooks Intel's runtime in memory: it patches the entry points of Intel's DLL and parts of
its code, and it may tell its callers apart by their return address (the game, OptiScaler, the runtime itself).
FreeFG patches nothing and reads nothing of such a module. It only notices it, and then changes its own behaviour:

- **Detection.** When the runtime loads, FreeFG reads the first 16 bytes of eight of Intel's entry points (seven it
  wraps and `xefgSwapChainGetProperties`) from `bc250_xefg_original.dll` on disk, from its own parse of the file's export table. At every
  context creation, initialisation and destruction it compares them with the bytes in memory (bytes that relocation
  changes are skipped), and checks that `GetProcAddress` still returns the export's own address. A difference is
  logged once in `BC250-MFG.log` (`FAST_COEXIST another module hooks Intel's XeFG runtime (entry: what changed; jumps
  to module)`).
- **Callers kept.** While another module hooks the runtime, the lifecycle entries (`xefgSwapChainD3D12CreateContext`,
  both `xefgSwapChainD3D12InitFromSwapChain` forms, `xefgSwapChainDestroy`), `xefgSwapChainD3D12GetSwapChainPtr` and
  `xefgSwapChainTagFrameConstants` tail-call Intel's entry: the hooking module sees the return address of whoever
  called the proxy (OptiScaler or the game), exactly as without the proxy. What FreeFG does after those calls
  without another mod moves to the next call that follows them. A context's initialisation (or its destruction, if it
  was never initialised) claims its scoped device: the creation whose output now holds the handle, or else the only
  pending creation on the device of the queue the initialisation gets. The first later call that carries the handle
  (`xefgSwapChainD3D12GetSwapChainPtr`, which callers make right after initialising, or the frame count, the status or
  the frame tag) finishes the initialisation (model census, network setup) before it reaches Intel, once Intel confirms
  the context is initialised (`xefgSwapChainD3D12GetInitializationParameters`). So the census holds what the
  initialisation allocated, and nothing a later frame-count change allocates, as without another mod. The next creation
  or initialisation releases a destroyed context's resources. `xefgSwapChainGetLastPresentStatus` and
  `xefgSwapChainSetNumInterpolatedFrames` take the context first and stay ordinary calls. The Wine loader check
  (`release/check_proxy_wine.py --variant intel-free-mfg`) tests the callers with a stand-in hook on eight entries.
- **OptiScaler's contexts only.** Beside another mod, FreeFG accelerates a context only when OptiScaler created it
  (the creating module's version resource names the product OptiScaler). A game's own XeFG context (the native route)
  keeps the game's own device. Such a mod may follow a game's own contexts and compare the device Intel gets with the
  device of the game's queue and swap chain; FreeFG's scoped device is a forwarding object and would never match, so
  frame generation would not start at all. That context runs Intel's or the other mod's shaders at every frame count,
  2× included.
- **Real objects where nothing is accelerated.** A context FreeFG does not accelerate (another GPU,
  `BC250_XEFG_DISABLE=1`, a second context, a game's own context beside another mod) gets the caller's own device and
  queue, as without the proxy.
- **Its own shaders where the work is still Intel's.** An accelerated context keeps the pipeline substitution below at
  every frame count, on every pipeline the runtime still creates from Intel's bytecode. A program the other module put
  in place of one of Intel's has another hash and stays as it is. Beside another mod, FreeFG creates Intel's
  original pipeline next to each one it replaces, so it can switch back.
- **Stepping aside instead of ending the game.** Beside another mod, the checks on the network's make-up (the set of
  coefficient buffers a reader needs, the initial census, network work arriving before setup) do not end the game.
  The context steps aside once: its scoped device, queue and command-list tables return to plain forwarding, every
  replaced pipeline is bound as Intel's original from then on, and the network, census and dispatch checks stop.
  `FAST_ASIDE` in both logs says why. FreeFG's resources stay alive until the context is destroyed, because work
  recorded earlier may still use them. The other checks (point 6 below) still end the game, beside another mod too.

### What happens inside an accelerated context

When the game creates an XeFG context, the proxy hands Intel's runtime **scoped** Direct3D 12 objects in place of the
game's device, command queue and command lists. These are thin forwarding objects: every call goes to the real
object. The forwarding lets FreeFG see the runtime's own GPU work: the pipelines it creates, the buffers it uploads
and the dispatches it records. The game keeps using its own, untouched objects. On the runtime's work, FreeFG does
the following (each is listed again under [What is changed at run time](#what-is-changed-at-run-time)):

1. **Pipeline substitution by hash.** When the runtime creates a compute pipeline, FreeFG hashes the runtime's shader
   bytecode. If the profile has a shader for that hash, the pipeline is created from FreeFG's shader instead, with
   the runtime's own root signature and pipeline description. 13 of the runtime's pipelines are replaced this way. All
   others are created from Intel's bytecode, unchanged.
2. **Kernel substitution for some convolutions.** For some of the network's convolution dispatches, FreeFG records
   its own kernels in place of the runtime's dispatch: 20 shaders (15 for the 2× network, 5 more for the multi-frame
   network) that compute the same convolution in the Winograd
   domain (transform, multiply, inverse transform) or as one fused refinement pass. They run in the same place in the
   runtime's command list, and the runtime's pipeline and bindings are restored afterwards.
3. **Coefficient layouts.** During initialisation the runtime uploads its network's coefficients (weights, biases,
   quantisation slopes) to GPU buffers. FreeFG gives those buffers their own allocations. From the same upload it
   computes pre-transformed copies for its kernels, and stores them after the original bytes. Intel's bytes stay at
   Intel's offsets, so Intel's own shaders read exactly what the runtime uploaded. The views FreeFG's kernels use
   are widened to cover the appended copies. All of this happens in memory, in every session. No coefficient is
   written to disk, and none is shipped.
4. **Root signature extension.** One of the runtime's root signatures gets two extra buffer bindings appended (scratch
   space for the Winograd kernels). Its first three parameters keep their positions and contents. Pipelines created on
   it, including Intel's, run with the extended signature; Intel's shaders do not declare the extra bindings.
5. **Dispatch sizes.** Some of FreeFG's replacement shaders cover more pixels per thread group than the shaders they
   replace. For those, the dispatch's group counts are divided accordingly (`dispatch-scale.txt`, 9 entries, each for a
   replaced shader).
6. **Checks that end the game.** FreeFG's kernels are written for the pinned runtime: its network sizes, buffer
   layouts and descriptor layouts, for its 2× network and its multi-frame network. Before acceleration starts, a
   mismatch means Intel's shaders are used. If the runtime later does something unexpected (another buffer write, a
   layout it does not know), FreeFG logs a `FAIL` line and ends the process. It does that rather than show frames it
   cannot vouch for. Beside another mod, the checks on the network's make-up step aside instead (above).
7. **Generation signal.** Every 20 ms the proxy writes a count to a small shared-memory page, which the pacing layer
   reads (below). The count advances with the accelerated passes and with the frames the runtime reports presented
   (`framesPresented` − 1 per present, from the caller's own status queries, or else one status query per frame), so
   it moves whenever XeFG generates, on Intel's shaders too.
8. **Frame-count changes.** When the frame count changes (`xefgSwapChainSetNumInterpolatedFrames`), the runtime
   rebuilds its pipelines and resources for the new count. FreeFG reuses identical pipelines and coefficient sets
   (pooled), and once the GPU has finished with the old count's work it stops tracking the command lists and descriptor
   heaps the runtime released.

Nothing above changes the number of frames the runtime generates, its API behaviour towards the game, or the bytes of
any of Intel's files.

Where the time goes: FreeFG's own shaders take over the reconstruction network and the large optical-flow layers,
the stages that cost Intel's shaders most on the BC-250. The warp, the smaller optical-flow passes, the splat and the
final compose stay Intel's ([MEASUREMENTS.md](MEASUREMENTS.md#gpu-time-per-generated-frame) gives the scope).

![GPU time per generated frame on the AMD BC-250, XeFG at 2×, output 2560×1440 SDR, from two runs with different inputs (Intel's shaders: replayed game inputs at 2560×1440, 27 September 2026; FreeFG: a synthetic scene with 1280×720 inputs, 18 October 2026). Intel's shaders: 9.76 ms. FreeFG: 4.50 ms, of which 2.93 ms are its own shaders and 1.57 ms Intel's. In the stages FreeFG replaces, 7.65 against 2.93 ms (−4.7 ms); the rest of the total gap (0.55 ms) comes from the different inputs. By stage, Intel's shaders against FreeFG: reconstruction network 5.12 against 1.93 ms (own shaders), optical-flow 224-channel layers 1.24 against 0.44 ms (own), optical-flow 64-channel refinement 1.29 against 0.56 ms (own), warp 0.82 against 0.82 ms (Intel's in both, another of Intel's warp variants in the reference run), other optical-flow passes 0.60 against 0.46 ms, motion splat and compose 0.69 against 0.29 ms (Intel's in both).](../../docs/assets/gpu-time-per-generated-frame.svg)

## The shader profile: `BC250-XeFG/shaders/`

42 files beside the proxy:

- **33 shaders** (DXIL, 31 of shader model 6.6 and 2 of shader model 6.9), compiled with Microsoft's DirectX Shader
  Compiler from this project's HLSL source: the 13 hash replacements, the 15 kernels described above, and 5 more
  kernels of the same kind for the multi-frame network's convolutions.
- **9 tables and markers:** `dispatch-scale.txt`, `waves.txt` and seven `*.required` files that switch on parts of the
  accelerated path.

The shaders contain no weights. They read the network's coefficients at run time from the buffers described in point 3.
They use exact arithmetic: int8 inputs and integer coefficients are accumulated in FP32 so that every partial sum is an
integer below 2^24, which FP32 represents exactly in any order. The results therefore equal the integer results of the
runtime's own shaders, and the generated images are bit-for-bit identical where this was tested (see
[MEASUREMENTS.md](MEASUREMENTS.md)). On the BC-250 this is faster than the int8 dot-product instructions that Intel's
shaders use, which the BC-250 (RDNA 1) does not have in hardware.

The proxy verifies every profile file against the manifest built into it and loads only the files that manifest
lists. A missing or modified file sends the context to Intel's shaders.

## The pacing layer: `libxefg_wave.so`

A Linux Vulkan layer that the launch environment enables (`VK_LAYER_PATH`, `VK_INSTANCE_LAYERS`). It runs in the game's
process, below vkd3d-proton, and does two things:

- **Even presentation under gamescope.** XeFG hands its generated and real frames to the swap chain back to back, but
  each one becomes ready wherever the game's next GPU work happens to put it, and a VRR display shows exactly that
  unevenness. The layer waits until each frame is rendered and releases it no sooner than 99% of the average frame
  interval after the previous one. It presents from a compute queue it reserves, where the driver has one, otherwise
  from the game's own queue under a lock. After a late frame it keeps a small margin (1 ms plus half the lateness, at
  most 5 ms, fading by 0.3 ms per second). Stock gamescope shows a frame that was already complete when it arrived only
  at its next refresh-timer tick. So after each paced present, the layer changes a property on the game's X display's
  root window seven times within 2.6 ms; each change wakes gamescope, which then shows the frame at once. The layer
  holds frames only while XeFG generates them: it reads the proxy's signal page in `/dev/shm`. A game's own FSR 3 frame
  generation, frame generation turned off, and menus pass straight through. With no signal page, or no answer from the
  proxy within 3 seconds, it holds every present. Outside gamescope it does not pace.
- **Wave size selection.** On the BC-250, the layer asks the driver to compile listed compute shaders with a required
  subgroup size of 32 or 64 (`waves.txt`, 123 entries, identified by shader hash). The list covers FreeFG's shaders
  and some of the runtime's unchanged shaders. The shader code is not changed.

The launch environment also adds vkd3d-proton's `no_staggered_submit` option.

## OptiScaler and FSR 4

OptiScaler connects a game's upscaler and frame-generation inputs (DLSS, FSR, XeSS, or its own OptiFG) to FSR 4
upscaling and to XeFG frame generation. The installer sets FSR 4 as the DirectX 12 upscaler, XeFG as the
frame-generation output, Intel's XeLL for latency, and `InterpolationCount=1` (2×; with MFG Unlocker the user raises it in
OptiScaler's menu, which saves it). It also keeps games borderless, because
XeFG does not interpolate in exclusive fullscreen. The bundled OptiScaler is upstream master of 19 October 2026 with
three commits on top. The one that matters fixes the lock order of an upstream change that can deadlock Streamline
games at start-up. The others are build fixes and automatic saving of menu changes. Its source and licence are in
[NOTICE.md](NOTICE.md). The FSR 4 DLL is a BC-250 build of AMD's FSR 4 (RC11, INT8) from the
bc250-fsr4-fork project, downloaded by hash.

**HelixSR instead of FSR 4.** [HelixSR](https://github.com/lonewolf0622/HelixSR), a separate project by lonewolf0622,
offers NVIDIA's DLSS Model E network through the same FidelityFX (FSR 3.1) upscaler interface; its own "FSR drop-in"
uses the file name `amd_fidelityfx_upscaler_dx12.dll`. OptiScaler loads its FidelityFX upscaler from that file name in
its folder (`Libraries.FfxDx12SRPath`, default `OptiScaler/`). It lists the versions the DLL reports, and
`FSR.UpscalerIndex=0` takes the first. So when you choose HelixSR, the installer puts the DLL HelixSR's own setup built
there instead of FSR 4's. Neither OptiScaler nor HelixSR is changed for this. Beside the DLL, `helixsr.ini` sets
`[DlssFrameGeneration] Enabled = false`, HelixSR's switch that keeps its own DLSS frame generation from loading. The
installer also never copies HelixSR's `helixsr-fg` folder, which that frame generation needs. Frame generation is XeFG's
either way. [NOTICE.md](NOTICE.md#helixsr) covers HelixSR's licence and what the installer does and does not do with
it.

## The installer

`install.py` (with the Zenity front end `setup.py`) prepares the downloads, saves every game file it will replace in
a backup folder in the game, places the files, and writes the launch environment into the game's entry in Steam,
Heroic or Lutris. That environment is `WINEDLLOVERRIDES` for OptiScaler's `dxgi.dll`, the layer variables, the wave
table and the vkd3d option. Per-game recipes add OptiScaler keys, the game's own frame-generation setting and a DX12
launch option. The upscaler DLL is FSR 4's or, on request, HelixSR's (`--upscaler`); `configure --upscaler` swaps it in
an installed game, as a pending update that Restore can finish or undo if it is interrupted. Restore reverses each
change and keeps anything the user or a game update changed since. The installer
refuses games it cannot handle cleanly: another proxy mod, a custom OptiScaler DLL path, an unknown OptiScaler build, or
a running game or launcher.

The same installer served the project's test builds from before the public release, which loaded a third-party
multi-frame enabler as `version.dll` with an `XeSSMFG` folder in the game. Its code still recognises such an
installation, so that it refuses to install over one, can restore one it made and keeps the settings it carried; this
package installs neither of them.

## What is changed at run time

Stated plainly, for anyone who needs to judge it:

| | Changed by FreeFG | Left alone |
| --- | --- | --- |
| Intel's DLL file | — | byte for byte as downloaded; verified by SHA-256 at install and by size and hash at load |
| Intel's code in memory | — | no hooks, no patches; every call enters through Intel's export table |
| The runtime's GPU pipelines | 13 created from FreeFG's shaders instead of the runtime's bytecode | all other pipelines, from Intel's bytecode |
| The runtime's command lists | some convolution dispatches carried out by FreeFG's 20 kernels; group counts of the 13 replaced shaders adjusted where their groups are larger | all other dispatches |
| The runtime's coefficient buffers | own allocations; pre-transformed copies appended after Intel's bytes | Intel's bytes at Intel's offsets |
| A root signature of the runtime | two buffer bindings appended | the original parameters |
| Shader compilation (Vulkan) | required wave size for 123 listed compute shaders (BC-250 only) | the shader code |
| Presentation | frames held until their turn (pacing layer) | which frames are generated and in what order |
| Number of generated frames | — | Intel's: one per real frame on GPUs other than Intel's; more only where another tool the user installed lifts that limit |
| Another mod's hooks on Intel's runtime | — | untouched; FreeFG only compares Intel's entry bytes with the file and passes the original caller through |

## Intel's licence and run-time changes

Intel distributes the XeFG runtime under the Intel Simplified Software License (October 2022). It permits use and
redistribution of the runtime "without modification". It also states: "No reverse engineering, decompilation, or
disassembly of the Software is permitted, nor any modification or alteration of the Software or its operation at any
time, including during execution." FreeFG does not modify Intel's file, and it does not ship it. But while the
runtime runs, FreeFG changes how part of the runtime's GPU work is carried out, as listed above. Whether that counts
as an "alteration of … its operation … during execution" under Intel's licence is a question this project cannot settle
for you, and Intel has not given this project permission. You are the licensee of the Intel runtime you download, and
Intel's terms apply to your use of it. A tool that lifts the runtime's frame limit changes the runtime itself; that is
the tool's change and your choice to add it, not FreeFG's. `BC250_XEFG_DISABLE=1` turns off the proxy's changes
(points 1–6 and 8 above; the signal of point 7 then counts only the runtime's own status); the
pacing layer and, on the BC-250, its wave-size table stay active. [NOTICE.md](NOTICE.md) has the licences of every
component.
