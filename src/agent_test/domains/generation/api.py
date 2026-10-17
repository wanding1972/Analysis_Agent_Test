"""Public Generation API. Outputs are candidates, never approved truth."""

from .models import (
    AxisOption, AxisTarget, DesignerRequest, GeneratedTestCase, GenerationAxis, GenerationBatch,
    GenerationFilters, GenerationPolicy, GenerationRequest, GenerationTemplate, ProposalBatch,
    QuestionProposal, SamplingRecord,
)
from .ports import (
    CandidateDesignError, CandidateDesigner, CombinationDesignError, CombinationDesigner,
    GenerationBudgetExceeded, GenerationConfigError, GenerationPolicySource,
)
from .service import generate, load_policy

__all__ = [
    "AxisOption", "AxisTarget", "DesignerRequest", "GeneratedTestCase", "GenerationAxis", "GenerationBatch",
    "GenerationFilters", "GenerationPolicy", "GenerationRequest", "GenerationTemplate", "ProposalBatch",
    "QuestionProposal", "SamplingRecord", "CandidateDesignError", "CandidateDesigner",
    "CombinationDesignError", "CombinationDesigner", "GenerationBudgetExceeded", "GenerationConfigError",
    "GenerationPolicySource", "generate", "load_policy",
]
