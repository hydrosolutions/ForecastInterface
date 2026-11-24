import polars as pl

from forecast_interface.common.temporal import validate_utc_datetime_dtype

NUMERIC_DTYPES = (
    pl.Decimal,
    pl.Float16,
    pl.Float32,
    pl.Float64,
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.Int128,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
    pl.UInt128,
)


AVAILABLE_AT_COLUMN = "available_at_us"
INTEGER_DTYPES = (
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
)


def validate_input_series_dataframe(df: pl.DataFrame) -> None:
    if "datetime" not in df.columns:
        raise ValueError("DataFrame must contain a 'datetime' column")
    validate_utc_datetime_dtype("datetime", df.schema["datetime"])
    if "issue_datetime" in df.columns:
        raise ValueError("InputSeries data must not contain 'issue_datetime'")

    datetime_values = df["datetime"]
    if datetime_values.is_null().any():
        raise ValueError("'datetime' values must not be null")
    if df.height == 0:
        raise ValueError("InputSeries data must contain at least one row")

    if AVAILABLE_AT_COLUMN in df.columns and not isinstance(
        df.schema[AVAILABLE_AT_COLUMN], INTEGER_DTYPES
    ):
        raise ValueError(
            f"Column '{AVAILABLE_AT_COLUMN}' must be an integer (UTC epoch microseconds)"
        )

    value_columns = [
        col for col in df.columns if col not in ("datetime", AVAILABLE_AT_COLUMN)
    ]
    if not value_columns:
        raise ValueError("InputSeries data must contain at least one value column")
    for col in value_columns:
        if not isinstance(df.schema[col], NUMERIC_DTYPES):
            raise ValueError(f"Column '{col}' must be numeric")

    if datetime_values.n_unique() != df.height:
        raise ValueError("'datetime' values must be unique")
    if not datetime_values.is_sorted():
        raise ValueError("'datetime' values must be sorted ascending")
