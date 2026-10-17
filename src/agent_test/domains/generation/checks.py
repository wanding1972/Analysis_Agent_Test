"""Interpret configured constraints over Canonical data only."""

from pydantic import ValidationError

from agent_test.domains.canonical.api import CanonicalSemanticModel, SemanticScope
from agent_test.domains.rules.api import RuleStatus, check_compatibility, semantic_axes


def semantic_nodes(case):
    nodes = [CanonicalSemanticModel.model_validate(case.model_dump(
        include=set(CanonicalSemanticModel.model_fields), mode="json")), *case.steps]
    pending = list(reversed(nodes))
    while pending:
        node = pending.pop()
        yield node
        parameters = node.operation.parameters if node.operation is not None else {}
        if "comparison" in parameters:
            comparison = parameters["comparison"]
            if not isinstance(comparison, dict) or not isinstance(comparison.get("operands"), list):
                raise ValueError("invalid canonical comparison")
            pending.extend(reversed([CanonicalSemanticModel.model_validate(operand["semantic"])
                                     for operand in comparison["operands"]]))


def _axes(node, context):
    axes = semantic_axes(node, context)
    parameters = node.operation.parameters if node.operation is not None else {}
    if "metrics" in parameters:
        values = parameters["metrics"]
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError("invalid canonical metric list")
        if node.metric != (values[0] if len(values) == 1 else None):
            raise ValueError("canonical metric aliases disagree")
        axes["metric"] = values
    if "scopes" in parameters:
        raw = parameters["scopes"]
        if not isinstance(raw, list):
            raise ValueError("invalid canonical scope list")
        scopes = [SemanticScope.model_validate(item) for item in raw]
        if node.scope != (scopes[0] if len(scopes) == 1 else None):
            raise ValueError("canonical scope aliases disagree")
        axes["subject"] = [scope.subject for scope in scopes]
    return axes


def _capability_status(case, nodes, request):
    filters = request.policy.generation_filters
    capability = request.capability.model_dump()
    if len(case.steps) > 1 and not request.capability.multi_step:
        return "blocked", "multistep_not_declared"
    for node in nodes:
        axes = _axes(node, request.context)
        axes["operation"] = [value for value in axes["operation"] if value not in filters.structural_operations]
        for axis, field in filters.capability_axes.items():
            if not set(axes[axis]) <= set(capability[field]):
                return ("invalid", "capability_disallowed") if axis in filters.closed_world_axes else (
                    "blocked", "capability_unknown")
    return "valid", "satisfied"


def assess(case, request):
    try:
        nodes = list(semantic_nodes(case))
        status, reason = _capability_status(case, nodes, request)
        if status != "valid":
            return status, reason, []
        required = request.policy.generation_filters.required_families
        rules = [item for item in request.rules.compatibility_rules if item.family in required]
        if not required and not request.policy.generation_filters.allow_capability_only:
            return "blocked", "compatibility_not_defined", []
        outcomes = []
        for node in nodes:
            current = check_compatibility(node, rules, request.context)
            outcomes.extend(current)
            for family in required:
                ids = {rule.rule_id for rule in rules if rule.family == family}
                selected = [item for item in current if item.rule_id in ids]
                if not any(item.status in {RuleStatus.PASSED, RuleStatus.FAILED} for item in selected):
                    return "blocked", "compatibility_not_covered", outcomes
        if any(item.status == RuleStatus.BLOCKED for item in outcomes):
            return "blocked", "compatibility_blocked", outcomes
        if any(item.status == RuleStatus.FAILED for item in outcomes):
            return "invalid", "compatibility_disallowed", outcomes
        return "valid", "satisfied", outcomes
    except (ValidationError, ValueError, TypeError, KeyError):
        return "blocked", "invalid_canonical_parameters", []
