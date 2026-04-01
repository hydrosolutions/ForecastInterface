import pytest
from pydantic import ValidationError

from forecast_interface.input import (
    DynamicInputSpec,
    EnsembleMode,
    FutureKnownVariable,
    InputRequirement,
    PastKnownVariable,
    TemporalResolution,
    SpatialInputSpec,
    SpatialResolution,
)


# ---------------------------------------------------------------------------
# Variable types
# ---------------------------------------------------------------------------


class TestPastKnownVariable:
    def test_valid(self) -> None:
        v = PastKnownVariable(lookback=30, max_nan=5)
        assert v.lookback == 30
        assert v.max_nan == 5

    def test_lookback_zero(self) -> None:
        with pytest.raises(ValidationError, match="lookback must be positive"):
            PastKnownVariable(lookback=0, max_nan=0)

    def test_lookback_negative(self) -> None:
        with pytest.raises(ValidationError, match="lookback must be positive"):
            PastKnownVariable(lookback=-1, max_nan=0)

    def test_max_nan_negative(self) -> None:
        with pytest.raises(ValidationError, match="max_nan must be non-negative"):
            PastKnownVariable(lookback=1, max_nan=-1)

    def test_max_nan_zero_allowed(self) -> None:
        v = PastKnownVariable(lookback=1, max_nan=0)
        assert v.max_nan == 0


class TestFutureKnownVariable:
    def test_valid(self) -> None:
        v = FutureKnownVariable(
            future_steps=10, max_nan=0, ensemble_mode=EnsembleMode.ENSEMBLE
        )
        assert v.future_steps == 10
        assert v.ensemble_mode == EnsembleMode.ENSEMBLE

    def test_ensemble_mode_default_single(self) -> None:
        v = FutureKnownVariable(future_steps=5, max_nan=0)
        assert v.ensemble_mode == EnsembleMode.SINGLE

    def test_future_steps_zero(self) -> None:
        with pytest.raises(ValidationError, match="future_steps must be positive"):
            FutureKnownVariable(future_steps=0, max_nan=0)

    def test_future_steps_negative(self) -> None:
        with pytest.raises(ValidationError, match="future_steps must be positive"):
            FutureKnownVariable(future_steps=-3, max_nan=0)

    def test_max_nan_negative(self) -> None:
        with pytest.raises(ValidationError, match="max_nan must be non-negative"):
            FutureKnownVariable(future_steps=1, max_nan=-1)


# ---------------------------------------------------------------------------
# Spec containers
# ---------------------------------------------------------------------------


class TestDynamicInputSpec:
    def test_past_only(self) -> None:
        spec = DynamicInputSpec(
            past_known={"obs": {"discharge": PastKnownVariable(lookback=30, max_nan=2)}}
        )
        assert "obs" in spec.past_known
        assert spec.future_known == {}

    def test_future_only(self) -> None:
        spec = DynamicInputSpec(
            future_known={
                "GFS": {"precip": FutureKnownVariable(future_steps=10, max_nan=0)}
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
    def test_lumped_only(self) -> None:
        dynamic = DynamicInputSpec(
            past_known={"obs": {"q": PastKnownVariable(lookback=10, max_nan=0)}}
        )
        spec = SpatialInputSpec(lumped=dynamic)
        assert spec.lumped is not None
        assert spec.distributed is None

    def test_distributed_only(self) -> None:
        dynamic = DynamicInputSpec(
            past_known={"ERA5": {"swe": PastKnownVariable(lookback=90, max_nan=5)}}
        )
        spec = SpatialInputSpec(distributed=dynamic)
        assert spec.distributed is not None

    def test_both(self) -> None:
        lumped = DynamicInputSpec(
            past_known={"obs": {"q": PastKnownVariable(lookback=10, max_nan=0)}}
        )
        distributed = DynamicInputSpec(
            past_known={"ERA5": {"swe": PastKnownVariable(lookback=90, max_nan=5)}}
        )
        spec = SpatialInputSpec(lumped=lumped, distributed=distributed)
        assert spec.lumped is not None
        assert spec.distributed is not None

    def test_neither_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="at least one of distributed or lumped"
        ):
            SpatialInputSpec()


class TestSpatialResolution:
    def test_members(self) -> None:
        assert SpatialResolution.DISTRIBUTED.value == "distributed"
        assert SpatialResolution.LUMPED.value == "lumped"
        assert len(SpatialResolution) == 2


# ---------------------------------------------------------------------------
# InputRequirement
# ---------------------------------------------------------------------------


class TestInputRequirement:
    def test_minimal(self) -> None:
        req = InputRequirement(
            dynamic={
                TemporalResolution.DAILY: SpatialInputSpec(
                    lumped=DynamicInputSpec(
                        past_known={
                            "obs": {
                                "discharge": PastKnownVariable(lookback=365, max_nan=10)
                            }
                        }
                    )
                )
            }
        )
        assert TemporalResolution.DAILY in req.dynamic
        assert req.static == set()

    def test_with_static(self) -> None:
        req = InputRequirement(
            dynamic={
                TemporalResolution.DAILY: SpatialInputSpec(
                    lumped=DynamicInputSpec(
                        past_known={
                            "obs": {"q": PastKnownVariable(lookback=30, max_nan=0)}
                        }
                    )
                )
            },
            static={"catchment_area", "mean_slope", "forest_fraction"},
        )
        assert len(req.static) == 3

    def test_empty_dynamic_raises(self) -> None:
        with pytest.raises(ValidationError, match="at least one temporal resolution"):
            InputRequirement(dynamic={})

    def test_empty_static_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty strings"):
            InputRequirement(
                dynamic={
                    TemporalResolution.DAILY: SpatialInputSpec(
                        lumped=DynamicInputSpec(
                            past_known={
                                "obs": {"q": PastKnownVariable(lookback=1, max_nan=0)}
                            }
                        )
                    )
                },
                static={"valid", ""},
            )

    def test_duplicate_static_deduplicated(self) -> None:
        req = InputRequirement(
            dynamic={
                TemporalResolution.DAILY: SpatialInputSpec(
                    lumped=DynamicInputSpec(
                        past_known={
                            "obs": {"q": PastKnownVariable(lookback=1, max_nan=0)}
                        }
                    )
                )
            },
            static=[
                "area",
                "area",
                "slope",
            ],  # list with duplicates, Pydantic coerces to set
        )
        assert len(req.static) == 2

    def test_whitespace_static_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty strings"):
            InputRequirement(
                dynamic={
                    TemporalResolution.DAILY: SpatialInputSpec(
                        lumped=DynamicInputSpec(
                            past_known={
                                "obs": {"q": PastKnownVariable(lookback=1, max_nan=0)}
                            }
                        )
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
            dynamic={
                TemporalResolution.DAILY: SpatialInputSpec(
                    lumped=DynamicInputSpec(
                        past_known={
                            "obs": {
                                "discharge": PastKnownVariable(
                                    lookback=365, max_nan=10
                                ),
                                "precipitation": PastKnownVariable(
                                    lookback=30, max_nan=5
                                ),
                            }
                        },
                        future_known={
                            "GFS": {
                                "precipitation": FutureKnownVariable(
                                    future_steps=10,
                                    max_nan=0,
                                    ensemble_mode=EnsembleMode.ENSEMBLE,
                                ),
                                "temperature": FutureKnownVariable(
                                    future_steps=10,
                                    max_nan=0,
                                    ensemble_mode=EnsembleMode.SINGLE,
                                ),
                            },
                            "ECMWF": {
                                "precipitation": FutureKnownVariable(
                                    future_steps=15,
                                    max_nan=0,
                                    ensemble_mode=EnsembleMode.ENSEMBLE,
                                ),
                            },
                        },
                    ),
                    distributed=DynamicInputSpec(
                        past_known={
                            "ERA5": {
                                "swe": PastKnownVariable(lookback=90, max_nan=5),
                                "precipitation": PastKnownVariable(
                                    lookback=30, max_nan=3
                                ),
                            }
                        }
                    ),
                ),
                TemporalResolution.HOURLY: SpatialInputSpec(
                    lumped=DynamicInputSpec(
                        past_known={
                            "obs": {
                                "discharge": PastKnownVariable(lookback=72, max_nan=2),
                            }
                        },
                        future_known={
                            "INCA": {
                                "precipitation": FutureKnownVariable(
                                    future_steps=48,
                                    max_nan=0,
                                    ensemble_mode=EnsembleMode.SINGLE,
                                ),
                            }
                        },
                    )
                ),
            },
            static={"catchment_area", "mean_slope", "forest_fraction"},
        )

    def test_construction(self, full_requirement: InputRequirement) -> None:
        assert len(full_requirement.dynamic) == 2
        assert TemporalResolution.DAILY in full_requirement.dynamic
        assert TemporalResolution.HOURLY in full_requirement.dynamic
        assert len(full_requirement.static) == 3

    def test_daily_lumped_past(self, full_requirement: InputRequirement) -> None:
        daily = full_requirement.dynamic[TemporalResolution.DAILY]
        assert daily.lumped is not None
        obs = daily.lumped.past_known["obs"]
        assert obs["discharge"].lookback == 365
        assert obs["precipitation"].max_nan == 5

    def test_daily_lumped_future(self, full_requirement: InputRequirement) -> None:
        daily = full_requirement.dynamic[TemporalResolution.DAILY]
        assert daily.lumped is not None
        gfs = daily.lumped.future_known["GFS"]
        assert gfs["precipitation"].ensemble_mode == EnsembleMode.ENSEMBLE
        assert gfs["temperature"].ensemble_mode == EnsembleMode.SINGLE
        ecmwf = daily.lumped.future_known["ECMWF"]
        assert ecmwf["precipitation"].future_steps == 15

    def test_daily_distributed_past(self, full_requirement: InputRequirement) -> None:
        daily = full_requirement.dynamic[TemporalResolution.DAILY]
        assert daily.distributed is not None
        era5 = daily.distributed.past_known["ERA5"]
        assert era5["swe"].lookback == 90

    def test_hourly_block(self, full_requirement: InputRequirement) -> None:
        hourly = full_requirement.dynamic[TemporalResolution.HOURLY]
        assert hourly.lumped is not None
        assert hourly.distributed is None
        assert hourly.lumped.past_known["obs"]["discharge"].lookback == 72
        assert hourly.lumped.future_known["INCA"]["precipitation"].future_steps == 48

    def test_serialization_roundtrip(self, full_requirement: InputRequirement) -> None:
        json_str = full_requirement.model_dump_json()
        restored = InputRequirement.model_validate_json(json_str)
        assert restored == full_requirement

    def test_dict_roundtrip(self, full_requirement: InputRequirement) -> None:
        data = full_requirement.model_dump()
        restored = InputRequirement.model_validate(data)
        assert restored == full_requirement
