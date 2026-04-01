# Input Requirement Specification

The input requirement is a Pydantic-based container that declares what data a forecasting model needs. The preprocessing pipeline reads this spec and provides exactly the required inputs.

All declared inputs are **required** — the pipeline fails if any are missing.

## Input Categories

Two top-level categories:

1. **Dynamic inputs** — time-varying data (e.g. discharge, precipitation, temperature)
2. **Static inputs** — time-invariant attributes (e.g. catchment area, slope, land cover fraction)

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

#### 2. Spatial Resolution

How spatial information is represented:

- **distributed** — gridded / raster data (spatial variability preserved)
- **lumped** — spatially aggregated to a single value per unit (e.g. catchment mean)

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
dynamic:
  daily:
    lumped:
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
    distributed:
      past_known:
        ERA5:
          swe:
            lookback: 90
            max_nan: 5
          precipitation:
            lookback: 30
            max_nan: 3
  hourly:
    lumped:
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
