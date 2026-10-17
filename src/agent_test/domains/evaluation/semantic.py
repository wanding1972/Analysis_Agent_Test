from agent_test.domains.assets.api import ConfirmedSemanticCase

from .checks import blocked, compare


def expected_case(request):
    baseline = request.golden_baseline
    if baseline is not None and isinstance(baseline.source, ConfirmedSemanticCase):
        return baseline.source.case
    return request.test_case


def evaluate_semantic(request):
    actual = request.observation.semantic
    if actual is None:
        return [blocked("semantic.input", "missing_semantic")]
    expected = expected_case(request).model_dump(mode="json")
    payload = actual.model_dump(mode="json")
    return [compare(f"semantic.{field}", expected[field], payload[field], kind, request.policy)
            for field, kind in request.policy.semantic.fields.items()]
