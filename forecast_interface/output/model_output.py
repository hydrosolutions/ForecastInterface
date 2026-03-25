from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from .status import VariableStatus
from .variable_output import VariableOutput


class ModelOutput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    forecast_issue_date: datetime
    variables: dict[str, VariableOutput]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return all(v.status == VariableStatus.SUCCESS for v in self.variables.values())
