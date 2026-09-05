# Tower Castle Defense

A fully working tower-defense game for Scratch / TurboWarp. Mouse only.

File: `tower-castle-defense.sb3` (~83 KB, 301 blocks, 9 targets, vanilla opcodes only, no extensions).

## How to play

1. Open https://scratch.mit.edu/ (Create) or TurboWarp Desktop, then File > Load from your computer > `tower-castle-defense.sb3`.
2. Click the green flag. You start with 150 Gold, 10 Lives, Wave 0, Score 0.
3. Click any dashed plot (marked 50) to build an Archer tower for 50 gold. There are 4 plots.
4. Click START WAVE. Orcs march from the left toward the castle on the right.
5. Towers auto-fire arrows while a wave is active (GameActive = 1).
6. Kills pay +20 Gold and +100 Score. Breaches cost 1 Life each.
7. Survive all 10 waves to see the Victory backdrop. Lose all lives for Game Over. Click the flag to retry.

## Waves

- Wave N spawns N + 3 orcs (4 in wave 1 ... 13 in wave 10).
- Orc HP = 1 + floor((Wave - 1) / 3) (1 HP waves 1-3, up to 4 HP wave 10).
- March time shrinks with wave: ~12s down to ~5s (glide 12 - Wave * 0.7).
- Spawn gap 0.8s. Tower fire rate one arrow per ~0.9s per tower.

## Costs and economy

- Tower: 50 gold, one-time, permanent for the run.
- Start gold 150 = 3 towers; kills fund the 4th and beyond.
- Lives 10, no healing; each orc reaching the castle costs 1.

## Tips

- Build 3 towers before wave 1; place the 4th as soon as kills pay for it.
- Towers near the middle cover all three lanes best.
- Arrows fly right (+x) from the firing tower, so left-side plots get more shots per orc.

## Under the hood (for your project)

- Stage: Gold/Lives/Wave/Score/EnemiesLeft/GameActive/ShooterX/ShooterY, backdrops Battlefield/GameOver/Victory, win/lose scripts.
- Castle: static art + "Defend me!".
- Plot1-4: click-to-build (occupied flag, gold check), auto-fire loop writing ShooterX/ShooterY then cloning Arrow.
- Enemy: StartWave spawner (create clones), clone march (upper/lower tower-row lane, wave-scaled glide), touching-Arrow per-clone MyHP loop, kill rewards + wave-clear/Victory/GameOver bookkeeping.
- Arrow: spawns at shooter coords, flies +x, dies on edge or on Enemy touch (Enemy confirms via ArrowSpent handshake).
- StartButton: starts next wave if idle and Wave < 10, sets EnemiesLeft, broadcasts StartWave; hides on GameOver/Victory.
- Art: inline vector SVGs (grass + path backdrop, castle, orc, tower, arrow, plots, button).
- Sounds: generated WAVs (shoot, hit, coin, build, win jingle, lose tone).
- Rebuild: `python3 build_tower_game.py` regenerates the .sb3.
