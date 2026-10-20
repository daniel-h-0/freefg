# Community recipes (`community-bc250`)

One JSON file per game, named after its Steam AppID or a slug (`3669870.json`, `the-witcher-3.json`).
`build_recipes.py` validates every file (`check_community`) and builds it into `packaging/recipes/recipes.json` →
`community`; Setup applies it as tier B ("Reported working on BC-250 by N reports; not reproduced by the maintainers"),
game settings included (Restore reverts them key by key). The checklist a report must pass is in CONTRIBUTING.md ("Game
recipes"); what a recipe may set is the table below (the maintainers' rule C1).

```json
{
  "title": "Game Title",
  "match": {"steam": ["1234560"], "exe": ["game-win64-shipping.exe"]},
  "status": "community-bc250",
  "route": "opti",
  "fg_input": "upscaler",
  "ini": {},
  "game_settings": [],
  "launch_args": ["-dx12"],
  "manual_steps": ["Choose DLSS in Video > Upscaling."],
  "known_problems": [{"input": "dlssg", "text": "DLSS FG input gives a black screen"}],
  "reports": [
    {"issue": 123, "freefg": "1.0.0", "package_sha256": "...", "proton": "GE-Proton11-7", "mesa": "...", "kernel": "...",
     "gamescope": "...", "hdr": false, "vrr": true, "resolution": "2560x1440", "upscaler_mode": "Performance",
     "ratio": 2.0, "minutes": 30, "starts": 3, "restore_checked": true, "date": "2026-11-02"}
  ],
  "reviewed_by": "maintainer handle",
  "reviewed": "2026-11-03"
}
```

| Field | Rule |
|---|---|
| `match` | a launcher ID (`steam`, `gog`, `epic`), or `exe` names together with the title; generic exe names alone never match |
| `route`, `fg_input` | `native`, or `opti` with `upscaler`, `dlssg` or `fsrfg` (never FSR 3.0 FG; XeFG is always the generator) |
| `fg_input` `dlssg`/`fsrfg` | needs the game setting that turns the game's frame generation on, or a manual step saying so (F2) |
| `ini` | OptiScaler keys the shipped build reads; never an installer key, HUDFix, `Spoofing.Dxgi`, Reflex, quality/colour keys (H1, D1, R1, S1), and never a key OptiScaler's own fix for the exe sets (Q1) |
| `game_settings` | `file` relative to the prefix's `drive_c/users/steamuser`, `format` (`json`, `json-options`, `xml-option`, `ini-replace`, `ini`), `values`; Restore reverts them key by key. Engine.ini motion-vector tweaks (E1) only with a maintainer's evidence |
| `launch_args` | one DX12 switch (`-dx12`, `-d3d12`, `-force-d3d12`) |
| `known_problems` | inputs that failed on a BC-250: they leave the automatic choice like a wiki veto |
| `reports` | at least one, each at 2.0 presents per game frame (`ratio` ≥ 1.95) over ≥ 10 minutes of gameplay, 3 starts without a hang, Restore checked |

No quotes from other sources go in these files, and no paths or user names.
