# TOWER-GAME-SPEC — Tower Castle Defense

Reference build proving the MCP can ship a complete, playable `.sb3`.
Generator: `build_tower_game.py` (stdlib only) → `tower-castle-defense.sb3`
(83,169 bytes, 301 blocks, 9 targets, vanilla opcodes, no extensions).

## 1. Concept

Tower defense, mouse only. Orcs march left → right toward the Castle.
The player clicks dashed plots to build Archer towers (50 gold). Towers
auto-fire arrows while a wave runs. 10 waves, escalating count/speed/HP.
Win by clearing wave 10; lose when 10 lives run out.

## 2. Entities

| Target | Position | Costumes | Role |
|---|---|---|---|
| `Stage` | — | `Battlefield`, `GameOver`, `Victory` | variables, win/lose scripts, monitors |
| `Castle` | (200, 0), 110% | `castle` | static art, says "Defend me!" |
| `Plot1` | (−120, 90) | `empty`, `tower` | click-to-build + auto-fire |
| `Plot2` | (0, 90) | `empty`, `tower` | same |
| `Plot3` | (−120, −110) | `empty`, `tower` | same |
| `Plot4` | (0, −110) | `empty`, `tower` | same |
| `Enemy` | hidden (−230, 0) | `orc` | spawner + 2 clone scripts |
| `Arrow` | hidden (−300, −200) | `arrow` | projectile clones |
| `StartButton` | (0, 150) | `button` | starts next wave on click |

Art: inline vector SVGs — grass + two dirt paths (y=90 / y=−110),
castle with flag, orc face, tower, arrow, dashed 50-gold plots, START
WAVE button. Sounds: generated WAVs `shoot`, `hit`, `coin`, `build`,
`win` jingle, `lose` tone.

## 3. State

Stage-owned: `Gold`=150, `Lives`=10, `Wave`=0, `Score`=0,
`EnemiesLeft`=0, `GameActive`=0, `ShooterX/Y` (fire position handoff),
`EnemyY` (reserved). Sprite-local: `occupied` (per Plot),
`HP` + `MyHP` (Enemy), `LanePick` (Enemy). Monitors show
Gold/Lives/Wave/Score.

Broadcasts (shared ids `bcast-<Name>`): `StartWave`, `ArrowSpent`,
`GameOver`, `Victory`.

## 4. Scripts (per target)

**Stage.** Green flag: backdrop `Battlefield`, init all 9 variables.
On `GameOver`: backdrop + `lose` + stop-all. On `Victory`: backdrop +
`win` + stop-all.

**Castle.** Green flag: goto (200,0), show, say "Defend me!".

**Plot (×4).** Green flag: costume `empty`, `occupied`=0, goto home,
show. On click: if `occupied`==0 AND `Gold`>49 → `occupied`=1,
`Gold`−=50, costume `tower`, `build` sound. Fire loop (staggered
`i*0.2` s start): forever → if `GameActive`==1 AND `occupied`==1 →
wait 0.9 s, `ShooterX/Y`=self pos, clone `Arrow`.

**Enemy — spawner.** On `StartWave`: repeat `3 + Wave` →
clone-myself + wait 0.8 s.

**Enemy — clone march.** show; `HP` = 1+floor((Wave−1)/3) (and a second
copy dealt to private `MyHP`); pick lane 1/2 → goto (−230, 90) or
(−230, −110); glide to x=195 over 12−Wave×0.7 s keeping lane y;
`Lives`−=1; shared `removed_seq` bookkeeping; delete clone.

**Enemy — clone hit-check.** forever → if touching `Arrow` →
`MyHP`−=1 → broadcast-and-wait `ArrowSpent` (arrow deletes itself) →
if `MyHP`<1 → `Gold`+=20, `Score`+=100, `coin` sound, `removed_seq`
bookkeeping, delete clone.

**`removed_seq` (shared snippet).** `EnemiesLeft`−=1 → if `Lives`<1
broadcast `GameOver` → else if `EnemiesLeft`==0 → `GameActive`=0 →
if `Wave`>9 broadcast `Victory`.

**Arrow — fly.** as-clone: goto (`ShooterX`, `ShooterY`), point 90,
show, `shoot` sound, forever → move 12 steps → if on edge delete.
On `ArrowSpent`: if touching `Enemy` delete.

**StartButton.** Green flag: goto (0,150), show. On click: if
`GameActive`==0 → if `Wave`<10 → `Wave`+=1, `EnemiesLeft`=`Wave`+3,
`GameActive`=1, broadcast `StartWave`, `coin` sound, say "Wave N";
else say "Wave in progress...". Hides on `GameOver`/`Victory`.

## 5. Balance table

| Wave | Orcs (N+3) | HP | Glide (s) | Spawn gap | Fire rate |
|---|---|---|---|---|---|
| 1 | 4 | 1 | ~11.3 | 0.8 s | 0.9 s/tower |
| 2–3 | 5–6 | 1 | ~10.6–9.9 | 0.8 s | 0.9 s/tower |
| 4–6 | 7–9 | 2 | ~9.2–7.8 | 0.8 s | 0.9 s/tower |
| 7–9 | 10–12 | 3 | ~7.1–5.7 | 0.8 s | 0.9 s/tower |
| 10 | 13 | 4 | ~5.0 | 0.8 s | 0.9 s/tower |

Economy: 150 start gold = 3 towers; kills fund the rest at +20 each.
10 lives, no healing.

## 6. How to play

1. Load `tower-castle-defense.sb3` in scratch.mit.edu Create or
   TurboWarp (File → Load from your computer).
2. Green flag → build 2–3 towers → START WAVE.
3. Kills pay for the 4th tower. Survive all 10 waves.
4. Flag to retry after Game Over.

## 7. Rebuild + verify

```bash
python3 build_tower_game.py   # validate() asserts, then writes the .sb3
```

`validate()` covers: ≥6 targets, >100 blocks, unique ids, unbroken
next/parent links, broadcast-menu shape + single-id-per-message,
arithmetic `NUM1`/`NUM2` names, `TIMES` input shape, asset presence.
The headless scratch-vm harness used during debugging
(`vm.start` → green flag → `startHats` click → count Enemy clones)
is the recommended pre-ship check for any generated `.sb3`.
