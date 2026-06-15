from forecast_interface.common.resolutions import (
    SpatialRepresentation,
    TemporalResolution,
)

from .requirement import (
    DynamicInputSpec,
    InputRequirement,
    SpatialInputSpec,
)
from .target import OutputRepresentation, TargetSpec
from .variable import EnsembleMode, FutureKnownVariable, PastKnownVariable

__all__ = [
    "DynamicInputSpec",
    "EnsembleMode",
    "FutureKnownVariable",
    "InputRequirement",
    "OutputRepresentation",
    "PastKnownVariable",
    "SpatialInputSpec",
    "SpatialRepresentation",
    "TargetSpec",
    "TemporalResolution",
]
