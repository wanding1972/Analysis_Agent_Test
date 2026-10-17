import logging

from anthropic import APIError, Anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_test.domains.generation.api import (
    CandidateDesignError, DesignerRequest, ProposalBatch,
)


logger = logging.getLogger(__name__)


class ClaudeDesignerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1, pattern=r"\S")
    max_tokens: int = Field(strict=True, gt=0)
    timeout_seconds: float = Field(strict=True, gt=0, allow_inf_nan=False)


class ClaudeCandidateDesigner:
    def __init__(self, client: Anthropic, settings: ClaudeDesignerSettings):
        self.client = client
        self.settings = settings

    def propose(self, request: DesignerRequest) -> ProposalBatch:
        request = DesignerRequest.model_validate(request.model_dump(mode="json"))
        settings = ClaudeDesignerSettings.model_validate(self.settings.model_dump())
        try:
            message = self.client.messages.create(
                model=settings.model_id, max_tokens=settings.max_tokens, timeout=settings.timeout_seconds,
                tools=[{"name": "submit_candidates", "description": "Return candidate questions only.",
                        "input_schema": ProposalBatch.model_json_schema()}],
                tool_choice={"type": "tool", "name": "submit_candidates"},
                messages=[{"role": "user", "content": request.model_dump_json()}],
            )
            tools = [block for block in message.content if block.type == "tool_use"]
            if message.stop_reason != "tool_use" or len(tools) != 1 or tools[0].name != "submit_candidates":
                raise ValueError("expected one complete candidate tool response")
            batch = ProposalBatch.model_validate(tools[0].input)
            if len(batch.proposals) > request.max_candidates:
                raise ValueError("candidate response exceeds quota")
            return batch
        except (APIError, ValidationError, ValueError) as error:
            logger.error("Claude candidate generation failed")
            raise CandidateDesignError("Claude candidate generation failed") from error
