"""Pure cross-version comparison; no SDK or storage dependency."""

import json

from .models import DriftItem, DriftPolicy, DriftRecord, VersionExecution


def compare(
    baseline: VersionExecution,
    candidate: VersionExecution,
    policy: DriftPolicy,
) -> DriftRecord:
    baseline = VersionExecution.model_validate(baseline.model_dump(mode="json"))
    candidate = VersionExecution.model_validate(candidate.model_dump(mode="json"))
    policy = DriftPolicy.model_validate(policy.model_dump(mode="json"))
    if baseline.observation.case_id != candidate.observation.case_id:
        return _blocked(baseline, candidate, "case_mismatch")
    if baseline.observation.snapshot_id != candidate.observation.snapshot_id:
        return _blocked(baseline, candidate, "snapshot_mismatch")

    items: list[DriftItem] = []
    _append_value_diff(items, "capability", "status", baseline.observation.status,
                       candidate.observation.status, policy)
    for kind in ("semantic", "plan", "evidence", "answer"):
        _append_value_diff(items, kind, kind, getattr(baseline, kind), getattr(candidate, kind), policy)
    status = "none" if not items else (
        "expected_change" if all(item.reason == "expected_change" for item in items) else "regression"
    )
    return DriftRecord(
        drift_id=f"{baseline.observation.case_id}:{baseline.version_id}:{candidate.version_id}",
        case_id=baseline.observation.case_id,
        snapshot_id=baseline.observation.snapshot_id,
        baseline_version=baseline.version_id,
        candidate_version=candidate.version_id,
        status=status,
        items=items,
        summary="no_drift" if status == "none" else f"{status}:{len(items)}_difference(s)",
    )


def _append_value_diff(items, kind, path, baseline, candidate, policy):
    if _same(baseline, candidate):
        return
    reason = "expected_change" if path in policy.expected_changes else "changed"
    items.append(DriftItem(kind=kind, path=path, baseline=baseline, candidate=candidate, reason=reason))


def _same(left, right):
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _blocked(baseline, candidate, reason):
    return DriftRecord(
        drift_id=f"{baseline.observation.case_id}:{baseline.version_id}:{candidate.version_id}",
        case_id=baseline.observation.case_id,
        snapshot_id=baseline.observation.snapshot_id,
        baseline_version=baseline.version_id,
        candidate_version=candidate.version_id,
        status="blocked", items=[], summary=reason,
    )
