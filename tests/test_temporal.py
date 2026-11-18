import datetime
from datetime import timedelta

import polars as pl
import pytest

from forecast_interface.common.temporal import exact_nanoseconds, validate_on_grid

_UTC = datetime.timezone.utc


def _series(*values: datetime.datetime) -> pl.Series:
    return pl.Series("datetime", list(values), dtype=pl.Datetime("us", "UTC"))


class TestExactNanoseconds:
    def test_converts_whole_days_and_microseconds(self) -> None:
        assert exact_nanoseconds(timedelta(days=1, microseconds=1)) == (
            86_400 * 10**9 + 1000
        )

    def test_negative_timedelta(self) -> None:
        assert exact_nanoseconds(timedelta(seconds=-1)) == -(10**9)

    def test_zero(self) -> None:
        assert exact_nanoseconds(timedelta(0)) == 0


class TestValidateOnGrid:
    def test_accepts_daily_at_18_origin(self) -> None:
        s = _series(
            datetime.datetime(2024, 1, 1, 18, tzinfo=_UTC),
            datetime.datetime(2024, 1, 2, 18, tzinfo=_UTC),
        )
        validate_on_grid(s, timedelta(days=1), timedelta(hours=18), "datetime")

    def test_rejects_fifteen_minutes_off(self) -> None:
        s = _series(datetime.datetime(2024, 1, 1, 18, 15, tzinfo=_UTC))
        with pytest.raises(ValueError, match="off the declared grid"):
            validate_on_grid(s, timedelta(days=1), timedelta(hours=18), "datetime")

    def test_accepts_three_hourly_with_phase(self) -> None:
        s = _series(
            datetime.datetime(2024, 1, 1, 1, tzinfo=_UTC),
            datetime.datetime(2024, 1, 1, 4, tzinfo=_UTC),
        )
        validate_on_grid(s, timedelta(hours=3), timedelta(hours=1), "datetime")

    def test_rejects_three_hourly_wrong_phase(self) -> None:
        s = _series(datetime.datetime(2024, 1, 1, 3, tzinfo=_UTC))
        with pytest.raises(ValueError, match="off the declared grid"):
            validate_on_grid(s, timedelta(hours=3), timedelta(hours=1), "datetime")

    def test_accepts_pre_1970_on_grid_timestamp(self) -> None:
        s = _series(datetime.datetime(1969, 12, 31, 18, tzinfo=_UTC))
        validate_on_grid(s, timedelta(days=1), timedelta(hours=18), "datetime")

    def test_rejects_pre_1970_off_grid_timestamp(self) -> None:
        s = _series(datetime.datetime(1969, 12, 31, 17, tzinfo=_UTC))
        with pytest.raises(ValueError, match="off the declared grid"):
            validate_on_grid(s, timedelta(days=1), timedelta(hours=18), "datetime")

    def test_rejects_when_only_one_of_many_is_off(self) -> None:
        good = [datetime.datetime(2024, 1, d, 18, tzinfo=_UTC) for d in (1, 2, 4)]
        bad = datetime.datetime(2024, 1, 3, 19, tzinfo=_UTC)
        s = _series(*good, bad)
        with pytest.raises(ValueError, match="2024-01-03 19:00"):
            validate_on_grid(s, timedelta(days=1), timedelta(hours=18), "datetime")
