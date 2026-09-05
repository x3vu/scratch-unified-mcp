# scratch-unified-mcp

The first standalone headless Scratch VM over MCP — plus every tool an AI agent needs to build, playtest, and publish Scratch projects without opening a browser.

112 tools. One stdio command. Zero name collisions.

```
MCP client ──stdio──▶ python3 -m scratch_unified
                        ├── social_*   website + social graph (scratchattach)
                        ├── project_*  goboscript text-authoring loop
                        ├── spy_*      blocks ↔ real Python (ScratchPy)
                        └── sb3_*      block surgery + headless VM test loop (Node sidecar)
```

## Why this exists

Three Scratch tool ecosystems each covered part of the loop — website API, block-level editing with a headless VM, Python-to-blocks — but none covered all of it, and switching between three servers with three naming schemes killed momentum. This merges all three behind one transport.

The piece that didn't exist anywhere else: a **headless TurboWarp scratch-vm you can drive and inspect over MCP**. Load a `.sb3`, press green flag, click sprites, step frames, read threads, watch variables — all from tool calls, all assertable.

## Quickstart

```bash
git clone <this-repo> && cd scratch-unified-mcp
pip install -e .
# runtime deps (gitignored reference clones — re-clone to update):
git clone https://github.com/uukelele/scratch-mcp upstream-scratch-mcp
git clone https://github.com/playforge-coding/scratch4js upstream-scratch4js
git clone https://github.com/ZDStudios/scratchpy-studio upstream-scratchpy-studio
# optional, unlocks sb3_* proxy tools:
cd upstream-scratch4js && pnpm install && pnpm build
```

```jsonc
// MCP client config
{ "mcpServers": { "scratch-unified": {
  "command": "python3",
  "args": ["-m", "scratch_unified"],
  "cwd": "/path/to/scratch-unified-mcp",
  "env": {
    "PYTHONPATH": "/path/to/scratch-unified-mcp",
    "SCRATCH_MCP_DATA_DIR": "/path/to/scratch-unified-mcp/.sessions"
    // "SCRATCH_MCP_BRIDGE_PORT": "9060"  // only if something else holds 9060
  },
  "timeout": 600000
} } }
```

```bash
python3 tests/test_offline.py   # 34 checks, no network, no credentials
python3 tests/test_runtime.py   # 41 checks, headless VM playtest (see below)
python3 build_tower_game.py     # 40-check static gate, regenerates the demo .sb3
```

## The headless VM loop

Six core tools, debug tools, and media tools, all proxied to a lazily-spawned Node sidecar (TurboWarp `scratch-vm`, interpreted mode, stdout muted so MCP framing stays clean):

| Tool | What it does |
|---|---|
| `sb3_open_project` / `sb3_save_project` | Load / write `.sb3` (saves live-reload TurboWarp Desktop) |
| `sb3_vm_load` | Load the open project into a fresh VM |
| `sb3_vm_green_flag` | Press green flag (clears bubbles, question, errors) |
| `sb3_vm_run` | Advance N seconds/frames, paced or flat-out. Returns state + ordered event timeline (`say`, `broadcast`, `question`/`answer`, errors) |
| `sb3_vm_state` | Snapshot now: targets (x/y/vars/lists/costume), monitors, bubbles, question, thread count, errors |
| `sb3_vm_input` | Keys, mouse position/clicks (stage coords), `ask` answers. Includes a click shim so `when this sprite clicked` fires headless |
| `sb3_vm_threads` | **Every live thread**: target, clone flag, starting hat, stack depth, status (`running`/`yield`/`promise-wait`/`done`), kill flag |
| `sb3_vm_monitors` | Full monitor table (visible or not) — watch a variable without pixels |
| `sb3_vm_step_frame` | Exactly one frame + before/after counts + delta (new threads, events that tick) |
| `sb3_vm_seed` | Deterministic PRNG (mulberry32 over `Math.random`; scratch-vm has no seedable RNG). Same seed, same run |
| `sb3_vm_watch` | Poll-and-diff variable watcher: old/new/changed per key, per-clone capable |
| `sb3_vm_stub_calls` | Recorded pen/sound stub calls since load |
| `sb3_vm_pen_png` | Pen raster (480×360 software canvas) as PNG base64 + pixel count. Strokes only |
| `sb3_vm_mix_wav` | Offline sound mix as WAV base64: every play at its timer offset, volume/pitch approximate |

Headless gaps are patched, not hidden: distance-based touching fallback (no renderer means every `touching` returns `false` upstream), sprite-click shim, broadcast logging via wrapped `startHats`, interpreter mode to dodge a JIT `pickrandom` false-alarm. Details: `upstream-scratch4js/packages/scratch-mcp/src/runtime.js`.

## Verification

```
34 passed, 0 failed   (offline: tool surface, sessions, spy round-trip, git diff)
41 passed, 0 failed   (runtime: live VM playtest + debug + media tools)
40 passed, 0 failed   (static gate on the generator)
```

## Tool census

`social_*` 20 · `project_*` 18 · `spy_*` 14 · `sb3_*` 60 = **112**, asserted by the offline suite. Full per-tool reference: `docs/IDENTIFIERS.md`. Architecture: `docs/ARCHITECTURE.md`. What the VM research found (and what it corrected): `docs/RESEARCH-HEADLESS-RUNTIME.md`. Build notes and every trap the game taught us: `docs/HANDOFF.md`.

## Layout

```
scratch_unified/          the server (this is what runs)
  server.py               FastMCP app + main()
  vendor_uu/              uukelele/scratch-mcp, vendored (social + projects)
  spy_loader.py           headless ScratchPy import (tkinter stubbed if absent)
  spy_tools.py            14 spy_* wrappers, one shared .spy server
  node_bridge.py          lazy Node sidecar transport (newline-delimited JSON-RPC, TIMEOUT-guarded)
  typed_proxy.py          typed sb3_* proxies (FastMCP rejects **kwargs)
  sb3_extra.py            git unpack/pack/diff, studio/remix/favorites, cloud vars
upstream-scratch-mcp/     reference clone (read-only)
upstream-scratch4js/      reference clone + Node sidecar source (runtime dep for sb3_*)
upstream-scratchpy-studio/  reference clone (runtime dep, loaded headless)
tests/                    test_offline.py (34) + test_runtime.py (26)
build_tower_game.py       demo game generator + 40-check static gate
tower-castle-defense.sb3  generated demo (84 KB)
docs/                     PRD, ARCHITECTURE, IDENTIFIERS, HANDOFF, RESEARCH-HEADLESS-RUNTIME
```

Upstream dirs are never edited — updates are re-clones. Sessions persist as session IDs only, never passwords. If Node/deps are missing, only `sb3_*` proxies report unavailable; everything else works.

## Credits

- [uukelele/scratch-mcp](https://github.com/uukelele/scratch-mcp) (MIT) — social + goboscript core
- [playforge-coding/scratch4js](https://github.com/playforge-coding/scratch4js) (MPL-2.0) — sb3/VM/bridge core
- [ZDStudios/scratchpy-studio](https://github.com/ZDStudios/scratchpy-studio) (MIT) — blocks↔Python core
- [TurboWarp/scratch-vm](https://github.com/TurboWarp/scratch-vm) — the headless engine
- [scratchattach](https://github.com/TimMcCool/scratchattach), [goboscript](https://github.com/aspizu/goboscript)
