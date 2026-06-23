from enum import Enum

from pydantic import BaseModel, field_validator

from forecast_interface.common import Unit


class OutputRepresentation(Enum):
    DETERMINISTIC = "deterministic"
    QUANTILES = "quantiles"
    TRAJECTORIES = "trajectories"


class TargetSpec(BaseModel):
    unit: Unit
    representations: frozenset[OutputRepresentation]

    @field_validator("representations")
    @classmethod
    def _non_empty_representations(
        cls,
        v: frozenset[OutputRepresentation],
    ) -> frozenset[OutputRepresentation]:
        if not v:
            raise ValueError(
                "representations must contain at least one output representation"
            )
        return v
