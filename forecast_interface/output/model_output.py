from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from .status import VariableStatus
from .variable_output import VariableOutput


class ModelOutput(BaseModel):
    # variables is station-keyed: station_id -> variable_name -> VariableOutput.
    # The model echoes back EVERY station id it was given: missing stations are
    # explicit FAILURE entries (a station whose VariableOutputs carry
    # status=FAILURE), never absent keys.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    issue_datetime: datetime
    # PROVISIONAL (Q1): station ids are opaque strings; the SAP3 adapter maps them to/from typed StationId (UUID).
    variables: dict[str, dict[str, VariableOutput]]

    @field_validator("model_name")
    @classmethod
    def _non_empty_model_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("model_name must be a non-empty string")
        return v

    @field_validator("variables")
    @classmethod
    def _validate_variables(
        cls,
        v: dict[str, dict[str, VariableOutput]],
    ) -> dict[str, dict[str, VariableOutput]]:
        if not v:
            raise ValueError("variables must contain at least one station")
        for station_id, station_vars in v.items():
            if not station_id or not station_id.strip():
                raise ValueError("station id keys must be non-empty strings")
            if not station_vars:
                raise ValueError(
                    f"station {station_id!r} must contain at least one variable"
                )
            for variable_name in station_vars:
                if not variable_name or not variable_name.strip():
                    raise ValueError("variable name keys must be non-empty strings")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return all(
            v.status == VariableStatus.SUCCESS
            for station in self.variables.values()
            for v in station.values()
        )
