import datetime

from pydantic import BaseModel, field_validator

from .units import Unit
from .resolutions import Resolution


class VariableMetadata(BaseModel):
    name: str
    unit: Unit
    resolution: Resolution
    timedelta: datetime.timedelta
    forecast_horizon: int
    offset: int

    @field_validator("forecast_horizon")
    @classmethod
    def _positive_horizon(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"forecast_horizon must be positive, got {v}")
        return v

    @field_validator("timedelta")
    @classmethod
    def _positive_timedelta(cls, v: datetime.timedelta) -> datetime.timedelta:
        if v.total_seconds() <= 0:
            raise ValueError(f"timedelta must be positive, got {v}")
        return v

    @field_validator("offset")
    @classmethod
    def _non_negative_offset(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"offset must be non-negative, got {v}")
        return v
