from forecast_interface.common.aggregation import AggregationMethod
from forecast_interface.common.resolutions import SpatialRepresentation

from .requirement import (
    DynamicInputSpec,
    InputRequirement,
    SpatialInputSpec,
)
from .target import OutputRepresentation, TargetSpec
from .variable import EnsembleMode, FutureKnownVariable, PastKnownVariable

__all__ = [
    "AggregationMethod",
    "DynamicInputSpec",
    "EnsembleMode",
    "FutureKnownVariable",
    "InputRequirement",
    "OutputRepresentation",
    "PastKnownVariable",
    "SpatialInputSpec",
    "SpatialRepresentation",
    "TargetSpec",
]
