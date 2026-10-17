"""Reuse the safe configuration parser behind an Evaluation-specific Port."""

import logging
from pathlib import Path

from agent_test.domains.evaluation.api import EvaluationConfigError
from agent_test.domains.rules.api import RuleConfigError

from .rule_config import YamlRuleConfigSource


logger = logging.getLogger(__name__)


class YamlEvaluationPolicySource:
    def __init__(self, path: Path):
        self.source = YamlRuleConfigSource(path)

    def read(self) -> dict[str, object]:
        try:
            return self.source.read()
        except RuleConfigError as error:
            logger.error("Unable to read evaluation policy")
            raise EvaluationConfigError("Unable to read evaluation policy") from error
