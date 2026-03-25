from enum import Enum


class Resolution(Enum):
    SUB_HOURLY = "sub_hourly"
    HOURLY = "hourly"
    SUB_DAILY = "sub_daily"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    ANNUAL = "annual"
