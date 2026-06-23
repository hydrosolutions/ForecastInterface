import datetime
from datetime import timedelta

import polars as pl
import pytest

from forecast_interface.common import AggregationMethod
from forecast_interface.output import (
    DeterministicData,
    EpistemicUncertaintyData,
    ForecastFlag,
    ModelOutput,
    QuantileData,
    TrajectoryData,
    Unit,
    VariableMetadata,
    VariableOutput,
    VariableStatus,
)

_ISSUE_DT = datetime.datetime(2024, 1, 1, 6, 0)
_DT1 = datetime.datetime(2024, 1, 1)
_DT2 = datetime.datetime(2024, 1, 2)


def _make_metadata(**overrides: object) -> VariableMetadata:
    defaults: dict[str, object] = {
        "unit": Unit.M3_PER_S,
        "timedelta": timedelta(days=1),
        "forecast_horizon": 2,
        "offset": 0,
    }
    defaults.update(overrides)
    return VariableMetadata.model_validate(defaults)


def _make_det_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "issue_datetime": [_ISSUE_DT, _ISSUE_DT],
            "datetime": [_DT1, _DT2],
            "value": [1.0, 2.0],
        }
    )


def _make_deterministic() -> DeterministicData:
    return DeterministicData(data=_make_det_df())


class TestUnit:
    def test_members_exist(self) -> None:
        assert Unit.M3_PER_S.value == "m³/s"
        assert Unit.MM_PER_DAY.value == "mm/day"
        assert Unit.MM_PER_S.value == "mm/s"
        assert Unit.MM.value == "mm"
        assert Unit.CM.value == "cm"
        assert Unit.M.value == "m"
        assert Unit.DEG_C.value == "°C"
        assert Unit.UNITLESS.value == "-"
        assert Unit.PERCENT.value == "%"
        assert Unit.M_PER_S.value == "m/s"
        assert Unit.DEGREE.value == "°"
        assert Unit.W_PER_M2.value == "W/m²"
        assert Unit.MM_PER_HOUR.value == "mm/hour"

    def test_member_count(self) -> None:
        assert len(Unit) == 13


class TestAggregationMethod:
    def test_members_exist(self) -> None:
        assert AggregationMethod.SUM.value == "sum"
        assert AggregationMethod.MEAN.value == "mean"

    def test_member_count(self) -> None:
        assert len(AggregationMethod) == 2


class TestVariableStatus:
    def test_members_exist(self) -> None:
        assert VariableStatus.SUCCESS is not None
        assert VariableStatus.FAILURE is not None
        assert VariableStatus.PARTIAL is not None

    def test_member_count(self) -> None:
        assert len(VariableStatus) == 3


class TestVariableMetadata:
    def test_valid_construction(self) -> None:
        meta = _make_metadata()
        assert meta.unit == Unit.M3_PER_S
        assert meta.timedelta == timedelta(days=1)
        assert meta.forecast_horizon == 2
        assert meta.offset == 0

    def test_zero_forecast_horizon_rejected(self) -> None:
        with pytest.raises(ValueError, match="forecast_horizon must be positive"):
            _make_metadata(forecast_horizon=0)

    def test_negative_forecast_horizon_rejected(self) -> None:
        with pytest.raises(ValueError, match="forecast_horizon must be positive"):
            _make_metadata(forecast_horizon=-5)

    def test_zero_timedelta_rejected(self) -> None:
        with pytest.raises(ValueError, match="timedelta must be positive"):
            _make_metadata(timedelta=timedelta(0))

    def test_negative_timedelta_rejected(self) -> None:
        with pytest.raises(ValueError, match="timedelta must be positive"):
            _make_metadata(timedelta=timedelta(days=-1))

    def test_negative_offset_rejected(self) -> None:
        with pytest.raises(ValueError, match="offset must be non-negative"):
            _make_metadata(offset=-1)

    def test_zero_offset_accepted(self) -> None:
        meta = _make_metadata(offset=0)
        assert meta.offset == 0


def _make_epistemic_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "issue_datetime": [_ISSUE_DT, _ISSUE_DT],
            "datetime": [_DT1, _DT2],
            "std": [0.5, 0.8],
            "range": [1.0, 1.6],
        }
    )


class TestForecastFlag:
    def test_members_exist(self) -> None:
        assert ForecastFlag.HIGH_EPISTEMIC_UNCERTAINTY is not None
        assert ForecastFlag.DATA_AVAILABILITY is not None

    def test_member_count(self) -> None:
        assert len(ForecastFlag) == 2


class TestEpistemicUncertaintyData:
    def test_valid_construction(self) -> None:
        eu = EpistemicUncertaintyData(data=_make_epistemic_df())
        assert eu.data.shape == (2, 4)
        assert eu.data.columns == ["issue_datetime", "datetime", "std", "range"]

    def test_missing_std_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "range": [1.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            EpistemicUncertaintyData(data=df)

    def test_missing_range_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "std": [0.5],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            EpistemicUncertaintyData(data=df)

    def test_extra_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "std": [0.5],
                "range": [1.0],
                "extra": [2.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            EpistemicUncertaintyData(data=df)

    def test_non_numeric_std_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "std": ["abc"],
                "range": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must be numeric"):
            EpistemicUncertaintyData(data=df)

    def test_non_temporal_datetime_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": ["2024-01-01"],
                "std": [0.5],
                "range": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must be Datetime"):
            EpistemicUncertaintyData(data=df)

    def test_non_temporal_issue_datetime_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": ["2024-01-01"],
                "datetime": [_DT1],
                "std": [0.5],
                "range": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must be Datetime"):
            EpistemicUncertaintyData(data=df)


class TestDeterministicData:
    def test_valid_construction(self) -> None:
        det = _make_deterministic()
        assert det.data.shape == (2, 3)
        assert det.data.columns == ["issue_datetime", "datetime", "value"]

    def test_missing_value_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "other": [1.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            DeterministicData(data=df)

    def test_missing_datetime_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "timestamp": [_DT1],
                "value": [1.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            DeterministicData(data=df)

    def test_extra_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "value": [1.0],
                "extra": [2.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            DeterministicData(data=df)

    def test_non_numeric_value_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "value": ["abc"],
            }
        )
        with pytest.raises(ValueError, match="must be numeric"):
            DeterministicData(data=df)

    def test_non_temporal_datetime_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": ["2024-01-01"],
                "value": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must be Datetime"):
            DeterministicData(data=df)

    def test_non_temporal_issue_datetime_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": ["2024-01-01"],
                "datetime": [_DT1],
                "value": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must be Datetime"):
            DeterministicData(data=df)


class TestQuantileData:
    def test_valid_construction(self) -> None:
        levels = [0.1, 0.5, 0.9]
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.5": [2.0],
                "0.9": [3.0],
            }
        )
        qd = QuantileData(quantile_levels=levels, data=df)
        assert qd.quantile_levels == levels
        assert qd.data.shape == (1, 5)

    def test_empty_levels_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
            }
        )
        with pytest.raises(ValueError, match="must contain at least 3 levels"):
            QuantileData(quantile_levels=[], data=df)

    def test_less_than_three_levels_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.9": [3.0],
            }
        )
        with pytest.raises(ValueError, match="must contain at least 3 levels"):
            QuantileData(quantile_levels=[0.1, 0.9], data=df)

    def test_level_zero_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.0": [1.0],
                "0.5": [2.0],
                "0.9": [3.0],
            }
        )
        with pytest.raises(ValueError, match="must be in \\(0, 1\\)"):
            QuantileData(quantile_levels=[0.0, 0.5, 0.9], data=df)

    def test_level_one_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.5": [2.0],
                "1.0": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must be in \\(0, 1\\)"):
            QuantileData(quantile_levels=[0.1, 0.5, 1.0], data=df)

    def test_unsorted_levels_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.9": [1.0],
                "0.1": [2.0],
                "0.5": [3.0],
            }
        )
        with pytest.raises(ValueError, match="must be sorted ascending"):
            QuantileData(quantile_levels=[0.9, 0.1, 0.5], data=df)

    def test_duplicate_levels_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.5": [1.0],
            }
        )
        with pytest.raises(ValueError, match="must not contain duplicates"):
            QuantileData(quantile_levels=[0.1, 0.5, 0.5], data=df)

    def test_column_mismatch_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.9": [3.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            QuantileData(quantile_levels=[0.1, 0.5, 0.9], data=df)

    def test_non_numeric_quantile_column_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.5": ["abc"],
                "0.9": [3.0],
            }
        )
        with pytest.raises(ValueError, match="must be numeric"):
            QuantileData(quantile_levels=[0.1, 0.5, 0.9], data=df)


class TestTrajectoryData:
    def test_valid_construction(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "1": [10.0],
                "2": [20.0],
                "3": [30.0],
                "4": [40.0],
                "5": [50.0],
                "6": [60.0],
                "7": [70.0],
                "8": [80.0],
            }
        )
        td = TrajectoryData(num_samples=8, data=df)
        assert td.num_samples == 8
        assert td.data.shape == (1, 10)

    def test_zero_samples_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
            }
        )
        with pytest.raises(ValueError, match="num_samples must be at least 8"):
            TrajectoryData(num_samples=0, data=df)

    def test_negative_samples_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
            }
        )
        with pytest.raises(ValueError, match="num_samples must be at least 8"):
            TrajectoryData(num_samples=-1, data=df)

    def test_less_than_eight_samples_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "1": [10.0],
                "2": [20.0],
                "3": [30.0],
                "4": [40.0],
                "5": [50.0],
                "6": [60.0],
                "7": [70.0],
            }
        )
        with pytest.raises(ValueError, match="num_samples must be at least 8"):
            TrajectoryData(num_samples=7, data=df)

    def test_column_count_mismatch_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "1": [10.0],
                "2": [20.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            TrajectoryData(num_samples=8, data=df)

    def test_wrong_column_names_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "a": [10.0],
                "b": [20.0],
            }
        )
        with pytest.raises(ValueError, match="Column mismatch"):
            TrajectoryData(num_samples=8, data=df)


class TestVariableOutput:
    def test_valid_deterministic_only(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            status=VariableStatus.SUCCESS,
        )
        assert vo.status == VariableStatus.SUCCESS
        assert vo.deterministic is not None
        assert vo.quantiles is None
        assert vo.trajectories is None

    def test_valid_quantiles_only(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "0.1": [1.0],
                "0.5": [2.0],
                "0.9": [3.0],
            }
        )
        vo = VariableOutput(
            metadata=_make_metadata(forecast_horizon=1),
            quantiles=QuantileData(quantile_levels=[0.1, 0.5, 0.9], data=df),
            status=VariableStatus.SUCCESS,
        )
        assert vo.quantiles is not None
        assert vo.deterministic is None

    def test_valid_trajectories_only(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "1": [10.0],
                "2": [20.0],
                "3": [30.0],
                "4": [40.0],
                "5": [50.0],
                "6": [60.0],
                "7": [70.0],
                "8": [80.0],
            }
        )
        vo = VariableOutput(
            metadata=_make_metadata(forecast_horizon=1),
            trajectories=TrajectoryData(num_samples=8, data=df),
            status=VariableStatus.SUCCESS,
        )
        assert vo.trajectories is not None
        assert vo.deterministic is None

    def test_valid_all_three(self) -> None:
        det = _make_deterministic()
        quant = QuantileData(
            quantile_levels=[0.1, 0.5, 0.9],
            data=pl.DataFrame(
                {
                    "issue_datetime": [_ISSUE_DT, _ISSUE_DT],
                    "datetime": [_DT1, _DT2],
                    "0.1": [1.0, 2.0],
                    "0.5": [2.0, 3.0],
                    "0.9": [3.0, 4.0],
                }
            ),
        )
        traj = TrajectoryData(
            num_samples=8,
            data=pl.DataFrame(
                {
                    "issue_datetime": [_ISSUE_DT, _ISSUE_DT],
                    "datetime": [_DT1, _DT2],
                    "1": [1.0, 2.0],
                    "2": [2.0, 3.0],
                    "3": [3.0, 4.0],
                    "4": [4.0, 5.0],
                    "5": [5.0, 6.0],
                    "6": [6.0, 7.0],
                    "7": [7.0, 8.0],
                    "8": [8.0, 9.0],
                }
            ),
        )
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=det,
            quantiles=quant,
            trajectories=traj,
            status=VariableStatus.SUCCESS,
        )
        assert vo.deterministic is not None
        assert vo.quantiles is not None
        assert vo.trajectories is not None

    def test_success_without_data_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one of"):
            VariableOutput(
                metadata=_make_metadata(),
                status=VariableStatus.SUCCESS,
            )

    def test_failure_without_data_accepted(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            status=VariableStatus.FAILURE,
        )
        assert vo.status == VariableStatus.FAILURE

    def test_partial_without_data_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one of"):
            VariableOutput(
                metadata=_make_metadata(),
                status=VariableStatus.PARTIAL,
            )

    def test_partial_with_data_accepted(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            status=VariableStatus.PARTIAL,
        )
        assert vo.status == VariableStatus.PARTIAL

    def test_partial_short_forecast_declares_smaller_horizon(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "value": [1.0],
            }
        )
        vo = VariableOutput(
            metadata=_make_metadata(forecast_horizon=1),
            deterministic=DeterministicData(data=df),
            status=VariableStatus.PARTIAL,
        )
        assert vo.metadata.forecast_horizon == 1

    def test_horizon_validator_passes_single_issue(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(forecast_horizon=2),
            deterministic=_make_deterministic(),
            status=VariableStatus.SUCCESS,
        )
        assert vo.deterministic is not None

    def test_horizon_validator_passes_batch_hindcast(self) -> None:
        issue_2 = datetime.datetime(2024, 1, 2, 6, 0)
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT, _ISSUE_DT, issue_2, issue_2],
                "datetime": [
                    _DT1,
                    _DT2,
                    datetime.datetime(2024, 1, 3),
                    datetime.datetime(2024, 1, 4),
                ],
                "value": [1.0, 2.0, 3.0, 4.0],
            }
        )
        vo = VariableOutput(
            metadata=_make_metadata(forecast_horizon=2),
            deterministic=DeterministicData(data=df),
            status=VariableStatus.SUCCESS,
        )
        assert vo.deterministic is not None

    def test_horizon_validator_rejects_mismatched_group_count(self) -> None:
        df = pl.DataFrame(
            {
                "issue_datetime": [_ISSUE_DT],
                "datetime": [_DT1],
                "value": [1.0],
            }
        )
        with pytest.raises(ValueError, match="rows per issue_datetime.*got 1"):
            VariableOutput(
                metadata=_make_metadata(forecast_horizon=2),
                deterministic=DeterministicData(data=df),
                status=VariableStatus.FAILURE,
            )

    def test_horizon_validator_rejects_empty_present_representation(self) -> None:
        df = pl.DataFrame(
            schema={
                "issue_datetime": pl.Datetime,
                "datetime": pl.Datetime,
                "value": pl.Float64,
            }
        )
        with pytest.raises(ValueError, match="deterministic data must not be empty"):
            VariableOutput(
                metadata=_make_metadata(forecast_horizon=1),
                deterministic=DeterministicData(data=df),
                status=VariableStatus.FAILURE,
            )

    def test_epistemic_uncertainty_accepted(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            epistemic_uncertainty=EpistemicUncertaintyData(data=_make_epistemic_df()),
            status=VariableStatus.SUCCESS,
        )
        assert vo.epistemic_uncertainty is not None

    def test_epistemic_uncertainty_alone_does_not_satisfy_success(self) -> None:
        with pytest.raises(ValueError, match="at least one of"):
            VariableOutput(
                metadata=_make_metadata(),
                epistemic_uncertainty=EpistemicUncertaintyData(
                    data=_make_epistemic_df()
                ),
                status=VariableStatus.SUCCESS,
            )

    def test_flags_default_empty(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            status=VariableStatus.SUCCESS,
        )
        assert vo.flags == frozenset()

    def test_trusted_true_when_no_flags(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            status=VariableStatus.SUCCESS,
        )
        assert vo.trusted is True

    def test_trusted_false_when_flags_present(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            flags=frozenset({ForecastFlag.HIGH_EPISTEMIC_UNCERTAINTY}),
            status=VariableStatus.SUCCESS,
        )
        assert vo.trusted is False

    def test_multiple_flags(self) -> None:
        vo = VariableOutput(
            metadata=_make_metadata(),
            deterministic=_make_deterministic(),
            flags=frozenset(
                {
                    ForecastFlag.HIGH_EPISTEMIC_UNCERTAINTY,
                    ForecastFlag.DATA_AVAILABILITY,
                }
            ),
            status=VariableStatus.SUCCESS,
        )
        assert len(vo.flags) == 2
        assert vo.trusted is False


class TestModelOutput:
    def _make_variable_output(
        self, status: VariableStatus = VariableStatus.SUCCESS
    ) -> VariableOutput:
        if status in (VariableStatus.SUCCESS, VariableStatus.PARTIAL):
            return VariableOutput(
                metadata=_make_metadata(),
                deterministic=_make_deterministic(),
                status=status,
            )
        return VariableOutput(
            metadata=_make_metadata(),
            status=status,
        )

    def test_valid_single_station(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={"station_1": {"discharge": self._make_variable_output()}},
        )
        assert mo.model_name == "test_model"
        assert len(mo.variables) == 1
        assert len(mo.variables["station_1"]) == 1

    def test_valid_multi_station(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {"discharge": self._make_variable_output()},
                "station_2": {"discharge": self._make_variable_output()},
            },
        )
        assert len(mo.variables) == 2

    def test_multiple_variables_per_station(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {
                    "discharge": self._make_variable_output(),
                    "temperature": self._make_variable_output(),
                },
            },
        )
        assert len(mo.variables["station_1"]) == 2

    def test_success_all_success(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {"a": self._make_variable_output(VariableStatus.SUCCESS)},
                "station_2": {"b": self._make_variable_output(VariableStatus.SUCCESS)},
            },
        )
        assert mo.success is True

    def test_success_false_when_any_failure(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {"a": self._make_variable_output(VariableStatus.SUCCESS)},
                "station_2": {"b": self._make_variable_output(VariableStatus.FAILURE)},
            },
        )
        assert mo.success is False

    def test_success_false_when_any_partial(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {
                    "a": self._make_variable_output(VariableStatus.SUCCESS),
                    "b": self._make_variable_output(VariableStatus.PARTIAL),
                },
            },
        )
        assert mo.success is False

    def test_explicit_failure_station_makes_success_false(self) -> None:
        # A station with no usable data is echoed back as an explicit FAILURE
        # entry, never an absent key; this still constructs but flips success.
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {"discharge": self._make_variable_output()},
                "station_2": {
                    "discharge": self._make_variable_output(VariableStatus.FAILURE)
                },
            },
        )
        assert mo.success is False
        assert mo.variables["station_2"]["discharge"].status == VariableStatus.FAILURE

    def test_roundtrip_preserves_nested_shape(self) -> None:
        mo = ModelOutput(
            model_name="test_model",
            issue_datetime=datetime.datetime(2024, 1, 1),
            variables={
                "station_1": {
                    "discharge": self._make_variable_output(VariableStatus.FAILURE)
                },
            },
        )
        restored = ModelOutput.model_validate(mo.model_dump())
        assert set(restored.variables) == {"station_1"}
        assert set(restored.variables["station_1"]) == {"discharge"}
        assert restored.success is False

    def test_empty_model_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="model_name must be a non-empty string"):
            ModelOutput(
                model_name="",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"station_1": {"discharge": self._make_variable_output()}},
            )

    def test_whitespace_model_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="model_name must be a non-empty string"):
            ModelOutput(
                model_name="   ",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"station_1": {"discharge": self._make_variable_output()}},
            )

    def test_empty_variables_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one station"):
            ModelOutput(
                model_name="test_model",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={},
            )

    def test_empty_station_map_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one variable"):
            ModelOutput(
                model_name="test_model",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"station_1": {}},
            )

    def test_empty_station_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="station id keys must be non-empty"):
            ModelOutput(
                model_name="test_model",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"": {"discharge": self._make_variable_output()}},
            )

    def test_whitespace_station_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="station id keys must be non-empty"):
            ModelOutput(
                model_name="test_model",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"   ": {"discharge": self._make_variable_output()}},
            )

    def test_empty_variable_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="variable name keys must be non-empty"):
            ModelOutput(
                model_name="test_model",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"station_1": {"": self._make_variable_output()}},
            )

    def test_whitespace_variable_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="variable name keys must be non-empty"):
            ModelOutput(
                model_name="test_model",
                issue_datetime=datetime.datetime(2024, 1, 1),
                variables={"station_1": {"   ": self._make_variable_output()}},
            )
