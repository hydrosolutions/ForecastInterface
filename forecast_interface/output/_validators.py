import datetime

import polars as pl
from polars.exceptions import InvalidOperationError

from forecast_interface.common.temporal import validate_utc_datetime_dtype


NUMERIC_DTYPES = (
    pl.Float32,
    pl.Float64,
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
)

TEMPORAL_COLUMNS = ("issue_datetime", "datetime")


def validate_temporal_columns(df: pl.DataFrame) -> None:
    for col in TEMPORAL_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain a '{col}' column")
        validate_utc_datetime_dtype(col, df.schema[col])
        if df[col].is_null().any():
            raise ValueError(f"'{col}' values must not be null")


def _exact_nanoseconds(td: datetime.timedelta) -> int:
    # timedelta resolves to microseconds; avoid total_seconds() (float, lossy).
    return ((td.days * 86_400 + td.seconds) * 10**6 + td.microseconds) * 1000


def validate_cadence(df: pl.DataFrame, timedelta: datetime.timedelta) -> None:
    # Compare in nanoseconds: casting the gap up is lossless, whereas comparing
    # against the Python timedelta lets polars truncate it to the column's unit.
    try:
        gaps = (
            df.select(pl.col("datetime").diff().over("issue_datetime").alias("gap"))
            .drop_nulls()
            .filter(
                pl.col("gap").cast(pl.Duration("ns")).cast(pl.Int64)
                != _exact_nanoseconds(timedelta)
            )
        )
    except InvalidOperationError as exc:
        raise ValueError(
            f"cadence out of representable range for the declared timedelta {timedelta}"
        ) from exc
    if gaps.height:
        raise ValueError(
            f"'datetime' spacing must equal the declared timedelta {timedelta} "
            f"within each issue_datetime group, got {gaps['gap'][0]}"
        )


def validate_numeric_columns(df: pl.DataFrame, columns: list[str]) -> None:
    for col in columns:
        if col not in df.columns:
            raise ValueError(f"DataFrame missing expected column '{col}'")
        if not isinstance(df.schema[col], NUMERIC_DTYPES):
            raise ValueError(f"Column '{col}' must be numeric, got {df.schema[col]}")


def validate_exact_columns(df: pl.DataFrame, expected: list[str]) -> None:
    actual = set(df.columns)
    expected_set = set(expected)
    if actual != expected_set:
        missing = expected_set - actual
        extra = actual - expected_set
        parts: list[str] = []
        if missing:
            parts.append(f"missing: {sorted(missing)}")
        if extra:
            parts.append(f"unexpected: {sorted(extra)}")
        raise ValueError(f"Column mismatch — {', '.join(parts)}")
