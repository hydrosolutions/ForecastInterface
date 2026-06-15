# Input Requirement Specification

The input requirement is a Pydantic-based container that declares what data a forecasting model needs. The preprocessing pipeline reads this spec and provides exactly the required inputs.

All declared inputs are **required** — the pipeline fails if any are missing.

## Input Categories

Three top-level declarations:

1. **Targets** — what the model forecasts (the output variables and their supported representations)
2. **Dynamic inputs** — time-varying data (e.g. discharge, precipitation, temperature)
3. **Static inputs** — time-invariant attributes (e.g. catchment area, slope, land cover fraction)

---

## Targets

A model must declare what it forecasts. `targets` is a dict keyed by variable name, each mapping to a `TargetSpec`:

```python
class TargetSpec(BaseModel):
    unit: Unit
    representations: frozenset[OutputRepresentation]
```

- **unit** — the physical unit of the target (e.g. `Unit.M3_PER_S`).
- **representations** — the output forms the model can produce for this target, a non-empty set of `OutputRepresentation`: `deterministic`, `quantiles`, `trajectories`. A target may support more than one form.

The combinability rule (whether a target's forecasts can be BMA-combined) is derived downstream from whether `TRAJECTORIES` is present; it is not encoded here.

Targets are declared **independently** of inputs. A model that needs the target's own past history simply lists that variable under `past_known` in its dynamic inputs; a pure-simulation model omits it. (See Q2 in `open_design_questions.md`.)

`targets` must contain at least one entry — a model must forecast something.

---

## Dynamic Inputs

Dynamic inputs follow a strict hierarchy:

```
temporal_resolution
  └── spatial_resolution
        └── temporality (past_known / future_known)
              └── product
                    └── variable
                          └── properties
```

### Hierarchy Levels

#### 1. Temporal Resolution

The time step of the data. One of: `sub_hourly`, `hourly`, `sub_daily`, `daily`, `weekly`, `monthly`, `seasonal`, `annual`.

#### 2. Spatial Representation

How spatial information is represented. Keyed by the `SpatialRepresentation` enum (values mirror SAP3's enum, so the adapter mapping is identity):

- **point** — a single point location (e.g. a gauge or grid-cell extraction)
- **basin_average** — single time series per basin (station observations or basin-averaged values)
- **elevation_band** — semi-distributed: one time series per elevation band (e.g. banded SnowMapper forcing such as `swe` and `rof` is declared at `elevation_band`)
- **gridded** — fully distributed raster data (spatial variability preserved)

The `SpatialInputSpec` model holds a `data` dict keyed by `SpatialRepresentation`:

```python
class SpatialInputSpec(BaseModel):
    data: dict[SpatialRepresentation, DynamicInputSpec]
```

A model can require any combination of representations within the same temporal resolution.

#### 3. Temporality

Relationship of the data to the forecast issue time:

- **past_known** — observed / historical data available up to the issue time
- **future_known** — forecast or projected data extending beyond the issue time

#### 4. Product

The data source or provider (e.g. `ERA5`, `GFS`, `INCA`, `obs`). This axis allows a model to require the same variable from multiple products.

#### 5. Variable

The physical quantity (e.g. `discharge`, `precipitation`, `temperature`, `swe`).

### Variable Properties

Each variable declares the following properties:

| Property       | Type   | Applies to    | Description                                                  |
|----------------|--------|---------------|--------------------------------------------------------------|
| `lookback`     | `int`  | past_known    | Number of past time steps required (must be > 0)             |
| `future_steps` | `int`  | future_known  | Number of future time steps required (must be > 0)           |
| `max_nan`      | `int`  | both          | Maximum allowed NaN values in the time series (must be >= 0) |
| `ensemble_mode`| `EnsembleMode` | future_known  | Whether ensemble or single traces are needed (`single` or `ensemble`, default: `single`) |

---

## Static Inputs

An unordered set of variable names (`set[str]`). Duplicates are ignored.

Example: `["catchment_area", "mean_slope", "forest_fraction", "clay_fraction"]`

---

## Full Example

```yaml
targets:
  discharge:
    unit: "m³/s"
    representations:
      - quantiles
      - trajectories

dynamic:
  daily:
    data:
      basin_average:
        past_known:
          obs:
            discharge:
              lookback: 365
              max_nan: 10
            precipitation:
              lookback: 30
              max_nan: 5
        future_known:
          GFS:
            precipitation:
              future_steps: 10
              max_nan: 0
              ensemble_mode: ensemble
            temperature:
              future_steps: 10
              max_nan: 0
              ensemble_mode: single
          ECMWF:
            precipitation:
              future_steps: 15
              max_nan: 0
              ensemble_mode: ensemble
      gridded:
        past_known:
          ERA5:
            swe:
              lookback: 90
              max_nan: 5
            precipitation:
              lookback: 30
              max_nan: 3
      elevation_band:
        future_known:
          SnowMapper:
            swe:
              future_steps: 10
              max_nan: 0
              ensemble_mode: single
            rof:
              future_steps: 10
              max_nan: 0
              ensemble_mode: single
  hourly:
    data:
      basin_average:
        past_known:
          obs:
            discharge:
              lookback: 72
              max_nan: 2
        future_known:
          INCA:
            precipitation:
              future_steps: 48
              max_nan: 0
              ensemble_mode: single

static:
  - catchment_area
  - mean_slope
  - forest_fraction
```
