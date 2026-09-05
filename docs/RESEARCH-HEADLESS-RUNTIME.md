# Headless-Runtime Research — What Exists, What Upstream Offers, What HANDOFF Gets Wrong

Date: 2026-09-05. Sources: 7 completed subagent reports (task ids below), the plan at
`/Users/blessed/.claude/plans/linear-napping-raven.md`, `docs/HANDOFF.md` §§6/10,
`tests/test_runtime.py`, and the sidecar at `upstream-scratch4js/packages/scratch-mcp/src/`.

Task-output agents: `aadcf8b279803b379` (debug APIs), `a65deeb45cf66f0aa` (test harness),
`a74b5ccf940cbcbec` (gui introspection), `a855ff79e344ad2a6` (clone semantics),
`a136fd32e23a0a7a4` (determinism), `a87cad3a83d63bfdf` (desktop harness),
`a0248ec90d67fcc34` (extensions/pen/sound — came back as a conversational proposal, not a
cited findings report; treat §2.7 as proposal, not evidence).

---

## 1. What exists today: our sidecar vs upstream

### 1.1 Our sidecar (`upstream-scratch4js/packages/scratch-mcp/src/`, 3210 lines total)

`runtime.js` (651 lines) — `HeadlessRuntime` on TurboWarp `scratch-vm`, lazily required
(`runtime.js:34-40`). No renderer, no audio engine, by design (`runtime.js:15-17`); nanolog
chatter muted around VM calls (`muted()`, `runtime.js:43-60`).

Already wired:
- `vm.loadProject` (`runtime.js:216`), `greenFlag()` (`runtime.js:369`), manual `rt._step()`
  loop (`runtime.js:412`), `drainEvents()` (`runtime.js:172`).
- `summary()` (`runtime.js:554-593`): per-target `{variables, lists}` from
  `t.variables`, sprite `{x, y, direction, size, visible, costume, costumeNumber}`,
  `monitors` via `getMonitorState()` (`runtime.js:595`), `bubbles` via
  `target.getCustomState('Scratch.looks')` (`bubbleOf`, `runtime.js:630-651`),
  `question`, `threadsRunning: rt.threads.length` (`runtime.js:588`), `errors[]`.
- Broadcast log via wrapped `rt.startHats` — **broadcasts only**
  (`event_whenbroadcastreceived` + `BROADCAST_OPTION`, `runtime.js:291-301`). Other hats are
  not logged. Coarse `PROJECT_RUN_START/STOP` debug events (`runtime.js:303-309`).
- `input()` (`runtime.js:449-510`): keyboard/mouse via `vm.postIOData`, 480x360 canvas
  remap, `_clickTargetAt` bbox stand-in that fires `event_whenthisspriteclicked`
  (`runtime.js:494`) because headless `Mouse` device would otherwise always pick the Stage
  (`runtime.js:477-490`); `answer` via emitting `ANSWER` (`runtime.js:502`).
- Event log capped at `MAX_EVENT_LOG=1000` (`runtime.js:121`); returned by `vm_run`
  (`runtime.js:421-431`).
- MCP tools (`index.js`, 1392 lines): exactly six — `vm_load`, `vm_green_flag`, `vm_run`,
  `vm_state`, `vm_input`, `vm_stop`. No thread inspector, no step control, no seed, no
  hat log, no variable watcher.
- `blocks.js` (780 lines): bundled-extension catalog (`buildExtensionCatalogInto`,
  `blocks.js:553-582`, dir→id map at `blocks.js:435`, e.g. `scratch3_pen: 'pen'`); pen/music
  opcodes deliberately excluded from the core catalog (`blocks.js:365-367`) and surfaced
  as `requiresExtension` (`blocks.js:638-639`). No extension *loader* — catalog only.

Python side (`scratch_unified/`): `typed_proxy.py:233-269` proxies `sb3_vm_*`;
`sb3_vm_run` has the `paced` passthrough (HANDOFF §10.3); `node_bridge` `_read_frame`
respects `TIMEOUT` and `call_tool` caps at 50 000 chars with a visible truncation marker.
`tests/test_runtime.py` drives load→green→click-plots→click-start→run-wave-1→assert.

### 1.2 Upstream (`TurboWarp/scratch-vm`, `develop`) surface we do NOT use yet

- `runtime.threads` (Array, `src/engine/runtime.js:229`) and `runtime.threadMap`
  (Map keyed `<targetId>&<topBlockId>`, `src/engine/runtime.js:231`, rebuilt by
  `updateThreadMap()` at `src/engine/runtime.js:2502-2509`). Status helpers
  `isActiveThread` (`:2077`), `isWaitingThread` (`:2090`); `runtime._lastStepDoneThreads`
  (`:2561`) holds threads that finished in the previous `_step()`.
- Full `Thread` class (`src/engine/thread.js`, 532 LOC): `topBlock`, `stack`
  (`Array<string>` block ids), `stackFrames` (parallel; each has `isLoop`, `warpMode`,
  `justReported`, `params` = procedure locals, `executionContext`), `status`
  (0 RUNNING / 1 PROMISE_WAIT / 2 YIELD / 3 YIELD_TICK / 4 DONE), `justReported`,
  `isKilled`, `isCompiled`, `target`, `blockContainer`, `stackClick`, `updateMonitor`.
  Methods: `peekStack()` (`:351`), `peekStackFrame()` (`:360`), `pushParam/getParam`,
  `goToNextBlock()` (`:439`).
- `Sequencer` at `runtime.sequencer` (`src/engine/sequencer.js`): `stepThreads()` (`:71`,
  one frame, returns doneThreads), `stepThread(thread)` (`:178`, one thread to next
  yield), `stepToBranch` (`:296`), `stepToProcedure` (`:319`), `retireThread` (`:365`),
  `activeThread` (`:56`).
- `BlockUtility` (`src/engine/block-utility.js`, 242 LOC): 2nd arg of every primitive —
  `sequencer/thread/runtime/target/stackFrame`, `startStackTimer/stackTimerFinished`,
  `yield/yieldTick`, `startBranch/startProcedure`, `stopAll/stopOtherTargetThreads/
  stopThisScript`, `startHats`, `ioQuery(device, func, args)` (`:229-239`),
  param accessors, `nowObj`. Only constructed inside `execute()` — obtainable outside by
  wrapping `runtime._primitives[opcode]`.
- Events: `BEFORE_EXECUTE/AFTER_EXECUTE` (`src/engine/runtime.js:668,675`, fired in
  `_step()` at `:2547,2552`), `MONITORS_UPDATE` (`:776`, emitted `:2587` with
  `state.shallowClone()`), `PROJECT_RUN_START/STOP`, `PROJECT_STOP_ALL`,
  `STOP_FOR_TARGET`, `VISUAL_REPORT` (`:3096`), `BLOCK_GLOW_ON/OFF` + `SCRIPT_GLOW_ON/OFF`
  (`:3052,3065`).
- `Profiler` (`src/engine/profiler.js`, 390 LOC): `enableProfiling(onFrame)` at
  `src/engine/runtime.js:3414`, `disableProfiling()` at `:3423`; per-frame +
  per-opcode counters. Closest thing to a trace hook.
- `ioDevices` (`src/engine/runtime.js:340-348`): `clock` (`projectTimer/pause/resume/
  resetProjectTimer`), `cloud` (`clear()`), `keyboard` (`getKeyIsDown`), `mouse/
  mouseWheel` (`getClientX/Y`), `userData` (`postData/getUsername`), `video`.
  Block-side access is `util.ioQuery(device, func, args)`; outside a block, call methods
  directly (e.g. `vm.runtime.ioDevices.clock.projectTimer()`).
- `getMonitorState()` (`src/engine/runtime.js:1025`) returns a `MonitorState`
  (`src/engine/tw-monitor-state.js`, Map of `MonitorRecord`
  `{id, mode, opcode, params, spriteName?, targetId?, x, y, width, height, visible, min,
  max, isDiscrete, sliderMin, sliderMax, value}`); GUI consumes it via
  `src/lib/monitor-adapter.js`.
- Upstream has **no** hat-entry log (only wrappable `startHats` at
  `src/engine/runtime.js:2197` and `_pushThread` at `:2004`), **no** per-variable watcher
  (only poll-and-diff on `target.variables`, or override `_primitives['data_setvariableto'/
  'data_changevariableby']` in `src/blocks/scratch3_data.js`), **no** breakpoint system,
  **no** seedable PRNG (see §2.5).

---

## 2. Per-report key findings

### 2.1 Debug APIs (`aadcf8b279803b379`) — the introspection cheat sheet

Thread stack/locals probe: `vm.runtime.threads` → `t.peekStackFrame().params`
(procedure locals), `t.stack` (block-id stack), `t.justReported`. Thread lookup:
`vm.runtime.threadMap.get(target.id + '&' + topBlockId)`. One-block stepping:
`vm.runtime.sequencer.stepThread(t)`; one frame: `sequencer.stepThreads()`. Hat-entry
logging: wrap `startHats` (our sidecar already does this for broadcasts at
`upstream-scratch4js/packages/scratch-mcp/src/runtime.js:291-301` — extend the same
wrapper to all opcodes). Most surgical trace hook: wrap `sequencer.stepThread` pre/post
(its call site is `sequencer.js:129`, inner execute at `:217`). Variable diff: poll
`target.variables[id].value`; `Variable` class at `src/engine/variable.js`
(`.id/.name/.type/.value/.isCloud`). Monitor subscription:
`runtime.on(runtime.constructor.MONITORS_UPDATE, state => …)`.

### 2.2 Test harness (`a65deeb45cf66f0aa`) — upstream's own headless patterns

Layout: `test/unit/*.test.js` (pure-Node, `new Thread('…')`, `MonitorRecord` asserts),
`test/fixtures/` (`make-test-storage.js` CDN-backed storage, `readProjectFile.js` —
**pass a Buffer to `vm.loadProject`, not a path**), `test/integration/*.test.js` (two
flavors: green-flag + `whenThreadsComplete` polling, or manual `_step()` with
`vm.runtime.currentStepTime = Runtime.THREAD_STEP_INTERVAL` and **no `vm.start()`**),
`test/snapshot/` (the published headless runner: `index.js` CLI + `lib.js` loader that
`vm.loadProject(buffer)` → `vm.runtime.precompile()` → compare compiled JS against
`__snapshots__/*.tw-snapshot`, `--update` regenerates goldens). SAY-as-test-protocol in
`test/integration/execute.js`: projects SAY `pass/fail/plan N/end`, intercepted via
`vm.runtime.on('SAY', (target, type, text) => …)`. The `updateMonitor` filter convention
(`execute.js` `whenThreadsComplete` counts only `!t.updateMonitor` threads) — our
`summary()` does NOT do this (`runtime.js:588` counts all threads; see §4.8). Local
analog: `upstream-scratch4js/packages/scratch-mcp/test/runtime.test.js` + `fixture.js`
(MCP-mediated load→run→assert on `state.targets[*].variables/bubbles/events/question`);
also `packages/git-sb3/test/git-sb3.test.js`. Verdict: no standalone "headless sb3 test
runner" npm package exists — `test/snapshot/` + `test/integration/` inside scratch-vm
are the runner. Minimal reproducer pattern (load Buffer → `precompile()` → N×`_step()` →
assert `_monitorState` + `threads` + target vars) is in the task output.

### 2.3 GUI introspection (`a74b5ccf940cbcbec`) — there is no `vm.query` protocol

`TurboWarp/scratch-gui/src/lib/` has no `vm-query.js`. Introspection is two-layer: redux
slices mirroring runtime state + the live `vm` in `state.scratchGui.vm`
(`src/reducers/vm.js`, `SET_VM`). The only inspector is the debugger **addon**
(`src/addons/addons/debugger/`): `module.js` pauses via
`thread.status = STATUS_PROMISE_WAIT` and single-steps by throwing a sentinel from a
`defineProperty` setter on `thread.blockGlowInFrame`; emits TW-specific
`RUNTIME_PAUSED/UNPAUSED`; `userscript.js` monkey-patches `vm.runtime._step` to fire
`afterStepCallbacks`; `threads.js` walks `vm.runtime.threads` with `stackFrames/stack/
peekStack/topBlock/target/isCompiled`; `performance.js` graphs FPS +
`vm.runtime._cloneCounter`. Event→redux bridge is `src/lib/vm-listener-hoc.jsx`
(`targetsUpdate`→`UPDATE_TARGET_LIST`, `MONITORS_UPDATE`→`UPDATE_MONITORS`,
`TURBO_MODE_ON/OFF`, `PROJECT_RUN_START/STOP`, `RUNTIME_STARTED/STOPPED`,
`COMPILE_ERROR`, `FRAMERATE_CHANGED`, …). Sprite state reads: `getTargetById`
(`scratch-vm/src/engine/runtime.js:3182`), `getSpriteTargetByName` (`:3197`),
`getTargetByDrawableId` (`:3214`); monitor writes: `requestUpdateMonitor`
(`:3124`) / `requestAddMonitor/requestRemoveMonitor/requestHideMonitor/
requestShowMonitor`. Upshot for us: skip the GUI entirely — read `vm.runtime.*`
directly in the sidecar, same as the debugger addon does.

### 2.4 Clone semantics (`a855ff79e344ad2a6`) — the authoritative reference

Dispatch: `control_start_as_clone` is NOT edge-activated
(`src/blocks/scratch3_control.js:45-51`), fires from `RenderedTarget.initDrawable`
(`src/sprites/rendered-target.js:630-639`, `if (!this.isOriginal) runtime.startHats(
'control_start_as_clone', null, this)`), called via `makeClone()` (`:955-976`) —
**before** the control block's trailing `runtime.addTarget(newClone)`
(`scratch3_control.js:152-175`), so in the hat body `runtime.targets` is one short.
`deleteClone` no-ops on originals and calls `disposeTarget` + `stopForTarget`
(`scratch3_control.js:177-181`); dispose order in `rendered-target.js:1098-1112`:
clone-counter −1 → kill threads (`isKilled`, `sequencer.retireThread`) → splice
`executableTargets` → `sprite.removeClone` (fires `targetWasRemoved`) → destroyDrawable.
Killed threads linger in `runtime.threads` until the next `_step()` filter
(`runtime.js:2528`); mid-tick, `sequencer.js:106-107` skips zero-stack/DONE threads.
Forever ordering: each top-level `forever` body runs **exactly one iteration per tick,
top-to-bottom in one thread** (`sequencer.js:251-264`, `isLoop` return; warp mode
re-executes inline until `WARP_TIME=500ms`, `sequencer.js:62-64`) — confirms HANDOFF
§4.2's one-hat/one-forever design. Per-clone locals: §3.1. Touching headless: §3.2.

### 2.5 Determinism (`a136fd32e23a0a7a4`) — no PRNG layer exists

Zero matches for `seedRandom/seedRNG/setRandomSeed/_seed/_rng` in `src/engine/runtime.js`;
`package.json` has no `seedrandom` dep; no `randomSeed` opcode
(`src/blocks/scratch3_operators.js:17-38`). Complete `Math.random` surface (all direct
calls): `blocks/scratch3_operators.js:91,93` (`operator_random` int/float),
`blocks/scratch3_motion.js:90-91,131` (random position/direction), `util/cast.js:226`
(list `random`/`any` index, interpreter), `util/math-util.js:99`
(`inclusiveRandIntWithout`), `util/uid.js:24`, `extensions/scratch3_translate/index.js:
101`, `sprites/rendered-target.js:996-997` (`duplicate()` x/y — the editor "duplicate
sprite" feature, NOT `create clone`; `makeClone()` at `:964-985` is fully deterministic
and never touches `Math.random`), `import/load-costume.js:153` (setTimeout jitter,
timing only), `compiler/jsexecute.js:349,357,418` (compiled int/float/list-random
templates bake in the global call — patchable at call time). Canonical upstream pattern
is exactly global monkey-patch (`test/unit/util_math.js:52-69` patch/restore;
`test/unit/blocks_operators.js:79-113` only assert range bounds, never reproducibility).
`paced=False` in our harness is **timing** determinism (no per-frame sleep), not value
determinism — do not conflate.

### 2.6 Desktop harness (`a87cad3a83d63bfdf`) — CDP + userscript are the only seams

`TurboWarp/desktop` has no headless mode, no `--evaluate/--screenshot`, no Playwright
harness. Seam A: renderer userscript (`src-renderer-Web/.../editor/gui/index.jsx` appends
`<userData>/userscript.js` post-mount; IPC in `src-main/windows/editor.js`;
userdata at `%APPDATA%/turbowarp-desktop`, `~/Library/Application Support/
turbowarp-desktop`, `~/.config/.config/turbowarp-desktop`). Seam B: Electron honors
`--remote-debugging-port=N`; `turbowarp-desktop --remote-debugging-port=9222
project.sb3` loads a file (`src-main/index.js` `parseCommandLine`) and CDP
`Runtime.evaluate/Page.captureScreenshot/Input.dispatchMouseEvent` work against
`tw-editor://./gui/gui.html`. Authoritative precedent: `GarboMuffin/bananatron`
(maintainer's own Electron audit tool; `instrumented-electron.cjs:587-589` switch table,
preload bridge logger). Reference E2E: `kubohiroya/tm-kamishibai`
(`test/e2e/dsl4-web-preview-chromium.test.mjs` — headless Chromium + hand-rolled
`CdpClient`, `Runtime.enable`, `waitForEvaluation('Boolean(globalThis.Scratch?.vm)')`,
`click()` via `Input.dispatchMouseEvent`, `--use-angle=swiftshader`); ML playtest:
`isHeSatoshi/Getting-Over-It-ML` (CDP `Runtime.evaluate` ↔ `window.nextCommand` input
bridge). `leonzalion/puppeteer-stream` does not exist (404; likely meant
`puppeteer-stream/puppeteer-stream`, migrated). `TurboWarp/packager` only *produces*
bundles, doesn't drive them. Ranking: packager→headless-Chromium→CDP first (cleanest
screenshots), Desktop+CDP second (editor chrome in frame), userscript-only third.
Local caveat: Chromium/Chrome was NOT installed in this environment; needs
`npx playwright install chrome`.

### 2.7 Extensions / pen / sound (`a0248ec90d67fcc34`) — proposal, thin on citations

Returned as chat, not a cited report. Claims: anything goes dependency-wise
(`node-canvas`, `headless-gl`, `sharp` — already a dep — for pen pixels; `web-audio-api`
polyfill or stub for sound); two motives for a custom extension (test blocks Scratch
lacks: HTTP/file/LLM; mock pen-sound-renderer-input with call recorders for assertions);
three options (A: stub renderer satisfying the 7 pen methods + record state; B: per-sprite
stub sound bank recording `playSound`; C: `extension_register` MCP tool calling
`_registerInternalExtension`). Architecture keeps `HeadlessRuntime` and adds stub
renderer / stub audio / extension loader underneath it. No upstream file:line evidence
was supplied — verify pen's 7 renderer methods and the extension registration path in
`scratch-vm/src/extensions/` + `src/engine/runtime.js` before building.

---

## 3. Corrections to HANDOFF where research contradicts it

### 3.1 §6.2 is wrong: per-clone sprite-locals are NOT a shared bucket

HANDOFF §6.2 claims "`MyHP` is a sprite-local on the Enemy target, so all clones share
the same bucket." The implementation says the opposite. Every `Target` owns its own
`this.variables = {}` (`src/engine/target.js:48-52`); `makeClone()` copies via
`newClone.variables = this.duplicateVariables()` (`src/sprites/rendered-target.js:971`),
and `duplicateVariable(id, optKeepOriginalId)` (`src/engine/target.js:410-427`)
constructs a **fresh `Variable` with its own `.value` slot** (same id, copied value);
lookup is per-target (`lookupVariableById`, `target.js:187-199`). A clone's
`set [MyHP] to (…)` writes only its own `Variable.value`; a sibling clone reads only its
own. **There is no cross-clone race on sprite-locals — by construction.**
Correction: delete the §6.2 shared-bucket framing and its "per-clone sprite-local
indexed by spawn order" fix (that refactor is unnecessary). What §6.2 was actually
smelling is §6.1: `EnemyX/EnemyY` are **Stage globals** (`build_tower_game.py:216,232`
declare them on `st`, while `MyHP` is declared on the Enemy target at
`build_tower_game.py:397`), so last-writer-wins clobbering across enemies is real and
§6.1's `EnemyXList + MyIndex` analysis stands unchanged.

### 3.2 Touching-* returns `false` headless — audit the .sb3 before trusting kill-path coverage

Every touching primitive is renderer-gated: `isTouchingPoint` (`rendered-target.js:
761-766`), `isTouchingEdge` (`:772-785`, pure bounds math but still gated),
`isTouchingSprite` (`:792-805`), `isTouchingColor` (`:812-817`),
`colorIsTouchingColor` (`:825-834`) all `return false` when `runtime.renderer === null`,
which is our sidecar's permanent state (`upstream-scratch4js/packages/scratch-mcp/src/
runtime.js:15-17`). The `_mouse_` branch additionally needs `runtime.ioDevices.mouse`.
HANDOFF never states this, and `tests/test_runtime.py`'s "Gold/Score increased (kills
paid out)" check is only meaningful if the tower's hit-check is math-based (EnemyX/Y
publisher + distance, per §§4.2-4.3) rather than a `touching` block. Correction: add to
§10.4 a prerequisite — `grep` the unpacked `.sb3` for `sensing_touchingobject/
sensing_touchingcolor/sensing_coloristouchingcolor`; any hit means the headless kill
assertion is vacuous (it asserts `false`, not combat). If a touching block is ever
needed, stub `renderer.drawableTouching/isTouchingDrawables/isTouchingColor` — do not
"fix" the VM.

### 3.3 No seedable PRNG — `paced=False` is not determinism

Nothing in HANDOFF §10 claims a seed; this corrects a likely misreading of the plan
("deterministic step-debug"). `paced=False` removes per-frame sleeps only. Value
determinism requires the §2.5 monkey-patch (`Math.random` swap covering interpreter +
compiled templates + `cast.toListIndex` + `math-util` + `duplicate()`; optionally pin
`setTimeout` for `load-costume.js:153` seed-budget stability). `makeClone` needs no
seeding. Any future "deterministic replay" tool must do the patch, ideally with the
compiler off (`vm.runtime.setCompilerOptions({enabled:false})`,
`src/engine/runtime.js:2697`) for the interpreter-only path.

### 3.4 Forever ordering: one iteration per tick, top-to-bottom — constrains §6.1 test design

§2.4's ordering rule (`sequencer.js:251-264`) means in a single `start_as_clone` hat
with chained forevers, snapshotting after one tick shows only the *first* forever's body
as run. HANDOFF §4.2's single-forever design is therefore load-bearing for the runtime
harness too: any regression oracle for the §6.1 publisher pattern must step ≥2 ticks (or
until idle) before asserting `EnemyX` freshness, never after exactly one tick.

### 3.5 `threadsRunning` counts monitor threads — §10's headline assertion is loose

`summary()` reports `rt.threads.length` verbatim
(`upstream-scratch4js/packages/scratch-mcp/src/runtime.js:588`), which includes
perpetual `updateMonitor` threads and not-yet-filtered `isKilled` threads (filter runs
at the top of the next `_step()`, upstream `runtime.js:2528`). Upstream's own convention
filters them (`test/integration/execute.js` `whenThreadsComplete` counts only
`!t.updateMonitor`). Correction: "threadsRunning > 0 during wave 1" can pass on monitor
threads alone, and "returns to 0 after" (§10.1's implied idle check) can fail while only
monitor threads remain. Fix in sidecar (`filter(t => !t.updateMonitor && !t.isKilled)`)
or assert on `threadsRunning` deltas plus `StartWave` broadcast, not absolutes.

### 3.6 No change needed: §6.4 already points at the harness; §6.3 rationale narrows

§6.4 already defers to `tests/test_runtime.py` + §10 (manual playtest kept as fallback) —
consistent with §2.6's ranking (headless-VM first, Desktop+CDP later). §6.3's `killed`
guard remains valid but its mechanism is same-clone double-decrement within one tick
(two arrow threads vs one enemy thread), not cross-clone contamination — rename "race"
to "double-hit" when touching the text.

---

## 4. Actionable next tools, ordered by leverage

1. **`vm_threads` inspector** (highest leverage; unlocks §6.1–6.3 oracles). Return
   `vm.runtime.threads` mapped to `{topBlock, target, status, stack, params:
   peekStackFrame().params, justReported, isKilled, updateMonitor, isCompiled}`
   (`src/engine/thread.js:198-360`). Filter flags `includeMonitors`, `includeKilled`.
   Sidecar home: next to `summary()` in
   `upstream-scratch4js/packages/scratch-mcp/src/runtime.js:554`.
2. **Variable watcher with old/new.** Poll-and-diff `target.variables[id].value` on each
   `vm_run` chunk (covers Stage globals `EnemyX/Gold/Lives`), plus optional primitive-wrap
   on `data_setvariableto/data_changevariableby` (`src/blocks/scratch3_data.js`) for
   per-write events. Emits into the existing `_eventLog`
   (`upstream-scratch4js/packages/scratch-mcp/src/runtime.js:121-136`).
3. **`vm_set_seed` determinism switch.** `Math.random` Mulberry32 swap per §2.5 +
   `setCompilerOptions({enabled:false})` interpreter option
   (`src/engine/runtime.js:2697`). Makes wave-1 Gold/Score assertions reproducible.
4. **Step control: `vm_step` (one frame via `sequencer.stepThreads()`,
   `src/engine/sequencer.js:71`) and `vm_step_thread` (via `stepThread(thread)`,
   `:178`), returning `doneThreads` + `_lastStepDoneThreads`
   (`src/engine/runtime.js:2561`). Exact-frame assertions; prerequisite for the §3.4
   two-tick publisher oracle.
5. **Hat-entry log for all hats.** Generalize the existing `startHats` wrapper
   (`upstream-scratch4js/packages/scratch-mcp/src/runtime.js:291-301`) beyond
   `event_whenbroadcastreceived`; log `(opcode, topBlock, target)` for every hat,
   or wrap `_pushThread` (`src/engine/runtime.js:2004`) to catch click/monitor threads
   too. Gives the "which hats fired this chunk" timeline the harness currently infers
   from broadcasts.
6. **Touching-block audit + documented `false` invariant.** `grep` unpacked `.sb3` for
   `sensing_touching*`; record the result in §10. If clean, the current kill-path
   assertions stand; if not, stub at the `renderer.*` seam per §3.2. One-off script, not
   a tool.
7. **`threadsRunning` filter fix** (§3.5). One-line sidecar change
   (`upstream-scratch4js/packages/scratch-mcp/src/runtime.js:588`); re-run
   `tests/test_runtime.py` to confirm the wave-1 assertions still pass.
8. **Pen/sound call recorders** (§2.7 Options A/B). Stub renderer satisfying pen's
   methods + per-sprite stub sound bank, both recording into `_eventLog`. Only after
   1–5: the tower game needs no pen/sound for its current assertions.
9. **`extension_register` loader** (§2.7 Option C, `_registerInternalExtension`). Only
   when a project under test actually uses a custom extension; verify the registration
   path in `scratch-vm/src/extensions/` first — the report supplied no file:lines.
10. **Packager→Chromium→CDP visual regression** (§2.6 `tm-kamishibai` pattern). Lowest
    priority: needs `npx playwright install chrome`, only pays off once headless logic
    coverage is solid and §6.4's "visual misplacement" class is the remaining gap.
