import logging

from pydantic import ValidationError

from agent_test.domains.assets.api import ReferenceResult, ReferenceSQL, VerifiedVersionResult
from agent_test.domains.rules.api import RuleInputs, RuleStatus, check_rule

from .checks import blocked, compare, select_fields, select_path
from .models import CheckResult
from .ports import ReferenceEvidenceError
from .semantic import expected_case


logger = logging.getLogger(__name__)


class _FactUnavailable(Exception):
    pass


def evaluate_evidence(request, reference_reader):
    bundle = request.observation.evidence
    if bundle is None:
        return [blocked("evidence.input", "missing_evidence")]
    checks = _golden_checks(request, reference_reader)
    rules = {rule.rule_id: rule for rule in request.approved_rules.test_rules}
    for rule_id, bindings in request.policy.evidence.rule_bindings.items():
        if rule_id not in rules:
            checks.append(blocked(f"evidence.{rule_id}", "missing_rule"))
            continue
        try:
            inputs = RuleInputs(facts={key: _fact(binding, request) for key, binding in bindings.items()})
            outcome = check_rule(rules[rule_id], inputs)
            checks.append(CheckResult(check_id=f"evidence.{rule_id}", status=outcome.status, reason=outcome.reason))
        except (KeyError, IndexError):
            checks.append(blocked(f"evidence.{rule_id}", "missing_rule_fact"))
        except _FactUnavailable as error:
            checks.append(blocked(f"evidence.{rule_id}", str(error)))
    if not checks or all(item.status == RuleStatus.SKIPPED for item in checks):
        checks.append(blocked("evidence.oracle", "no_applicable_oracle"))
    if request.policy.evidence.check_reference_conditions:
        checks.extend(_reference_conditions(request))
    return checks


def _reference_conditions(request):
    case = expected_case(request)
    steps = {step.step_id: step for step in case.steps}
    fields = request.policy.evidence.condition_fields
    checks = []
    for reference in request.observation.evidence.references:
        identity = f"evidence.conditions.{reference.evidence_id}"
        expected = steps.get(reference.step_id) if reference.step_id is not None else case
        if expected is None or reference.conditions is None:
            checks.append(blocked(identity, "missing_evidence_conditions"))
        else:
            checks.append(compare(identity, select_fields(expected, fields),
                                  select_fields(reference.conditions, fields),
                                  request.policy.evidence.reference_condition_comparison, request.policy))
    return checks


def _golden_checks(request, reader):
    baseline = request.golden_baseline
    if baseline is None:
        return [blocked("evidence.golden", "missing_golden")] if request.policy.evidence.require_golden else []
    source = baseline.source
    if isinstance(source, (ReferenceResult, VerifiedVersionResult)):
        expected = source.result
    elif isinstance(source, ReferenceSQL):
        if reader is None:
            return [blocked("evidence.golden", "reference_reader_missing")]
        try:
            expected = RuleInputs(facts={"reference": reader.read(baseline)}).facts["reference"]
        except (ReferenceEvidenceError, ValidationError):
            logger.error("Reference evidence unavailable")
            return [blocked("evidence.golden", "reference_unavailable")]
    else:
        return [blocked("evidence.golden", "no_numeric_golden")] if request.policy.evidence.require_golden else []
    return [compare("evidence.golden", expected, request.observation.evidence.result,
                    request.policy.evidence.golden_comparison, request.policy)]


def _fact(binding, request):
    if binding.source == "literal":
        return binding.value
    if binding.source == "related":
        related = request.related_evidence[binding.reference]
        if related.snapshot_id != request.snapshot_id:
            raise _FactUnavailable("related_snapshot_mismatch")
        payload = related.bundle.result
    elif binding.source == "semantic":
        if request.observation.semantic is None:
            raise _FactUnavailable("missing_semantic_fact")
        payload = request.observation.semantic.model_dump(mode="json")
    else:
        payload = request.observation.evidence.result
    return select_path(payload, binding.path)
