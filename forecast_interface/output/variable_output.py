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
        if len(v) < 3:
            raise ValueError("quantile_levels must contain at least 3 levels")
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
    def _minimum_samples(cls, v: int) -> int:
        if v < 8:
            raise ValueError(f"num_samples must be at least 8, got {v}")
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

    @computed_field  # type: ignore[prop-decorator]  # pydantic computed_field + property: known mypy false positive
    @property
    def trusted(self) -> bool:
        return len(self.flags) == 0

    @model_validator(mode="after")
    def _validate_data_present(self) -> "VariableOutput":
        if self.status in (VariableStatus.SUCCESS, VariableStatus.PARTIAL):
            if not any([self.deterministic, self.quantiles, self.trajectories]):
                raise ValueError(
                    "at least one of deterministic, quantiles, or trajectories "
                    "must be present when status is SUCCESS or PARTIAL"
                )
        return self

    @model_validator(mode="after")
    def _validate_forecast_horizon(self) -> "VariableOutput":
        for representation, data_container in (
            ("deterministic", self.deterministic),
            ("quantiles", self.quantiles),
            ("trajectories", self.trajectories),
        ):
            if data_container is None:
                continue
            df = data_container.data
            if df.height == 0:
                raise ValueError(f"{representation} data must not be empty")
            mismatches = (
                df.group_by("issue_datetime")
                .agg(pl.len().alias("rows"))
                .filter(pl.col("rows") != self.metadata.forecast_horizon)
            )
            if mismatches.height:
                observed = mismatches["rows"][0]
                raise ValueError(
                    f"{representation} data must contain exactly "
                    f"{self.metadata.forecast_horizon} rows per issue_datetime "
                    f"(got {observed})"
                )
        return self
