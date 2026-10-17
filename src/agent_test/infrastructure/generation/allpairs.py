import logging
from itertools import combinations, product

from allpairspy import AllPairs

from agent_test.domains.generation.api import CombinationDesignError, GenerationBudgetExceeded


logger = logging.getLogger(__name__)


class AllPairsDesigner:
    def rows(self, sizes, strength, allow, max_interactions):
        try:
            if (type(strength) is not int or strength not in (2, 3)
                    or type(max_interactions) is not int or max_interactions < 1
                    or any(type(size) is not int or size < 1 for size in sizes.values())):
                raise ValueError("unsupported combination dimensions")
            names = list(sizes)
            if not names:
                if allow({}):
                    yield {}
                return
            if len(names) == 1:
                for index in range(sizes[names[0]]):
                    row = {names[0]: index}
                    if allow(row):
                        yield row
                return

            seen = set()
            for row in self._pairs(names, sizes, {}, allow):
                seen.add(tuple(row[name] for name in names))
                yield row
            if strength == 3:
                interactions = 0
                for axes in combinations(names, strength):
                    for values in product(*(range(sizes[name]) for name in axes)):
                        interactions += 1
                        if interactions > max_interactions:
                            raise GenerationBudgetExceeded("interaction_limit")
                        positions = [names.index(name) for name in axes]
                        if any(tuple(row[index] for index in positions) == values for row in seen):
                            continue
                        fixed = dict(zip(axes, values, strict=True))
                        witness = next(self._pairs(names, sizes, fixed, allow), None)
                        if witness is not None:
                            seen.add(tuple(witness[name] for name in names))
                            yield witness
        except (ValueError, TypeError, IndexError) as error:
            logger.error("Combination designer failed")
            raise CombinationDesignError("Combination designer failed") from error

    @staticmethod
    def _pairs(names, sizes, fixed, allow):
        def permitted(values):
            return len(values) < len(names) or allow(dict(zip(names, values, strict=True)))

        choices = [[fixed[name]] if name in fixed else list(range(sizes[name])) for name in names]
        for values in AllPairs(choices, n=2, filter_func=permitted):
            yield dict(zip(names, values, strict=True))
