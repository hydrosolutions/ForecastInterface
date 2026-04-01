from pydantic import BaseModel, field_validator, model_validator

from forecast_interface.common.resolutions import TemporalResolution

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
    distributed: DynamicInputSpec | None = None
    lumped: DynamicInputSpec | None = None

    @model_validator(mode="after")
    def _at_least_one_spatial(self) -> "SpatialInputSpec":
        if self.distributed is None and self.lumped is None:
            raise ValueError("at least one of distributed or lumped must be provided")
        return self


class InputRequirement(BaseModel):
    dynamic: dict[TemporalResolution, SpatialInputSpec]
    static: set[str] = set()

    @field_validator("dynamic")
    @classmethod
    def _at_least_one_resolution(
        cls,
        v: dict[TemporalResolution, SpatialInputSpec],
    ) -> dict[TemporalResolution, SpatialInputSpec]:
        if not v:
            raise ValueError("dynamic must contain at least one temporal resolution")
        return v

    @field_validator("static")
    @classmethod
    def _non_empty_static_entries(cls, v: set[str]) -> set[str]:
        for entry in v:
            if not entry or not entry.strip():
                raise ValueError("static input names must be non-empty strings")
        return v
