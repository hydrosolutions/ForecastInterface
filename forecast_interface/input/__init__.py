from forecast_interface.common.aggregation import AggregationMethod
from forecast_interface.common.resolutions import SpatialRepresentation

from .bundle import (
    DynamicInputs,
    InputSeries,
    ModelInputs,
    SpatialInputs,
    StationInputs,
)
from .requirement import (
    DynamicInputSpec,
    InputRequirement,
    SpatialInputSpec,
)
from .target import OutputRepresentation, TargetSpec
from .variable import (
    EnsembleMode,
    FutureKnownVariable,
    HorizonSemantics,
    PastKnownVariable,
)

__all__ = [
    "AggregationMethod",
    "DynamicInputs",
    "DynamicInputSpec",
    "EnsembleMode",
    "FutureKnownVariable",
    "HorizonSemantics",
    "InputRequirement",
    "InputSeries",
    "ModelInputs",
    "OutputRepresentation",
    "PastKnownVariable",
    "SpatialInputs",
    "SpatialInputSpec",
    "SpatialRepresentation",
    "StationInputs",
    "TargetSpec",
]
