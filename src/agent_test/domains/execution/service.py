"""Deterministic orchestration of Agent calls and observation capture."""

import logging

from pydantic import ValidationError

from .models import ExecutionBatch, ExecutionObservation, ExecutionRequest
from .ports import AgentExecutor, ExecutionError


logger = logging.getLogger(__name__)


def execute(request: ExecutionRequest, executor: AgentExecutor) -> ExecutionBatch:
    """Run cases in input order, retaining stable observations and error codes."""
    try:
        request = ExecutionRequest.model_validate(request.model_dump(mode="json"))
    except ValidationError as error:
        logger.error("Execution request schema validation failed")
        raise ValueError("Invalid execution request") from error

    if len(request.cases) > request.max_cases:
        return ExecutionBatch(status="blocked", observations=[], errors=["case_limit_exceeded"], truncated=True)

    observations: list[ExecutionObservation] = []
    errors: list[str] = []
    for case in request.cases:
        snapshot_id = f"{request.run_id}:{case.case_id}"
        try:
            reply = executor.ask(case.question, timeout_seconds=request.timeout_seconds)
            observations.append(ExecutionObservation(
                run_id=request.run_id, case_id=case.case_id, question=case.question,
                snapshot_id=snapshot_id, status=reply.status, answer=reply.answer,
                detail=reply.detail,
            ))
        except ExecutionError:
            logger.error("Agent execution failed for case")
            errors.append("agent_execution_failed")
            observations.append(ExecutionObservation(
                run_id=request.run_id, case_id=case.case_id, question=case.question,
                snapshot_id=snapshot_id, status="error", detail="agent_execution_failed",
            ))

    status = "ready" if not errors else "partial" if observations else "blocked"
    return ExecutionBatch(status=status, observations=observations, errors=list(dict.fromkeys(errors)), truncated=False)
