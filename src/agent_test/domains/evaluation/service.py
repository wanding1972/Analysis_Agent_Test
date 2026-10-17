import logging

from pydantic import ValidationError

from agent_test.domains.rules.api import ApprovalStatus, RuleStatus

from .answer import evaluate_answer
from .checks import blocked, layer_result, reduce_status
from .evidence import evaluate_evidence
from .models import CheckResult, EvaluationPolicy, EvaluationRequest, TestResult
from .plan import evaluate_plan
from .ports import EvaluationConfigError, EvaluationPolicySource, ReferenceEvidenceReader
from .semantic import evaluate_semantic, expected_case


logger = logging.getLogger(__name__)


def load_policy(source: EvaluationPolicySource) -> EvaluationPolicy:
    try:
        return EvaluationPolicy.model_validate(source.read())
    except ValidationError as error:
        logger.error("Evaluation policy schema validation failed")
        raise EvaluationConfigError("Invalid evaluation policy schema") from error


def evaluate(request: EvaluationRequest, reference_reader: ReferenceEvidenceReader | None = None) -> TestResult:
    request = EvaluationRequest.model_validate(request.model_dump(mode="json"))
    reason = _context_error(request)
    layers = []
    for name, check in (
        ("semantic", lambda: evaluate_semantic(request)),
        ("plan", lambda: evaluate_plan(request)),
        ("evidence", lambda: evaluate_evidence(request, reference_reader)),
        ("answer", lambda: evaluate_answer(request)),
    ):
        if reason is not None:
            checks = [blocked(f"{name}.context", reason)]
        elif expected_case(request).expected_behavior not in getattr(request.policy, name).behaviors:
            checks = [CheckResult(check_id=f"{name}.applicability", status=RuleStatus.SKIPPED, reason="not_applicable")]
        else:
            checks = check()
        layers.append(layer_result(name, checks, request.policy))
    return TestResult(case_id=request.test_case.case_id, snapshot_id=request.snapshot_id,
                      status=reduce_status([item.status for item in layers], request.policy), layers=layers)


def _context_error(request):
    if request.policy.approval != ApprovalStatus.APPROVED:
        return "policy_not_approved"
    if request.observation.case_id != request.test_case.case_id:
        return "case_mismatch"
    if request.observation.snapshot_id != request.snapshot_id:
        return "snapshot_mismatch"
    baseline = request.golden_baseline
    if baseline is not None and (baseline.snapshot_id != request.snapshot_id or baseline.question_id != request.question_id):
        return "golden_context_mismatch"
    return None
