import pytest

from agent_test.domains.canonical.api import CanonicalTestCase, ExpectedBehavior


@pytest.fixture
def case() -> CanonicalTestCase:
    return CanonicalTestCase(
        case_id="case-1", question="测试问题", expected_behavior=ExpectedBehavior.ANSWER,
        metric=None, scope=None, grain=None, dimensions=[], time=None, filters=[],
        relations=[], set_operations=[], operation=None, steps=[], step_dependencies=[],
    )
