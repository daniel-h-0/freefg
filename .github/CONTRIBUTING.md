<!-- Copy of packaging/public/CONTRIBUTING.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/CONTRIBUTING.md instead. -->
# Contributing to FreeFG

Use [GitHub issues](https://github.com/daniel-h-0/freefg/issues) for bugs and game reports.
Send vulnerabilities and private rights-holder concerns through [SECURITY.md](../packaging/public/SECURITY.md).

## Reporting a problem

Include the game/store/version, FreeFG version, Proton/Mesa/kernel/gamescope versions, resolution, HDR/VRR state,
upscaler and FG input/factor. Describe what you saw and how to reproduce it.

Start with `python3 install.py check GAME.exe --report`. For runtime or pacing problems, also include relevant
`BC250-MFG.log`, `BC250-XeFG-fast.log` and `BC250_PACE` lines ([log guide](../packaging/public/TROUBLESHOOTING.md#logs)).
Review reports and logs before posting: raw logs can contain paths and user names. Do not attach game files, saves,
shader caches, runtime/GPU dumps or account data.

## Game recipes

A recipe supplies a game's input, settings and launch options. Submit working and failed cases through the
**Game report** issue form after testing the game.

### Reporting a game

Run `python3 install.py check '/path/to/Game.exe' --report` after play. Record gameplay duration, number of starts,
observed output/game-frame ratio and whether Restore worked. The redacted report helps, but cannot prove visual quality
or stable pacing by itself.

### Community and verified recipes

Community recipes live in `research/recipes/community/`, one JSON file per game. A maintainer reviews them before
Setup applies them as **Community-reported on BC-250**. Maintainer-tested recipes use the UI label **Verified on
BC-250**; the compatibility table records what was actually tested. Existing curated entries include partial checks
and known failures, so that label is not a blanket gameplay guarantee.

For a new working community recipe, provide at least 10 minutes of gameplay, three successful starts and a checked
Restore. At 2×, the observed ratio should be approximately 2.0; the validator's threshold is 1.95. Describe how you
measured it, test VRR behavior when available, and separate menu checks from gameplay. Maintainer verification should
include repeated starts, generated-frame confirmation and before/after file and launcher checks.

### What a recipe may set

The [community schema](../research/recipes/community/README.md) and `check_community()` in
`research/recipes/build_recipes.py` are the reference. They permit supported FG inputs, DX12 launch switches,
readable OptiScaler keys and specific game-setting edits. They reject installer-owned keys, unsupported FG outputs,
spoofing/Reflex/quality overrides and conflicts with OptiScaler's own game fix. Game FG inputs need an enabling setting
or a clear manual step.

A recipe must identify the game reliably and cite reports, not quote other sources. Failed inputs belong in
`known_problems`; review determines whether they should be excluded from automatic selection.

## Clean-room rules

1. **Do not contribute Intel runtime code or model data.** No captured DLL fragments, shader bytecode, weights,
   weight-derived constants, GPU-buffer dumps or generated copies of them. Public API headers are fetched during the
   build, not committed.
2. **Do not derive contributions from disassembly or decompilation.** Use written mathematical/input-output
   specifications, public API documentation, observable API behavior and this project's own source. Do not post
   prohibited material in issues or pull requests.
3. **State the specification and provenance.** Explain the operation, inputs, outputs and sources consulted. Where
   practical, separate specification and implementation authorship.
4. **Keep weights at runtime.** Kernels read coefficients from runtime buffers; no weights or weight-derived constants
   belong in source or shipped shaders.
5. **Compare outputs through the API.** Exact paths need byte comparisons. Approximate paths must be identified as
   approximate, include a way to disable them, and report image differences and quality-test limitations. Matching a
   test set does not prove equivalence for every input. Do not compare with Intel's shader code.
6. **Record every shader build.** Update the relevant `origin.json` with source, compiler/options, output hash and
   compile recipe; document the output tests in the pull request.
7. **Pass the content checks.** The assembled package must pass `release/check_intel_free.py check` with no allowance.

If a contribution may rely on prohibited material, ask about the proposed scope before submitting it; do not attach
or describe the material itself.

## Code changes

- Use `SPDX-License-Identifier: MIT` for new project code. Contributions to that code are under the project's MIT licence.
- Identify third-party code, its source/version and licence in NOTICE and provenance records; retain required notices.
- Keep private host paths, account identifiers and LAN addresses out of the public tree. Strict export checks host paths.
- Installer changes need appropriate tests, including Restore and preservation of user edits.
- Run [build and check](../packaging/public/BUILDING.md#build-and-check) before opening a pull request. A changed proxy or layer hash identifies
  a new binary: update its pin and report its tests. GPU qualification is currently limited to the BC-250.

## Conduct

Be specific and respectful. Harassment, personal attacks and disclosure of others' private information can result in
removal of contributions or a block.
