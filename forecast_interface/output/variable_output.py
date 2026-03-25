import polars as pl
from pydantic import (
    BaseModel,
    ConfigDict,
    computed_field,
    field_validator,
    model_validator,
)

from ._validators import (
    validate_temporal_columns,
    validate_exact_columns,
    validate_numeric_columns,
)
from .flags import ForecastFlag
from .metadata import VariableMetadata
from .status import VariableStatus


class DeterministicData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: pl.DataFrame

    @model_validator(mode="after")
    def _validate_schema(self) -> "DeterministicData":
        validate_exact_columns(self.data, ["issue_datetime", "datetime", "value"])
        validate_temporal_columns(self.data)
        validate_numeric_columns(self.data, ["value"])
        return self


class QuantileData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    quantile_levels: list[float]
    data: pl.DataFrame

    @field_validator("quantile_levels")
    @classmethod
    def _validate_levels(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("quantile_levels must not be empty")
        for level in v:
            if not (0 < level < 1):
                raise ValueError(f"quantile levels must be in (0, 1), got {level}")
        if v != sorted(v):
            raise ValueError("quantile_levels must be sorted ascending")
        if len(v) != len(set(v)):
            raise ValueError("quantile_levels must not contain duplicates")
        return v

    @model_validator(mode="after")
    def _validate_schema(self) -> "QuantileData":
        expected_cols = ["issue_datetime", "datetime"] + [
            str(q) for q in self.quantile_levels
        ]
        validate_exact_columns(self.data, expected_cols)
        validate_temporal_columns(self.data)
        validate_numeric_columns(self.data, [str(q) for q in self.quantile_levels])
        return self


class TrajectoryData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    num_samples: int
    data: pl.DataFrame

    @field_validator("num_samples")
    @classmethod
    def _positive_samples(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"num_samples must be positive, got {v}")
        return v

    @model_validator(mode="after")
    def _validate_schema(self) -> "TrajectoryData":
        expected_cols = ["issue_datetime", "datetime"] + [
            str(i) for i in range(1, self.num_samples + 1)
        ]
        validate_exact_columns(self.data, expected_cols)
        validate_temporal_columns(self.data)
        validate_numeric_columns(
            self.data, [str(i) for i in range(1, self.num_samples + 1)]
        )
        return self


class EpistemicUncertaintyData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: pl.DataFrame

    @model_validator(mode="after")
    def _validate_schema(self) -> "EpistemicUncertaintyData":
        validate_exact_columns(
            self.data, ["issue_datetime", "datetime", "std", "range"]
        )
        validate_temporal_columns(self.data)
        validate_numeric_columns(self.data, ["std", "range"])
        return self


class VariableOutput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    metadata: VariableMetadata
    deterministic: DeterministicData | None = None
    quantiles: QuantileData | None = None
    trajectories: TrajectoryData | None = None
    epistemic_uncertainty: EpistemicUncertaintyData | None = None
    flags: frozenset[ForecastFlag] = frozenset()
    status: VariableStatus

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trusted(self) -> bool:
        return len(self.flags) == 0

    @model_validator(mode="after")
    def _validate_data_present(self) -> "VariableOutput":
        if self.status == VariableStatus.SUCCESS:
            if not any([self.deterministic, self.quantiles, self.trajectories]):
                raise ValueError(
                    "at least one of deterministic, quantiles, or trajectories "
                    "must be present when status is SUCCESS"
                )
        return self
