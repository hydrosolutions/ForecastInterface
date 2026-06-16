import datetime

from pydantic import BaseModel, field_validator, model_validator

from forecast_interface.common.resolutions import SpatialRepresentation

from .target import TargetSpec
from .variable import FutureKnownVariable, PastKnownVariable


class DynamicInputSpec(BaseModel):
    past_known: dict[str, dict[str, PastKnownVariable]] = {}
    future_known: dict[str, dict[str, FutureKnownVariable]] = {}

    @model_validator(mode="after")
    def _at_least_one_temporality(self) -> "DynamicInputSpec":
        if not self.past_known and not self.future_known:
            raise ValueError(
                "at least one of past_known or future_known must be non-empty"
            )
        return self


class SpatialInputSpec(BaseModel):
    data: dict[SpatialRepresentation, DynamicInputSpec]

    @field_validator("data")
    @classmethod
    def _at_least_one_spatial(
        cls,
        v: dict[SpatialRepresentation, DynamicInputSpec],
    ) -> dict[SpatialRepresentation, DynamicInputSpec]:
        if not v:
            raise ValueError("data must contain at least one spatial representation")
        return v


class InputRequirement(BaseModel):
    # Targets are declared independently of inputs; a model needing the target's own
    # history lists it under past_known (see Q2 in open_design_questions.md).
    targets: dict[str, TargetSpec]
    dynamic: dict[datetime.timedelta, SpatialInputSpec]
    static: set[str] = set()

    @field_validator("targets")
    @classmethod
    def _at_least_one_target(
        cls,
        v: dict[str, TargetSpec],
    ) -> dict[str, TargetSpec]:
        if not v:
            raise ValueError("targets must contain at least one entry")
        for name in v:
            if not name or not name.strip():
                raise ValueError("target variable names must be non-empty strings")
        return v

    @field_validator("dynamic")
    @classmethod
    def _validate_dynamic_time_steps(
        cls,
        v: dict[datetime.timedelta, SpatialInputSpec],
    ) -> dict[datetime.timedelta, SpatialInputSpec]:
        if not v:
            raise ValueError("dynamic must contain at least one time step")
        for time_step in v:
            if time_step.total_seconds() <= 0:
                raise ValueError("dynamic time step keys must be positive")
        return v

    @field_validator("static")
    @classmethod
    def _non_empty_static_entries(cls, v: set[str]) -> set[str]:
        for entry in v:
            if not entry or not entry.strip():
                raise ValueError("static input names must be non-empty strings")
        return v
