from enum import Enum


class TemporalResolution(Enum):
    SUB_HOURLY = "sub_hourly"
    HOURLY = "hourly"
    SUB_DAILY = "sub_daily"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    ANNUAL = "annual"


class SpatialResolution(Enum):
    DISTRIBUTED = "distributed"
    LUMPED = "lumped"
