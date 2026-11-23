from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from forecast_interface.common.aggregation import AggregationMethod
from forecast_interface.common.time_grid import PeriodLabel, TimeAnchor
from forecast_interface.common.units import Unit


class EnsembleMode(Enum):
    SINGLE = "single"
    ENSEMBLE = "ensemble"


class HorizonSemantics(Enum):
    # How `future_steps` reads: a floor (fewer is an error) or a ceiling
    # (fewer is acceptable and yields a correspondingly shorter forecast).
    EXACT = "exact"
    AT_MOST = "at_most"


def _reject_point_label(
    aggregation: AggregationMethod | None, label: PeriodLabel | None
) -> None:
    if (
        aggregation is AggregationMethod.POINT
        and label is not None
        and label is not PeriodLabel.UNKNOWN
    ):
        raise ValueError(
            "label is meaningless with POINT aggregation (value sampled at the stamp)"
        )


class PastKnownVariable(BaseModel):
    lookback: int
    max_nan: int
    unit: Unit
    aggregation: AggregationMethod | None = None
    # None inherits the label declared on the branch anchor.
    label: PeriodLabel | None = None

    @model_validator(mode="after")
    def _label_matches_aggregation(self) -> "PastKnownVariable":
        _reject_point_label(self.aggregation, self.label)
        return self

    @field_validator("lookback")
    @classmethod
    def _positive_lookback(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"lookback must be positive, got {v}")
        return v

    @field_validator("max_nan")
    @classmethod
    def _non_negative_max_nan(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"max_nan must be non-negative, got {v}")
        return v


class FutureKnownVariable(BaseModel):
    # horizon_semantics and min_future_steps constrain each other, so assignment
    # must re-run validation or the pair can be driven into an invalid state.
    model_config = ConfigDict(validate_assignment=True)

    future_steps: int
    max_nan: int
    unit: Unit
    aggregation: AggregationMethod | None = None
    label: PeriodLabel | None = None
    ensemble_mode: EnsembleMode = EnsembleMode.SINGLE
    horizon_semantics: HorizonSemantics = HorizonSemantics.EXACT
    min_future_steps: int | None = None

    @field_validator("future_steps")
    @classmethod
    def _positive_future_steps(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"future_steps must be positive, got {v}")
        return v

    @field_validator("max_nan")
    @classmethod
    def _non_negative_max_nan(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"max_nan must be non-negative, got {v}")
        return v

    @model_validator(mode="after")
    def _coherent_horizon_semantics(self) -> "FutureKnownVariable":
        _reject_point_label(self.aggregation, self.label)
        if self.horizon_semantics is HorizonSemantics.EXACT:
            if self.min_future_steps is not None:
                raise ValueError(
                    "min_future_steps is only meaningful when "
                    "horizon_semantics is at_most"
                )
            return self

        if self.min_future_steps is None:
            raise ValueError(
                "min_future_steps is required when horizon_semantics is at_most"
            )
        if self.min_future_steps <= 0:
            raise ValueError(
                f"min_future_steps must be positive, got {self.min_future_steps}"
            )
        if self.min_future_steps > self.future_steps:
            raise ValueError(
                f"min_future_steps {self.min_future_steps} must not exceed "
                f"future_steps {self.future_steps}"
            )
        return self


def effective_label(
    variable: PastKnownVariable | FutureKnownVariable, anchor: TimeAnchor
) -> PeriodLabel | None:
    if variable.aggregation is AggregationMethod.POINT:
        return None
    return variable.label if variable.label is not None else anchor.label
