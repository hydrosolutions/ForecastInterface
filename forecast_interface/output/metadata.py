import datetime

from pydantic import BaseModel, field_validator

from forecast_interface.common.units import Unit
from forecast_interface.common.resolutions import TemporalResolution


class VariableMetadata(BaseModel):
    name: str  # Name of the variable, e.g. "discharge", "water_level", etc.
    unit: Unit
    resolution: TemporalResolution
    timedelta: datetime.timedelta  # Concrete value im minutes for example, but can be any positive timedelta that is consistent with the resolution
    forecast_horizon: (
        int  # Number of time steps of length timedelta that the forecast is made for
    )
    offset: int  # Number of time steps of length timedelta between the last observed data point and the first forecasted data point

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must be a non-empty string")
        return v

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
