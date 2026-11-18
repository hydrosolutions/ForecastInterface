import polars as pl


def validate_utc_datetime_dtype(col: str, dtype: pl.DataType) -> None:
    if not isinstance(dtype, pl.Datetime):
        raise ValueError(f"'{col}' column must be Datetime, got {dtype}")
    if dtype.time_zone != "UTC":
        raise ValueError(
            f"'{col}' column must be timezone-aware UTC Datetime, got {dtype}"
        )
