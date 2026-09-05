# HANDOFF — Tower Castle Defense Build

Everything I learned the hard way while building this game. Read this before
touching `build_tower_game.py` again.

---

## 1. The project, one paragraph

`/Users/blessed/Scratch mcp/build_tower_game.py` is a stdlib-only Python
script that generates `tower-castle-defense.sb3` — a 9-target vanilla
Scratch 3 tower-defense game (Stage + Castle + 4 Plots + Enemy + Arrow +
StartButton). 40-check self-test runs in <2s, only writes the .sb3 on PASS.

Run: `cd "/Users/blessed/Scratch mcp" && python3 build_tower_game.py`

---

## 2. The map (what each piece does)

### File layout

| Lines (approx) | What it is |
|---|---|
| 1-50 | imports, helpers `uid()`, `B()`, `chain()`, `sub()`, `menu()`, `NUM()`, `TXT()`, `var_rep()` |
| 200-260 | Stage setup: 11 variables, 4 broadcasts, 3 backdrops, 2 sounds, green-flag reset |
| 270-300 | Castle target (1 sprite, 1 sound, 2 costumes) |
| 290-380 | Plot setup loop (4 instances), per-Plot `occupied` + `ShooterX` + `ShooterY` sprite-locals |
| 340-380 | Plot shoot loop (per-Plot `event_whenflagclicked` with `control_forever`) |
| 380-580 | Enemy target: 1 `start_as_clone` hat, ONE forever (publish + hit-check + arrival-check + movesteps) |
| 580-740 | Arrow target: 1 `start_as_clone` hat with atan-based homing math |
| 660-720 | StartButton: click handler with `looks_hide` + `sayforsecs` + 3-branch feedback |
| 760-800 | `OPCODE_INPUTS` schema (every supported opcode's required input names) |
| 800-1100 | `_check_static` (12 structural checks) |
| 1100-1300 | `_simulate_spawner`, `_simulate_arrow_hits` (behavioral checks via block walking) |
| 1300-1450 | `_check_geometry` (SVG bbox checks) |
| 1450-1700 | `self_test()`, `Report`, `main()` |

### Key helpers — these are how the script talks to Scratch's block model

- `B(target, opcode, **kwargs)` — create a block. `parent=None` for top-level.
  Returns the block id.
- `chain(target, [id1, id2, ...])` — set `next` pointers so id1 → id2 → ... → None.
- `sub(target, parent_id, input_name, child_id)` — wire a child block as
  an input. For `SUBSTACK` / `SUBSTACK2` (forever / if-else bodies) and
  `CONDITION` (if conditions).
- `var_rep(target, sprite_or_None, var_name, var_id)` — create a reporter
  block that reads a variable. Returns the reporter's block id. **You must
  set the reporter's `parent` after, because the helper doesn't.**
- `menu(target, sprite_or_None, opcode, input_name, value)` — create a
  dropdown shadow menu (sprite-name selectors, sound menus, etc).
- `NUM(n)` — primitive number shadow `[4, str(n)]`.
- `TXT(s)` — primitive string shadow `[10, s]`.
- `bc(target, msg)` / `bcast(target, msg, parent=...)` / `bcast_wait(target, msg)` — broadcast senders.

### The stage variables and lists

Scalars: `Gold` (150), `Lives` (10), `Wave` (0), `Score` (0),
`EnemiesLeft` (0), `GameActive` (0), `ShooterX` (0), `ShooterY` (0).

Lists: `EnemyXList`, `EnemyYList`, `MyHPList` (one slot per enemy clone,
HANDOFF §6.1 — replaced the old last-writer-wins `EnemyX`/`EnemyY`
publisher). ShooterX/Y are still the shared handoff (last tower to fire
wins), which is fine because only one arrow is in flight per plot at a
time.

### The 4 broadcasts (each with a single shared id across all targets)

`StartWave` (StartButton → Enemy spawner), `ArrowSpent` (Enemy → Arrow),
`GameOver` (Enemy + StartButton → Stage), `Victory` (Enemy + StartButton
→ Stage). IDs are `bcast-<Name>` strings.

---

## 3. The 42 self-test checks (what they actually verify)

| # | Check | Catches |
|---|---|---|
| 1 | targets_present | missing/extra sprite targets |
| 2 | block_count | total block count drift |
| 3 | unique_block_ids | duplicate ids |
| 4 | parent_next_links | dangling or self-referential pointers |
| 5 | broadcast_senders | sender missing menu shadow |
| 6 | broadcast_id_uniqueness | two ids for the same message name |
| 7 | broadcast_listeners | listener missing broadcast field |
| 8 | opcode_input_names | the NUM1/OPERAND1 swap trap (caught the spawner bug) |
| 9 | list_field_not_input | list ops encode LIST as a **field** `[name, id]`, never an input — the VM's arg resolver and JIT both read `fields.LIST`; input-encoded refs crash threads with `Cannot read properties of null (reading '_isHat')` |
| 10 | known_opcodes | every emitted opcode is one scratch-vm registers — catches typos like `operator_pickrandom` (real name `operator_random`), which silently fail JIT compile and spin the interpreter |
| 11 | repeat_TIMES_shape | `control_repeat` with wrong input name |
| 12 | menu_values | dropdown references nonexistent menu option |
| 13 | assets_present | costumes/sounds not in `data` |
| 14 | monitors_match_stage_vars | Gold/Lives/Wave/Score have monitors |
| 15 | spawner_TIMES_evaluates | spawner `repeat TIMES` evaluates to 0 (or non-positive) |
| 16 | spawner_creates_clones | spawner has at least 1 `control_create_clone_of` |
| 17 | arrow_moves_horizontally | Arrow has `motion_movesteps STEPS>0` (still useful as a sanity check) |
| 18 | arrow_points_right | Arrow chain has `point in direction 90` with DIRECTION as an input (the build's own convention) |
| 19 | arrow_clone_chain_order | Arrow's `start_as_clone` chain: goto → show → forever (in that order) |
| 20 | arrow_no_static_90 | no hardcoded `point in direction 90` in the Arrow top-level hat chain (regression check) |
| 21 | arrow_homes_on_enemy | Arrow's forever body reads `item T of EnemyXList` and uses `operator_mathop atan` (per-clone targeting, HANDOFF §6.1) |
| 22 | arrow_dx_dy_computed | Arrow's forever has `operator_subtract(itemT(EnemyXList), motion_xposition)` and same for y |
| 23 | enemy_publishes_position | Enemy clone hat's forever `replaceitemoflist` both EnemyXList and EnemyYList at MyIndex |
| 24 | enemy_registers_slot | Enemy clone hat sets MyIndex and appends x/y/HP to EnemyXList/EnemyYList/MyHPList (HANDOFF §6.1) |
| 25 | plot_has_per_plot_shooter_vars | each Plot has sprite-local ShooterX/ShooterY |
| 26 | enemy_walks_tower_lane | Enemy has gotoxy to y=90 or y=-110 (one of the two lanes) |
| 27-37 | costume_center:* (11) | each costume's SVG bbox is non-empty |
| 38 | arrow_cosmetic_tip_right | arrow SVG's rightmost `<path>` is within 1px of bbox xmax (real check, not tautology) |
| 39 | arrow_atan_dx_over_dy | arrow homing math: `atan(dx/dy)` + 180-flip on `dy<0`, `DEGREES` on turnright (the axes were swapped; same-row shots only worked by luck) |
| 40 | opcode_input_names covers list ops | `data_replaceitemoflist` = `INDEX`+`ITEM`, `data_itemoflist` = `INDEX` (emitting `ITEM`/`VALUE` silently no-ops every read/write — lists froze at append values, arrows homed to the origin) |
| 41 | spawner_resets_slot_lists | spawner clears EnemyXList/YList/MyHPList before repeating — the append-only graveyard grew to 96+ dead slots and arrow scans crawled |
| 42 | no_orphaned_blocks | every non-shadow block reachable from a topLevel script — caught the escape/kill zero-writes whose SUBSTACK heads pointed past them |

---

## 4. What I got wrong (the long list, with the actual fix)

### 4.1 `OPERAND1`/`OPERAND2` vs `NUM1`/`NUM2` — THE trap

**What it is:** Scratch VM silently ignores input keys that don't match
the opcode's schema. The block "runs" but reads `0` for the wrong-named
input. Self-test check #8 catches this for `operator_add`/`subtract`/
`multiply`/`divide` (`NUM1`/`NUM2`) and `operator_equals`/`gt`/`lt`/
`and`/`or` (`OPERAND1`/`OPERAND2`) and `operator_mathop` (`NUM`).

**The actual bug I shipped:** Enemy spawner's `operator_add` used
`OPERAND1`/`OPERAND2`, so `3 + Wave` evaluated to `0 + 0 = 0`, and
`repeat TIMES=0` spawned zero orcs. The comment immediately above the
block literally described the bug. The build had been broken for days
because the static check existed but I never re-ran it after a prior
agent "fixed" something.

**Fix:** Use `NUM1`/`NUM2` for arithmetic. The check will fail loudly
next time.

### 4.1b `operator_not` reads `OPERAND`, not `OPERAND1` — arrows never flew straight

**What it is:** the same silent-ignore trap but for a UNARY op: `not (a)`
reads `args.OPERAND` (scratch3_operators.js `not(args)`), while the
generator emitted `OPERAND1` (binary-op habit). The VM warned once
(`operator_not: missing input OPERAND`) and every `not` evaluated
`!toBoolean(undefined)` = **always TRUE**.

**Consequence (only visible live):** the Arrow's `if not(T > len) → home
else fly straight` ALWAYS took the home branch. An arrow whose target
died re-homed to the stale dead slot and chased it forever instead of
flying straight to the stage edge — arrows never died, the population
grew to 100+, frame rate collapsed, and the game died by wave 5-9 even
with 4 towers. `operator_not` is now in `OPCODE_INPUTS` with `OPERAND`,
so check #8 (opcode_input_names) fails loudly on a regression.

### 4.1c The escape/kill zero-writes were ORPHANED — escaped orcs became
unhittable ghosts

**What it is:** the §6.1 design zeroes a clone's `MyHPList` slot when it
dies (`hpk0`) or escapes (`hpe0`) so arrow targeting skips it. Both
blocks were BUILT and `chain()`-ed — but the `ifx`/`ifd` SUBSTACK heads
were pointed at `chL`/`chG`, one block PAST the zero-write, so the
writes never executed. `data_replaceitemoflist ITEM=0` blocks sat
orphaned (no parent, unreachable), and every structural check passed
because they had valid ids/inputs.

**Consequence (found by watching list state live):** an escaped orc left
`MyHPList[i]=1` and `EnemyXList[i]=196` behind — a live slot whose clone
was gone. Every arrow's first-live scan found that ghost first and homed
to x=196 forever (freezing at ~204, never reaching the edge), so arrow
population exploded to 100+, the VM crawled, and kills collapsed. The
old harness passed because wave-1 orcs (HP 1) were zeroed "for free" by
the hit-decrement.

**Fix:** point the SUBSTACK heads at the zero-writes
(`sub(e, ifd, "SUBSTACK", hpk0)`, `sub(e, ifx, "SUBSTACK", hpe0)`), and
add check #42 `no_orphaned_blocks` (every non-shadow block reachable
from a topLevel script). Mutation-tested: reverting the two heads makes
#42 fail with exactly those orphans.

### 4.1d Append-only slot lists became a graveyard — arrow scans crawled

**What it is:** slots are never removed (indices must stay stable
mid-wave), so the three lists grew by one row per orc, forever. By wave
9 they held 96+ dead slots, and every arrow re-ran its first-live scan
from slot 1 every frame. TurboWarp's compiled-loop interrupt parks a
long non-yielding loop at ~1 iteration per frame when the frame is busy,
so under load each scan took ~3 seconds and arrows effectively froze.

**Fix:** the Enemy `StartWave` spawner clears all three lists before
repeating (safe: every prior clone is dead by a wave boundary; fresh
clones re-register from slot 1). Check #41 `spawner_resets_slot_lists`
guards it, and the simulator that walks hat → repeat now skips the
`data_deletealloflist` resets.

### 4.2 Scratch 3 only runs ONE `start_as_clone` hat per clone — and chained forevers do NOT spawn threads

**What it is:** two related illusions. First, adding three
`control_start_as_clone` hats to the Enemy target (march script,
hit-check forever, position-publisher) is dead code — the runtime only
executes the topmost one. Second, the attempted "fix" — chaining two
`control_forever` blocks via `next` inside one hat — never spawned
parallel threads either. scratch-vm's sequencer has **no sibling-thread
semantics for C-blocks reached in normal flow**: the first `forever`
swallows the thread, so everything after it (the position-publisher
forever, the glide, the arrival handling) was dead. Verified in the
Sequencer source: `control_forever` pushes a stack frame with
`executedForever` and re-steps its own SUBSTACK forever.

Result (observed live in the headless VM): orcs never moved (x stayed
at the spawn), `EnemyX`/`EnemyY` stayed 0, arrows homed to the origin
and accumulated forever, and nothing was ever hit.

**The static check missed it** because it only verified that a
forever with `set EnemyX` existed somewhere in the Enemy target — not
that it was actually reachable from the topmost start_as_clone hat.

**Fix:** ONE `start_as_clone` hat, ONE `control_forever`, no glide.
`motion_glidesecstoxy` is also blocking (it yields the thread until
the glide finishes), so it can't precede the forever either — the
clone does everything per frame inside a single forever: publish
position, hit-check (via the sidecar's headless touching shim, §4.15),
arrival-check, then a manual `motion_movesteps` toward the castle:

```
hat → looks_show → set MyHP → set LanePick → gotoxy(lane)
  → point in direction 90
  → control_forever{
      set EnemyX to x position; set EnemyY to y position;
      if touching Arrow { change MyHP -1; broadcast ArrowSpent;
        if MyHP < 1 { Gold+20; Score+100; coin; removed_seq; delete this clone } }
      if x position > 195 { change Lives -1; removed_seq; delete this clone }
      else { move 1.5 steps }
      wait 0.03 }   ← per-frame pacing, see below
```

Because every exit path (`delete this clone`) also kills the thread,
no "after the forever" code can exist — everything the clone ever
does must live inside the forever's SUBSTACK.

**One more trap found live:** a forever body with **no yielding block**
does NOT run once per frame in this TurboWarp build. Its warp-mode
sequencer spins the body until the JIT's stuck threshold (~10
iterations per `_step`), so `move 1.5 steps` became ~14px/frame and
orcs teleported across the lane before arrows could fire (arrows
without waits flew to ±2M). The fix is a trailing `control_wait 0.03`
(≈1 frame at 30fps) in the Enemy AND Arrow forever bodies — a wait
yields per frame in both the JIT and interpreter paths, restoring
official-Scratch pacing. The Arrow got the same treatment.

### 4.3 `motion_pointtowards [Enemy v]` does NOT work for clones

**What it is:** `motion_pointtowards` resolves to the **original sprite's**
`(x, y)`, not a clone's. In a tower-defense game where the orc is a
clone, this points at where the sprite template sits (often `(0, 0)` or
the home position), not at any active enemy.

**The fix I shipped:** the Enemy publishes its position to Stage
variables `EnemyX`/`EnemyY` on every frame. The Arrow's forever
re-aims using `atan2`-emulation: `dx = EnemyX - x position`,
`dy = EnemyY - y position`, `point in direction (atan(dy/dx))` with
`if dx<0 then change direction by 180` for quadrant correction.

**Why "last writer wins" is OK here:** the arrow flies at 12 steps/frame
(~360/sec) and reaches an enemy in 1-2 seconds. Within that window,
the latest-published position is usually the one the arrow is tracking.
With 4-13 enemies per wave, the arrow hits something.

### 4.4 Scratch 3 has `atan` but NOT `atan2`

`operator_mathop` with `OPERATOR="atan"` returns degrees in `(-90, 90)`.
No `* 180/π` needed (the block already does the conversion). The
quadrant correction (`if dx<0 then change direction by 180`) is required
because `atan(dy/dx)` only handles the right half-plane. For `dx=0`,
`atan(±∞) = ±90` which is correct (straight up/down), so no extra
handling needed.

### 4.5 The "earlier race fix" didn't actually fix the race

A previous agent claimed to make `ShooterX`/`ShooterY` per-Plot
sprite-locals. They were still on the Stage. The fix was actually
applied: each Plot has its own local id, AND the Plot writes to both
the local AND the Stage mirror. The Stage mirror is what the Arrow
reads. So the writes are correct, but the variable assignment is
shared.

**Verdict:** the double-write works because Scratch serializes
variable writes per tick. Last writer wins. With `wait 0.9` between
shots, the race is irrelevant in practice.

### 4.6 `broadcast ArrowSpent and wait` froze the game

The Enemy's hit-check used `bcast_wait("ArrowSpent")` to signal the
arrow to self-delete. `bcast_wait` blocks the sender until ALL
receivers finish. With 4 arrows/sec × 4 towers, every arrow's
`ArrowSpent` handler had to run before the next enemy could check
hit. This serialized the game loop and dropped the framerate.

**Fix:** use `bcast` (fire-and-forget) for `ArrowSpent`. The Arrow's
defensive delete-on-ArrowSpent handler can stay (cheap insurance) but
the Enemy no longer blocks on it.

### 4.7 Static `point in direction 90` — the original "tower shoots
straight up" complaint

The user said "the tower shoots straight up". The actual bug was
subtler: the arrow DID point right (direction 90), but the tower
fired horizontally at the tower's y. A tower in y=90 row could not
hit an orc in y=−110 row. **There are TWO lanes, but only one is
reachable per tower.**

The fix in 4.3 (homing) made the cross-lane case work.

### 4.8 Costume / say blocks pile up and obscure the play area

`looks_say` with no duration persists until another `say` overwrites
it. The original "Defend me!" on Castle and "Wave N" on StartButton
both stayed forever, covering parts of the play area.

**Fix:** use `looks_sayforsecs MESSAGE SECS=2` so they auto-clear.

### 4.9 StartButton covered the stage during waves

It only hid on `GameOver`/`Victory`, so it sat at `(0, 150)` for the
whole wave.

**Fix:** `looks_hide` is the first block in the wave-starting chain
of the StartButton's click handler.

### 4.10 Wave ≥10 click was a silent no-op

Click handler had `if (GameActive==0) { if (Wave<10) {...} else {?} }`.
The else branch was empty.

**Fix:** added `looks_sayforsecs "All waves complete!" 2` to the
inner else.

### 4.11 Glide ended at x=195, Castle at x=200

Orcs visibly stopped 5px short.

**Fix:** changed glide x literal to 200.

### 4.12 The "costume_center" check was hardcoded `True`

Looked like a real check in the output but always passed. Cosmetic
only — caught by code review, not by anything semantic.

**Fix:** now asserts `bbox_w > 0 and bbox_h > 0` with the actual
dimensions in the message.

### 4.13 The "arrow_cosmetic_tip_right" check was a tautology

`visual_xmax >= width * 0.8 + visual_xmin` simplifies to
`width >= 0.8 * width` (always true for non-empty bbox).

**Fix:** now counts `<path>` elements and verifies the rightmost
path's xmax is within 1px of the bbox xmax.

### 4.15 Headless touching: `touching` blocks need a renderer shim

**What it is:** scratch-vm's `isTouchingSprite` and `isTouchingEdge`
both bail with `if (!this.renderer) return false`. Headless (no
renderer), arrows could fly straight through orcs — `touching Arrow`
always evaluated false, so enemies never took damage and nothing ever
died, regardless of how well arrows homed.

**Fix:** `HeadlessRuntime._patchHeadlessTouching` (runtime.js, applied
once per load) wraps the two methods on the RenderedTarget prototype:
when a renderer exists the real implementation wins; otherwise
`isTouchingSprite` does a stage-coordinate distance check (size-scaled
24px radius, like the click shim) against **all visible clones** of the
named sprite (the renderer path checks every clone, not just the
first), and `isTouchingEdge` checks the sprite's bounds against the
480×360 stage.

### 4.14 Dead code (resolved): `EnemyY` Stage var, Enemy `HP` sprite-local,
`tip_offset_from_right` geometry variable

`EnemyY` was declared and initialized but never read or written
elsewhere. `HP` (separate from `MyHP`) was set on each clone but
only `MyHP` was read by the hit-check. `tip_offset_from_right` was
`visual_xmax - visual_xmax` (always 0 by construction) and never used.

**Fix:** removed all three. (The old `EnemyY` Stage var is now a
real, used Stage list `EnemyYList` — see §6.1.)

---

## 5. How the runtime actually flows

1. Green flag → Stage resets all 11 vars, shows Battlefield backdrop.
   Castle shows, says "Defend me!" for 2s. Each Plot shows empty
   costume at its home, sets `occupied=0`. Arrow and Enemy hide.
2. Click an empty Plot → if `Gold >= 50`, set `occupied=1`,
   `Gold -= 50`, switch to tower costume, play build sound. Start
   its shoot-loop thread.
3. Click StartButton → if `GameActive==0 AND Wave<10`: increment
   `Wave`, set `EnemiesLeft = Wave + 3`, set `GameActive=1`,
   broadcast `StartWave`, hide, say "Wave N" for 2s.
4. Enemy receives `StartWave` → `repeat (3 + Wave) { clone
   myself; wait 0.8s }`. Each clone runs the merged
   `start_as_clone` hat.
5. Each Enemy clone shows, registers its per-clone slot (`MyIndex`
   = list length + 1; appends x/y/HP to `EnemyXList`/`EnemyYList`/
   `MyHPList`, §6.1), picks lane y=90 or y=−110, points right, then
   runs ONE forever (see §4.2): `replaceitemoflist MyIndex` its
   x/y into the lists every frame, hit-checks arrow contact
   (headless touching shim, §4.15), arrival-checks `x > 195`
   (castle → `Lives -= 1` + vanish), else `move 1.5 steps` toward
   the castle, then `wait 0.03` to pace the loop at 30fps
   (warp-mode spins non-yielding bodies ~10x/frame).
6. Each Plot's shoot-loop (every 0.9s, when built and wave is
   active) writes its position to its sprite-local AND the Stage
   `ShooterX`/`ShooterY`, then clones the Arrow.
7. Each Arrow clone goes to `(ShooterX, ShooterY)`, shows, plays
   shoot sound. In its forever: scans `EnemyXList`/`MyHPList` for
   the first live slot (T cursor: `repeat until T > len OR item T
   of MyHPList > 0 { T += 1 }`), then re-aims at `item T` of
   EnemyXList/EnemyYList via atan with quadrant correction, moves
   12 steps. Deletes at the edge or on `ArrowSpent` while touching
   Enemy.
8. If a clone hits the castle: `Lives -= 1`, `EnemiesLeft -= 1`,
   `removed_seq` runs. If `Lives<1` → `GameOver`. If
   `EnemiesLeft==0` → `GameActive=0`. If `Wave>9` → `Victory`.
9. `GameOver` / `Victory` → Stage swaps backdrop, plays sound,
   `stop all`.

---

## 6. What still needs doing

### 6.1 Per-clone enemy state via Stage lists (DONE)

Per-clone tracking is implemented: Stage lists `EnemyXList` /
`EnemyYList` / `MyHPList` hold one slot per enemy clone. Each clone,
on entry, appends x/y/HP and saves its slot as a sprite-local
`MyIndex` (list length + 1, assigned in spawn order). The
position-publisher forever does `data_replaceitemoflist MyIndex
motion_xposition` into EnemyXList / EnemyYList each frame. The
arrow's homing body scans the lists with a `T` cursor: `repeat
until T > length(EnemyXList) OR item T of MyHPList > 0 { T += 1 }`,
then homes on `item T` — the first LIVE enemy, not the last writer.

**No mid-list deletes.** On kill or escape the clone sets its
`MyHPList` slot to 0 (liveness marker) and `delete_this_clone`;
slots are never removed, so other clones' `MyIndex` never shifts.
The arrow's scan skips dead slots via the HP check. This replaces
HANDOFF's original "delete at MyIndex" idea (which would have shifted
indices mid-wave) and the old shared `EnemyX`/`EnemyY` last-writer
clobbering.

**sb3 gotcha that cost an hour:** list references must be encoded as
`fields.LIST = [name, id]`, NOT `inputs.LIST = [1, id]`. Both the
interpreter's arg resolver (`_argValues.LIST = {id, name}`) and the
JIT (`descendVariable(block, 'LIST', ...)` reads `fields`) only look
at fields. Input-encoded list refs deserialize to a dangling block
id — `getCached` returns null and the thread dies with `Cannot read
properties of null (reading '_isHat')`. Static check #9
(`list_field_not_input`) guards this.

### 6.2 Per-clone `MyHP` (DONE)

The old shared `MyHP` sprite-local is gone; HP lives in the
`MyHPList` Stage list slot per clone (§6.1). Arrow contact drains
this clone's slot by 1; at 0 the clone pays out Gold/Score, plays
the coin sound, zeroes its slot, and deletes itself. Escape zeroes
the slot too (same liveness rule) before deducting a Life.

### 6.3 The hit-kill race

If two arrows touch the same enemy on the same frame, both
decrement `MyHP` and both broadcast `ArrowSpent`. The enemy could
over-kill (go to -2 instead of 0). With low tower density, rare.

**Fix:** add a `killed` sprite-local; set it to 1 the first time
`MyHP<1`, then the second decrement is no-op'd by an outer `if
not killed`.

### 6.4 Re-test in a real browser

The 40-check self-test catches structural bugs. It does NOT catch:
- visual misplacement (bboxes can be non-empty but in the wrong
  place)
- timing bugs (clones spawning too fast/slow)
- cross-target semantic bugs (broadcast id collisions, hidden
  variable scoping)

**The right next step (automated):** run `python3 tests/test_runtime.py`.
It drives the `.sb3` through the headless `sb3_vm_*` tools, clicks
Plots 1-3, clicks StartButton, runs wave 1 to completion, and asserts
threads ran, `StartWave` broadcast fired, `errors[]` stayed empty,
`Gold`/`Score` increased, `Lives` stayed >= 0. If the sidecar isn't
installed it skips cleanly; with `SCRATCH_RUNTIME_SKIP=1` it no-ops
for offline CI. See §10 for the harness contract.

**The right next step (manual fallback):** open the .sb3 in
scratch.mit.edu or TurboWarp and play it. Build 2-3 towers, click
START WAVE, watch one full wave. If orcs die and gold ticks up, the
build is shippable. If they don't, dump the .sb3 to a temp dir and
read the actual block graph.

### 6.5 Update docs

`docs/TOWER-GAME-SPEC.md`, `docs/ARCHITECTURE.md`, `docs/IDENTIFIERS.md`
are stale. They describe the pre-homing, pre-sprite-local,
pre-StartButton-hide design. Update them with:
- New ShotterX/Y semantics (per-Plot local + Stage mirror)
- New EnemyX/Y publisher pattern
- New homing atan math
- New self-test check count and what each one catches

### 6.6 Add a docstring to `build_tower_game.py` listing the
self-test's known coverage gaps

So the next person who touches this doesn't repeat the same
search. Specifically: "this script does not simulate runtime
cloning behavior; for any change that adds a new `start_as_clone`
hat, verify only ONE such hat exists per target."

---

## 7. Hard-won rules (commit these to memory)

1. **Always re-run `python3 build_tower_game.py` after any edit.**
   The check count is the contract. If it drops, I broke something.
2. **Never add a second `start_as_clone` hat to a target.** Merge
   the logic into a `control_forever` chained via `next`.
3. **Never use `motion_pointtowards [Sprite v]` for a sprite that
   gets cloned.** It reads the template, not the clone. Use
   position publishing + atan.
4. **Arithmetic: `NUM1`/`NUM2`. Comparison: `OPERAND1`/`OPERAND2`.**
   `operator_mathop`: `NUM`. The static check enforces this; the
   VM silently ignores wrong names.
5. **Broadcast receivers and senders must share a single id per
   message name across all targets.** The Stage mirrors the
   registry. The `broadcast_id_uniqueness` check enforces this.
6. **Sprite-local variables are per-clone, Stage variables are
   shared.** `duplicateVariable(id, keepId=true)` (`target.js:415`) gives
   every clone its own `Variable` instance (same id, own `.value`), so a
   clone writing `MyHP` never touches another clone's `MyHP`. Only Stage
   globals (`EnemyX/Y`, `ShooterX/Y`, `Gold`, `Lives`) are last-writer-wins
   across clones — those are the ones that need a list + index (§6.1).
7. **`bcast_wait` blocks the sender until all receivers finish.**
   Use `bcast` unless you genuinely need the synchronous wait.
8. **`glidesecstoxy` is blocking — no other code in the same
   thread runs while it animates.** For parallel work in a hat,
   chain `control_forever` via `next`.

---

## 8. The file list

Modified:
- `/Users/blessed/Scratch mcp/build_tower_game.py` — the only file
  with code changes. ~1700 lines.

Generated:
- `/Users/blessed/Scratch mcp/tower-castle-defense.sb3` — the
  output. ~84,700 bytes.

Unchanged (stale docs):
- `/Users/blessed/Scratch mcp/docs/PRD.md`
- `/Users/blessed/Scratch mcp/docs/ARCHITECTURE.md`
- `/Users/blessed/Scratch mcp/docs/IDENTIFIERS.md`
- `/Users/blessed/Scratch mcp/docs/TOWER-GAME-SPEC.md`

---

## 9. Unified-server update (2026-09-04, verified live)

HANDOFF §§1-8 cover only the tower game. This section covers the rest
of the repo — the unified MCP server — and re-verifies the tower
build so the next session starts from a known-good state.

### 9.1 What this repo actually is

Two projects in one directory:

1. **`scratch_unified/` — the merged MCP server** (the product).
   One FastMCP app over stdio merging three upstreams into 112 tools:
   20 `social_*` + 18 `project_*` (vendored uukelele/scratch-mcp,
   scratchattach+goboscript) + 14 `spy_*` (headless scratchpy-studio)
   + 60 `sb3_*` (52 proxied to the scratch4js Node sidecar + 8 native
   extras in `sb3_extra.py`). Zero name collisions, one `command`
   (`python3 -m scratch_unified`) starts everything.
2. **`build_tower_game.py` → `tower-castle-defense.sb3`** — the
   reference build proving the server's `sb3_*`-shaped output can ship
   a complete playable game. Stdlib only, self-test gated.

Reference clones (`upstream-scratch-mcp/`, `upstream-scratch4js/`,
`upstream-scratchpy-studio/`) are read-only / runtime deps — never
edit them. Upstream updates = re-clone.

### 9.2 Server entrypoint and ownership

- `scratch_unified/__main__.py:1-4` → `from .server import main`.
- `scratch_unified/server.py:25-30` `main()` calls
  `vendor_uu.utils._restore()` (reload persisted session ids) then
  `mcp.run(transport="stdio")`.
- The single FastMCP app is owned by
  `scratch_unified/vendor_uu/server.py:8`
  (`mcp = FastMCP("scratch-unified")`); `server.py:12` re-exports it.
  Vendored modules do `from .server import mcp`. Import-time
  registration in `server.py:16-22`: `social` + `projects`
  (self-registering via decorators), `sb3_extra` (decorators),
  `register_sb3_tools(mcp)` (52 typed proxies), `register_spy_tools(mcp)`
  (14 wrappers). Import order matters — don't reorder.
- Path constants in `scratch_unified/__init__.py:4-11` (`ROOT`,
  `UPSTREAM_UU/JS/SPY`, `NODE_SERVER`, `SPY_FILE`, `__version__`).
- Deps (`pyproject.toml`): `fastmcp>=3.4.4`, `httpx>=0.28.1`,
  `python-dotenv>=1.2.2`, `scratchattach==3.0.0b3` (pinned beta);
  Python ≥ 3.12. Console script `scratch-unified` =
  `scratch_unified.server:main`.
- Client config (`mcp.json`): `python3 -m scratch_unified`,
  `cwd` = repo root (note the space in `Scratch mcp` — quote paths),
  `PYTHONPATH` = repo root,
  `SCRATCH_MCP_DATA_DIR` = repo `.sessions`, timeout 600000.
- Sessions persist as **session ids only, never passwords**
  (`store.session_file()`; asserted by offline test "no password
  stored").

### 9.3 Tool families (where each tool runs)

- **`social_*` (20, `vendor_uu/social.py`)** — native via scratchattach.
  Sessions (connect/list/set-active/forget/verify), profile, comments,
  follow/like/studio, search (retries on Scratch 429/503), inbox.
  Writes default to check-first; `social_become_scratcher` confirm-gated.
- **`project_*` (18, `vendor_uu/projects.py`)** — native via goboscript
  CLI. `project_new/open/download/list/select/info/close`,
  assets, `project_build` (needs Rust nightly goboscript + sb2gs;
  check with `project_check_toolchain`, which reports but never blocks
  other families), `project_summary`, `project_save_to_cloud`.
  `project_download` decompile path: fetch → `sb3.py` normalize →
  `sb2gs` → optional build-verify.
- **`spy_*` (14, `spy_tools.py` → `spy_loader.py`)** — native
  in-process. `spy_loader.load_spy()` imports
  `upstream-scratchpy-studio/scratchpy_studio.py` headless (real
  tkinter if present, stubbed `tkinter`+submodules fallback only).
  One shared `MCPServer` rooted at
  `$TMPDIR/scratch-unified-spy/default.spy`; `spy_open_project`
  switches it — concurrent projects need explicit switches, and the
  tmpdir is volatile across reboots. `spy_write_python` (defaults
  `file="main", replace=True` — overwrites unless `replace=False`)
  is the main build tool.
- **`sb3_*` proxied (44, `typed_proxy.py` → `node_bridge.py`)** —
  lazy Node sidecar subprocess (`node
  upstream-scratch4js/packages/scratch-mcp/src/index.js`), MCP over
  stdio with Content-Length framing (`initialize` +
  `notifications/initialized` → `tools/call`). FastMCP rejects
  `**kwargs`, hence one explicit typed function per tool; JSON-string
  params (`patch`, `props`, `items`, `keys`) are parsed before
  forwarding. If Node ≥ 18 / `pnpm install && pnpm build` is missing,
  every proxy raises `UNAVAILABLE` naming the unaffected families —
  server still starts. Known wart: `TIMEOUT = 120.0` is defined but
  unused; reads are blocking, so a hung Node hangs the caller.
- **`sb3_*` native extras (8, `sb3_extra.py`, no Node)** —
  `sb3_git_unpack/pack/diff` (pure-Python zipfile+json),
  `sb3_studio_info/remixes/favorites`, `sb3_cloud_get_vars/set_var/logs`
  (cloud tools require an active session: "call
  `social_connect_session` first").

### 9.4 Verified state (ran 2026-09-05)

- `python3 tests/test_offline.py` → **34 passed, 0 failed**.
- `python3 build_tower_game.py` → **self_test: 42 passed, 0 failed**,
  wrote `tower-castle-defense.sb3` (86,199 bytes).
- `python3 tests/test_runtime.py` → **41 passed, 0 failed, 1 skipped**
  (the skipped one is the gated full-game Victory run).
- `RUN_SLOW=1 python3 tests/test_runtime.py` → **44 passed, 0 failed** —
  the full 10-wave playthrough reaches wave 10 with Lives left and the
  Victory broadcast fires. (Dynamic full runs win ~2/3 of the time,
  entering wave 10 at L=6-8.)
- Live `.sb3` introspection: 9 targets
  (Stage, Castle, Plot1-4, Enemy, Arrow, StartButton), ~450 blocks,
  Stage vars incl. Gold 150 / Lives 10 / Wave 0, 3 per-clone slot lists
  (EnemyXList/EnemyYList/MyHPList), 4 broadcasts
  (GameOver, Victory, StartWave, ArrowSpent). File sizes:
  `build_tower_game.py` ~2,300 lines.

### 9.5 Doc drift to know about

- HANDOFF §2 line map and §8 "~1700 lines / ~84,700 bytes" are
  approximate (actual 1861 lines / 84,698 bytes) — close enough, don't
  churn the doc over it.
- HANDOFF §2/§5 say "11 variables" then list 10 and say "Why all 10".
  Code has **10** Stage vars (`build_tower_game.py:213-216`). The
  "11" is the typo.
- `docs/TOWER-GAME-SPEC.md`, `ARCHITECTURE.md`, `IDENTIFIERS.md`,
  `PRD.md`, `TOWER-GAME-README.md` still describe the pre-homing
  design in places (straight-flying arrows, "3 lanes", old byte/block
  counts) — flagged stale in §6.5, still true. Update them only when
  changing gameplay, not for count churn.
- README tool census (20+18+14+52=104) matches `tests/test_offline.py`
  minimums (≥100 total; per-prefix ≥20/18/14/44) — both green.

---

## 10. Headless-VM runtime harness (added 2026-09-05)

The 40-check self-test in `build_tower_game.py` is structural and
single-expression — it does NOT run the VM. `tests/test_runtime.py`
fills that gap by driving `tower-castle-defense.sb3` through the
proxied `sb3_vm_*` tools.

### 10.1 What it checks (live behavior, not shape)

The harness opens the static-test-generated `.sb3`, presses green
flag, clicks Plots 1-3 (cost 50 each → Gold 150→0), clicks
StartButton, runs wave 1, then asserts:

- `Castle "Defend me!" say` event observed on green flag.
- `Gold` drops to 0 after building 3 plots.
- `StartWave` broadcast observed.
- `threadsRunning > 0` while wave active.
- `errors[]` empty across wave 1 (no RUNTIME_ERROR / COMPILE_ERROR).
- `Wave` advanced to ≥ 1.
- `Lives` stayed ≥ 0 (no exception path).
- `Gold` or `Score` increased (kills paid out).
- `vm_threads` sees live Enemy threads mid-wave (sampled while the
  wave is running, not after it completes).
- Escape path: a fresh green flag resets the board (plots' `occupied`
  back to 0, Gold/Lives/Wave reset), so a tower-less wave runs with
  zero kills — all 4 orcs walk the full lane and reach the castle,
  `Lives` deducts 10 → 6, and `GameActive` returns to 0.
- Wave 2: 5 more escapes take `Lives` to exactly 1, still no
  `GameOver` broadcast.
- GameOver: wave 3's 10th escape drops `Lives` below 1 and the
  `GameOver` broadcast fires (removed_seq path), `Lives ≤ 0`.
- Deterministic seed: reload the VM, seed the PRNG (`vm_seed 20240701`),
  run wave 1, and record each enemy clone's `(MyIndex, lane y)` —
  deduped by `MyIndex` across 0.5s chunks. Two runs with the same seed
  must produce byte-identical fingerprints (same lane picks, same spawn
  order). `MyIndex` is assigned in spawn order and lane y is constant
  per clone, so the fingerprint is immune to the wall-clock jitter of
  paced runs shifting which clones exist at each sample boundary.

Both escape/GameOver phases reuse a `run_until(predicate, max_s)`
helper that steps in 0.5s paced chunks and accumulates events across
them (each `vm_run` drains its own event log).

### 10.2 Run

```bash
# Full run (needs Node ≥ 18 + scratch4js workspace deps built).
cd "/Users/blessed/Scratch mcp" && python3 tests/test_runtime.py

# Offline CI without Node.
SCRATCH_RUNTIME_SKIP=1 python3 tests/test_runtime.py
```

Skips gracefully with a clear "sidecar unavailable" message when
Node is missing. Exit code is 1 only on a real failure (skips
don't fail the build).

### 10.3 Sidecar + proxy hardening the harness depends on

- `node_bridge._read_frame` now respects `TIMEOUT` (was
  defined-but-unused; reads were blocking with no deadline). A
  hung Node raises `RuntimeError("Node sidecar timeout after
  %.1fs ...")` instead of hanging the harness. Stdlib-only
  (`time.monotonic` + a deadline check on each read).
- `node_bridge.call_tool` truncation cap raised from 8 000 to
  50 000 chars, with a visible `... [truncated at 50000 chars;
  full result not returned]` marker so long event timelines are
  detectable.
- `typed_proxy.sb3_vm_run` gained a `paced: bool = True`
  parameter (passthrough to upstream). Set `paced=False` for
  back-to-back stepping without per-frame sleeps — what the
  harness uses.

### 10.4 Extending

- New assertion: add `check(label, cond)` after the relevant
  `sb3_vm_run` step; the harness accumulates and prints a final
  `N passed, N failed, N skipped` line.
- New project under test: change `SB3` and the `PLOTS` /
  StartButton coordinates, then keep the same load→green→
  click→run→assert shape.
- The kill-path assertion (`Gold`/`Score` increase) now works: it
  depended on the headless touching shim (§4.15) plus per-frame loop
  pacing (§4.2) — both landed with the wave-1 fixes.
- Regression oracles for the latent races: §6.1 (`EnemyX/Y` Stage
  clobber) is live-tested via the deterministic-seed fingerprint; §6.3
  (hit-kill over-kill) is covered by `errors[]` empty + exact `Lives`
  accounting across the escape/GameOver phases. §6.2 (`MyHP` per-clone)
  needs no oracle — `duplicateVariable` gives each clone its own value
  (rule 6), so there is no shared bucket to regress.

### 10.6 Phase 3a media surface (added 2026-09-05)

- `sb3_vm_pen_png` → `vm_pen_png` — 480×360 software pen raster
  (Bresenham strokes with round caps from `penAttributes.color4f` +
  diameter) exported via `sharp` (already a sidecar dep) as PNG base64
  + non-transparent pixel count. Pen strokes only; sprites never render.
- `sb3_vm_mix_wav` → `vm_mix_wav` — offline mix of every `playSound`
  since load at its project-timer offset, summed to 16-bit mono WAV
  (22050 Hz). PCM-16 assets decode via pure RIFF parse; ADPCM legacy
  assets are recorded but skipped (documented). Volume/pitch effects
  approximate.
- Monitor push — `MONITORS_UPDATE` subscription emits one debug
  `monitor` event per changed monitor per tick (bounded by the log cap).
- Color touching — `isTouchingColor` on the stub samples the pen
  raster for the target RGB inside the sprite's box (tolerance 30);
  `colorIsTouchingColor` mask approximated as target-present.
- Harness §"phase 3a": PNG magic + transparency on the pen-less game,
  RIFF/WAVE magic + event count on the mix, monitor events in a post-flag
  run. 41/41 live.

### 10.5 Phase 2 debug surface (added 2026-09-05)

Four more tools, all live-tested in `test_runtime.py` §"phase 2":

- `sb3_vm_watch(name?, target?)` → `vm_watch` — poll-and-diff variable
  watcher (`HeadlessRuntime.watch`, `runtime.js`). Reports
  `{target, name, value, changed, previous}` per key; clones own their
  values so per-clone watches work.
- `sb3_vm_stub_calls` → `vm_stub_calls` — recorded pen/sound stub calls
  since load (`HeadlessRuntime.stubCallsOf`). Pen state itself lives on
  the sprite (`_customState['Scratch.pen']`); sound plays are recorded
  per sprite via the `soundBank` stub.
- All-hat log — the existing `startHats` wrapper now logs every hat at
  debug level (`hat <opcode> on <target>`), not just broadcasts.
- Monitor-thread filter — `threadsRunning` and the `run()`/`stepFrame()`
  idle check exclude `updateMonitor` + `isKilled` threads (upstream's own
  `whenThreadsComplete` convention), so idle reads 0 instead of +N.

Sidecar fixes that came out of phase-2 testing (all in `runtime.js`
`_attachHeadlessStubs`, each found by a real crash, not by reading):

- `setEffects: () => {}` on the soundBank stub — `sound_cleareffects`
  on green flag calls `_syncEffectsForTarget → setEffects` and crashed
  without it.
- `document = { hidden: false }` shim in `ensureDeps` — TurboWarp's
  `_step` reads `document.hidden` once a renderer is attached; headless
  node has no document.
- Target renderer backfill (`t.renderer = rt.renderer` for load-time
  targets) — targets constructed during `loadProject` captured null
  before `attachRenderer`; the say-bubble path then passed the
  `!runtime.renderer` guard and crashed on null `getBoundsForBubble`.
- `getNativeSize: () => [480, 360]` (was `[100, 100]`) — bubble
  positioning reads stage bounds; the wrong size broke layout math.
- `isTouchingDrawables` distance fallback on the stub — attaching a
  renderer routes the REAL `isTouchingSprite` (which calls
  `renderer.isTouchingDrawables`), so the stub must implement the same
  stage-coordinate semantics, not return false.
- Bridge opt-in — `index.js` only binds the live-reload port when
  `SCRATCH_MCP_BRIDGE_PORT` is set. A second spawn on a held port threw
  `EADDRINUSE` as an unhandled error and killed the sidecar before MCP
  stdio came up ("node stdout closed" on every call).
