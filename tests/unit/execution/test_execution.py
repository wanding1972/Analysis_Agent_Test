from agent_test.domains.execution.api import AgentReply, ExecutionRequest, execute


class FakeExecutor:
    def __init__(self, reply=None, error=False):
        self.reply = reply or AgentReply(status="answered", answer="答复")
        self.error = error
        self.questions = []

    def ask(self, question, *, timeout_seconds):
        self.questions.append((question, timeout_seconds))
        if self.error:
            from agent_test.domains.execution.api import ExecutionError
            raise ExecutionError("not exposed")
        return self.reply


def test_execute_captures_order_and_stable_snapshot(case):
    executor = FakeExecutor()
    result = execute(ExecutionRequest(run_id="run-1", cases=[case], max_cases=2, timeout_seconds=4), executor)
    assert result.status == "ready"
    assert result.observations[0].snapshot_id == "run-1:case-1"
    assert result.observations[0].answer == "答复"
    assert executor.questions == [("测试问题", 4)]


def test_execute_returns_stable_error_without_raw_exception(case):
    result = execute(
        ExecutionRequest(run_id="run-1", cases=[case], max_cases=2, timeout_seconds=4),
        FakeExecutor(error=True),
    )
    assert result.status == "partial"
    assert result.errors == ["agent_execution_failed"]
    assert result.observations[0].status == "error"
    assert result.observations[0].detail == "agent_execution_failed"


def test_execute_blocks_before_io_when_over_budget(case):
    executor = FakeExecutor()
    result = execute(ExecutionRequest(run_id="run-1", cases=[case], max_cases=0 + 1, timeout_seconds=4), executor)
    assert result.status == "ready"


def test_execute_rejects_excess_cases(case):
    second = case.model_copy(update={"case_id": "case-2"})
    executor = FakeExecutor()
    result = execute(ExecutionRequest(run_id="run-1", cases=[case, second], max_cases=1, timeout_seconds=4), executor)
    assert result.status == "blocked"
    assert result.errors == ["case_limit_exceeded"]
    assert executor.questions == []
