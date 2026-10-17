"""Finite comparison operations delegated to the public Rules API."""

from agent_test.domains.rules.api import RuleInputs, RuleStatus, TestRule, check_rule

from .models import CheckResult, EvaluationPolicy, LayerResult


def blocked(check_id, reason):
    return CheckResult(check_id=check_id, status=RuleStatus.BLOCKED, reason=reason)


def compare(check_id, expected, actual, kind, policy):
    rule = TestRule(
        rule_id=check_id, description="Configured evaluation comparison",
        approval=policy.approval, approved_by=policy.approved_by,
        category="property", preconditions={},
        assertion={"kind": kind, "left": "expected", "right": "actual"},
    )
    result = check_rule(rule, RuleInputs(facts={"expected": expected, "actual": actual}))
    return CheckResult(check_id=check_id, status=result.status, reason=result.reason,
                       expected=expected, actual=actual)


def reduce_status(statuses, policy: EvaluationPolicy):
    available = set(statuses)
    return next(status for status in policy.precedence if status in available)


def layer_result(name, checks, policy):
    checks = checks or [blocked(f"{name}.coverage", "no_checks")]
    status = reduce_status([item.status for item in checks], policy)
    return LayerResult(layer=name, status=status,
                       failure_code=getattr(policy, name).failure_code if status == RuleStatus.FAILED else None,
                       checks=checks)


def select_fields(model, fields):
    payload = model.model_dump(mode="json")
    return {field: payload[field] for field in fields}


def select_path(payload, path):
    """Only literal JSON object keys and array indices; never an expression."""
    for key in path:
        if isinstance(payload, list) and type(key) is int:
            payload = payload[key]
        elif isinstance(payload, dict) and isinstance(key, str):
            payload = payload[key]
        else:
            raise KeyError("path type mismatch")
    return payload
