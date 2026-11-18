from datetime import timedelta

import pytest
from pydantic import ValidationError

from forecast_interface.common import (
    AggregationMethod,
    Compatibility,
    GridDeclaration,
    GridMismatchError,
    PeriodLabel,
    TimeAnchor,
    TimeGrid,
    TrainingGridDeclaration,
    Unknown,
    compatibility,
    require_compatible,
    validate_divides_day,
    validate_whole_minutes,
)

DAY = timedelta(days=1)
H = timedelta(hours=1)


def _grid(
    step: timedelta = DAY,
    origin: timedelta = timedelta(0),
    label: PeriodLabel = PeriodLabel.START,
) -> TimeGrid:
    return TimeGrid(step, origin, label)


class TestValidateWholeMinutes:
    def test_accepts_whole_minutes(self) -> None:
        validate_whole_minutes(timedelta(minutes=15), "x")

    def test_rejects_sub_minute_remainder(self) -> None:
        with pytest.raises(ValueError, match="whole number of minutes"):
            validate_whole_minutes(timedelta(minutes=1, seconds=1), "x")


class TestValidateDividesDay:
    @pytest.mark.parametrize("step", [H, 3 * H, DAY, timedelta(minutes=15)])
    def test_accepts_divisors_of_a_day(self, step: timedelta) -> None:
        validate_divides_day(step, "step")

    def test_rejects_non_divisor(self) -> None:
        with pytest.raises(ValueError, match="divide 24 hours"):
            validate_divides_day(7 * H, "step")

    def test_rejects_multi_day_step(self) -> None:
        with pytest.raises(ValueError, match="divide 24 hours"):
            validate_divides_day(2 * DAY, "step")


class TestTimeGrid:
    def test_utc_midnight_origin_is_valid(self) -> None:
        assert _grid().origin == timedelta(0)

    def test_18h_origin_on_daily_step_is_valid(self) -> None:
        assert _grid(origin=timedelta(hours=18)).origin == timedelta(hours=18)

    def test_three_hourly_with_phase_is_valid(self) -> None:
        g = _grid(step=3 * H, origin=timedelta(hours=1))
        assert g.step == 3 * H

    def test_unknown_label_is_allowed(self) -> None:
        assert _grid(label=PeriodLabel.UNKNOWN).label is PeriodLabel.UNKNOWN

    def test_origin_equal_to_step_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="origin"):
            _grid(step=H, origin=H)

    def test_negative_origin_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="origin"):
            _grid(origin=timedelta(minutes=-1))

    def test_origin_with_59_second_remainder_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="whole number of minutes"):
            _grid(origin=timedelta(minutes=5, seconds=59))

    def test_sub_minute_step_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="whole number of minutes"):
            _grid(step=timedelta(seconds=90))

    def test_zero_step_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _grid(step=timedelta(0))

    def test_negative_step_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _grid(step=-H)

    def test_step_not_dividing_day_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="divide 24 hours"):
            _grid(step=7 * H)

    def test_string_label_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="PeriodLabel"):
            _grid(label="start")  # type: ignore[arg-type]

    def test_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            _grid().step = H  # type: ignore[misc]


class TestTimeAnchor:
    def test_defaults_are_unknown(self) -> None:
        a = TimeAnchor()
        assert a.origin is Unknown.UNKNOWN
        assert a.label is PeriodLabel.UNKNOWN

    def test_accepts_declared_origin(self) -> None:
        assert TimeAnchor(origin=timedelta(hours=18)).origin == timedelta(hours=18)

    def test_rejects_negative_origin(self) -> None:
        with pytest.raises(ValidationError, match=">= 0"):
            TimeAnchor(origin=timedelta(minutes=-1))

    def test_rejects_sub_minute_origin(self) -> None:
        with pytest.raises(ValidationError, match="whole number of minutes"):
            TimeAnchor(origin=timedelta(seconds=30))

    def test_is_immutable(self) -> None:
        with pytest.raises(ValidationError):
            TimeAnchor().label = PeriodLabel.END  # type: ignore[misc]


class TestCompatibility:
    def test_equal_grids_are_compatible(self) -> None:
        assert compatibility(_grid(), _grid()) is Compatibility.COMPATIBLE

    @pytest.mark.parametrize(
        "other",
        [
            _grid(step=H),
            _grid(origin=timedelta(hours=18)),
            _grid(label=PeriodLabel.END),
        ],
    )
    def test_single_differing_field_is_mismatch(self, other: TimeGrid) -> None:
        assert compatibility(_grid(), other) is Compatibility.MISMATCH

    def test_unknown_on_either_side_is_unknown(self) -> None:
        assert compatibility(Unknown.UNKNOWN, _grid()) is Compatibility.UNKNOWN
        assert compatibility(_grid(), Unknown.UNKNOWN) is Compatibility.UNKNOWN
        assert compatibility(Unknown.UNKNOWN, Unknown.UNKNOWN) is Compatibility.UNKNOWN

    def test_equal_step_origin_with_unknown_label_is_unknown(self) -> None:
        unlabelled = _grid(label=PeriodLabel.UNKNOWN)
        assert compatibility(_grid(), unlabelled) is Compatibility.UNKNOWN
        assert compatibility(unlabelled, _grid()) is Compatibility.UNKNOWN
        assert compatibility(unlabelled, unlabelled) is Compatibility.UNKNOWN

    def test_differing_origin_with_unknown_label_is_mismatch(self) -> None:
        other = _grid(origin=timedelta(hours=1), label=PeriodLabel.UNKNOWN)
        assert compatibility(_grid(), other) is Compatibility.MISMATCH

    def test_no_tolerance_between_18_00_and_18_15(self) -> None:
        a = _grid(origin=timedelta(hours=18))
        b = _grid(origin=timedelta(hours=18, minutes=15))
        assert compatibility(a, b) is Compatibility.MISMATCH


class TestGridMismatchError:
    def test_differences_name_exactly_the_differing_fields(self) -> None:
        deployment = _grid(step=H, origin=timedelta(0))
        declared = _grid(step=H, origin=timedelta(minutes=30), label=PeriodLabel.END)
        with pytest.raises(GridMismatchError) as exc:
            require_compatible(deployment, declared)
        assert exc.value.differences == ("origin", "label")

    def test_message_names_fields_and_values(self) -> None:
        with pytest.raises(GridMismatchError, match="step") as exc:
            require_compatible(_grid(step=H), _grid(step=3 * H))
        assert exc.value.differences == ("step",)
        assert "3:00:00" in str(exc.value)

    def test_is_a_value_error(self) -> None:
        assert issubclass(GridMismatchError, ValueError)


class TestRequireCompatible:
    def test_returns_compatible(self) -> None:
        assert require_compatible(_grid(), _grid()) is Compatibility.COMPATIBLE

    def test_returns_unknown_without_raising(self) -> None:
        assert require_compatible(Unknown.UNKNOWN, _grid()) is Compatibility.UNKNOWN
        unlabelled = _grid(label=PeriodLabel.UNKNOWN)
        assert require_compatible(_grid(), unlabelled) is Compatibility.UNKNOWN

    def test_raises_on_mismatch(self) -> None:
        with pytest.raises(GridMismatchError, match="origin"):
            require_compatible(_grid(), _grid(origin=H))


class TestTrainingGridDeclaration:
    @pytest.mark.parametrize(
        "grid",
        [_grid(origin=timedelta(hours=18), label=PeriodLabel.END), Unknown.UNKNOWN],
    )
    def test_json_round_trip(self, grid: GridDeclaration) -> None:
        decl = TrainingGridDeclaration(grid=grid)
        restored = TrainingGridDeclaration.model_validate_json(decl.model_dump_json())
        assert restored == decl
        assert type(restored.grid) is type(grid)

    def test_defaults_to_unknown_version_1(self) -> None:
        decl = TrainingGridDeclaration()
        assert decl.grid is Unknown.UNKNOWN
        assert decl.version == 1

    def test_rejects_other_versions(self) -> None:
        with pytest.raises(ValidationError, match="version"):
            TrainingGridDeclaration.model_validate({"version": 2})

    def test_is_immutable(self) -> None:
        with pytest.raises(ValidationError):
            TrainingGridDeclaration().grid = _grid()  # type: ignore[misc]


class TestAggregationMethodAdditions:
    def test_has_min_and_point(self) -> None:
        assert AggregationMethod.MIN.value == "min"
        assert AggregationMethod.POINT.value == "point"
