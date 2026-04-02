from forecast_interface.common.resolutions import SpatialResolution, TemporalResolution

from .requirement import (
    DynamicInputSpec,
    InputRequirement,
    SpatialInputSpec,
)
from .variable import EnsembleMode, FutureKnownVariable, PastKnownVariable

__all__ = [
    "DynamicInputSpec",
    "EnsembleMode",
    "FutureKnownVariable",
    "InputRequirement",
    "PastKnownVariable",
    "SpatialResolution",
    "TemporalResolution",
    "SpatialInputSpec",
]
