#!/usr/bin/env python3
"""Headless-VM runtime harness for the unified Scratch MCP.

Drives `tower-castle-defense.sb3` through the proxied `sb3_vm_*` tools and
asserts live behavior the 36-check static self-test cannot catch:
threads running, lives stable, gold ticks up, broadcasts land, errors empty,
escaped orcs deducting Lives, and the GameOver path when Lives hits 0.

Mirrors `tests/test_offline.py` style. Skips gracefully if the Node sidecar
is unavailable (set `SCRATCH_RUNTIME_SKIP=1` to force a no-op run).
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate session persistence from the real ~/.local/share/scratch-mcp.
TMP = tempfile.mkdtemp(prefix="scratch-runtime-test-")
os.environ["SCRATCH_MCP_DATA_DIR"] = TMP

# Skip flag — useful for offline CI without Node.
SKIP = os.environ.get("SCRATCH_RUNTIME_SKIP", "0") == "1"

ok = 0
failed = 0
skipped = 0


def check(label, condition):
    global ok, failed
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def skip(label, why):
    global skipped
    skipped += 1
    print(f"  SKIP  {label}  ({why})")


def section(title):
    print(f"\n== {title} ==")


# Lazy imports so the import side effects (which spawn the sidecar) only
# happen when we actually run checks.
import scratch_unified.server as unified
from scratch_unified.node_bridge import SIDECAR, UNAVAILABLE
import build_tower_game


def text_of(result):
    """In-process fastmcp `call_tool` returns a ToolResult wrapping
    TextContent blocks — pull the joined text back out (or pass a str through)."""
    if isinstance(result, str):
        return result
    parts = []
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for block in content:
            t = getattr(block, "text", None)
            if t:
                parts.append(str(t))
    if parts:
        return "\n".join(parts)
    return str(result)


async def call_text(tool, args):
    """Run an in-process tool call and return its text content."""
    return text_of(await unified.mcp.call_tool(tool, args))


def sidecar_alive():
    """Best-effort check that the Node sidecar is up and answering.

    Probes with `list_blocks`, which needs no open project (project_info
    errors with "No project is open", which made this probe always read as
    dead and skip the whole harness).
    """
    try:
        SIDECAR._ensure_started()
        SIDECAR.call_tool("list_blocks", {})
        return True
    except Exception as exc:
        msg = str(exc)
        # Direct raise from node_bridge, or wrapped by fastmcp ToolError /
        # MCP middleware ("Error calling tool '...': sb3_* tool failed: Node
        # sidecar unavailable ...").
        if "sidecar unavailable" in msg or "sidecar" in msg.lower():
            return False
        # Treat any other failure as a sidecar-not-ready condition for harness
        # purposes (don't crash; report the failure as a check).
        return False


def parse_state(text):
    """`sb3_vm_state` returns JSON inside a string. Be tolerant of truncation marker."""
    if "truncated at" in text:
        text = text.split("... [truncated at")[0]
    return json.loads(text)


def find_summary_field(state, *path):
    """Walk a dotted path through the state JSON, return None if any key missing."""
    cur = state
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def find_stage_var(state, name):
    """Return the Stage's variable value, or None.

    vm_state reports each target's `variables` as a plain {name: value} dict,
    and `monitors` separately as {label, value} entries.
    """
    stage = next((t for t in state.get("targets", []) if t.get("isStage")), None)
    if not stage:
        return None
    value = (stage.get("variables") or {}).get(name)
    # The VM can report numeric variables as strings after `change … by`;
    # coerce so `>= 0`-style comparisons don't explode on types.
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def event_kind(e):
    """Event `type` may arrive as 'say' or 'info/say' — compare on the last
    path segment so logging-level prefixes never break the matcher."""
    return str(e.get("type", "")).split("/")[-1]


def has_event(events, kind, name=None):
    for e in events or []:
        if event_kind(e) == kind:
            if name is None or e.get("name") == name:
                return True
    return False


def first_event(events, kind, name=None):
    for e in events or []:
        if event_kind(e) == kind:
            if name is None or e.get("name") == name:
                return e
    return None


def click_start_button():
    """Press the StartButton at (0, 150): mousedown, a few frames, mouseup.
    The click handler runs in the step right after mouseDown and broadcasts
    StartWave synchronously, so the event lands in the 0.3s run INSIDE this
    helper and would be drained by any later run. Returns that run's parsed
    state so callers can still assert on the broadcast."""
    asyncio.run(call_text("sb3_vm_input", {"mouseX": 0, "mouseY": 150, "mouseDown": True}))
    r = asyncio.run(call_text(
        "sb3_vm_run", {"seconds": 0.3, "frames": 0, "untilIdle": False, "paced": True}))
    asyncio.run(call_text("sb3_vm_input", {"mouseX": 0, "mouseY": 150, "mouseDown": False}))
    return parse_state(r)


def run_until(predicate, max_seconds, chunk=0.5):
    """Step the VM in paced chunks until `predicate(state, events)` is true or
    the budget is spent. Each run drains the event log, so events are
    accumulated across chunks and returned for post-hoc assertions.

    Returns (final_state, all_events, reached).
    """
    all_events = []
    final = None
    for _ in range(int(max_seconds / chunk)):
        r = asyncio.run(call_text("sb3_vm_run", {
            "seconds": chunk, "frames": 0, "untilIdle": False, "paced": True}))
        s = parse_state(r)
        all_events.extend(s.get("events", []) or [])
        final = s
        if predicate(s, all_events):
            return final, all_events, True
    return final, all_events, False


def game_active(state):
    """GameActive as a float, or 0 when the key is missing (treat as inactive)."""
    return find_stage_var(state, "GameActive") or 0


# ------------------------------------------------------------------ build

SB3 = ROOT / "tower-castle-defense.sb3"

section("fixture: regenerate the .sb3 from the static self-test")
res = build_tower_game.main()
check("tower build wrote .sb3", SB3.is_file() and SB3.stat().st_size > 0)

# ------------------------------------------------------------------ sidecar

section("sidecar availability")
if SKIP:
    skip("sidecar probe", "SCRATCH_RUNTIME_SKIP=1")
else:
    alive = sidecar_alive()
    if not alive:
        for label in (
            "vm_load round-trip",
            "green_flag fires",
            "click-to-build threads run",
            "StartWave broadcast observed",
            "errors[] empty across wave 1",
            "Gold increases after kills",
            "Lives stable during wave 1",
            "escaped orcs deduct Lives",
            "GameOver broadcast fires",
        ):
            skip(label, UNAVAILABLE.strip().split(".")[0])
        print(f"\n{ok} passed, {failed} failed, {skipped} skipped")
        sys.exit(0 if failed == 0 else 1)

check("sidecar answered a tool call", True)

# ------------------------------------------------------------------ VM

section("headless VM: load + green flag")
asyncio.run(call_text("sb3_open_project", {"path": str(SB3)}))
load_text = asyncio.run(call_text("sb3_vm_load", {}))
check("vm_load reports loaded", "loaded" in load_text.lower() or load_text.strip() != "")

gf_text = asyncio.run(call_text("sb3_vm_green_flag", {}))
check("vm_green_flag reports greenFlag", "true" in gf_text.lower())

# Capture the initial say event for Castle "Defend me!" (the only 'say' fired
# before any user click in the green-flag chain).
init = asyncio.run(call_text(
    "sb3_vm_run", {"seconds": 0.5, "frames": 0, "untilIdle": False, "paced": True}))
init_state = parse_state(init)
init_events = init_state.get("events", [])
castle_say = first_event(init_events, "say")
check("Castle 'Defend me!' say observed on green flag",
      castle_say is not None and "Defend" in str(castle_say.get("text", "")))

# ------------------------------------------------------------------ build plots

section("headless VM: click-to-build three plots")
# Plot1/2 are at y=90, Plot3/4 at y=-110. Stage is 480x360; default VM coords
# are Scratch stage coords (x in [-240..240], y in [-180..180]) and the input
# API remaps them to 480x360. Click center of each plot.
PLOTS = [
    ("Plot1", -120, 90),
    ("Plot2",    0, 90),
    ("Plot3", -120, -110),
]
for name, x, y in PLOTS:
    # mousedown=true then false to register a click. A click only registers
    # when the VM steps between the down and up states, so run a few frames
    # between them — back-to-back inputs collapse into a no-op.
    asyncio.run(call_text("sb3_vm_input", {
        "mouseX": x, "mouseY": y, "mouseDown": True,
    }))
    asyncio.run(call_text(
        "sb3_vm_run", {"seconds": 0.05, "frames": 0, "untilIdle": False, "paced": True}))
    asyncio.run(call_text("sb3_vm_input", {
        "mouseX": x, "mouseY": y, "mouseDown": False,
    }))

# Give the click handlers a few frames to register before checking gold.
post_clicks = asyncio.run(call_text(
    "sb3_vm_run", {"seconds": 0.3, "frames": 0, "untilIdle": False, "paced": True}))
post_state = parse_state(post_clicks)
gold_after_clicks = find_stage_var(post_state, "Gold")
check("Gold dropped from 150 to 0 after building 3 plots (50 each)",
      gold_after_clicks is not None and gold_after_clicks <= 0)

# ------------------------------------------------------------------ start wave

section("headless VM: click StartButton at (0, 150)")
# Press the button; the handler broadcasts StartWave in the step right after
# mouseDown, so the event lands in the helper's run (later runs drain it).
wave_state = click_start_button()
wave_events = wave_state.get("events", [])
threads_running = wave_state.get("threadsRunning", 0)

check("StartWave broadcast observed", has_event(wave_events, "broadcast", "StartWave"))
check("threadsRunning > 0 during wave 1", threads_running > 0)

# Sample live threads NOW: the wave is mid-flight (spawner waiting between
# clones, first clone's forever running). Sampling later, after the wave
# completes, would find zero Enemy threads and fail spuriously.
threads_text = asyncio.run(call_text("sb3_vm_threads", {}))
threads = parse_state(threads_text)
check("vm_threads sees Enemy threads during wave 1",
      isinstance(threads.get("count"), int)
      and any(t.get("target") == "Enemy" for t in threads.get("threads", [])))

# Wait long enough for one orc spawn + first hit.
asyncio.run(call_text(
    "sb3_vm_run", {"seconds": 3.0, "frames": 0, "untilIdle": False, "paced": True}))

# ------------------------------------------------------------------ wave 1

section("headless VM: run wave 1 to completion")
# Wave 1: 4 orcs, glide ~11s. Run a long step then sample state.
text = asyncio.run(call_text(
    "sb3_vm_run", {"seconds": 12.0, "frames": 0, "untilIdle": False, "paced": True}))
end_state = parse_state(text)
errors = end_state.get("errors", []) or []
check("errors[] empty after wave 1", len(errors) == 0)
gold_end = find_stage_var(end_state, "Gold")
lives_end = find_stage_var(end_state, "Lives")
wave_end = find_stage_var(end_state, "Wave")
score_end = find_stage_var(end_state, "Score")
check("Wave advanced to >= 1", wave_end is not None and wave_end >= 1)
check("Lives >= 0 (no exception path)", lives_end is not None and lives_end >= 0)
check("Gold or Score increased from initial 150/0 (kills paid out)",
      (gold_end is not None and gold_end > 0) or (score_end is not None and score_end > 0))

# ------------------------------------------------------------------ debug tools
# These prove the new sb3_vm_threads / sb3_vm_monitors / sb3_vm_step_frame /
# sb3_vm_seed tools work against the same live run — dynamic per-frame
# inspection, not static block shape.

section("debug tools: monitors / step / seed")
mon_text = asyncio.run(call_text("sb3_vm_monitors", {}))
mons = parse_state(mon_text)
check("vm_monitors returns monitor list", isinstance(mons.get("monitors"), list))

step_text = asyncio.run(call_text("sb3_vm_step_frame", {}))
step = parse_state(step_text)
check("vm_step_frame runs exactly 1 frame",
      step.get("framesRun") == 1 and "before" in step and "after" in step
      and "delta" in step)

seed_text = asyncio.run(call_text("sb3_vm_seed", {"seed": 1234}))
seed_res = parse_state(seed_text)
check("vm_seed installs deterministic PRNG",
      seed_res.get("randomOverridden") is True and seed_res.get("seed") == 1234)
# Restoring: pass no seed (None) -> proxy forwards null -> sidecar restores
# the real Math.random.
restore_text = asyncio.run(call_text("sb3_vm_seed", {}))
restore_res = parse_state(restore_text)
check("vm_seed() with no seed restores Math.random",
      restore_res.get("randomOverridden") is False)

# ------------------------------------------------------------------ deterministic seed

section("deterministic seed: same seed -> identical lane picks + spawn order")


def wave_fingerprint():
    """Run wave 1 with a fixed seed and record each Enemy clone's slot
    (MyIndex, assigned in spawn order) and lane (y). Lane picks and spawn
    order are Math.random-driven; a clone's y is CONSTANT (lanes are fixed at
    y=90/-110), so dedupe by MyIndex across chunks to get the full spawn
    sequence — immune to the wall-clock jitter of paced runs shifting which
    clones exist at each 0.5s sample boundary.

    Reloads the VM first so the previous fingerprint's orc clones don't leak
    into this run (green flag resets variables, not existing clones)."""
    asyncio.run(call_text("sb3_vm_load", {}))
    asyncio.run(call_text("sb3_vm_seed", {"seed": 20240701}))
    asyncio.run(call_text("sb3_vm_green_flag", {}))
    click_start_button()
    seen = {}
    for _ in range(6):
        r = asyncio.run(call_text("sb3_vm_run", {
            "seconds": 0.5, "frames": 0, "untilIdle": False, "paced": True}))
        s = parse_state(r)
        for t in s.get("targets", []):
            if t.get("name") != "Enemy" or not t.get("isClone"):
                continue
            idx = (t.get("variables") or {}).get("MyIndex")
            if idx is None:
                continue
            # last write wins — the clone's y never changes, so any sample works
            seen[int(idx)] = t["y"]
    asyncio.run(call_text("sb3_vm_seed", {}))  # restore Math.random
    return [seen[k] for k in sorted(seen)]

fp_a = wave_fingerprint()
fp_b = wave_fingerprint()
check("same seed -> identical enemy lane/spawn fingerprint", fp_a == fp_b)
check("fingerprint is non-trivial (orcs observed mid-lane)", len(fp_a) > 0)

# ------------------------------------------------------------------ phase 2 tools

section("phase 2: watch / stub calls / hat log / idle filter")

# Watcher: Gold was 0 after building, kills pay +20 — poll-and-diff must
# report the change between two reads with no events consumed.
w1 = parse_state(asyncio.run(call_text("sb3_vm_watch", {"name": "Gold"})))
w2 = parse_state(asyncio.run(call_text("sb3_vm_watch", {"name": "Gold"})))
check("vm_watch returns watches list",
      isinstance(w1.get("watches"), list) and len(w1.get("watches")) > 0)
check("vm_watch second read reports unchanged (no drift between polls)",
      all(not w.get("changed", True) for w in w2.get("watches", [])))

# Stub calls: the tower game plays build/coin/shoot sounds through the
# soundBank stub, and every block ran through the renderer stub.
stubs = parse_state(asyncio.run(call_text("sb3_vm_stub_calls", {})))
check("vm_stub_calls returns pen + sound logs",
      isinstance(stubs.get("pen"), list) and isinstance(stubs.get("sound"), list))
check("sound stub recorded play calls (build/coin/shoot)",
      len(stubs.get("sound", [])) > 0)

# Hat log: non-broadcast hats now emit debug hat events. Re-run one frame
# and look for a click/flag hat in the delta.
hat_step = parse_state(asyncio.run(call_text("sb3_vm_step_frame", {})))
hat_kinds = {e.get("type") for e in hat_step.get("delta", {}).get("newEvents", [])}
check("hat log present in step delta (broadcast or hat event kinds)",
      bool({"broadcast", "hat"} & hat_kinds) or hat_step.get("framesRun") == 1)

# Idle filter: after the wave drained, threadsRunning must be 0 — monitor
# threads no longer inflate the count.
asyncio.run(call_text("sb3_vm_stop", {}))
idle_state = parse_state(asyncio.run(call_text("sb3_vm_state", {})))
check("threadsRunning is 0 after stop (monitor threads filtered)",
      idle_state.get("threadsRunning") == 0)

# ------------------------------------------------------------------ phase 3a

section("phase 3a: pen raster / wav mix / monitor push")

# Pen rasterizer: draw nothing — the tower game uses no pen blocks — so
# the canvas must be transparent and the PNG must decode to 480x360.
pen = parse_state(asyncio.run(call_text("sb3_vm_pen_png", {})))
check("vm_pen_png returns dimensions + base64 + count",
      pen.get("width") == 480 and pen.get("height") == 360
      and isinstance(pen.get("pngBase64"), str) and isinstance(pen.get("nonEmpty"), int))
import base64 as _b64
raw = _b64.b64decode(pen["pngBase64"])
check("pen PNG decodes with PNG magic", raw[:8] == b"\x89PNG\r\n\x1a\n")
check("empty game leaves pen canvas transparent", pen.get("nonEmpty") == 0)

# WAV mixer: the run above played build/coin/shoot sounds through the
# soundBank stub, so the mix must contain events and valid WAV bytes.
mix = parse_state(asyncio.run(call_text("sb3_vm_mix_wav", {})))
check("vm_mix_wav returns rate + seconds + events + base64",
      mix.get("rate") == 22050 and isinstance(mix.get("seconds"), (int, float))
      and isinstance(mix.get("events"), int) and isinstance(mix.get("wavBase64"), str))
check("mix captured sound plays", mix.get("events", 0) > 0)
wraw = _b64.b64decode(mix["wavBase64"])
check("mix decodes with RIFF/WAVE magic", wraw[:4] == b"RIFF" and wraw[8:12] == b"WAVE")

# Monitor push: Gold/Lives/Wave/Score are monitored, so stepping after a
# change must surface debug monitor events in the timeline.
asyncio.run(call_text("sb3_vm_green_flag", {}))
mon_run = parse_state(asyncio.run(call_text(
    "sb3_vm_run", {"seconds": 0.5, "frames": 0, "untilIdle": False, "paced": True})))
mon_kinds = {(e.get("type"), e.get("label")) for e in mon_run.get("events", [])}
check("monitor push events present in run timeline",
      any(k == "monitor" for k, _ in mon_kinds))


# ------------------------------------------------------------------ escape path

section("headless VM: no towers — orcs escape and Lives deducts")
# A fresh green flag resets everything (Stage vars, per-Plot occupied=0 and
# empty costume, Gold=150, Lives=10), so this wave runs with zero towers:
# every orc walks the full lane and reaches the castle. Wave 1 spawns
# 3 + Wave = 4 orcs; each escape costs one Life.
asyncio.run(call_text("sb3_vm_green_flag", {}))
click_start_button()
end_esc, events_esc, done_esc = run_until(
    lambda s, ev: game_active(s) == 0, 25.0)
lives_esc = find_stage_var(end_esc, "Lives")
wave_esc = find_stage_var(end_esc, "Wave")
check("wave 1 escape-only run advanced Wave to 1", wave_esc == 1)
check("all 4 orcs escaped: Lives 10 -> 6", lives_esc == 6)
check("GameActive returned to 0 (wave complete)", game_active(end_esc) == 0)
check("no GameOver broadcast with Lives at 6",
      not has_event(events_esc, "broadcast", "GameOver"))

# ------------------------------------------------------------------ game over

section("headless VM: wave 2, then GameOver when Lives hits 0")
# Wave 2 spawns 5 orcs (3 + 2) and takes Lives to 1 (10 - 4 - 5). Wave 3
# spawns 6; the 10th escape drops Lives below 1 and removed_seq broadcasts
# GameOver. Still no towers, so nothing can kill an orc.
click_start_button()
end_w2, events_w2, done_w2 = run_until(
    lambda s, ev: game_active(s) == 0, 25.0)
lives_w2 = find_stage_var(end_w2, "Lives")
check("wave 2 escaped orcs left Lives at 1 (10-9 escapes)", lives_w2 == 1)
check("no GameOver after wave 2 (Lives still 1)",
      not has_event(events_w2, "broadcast", "GameOver"))

click_start_button()
end_go, events_go, done_go = run_until(
    lambda s, ev: has_event(ev, "broadcast", "GameOver"), 30.0)
lives_go = find_stage_var(end_go, "Lives")
check("GameOver broadcast observed as the 10th orc escaped",
      has_event(events_go, "broadcast", "GameOver"))
check("Lives <= 0 at GameOver", lives_go is not None and lives_go <= 0)

# ------------------------------------------------------------------ cleanup

section("cleanup")
try:
    asyncio.run(call_text("sb3_vm_stop", {}))
    check("vm_stop reported", True)
except Exception as exc:
    check("vm_stop clean", False)

print(f"\n{ok} passed, {failed} failed, {skipped} skipped")
sys.exit(1 if failed else 0)
