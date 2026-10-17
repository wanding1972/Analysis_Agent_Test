import logging
from pathlib import Path

from agent_test.domains.generation.api import GenerationConfigError
from agent_test.domains.rules.api import RuleConfigError

from .rule_config import YamlRuleConfigSource


logger = logging.getLogger(__name__)


class YamlGenerationPolicySource:
    def __init__(self, path: Path):
        self.source = YamlRuleConfigSource(path)

    def read(self) -> dict[str, object]:
        try:
            return self.source.read()
        except RuleConfigError as error:
            logger.error("Unable to read generation policy")
            raise GenerationConfigError("Unable to read generation policy") from error
