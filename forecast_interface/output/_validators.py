import polars as pl


DATETIME_DTYPE = pl.Datetime
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
        if not isinstance(df.schema[col], DATETIME_DTYPE):
            raise ValueError(f"'{col}' column must be Datetime, got {df.schema[col]}")


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
