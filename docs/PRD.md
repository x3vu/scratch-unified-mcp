# PRD — Scratch Unified MCP

## 1. Problem

Three separate Scratch tool ecosystems exist, each covering only part of the
workflow:

1. **uukelele/scratch-mcp** (Python, MIT) — full Scratch website/social API and
   a goboscript text-authoring loop, but no block-level `.sb3` surgery, no
   headless playtesting, no Python-to-blocks path.
2. **playforge-coding/scratch4js** (Node, MPL-2.0) — surgical `.sb3` editing,
   a live block catalog from scratch-vm, a headless TurboWarp VM test loop,
   and a TurboWarp Desktop live-reload bridge, but no website/social API and
   no Python authoring.
3. **ZDStudios/scratchpy-studio** (Python stdlib, MIT) — blocks ↔ real-Python
   round trip and "any module becomes blocks", but no website API and no
   `.sb3`-native editing.

A user building a Scratch game (e.g. Tower Castle Defense) needs all three:
author logic, test it headlessly, publish and share it socially. Switching
between three servers, three transports, and three naming schemes is the
pain this project removes.

## 2. Goals

- **G1 — One command.** A single MCP client entry (`python3 -m
  scratch_unified` over stdio) exposes everything.
- **G2 — Biggest-leverage toolset.** Keep every tool from all three
  upstreams that has no equivalent elsewhere: 104 tools total.
- **G3 — Zero collisions.** Every tool name is unique; upstream A's
  `social_*`/`project_*` names are kept verbatim, scratch4js becomes
  `sb3_*`, scratchpy becomes `spy_*`.
- **G4 — Graceful degradation.** The server always starts. If Node/deps,
  the goboscript toolchain, or Scratch credentials are missing, only the
  affected family reports "unavailable" — the rest works.
- **G5 — No regressions.** Each upstream README quickstart keeps working
  (vendored as-is, reference clones untouched).

## 3. Non-goals

- No TypeScript rewrite of scratch-vm (kept as a lazy Node sidecar).
- No GUI for scratchpy-studio (headless import only).
- No new Scratch website API surface beyond what scratchattach/s-api4js
  already provide.
- No cloud persistence; sessions live in a local JSON file.

## 4. Users

- **Game builders** (primary): author → playtest → publish a `.sb3`
  entirely through MCP tools. Tower Castle Defense is the reference build.
- **Researchers / archivists**: search projects, fetch metadata, remixes,
  favorites, studio info, cloud vars.
- **Automation agents**: drive the full loop (write Python → blocks →
  headless VM run → screenshots → publish).

## 5. Functional requirements

### 5.1 Tool families

| Family | Count | Source | Transport |
|---|---|---|---|
| `social_*` | 20 | vendored uukelele `social.py` | native (scratchattach) |
| `project_*` | 18 | vendored uukelele `projects.py` | native (goboscript CLI) |
| `spy_*` | 14 | native wrappers over headless scratchpy core | native (in-process) |
| `sb3_*` proxied | 44 | typed proxies to Node sidecar | lazy MCP-over-stdio subprocess |
| `sb3_*` native extras | 8 | `sb3_extra.py` (git diff, studio, cloud) | native |

### 5.2 Social (`social_*`)

- Connect via `.env`, password, session id, or browser cookie;
  `social_list_sessions`, `social_set_active_session`,
  `social_verify_session`, `social_forget_session`.
- Reads: `social_get_user_info`, `social_get_project_info`,
  `social_search_projects`, `social_check_inbox`, `social_get_comments`,
  `social_get_comment_replies`.
- Writes (default to check-first): `social_post_comment`,
  `social_reply_to_comment`, `social_follow_user`, `social_like_project`,
  `social_add_project_to_studio`, `social_become_scratcher`,
  `social_set_bio`, `social_set_whatimworkingon`, `social_set_pfp`.
- Sessions persist as session ids only — never passwords.

### 5.3 Projects / goboscript (`project_*`)

- Lifecycle: `project_new` → edit `.gs` → `project_build` →
  `project_summary` → `project_save_to_cloud`; plus `project_open`,
  `project_download`, `project_list`, `project_select`, `project_info`,
  `project_close`.
- Assets: `project_list_assets`, `project_add_costume`,
  `project_add_sound`, `project_remove_asset`, `project_set_thumbnail`.
- Help: `project_editing_guide`, `project_goboscript_docs_help`,
  `project_check_toolchain` (reports; never blocks other families).

### 5.4 Blocks ↔ Python (`spy_*`)

- `spy_open_project` → `spy_write_python` (the main build tool: any
  Python becomes blocks) → `spy_read_blocks` / `spy_read_code` →
  `spy_run` (run-and-capture).
- `spy_import_python_file`, `spy_delete_file`, `spy_set_variable`,
  `spy_project_overview`.
- `spy_list_block_types`, `spy_list_packages`, `spy_install_package`,
  `spy_add_package_blocks` (any installed/stdlib module → blocks),
  `spy_remove_package_blocks`.

### 5.5 SB3 surgery + VM (`sb3_*`)

- Edit: `sb3_open_project`, `sb3_save_project`, `sb3_project_info`,
  `sb3_list_sprites`, `sb3_get_target`, `sb3_get_target_json`,
  `sb3_list_blocks`, `sb3_get_block_schema`, `sb3_enable_extension`,
  `sb3_patch_target`, `sb3_set_sprite`, `sb3_add_sprite`,
  `sb3_remove_sprite`, `sb3_rename_target`, `sb3_set_stage`,
  `sb3_set_variable`, `sb3_delete_variable`, `sb3_set_list`,
  `sb3_delete_list`, `sb3_add_broadcast`, comments
  (`sb3_list/add/set/remove_comment`), costumes/sounds add/remove.
- Website via Node session: `sb3_scratch_login`,
  `sb3_open_scratch_project`, `sb3_push_to_scratch` (confirm-gated),
  `sb3_share_project` (confirm-gated).
- Headless VM: `sb3_vm_load`, `sb3_vm_green_flag`, `sb3_vm_run`
  (state + event timeline), `sb3_vm_stop`, `sb3_vm_state`,
  `sb3_vm_input`.
- Live: `sb3_reload`, `sb3_run_project`, `sb3_stop_project`,
  `sb3_screenshot`, `sb3_screenshot_jpeg` (need TurboWarp + userscript).
- Native extras (no Node needed): `sb3_git_unpack`, `sb3_git_pack`,
  `sb3_git_diff`, `sb3_studio_info`, `sb3_remixes`, `sb3_favorites`,
  `sb3_cloud_get_vars`, `sb3_cloud_set_var`, `sb3_cloud_logs`.

## 6. Quality requirements

- Offline suite `tests/test_offline.py`: 34 checks, no network, no
  credentials — tool-surface counts, session-registry parity, spy
  round trip, sb3 unpack/pack/diff, graceful-degradation messages.
- Full tool census asserted: 20 + 18 + 14 + 52 = 104, no duplicates.
- `validate()`-style structural checks wherever we generate `.sb3`
  bytes (see Tower Castle Defense: input-name and broadcast-ID checks).

## 7. Constraints

- Python ≥ 3.12; Node ≥ 18 optional (sidecar only).
- License mix respected: MIT (uukelele, scratchpy) + MPL-2.0
  (scratch4js); upstream dirs are reference-only, never edited.
- Directory name contains a space (`Scratch mcp`): all paths resolved
  absolutely; client config `cwd` quoted.
- `scratchattach==3.0.0b3` pinned (upstream-pinned beta API).

## 8. Acceptance criteria

- [ ] One MCP client `command` starts the server (Python stdio).
- [ ] `tools/list` shows all 104 tools with the names in §5.
- [ ] No regression vs each upstream README quickstart.
- [ ] `python3 tests/test_offline.py` → 34 passed, 0 failed.
- [ ] Tower Castle Defense `.sb3` loads and plays in Scratch/TurboWarp.
