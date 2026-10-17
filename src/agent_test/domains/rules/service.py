"""Pure bounded rule checks; no discovery, IO, expression language or judgment."""

import logging
from collections.abc import Callable
from decimal import Decimal, localcontext

from pydantic import ValidationError

from agent_test.domains.canonical.api import CanonicalSemanticModel

from .models import (
    ApprovalStatus, CompatibilityContext, CompatibilityRule, CountLimitAssertion,
    DisjointAssertion, DistinctAssertion, RangeAssertion, RuleInputs, RuleOutcome,
    RuleSet, RuleStatus, SemanticEqualityAssertion, SubsetAssertion, SumAssertion,
    TestRule,
)
from .ports import RuleConfigError, RuleConfigSource


logger = logging.getLogger(__name__)


def load_rules(source: RuleConfigSource) -> RuleSet:
    try:
        return RuleSet.model_validate(source.read())
    except ValidationError as error:
        logger.error("Rule configuration schema validation failed")
        raise RuleConfigError("Invalid rule configuration schema") from error


def _outcome(rule_id: str, status: RuleStatus, reason: str) -> RuleOutcome:
    return RuleOutcome(rule_id=rule_id, status=status, reason=reason)


def _json_equal(left: object, right: object) -> bool:
    """Keep bool/number and unknown/zero distinct, including nested JSON."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _number(value: object) -> Decimal:
    if type(value) not in (int, float):
        raise ValueError("expected a number")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("expected a finite number")
    return number


def _items(value: object) -> list:
    if not isinstance(value, list):
        raise ValueError("expected an array")
    return value


def _range(rule: RangeAssertion, facts: dict) -> bool:
    value = _number(facts[rule.value])
    lower, upper = _number(rule.minimum), _number(rule.maximum)
    return (value >= lower if rule.include_minimum else value > lower) and (
        value <= upper if rule.include_maximum else value < upper
    )


def _count(rule: CountLimitAssertion, facts: dict) -> bool:
    limit = facts[rule.limit]
    if type(limit) is not int or limit < 0:
        raise ValueError("count limit must be a nonnegative integer")
    return len(_items(facts[rule.items])) <= limit


def _subset(rule: SubsetAssertion, facts: dict) -> bool:
    subset, superset = _items(facts[rule.subset]), _items(facts[rule.superset])
    return all(any(_json_equal(item, source) for source in superset) for item in subset)


def _disjoint(rule: DisjointAssertion, facts: dict) -> bool:
    left, right = _items(facts[rule.left]), _items(facts[rule.right])
    return not any(_json_equal(a, b) for a in left for b in right)


def _distinct(rule: DistinctAssertion, facts: dict) -> bool:
    return not _json_equal(facts[rule.left], facts[rule.right])


def _equal(rule, facts: dict) -> bool:
    return _json_equal(facts[rule.left], facts[rule.right])


def _unordered_equal(rule, facts: dict) -> bool:
    remaining = list(_items(facts[rule.right]))
    for item in _items(facts[rule.left]):
        match = next((index for index, other in enumerate(remaining) if _json_equal(item, other)), None)
        if match is None:
            return False
        remaining.pop(match)
    return not remaining


def _sum(rule: SumAssertion, facts: dict) -> bool:
    parts = [_number(value) for value in _items(facts[rule.parts])]
    total = _number(facts[rule.total])
    tolerance = _number(rule.absolute_tolerance)
    # Precision follows input size, avoiding a hidden business rounding policy.
    numbers = [*parts, total, tolerance]
    with localcontext() as context:
        context.prec = sum(len(item.as_tuple().digits) + abs(item.as_tuple().exponent)
                           for item in numbers) + len(str(len(parts))) + 1
        return abs(sum(parts, Decimal(0)) - total) <= tolerance


def _semantic_equal(rule: SemanticEqualityAssertion, facts: dict) -> bool:
    left = CanonicalSemanticModel.model_validate(facts[rule.left]).model_dump(mode="json")
    right = CanonicalSemanticModel.model_validate(facts[rule.right]).model_dump(mode="json")
    return all(_json_equal(left[field], right[field]) for field in rule.fields)


_CHECKS: dict[str, Callable] = {
    "numeric_range": _range, "count_limit": _count, "subset": _subset,
    "disjoint": _disjoint, "distinct": _distinct, "sum_equals": _sum,
    "semantic_equal": _semantic_equal,
    "json_equal": _equal, "unordered_equal": _unordered_equal,
}


def check_rule(rule: TestRule, inputs: RuleInputs) -> RuleOutcome:
    """Return one rule's finding, never a four-layer or final case verdict."""
    rule = TestRule.model_validate(rule.model_dump())
    inputs = RuleInputs.model_validate(inputs.model_dump())
    if rule.approval != ApprovalStatus.APPROVED:
        return _outcome(rule.rule_id, RuleStatus.BLOCKED, "not_approved")
    try:
        matches = [_json_equal(inputs.facts[key], value)
                   for key, value in rule.preconditions.items()]
        if not all(matches):
            return _outcome(rule.rule_id, RuleStatus.SKIPPED, "not_applicable")
        passed = _CHECKS[rule.assertion.kind](rule.assertion, inputs.facts)
    except KeyError:
        return _outcome(rule.rule_id, RuleStatus.BLOCKED, "missing_input")
    except (ValueError, TypeError, ArithmeticError):
        logger.warning("Invalid input for rule %s", rule.rule_id)
        return _outcome(rule.rule_id, RuleStatus.BLOCKED, "invalid_input")
    return _outcome(rule.rule_id, RuleStatus.PASSED if passed else RuleStatus.FAILED,
                    "satisfied" if passed else "violated")


def _semantic_axes(semantic: CanonicalSemanticModel, context: CompatibilityContext) -> dict:
    return {
        "metric": [semantic.metric] if semantic.metric is not None else [],
        "subject": [semantic.scope.subject] if semantic.scope is not None else [],
        "grain": [semantic.grain] if semantic.grain is not None else [],
        "dimensions": semantic.dimensions,
        "time_op": [semantic.time.operator] if semantic.time is not None else [],
        "filters": [item.field for item in semantic.filters],
        "relations": [item.relation for item in semantic.relations],
        "set_ops": [item.operator for item in semantic.set_operations],
        "operation": [semantic.operation.operator] if semantic.operation is not None else [],
        **{key: [value] if value is not None else []
           for key, value in context.model_dump().items()},
    }


def semantic_axes(semantic: CanonicalSemanticModel, context: CompatibilityContext) -> dict[str, list[str]]:
    """Public structural projection, shared by compatibility and generation."""
    semantic = CanonicalSemanticModel.model_validate(
        semantic.model_dump(include=set(CanonicalSemanticModel.model_fields))
    )
    context = CompatibilityContext.model_validate(context.model_dump())
    return _semantic_axes(semantic, context)


def check_compatibility(
    semantic: CanonicalSemanticModel,
    rules: list[CompatibilityRule],
    context: CompatibilityContext,
) -> list[RuleOutcome]:
    """No implicit allow: an empty rules list produces an empty findings list."""
    semantic = CanonicalSemanticModel.model_validate(
        semantic.model_dump(include=set(CanonicalSemanticModel.model_fields))
    )
    context = CompatibilityContext.model_validate(context.model_dump())
    axes = _semantic_axes(semantic, context)
    return [_check_compatibility_rule(rule, axes) for rule in rules]


def _check_compatibility_rule(rule: CompatibilityRule, axes: dict) -> RuleOutcome:
    rule = CompatibilityRule.model_validate(rule.model_dump())
    if rule.approval != ApprovalStatus.APPROVED:
        return _outcome(rule.rule_id, RuleStatus.BLOCKED, "not_approved")
    if any(not axes[item.axis] for item in rule.when):
        return _outcome(rule.rule_id, RuleStatus.BLOCKED, "missing_input")
    if not all(set(axes[item.axis]) <= set(item.allowed) for item in rule.when):
        return _outcome(rule.rule_id, RuleStatus.SKIPPED, "not_applicable")
    if any(not axes[item.axis] for item in rule.require):
        return _outcome(rule.rule_id, RuleStatus.BLOCKED, "missing_input")
    passed = all(set(axes[item.axis]) <= set(item.allowed) for item in rule.require)
    return _outcome(rule.rule_id, RuleStatus.PASSED if passed else RuleStatus.FAILED,
                    "satisfied" if passed else "violated")
