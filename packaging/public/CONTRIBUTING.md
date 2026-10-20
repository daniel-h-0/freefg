# Contributing to FreeFG

Thank you for helping. Bug reports with logs are the most useful contribution. Code changes are welcome too, as long
as they follow the rules below. The clean-room rules are not optional: they are what lets this project ship its own
code next to Intel's runtime.

## Reporting problems

Open an issue at <https://github.com/daniel-h-0/freefg/issues> with:

- the game (store and version), your Proton, Mesa, kernel and gamescope versions, and whether it ran in Steam Game Mode
  (for a game that does or does not work at all, the Check report is enough: see [Game recipes](#game-recipes));
- resolution, HDR on or off, the upscaler mode, the frame-generation input, and what you saw;
- `BC250-MFG.log` and `BC250-XeFG-fast.log` from the game folder, the output of `python3 install.py doctor`, and, for
  pacing problems, the `BC250_PACE` lines from the game's standard error (launch option `PROTON_LOG=1 %command%`).

Check the logs before you post them: they contain the game's path, which can include your user name. Never attach
game files, saves, shader caches, captures of Intel's runtime, or anything from your Steam or launcher accounts.

## Game recipes

A report of a game on a BC-250, working or not, can become a recipe that Setup applies for everyone. Run
`python3 install.py check '/path/to/Game.exe' --report` (or Setup's **Check**) after playing, and paste its text into an
issue with the game report form. The text holds no paths or user name; check it before you post anyway.

A community recipe (one JSON file in the source repository's `research/recipes/community/`; its fields and rules are
in that folder's `README.md`) is built into Setup as **Community-reported on BC-250** once a maintainer has reviewed it. A maintainer who reproduces it on the maintainers' BC-250 makes it a verified
recipe. The checklist:

| Step | Community recipe | Verified recipe |
| --- | --- | --- |
| Hardware | a BC-250 | a BC-250 run by a maintainer |
| Install | Setup from an unmodified game folder; the Check report attached | the same, on the maintainers' library |
| Generation | 2.0 presents per game frame (the OptiScaler overlay or the logs) over at least 10 minutes of gameplay, not a menu | measured with the project's tools over gameplay |
| Stability | 3 starts without a hang or crash | 5 or more starts |
| Pacing | VRR on, no obvious stutter | `BC250_PACE` holding while generating, passing through in menus |
| Restore | Restore run; Status and the launcher show nothing left | the game folder and launcher entry compared byte for byte before and after |
| Game settings | the file and key, the value before and after | applied and reverted key by key by the installer |
| Review | a maintainer reviews the JSON in a pull request | a maintainer reproduces it and updates the README's table |

What a recipe may set: one DirectX 12 launch switch; OptiScaler keys the shipped build reads, but never HUDFix, GPU
spoofing, Reflex or quality and colour settings, and never a key OptiScaler's own fix for the game sets; game settings
by file, key and value. A game frame-generation input needs the setting that turns the game's frame generation on. A
maintainer builds every recipe into the recipe file with the project's recipe builder, which refuses one that breaks
these rules. No quotes from other sources go into a recipe. A report that fails becomes a known problem: Check shows it, and a repeated failure of
one input takes that input out of the automatic choice.

## Clean-room rules

FreeFG works next to Intel's XeFG runtime but contains none of it. Every contribution must keep it that way.

1. **No Intel bytes.** Do not add any file, or any part of a file, that comes from Intel's software. That includes
   DLLs, shader bytecode (DXIL or DXBC) captured from the runtime, dumps of its GPU buffers, its network weights or
   other constants, its headers, and generated output that copies any of these. Intel's public headers are fetched at
   build time by `release/fetch.py` and must never be committed.
2. **No disassembly, decompilation or reverse engineering of Intel's software for this project.** Do not submit code,
   constants, layouts or comments that you obtained by disassembling, decompiling, tracing or otherwise inspecting the
   inside of Intel's runtime or its shaders. Do not describe such work in issues or pull requests either.
3. **Work from the specification.** Base a new kernel or change on:
   - a written description of the maths and of the inputs and outputs it must handle;
   - Intel's public API and documentation;
   - the observable behaviour of the public API (what goes in, what comes out);
   - this project's own code and documents.

   Write that description down in the pull request. Where it can be arranged, the person who writes a kernel should
   not be the person who wrote its specification.
4. **Weights only at run time.** Kernels read the network's coefficients from the buffers the runtime uploads, at run
   time. Never embed a weight or a weight-derived constant in a shader or in source.
5. **Compare outputs, never code.** A kernel is correct when its output is bit-identical to the runtime's output for
   the same inputs (tested through the public API). Do not compare it with Intel's shader code, or "diff" it against
   that code, or try to make it resemble that code.
6. **Keep a provenance record.** Each new or changed shader needs an entry with its author, its specification, the
   sources consulted, the exact compile command (DXC version and options), the output SHA-256 and the test that
   showed it bit-identical.
7. **The static check must pass.** `release/check_intel_free.py check` on the assembled package must report `pass` with
   no allowance. CI runs it on every pull request.

If you are not sure whether something you know or want to add falls under these rules, ask in an issue before you
write it. Leave out where the knowledge came from in that issue; say only what you want to add.

## Code

- New files start with `SPDX-License-Identifier: MIT` (in the file's comment syntax). By contributing you agree that
  your contribution is licensed under the MIT licence of this project.
- Third-party code needs a licence compatible with MIT and with the GPL-3.0 OptiScaler build it runs alongside. Name
  it, with its source, commit and licence, in `NOTICE.md` and a provenance file.
- Keep host-specific paths, user names, LAN addresses and account identifiers out of the tree. `release/export_tree.py
  --public --strict` refuses files that contain them.
- Run before you open a pull request:

  ```sh
  python3 release/build_layer.py
  python3 release/build_proxy.py
  python3 release/ci/installer_tests.py
  python3 release/assemble.py --variant intel-free-mfg --no-source-companion
  python3 release/check_proxy_wine.py
  ```

  A change that alters `libxess_fg.dll` or `libxefg_wave.so` is a new build. Update its reference hash in
  `release/inputs.lock.json` in the same change, and say what you tested it on. The project can test GPU changes only
  on a BC-250.
- Installer changes need unit tests in `scripts/test_*.py`. Restore must return a game folder and its launcher
  settings to exactly their earlier state.

## Conduct

Be kind and specific. Personal attacks, harassment and posting other people's private information are not tolerated,
and the maintainers may remove such contributions and block their authors.
