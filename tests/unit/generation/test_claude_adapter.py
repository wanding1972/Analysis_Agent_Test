import json

import httpx2
import pytest
from anthropic import Anthropic

from agent_test.domains.generation.api import CandidateDesignError, DesignerRequest
from agent_test.infrastructure.ai.claude_designer import ClaudeCandidateDesigner, ClaudeDesignerSettings


def response(proposals=None, stop_reason="tool_use"):
    return {"id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture-model",
            "content": [{"type": "tool_use", "id": "tool_fixture", "name": "submit_candidates",
                         "input": {"proposals": proposals if proposals is not None else [
                             {"seed_case_id": "seed", "question": "Fixture paraphrase"}]}}],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_actual_sdk_request_response_contract_offline():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx2.Response(200, json=response())

    # MockTransport intercepts all requests; this is not a real API credential/call.
    with Anthropic(api_key="test-fixture-only", base_url="https://claude-fixture.invalid",
                   max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
        adapter = ClaudeCandidateDesigner(client, ClaudeDesignerSettings(model_id="fixture-model", max_tokens=37, timeout_seconds=10.0))
        batch = adapter.propose(DesignerRequest(seeds=[], paraphrase_count=1, max_candidates=1,
                                               prompt="Fixture candidate request"))
    assert batch.proposals[0].question == "Fixture paraphrase"
    assert len(captured) == 1 and captured[0]["max_tokens"] == 37
    assert captured[0]["tool_choice"] == {"type": "tool", "name": "submit_candidates"}
    schema = captured[0]["tools"][0]["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["$defs"]["QuestionProposal"]["properties"]) == {"seed_case_id", "question"}


@pytest.mark.parametrize("failure", ["quota", "extra_truth", "truncated", "wrong_tool", "multiple_tools", "http_error"])
def test_sdk_failures_have_stable_errors_and_no_raw_logs(failure, caplog):
    def handler(request):
        payload = response()
        if failure == "quota":
            payload = response([{"seed_case_id": "seed", "question": "q"}] * 2)
        elif failure == "extra_truth":
            payload["content"][0]["input"]["proposals"][0]["expected_metric"] = "private-fixture"
        elif failure == "truncated":
            payload["stop_reason"] = "max_tokens"
        elif failure == "wrong_tool":
            payload["content"][0]["name"] = "private-fixture"
        elif failure == "multiple_tools":
            payload["content"] *= 2
        else:
            return httpx2.Response(503, json={"type": "error", "error": {"type": "api_error", "message": "private-fixture"}})
        return httpx2.Response(200, json=payload)

    with Anthropic(api_key="test-fixture-only", base_url="https://claude-fixture.invalid",
                   max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
        adapter = ClaudeCandidateDesigner(client, ClaudeDesignerSettings(model_id="fixture-model", max_tokens=37, timeout_seconds=10.0))
        with pytest.raises(CandidateDesignError):
            adapter.propose(DesignerRequest(seeds=[], paraphrase_count=1, max_candidates=1, prompt="Fixture"))
    assert "Claude candidate generation failed" in caplog.text
    assert "private-fixture" not in caplog.text
