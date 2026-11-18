from datetime import datetime, timedelta
from typing import Annotated

import polars as pl
from pydantic import AfterValidator, AwareDatetime


def validate_utc_datetime_dtype(col: str, dtype: pl.DataType) -> None:
    if not isinstance(dtype, pl.Datetime):
        raise ValueError(f"'{col}' column must be Datetime, got {dtype}")
    if dtype.time_zone != "UTC":
        raise ValueError(
            f"'{col}' column must be timezone-aware UTC Datetime, got {dtype}; "
            "only the literal 'UTC' time zone is accepted "
            "(aliases such as 'Etc/UTC' are rejected on purpose)"
        )


def _require_utc_offset(v: datetime) -> datetime:
    if v.utcoffset() != timedelta(0):
        raise ValueError(f"issue_datetime must be UTC, got offset {v.utcoffset()}")
    return v


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc_offset)]
