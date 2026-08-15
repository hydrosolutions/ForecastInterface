from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from forecast_interface.common.aggregation import AggregationMethod
from forecast_interface.common.units import Unit


class EnsembleMode(Enum):
    SINGLE = "single"
    ENSEMBLE = "ensemble"


class HorizonSemantics(Enum):
    # How `future_steps` reads: a floor (fewer is an error) or a ceiling
    # (fewer is acceptable and yields a correspondingly shorter forecast).
    EXACT = "exact"
    AT_MOST = "at_most"


class PastKnownVariable(BaseModel):
    lookback: int
    max_nan: int
    unit: Unit
    aggregation: AggregationMethod | None = None

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
