"""MCP Streamable HTTP client with zero third-party dependencies.

Implements just enough of the Model Context Protocol (2025-06-18 transport spec)
to talk to McDonald's China MCP server over ``urllib`` from the standard library.

Why zero dependencies?
    A judge / passerby can ``git clone`` this repo and run it immediately.  No
    ``pip install``, no SDK version drift, no network needed beyond the MCP
    endpoint itself.  Every byte here is stdlib Python 3.9+.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from urllib import request, error

__all__ = ["McpError", "McpClient"]

DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """Raised when the MCP server returns an error or an unusable payload."""

    def __init__(self, message: str, *, code: Optional[int] = None,
                 data: Any = None) -> None:
        self.code = code
        self.data = data
        super().__init__(message)


class McpClient:
    """Minimal but spec-correct Streamable HTTP MCP client.

    Handles both response shapes the spec allows:
      * ``application/json``      -> plain JSON-RPC response
      * ``text/event-stream``     -> SSE frames, we stitch the final JSON-RPC body

    Also carries the ``Mcp-Session-Id`` the server may hand back after
    ``initialize`` so subsequent calls reuse the same session.
    """

    def __init__(self, token: str, endpoint: str = DEFAULT_ENDPOINT,
                 timeout: float = 30.0) -> None:
        if not token or not str(token).strip():
            raise ValueError("MCP token is required (get one at https://open.mcd.cn/mcp)")
        self.token = str(token).strip()
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._request_id = 0
        self._initialized = False
        self._server_info: Dict[str, Any] = {}

    # ---------------------------------------------------------------- helpers

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    @staticmethod
    def _parse_sse(raw: str) -> Dict[str, Any]:
        """Extract the JSON-RPC object(s) out of a raw SSE stream."""
        result: Optional[Dict[str, Any]] = None
        for line in raw.splitlines():
            line = line.rstrip("\r")
            # `event:` lines are noise for us; only data lines carry payloads.
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload in ("", "[DONE]"):
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and ("id" in obj or "method" in obj):
                    # Prefer the message carrying a `result` or `error`.
                    if "result" in obj or "error" in obj:
                        result = obj
                    elif result is None:
                        result = obj
        if result is None:
            raise McpError("SSE stream contained no JSON-RPC message")
        return result

    # ----------------------------------------------------------------- low IO

    def _post(self, payload: Dict[str, Any],
              expect_response: bool = True) -> Optional[Dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                if not expect_response:
                    return None
                if resp.status == 202:  # Accepted, no body (notifications)
                    return None
                raw = resp.read().decode("utf-8", errors="replace")
                ctype = (resp.headers.get("Content-Type") or "").lower()
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 401:
                raise McpError(
                    "401 Unauthorized: MCP token is invalid or expired", code=401
                ) from exc
            if exc.code == 429:
                raise McpError(
                    "429 Too Many Requests: token is capped at 600 calls/minute, "
                    "slow down", code=429
                ) from exc
            raise McpError("HTTP %s: %s" % (exc.code, detail[:400]),
                           code=exc.code) from exc
        except error.URLError as exc:
            raise McpError("Network unreachable (%s)" % exc.reason) from exc

        if not raw.strip():
            return None
        if "text/event-stream" in ctype:
            return self._parse_sse(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return self._parse_sse(raw)

    @staticmethod
    def _unwrap(message: Dict[str, Any]) -> Any:
        if "error" in message and message["error"] is not None:
            err = message["error"]
            raise McpError(
                "MCP error %s: %s" % (err.get("code"), err.get("message")),
                code=err.get("code"), data=err.get("data"),
            )
        return message.get("result")

    # ------------------------------------------------------------------- API

    def initialize(self) -> Dict[str, Any]:
        """Perform the MCP handshake (idempotent)."""
        if self._initialized:
            return self._server_info
        resp = self._post({
            "jsonrpc": JSONRPC_VERSION,
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-expiry-ledger", "version": "1.0.0"},
            },
        })
        if resp:
            self._server_info = self._unwrap(resp) or {}
            # notify/initialized is fire-and-forget
            self._post({
                "jsonrpc": JSONRPC_VERSION,
                "method": "notifications/initialized",
            }, expect_response=True)
        self._initialized = True
        return self._server_info

    def list_tools(self) -> List[Dict[str, Any]]:
        self.initialize()
        resp = self._post({
            "jsonrpc": JSONRPC_VERSION,
            "id": self._next_id(),
            "method": "tools/list",
        })
        return (self._unwrap(resp) or {}).get("tools", [])

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                  safe: bool = False) -> Any:
        """Call a tool and return its structured payload.

        Parameters
        ----------
        name:
            Tool name exactly as advertised by ``tools/list``.
        arguments:
            Tool arguments. Ignored (kept empty) when the tool takes no input.
        safe:
            When True, network/runtime failures return ``None`` instead of
            raising, so one dead endpoint can never abort a whole ledger scan.
        """
        self.initialize()
        params: Dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        try:
            resp = self._post({
                "jsonrpc": JSONRPC_VERSION,
                "id": self._next_id(),
                "method": "tools/call",
                "params": params,
            })
        except McpError:
            if safe:
                return None
            raise
        except Exception:  # noqa: BLE001 - `safe` must swallow everything
            if safe:
                return None
            raise
        if not resp:
            return None
        try:
            result = self._unwrap(resp)
        except McpError:
            if safe:
                return None
            raise
        content = (result or {}).get("content") if isinstance(result, dict) else None
        return self._decode_content(content) if content is not None else result

    @staticmethod
    def _decode_content(content: Any) -> Any:
        """Tool results come wrapped in content blocks; peel them open."""
        if isinstance(content, list):
            blocks = []
            for block in content:
                if not isinstance(block, dict):
                    blocks.append(block)
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                    try:
                        blocks.append(json.loads(text))
                    except json.JSONDecodeError:
                        blocks.append(text)
                else:
                    blocks.append(block)
            return blocks[0] if len(blocks) == 1 else blocks
        return content

    # -------------------------------------------------------------- utilities

    def ping(self) -> Dict[str, Any]:
        """Cheap liveness check that also reports which tools are reachable."""
        tools = self.list_tools()
        return {
            "endpoint": self.endpoint,
            "session": bool(self.session_id),
            "server": (self._server_info or {}).get("serverInfo", {}).get("name"),
            "tool_count": len(tools),
            "tools": [t.get("name") for t in tools],
        }
