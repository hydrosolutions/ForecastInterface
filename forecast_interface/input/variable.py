from enum import Enum

from pydantic import BaseModel, field_validator


class EnsembleMode(Enum):
    SINGLE = "single"
    ENSEMBLE = "ensemble"


class PastKnownVariable(BaseModel):
    lookback: int
    max_nan: int

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
    future_steps: int
    max_nan: int
    ensemble_mode: EnsembleMode = EnsembleMode.SINGLE

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
