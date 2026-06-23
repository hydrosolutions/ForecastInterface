from datetime import datetime, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from forecast_interface.common import Unit
from forecast_interface.input import (
    DynamicInputs,
    InputSeries,
    ModelInputs,
    SpatialInputs,
    SpatialRepresentation,
    StationInputs,
)

DAILY = timedelta(days=1)
HOURLY = timedelta(hours=1)
DT1 = datetime(2024, 1, 1)
DT2 = datetime(2024, 1, 2)


def _single_df() -> pl.DataFrame:
    return pl.DataFrame({"datetime": [DT1], "value": [1.0]})


def _series() -> InputSeries:
    return InputSeries(unit=Unit.M3_PER_S, data=_single_df())


def _dynamic_inputs() -> DynamicInputs:
    return DynamicInputs(past_known={"obs": {"q": _series()}})


def _spatial_inputs() -> SpatialInputs:
    return SpatialInputs(data={SpatialRepresentation.BASIN_AVERAGE: _dynamic_inputs()})


def _station_inputs() -> StationInputs:
    return StationInputs(dynamic={DAILY: _spatial_inputs()})


class TestInputSeries:
    def test_valid_single(self) -> None:
        series = InputSeries(unit=Unit.M3_PER_S, data=_single_df())

        assert series.unit == Unit.M3_PER_S
        assert series.data.columns == ["datetime", "value"]

    def test_valid_ensemble(self) -> None:
        df = pl.DataFrame(
            {
                "datetime": [DT1, DT2],
                "1": [1.0, 2.0],
                "2": [2, 3],
                "3": [3.0, 4.0],
            }
        )

        series = InputSeries(unit=Unit.MM_PER_DAY, data=df)

        assert series.unit == Unit.MM_PER_DAY
        assert series.data.columns == ["datetime", "1", "2", "3"]

    def test_unit_required(self) -> None:
        with pytest.raises(ValidationError, match="unit"):
            InputSeries.model_validate({"data": _single_df()})

    def test_nan_in_value_accepted(self) -> None:
        df = pl.DataFrame({"datetime": [DT1], "value": [float("nan")]})

        series = InputSeries(unit=Unit.M3_PER_S, data=df)

        assert series.data["value"].is_nan().all()

    def test_missing_datetime_rejected(self) -> None:
        df = pl.DataFrame({"value": [1.0]})

        with pytest.raises(
            ValidationError, match="DataFrame must contain a 'datetime' column"
        ):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_wrong_datetime_dtype_rejected(self) -> None:
        df = pl.DataFrame({"datetime": ["2024-01-01"], "value": [1.0]})

        with pytest.raises(ValidationError, match="'datetime' column must be Datetime"):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_issue_datetime_column_rejected_by_name(self) -> None:
        df = pl.DataFrame(
            {
                "datetime": [DT1],
                "issue_datetime": [1_704_067_200],
                "value": [1.0],
            }
        )

        with pytest.raises(
            ValidationError, match="InputSeries data must not contain 'issue_datetime'"
        ):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_null_datetime_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "datetime": pl.Series("datetime", [DT1, None], dtype=pl.Datetime),
                "value": [1.0, 2.0],
            }
        )

        with pytest.raises(ValidationError, match="'datetime' values must not be null"):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_empty_rows_rejected(self) -> None:
        df = pl.DataFrame(
            schema={"datetime": pl.Datetime, "value": pl.Float64},
        )

        with pytest.raises(
            ValidationError, match="InputSeries data must contain at least one row"
        ):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_no_value_column_rejected(self) -> None:
        df = pl.DataFrame({"datetime": [DT1]})

        with pytest.raises(
            ValidationError,
            match="InputSeries data must contain at least one value column",
        ):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_stray_string_column_rejected(self) -> None:
        df = pl.DataFrame({"datetime": [DT1], "value": [1.0], "stray": ["abc"]})

        with pytest.raises(ValidationError, match="Column 'stray' must be numeric"):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_duplicate_datetimes_rejected(self) -> None:
        df = pl.DataFrame({"datetime": [DT1, DT1], "value": [1.0, 2.0]})

        with pytest.raises(ValidationError, match="'datetime' values must be unique"):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_unsorted_datetimes_rejected(self) -> None:
        df = pl.DataFrame({"datetime": [DT2, DT1], "value": [2.0, 1.0]})

        with pytest.raises(
            ValidationError, match="'datetime' values must be sorted ascending"
        ):
            InputSeries(unit=Unit.M3_PER_S, data=df)


class TestDynamicInputs:
    def test_past_only(self) -> None:
        inputs = DynamicInputs(past_known={"obs": {"q": _series()}})

        assert "obs" in inputs.past_known
        assert inputs.future_known == {}

    def test_future_only(self) -> None:
        inputs = DynamicInputs(future_known={"GFS": {"precip": _series()}})

        assert "GFS" in inputs.future_known
        assert inputs.past_known == {}

    def test_both(self) -> None:
        inputs = DynamicInputs(
            past_known={"obs": {"q": _series()}},
            future_known={"GFS": {"precip": _series()}},
        )

        assert "obs" in inputs.past_known
        assert "GFS" in inputs.future_known

    def test_empty_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="at least one of past_known or future_known"
        ):
            DynamicInputs()

    def test_product_variable_nesting_depth(self) -> None:
        series = _series()
        inputs = DynamicInputs(past_known={"obs": {"q": series}})

        assert inputs.past_known["obs"]["q"] is series


class TestSpatialInputs:
    def test_multiple_spatial_representations_accepted(self) -> None:
        inputs = SpatialInputs(
            data={
                SpatialRepresentation.BASIN_AVERAGE: _dynamic_inputs(),
                SpatialRepresentation.GRIDDED: _dynamic_inputs(),
            }
        )

        assert SpatialRepresentation.BASIN_AVERAGE in inputs.data
        assert SpatialRepresentation.GRIDDED in inputs.data

    def test_empty_data_rejected(self) -> None:
        with pytest.raises(
            ValidationError,
            match="data must contain at least one spatial representation",
        ):
            SpatialInputs(data={})


class TestStationInputs:
    def test_valid_dynamic(self) -> None:
        inputs = StationInputs(dynamic={DAILY: _spatial_inputs()})

        assert DAILY in inputs.dynamic
        assert inputs.static == {}

    def test_per_station_static_accepted(self) -> None:
        inputs = StationInputs(
            dynamic={DAILY: _spatial_inputs()},
            static={
                "catchment_area": 42.5,
                "elevation": 1200,
                "land_cover": "alpine",
            },
        )

        assert inputs.static["land_cover"] == "alpine"
        assert inputs.static["elevation"] == 1200

    def test_empty_dynamic_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="dynamic must contain at least one time step"
        ):
            StationInputs(dynamic={})

    def test_zero_dynamic_time_step_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="dynamic time step keys must be positive"
        ):
            StationInputs(dynamic={timedelta(0): _spatial_inputs()})

    def test_negative_dynamic_time_step_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="dynamic time step keys must be positive"
        ):
            StationInputs(dynamic={timedelta(days=-1): _spatial_inputs()})

    @pytest.mark.parametrize("name", ["", "   "])
    def test_empty_static_name_rejected(self, name: str) -> None:
        with pytest.raises(
            ValidationError, match="static input names must be non-empty strings"
        ):
            StationInputs(dynamic={DAILY: _spatial_inputs()}, static={name: 1.0})


class TestModelInputs:
    def test_single_station_bundle(self) -> None:
        inputs = ModelInputs(stations={"station_1": _station_inputs()})

        assert "station_1" in inputs.stations

    def test_multi_station_group_bundle_uses_same_type(self) -> None:
        inputs = ModelInputs(
            stations={
                "station_1": _station_inputs(),
                "station_2": StationInputs(dynamic={HOURLY: _spatial_inputs()}),
            }
        )

        assert len(inputs.stations) == 2
        assert HOURLY in inputs.stations["station_2"].dynamic

    def test_empty_stations_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="stations must contain at least one station"
        ):
            ModelInputs(stations={})

    @pytest.mark.parametrize("station_id", ["", "   "])
    def test_empty_station_key_rejected(self, station_id: str) -> None:
        with pytest.raises(
            ValidationError, match="station keys must be non-empty strings"
        ):
            ModelInputs(stations={station_id: _station_inputs()})


class TestExports:
    def test_input_exports(self) -> None:
        from forecast_interface.input import (
            DynamicInputs,
            InputSeries,
            ModelInputs,
            SpatialInputs,
            StationInputs,
        )

        assert DynamicInputs is not None
        assert InputSeries is not None
        assert ModelInputs is not None
        assert SpatialInputs is not None
        assert StationInputs is not None

    def test_top_level_exports(self) -> None:
        from forecast_interface import (
            DynamicInputs,
            InputSeries,
            ModelInputs,
            SpatialInputs,
            StationInputs,
        )

        assert DynamicInputs is not None
        assert InputSeries is not None
        assert ModelInputs is not None
        assert SpatialInputs is not None
        assert StationInputs is not None
