from enum import Enum


class Unit(Enum):
    M3_PER_S = "m³/s"
    MM_PER_DAY = "mm/day"
    MM_PER_S = "mm/s"
    MM = "mm"
    CM = "cm"
    M = "m"
    DEG_C = "°C"
    UNITLESS = "-"
    PERCENT = "%"
    M_PER_S = "m/s"
    DEGREE = "°"
    W_PER_M2 = "W/m²"
    MM_PER_HOUR = "mm/hour"

    @property
    def is_rate(self) -> bool:
        return self in _RATE_UNITS


_RATE_UNITS = frozenset(
    {
        Unit.M3_PER_S,
        Unit.MM_PER_DAY,
        Unit.MM_PER_S,
        Unit.M_PER_S,
        Unit.MM_PER_HOUR,
        Unit.W_PER_M2,
    }
)
