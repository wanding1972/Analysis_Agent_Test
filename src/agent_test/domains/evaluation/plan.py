from pydantic import ValidationError

from agent_test.domains.canonical.api import CanonicalTestCase
from agent_test.domains.rules.api import RuleStatus

from .checks import blocked, compare
from .models import CheckResult
from .semantic import expected_case


def evaluate_plan(request):
    observation = request.observation
    if observation.steps is None or observation.step_dependencies is None:
        return [blocked("plan.input", "missing_plan")]
    if not observation.steps:
        return [blocked("plan.input", "empty_plan")]
    expected = expected_case(request).model_dump(mode="json")
    actual = observation.model_dump(mode="json")
    checks = [compare(f"plan.{field}", expected[field], actual[field], kind, request.policy)
              for field, kind in request.policy.plan.fields.items()]
    if request.policy.plan.validate_structure:
        payload = request.test_case.model_dump(mode="json")
        payload.update(steps=actual["steps"], step_dependencies=actual["step_dependencies"])
        try:
            CanonicalTestCase.model_validate(payload)
            checks.append(CheckResult(check_id="plan.structure", status=RuleStatus.PASSED, reason="valid_schema"))
        except ValidationError:
            checks.append(CheckResult(check_id="plan.structure", status=RuleStatus.FAILED, reason="invalid_plan_structure"))
    return checks
