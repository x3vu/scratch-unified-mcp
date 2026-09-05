# IDENTIFIERS — every name an agent needs, in one place

Conventions: tool names are the MCP contract (stable). File-level helpers
(`B`, `chain`, `uid`, …) exist only inside `build_tower_game.py`. Env vars
are read at runtime. Broadcast/message ids below are Tower-Game-specific.

## 1. MCP tools (104 — the stable contract)

### `social_*` — website/social graph (20, `vendor_uu/social.py`)

| Tool | One-liner |
|---|---|
| `social_connect_session` | Log in via `.env`, password, session id, or browser cookie |
| `social_list_sessions` | Saved sessions + which is active |
| `social_set_active_session` | Switch active login (takes username) |
| `social_verify_session` | Check the active login still works |
| `social_forget_session` | Drop a saved login (optional remote logout) |
| `social_set_bio` | Set profile "About me" |
| `social_set_whatimworkingon` | Set profile "What I'm working on" |
| `social_set_pfp` | Set profile picture from a file |
| `social_get_user_info` | User profile + recent comments |
| `social_get_project_info` | Project metadata + recent comments |
| `social_search_projects` | Search Scratch projects (retries on 429/503) |
| `social_check_inbox` | Activity/alerts inbox page |
| `social_get_comments` | Comments on a project/user/studio |
| `social_get_comment_replies` | Replies under one comment |
| `social_post_comment` | Post a comment (check-first by default) |
| `social_reply_to_comment` | Reply to a comment |
| `social_follow_user` | Follow/unfollow (or check state) |
| `social_like_project` | Love/favorite (or check state) |
| `social_add_project_to_studio` | Add a project to a studio |
| `social_become_scratcher` | Request Scratcher status (confirm-gated) |

Types: `InboxResult`, `ProjectHit`, `ProjectSearch`, `ScratcherResult`,
`UserInfo`, `ProjectInfo`, `CommentInfo`, `CommentThread`, `CommentPage`.

### `project_*` — goboscript lifecycle + assets (18, `vendor_uu/projects.py`)

| Tool | One-liner |
|---|---|
| `project_new` | Scaffold a `.gs` text project |
| `project_open` | Register an existing dir as the active project |
| `project_download` | Download + decompile a Scratch project to `.gs` |
| `project_list` | All known local projects |
| `project_select` | Switch active project |
| `project_info` | Paths, publish id, compat flags |
| `project_close` | Unregister (keeps files) |
| `project_list_assets` | Costumes/sounds per sprite |
| `project_add_costume` | Add costume from file |
| `project_add_sound` | Add sound from file |
| `project_remove_asset` | Remove a costume/sound |
| `project_build` | Compile `.gs` → `.sb3` (needs toolchain) |
| `project_summary` | Targets, blocks, extensions, thumbnail |
| `project_save_to_cloud` | Publish to scratch.mit.edu |
| `project_set_thumbnail` | Upload thumbnail |
| `project_editing_guide` | The authoring manual (from `prompts.py`) |
| `project_goboscript_docs_help` | Block-name lookup (from `prompts.py`) |
| `project_check_toolchain` | Report goboscript/sb2gs readiness |

Types: `ProjectSummary`, `DownloadResult`, `BuildResult`, `PublishResult`,
`AssetList`, `AssetEntry`.

### `spy_*` — blocks ↔ Python (14, `spy_tools.py`)

| Tool | One-liner |
|---|---|
| `spy_open_project` | Open/create a `.spy` file; all other `spy_*` act on it |
| `spy_project_overview` | Tabs, variables, lists, custom blocks, packs |
| `spy_read_blocks` | Readable outline of a tab's scripts |
| `spy_read_code` | The Python a tab generates |
| `spy_write_python` | **Main build tool:** Python → blocks |
| `spy_import_python_file` | Existing `.py` → blocks |
| `spy_delete_file` | Remove a tab |
| `spy_set_variable` | Create variable/list or set start value |
| `spy_run` | Run a tab, return stdout + exit code |
| `spy_list_block_types` | Every block kind + its Python |
| `spy_list_packages` | Installed packages visible to ScratchPy |
| `spy_install_package` | `pip install` + make blocks |
| `spy_add_package_blocks` | Installed/stdlib module → blocks |
| `spy_remove_package_blocks` | Remove a package's blocks |

Infra: `SPY_TOOL_DEFS`, `register_spy_tools(mcp)`, `spy_loader.load_spy()`,
`SPY_PATH`, shared `_server` rooted at
`$TMPDIR/scratch-unified-spy/default.spy`.

### `sb3_*` — surgery, VM, live, extras (52 = 44 proxied + 8 native)

Proxied (`typed_proxy.py` → Node sidecar):

| Tool | One-liner |
|---|---|
| `sb3_open_project` | Load `.sb3` into the Node editor |
| `sb3_save_project` | Write `.sb3` back (live-reloads TurboWarp) |
| `sb3_project_info` | Targets, extensions, monitors, meta |
| `sb3_scratch_login` | Website login for the Node session |
| `sb3_open_scratch_project` | Download a site project by id |
| `sb3_push_to_scratch` | Upload back (confirm-gated) |
| `sb3_share_project` | Publish (confirm-gated) |
| `sb3_list_sprites` | Sprites + position/size/media |
| `sb3_get_target` | Full details for a sprite/Stage |
| `sb3_get_target_json` | Raw `project.json` entry (JSON Pointer ok) |
| `sb3_list_blocks` | scratch-vm opcode catalog |
| `sb3_get_block_schema` | Schema + shadow encodings for one opcode |
| `sb3_enable_extension` | Register an extension id |
| `sb3_patch_target` | RFC 6902 JSON Patch (as JSON string) |
| `sb3_set_sprite` / `sb3_add_sprite` / `sb3_remove_sprite` / `sb3_rename_target` / `sb3_set_stage` | Sprite CRUD |
| `sb3_set_variable` / `sb3_delete_variable` / `sb3_set_list` / `sb3_delete_list` / `sb3_add_broadcast` | Data CRUD |
| `sb3_list_comments` / `sb3_add_comment` / `sb3_set_comment` / `sb3_remove_comment` | Sprite comments |
| `sb3_add_costume` / `sb3_remove_costume` / `sb3_add_sound` / `sb3_remove_sound` | Media (bytes move here, not via patch) |
| `sb3_reload` / `sb3_run_project` / `sb3_stop_project` | TurboWarp Desktop via bridge |
| `sb3_vm_load` / `sb3_vm_green_flag` / `sb3_vm_run` / `sb3_vm_stop` / `sb3_vm_state` / `sb3_vm_input` | Headless VM test loop |
| `sb3_screenshot` / `sb3_screenshot_jpeg` | Live stage pixels via bridge |

Native extras (`sb3_extra.py`, no Node):

| Tool | One-liner |
|---|---|
| `sb3_git_unpack` | `.sb3` → diffable dir |
| `sb3_git_pack` | diffable dir → `.sb3` |
| `sb3_git_diff` | targets/block counts/assets summary |
| `sb3_studio_info` | Studio title/description/stats |
| `sb3_remixes` | Remix lineage (id + title) |
| `sb3_favorites` | User's favorites (id + title) |
| `sb3_cloud_get_vars` | Cloud variable values |
| `sb3_cloud_set_var` | Set one cloud var |
| `sb3_cloud_logs` | Recent cloud activity |

## 2. Server internals (non-tool identifiers)

| Name | File | Meaning |
|---|---|---|
| `mcp` | `vendor_uu/server.py` → re-exported by `server.py` | the single FastMCP app |
| `main(argv)` | `server.py` | `_restore()` sessions, then serve stdio |
| `SESSIONS` / `ACTIVE` / `PERSISTED` | `vendor_uu/utils.py` | live logins / active username / persisted snapshot |
| `active_ses()` / `maybe_ses()` / `me()` / `get_user()` / `get_project()` | `vendor_uu/utils.py` | session accessors + converters |
| `State` / `Record` / `Project` | `vendor_uu/store.py` | persisted JSON shape |
| `data_dir()` / `session_file()` / `read()` / `write()` / `clear()` | `vendor_uu/store.py` | persistence ops |
| `NodeSidecar` / `SIDECAR` | `node_bridge.py` | lazy subprocess + `call_tool(name, args)` |
| `NODE_INDEX` / `TIMEOUT` / `UNAVAILABLE` | `node_bridge.py` | sidecar path, timeout, degradation text |
| `SB3_TOOL_DEFS` / `SPY_TOOL_DEFS` | `typed_proxy.py` / `spy_tools.py` | registration lists |
| `APPLIED` | `vendor_uu/compat.py` | which scratchattach patches fired |

## 3. Environment variables

| Var | Read by | Meaning |
|---|---|---|
| `SCRATCH_MCP_DATA_DIR` | `store.py` | where `sessions.json` lives |
| `SCRATCH_MCP_SESSION_FILE` | `store.py` | override the file path directly |
| `SCRATCH_USERNAME` / `SCRATCH_PASSWORD` / `SCRATCH_SESSION_ID` | `social_connect_session` | login inputs (ids only are persisted) |
| `GOBOSCRIPT_BIN` / `SB2GS_BIN` | `goboscript.py` | Rust toolchain binaries |
| `SCRATCH_MCP_BRIDGE_PORT` | bridge/userscript | TurboWarp live-reload port (default 9060) |
| `PYTHONPATH` | client (`mcp.json`) | must include the `Scratch mcp` dir |

## 4. Tower Castle Defense identifiers

Sprites/targets: `Stage`, `Castle`, `Plot1`–`Plot4`, `Enemy`, `Arrow`,
`StartButton`.

Stage variables: `Gold` (150), `Lives` (10), `Wave` (0), `Score` (0),
`EnemiesLeft` (0), `GameActive` (0), `ShooterX`, `ShooterY`, `EnemyY`.
Sprite-local: `occupied` (per Plot), `HP` + `MyHP` (Enemy),
`LanePick` (Enemy).

Broadcasts (one shared id each, `bcast-<Name>`, Stage mirrors registry):
`StartWave` (button → spawner), `ArrowSpent` (enemy → arrow cleanup),
`GameOver`, `Victory`.

Key builder helpers (`build_tower_game.py`): `uid()`, `B()`, `chain()`,
`sub()`, `bc()`, `bcast()`, `bcast_wait()`, `var_rep()`, `menu()`,
`NUM()`, `TXT()`, `build()`, `validate()`, `main()`.

Gameplay constants: tower cost 50; kill +20 gold / +100 score;
wave N spawns N+3 orcs; HP = 1+floor((Wave−1)/3); glide 12−Wave×0.7 s;
spawn gap 0.8 s; fire 0.9 s/tower; lanes y=90 / y=−110.

## 5. Upstream reference map

| Dir | What lives there | Touched? |
|---|---|---|
| `upstream-scratch-mcp/` | uukelele source (`scratch_mcp/`, tests, README) | never — vendored copies live in `vendor_uu/` |
| `upstream-scratch4js/` | Node monorepo (`packages/scratch-mcp/src/index.js` = sidecar, `s-api4js`, `scratch4js`, `git-sb3`, `userscript`) | never — run in place via `NODE_INDEX` |
| `upstream-scratchpy-studio/` | `scratchpy_studio.py` (11,663 lines) | never — loaded headless via `SPY_PATH` |

## 6. How to find anything

- "I want to do X with Scratch" → §1 tables (tool → family → file).
- "Where does a tool run?" → ARCHITECTURE.md §3 (native vs sidecar).
- "What env/config does it need?" → §3 above + `mcp.json`.
- "Why does the game do that?" → §4 above + `TOWER-GAME-README.md`.
- "Why is it built this way?" → ARCHITECTURE.md §4 + PRD.md §2.
