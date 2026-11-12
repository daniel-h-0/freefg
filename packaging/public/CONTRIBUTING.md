# Contributing to FreeFG

Use [GitHub issues](https://github.com/daniel-h-0/freefg/issues) for bugs and game reports. Vulnerabilities and private
concerns of rights holders go through [Security](SECURITY.md).

## Reporting a problem

Start with `python3 install.py check GAME.exe --report` and add:

- the game, its store and version, and the FreeFG version;
- the Proton, Mesa, kernel and gamescope versions;
- resolution, HDR and VRR state, upscaler, frame-generation input and factor;
- what you saw and how to reproduce it.

For runtime or pacing problems, include the relevant lines of `BC250-MFG.log` and `BC250-XeFG-fast.log` and the
`BC250_PACE` lines ([logs](TROUBLESHOOTING.md#logs)). Read reports and logs before posting: raw logs can contain
paths and user names. Do not attach game files, saves, shader caches, runtime or GPU dumps or account data.

## Game recipes

A recipe supplies a game's input, settings and launch options. Submit working and failed cases through the
**Game report** issue form after testing the game.

### Reporting a game

Run `python3 install.py check '/path/to/Game.exe' --report` after playing. Add how long you played, how many times
the game started, the ratio of output frames to game frames you observed and whether Restore worked. The report alone
cannot show image quality or steady pacing.

### Community and verified recipes

Community recipes live in `research/recipes/community/`, one JSON file per game. A maintainer reviews them before
Setup applies them as **Community-reported on BC-250**. Maintainer-tested recipes use the UI label **Verified on
BC-250**; the compatibility table records what was tested. Some verified entries rest on partial checks or list
known failures, so the label does not mean that all of a game was tested.

A new community recipe needs at least 10 minutes of gameplay, three successful starts and a checked Restore. At 2×
the observed ratio should be about 2.0; the validator's threshold is 1.95. Say how you measured it, test VRR where you
can and keep menu checks apart from gameplay. A maintainer's verification adds repeated starts, confirmation of
generated frames and file and launcher comparisons before and after.

### Allowed settings

The [community schema](https://github.com/daniel-h-0/freefg/blob/main/research/recipes/community/README.md) and `check_community()` in
`research/recipes/build_recipes.py` are the reference. They permit supported FG inputs, DX12 launch switches,
readable OptiScaler keys and specific game-setting edits. They reject installer-owned keys, unsupported FG outputs,
spoofing/Reflex/quality overrides and conflicts with OptiScaler's own game fix. Game FG inputs need an enabling setting
or a clear manual step.

A recipe must identify its game reliably and cite reports instead of quoting other sources. Record failed inputs in
`known_problems`. An entry with an `input` removes that input from the candidates detection proposes, as a wiki veto
does. A user's explicit choice and an applicable recipe route still take precedence, and installation is not blocked.

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

If a contribution may rely on prohibited material, ask about its scope before submitting it. Do not attach or
describe the material itself.

## Code changes

- Use `SPDX-License-Identifier: MIT` for new project code. Contributions to that code are under the project's MIT licence.
- Identify third-party code, its source/version and licence in NOTICE and provenance records; retain required notices.
- Keep private host paths, account identifiers and LAN addresses out of the public tree. Strict export checks host paths.
- Installer changes need appropriate tests, including Restore and preservation of user edits.
- Run [build and check](BUILDING.md#build-and-check) before opening a pull request. A changed proxy or layer hash identifies
  a new binary: update its pin and report its tests. GPU qualification is currently limited to the BC-250.

## Conduct

Be specific and respectful. Harassment, personal attacks and disclosure of others' private information can result in
removal of contributions or a block.
