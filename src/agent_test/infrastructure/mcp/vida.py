"""Stdlib MCP adapter for the VIDA ``ask`` tool.

The adapter follows the protocol used by the supplied verify_mcp.py reference:
initialize, retain Mcp-Session-Id, then tools/call ask. It does not log bodies.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from agent_test.domains.execution.api import AgentReply
from agent_test.domains.execution.ports import AgentExecutor, ExecutionError


@dataclass(frozen=True)
class VidaMcpSettings:
    url: str
    protocol_version: str = "2025-03-26"
    client_name: str = "analysis-agent-test"
    client_version: str = "0.1.0"


class VidaMcpExecutor(AgentExecutor):
    def __init__(self, settings: VidaMcpSettings):
        if not settings.url.strip():
            raise ValueError("MCP URL must not be empty")
        self._settings = settings

    def _post(self, payload: dict[str, Any], timeout_seconds: int, session_id: str | None = None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(
            self._settings.url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.headers.get("Mcp-Session-Id"), response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ExecutionError("MCP transport failed") from error

    @staticmethod
    def _messages(body: str) -> list[dict[str, Any]]:
        messages = []
        for line in body.splitlines():
            if line.startswith("data:") and line[5:].strip():
                try:
                    messages.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError as error:
                    raise ExecutionError("MCP returned invalid SSE JSON") from error
        if not messages and body.strip().startswith("{"):
            try:
                messages.append(json.loads(body))
            except json.JSONDecodeError as error:
                raise ExecutionError("MCP returned invalid JSON") from error
        return messages

    @staticmethod
    def _message_for(body: str, message_id: int) -> dict[str, Any]:
        message = next((item for item in VidaMcpExecutor._messages(body) if item.get("id") == message_id), None)
        if message is None or "error" in message:
            raise ExecutionError("MCP response missing or reports an error")
        return message

    @staticmethod
    def _reply(message: dict[str, Any]) -> AgentReply:
        result = message.get("result", {})
        raw: Any = result.get("structuredContent")
        if raw is None:
            content = result.get("content", [])
            if content and content[0].get("type") == "text":
                try:
                    raw = json.loads(content[0]["text"])
                except (KeyError, TypeError, json.JSONDecodeError) as error:
                    raise ExecutionError("MCP ask returned non-JSON content") from error
        if not isinstance(raw, dict):
            raise ExecutionError("MCP ask returned an invalid result")
        try:
            return AgentReply(status=raw["status"], answer=raw.get("answer"), detail=raw.get("detail"))
        except (KeyError, TypeError, ValueError) as error:
            raise ExecutionError("MCP ask returned an invalid Agent reply") from error

    def ask(self, question: str, *, timeout_seconds: int) -> AgentReply:
        init = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": self._settings.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self._settings.client_name,
                    "version": self._settings.client_version,
                },
            },
        }
        session_id, body = self._post(init, timeout_seconds)
        self._message_for(body, 1)
        call = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "ask", "arguments": {"question": question}},
        }
        _session, body = self._post(call, timeout_seconds, session_id=session_id)
        return self._reply(self._message_for(body, 2))
