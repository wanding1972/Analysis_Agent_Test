from agent_test.domains.rules.api import RuleStatus

from .checks import blocked, compare, select_fields, select_path
from .models import CheckResult
from .semantic import expected_case


def evaluate_answer(request):
    answer = request.observation.answer
    if answer is None:
        return [blocked("answer.input", "missing_answer")]
    checks = []
    for check in request.policy.answer.checks:
        if expected_case(request).expected_behavior not in check.behaviors:
            checks.append(CheckResult(check_id=f"answer.{check.kind}", status=RuleStatus.SKIPPED, reason="not_applicable"))
            continue
        checks.extend(_CHECKS[check.kind](request, check))
    return checks


def _behavior(request, check):
    return [compare("answer.behavior", expected_case(request).expected_behavior.value,
                    request.observation.answer.behavior.value, check.comparison, request.policy)]


def _complete(request, check):
    actual = request.observation.answer.claims_complete
    if actual is None:
        return [blocked("answer.claims_complete", "unknown_claim_coverage")]
    result = compare("answer.claims_complete", request.policy.answer.required_claims_complete,
                     actual, check.comparison, request.policy)
    if result.status == RuleStatus.FAILED:
        return [blocked(result.check_id, "incomplete_claim_coverage")]
    return [result]


def _conditions(request, check):
    actual = request.observation.answer.conditions
    if actual is None:
        return [blocked("answer.conditions", "missing_answer_conditions")]
    fields = request.policy.answer.condition_fields
    return [compare("answer.conditions", select_fields(expected_case(request), fields),
                    select_fields(actual, fields), check.comparison, request.policy)]


def _claim_checks(request, check):
    claims = request.observation.answer.claims
    if not claims:
        return [CheckResult(check_id=f"answer.{check.kind}", status=RuleStatus.PASSED, reason="no_claims")]
    evidence = request.observation.evidence
    if evidence is None:
        return [blocked(f"answer.{check.kind}", "missing_evidence")]
    references = {item.evidence_id: item for item in evidence.references}
    results = []
    for claim in claims:
        identity = f"answer.{check.kind}.{claim.claim_id}"
        reference = references.get(claim.evidence_id)
        if reference is None:
            results.append(CheckResult(check_id=identity, status=RuleStatus.FAILED, reason="unbacked_claim"))
        elif check.kind == "claim_values":
            try:
                value = select_path(evidence.result, reference.path)
                results.append(compare(identity, value, claim.value, check.comparison, request.policy))
            except (KeyError, IndexError):
                results.append(blocked(identity, "invalid_evidence_path"))
        elif reference.conditions is None or claim.conditions is None:
            results.append(blocked(identity, "missing_claim_conditions"))
        else:
            fields = request.policy.answer.condition_fields
            results.append(compare(identity, select_fields(reference.conditions, fields),
                                   select_fields(claim.conditions, fields), check.comparison, request.policy))
    return results


_CHECKS = {"behavior": _behavior, "claims_complete": _complete, "answer_conditions": _conditions,
           "claim_values": _claim_checks, "claim_conditions": _claim_checks}
