import datetime

import polars as pl
from polars.exceptions import InvalidOperationError

from forecast_interface.common.temporal import (
    exact_nanoseconds,
    validate_utc_datetime_dtype,
)


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


_MAX_NS = 2**63 - 1
_MAX_GAP_SECONDS = _MAX_NS // 10**9


def _raise_gap_out_of_range(df: pl.DataFrame, exc: InvalidOperationError) -> None:
    offender = (
        df.select(
            "issue_datetime",
            "datetime",
            pl.col("datetime").diff().over("issue_datetime").alias("gap"),
        )
        .filter(pl.col("gap").dt.total_seconds().abs() > _MAX_GAP_SECONDS)
        .head(1)
    )
    where = (
        f"issue_datetime {offender['issue_datetime'][0]}, "
        f"datetime {offender['datetime'][0]}"
        if offender.height
        else "an unidentified row"
    )
    raise ValueError(
        f"'datetime' gap at {where} is out of representable range "
        "(it does not fit in nanoseconds), so it cannot match the declared cadence"
    ) from exc


def validate_cadence(df: pl.DataFrame, timedelta: datetime.timedelta) -> None:
    # Compare in nanoseconds: casting the gap up is lossless, whereas comparing
    # against the Python timedelta lets polars truncate it to the column's unit.
    declared_ns = exact_nanoseconds(timedelta)
    if abs(declared_ns) > _MAX_NS:
        raise ValueError(
            f"cadence out of representable range: declared timedelta {timedelta} "
            "does not fit in nanoseconds"
        )
    try:
        bad = (
            df.select(
                "issue_datetime",
                "datetime",
                pl.col("datetime")
                .diff()
                .over("issue_datetime")
                .cast(pl.Duration("ns"))
                .cast(pl.Int64)
                .alias("gap_ns"),
            )
            .drop_nulls("gap_ns")
            .filter(pl.col("gap_ns") != declared_ns)
        )
    except InvalidOperationError as exc:
        _raise_gap_out_of_range(df, exc)
        raise
    if not bad.height:
        return
    first = bad.row(0, named=True)
    where = f"issue_datetime {first['issue_datetime']}, datetime {first['datetime']}"
    if (bad["gap_ns"] < 0).any():
        raise ValueError(
            "rows must be sorted ascending by datetime within each "
            f"issue_datetime group; out of order at {where}"
        )
    gap = datetime.timedelta(microseconds=first["gap_ns"] // 1000)
    raise ValueError(
        f"'datetime' spacing must equal the declared timedelta {timedelta} "
        f"within each issue_datetime group, got {gap} at {where}"
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
