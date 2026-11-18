from enum import Enum


class AggregationMethod(Enum):
    SUM = "sum"
    MEAN = "mean"
    MAX = "max"
    MIN = "min"
    POINT = "point"
