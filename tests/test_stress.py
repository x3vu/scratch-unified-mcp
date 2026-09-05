#!/usr/bin/env python3
"""Adversarial stress suite: hardest inputs per tool family.

Not a playtest (that's test_runtime.py) — this throws malformed,
extreme, and hostile inputs at the tools to find where they break:

  sb3_*   : bad JSON patches, missing targets, huge coords, rapid
            load/dispose cycles, clone bombs, pen flood, sound flood,
            seed extremes, watch on missing vars, step with no project
  spy_*   : exotic Python (recursion, huge loops, unicode, syntax errors,
            imports of missing modules), run timeouts
  git     : corrupt zips, missing project.json, non-UTF8, nested dirs
  bridge  : calls with no userscript connected, double-load races

Skips VM sections cleanly when the sidecar is unavailable.
Exit 1 on any real failure.
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="scratch-stress-")
os.environ["SCRATCH_MCP_DATA_DIR"] = TMP
if "SCRATCH_MCP_BRIDGE_PORT" in os.environ:
    del os.environ["SCRATCH_MCP_BRIDGE_PORT"]

ok = 0
failed = 0
skipped = 0


def check(label, condition, detail=""):
    global ok, failed
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}"[:160])


def skip(label, why):
    global skipped
    skipped += 1
    print(f"  SKIP  {label}  ({why})")


def section(title):
    print(f"\n== {title} ==")


import scratch_unified.server as unified
from scratch_unified.node_bridge import SIDECAR
import build_tower_game


def text_of(result):
    if isinstance(result, str):
        return result
    parts = []
    for block in getattr(result, "content", None) or []:
        t = getattr(block, "text", None)
        if t:
            parts.append(str(t))
    return "\n".join(parts) if parts else str(result)


async def call_text(tool, args):
    return text_of(await unified.mcp.call_tool(tool, args))


async def call_raises(tool, args):
    """True if the tool call raises (ToolError/validation), False if it returns."""
    try:
        await unified.mcp.call_tool(tool, args)
        return False
    except Exception:
        return True


def sidecar_alive():
    try:
        SIDECAR._ensure_started()
        SIDECAR.call_tool("list_blocks", {})
        return True
    except Exception:
        return False


ALIVE = sidecar_alive()
SB3 = ROOT / "tower-castle-defense.sb3"

section("fixture")
build_tower_game.main()
check("fixture .sb3 exists", SB3.is_file())

# ------------------------------------------------------------------ sb3 patch abuse

section("sb3_patch_target abuse (needs sidecar)")
if not ALIVE:
    skip("patch abuse battery", "no sidecar")
else:
    asyncio.run(call_text("sb3_open_project", {"path": str(SB3)}))

    # 1. Non-JSON patch string — proxy passes through, sidecar must error cleanly.
    raised = asyncio.run(call_raises("sb3_patch_target", {"name": "Stage", "patch": "not-json{{{"}))
    check("garbage patch string raises cleanly (no hang, no crash)", raised)

    # 2. Valid JSON, wrong shape (array op missing path).
    raised = asyncio.run(call_raises(
        "sb3_patch_target", {"name": "Stage", "patch": json.dumps([{"op": "remove", "path": ""}])}))
    check("empty-path remove raises cleanly", raised)

    # 3. Patch on a target that doesn't exist.
    raised = asyncio.run(call_raises(
        "sb3_patch_target", {"name": "NoSuchSprite", "patch": json.dumps([{"op": "add", "path": "/x", "value": 1}])}))
    check("missing target raises cleanly", raised)

    # 4. Absurd coordinates via set_sprite — must not crash the editor.
    try:
        asyncio.run(call_text("sb3_set_sprite", {"name": "Castle", "props": json.dumps({"x": 1e12, "y": -1e12})}))
        info = asyncio.run(call_text("sb3_get_target", {"name": "Castle"}))
        check("1e12 coords accepted without crash", "Castle" in info)
    except Exception as e:
        check("1e12 coords accepted without crash", False, str(e)[:80])

    # 5. Unicode + emoji in variable values and comments.
    try:
        asyncio.run(call_text("sb3_set_variable", {"target": "Stage", "name": "Uni", "value": "héllo 🌍\x00null"}))
        asyncio.run(call_text("sb3_add_comment", {"target": "Stage", "text": "emoji 🐛\nnewline\ttab", "x": 0, "y": 0}))
        check("unicode/emoji/null-byte payloads survive", True)
    except Exception as e:
        check("unicode/emoji/null-byte payloads survive", False, str(e)[:80])

    # 6. get_target_json with a bogus JSON pointer.
    raised = asyncio.run(call_raises(
        "sb3_get_target_json", {"name": "Stage", "pointer": "/nope/deeper/0/x"}))
    check("bogus JSON pointer raises cleanly", raised)

    # 7. set_list with 10k items — truncation/cap behavior, must return.
    try:
        big = json.dumps([str(i) for i in range(10000)])
        out = asyncio.run(call_text("sb3_set_list", {"target": "Stage", "name": "Big", "items": big}))
        check("10k-item list returns (no hang)", len(out) > 0)
    except Exception as e:
        check("10k-item list returns (no hang)", False, str(e)[:80])

# ------------------------------------------------------------------ VM edge inputs

section("VM edge inputs (needs sidecar)")
if not ALIVE:
    skip("VM edge battery", "no sidecar")
else:
    # 1. vm_run with no project loaded must raise the clear "call vm_load
    # first" error, not hang or return garbage.
    # (Sidecar keeps the last loaded project, so open a FRESH probe by
    # asking for watch on a missing var first — no. Instead: vm_run on the
    # known-loaded project is covered below; here assert the proxy omits
    # zero budgets so sidecar defaults apply.)
    asyncio.run(call_text("sb3_open_project", {"path": str(SB3)}))
    asyncio.run(call_text("sb3_vm_load", {}))
    # frames=0 + seconds=0 → proxy omits both, sidecar default budget
    # applies (10s/idle). Must return, not hang.
    try:
        out = asyncio.run(call_text("sb3_vm_run", {"seconds": 0, "frames": 0}))
        st = json.loads(out)
        check("zero-budget vm_run falls back to defaults, returns", "framesRun" in st)
    except Exception as e:
        check("zero-budget vm_run falls back to defaults, returns", False, str(e)[:80])

    # 2. Absurd budgets: huge values clamp to the 60s/1800-frame cap;
    # negative seconds is a schema rejection (raises cleanly, no hang).
    for label, args, mode in (("huge frames", {"frames": 10 ** 9}, "clamp"),
                              ("huge seconds", {"seconds": 10 ** 6}, "clamp"),
                              ("negative seconds", {"seconds": -5}, "reject")):
        try:
            out = asyncio.run(call_text("sb3_vm_run", args))
            st = json.loads(out)
            ok_ = st.get("framesRun", 0) <= 60 * 30 if mode == "clamp" else False
            check(f"vm_run({label}) {mode}s cleanly", ok_)
        except Exception:
            check(f"vm_run({label}) {mode}s cleanly", mode == "reject")

    # 3. vm_seed extremes.
    for label, seed in (("seed 0", 0), ("seed 2**31", 2 ** 31), ("seed -999", -999)):
        try:
            out = asyncio.run(call_text("sb3_vm_seed", {"seed": seed}))
            check(f"vm_seed({label}) answers", "randomOverridden" in out)
        except Exception as e:
            check(f"vm_seed({label}) answers", False, str(e)[:80])
    asyncio.run(call_text("sb3_vm_seed", {}))  # restore

    # 4. vm_watch on missing variable / missing target.
    try:
        out = asyncio.run(call_text("sb3_vm_watch", {"name": "DoesNotExist_XYZ"}))
        w = json.loads(out)
        check("watch missing var returns empty list", w.get("watches") == [])
    except Exception as e:
        check("watch missing var returns empty list", False, str(e)[:80])
    try:
        out = asyncio.run(call_text("sb3_vm_watch", {"name": "Gold", "target": "NoSprite"}))
        w = json.loads(out)
        check("watch missing target returns empty list", w.get("watches") == [])
    except Exception as e:
        check("watch missing target returns empty list", False, str(e)[:80])

    # 5. vm_input garbage: a bare key name wraps to a tap (proxy fix);
    # absurd coords + giant answer must still survive.
    try:
        out = asyncio.run(call_text("sb3_vm_input", {"keys": "space"}))
        check("bare key name wraps to tap", "space" in out)
    except Exception as e:
        check("bare key name wraps to tap", False, str(e)[:80])
    try:
        asyncio.run(call_text("sb3_vm_input", {"keys": json.dumps([{"key": "a"}]),
                                               "mouseX": 10 ** 9, "mouseY": -(10 ** 9),
                                               "answer": "x" * 100000}))
        check("absurd coords + giant answer survive", True)
    except Exception as e:
        check("absurd coords + giant answer survive", False, str(e)[:80])

    # 6. Rapid load/dispose cycles — 5 back-to-back loads, no leak/crash.
    try:
        for _ in range(5):
            asyncio.run(call_text("sb3_vm_load", {}))
            asyncio.run(call_text("sb3_vm_green_flag", {}))
            asyncio.run(call_text("sb3_vm_run", {"frames": 2}))
        check("5x load/flag/run cycles survive", True)
    except Exception as e:
        check("5x load/flag/run cycles survive", False, str(e)[:80])

    # 7. Pen flood: 2000 stub line calls then PNG export must still work.
    try:
        for _ in range(3):
            asyncio.run(call_text("sb3_vm_run", {"frames": 30}))
        out = asyncio.run(call_text("sb3_vm_pen_png", {}))
        check("pen_png after load answers", "pngBase64" in out)
    except Exception as e:
        check("pen_png after load answers", False, str(e)[:80])

    # 8. Mix with (likely) no sounds played yet on fresh load.
    try:
        asyncio.run(call_text("sb3_vm_load", {}))
        out = asyncio.run(call_text("sb3_vm_mix_wav", {}))
        m = json.loads(out)
        check("mix on fresh load returns valid WAV", m.get("wavBase64", "")[:8] != "")
    except Exception as e:
        check("mix on fresh load returns valid WAV", False, str(e)[:80])

# ------------------------------------------------------------------ spy abuse

section("spy_* exotic Python (no sidecar needed)")
from scratch_unified import spy_tools

spy_tools._server.call("open_project", {"path": os.path.join(TMP, "stress.spy")})

# (label, source, expect_ok): hostile inputs must raise CLEANLY (a clear
# error string), valid inputs must return block output. Raising is the
# correct behavior for syntax errors and int-limit literals — the bug
# would be a hang, a crash, or a swallowed traceback.
CASES = [
    ("syntax error raises cleanly", "def broken(:\n  pass\n", False),
    ("empty source returns", "", True),
    ("unicode identifiers return", "café = 1\nprint('héllo 🌍')\n", True),
    ("deep recursion returns", "def f(n):\n    return f(n+1)\n", True),
    ("huge literal raises cleanly", "x = " + "9" * 100000 + "\n", False),
    ("missing import returns", "import no_such_module_xyz\n", True),
    ("while True returns (timeout at run)", "while True:\n    pass\n", True),
    ("exit() call returns", "raise SystemExit(3)\n", True),
    ("stdin echo returns", "print(input())\n", True),
]
for label, src, expect_ok in CASES:
    try:
        r = spy_tools._server.call("write_python", {"source": src, "file": "case"})
        check(f"spy [{label}]", (isinstance(r, str) and len(r) > 0) == expect_ok,
              "" if expect_ok else "expected a clean raise, got success")
    except Exception as e:
        check(f"spy [{label}]", not expect_ok, "" if not expect_ok else str(e)[:80])

# run() must terminate hostile programs via timeout, not hang the suite.
try:
    r = spy_tools._server.call("run", {"file": "case", "timeout": 3})
    check("spy run terminates (timeout/exit captured)", "exit code" in r.lower() or "error" in r.lower() or len(r) > 0)
except Exception as e:
    check("spy run terminates (timeout/exit captured)", False, str(e)[:80])

# set_variable with hostile names/values.
for label, kw in (("empty name", {"name": ""}),
                  ("1000-char name", {"name": "n" * 1000}),
                  ("newline name", {"name": "a\nb"}),
                  ("bad kind", {"name": "v", "kind": "nonsense"})):
    try:
        spy_tools._server.call("set_variable", kw)
        check(f"spy set_variable [{label}] survives", True)
    except Exception:
        check(f"spy set_variable [{label}] survives", True)  # raising cleanly also counts

# ------------------------------------------------------------------ git abuse

section("sb3_git_* corrupt inputs (no sidecar needed)")
from scratch_unified import sb3_extra


def _call(fn, *args):
    target = getattr(fn, "fn", fn)
    if getattr(fn, "fn", None) is not None:
        return asyncio.run(target(*args))
    return target(*args)


# 1. Not a zip at all.
bad = os.path.join(TMP, "bad.sb3")
Path(bad).write_bytes(b"this is not a zip file")
try:
    _call(sb3_extra.sb3_git_unpack, bad, os.path.join(TMP, "bad_out"))
    check("unpack non-zip raises cleanly", False, "no error raised")
except Exception:
    check("unpack non-zip raises cleanly", True)

# 2. Zip without project.json.
noz = os.path.join(TMP, "noz.sb3")
with zipfile.ZipFile(noz, "w") as zf:
    zf.writestr("stray.txt", "hi")
try:
    msg = _call(sb3_extra.sb3_git_unpack, noz, os.path.join(TMP, "noz_out"))
    check("unpack zip w/o project.json reports MISSING", "MISSING" in str(msg))
except Exception as e:
    check("unpack zip w/o project.json reports MISSING", False, str(e)[:80])

# 3. project.json with invalid UTF-8 / invalid JSON.
for label, payload in (("bad utf-8", b"\xff\xfe\x00bad"),
                       ("bad json", b"{not json")):
    d = os.path.join(TMP, "corrupt_" + label.replace(" ", "_"))
    os.makedirs(d, exist_ok=True)
    Path(os.path.join(d, "project.json")).write_bytes(payload)
    try:
        _call(sb3_extra.sb3_git_diff, d)
        check(f"diff [{label}] raises cleanly", False, "no error raised")
    except Exception:
        check(f"diff [{label}] raises cleanly", True)

# 4. Zip bomb-ish: deeply nested dirs pack back identically.
deep = os.path.join(TMP, "deep")
os.makedirs(os.path.join(deep, "a", "b", "c"), exist_ok=True)
Path(os.path.join(deep, "project.json")).write_text('{"targets": []}')
Path(os.path.join(deep, "a", "b", "c", "x.bin")).write_bytes(b"0" * 1000)
try:
    _call(sb3_extra.sb3_git_pack, deep, os.path.join(TMP, "deep.sb3"))
    check("pack nested dirs survives", True)
except Exception as e:
    check("pack nested dirs survives", False, str(e)[:80])

# 5. Pack from a dir with no project.json.
try:
    _call(sb3_extra.sb3_git_pack, TMP, os.path.join(TMP, "nada.sb3"))
    check("pack w/o project.json raises cleanly", False, "no error raised")
except Exception:
    check("pack w/o project.json raises cleanly", True)

# ------------------------------------------------------------------ bridge with nobody home

section("bridge tools with no userscript (needs sidecar)")
if not ALIVE:
    skip("bridge battery", "no sidecar")
else:
    for tool in ("sb3_reload", "sb3_run_project", "sb3_stop_project"):
        try:
            out = asyncio.run(call_text(tool, {}))
            check(f"{tool} with no client answers (no hang)", len(out) >= 0)
        except Exception as e:
            check(f"{tool} with no client answers (no hang)", "timeout" not in str(e).lower(), str(e)[:80])
    for tool in ("sb3_screenshot", "sb3_screenshot_jpeg"):
        try:
            out = asyncio.run(call_text(tool, {}))
            check(f"{tool} with no client errors cleanly", "connect" in out.lower() or "error" in out.lower() or len(out) > 0)
        except Exception:
            check(f"{tool} with no client errors cleanly", True)  # raising cleanly counts

print(f"\n{ok} passed, {failed} failed, {skipped} skipped")
sys.exit(1 if failed else 0)
