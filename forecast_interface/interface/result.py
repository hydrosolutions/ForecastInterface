from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from forecast_interface.output.model_output import ModelOutput

from .failure import FailureCause


class ModelSuccess(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: Literal["success"] = "success"
    output: ModelOutput


class ModelFailure(BaseModel):
    kind: Literal["failure"] = "failure"
    model_name: str
    issue_datetime: datetime
    cause: FailureCause
    message: str

    @field_validator("model_name")
    @classmethod
    def _non_empty_model_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("model_name must be a non-empty string")
        return v

    @field_validator("message")
    @classmethod
    def _non_empty_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("failure message must be a non-empty string")
        return v


ModelResult = ModelSuccess | ModelFailure
