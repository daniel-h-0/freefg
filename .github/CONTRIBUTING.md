<!-- Copy of packaging/public/CONTRIBUTING.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/CONTRIBUTING.md instead. -->
# Contributing to FreeFG

Report security problems privately, as [SECURITY.md](../packaging/public/SECURITY.md) describes. It also gives the contact route for rights
holders.

## Reporting a problem

Open an issue at <https://github.com/daniel-h-0/freefg/issues> with:

- the game (store and version), your Proton, Mesa, kernel and gamescope versions, and whether it ran in Steam Game Mode;
- resolution, HDR on or off, the upscaler mode, the frame-generation input, and what you saw;
- `BC250-MFG.log` and `BC250-XeFG-fast.log` from the game folder, and the output of `python3 install.py doctor`;
- for pacing problems, the `BC250_PACE` lines from the game's standard error
  ([TROUBLESHOOTING.md](../packaging/public/TROUBLESHOOTING.md#logs) says where they are).

For a game that does or does not work at all, the Check report is enough ([Game recipes](#game-recipes)).

The logs contain the game's path, which can include your user name; read them before you post them. Never attach game
files, saves, shader caches, captures of Intel's runtime, or anything from your Steam or launcher accounts.

## Game recipes

A recipe is a per-game setup that Setup applies for everyone. Any report of a game on a BC-250, working or not, can
become one.

### Reporting a game

Play the game, then run `python3 install.py check '/path/to/Game.exe' --report` (or Setup's **Check**) and paste its
text into an issue with the **Game report** form. The text holds no paths or user name; read it before you post anyway.

### Community and verified recipes

A community recipe is one JSON file in the source repository's `research/recipes/community/`, whose `README.md` lists
the fields and their rules. Once a maintainer has reviewed it, Setup applies it as **Community-reported on BC-250**. A
recipe that a maintainer reproduces on the maintainers' BC-250 becomes a verified recipe (**Verified on BC-250**).

| Step | Community recipe | Verified recipe |
| --- | --- | --- |
| Hardware | a BC-250 | a BC-250 run by a maintainer |
| Install | Setup from an unmodified game folder; the Check report attached | the same, on the maintainers' library |
| Generation | 2.0 presents per game frame (the OptiScaler overlay or the logs) over at least 10 minutes of gameplay, not a menu | measured with the project's tools over gameplay |
| Stability | 3 starts without a hang or crash | 5 or more starts |
| Pacing | VRR on, no obvious stutter | `BC250_PACE` holding while generating, passing through in menus |
| Restore | Restore run; Status and the launcher show nothing left | the game folder and launcher entry compared byte for byte before and after |
| Game settings | the file and key, the value before and after | applied and reverted key by key by the installer |
| Review | a maintainer reviews the JSON in a pull request | a maintainer reproduces it and updates the table in COMPATIBILITY.md |

### What a recipe may set

- one DirectX 12 launch switch;
- OptiScaler keys that the shipped build reads, except HUDFix, GPU spoofing, Reflex, quality and colour settings, and
  any key that OptiScaler's own fix for the game sets;
- game settings, by file, key and value. A game frame-generation input needs the setting that turns the game's frame
  generation on, or a manual step that says so.

A maintainer builds every recipe into the recipe file with the project's recipe builder, which refuses a recipe that
breaks these rules. A recipe contains no quotes from other sources. A failed report becomes a known problem: Check shows
it, and a repeated failure of one input takes that input out of the automatic choice.

## Clean-room rules

FreeFG runs next to Intel's XeFG runtime but contains none of it. These rules apply to every contribution.

1. No Intel bytes. Add no file, or part of a file, from Intel's software: DLLs, shader bytecode (DXIL or DXBC) captured
   from the runtime, dumps of its GPU buffers, its network weights or other constants, its headers, or generated output
   that copies any of these. `release/fetch.py` fetches Intel's public headers at build time; never commit them.
2. No disassembly, decompilation or reverse engineering of Intel's software for this project. Submit no code, constants,
   layouts or comments obtained by disassembling, decompiling, tracing or otherwise inspecting the inside of Intel's
   runtime or its shaders, and do not describe such work in issues or pull requests.
3. Work from a specification. Base a new kernel or a change on:
   - a written description of the maths and of the inputs and outputs it must handle;
   - Intel's public API and documentation;
   - the observable behaviour of the public API (what goes in, what comes out);
   - this project's own code and documents.

   Write the description in the pull request. Where it can be arranged, a kernel's author is not the author of its
   specification.
4. Weights only at run time. Kernels read the network's coefficients at run time, from the buffers the runtime uploads.
   Never embed a weight or a weight-derived constant in a shader or in source.
5. Compare outputs, never code. A kernel is correct when its output is bit-identical to the runtime's output for the
   same inputs, tested through the public API. Do not compare it with Intel's shader code, diff it against that code, or
   make it resemble that code.
6. Keep a provenance record. Each new or changed shader needs its author, its specification, the sources consulted, the
   exact compile command (DXC version and options), the output SHA-256 and the test that showed it bit-identical. The
   compile recipe and SHA-256 belong in `release/profile/origin.json`, which `release/build_profile.py check` reads;
   state the rest in the pull request.
7. The static check must pass. `release/check_intel_free.py check` on the assembled package must report `pass` with no
   allowance. CI runs it on every pull request.

If you are not sure whether something you know or want to add falls under these rules, ask in an issue before you write
it. In that issue, say only what you want to add, not where the knowledge came from.

## Code changes

- Start every new file with `SPDX-License-Identifier: MIT` in the file's comment syntax. By contributing you agree that
  your contribution is licensed under this project's MIT licence.
- Third-party code needs a licence compatible with MIT and with the GPL-3.0 OptiScaler build it runs alongside. Name it,
  with its source, commit and licence, in `NOTICE.md` and in a provenance file.
- Keep host-specific paths, user names, LAN addresses and account identifiers out of the tree.
  `release/export_tree.py --public --strict` refuses files that name a host path (a home directory, a removable-media
  mount, a Windows user folder).
- Installer changes need unit tests in `scripts/test_*.py`. Restore must return a game folder and its launcher settings
  to exactly their earlier state.
- Before you open a pull request, run the commands in [BUILDING.md](../packaging/public/BUILDING.md#build-and-check). CI runs them again on
  the pull request.
- A change that alters `libxess_fg.dll` or `libxefg_wave.so` is a new build. Update its reference hash in
  `release/inputs.lock.json` in the same change, and say what you tested it on. The project can test GPU changes only on
  a BC-250.

## Conduct

Be kind and specific. Personal attacks, harassment and posting other people's private information are not tolerated. The
maintainers may remove such contributions and block their authors.
