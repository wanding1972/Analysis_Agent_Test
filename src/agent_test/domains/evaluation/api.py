"""Public deterministic Evaluation API; no Agent version or SDK dependency."""

from .models import (
    AnswerClaim, AnswerObservation, CheckResult, EvaluationPolicy, EvaluationRequest,
    EvidenceBundle, EvidenceReference, LayerResult, Observation, RelatedEvidence, TestResult,
)
from .ports import (
    EvaluationConfigError, EvaluationPolicySource, ReferenceEvidenceError, ReferenceEvidenceReader,
)
from .service import evaluate, load_policy

__all__ = [
    "AnswerClaim", "AnswerObservation", "CheckResult", "EvaluationPolicy", "EvaluationRequest",
    "EvidenceBundle", "EvidenceReference", "LayerResult", "Observation", "RelatedEvidence", "TestResult",
    "EvaluationConfigError", "EvaluationPolicySource", "ReferenceEvidenceError", "ReferenceEvidenceReader",
    "evaluate", "load_policy",
]
