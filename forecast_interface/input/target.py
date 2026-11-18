from enum import Enum

from pydantic import BaseModel, field_validator, model_validator

from forecast_interface.common import AggregationMethod, PeriodLabel, Unit


class OutputRepresentation(Enum):
    DETERMINISTIC = "deterministic"
    QUANTILES = "quantiles"
    TRAJECTORIES = "trajectories"


_RATE_UNITS = frozenset(
    {
        Unit.M3_PER_S,
        Unit.MM_PER_DAY,
        Unit.MM_PER_S,
        Unit.M_PER_S,
        Unit.MM_PER_HOUR,
        Unit.W_PER_M2,
    }
)


class TargetSpec(BaseModel):
    unit: Unit
    representations: frozenset[OutputRepresentation]
    aggregation: AggregationMethod | None = None
    label: PeriodLabel = PeriodLabel.UNKNOWN

    @model_validator(mode="after")
    def _coherent_aggregation(self) -> "TargetSpec":
        if (
            self.aggregation is AggregationMethod.POINT
            and self.label is not PeriodLabel.UNKNOWN
        ):
            raise ValueError("label is meaningless with POINT aggregation")
        if self.aggregation is AggregationMethod.SUM and self.unit in _RATE_UNITS:
            raise ValueError(
                f"SUM aggregation is incompatible with rate unit {self.unit.value}; "
                "use MEAN or an accumulated unit"
            )
        return self

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
