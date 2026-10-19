import json

import pytest

from agent_test.domains.execution.api import ExecutionError
from agent_test.infrastructure.mcp.vida import VidaMcpExecutor, VidaMcpSettings


def test_sse_reply_is_parsed():
    body = "data: " + json.dumps({"id": 2, "result": {"structuredContent": {"status": "answered", "answer": "42"}}})
    reply = VidaMcpExecutor._reply(VidaMcpExecutor._message_for(body, 2))
    assert reply.status == "answered"
    assert reply.answer == "42"


def test_plain_json_content_is_parsed():
    body = json.dumps({"id": 2, "result": {"content": [{"type": "text", "text": json.dumps({"status": "clarify", "detail": "需要范围"})}]}})
    reply = VidaMcpExecutor._reply(VidaMcpExecutor._message_for(body, 2))
    assert reply.status == "clarify"
    assert reply.detail == "需要范围"


def test_invalid_sse_is_stable_error():
    with pytest.raises(ExecutionError, match="invalid SSE"):
        VidaMcpExecutor._messages("data: not-json")


def test_settings_reject_empty_url():
    with pytest.raises(ValueError):
        VidaMcpExecutor(VidaMcpSettings(url="  "))
