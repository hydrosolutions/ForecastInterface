from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from .status import VariableStatus
from .variable_output import VariableOutput


class ModelOutput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    issue_datetime: datetime
    variables: dict[str, VariableOutput]

    @field_validator("model_name")
    @classmethod
    def _non_empty_model_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("model_name must be a non-empty string")
        return v

    @field_validator("variables")
    @classmethod
    def _at_least_one_variable(
        cls,
        v: dict[str, VariableOutput],
    ) -> dict[str, VariableOutput]:
        if not v:
            raise ValueError("variables must contain at least one entry")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return all(v.status == VariableStatus.SUCCESS for v in self.variables.values())
