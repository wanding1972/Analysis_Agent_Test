"""Opt-in end-to-end tests against a real VIDA MCP Agent."""

import os

import pytest

from agent_test.domains.canonical.api import CanonicalTestCase, ExpectedBehavior
from agent_test.domains.execution.api import ExecutionRequest, execute
from agent_test.infrastructure.mcp.vida import VidaMcpExecutor, VidaMcpSettings


MCP_URL = os.getenv("ANALYSIS_AGENT_MCP_URL")


@pytest.mark.live
@pytest.mark.skipif(not MCP_URL, reason="set ANALYSIS_AGENT_MCP_URL to run live MCP E2E")
def test_real_vida_agent_end_to_end():
    question = os.getenv("ANALYSIS_AGENT_LIVE_QUESTION", "大众品牌今年的总销量是多少？")
    case = CanonicalTestCase(
        case_id="live-vida-001", question=question, expected_behavior=ExpectedBehavior.ANSWER,
        metric=None, scope=None, grain=None, dimensions=[], time=None,
        filters=[], relations=[], set_operations=[], operation=None,
        steps=[], step_dependencies=[],
    )
    batch = execute(
        ExecutionRequest(run_id="live-vida", cases=[case], max_cases=1, timeout_seconds=60),
        VidaMcpExecutor(VidaMcpSettings(url=MCP_URL)),
    )
    assert batch.status == "ready"
    assert len(batch.observations) == 1
    observation = batch.observations[0]
    assert observation.status == "answered"
    assert observation.answer
    assert observation.snapshot_id == "live-vida:live-vida-001"
