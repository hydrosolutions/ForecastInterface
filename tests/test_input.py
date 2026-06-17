from datetime import timedelta

import pytest
from pydantic import ValidationError

from forecast_interface.common import Unit
from forecast_interface.input import (
    AggregationMethod,
    DynamicInputSpec,
    EnsembleMode,
    FutureKnownVariable,
    InputRequirement,
    OutputRepresentation,
    PastKnownVariable,
    SpatialInputSpec,
    SpatialRepresentation,
    TargetSpec,
)

DAILY = timedelta(days=1)
HOURLY = timedelta(hours=1)


def _target() -> dict[str, TargetSpec]:
    return {
        "discharge": TargetSpec(
            unit=Unit.M3_PER_S,
            representations=frozenset({OutputRepresentation.QUANTILES}),
        )
    }


# ---------------------------------------------------------------------------
# Variable types
# ---------------------------------------------------------------------------


class TestPastKnownVariable:
    def test_valid(self) -> None:
        v = PastKnownVariable(unit=Unit.M3_PER_S, lookback=30, max_nan=5)
        assert v.lookback == 30
        assert v.max_nan == 5
        assert v.unit == Unit.M3_PER_S
        assert v.aggregation is None

    def test_aggregation_override(self) -> None:
        v = PastKnownVariable(
            unit=Unit.MM_PER_DAY,
            lookback=30,
            max_nan=5,
            aggregation=AggregationMethod.SUM,
        )
        assert v.aggregation == AggregationMethod.SUM

    def test_unit_required(self) -> None:
        with pytest.raises(ValidationError, match="unit"):
            PastKnownVariable.model_validate({"lookback": 1, "max_nan": 0})

    def test_lookback_zero(self) -> None:
        with pytest.raises(ValidationError, match="lookback must be positive"):
            PastKnownVariable(unit=Unit.M3_PER_S, lookback=0, max_nan=0)

    def test_lookback_negative(self) -> None:
        with pytest.raises(ValidationError, match="lookback must be positive"):
            PastKnownVariable(unit=Unit.M3_PER_S, lookback=-1, max_nan=0)

    def test_max_nan_negative(self) -> None:
        with pytest.raises(ValidationError, match="max_nan must be non-negative"):
            PastKnownVariable(unit=Unit.M3_PER_S, lookback=1, max_nan=-1)

    def test_max_nan_zero_allowed(self) -> None:
        v = PastKnownVariable(unit=Unit.M3_PER_S, lookback=1, max_nan=0)
        assert v.max_nan == 0


class TestFutureKnownVariable:
    def test_valid(self) -> None:
        v = FutureKnownVariable(
            unit=Unit.M3_PER_S,
            future_steps=10,
            max_nan=0,
            ensemble_mode=EnsembleMode.ENSEMBLE,
        )
        assert v.future_steps == 10
        assert v.ensemble_mode == EnsembleMode.ENSEMBLE
        assert v.unit == Unit.M3_PER_S
        assert v.aggregation is None

    def test_aggregation_override(self) -> None:
        v = FutureKnownVariable(
            unit=Unit.MM_PER_DAY,
            future_steps=10,
            max_nan=0,
            aggregation=AggregationMethod.MEAN,
        )
        assert v.aggregation == AggregationMethod.MEAN

    def test_unit_required(self) -> None:
        with pytest.raises(ValidationError, match="unit"):
            FutureKnownVariable.model_validate({"future_steps": 1, "max_nan": 0})

    def test_ensemble_mode_default_single(self) -> None:
        v = FutureKnownVariable(unit=Unit.M3_PER_S, future_steps=5, max_nan=0)
        assert v.ensemble_mode == EnsembleMode.SINGLE

    def test_future_steps_zero(self) -> None:
        with pytest.raises(ValidationError, match="future_steps must be positive"):
            FutureKnownVariable(unit=Unit.M3_PER_S, future_steps=0, max_nan=0)

    def test_future_steps_negative(self) -> None:
        with pytest.raises(ValidationError, match="future_steps must be positive"):
            FutureKnownVariable(unit=Unit.M3_PER_S, future_steps=-3, max_nan=0)

    def test_max_nan_negative(self) -> None:
        with pytest.raises(ValidationError, match="max_nan must be non-negative"):
            FutureKnownVariable(unit=Unit.M3_PER_S, future_steps=1, max_nan=-1)


# ---------------------------------------------------------------------------
# Target types
# ---------------------------------------------------------------------------


class TestOutputRepresentation:
    def test_members(self) -> None:
        assert OutputRepresentation.DETERMINISTIC.value == "deterministic"
        assert OutputRepresentation.QUANTILES.value == "quantiles"
        assert OutputRepresentation.TRAJECTORIES.value == "trajectories"
        assert len(OutputRepresentation) == 3


class TestTargetSpec:
    def test_valid(self) -> None:
        spec = TargetSpec(
            unit=Unit.M3_PER_S,
            representations=frozenset(
                {OutputRepresentation.QUANTILES, OutputRepresentation.TRAJECTORIES}
            ),
        )
        assert spec.unit == Unit.M3_PER_S
        assert OutputRepresentation.QUANTILES in spec.representations
        assert len(spec.representations) == 2

    def test_empty_representations_raises(self) -> None:
        with pytest.raises(ValidationError, match="at least one output representation"):
            TargetSpec(unit=Unit.M3_PER_S, representations=frozenset())

    def test_unit_required(self) -> None:
        with pytest.raises(ValidationError, match="unit"):
            TargetSpec.model_validate(
                {"representations": frozenset({OutputRepresentation.DETERMINISTIC})}
            )


# ---------------------------------------------------------------------------
# Spec containers
# ---------------------------------------------------------------------------


class TestDynamicInputSpec:
    def test_past_only(self) -> None:
        spec = DynamicInputSpec(
            past_known={
                "obs": {
                    "discharge": PastKnownVariable(
                        unit=Unit.M3_PER_S, lookback=30, max_nan=2
                    )
                }
            }
        )
        assert "obs" in spec.past_known
        assert spec.future_known == {}

    def test_future_only(self) -> None:
        spec = DynamicInputSpec(
            future_known={
                "GFS": {
                    "precip": FutureKnownVariable(
                        unit=Unit.M3_PER_S, future_steps=10, max_nan=0
                    )
                }
            }
        )
        assert "GFS" in spec.future_known
        assert spec.past_known == {}

    def test_empty_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="at least one of past_known or future_known"
        ):
            DynamicInputSpec()


class TestSpatialInputSpec:
    def test_basin_average_only(self) -> None:
        dynamic = DynamicInputSpec(
            past_known={
                "obs": {
                    "q": PastKnownVariable(unit=Unit.M3_PER_S, lookback=10, max_nan=0)
                }
            }
        )
        spec = SpatialInputSpec(data={SpatialRepresentation.BASIN_AVERAGE: dynamic})
        assert SpatialRepresentation.BASIN_AVERAGE in spec.data
        assert len(spec.data) == 1

    def test_gridded_only(self) -> None:
        dynamic = DynamicInputSpec(
            past_known={
                "ERA5": {
                    "swe": PastKnownVariable(unit=Unit.M3_PER_S, lookback=90, max_nan=5)
                }
            }
        )
        spec = SpatialInputSpec(data={SpatialRepresentation.GRIDDED: dynamic})
        assert SpatialRepresentation.GRIDDED in spec.data
        assert len(spec.data) == 1

    def test_elevation_band(self) -> None:
        dynamic = DynamicInputSpec(
            past_known={
                "SnowMapper": {
                    "swe": PastKnownVariable(unit=Unit.M3_PER_S, lookback=30, max_nan=2)
                }
            }
        )
        spec = SpatialInputSpec(data={SpatialRepresentation.ELEVATION_BAND: dynamic})
        assert SpatialRepresentation.ELEVATION_BAND in spec.data

    def test_both(self) -> None:
        basin = DynamicInputSpec(
            past_known={
                "obs": {
                    "q": PastKnownVariable(unit=Unit.M3_PER_S, lookback=10, max_nan=0)
                }
            }
        )
        gridded = DynamicInputSpec(
            past_known={
                "ERA5": {
                    "swe": PastKnownVariable(unit=Unit.M3_PER_S, lookback=90, max_nan=5)
                }
            }
        )
        spec = SpatialInputSpec(
            data={
                SpatialRepresentation.BASIN_AVERAGE: basin,
                SpatialRepresentation.GRIDDED: gridded,
            }
        )
        assert SpatialRepresentation.BASIN_AVERAGE in spec.data
        assert SpatialRepresentation.GRIDDED in spec.data
        assert len(spec.data) == 2

    def test_neither_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="at least one spatial representation"
        ):
            SpatialInputSpec(data={})


class TestSpatialRepresentation:
    def test_members(self) -> None:
        assert SpatialRepresentation.POINT.value == "point"
        assert SpatialRepresentation.BASIN_AVERAGE.value == "basin_average"
        assert SpatialRepresentation.ELEVATION_BAND.value == "elevation_band"
        assert SpatialRepresentation.GRIDDED.value == "gridded"
        assert len(SpatialRepresentation) == 4


# ---------------------------------------------------------------------------
# InputRequirement
# ---------------------------------------------------------------------------


class TestInputRequirement:
    def test_minimal(self) -> None:
        req = InputRequirement(
            targets=_target(),
            dynamic={
                DAILY: SpatialInputSpec(
                    data={
                        SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                            past_known={
                                "obs": {
                                    "discharge": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=365, max_nan=10
                                    )
                                }
                            }
                        )
                    }
                )
            },
        )
        assert DAILY in req.dynamic
        assert req.static == set()
        assert "discharge" in req.targets

    def test_with_static(self) -> None:
        req = InputRequirement(
            targets=_target(),
            dynamic={
                DAILY: SpatialInputSpec(
                    data={
                        SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                            past_known={
                                "obs": {
                                    "q": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=30, max_nan=0
                                    )
                                }
                            }
                        )
                    }
                )
            },
            static={"catchment_area", "mean_slope", "forest_fraction"},
        )
        assert len(req.static) == 3

    def test_empty_targets_raises(self) -> None:
        with pytest.raises(ValidationError, match="at least one entry"):
            InputRequirement(
                targets={},
                dynamic={
                    DAILY: SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S, lookback=1, max_nan=0
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
            )

    def test_whitespace_target_key_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="target variable names must be non-empty"
        ):
            InputRequirement(
                targets={
                    "  ": TargetSpec(
                        unit=Unit.M3_PER_S,
                        representations=frozenset({OutputRepresentation.QUANTILES}),
                    )
                },
                dynamic={
                    DAILY: SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S, lookback=1, max_nan=0
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
            )

    def test_empty_dynamic_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="dynamic must contain at least one time step"
        ):
            InputRequirement(targets=_target(), dynamic={})

    def test_zero_dynamic_time_step_rejected(self) -> None:
        with pytest.raises(ValidationError, match="time step keys must be positive"):
            InputRequirement(
                targets=_target(),
                dynamic={
                    timedelta(0): SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S,
                                            lookback=1,
                                            max_nan=0,
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
            )

    def test_negative_dynamic_time_step_rejected(self) -> None:
        with pytest.raises(ValidationError, match="time step keys must be positive"):
            InputRequirement(
                targets=_target(),
                dynamic={
                    timedelta(days=-1): SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S,
                                            lookback=1,
                                            max_nan=0,
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
            )

    def test_empty_static_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty strings"):
            InputRequirement(
                targets=_target(),
                dynamic={
                    DAILY: SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S, lookback=1, max_nan=0
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
                static={"valid", ""},
            )

    def test_duplicate_static_deduplicated(self) -> None:
        req = InputRequirement.model_validate(
            {
                "targets": _target(),
                "dynamic": {
                    DAILY: SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S, lookback=1, max_nan=0
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
                "static": [
                    "area",
                    "area",
                    "slope",
                ],  # list with duplicates, Pydantic coerces to set
            }
        )
        assert len(req.static) == 2

    def test_whitespace_static_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty strings"):
            InputRequirement(
                targets=_target(),
                dynamic={
                    DAILY: SpatialInputSpec(
                        data={
                            SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                                past_known={
                                    "obs": {
                                        "q": PastKnownVariable(
                                            unit=Unit.M3_PER_S, lookback=1, max_nan=0
                                        )
                                    }
                                }
                            )
                        }
                    )
                },
                static={"  "},
            )


# ---------------------------------------------------------------------------
# Full YAML example from docs/input_requirement.md
# ---------------------------------------------------------------------------


class TestFullYamlExample:
    """Construct the full example from the spec doc and verify roundtrip."""

    @pytest.fixture()
    def full_requirement(self) -> InputRequirement:
        return InputRequirement(
            targets={
                "discharge": TargetSpec(
                    unit=Unit.M3_PER_S,
                    representations=frozenset(
                        {
                            OutputRepresentation.QUANTILES,
                            OutputRepresentation.TRAJECTORIES,
                        }
                    ),
                )
            },
            dynamic={
                DAILY: SpatialInputSpec(
                    data={
                        SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                            past_known={
                                "obs": {
                                    "discharge": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=365, max_nan=10
                                    ),
                                    "precipitation": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=30, max_nan=5
                                    ),
                                }
                            },
                            future_known={
                                "GFS": {
                                    "precipitation": FutureKnownVariable(
                                        unit=Unit.M3_PER_S,
                                        future_steps=10,
                                        max_nan=0,
                                        ensemble_mode=EnsembleMode.ENSEMBLE,
                                    ),
                                    "temperature": FutureKnownVariable(
                                        unit=Unit.M3_PER_S,
                                        future_steps=10,
                                        max_nan=0,
                                        ensemble_mode=EnsembleMode.SINGLE,
                                    ),
                                },
                                "ECMWF": {
                                    "precipitation": FutureKnownVariable(
                                        unit=Unit.M3_PER_S,
                                        future_steps=15,
                                        max_nan=0,
                                        ensemble_mode=EnsembleMode.ENSEMBLE,
                                    ),
                                },
                            },
                        ),
                        SpatialRepresentation.GRIDDED: DynamicInputSpec(
                            past_known={
                                "ERA5": {
                                    "swe": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=90, max_nan=5
                                    ),
                                    "precipitation": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=30, max_nan=3
                                    ),
                                }
                            }
                        ),
                        SpatialRepresentation.ELEVATION_BAND: DynamicInputSpec(
                            future_known={
                                "SnowMapper": {
                                    "swe": FutureKnownVariable(
                                        unit=Unit.M3_PER_S,
                                        future_steps=10,
                                        max_nan=0,
                                        ensemble_mode=EnsembleMode.SINGLE,
                                    ),
                                    "rof": FutureKnownVariable(
                                        unit=Unit.M3_PER_S,
                                        future_steps=10,
                                        max_nan=0,
                                        ensemble_mode=EnsembleMode.SINGLE,
                                    ),
                                }
                            }
                        ),
                    }
                ),
                HOURLY: SpatialInputSpec(
                    data={
                        SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                            past_known={
                                "obs": {
                                    "discharge": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=72, max_nan=2
                                    ),
                                }
                            },
                            future_known={
                                "INCA": {
                                    "precipitation": FutureKnownVariable(
                                        unit=Unit.M3_PER_S,
                                        future_steps=48,
                                        max_nan=0,
                                        ensemble_mode=EnsembleMode.SINGLE,
                                    ),
                                }
                            },
                        )
                    }
                ),
            },
            static={"catchment_area", "mean_slope", "forest_fraction"},
        )

    def test_construction(self, full_requirement: InputRequirement) -> None:
        assert len(full_requirement.dynamic) == 2
        assert DAILY in full_requirement.dynamic
        assert HOURLY in full_requirement.dynamic
        assert len(full_requirement.static) == 3

    def test_targets(self, full_requirement: InputRequirement) -> None:
        discharge = full_requirement.targets["discharge"]
        assert discharge.unit == Unit.M3_PER_S
        assert OutputRepresentation.TRAJECTORIES in discharge.representations

    def test_daily_basin_average_past(self, full_requirement: InputRequirement) -> None:
        daily = full_requirement.dynamic[DAILY]
        basin = daily.data[SpatialRepresentation.BASIN_AVERAGE]
        obs = basin.past_known["obs"]
        assert obs["discharge"].lookback == 365
        assert obs["precipitation"].max_nan == 5

    def test_daily_basin_average_future(
        self, full_requirement: InputRequirement
    ) -> None:
        daily = full_requirement.dynamic[DAILY]
        basin = daily.data[SpatialRepresentation.BASIN_AVERAGE]
        gfs = basin.future_known["GFS"]
        assert gfs["precipitation"].ensemble_mode == EnsembleMode.ENSEMBLE
        assert gfs["temperature"].ensemble_mode == EnsembleMode.SINGLE
        ecmwf = basin.future_known["ECMWF"]
        assert ecmwf["precipitation"].future_steps == 15

    def test_daily_gridded_past(self, full_requirement: InputRequirement) -> None:
        daily = full_requirement.dynamic[DAILY]
        gridded = daily.data[SpatialRepresentation.GRIDDED]
        era5 = gridded.past_known["ERA5"]
        assert era5["swe"].lookback == 90

    def test_daily_elevation_band(self, full_requirement: InputRequirement) -> None:
        daily = full_requirement.dynamic[DAILY]
        band = daily.data[SpatialRepresentation.ELEVATION_BAND]
        snow = band.future_known["SnowMapper"]
        assert "swe" in snow
        assert "rof" in snow

    def test_hourly_block(self, full_requirement: InputRequirement) -> None:
        hourly = full_requirement.dynamic[HOURLY]
        assert SpatialRepresentation.BASIN_AVERAGE in hourly.data
        assert SpatialRepresentation.GRIDDED not in hourly.data
        basin = hourly.data[SpatialRepresentation.BASIN_AVERAGE]
        assert basin.past_known["obs"]["discharge"].lookback == 72
        assert basin.future_known["INCA"]["precipitation"].future_steps == 48

    def test_serialization_roundtrip(self, full_requirement: InputRequirement) -> None:
        json_str = full_requirement.model_dump_json()
        restored = InputRequirement.model_validate_json(json_str)
        assert restored == full_requirement

    def test_dict_roundtrip(self, full_requirement: InputRequirement) -> None:
        data = full_requirement.model_dump()
        restored = InputRequirement.model_validate(data)
        assert restored == full_requirement
