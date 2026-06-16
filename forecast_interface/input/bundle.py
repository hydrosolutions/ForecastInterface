import datetime

import polars as pl
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from forecast_interface.common import SpatialRepresentation, Unit

from ._validators import validate_input_series_dataframe


class InputSeries(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Deliberately carries only unit + data; declaration-only fields
    # (lookback/future_steps/max_nan/aggregation/ensemble_mode) do not appear
    # at the data leaf.
    unit: Unit
    data: pl.DataFrame

    @field_validator("data")
    @classmethod
    def _validate_data(cls, v: pl.DataFrame) -> pl.DataFrame:
        validate_input_series_dataframe(v)
        return v


class DynamicInputs(BaseModel):
    past_known: dict[str, dict[str, InputSeries]] = {}
    future_known: dict[str, dict[str, InputSeries]] = {}

    @model_validator(mode="after")
    def _at_least_one_temporality(self) -> "DynamicInputs":
        if not self.past_known and not self.future_known:
            raise ValueError(
                "at least one of past_known or future_known must be non-empty"
            )
        return self


class SpatialInputs(BaseModel):
    data: dict[SpatialRepresentation, DynamicInputs]

    @field_validator("data")
    @classmethod
    def _at_least_one_spatial(
        cls,
        v: dict[SpatialRepresentation, DynamicInputs],
    ) -> dict[SpatialRepresentation, DynamicInputs]:
        if not v:
            raise ValueError("data must contain at least one spatial representation")
        return v


class StationInputs(BaseModel):
    dynamic: dict[datetime.timedelta, SpatialInputs]
    static: dict[str, int | float | str] = {}

    @field_validator("dynamic")
    @classmethod
    def _validate_dynamic_time_steps(
        cls,
        v: dict[datetime.timedelta, SpatialInputs],
    ) -> dict[datetime.timedelta, SpatialInputs]:
        if not v:
            raise ValueError("dynamic must contain at least one time step")
        for time_step in v:
            if time_step.total_seconds() <= 0:
                raise ValueError("dynamic time step keys must be positive")
        return v

    @field_validator("static")
    @classmethod
    def _non_empty_static_entries(
        cls,
        v: dict[str, int | float | str],
    ) -> dict[str, int | float | str]:
        for entry in v:
            if not entry or not entry.strip():
                raise ValueError("static input names must be non-empty strings")
        return v


class ModelInputs(BaseModel):
    # Intentional drift from InputRequirement: a station level is added because
    # data is per-station, and static is a per-station dict rather than the
    # declaration's top-level set[str].
    stations: dict[str, StationInputs]

    @field_validator("stations")
    @classmethod
    def _validate_stations(
        cls,
        v: dict[str, StationInputs],
    ) -> dict[str, StationInputs]:
        if not v:
            raise ValueError("stations must contain at least one station")
        for station_id in v:
            if not station_id or not station_id.strip():
                raise ValueError("station keys must be non-empty strings")
        return v
