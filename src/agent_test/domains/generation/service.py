import hashlib
import json
import logging

from pydantic import ValidationError

from agent_test.domains.canonical.api import CanonicalTestCase
from agent_test.domains.rules.api import ApprovalStatus

from .checks import assess
from .models import (
    DesignerRequest, GeneratedTestCase, GenerationBatch, GenerationPolicy, GenerationRequest,
    ProposalBatch, SamplingRecord,
)
from .ports import (
    CandidateDesignError, CandidateDesigner, CombinationDesignError, CombinationDesigner,
    GenerationBudgetExceeded, GenerationConfigError, GenerationPolicySource,
)


logger = logging.getLogger(__name__)


def load_policy(source: GenerationPolicySource) -> GenerationPolicy:
    try:
        return GenerationPolicy.model_validate(source.read())
    except ValidationError as error:
        logger.error("Generation policy schema validation failed")
        raise GenerationConfigError("Invalid generation policy schema") from error


def _reject(batch, reason):
    batch.rejected_counts[reason] = batch.rejected_counts.get(reason, 0) + 1


def _materialize(seed, template, row):
    if set(row) != {axis.name for axis in template.axes}:
        raise ValueError("combination row has incorrect axes")
    payload = seed.model_dump(mode="json")
    steps = {item["step_id"]: item for item in payload["steps"]}
    labels = {"question": seed.question}
    for axis in template.axes:
        index = row[axis.name]
        if type(index) is not int or not 0 <= index < len(axis.options):
            raise ValueError("combination row has invalid option index")
        option = axis.options[index]
        labels[axis.name] = option.label
        for target in axis.targets:
            (payload if target.step_id is None else steps[target.step_id]).update(option.patch)
    payload["question"] = template.question_template.format_map(labels)
    return CanonicalTestCase.model_validate(payload)


def _candidate(case, seed_id, case_type, source, outcomes, rule_ids, related, request):
    payload = case.model_dump(mode="json", exclude={"case_id"})
    fingerprint = json.dumps([payload, case_type, source, rule_ids, related], sort_keys=True, ensure_ascii=False, allow_nan=False)
    identity = f"generated:{hashlib.sha256(fingerprint.encode()).hexdigest()}"
    payload["case_id"] = identity
    return GeneratedTestCase(case=CanonicalTestCase.model_validate(payload), seed_case_id=seed_id,
        capability_id=request.capability.capability_id, case_type=case_type, source=source,
        review_required=source == "ai", compatibility=outcomes, rule_ids=rule_ids,
        related_seed_case_ids=related)


def _append(candidate, batch, request):
    if any(item.case.case_id == candidate.case.case_id for item in batch.candidates):
        _reject(batch, "duplicate_candidate")
        return True
    if len(batch.candidates) >= request.policy.max_generated_cases:
        batch.truncated = True
        batch.diagnostics.append("case_limit_reached")
        return False
    batch.candidates.append(candidate)
    return True


def _template_rules_available(template, request):
    rules = {item.rule_id: item for item in request.rules.test_rules}
    return all(identity in rules and rules[identity].approval == ApprovalStatus.APPROVED
               and (template.case_type not in {"property", "metamorphic"}
                    or rules[identity].category == template.case_type) for identity in template.rule_ids)


def _sample(template, request, designer, batch, budget):
    if template.case_type not in request.policy.allowed_case_types:
        _reject(batch, "case_type_excluded")
        return
    if not _template_rules_available(template, request):
        batch.diagnostics.append("template_rule_not_approved")
        return
    seed = next(item for item in request.seed_cases if item.case_id == template.seed_case_id)
    strength = (request.policy.high_risk_strength if request.capability.capability_id
                in request.policy.high_risk_capability_ids else request.policy.pairwise_strength)
    sizes = {axis.name: len(axis.options) for axis in template.axes}
    record = SamplingRecord(template_id=template.template_id, requested_strength=strength,
        effective_strength=min(strength, len(sizes)), backend_exhausted=False, emitted_rows=0)
    batch.sampling.append(record)
    cache = {}

    def allow(row):
        if not isinstance(row, dict) or set(row) != set(sizes) or any(type(value) is not int for value in row.values()):
            raise CombinationDesignError("invalid combination row schema")
        key = tuple(row.get(axis.name) for axis in template.axes)
        if key in cache:
            return cache[key] is not None
        budget["checks"] += 1
        if budget["checks"] > request.policy.max_candidate_checks:
            raise GenerationBudgetExceeded("candidate_check_limit")
        try:
            case = _materialize(seed, template, row)
            status, reason, outcomes = assess(case, request)
        except (ValidationError, ValueError, KeyError, TypeError):
            cache[key] = None
            _reject(batch, "invalid_candidate_schema")
            batch.diagnostics.append("invalid_candidate_schema")
            return False
        kind = template.case_type
        if status == "invalid" and request.policy.invalid_combination_strategy == "negative":
            kind = "negative"
            case.expected_behavior = request.policy.invalid_combination_behavior
        elif status != "valid":
            cache[key] = None
            _reject(batch, reason)
            if status == "blocked":
                batch.diagnostics.append(reason)
            return False
        if kind not in request.policy.allowed_case_types:
            cache[key] = None
            _reject(batch, "case_type_excluded")
            return False
        cache[key] = _candidate(case, seed.case_id, kind, "deterministic", outcomes,
                                template.rule_ids, template.related_seed_case_ids, request)
        return True

    for row in designer.rows(sizes, strength, allow, request.policy.max_interaction_checks):
        if not allow(row):
            raise CombinationDesignError("backend returned a disallowed row")
        key = tuple(row[axis.name] for axis in template.axes)
        if not _append(cache[key], batch, request):
            return
        record.emitted_rows += 1
    record.backend_exhausted = True


def _paraphrases(request, designer, batch):
    policy = request.policy
    if not policy.ai_enabled or policy.paraphrase_count == 0 or "paraphrase" not in policy.allowed_case_types:
        return
    if designer is None:
        batch.diagnostics.append("candidate_designer_unavailable")
        return
    if len(batch.candidates) >= policy.max_generated_cases:
        batch.truncated = True
        return
    seeds = {seed.case_id: seed for seed in request.seed_cases if assess(seed, request)[0] == "valid"}
    if not seeds:
        batch.diagnostics.append("no_compatible_ai_seeds")
        return
    proposal_request = DesignerRequest(seeds=list(seeds.values()), paraphrase_count=policy.paraphrase_count,
                                       max_candidates=policy.max_ai_candidates, prompt=policy.designer_prompt)
    proposals = ProposalBatch.model_validate(designer.propose(proposal_request).model_dump(mode="json")).proposals
    if len(proposals) > policy.max_ai_candidates:
        raise CandidateDesignError("AI proposal count exceeds configured limit")
    counts = {}
    for proposal in proposals:
        counts[proposal.seed_case_id] = counts.get(proposal.seed_case_id, 0) + 1
        if proposal.seed_case_id not in seeds or counts[proposal.seed_case_id] > policy.paraphrase_count:
            raise CandidateDesignError("AI proposal references unknown seed or exceeds quota")
    if len(proposals) < min(policy.max_ai_candidates, len(seeds) * policy.paraphrase_count):
        batch.diagnostics.append("ai_quota_not_met")
    for proposal in proposals:
        seed = seeds[proposal.seed_case_id]
        payload = seed.model_dump(mode="json")
        payload["question"] = proposal.question
        case = CanonicalTestCase.model_validate(payload)
        candidate = _candidate(case, seed.case_id, "paraphrase", "ai", assess(seed, request)[2], [], [], request)
        if not _append(candidate, batch, request):
            return
    if sum(item.source == "ai" for item in batch.candidates) < min(policy.max_ai_candidates, len(seeds) * policy.paraphrase_count):
        batch.diagnostics.append("ai_quota_not_met")


def generate(request: GenerationRequest, combinations: CombinationDesigner,
             candidate_designer: CandidateDesigner | None = None) -> GenerationBatch:
    request = GenerationRequest.model_validate(request.model_dump(mode="json"))
    batch = GenerationBatch(status="blocked", candidates=[], rejected_counts={}, diagnostics=[], truncated=False, sampling=[])
    if request.policy.approval != ApprovalStatus.APPROVED:
        batch.diagnostics.append("policy_not_approved")
        return batch
    budget = {"checks": 0}
    try:
        for template in request.policy.templates:
            _sample(template, request, combinations, batch, budget)
            if batch.truncated:
                break
    except GenerationBudgetExceeded:
        batch.truncated = True
        batch.diagnostics.append("sampling_budget_exceeded")
    except CombinationDesignError:
        logger.error("Combination generation unavailable")
        batch.diagnostics.append("combination_designer_failed")
    if not batch.truncated:
        try:
            _paraphrases(request, candidate_designer, batch)
        except (CandidateDesignError, ValidationError):
            logger.error("AI candidate generation unavailable")
            batch.diagnostics.append("candidate_designer_failed")
    batch.diagnostics = list(dict.fromkeys(batch.diagnostics))
    if batch.candidates:
        batch.status = "partial" if batch.truncated or batch.diagnostics else "ready"
    elif not batch.diagnostics:
        batch.diagnostics.append("no_candidates")
    return batch
