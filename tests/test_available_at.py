from datetime import UTC, datetime

import polars as pl
import pytest

from forecast_interface.common import Unit
from forecast_interface.input import InputSeries


def _frame(**extra: pl.Series) -> pl.DataFrame:
    t = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
    return pl.DataFrame({"datetime": t, "q": [1.0, 2.0], **extra}).with_columns(
        pl.col("datetime").cast(pl.Datetime("us", "UTC"))
    )


class TestAvailableAtColumn:
    def test_integer_column_accepted(self) -> None:
        df = _frame(available_at_us=pl.Series([1, 2], dtype=pl.Int64))
        assert InputSeries(unit=Unit.M3_PER_S, data=df).data.columns == [
            "datetime",
            "q",
            "available_at_us",
        ]

    def test_null_entries_accepted(self) -> None:
        df = _frame(available_at_us=pl.Series([1, None], dtype=pl.Int64))
        InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_float_column_rejected(self) -> None:
        df = _frame(available_at_us=pl.Series([1.0, 2.0]))
        with pytest.raises(ValueError, match="integer"):
            InputSeries(unit=Unit.M3_PER_S, data=df)

    def test_datetime_column_rejected(self) -> None:
        t = pl.Series([datetime(2026, 1, 1, tzinfo=UTC)] * 2).cast(
            pl.Datetime("us", "UTC")
        )
        with pytest.raises(ValueError, match="integer"):
            InputSeries(unit=Unit.M3_PER_S, data=_frame(available_at_us=t))

    def test_not_a_value_column(self) -> None:
        df = _frame(available_at_us=pl.Series([1, 2], dtype=pl.Int64)).drop("q")
        with pytest.raises(ValueError, match="value column"):
            InputSeries(unit=Unit.M3_PER_S, data=df)
