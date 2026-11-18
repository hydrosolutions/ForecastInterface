import datetime

from pydantic import BaseModel, field_validator, model_validator

from forecast_interface.common.time_grid import (
    PeriodLabel,
    Unknown,
    validate_divides_day,
    validate_whole_minutes,
)
from forecast_interface.common.units import Unit


class VariableMetadata(BaseModel):
    unit: Unit
    timedelta: datetime.timedelta
    forecast_horizon: (
        int  # Number of time steps of length timedelta that the forecast is made for
    )
    offset: int  # Number of time steps of length timedelta between the last observed data point and the first forecasted data point
    origin: datetime.timedelta | Unknown = Unknown.UNKNOWN
    label: PeriodLabel = PeriodLabel.UNKNOWN

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

    @model_validator(mode="after")
    def _origin_on_step(self) -> "VariableMetadata":
        if isinstance(self.origin, datetime.timedelta):
            validate_whole_minutes(self.origin, "origin")
            validate_divides_day(self.timedelta, "timedelta")
            if not datetime.timedelta(0) <= self.origin < self.timedelta:
                raise ValueError(
                    f"origin must satisfy 0 <= origin < timedelta, got {self.origin}"
                )
        return self
