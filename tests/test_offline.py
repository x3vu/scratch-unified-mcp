#!/usr/bin/env python3
"""Offline tests for the unified Scratch MCP (no network, no credentials).

Covers: merged tool surface, upstream session-registry parity, spy
blocks<->Python round trip, sb3 git unpack/pack/diff, sidecar-graceful
failure, unknown-tool errors.
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import zlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="scratch-unified-test-")
os.environ["SCRATCH_MCP_DATA_DIR"] = TMP

B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

ok = 0
failed = 0


def check(label, condition):
    global ok, failed
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def section(title):
    print(f"\n== {title} ==")


def b62_encode(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n, 62)
        out = B62[r] + out
    return out or "0"


def session_id(username, *, uid=12345, ts=1700000000):
    payload = zlib.compress(json.dumps({
        "username": username,
        "_auth_user_id": str(uid),
        "token": f"tok-{username}",
        "_language": "en",
    }).encode())
    p1 = "." + base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{p1}:{b62_encode(ts)}:sig"


import scratch_unified.server as unified
from scratch_unified.vendor_uu import social, store, utils


def reset():
    utils.SESSIONS.clear()
    utils.PERSISTED.clear()
    utils._set_active(None)


section("merged tool surface")
tools = asyncio.run(unified.mcp.list_tools())
names = sorted(t.name for t in tools)
check("total tools >= 100", len(names) >= 100)
for prefix, minimum in (("social_", 20), ("project_", 18), ("spy_", 14), ("sb3_", 44)):
    n = sum(1 for x in names if x.startswith(prefix))
    check(f"{prefix} tools >= {minimum} (got {n})", n >= minimum)
check("no name collisions", len(names) == len(set(names)))
for required in ("project_new", "project_build", "sb3_patch_target",
                 "sb3_vm_run", "spy_write_python", "sb3_git_unpack",
                 "sb3_cloud_get_vars", "social_connect_session"):
    check(f"tool present: {required}", required in names)

section("offline session registry parity (upstream behavior)")
reset()
out = social.social_list_sessions()
check("list_sessions works empty", out["sessions"] == [] and out["active"] is None)
first = social.social_connect_session(scratch_session_id=session_id("alice"))
check("first login names the user", "alice" in first)
social.social_connect_session(scratch_session_id=session_id("bob", uid=999))
check("second login does not steal focus", utils.ACTIVE == "alice")
reset()
utils._restore()
check("sessions restore across restart", set(utils.SESSIONS) == {"alice", "bob"})
check("restored session usable offline", utils.active_ses().xtoken == "tok-alice")
path = store.session_file()
check("no password stored", "password" not in path.read_text().lower())
store.clear()
reset()
utils._restore()
check("missing store restores empty", utils.SESSIONS == {})

section("spy blocks<->Python round trip")
from scratch_unified import spy_tools

spy_tools._server.call("open_project", {"path": os.path.join(TMP, "t.spy")})
built = spy_tools._server.call("write_python", {
    "source": "print('hi from unified')\nfor i in range(3):\n    print(i)\n",
    "file": "mcpdemo",
})
check("write_python builds blocks", "blocks" in built)
code = spy_tools._server.call("read_code", {"file": "mcpdemo"})
check("read_code keeps the program", "hi from unified" in code)
outline = spy_tools._server.call("read_blocks", {"file": "mcpdemo"})
check("read_blocks shows green-flag script", "green flag" in outline.lower())
check("project_overview lists the tab",
      "mcpdemo" in spy_tools._server.call("project_overview", {}))
ran = spy_tools._server.call("run", {"file": "mcpdemo", "timeout": 15})
check("run executes and prints", "hi from unified" in ran and "exit code 0" in ran)
bad = spy_tools._spy.MCPServer().handle(
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "nope", "arguments": {}}})
check("unknown tool reports error", bad["result"].get("isError") is True)
by_name = {t.name: t for t in tools}
check("spy_write_python schema requires source",
      "source" in (by_name["spy_write_python"].parameters.get("required", [])))

section("sb3 git unpack/pack/diff (pure Python)")
from scratch_unified import sb3_extra

sb3 = os.path.join(TMP, "demo.sb3")
proj = {"targets": [{"name": "Stage", "blocks": {}, "costumes": [],
                     "sounds": [], "variables": {}}],
        "meta": {"semver": "3.0.0"}}
with zipfile.ZipFile(sb3, "w") as zf:
    zf.writestr("project.json", json.dumps(proj))
    zf.writestr("cd21514d0531fdadf14cbffaec5e775_Placeholder.png", b"\x89PNG\r\n\x1a\n")
unpacked = os.path.join(TMP, "unpacked")
msg = asyncio.run(sb3_extra.sb3_git_unpack.fn(sb3, unpacked)) \
    if hasattr(sb3_extra.sb3_git_unpack, "fn") else sb3_extra.sb3_git_unpack(sb3, unpacked)
check("unpack reports files", "2 files" in str(msg))
diff = sb3_extra.sb3_git_diff(unpacked) \
    if not hasattr(sb3_extra.sb3_git_diff, "fn") else asyncio.run(sb3_extra.sb3_git_diff.fn(unpacked))
check("diff summarises Stage", "Stage" in str(diff))
repacked = os.path.join(TMP, "repacked.sb3")
msg2 = sb3_extra.sb3_git_pack(unpacked, repacked) \
    if not hasattr(sb3_extra.sb3_git_pack, "fn") else asyncio.run(sb3_extra.sb3_git_pack.fn(unpacked, repacked))
check("pack rebuilds sb3", os.path.exists(repacked) and "Packed" in str(msg2))

section("toolchain + sidecar graceful degradation")
from scratch_unified.vendor_uu import projects

report = projects.project_check_toolchain()
check("check_toolchain never raises", "ready" in report)
from scratch_unified.node_bridge import SIDECAR, UNAVAILABLE  # noqa

if SIDECAR._proc is None:
    try:
        SIDECAR.call_tool("project_info", {})
        check("sidecar proxies when Node deps installed", True)
    except RuntimeError as exc:
        check("sidecar degrades with clear message", "Node sidecar" in str(exc) or "sidecar" in str(exc).lower()
              or "node" in str(exc).lower())
else:
    check("sidecar already running", True)
check("UNAVAILABLE mentions unaffected families", "spy_*" in UNAVAILABLE)

print(f"\n{ok} passed, {failed} failed")
sys.exit(1 if failed else 0)
