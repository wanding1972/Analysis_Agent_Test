"""Asset input validation and persistence through Ports only."""

import logging

from pydantic import TypeAdapter, ValidationError

from .models import AssetSetSummary, GoldenQuestion, Identifier, QuestionSet, TestAssetSet
from .ports import (
    AssetSetRepository, AssetSetSource, AssetValidationError, QuestionSource,
)


logger = logging.getLogger(__name__)


def load_questions(source: QuestionSource) -> list[GoldenQuestion]:
    try:
        return QuestionSet.model_validate({"questions": source.read()}).questions
    except ValidationError as error:
        logger.error("Question asset schema validation failed")
        raise AssetValidationError("Invalid question asset schema") from error


def load_asset_set(source: AssetSetSource) -> TestAssetSet:
    return validate_asset_set(source.read())


def validate_asset_set(payload: object) -> TestAssetSet:
    try:
        return TestAssetSet.model_validate(payload)
    except ValidationError as error:
        logger.error("Asset set schema validation failed")
        raise AssetValidationError("Invalid asset set schema") from error


def save_asset_set(asset_set: TestAssetSet, repository: AssetSetRepository) -> None:
    validated = validate_asset_set(asset_set.model_dump(mode="json"))
    repository.save(validated)


def get_asset_set(asset_set_id: str, repository: AssetSetRepository) -> TestAssetSet:
    validated_id = TypeAdapter(Identifier).validate_python(asset_set_id)
    return validate_asset_set(repository.get(validated_id).model_dump(mode="json"))


def list_asset_sets(repository: AssetSetRepository) -> list[AssetSetSummary]:
    return TypeAdapter(list[AssetSetSummary]).validate_python(
        [item.model_dump() for item in repository.list()]
    )
