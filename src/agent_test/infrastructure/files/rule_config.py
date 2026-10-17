"""Safe YAML rule source; implements the domain's configuration Port."""

import logging
from pathlib import Path

import yaml

from agent_test.domains.rules.api import RuleConfigError


logger = logging.getLogger(__name__)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    pairs = loader.construct_pairs(node, deep=True)
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError("YAML mapping keys must be unique strings")
        result[key] = value
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


class YamlRuleConfigSource:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict[str, object]:
        try:
            with self.path.open(encoding="utf-8") as stream:
                payload = yaml.load(stream, Loader=_UniqueKeyLoader)
            if not isinstance(payload, dict):
                raise ValueError("rule configuration must be an object")
            return payload
        except (OSError, UnicodeError, yaml.YAMLError, ValueError, RecursionError) as error:
            logger.error("Unable to read rule configuration")
            raise RuleConfigError("Unable to read rule configuration") from error
