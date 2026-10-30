# Measurements

All measurements are from one AMD BC-250. Headless output FPS includes generated frames; it does not measure TV
presentation or input latency. Results from different games, versions, upscalers and settings are separate datasets.

The detailed [measurement record at the 1.1.6 release](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md)
retains the older tables, individual runs, methods and exclusions summarized below. Figure data and scripts are in
[`docs/data`](https://github.com/daniel-h-0/freefg/tree/5de9a40317ff07511c69c006bad22b36d3250f03/docs/data).

## Checks of 1.1.6

FreeFG's 97 runtime/profile payload files match 1.1.5. The integration uses OptiScaler fork `25db192b` (DLL
`5c7dd0f333e97f7e547a2f1873794e1ec9f59757623576cdedd6f9117577d617`) with HLX DLSS and HLX FSR 4 from the pinned
HelixSR 3.1.0 archive.

- 514 installer tests passed. The release-tool suite ran 124 tests, including three exclusions for private or
  obsolete builds absent from the public tree. Library rendering and selection passed on an isolated X server.
- Sixteen installed-game copies passed Update, exact Rollback, repeat Update and 1.1.5 Restore. Twelve release
  transitions covered 1.1.3.1, 1.1.4 and 1.1.5 on both integration routes with legacy HelixSR and AMD FSR 4.
- Eleven Cyberpunk 2.5 functional starts confirmed each HLX provider and generated presents: 2× SDR/HDR at 1440p,
  3× SDR at 4K with 1440p generation, and 4× HDR at 1440p. Higher factors used MFG Unlocker 1.6.0. The maximum
  sampled temperature was 85 °C.

Of 14 attempted starts, one early filename prototype produced a placeholder, one HLX FSR 4 HDR start faulted with
the default reactive mask, and one yielded to a separate preparation process. The filename was corrected. The scoped
mask-off recipe passed repeated HDR checks; the fault's cause and mask-on image equivalence are unresolved. These
checks do not establish all-game behavior, image quality, live-resize behavior, latency or new TV pacing.

## Scaling overhead in 1.1.5

28 October 2026. Cyberpunk 2.5, High/RT-off, SDR, HelixSR 2.0.0 Performance (1080p → 4K), 2×, generated at 1440p
with Area/FSR 1. Each build had one warm-up and four scored starts in balanced neighboring pairs; none was excluded.

| Build | Mean output FPS | 95% interval | Scored output FPS |
| --- | ---: | --- | --- |
| 1.1.4 | 75.934 | 75.724–76.143 | 75.766, 76.060, 75.893, 76.014 |
| 1.1.5 | 77.087 | 76.792–77.383 | 77.108, 76.887, 77.330, 77.025 |

Output increased **1.52%**; mean paired saving was **0.394 ms per generated frame** (95% interval 0.240–0.548 ms).
The calculation uses game-frame times and Student-t intervals across four pairs. It is headless throughput with pacing
off, not a GPU-duration or latency measurement.

All 13 Cyberpunk functional starts and 43 SDK starts passed. The SDK suite covered SDR/HDR, geometry and filter
variants, factor changes and resizing; 165 images matched 1.1.4 captures made with the same fixtures. Two attempted
Echo starts were cancelled at a Steam Cloud synchronization failure before startup. This campaign did not qualify
fresh Echo runtime, image quality or TV pacing.

## Generated-frame scaling in 1.1.4

27 October 2026. At 1440p output, Cyberpunk 2.5 with HelixSR Quality and 2× averaged 107.93 FPS at full generated
resolution and 110.50 FPS at 75% per axis (Area/FSR 1), a **2.38%** gain. Each condition had a warm-up and two
scored headless starts. Scaling changes generated pixels even in Exact mode.

Nine Cyberpunk functional starts passed. Echo passed a 2× menu start; its 3× run was interrupted by Steam account
use elsewhere, and 4× was not started. The SDK covered higher factors separately. These are limited integration
checks, not full-game or image-quality qualification.

### Scaling bounds and acceleration

Geometry tests covered 181,920 output/scale pairs. The 25 bounded convolution forms passed 150 poisoned-background
comparisons; 20 filter checks covered alpha and floating-point extremes. Thirty-one SDK checks covered tiny, odd,
portrait, ultrawide, 4K and 16,383-pixel-wide inputs, factor changes and resolution cycles. Twenty-five native Exact
images matched Intel controls. Unsupported observed layouts retain full output.

## Cyberpunk 2.5 with HelixSR

26 October 2026. FreeFG 1.1.3.1, Cyberpunk 2.5, High/RT-off, HelixSR 2.0.0 Quality (1706×960 → 2560×1440),
reactive mask off. The 3×/4× conditions use separately supplied MFG Unlocker 1.6.0 with `XeFGModel=default`.

![Output and game FPS for Intel and FreeFG at 2×, 3× and 4×, SDR and HDR10.](https://raw.githubusercontent.com/daniel-h-0/freefg/5de9a40317ff07511c69c006bad22b36d3250f03/docs/assets/cyberpunk-helixsr-fps.svg)

| Range | Mode | Game FPS | Output FPS | Output FPS, 95% CI | Added ms / generated frame |
| --- | --- | ---: | ---: | --- | ---: |
| SDR | No FG | 71.95 | 71.95 | 71.58–72.32 | — |
| SDR | Intel XeFG 2× | 43.17 | 86.34 | 86.09–86.59 | 9.27 |
| SDR | FreeFG 2× | 54.18 | 108.36 | 108.00–108.73 | 4.56 |
| SDR | Intel XeFG 3× | 31.30 | 93.89 | 93.82–93.96 | 9.03 |
| SDR | FreeFG 3× | 43.89 | 131.67 | 130.62–132.72 | 4.44 |
| SDR | Intel XeFG 4× | 24.49 | 97.95 | 97.63–98.26 | 8.98 |
| SDR | FreeFG 4× | 37.77 | 151.06 | 150.77–151.35 | 4.19 |
| HDR10 | No FG | 71.64 | 71.64 | 71.46–71.81 | — |
| HDR10 | Intel XeFG 2× | 42.46 | 84.92 | 84.74–85.09 | 9.59 |
| HDR10 | FreeFG 2× | 53.26 | 106.52 | 106.24–106.80 | 4.82 |
| HDR10 | Intel XeFG 3× | 30.57 | 91.72 | 91.53–91.92 | 9.37 |
| HDR10 | FreeFG 3× | 43.20 | 129.61 | 129.32–129.90 | 4.59 |
| HDR10 | Intel XeFG 4× | 23.84 | 95.36 | 95.29–95.43 | 9.33 |
| HDR10 | FreeFG 4× | 36.53 | 146.12 | 145.83–146.41 | 4.47 |

Against Intel at the same factor, output FPS increased **25.5% / 40.2% / 54.2%** in SDR and
**25.4% / 41.3% / 53.2%** in HDR10 at 2× / 3× / 4×. The `(unofficial)` chart labels mark the separate unlocker
needed for higher factors on this GPU. All 14 warm-ups and 56 scored starts passed; each condition has four scored
runs. Intervals are Student-t 95% intervals across run means. One interrupted preparation pilot was repeated before
the series; no scored run was excluded.

### Derived frame cost

For factor `m`, no-FG game FPS `G₀` and FG game FPS `Gₘ`:

```text
added ms per generated frame = (1000 / Gₘ − 1000 / G₀) / (m − 1)
```

This estimates added frame time from throughput, including interactions with game work. It is not isolated GPU time
or input latency. The table uses unrounded means; its intervals describe output FPS, not the derived cost.

### Method

Each condition used the same game, OptiScaler, upscaler and reactive-mask setting. Intel controls disabled FreeFG
shader replacements and wave overrides; no-FG controls disabled generation. Headless gamescope ran at 240 Hz with
pacing and frame caps off. Tests used GE-Proton11-11 and the BC-250 Mesa/RADV build. The mask-off workaround changes
an upscaler input, so mask-on visual equivalence is not established.

[Data and driver settings](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/docs/data/cyberpunk-helixsr/data.json) ·
[Figure script](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/docs/data/cyberpunk-helixsr/plot.py) ·
[Compact chart](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/docs/assets/cyberpunk-helixsr-fps-narrow.svg).
The 25 October 2× series is a [separate dataset](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/docs/data/cyberpunk-helixsr/2x-2026-10-25.json).

## Checks of 1.1.3.1

A wave-table bisection associated a wave32 selection with early GPU faults. The hotfix selects wave64 for that
shader without changing its bytes; the underlying cause remains unresolved. Nine SDK comparisons produced 144 images
identical to 1.1.3. Echo menu starts passed at 2×/3×/4×. [Detailed checks](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#checks-of-1131).

## Checks of 1.1.3

25 October 2026. CONTROL Resonant, physical 1440p120 HDR/VRR TV, GE-Proton11-11 and gamescope 3.16.30. Each timing
sample lasted 25–45 seconds; long intervals exceed 1.5× the sample median.

| Check | Before | Candidate |
| --- | --- | --- |
| 3× game starts, 5th–95th percentile | 16.2–34.7 ms | 24.0–26.9 ms |
| Uneven adjacent game-start pairs | 89.5% | 0% |
| 4× stationary, 99th-percentile display interval | 16.4 ms | 11.3 ms |
| 4× long flips | 69 in 33 s | 0 in 38 s |
| 2× long flips | 0 in 28 s | 0 in 33 s |

Camera motion and injected stalls still produced long intervals. End-to-end latency and library-wide pacing were
not measured. [Method and remaining stalls](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#checks-of-113).

## Scope

Results describe the named build, configuration and hardware. Small samples and excluded runs are recorded with
each campaign. Public source reproduces the binaries and CPU checks; SDK scenes and benchmark harnesses are separate
research tooling.

## Builds

| Component | Build | SHA-256 |
| --- | --- | --- |
| FreeFG proxy | 1.1.5 / 1.1.6 | `5665410389ec719d8d4f04a66231c77b61bfd19f08929a7a470fa5a383652b1f` |
| Pacing layer | 1.1.3 onward | `5de86d968c8adbfb42cf3d56bd020a0ba82e92ca31e9dcf4e319cbc479963687` |
| FreeFG proxy | 0.9.0 (2×) | `3bb43859ccff3a98786dd3c931e430523dbd05676f8d721515973ea73f935410` |
| Earlier pacing layer | 0.9.0–1.1.2 | `d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` |

[Earlier build identities and full table](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#builds).

## Test system

The October 26 chart used CachyOS, a BC-250 at up to 1850 MHz, kernel `7.3.0-2.326-cachyos-bc250`, Mesa/RADV
`3:26.2.5-1.331`, GE-Proton11-11 and gamescope 3.16.30. The 1.1.5 scaling comparison used kernel 7.3.0-4.341 and
Mesa 26.2.5-1.346. [Other campaign configurations](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#test-system).

## Checks of 1.1.2

In 20 synthetic configurations, **704 of 704** generated images in Exact mode matched Intel's. The default FP16
forms differed in **0.12–16.2% of pixels** across 19 configurations; the quality gate did not pass overall. Neither
result establishes perceptual equivalence in games. Constructed rounding-sensitive inputs also exposed F4Q-family
differences. [Test details and coverage](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#checks-of-112).

## Checks of 1.1.0

In 20 synthetic configurations, 704 images matched Intel with F4Q on and off. [Qualification and limitations](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#checks-of-110).

## Shader caches

Setup normally uses a private vkd3d cache and disables shader-module identifiers so the layer can see shader code
and apply wave choices. Explicit user cache paths are preserved; path-length limits can prevent the private cache
and wave override from taking effect. [Cache checks](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#shader-caches).

## Checks of 1.0.0

[Build, loader, synthetic output and installation checks](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#checks-of-100).

## Earlier comparisons

The original record keeps the full conditions, sample counts and exclusions for:

<a id="100-against-090-at-2-same-day"></a>
<a id="3-and-4-with-mfg-unlocker"></a>
<a id="earlier-series-100-both-models"></a>
<a id="start-up-exits-at-3"></a>
<a id="generated-images-bit-identical"></a>
<a id="frame-rate-cyberpunk-2077"></a>
<a id="4k"></a>
<a id="on-a-tv-with-vrr"></a>

- [1.0.0 against 0.9.0 at 2×](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#100-against-090-at-2-same-day).
- [Higher factors with MFG Unlocker](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#3-and-4-with-mfg-unlocker), including both models and three historical startup exits.
- [0.9.0 generated images](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#generated-images-bit-identical), with direct Intel and reference-only comparisons.
- [Earlier 1440p](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#frame-rate-cyberpunk-2077), [4K](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#4k) and [TV/VRR](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#on-a-tv-with-vrr) checks.

## GPU time per generated frame

[Historical 0.9.0 GPU stage timings](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#gpu-time-per-generated-frame) use different input sizes and days for Intel and FreeFG.

## Live install and Restore

[Earlier live install and Restore checks](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/MEASUREMENTS.md#live-install-and-restore) describe their tested releases. The [1.1.6 checks](#checks-of-116) cover in-place updates on copies.
