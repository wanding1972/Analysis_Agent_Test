"""Public Rules contracts and pure services."""

from .models import (
    CompatibilityFamily, SemanticAxis,
    ApprovalStatus, AxisConstraint, CompatibilityContext, CompatibilityRule,
    CountLimitAssertion, DisjointAssertion, DistinctAssertion, EqualityAssertion, RangeAssertion,
    RuleInputs, RuleOutcome, RuleSet, RuleStatus, SemanticEqualityAssertion,
    SubsetAssertion, SumAssertion, TestRule,
)
from .ports import RuleConfigError, RuleConfigSource
from .service import check_compatibility, check_rule, load_rules, semantic_axes

__all__ = [
    "ApprovalStatus", "AxisConstraint", "CompatibilityContext", "CompatibilityRule",
    "CountLimitAssertion", "DisjointAssertion", "DistinctAssertion", "RangeAssertion",
    "RuleInputs", "RuleOutcome", "RuleSet", "RuleStatus", "SemanticEqualityAssertion",
    "SubsetAssertion", "SumAssertion", "TestRule", "RuleConfigError", "RuleConfigSource",
    "check_compatibility", "check_rule", "load_rules", "EqualityAssertion",
    "CompatibilityFamily", "SemanticAxis", "semantic_axes",
]
