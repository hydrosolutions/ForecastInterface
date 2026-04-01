# Spatial Representation in ForecastInterface — Discussion Brief

## Context

ForecastInterface defines an `InputRequirement` that a model uses to declare what data the preprocessing pipeline must provide. The spatial axis currently uses two structural fields:

```
SpatialInputSpec
    distributed: DynamicInputSpec | None   # gridded / raster data
    lumped: DynamicInputSpec | None         # spatially aggregated (catchment mean)
```

There is also an unused `SpatialResolution` enum with members `DISTRIBUTED` and `LUMPED`.

Meanwhile, SAPPHIRE_flow (the operational system) uses a richer enum:

```python
class SpatialRepresentation(Enum):
    POINT = "point"
    BASIN_AVERAGE = "basin_average"
    ELEVATION_BAND = "elevation_band"
    GRIDDED = "gridded"
```

This enum appears on `ModelDataRequirements.spatial_input_type` — the model declares what spatial format it expects.

## The Question

Should ForecastInterface's spatial abstraction align with SAPPHIRE_flow's 4-member enum, or stay at the coarser distributed/lumped level?

## How the Pieces Fit

```
ForecastInterface (this package)
  InputRequirement: declares what data the pipeline must fetch
  └── SpatialInputSpec: distributed vs lumped

SAPPHIRE_flow (operational system)
  ModelDataRequirements: declares what format the model consumes
  └── spatial_input_type: POINT | BASIN_AVERAGE | ELEVATION_BAND | GRIDDED
```

The pipeline reads the InputRequirement, fetches raw data, and converts it into the format declared in ModelDataRequirements. ForecastInterface specifies the *data source structure*; SAPPHIRE_flow specifies the *model consumption format*.

## Mapping Between the Two

| SAPPHIRE_flow          | ForecastInterface | Notes |
|------------------------|-------------------|-------|
| `POINT`                | lumped            | Single location, no spatial aggregation |
| `BASIN_AVERAGE`        | lumped            | Spatially aggregated to one value |
| `ELEVATION_BAND`       | lumped or distributed? | Multiple bands per catchment — structured but not gridded |
| `GRIDDED`              | distributed       | Full spatial grid (xarray) |

**The ambiguity is elevation bands.** Elevation-banded data is:
- **Not lumped** in the traditional sense — there are multiple values per timestep (one per band)
- **Not gridded** — it's a 1D decomposition, not a 2D spatial grid
- Could be modeled as "lumped per band" (multiple lumped inputs, one per elevation zone)
- Or as a third category entirely

## Options

### A. Keep distributed/lumped (abstract, decoupled)

```
SpatialInputSpec
    distributed: DynamicInputSpec | None
    lumped: DynamicInputSpec | None
```

- Stable interface that doesn't change when SAPPHIRE_flow adds spatial modes
- Elevation bands would go under `lumped` (each band is a spatially aggregated value)
- Adapter in SAPPHIRE_flow maps: `GRIDDED → distributed`, everything else `→ lumped`
- **Trade-off:** loses the distinction between point, basin-average, and elevation-band at the requirement level

### B. Align with SAPPHIRE_flow's 4-member enum

```python
class SpatialRepresentation(Enum):
    POINT = "point"
    BASIN_AVERAGE = "basin_average"
    ELEVATION_BAND = "elevation_band"
    GRIDDED = "gridded"

class SpatialInputSpec(BaseModel):
    data: dict[SpatialRepresentation, DynamicInputSpec]
```

- Model can declare exactly what spatial format it needs per temporal resolution
- No translation needed between ForecastInterface and SAPPHIRE_flow
- **Trade-off:** ForecastInterface becomes coupled to SAPPHIRE_flow's vocabulary. If another system uses different spatial concepts, the enum must evolve

### C. Three-level abstraction (middle ground)

```python
class SpatialStructure(Enum):
    LUMPED = "lumped"           # single value per unit (point, basin_average)
    BANDED = "banded"          # 1D decomposition (elevation bands, HRUs)
    GRIDDED = "gridded"        # 2D spatial grid

class SpatialInputSpec(BaseModel):
    data: dict[SpatialStructure, DynamicInputSpec]
```

- Captures the structural difference that matters: scalar vs 1D vs 2D
- SAPPHIRE_flow maps: `POINT/BASIN_AVERAGE → LUMPED`, `ELEVATION_BAND → BANDED`, `GRIDDED → GRIDDED`
- Less coupled than full alignment, more expressive than binary

## Key Question for Model Developer

**When you declare input requirements, do you need to distinguish between:**
1. Point observations vs basin-averaged values? (Both are single-valued per timestep)
2. Elevation-banded inputs vs gridded inputs? (Both are multi-valued per timestep but different shapes)

If the answer is "I just need to know if it's a single value or spatially distributed," then Option A suffices.
If "elevation bands are structurally different from grids and I need to handle them differently," then Option B or C.
