from itertools import combinations, product

import pytest
from hypothesis import given, settings, strategies as st

from agent_test.domains.generation.api import CombinationDesignError, GenerationBudgetExceeded
from agent_test.infrastructure.generation.allpairs import AllPairsDesigner


@settings(max_examples=20, derandomize=True, database=None)
@given(sizes=st.lists(st.integers(2, 3), min_size=2, max_size=4), strength=st.sampled_from([2, 3]))
def test_independent_unconstrained_twise_coverage(sizes, strength):
    factors = {f"axis_{index}": size for index, size in enumerate(sizes)}
    rows = list(AllPairsDesigner().rows(factors, strength, lambda _: True, 10000))
    for axes in combinations(factors, min(strength, len(factors))):
        expected = set(product(*(range(factors[name]) for name in axes)))
        observed = {tuple(row[name] for name in axes) for row in rows}
        assert observed == expected
    assert len({tuple(row.values()) for row in rows}) == len(rows)


def test_three_wise_regression_for_upstream_n3_gap():
    rows = list(AllPairsDesigner().rows({"a": 2, "b": 2, "c": 2}, 3, lambda _: True, 1000))
    assert {tuple(row.values()) for row in rows} == set(product(range(2), repeat=3))


def test_constraint_callback_never_exports_invalid_rows():
    rows = list(AllPairsDesigner().rows({"a": 2, "b": 2, "c": 2}, 3,
                                      lambda row: row["a"] == row["b"], 1000))
    assert rows and all(row["a"] == row["b"] for row in rows)


@pytest.mark.parametrize("sizes,strength", [({"a": 0}, 2), ({"a": 2}, 1)])
def test_invalid_backend_input(sizes, strength):
    with pytest.raises(CombinationDesignError):
        list(AllPairsDesigner().rows(sizes, strength, lambda _: True, 1000))


def test_interaction_budget_is_not_silently_truncated():
    with pytest.raises(GenerationBudgetExceeded):
        list(AllPairsDesigner().rows({"a": 2, "b": 2, "c": 2}, 3, lambda _: True, 1))
