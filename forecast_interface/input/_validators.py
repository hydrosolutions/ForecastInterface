import polars as pl


DATETIME_DTYPE = pl.Datetime
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


def validate_input_series_dataframe(df: pl.DataFrame) -> None:
    if "datetime" not in df.columns:
        raise ValueError("DataFrame must contain a 'datetime' column")
    if not isinstance(df.schema["datetime"], DATETIME_DTYPE):
        raise ValueError("'datetime' column must be Datetime")
    if "issue_datetime" in df.columns:
        raise ValueError("InputSeries data must not contain 'issue_datetime'")

    datetime_values = df["datetime"]
    if datetime_values.is_null().any():
        raise ValueError("'datetime' values must not be null")
    if df.height == 0:
        raise ValueError("InputSeries data must contain at least one row")

    value_columns = [col for col in df.columns if col != "datetime"]
    if not value_columns:
        raise ValueError("InputSeries data must contain at least one value column")
    for col in value_columns:
        if not isinstance(df.schema[col], NUMERIC_DTYPES):
            raise ValueError(f"Column '{col}' must be numeric")

    if datetime_values.n_unique() != df.height:
        raise ValueError("'datetime' values must be unique")
    if not datetime_values.is_sorted():
        raise ValueError("'datetime' values must be sorted ascending")
