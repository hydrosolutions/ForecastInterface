from enum import Enum


class SpatialRepresentation(Enum):
    POINT = "point"
    BASIN_AVERAGE = "basin_average"
    ELEVATION_BAND = "elevation_band"
    GRIDDED = "gridded"
