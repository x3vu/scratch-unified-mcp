"""Lazy stdio proxy to the scratch4js Node MCP server (scratch4js sidecar).

The Node server (upstream-scratch4js/packages/scratch-mcp/src/index.js) owns
capabilities with no Python equivalent: JSON-Patch sb3 editing, the
scratch-vm block catalog/schema, the headless TurboWarp VM test loop, and the
TurboWarp Desktop live-reload bridge + screenshots.

Pattern: spawn `node index.js` once, speak MCP over stdio
(initialize -> notifications/initialized -> tools/call). The 44 sb3_*
tools live as typed functions in `typed_proxy.py` (FastMCP rejects **kwargs
tools); this module owns the subprocess transport. If Node/deps are missing,
every sb3_* tool raises a clear "sidecar unavailable" message instead of
breaking startup.

FRAMING NOTE (2026-09-05): the scratch4js workspace resolves
@modelcontextprotocol/sdk to >= 1.10, where the stdio transport is
NEWLINE-DELIMITED JSON (serializeMessage = JSON.stringify(msg) + '\n', and
the read buffer splits on '\n'). The legacy Content-Length framing silently
breaks the handshake: the sidecar tries to JSON.parse the header line and
never answers initialize, which deadlocks every sb3_* call. If the workspace
is ever pinned back to an SDK < 1.10 (Content-Length era), this transport
must flip back.
"""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

NODE_INDEX = Path(__file__).resolve().parent.parent / "upstream-scratch4js" / "packages" / "scratch-mcp" / "src" / "index.js"
TIMEOUT = 120.0
UNAVAILABLE = (
    "Node sidecar unavailable (need node >= 18 plus scratch4js workspace "
    "deps: run `pnpm install && pnpm build` in upstream-scratch4js). "
    "social_*, project_*, and spy_* tools are unaffected."
)


class NodeSidecar:
    """Single lazy Node subprocess speaking MCP over stdio."""

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._buf = b""

    def _fail(self, reason):
        raise RuntimeError("sb3_* tool failed: " + reason + " " + UNAVAILABLE)

    def _ensure_started(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        if shutil.which("node") is None:
            self._fail("node binary not found.")
        if not NODE_INDEX.is_file():
            self._fail("Node server missing at %s." % NODE_INDEX)
        try:
            self._proc = subprocess.Popen(
                ["node", str(NODE_INDEX)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._fail("could not spawn node: %s" % exc)
        try:
            # NOTE: the scratch4js sidecar only answers an initialize that
            # advertises the LEGACY protocol version (2024-11-05). Advertising
            # 2025-06-18 is silently ignored and every sb3_* call times out.
            self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "scratch-unified", "version": "1.0.0"},
            })
            self._notify("notifications/initialized")
        except Exception as exc:
            self._fail("Node server did not answer initialize: %s" % exc)

    def _write(self, obj):
        # Newline-delimited JSON-RPC framing (SDK >= 1.10). Each message is
        # exactly one JSON document terminated by a single '\n'.
        payload = json.dumps(obj).encode("utf-8") + b"\n"
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def _read_line(self):
        # Read via the raw fd with non-blocking os.read. select() on the
        # BufferedReader never reported the pipe readable even with a reply
        # waiting (observed 2026-09-05: select timed out for the full window
        # while os.read on the same fd returned the bytes instantly), so
        # select is NOT used here. The non-blocking poll gives a deadline that
        # actually fires when the sidecar is alive but silent, and a plain
        # blocking read can never reach its timeout checks.
        fd = self._proc.stdout.fileno()
        os.set_blocking(fd, False)
        deadline = time.monotonic() + TIMEOUT
        while b"\n" not in self._buf:
            if time.monotonic() >= deadline:
                self._proc = None
                raise RuntimeError(
                    "Node sidecar timeout after %.1fs waiting for a message" % TIMEOUT)
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                chunk = b""
            if chunk:
                self._buf += chunk
            elif self._proc.poll() is not None:
                self._proc = None
                raise RuntimeError("node stdout closed")
            else:
                time.sleep(0.01)
        line, self._buf = self._buf.split(b"\n", 1)
        line = line.rstrip(b"\r")
        if not line.strip():
            # Blank keep-alive line: skip and wait for the next real message.
            return self._read_line()
        return json.loads(line.decode("utf-8"))

    def _rpc(self, method, params=None):
        with self._lock:
            mid = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
            while True:
                msg = self._read_line()
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"]))
                    return msg.get("result")
                # ignore async notifications/log messages

    def _notify(self, method):
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method})

    def call_tool(self, name, arguments):
        self._ensure_started()
        try:
            result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        except Exception as exc:
            self._proc = None
            raise RuntimeError("Node sidecar call %s failed: %s" % (name, exc))
        if isinstance(result, dict) and result.get("isError"):
            texts = [b.get("text", "") for b in result.get("content", []) if isinstance(b, dict)]
            raise RuntimeError("Node tool %s error: %s" % (name, " ".join(texts)[:2000]))
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            return "\n".join(str(b.get("text", b)) for b in result["content"])
        # Bumped from 8000 to 50000 chars so long event timelines from
        # sb3_vm_state / sb3_vm_run don't get silently clipped. Append a
        # visible marker if we did clip so harnesses can detect it.
        s = json.dumps(result)
        if len(s) > 50000:
            return s[:50000] + "\n... [truncated at 50000 chars; full result not returned]"
        return s


SIDECAR = NodeSidecar()


def register_sb3_tools(mcp):
    """Register the 44 typed sb3_* proxy tools on the FastMCP app."""
    from .typed_proxy import SB3_TOOL_DEFS

    for fn in SB3_TOOL_DEFS:
        mcp.tool(fn)
