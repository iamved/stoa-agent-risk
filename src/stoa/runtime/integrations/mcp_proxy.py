"""An MCP stdio proxy that records tool activity and applies the policy.

``stoa runtime mcp-proxy --upstream "python server.py"`` starts the upstream
MCP server as a subprocess and relays newline-delimited JSON-RPC between
the client on this process's stdin/stdout and the server. Two methods are
watched:

- ``tools/list``: the tool names the server advertises are recorded once
  (an ``action``-free ``agent_run`` span with ``attrs.tools_advertised``)
  and compared with the registry's tool list for the agent; tools the scan
  never listed get the ``undeclared_tool`` flag when they are later called.
- ``tools/call``: an ``action`` span per call, named after the tool, with
  the policy evaluated before the request is forwarded. An enforced deny is
  answered with a JSON-RPC error and never reaches the server.

Streamable-HTTP transport is not proxied here; stdio is the transport local
agents use. Nothing in this module imports the ``mcp`` package.
"""

from __future__ import annotations

import contextvars
import json
import shlex
import subprocess
import sys
import threading
from contextlib import ExitStack

from .. import _Late, _apply_policy, _raise_if_denied, _schema_hash, _state, stoa_span
from ..policy import StoaDenied


class McpProxy:
    def __init__(self, upstream: str | list[str], *, agent_id: str | None = None, side_effects: dict[str, str] | None = None, limit_fields: dict[str, str] | None = None, currency: str = "USD") -> None:
        self.upstream = upstream
        self.agent_id = agent_id
        self.side_effects = side_effects or {}
        self.limit_fields = limit_fields or {}
        self.currency = currency
        self.tools_advertised: list[str] = []
        self._pending: dict = {}  # request id -> (ExitStack, tool)
        self._lock = threading.Lock()

    # --- framing ---------------------------------------------------------------

    @staticmethod
    def _parse(line: bytes):
        try:
            message = json.loads(line)
            return message if isinstance(message, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # --- client -> server ------------------------------------------------------

    def on_request(self, message: dict) -> dict | None:
        """Inspect a client message. Returns a response to send back to the
        client instead of forwarding (an enforced deny), or None to forward."""
        method = message.get("method")
        if method != "tools/call":
            return None
        params = message.get("params") or {}
        tool = str(params.get("name") or "tool")
        values = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        side_effect = self.side_effects.get(tool, "write")
        limit_field = self.limit_fields.get(tool)
        amount = values.get(limit_field) if limit_field else None
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            amount = None
        late = _Late(attrs={"side_effect": side_effect, "args_schema_hash": _schema_hash(values), "transport": "mcp_stdio"})
        approval = _apply_policy(late, tool, values, side_effect, amount, None)
        # Each call's span lives in its own copied context, so entering it here
        # and closing it on the reader thread leaves neither thread's context
        # changed and the span's own reset succeeds.
        ctx = contextvars.copy_context()
        stack = ExitStack()
        try:
            ctx.run(stack.enter_context, stoa_span("action", agent_id=self.agent_id, tool=tool, amount=amount, currency=self.currency, approval_span_id=approval, _late=late))
            _raise_if_denied(late)
        except StoaDenied as exc:
            ctx.run(stack.__exit__, type(exc), exc, exc.__traceback__)
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32000, "message": str(exc), "data": {"rule_id": exc.rule_id}}}
        except Exception:  # noqa: BLE001
            ctx.run(stack.close)
            return None
        with self._lock:
            self._pending[message.get("id")] = (stack, ctx)
        return None

    # --- server -> client ------------------------------------------------------

    def on_response(self, message: dict) -> None:
        if "result" in message and isinstance(message["result"], dict) and isinstance(message["result"].get("tools"), list):
            names = [str(t.get("name")) for t in message["result"]["tools"] if isinstance(t, dict) and t.get("name")]
            if names and names != self.tools_advertised:
                self.tools_advertised = names
                self._record_advertised(names)
        with self._lock:
            entry = self._pending.pop(message.get("id"), None)
        if entry is None:
            return
        stack, ctx = entry
        error = message.get("error") or (message.get("result") or {}).get("isError")
        try:
            if error:
                exc = RuntimeError("mcp tool error")
                ctx.run(stack.__exit__, RuntimeError, exc, None)
            else:
                ctx.run(stack.close)
        except BaseException:  # noqa: BLE001
            pass

    def _record_advertised(self, names: list[str]) -> None:
        try:
            facts = _state.registry.for_agent(self.agent_id or _state.agent_id)
            undeclared = sorted(n for n in names if facts and facts.tools and n not in facts.tools)
            late = _Late(attrs={"tools_advertised": ",".join(names), "tools_undeclared": ",".join(undeclared), "transport": "mcp_stdio"})
            with stoa_span("agent_run", agent_id=self.agent_id, _late=late):
                pass
        except Exception:  # noqa: BLE001
            pass

    # --- run -------------------------------------------------------------------

    def run(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        command = self.upstream if isinstance(self.upstream, list) else shlex.split(self.upstream)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        assert process.stdin and process.stdout
        write_lock = threading.Lock()

        def to_client(payload: bytes) -> None:
            with write_lock:
                stdout.write(payload)
                stdout.flush()

        def pump_server() -> None:
            for line in process.stdout:
                message = self._parse(line)
                if message is not None:
                    self.on_response(message)
                to_client(line)

        thread = threading.Thread(target=pump_server, daemon=True)
        thread.start()
        try:
            for line in stdin:
                message = self._parse(line)
                reply = self.on_request(message) if message is not None else None
                if reply is not None:
                    to_client((json.dumps(reply, separators=(",", ":")) + "\n").encode("utf-8"))
                    continue
                process.stdin.write(line if line.endswith(b"\n") else line + b"\n")
                process.stdin.flush()
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.wait(timeout=5)
            thread.join(timeout=5)
            # Calls the server never answered are closed as errors, so no span is left open.
            with self._lock:
                orphans, self._pending = list(self._pending.values()), {}
            for stack, ctx in orphans:
                try:
                    ctx.run(stack.__exit__, RuntimeError, RuntimeError("no response from mcp server"), None)
                except BaseException:  # noqa: BLE001
                    pass
        return process.returncode or 0
