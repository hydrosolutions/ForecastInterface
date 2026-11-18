import datetime
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


def exact_nanoseconds(td: datetime.timedelta) -> int:
    # timedelta resolves to microseconds; avoid total_seconds() (float, lossy).
    return ((td.days * 86_400 + td.seconds) * 10**6 + td.microseconds) * 1000


def validate_on_grid(
    values: pl.Series,
    step: datetime.timedelta,
    origin: datetime.timedelta,
    name: str,
) -> None:
    # `values` must be timezone-aware UTC datetimes (callers validate dtype first).
    # A value is on the grid when (epoch - origin) is a whole multiple of step.
    step_ns = exact_nanoseconds(step)
    origin_ns = exact_nanoseconds(origin)
    epoch = values.dt.epoch("ns")
    off_grid = (epoch - origin_ns) % step_ns != 0
    if off_grid.any():
        offender = values.filter(off_grid)[0]
        raise ValueError(
            f"'{name}' value {offender} is off the declared grid "
            f"(step {step}, origin {origin} from UTC midnight)"
        )


def _require_utc_offset(v: datetime.datetime) -> datetime.datetime:
    if v.utcoffset() != datetime.timedelta(0):
        raise ValueError(f"issue_datetime must be UTC, got offset {v.utcoffset()}")
    return v


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc_offset)]
