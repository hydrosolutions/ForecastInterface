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

The combinability rule is **derived** from whether `TRAJECTORIES` is present — trajectory output is combinable (pooled / BMA); quantile-only or deterministic output is not. It is not separately encoded, and the combination mechanism (cross-model compatibility checks, weighting, member-id remapping, sentinel models) is entirely SAP3-side (decision 1.14).

Targets are declared **independently** of inputs. A model that needs the target's own past history simply lists that variable under `past_known` in its dynamic inputs; a pure-simulation model omits it. (See Q2 in `open_design_questions.md`.)

`targets` must contain at least one entry — a model must forecast something.

---

## Dynamic Inputs

Dynamic inputs follow a strict hierarchy:

```
time_step (timedelta)
  └── spatial_resolution
        └── temporality (past_known / future_known)
              └── product
                    └── variable
                          └── properties
```

### Hierarchy Levels

#### 1. Time step

The time step of the data, expressed as a **`timedelta`** (the `dynamic` dict is keyed by `timedelta`). This is a precise, fixed duration — e.g. `timedelta(hours=1)`, `timedelta(hours=3)`, `timedelta(hours=6)`, `timedelta(hours=24)` — and is an identity match to SAP3's `time_step`. Sub-daily steps such as 3-hourly and 6-hourly are first-class.

Calendar-based resolutions (monthly / seasonal / annual / decadal) are **out of scope for v1** — they are not fixed durations. If forecasting at those steps is later required, a dedicated `TimeStep = timedelta | CalendarResolution` type will be introduced (see decision 1.12).

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
| `future_steps` | `int`  | future_known  | Number of future time steps (must be > 0). Read as a floor or a ceiling according to `horizon_semantics` — see [Horizon semantics](#horizon-semantics). |
| `horizon_semantics` | `HorizonSemantics` | future_known | Whether `future_steps` is a hard requirement (`exact`, the default) or a maximum (`at_most`). |
| `min_future_steps` | `int \| None` | future_known | The floor under `at_most`: **required** when `horizon_semantics` is `at_most`, and rejected otherwise. Must satisfy `0 < min_future_steps <= future_steps`. |
| `max_nan`      | `int`  | both          | The model's **tolerance**: max NaNs it can cope with in the series (must be >= 0). **SAP3 enforces this as a pre-`predict` gate** — if exceeded, the model is not called and the station is failed (`DATA_AVAILABILITY`); within tolerance, residual NaNs are delivered **as-is** for the model to handle (decision 1.13). |
| `ensemble_mode`| `EnsembleMode` | future_known  | Whether ensemble or single traces are needed (`single` or `ensemble`, default: `single`) |
| `unit`         | `Unit` | both          | **Required.** The physical unit the model expects this variable in (e.g. `Unit.MM_PER_DAY`). The delivered series is tagged with its unit and delivered **in the declared unit, or rejected loudly at integration** — no data without units. (Automatic unit conversion is a future adapter feature.) |
| `aggregation`  | `AggregationMethod \| None` | both | **Optional.** `SUM`, `MEAN` or `MAX`, used when the declared resolution is coarser than the delivered data. Defaults to the per-parameter convention (precipitation / reference_et = `SUM`; state variables = `MEAN`); declare only to override. |

### Horizon semantics

`future_steps` alone cannot say whether a model *requires* that many future steps or merely *can use*
that many. Both readings occur in practice, and a provider that guesses wrong either refuses to run a
model that would have worked or hands a short input to a model that needs its full horizon. The
variable therefore states its own semantics:

```python
class HorizonSemantics(Enum):
    EXACT = "exact"      # future_steps is a floor: fewer is an error
    AT_MOST = "at_most"  # future_steps is a ceiling: fewer yields a shorter forecast
```

- **`exact`** — the default, and the meaning every declaration had before this field existed. Fewer
  than `future_steps` delivered steps is a data-availability failure; the model is not called.
- **`at_most`** — the model degrades gracefully. Any count in `[min_future_steps, future_steps]` is
  acceptable and produces a correspondingly shorter forecast. Below `min_future_steps` the provider
  refuses, exactly as under `exact`.

Two rules bind a short delivery:

1. **A short delivery is a shorter series, not a NaN-padded full-length one.** The undelivered steps
   are not counted against `max_nan`, which continues to gate only NaNs *within* the delivered
   extent. Padding a fixed-length frame with a trailing NaN block is a contract violation.
2. **The delivered steps are the contiguous prefix** beginning at the first future step. `at_most`
   licenses a short tail — never a leading or interior gap.

`min_future_steps` is mandatory under `at_most` because "fewer is fine" is rarely unbounded: a
15-day model may be useless at 1 day. Requiring the floor keeps that judgement with the model, which
is the only party that knows it.

Semantics are declared **per variable**, not per model: a model may need one forcing in full while
tolerating truncation in another, and the same model may tolerate truncation only in some
configurations. The horizon the model actually produces is still the model's own to compute and
declare in `metadata.forecast_horizon` — this field only tells a provider how much forcing is
useful, and how little is still enough.

```python
FutureKnownVariable(
    future_steps=15,                              # trained maximum
    min_future_steps=5,                           # below this, do not call the model
    horizon_semantics=HorizonSemantics.AT_MOST,
    max_nan=0,
    unit=Unit.MM_PER_DAY,
)
```

Under this declaration a provider with a 120 h (5-day) NWP feed is permitted to invoke the model and
receives a 5-day forecast, where an `exact` declaration would oblige it to refuse. The contract
grants the permission; **acting on it is provider-side work** — a provider that does not yet read
`horizon_semantics` keeps applying `future_steps` as a floor, which stays correct, just no less
strict than before.

---

## Parameter vocabulary, units & aggregation

These three are a single coherent concern (mirroring SAP3's `ParameterDefinition`, which binds name → unit → aggregation) and each is a **coordination contract with SAP3**.

**Canonical parameter names.** Variable names are free strings, but they **must match SAP3's canonical parameter vocabulary** so the preprocessing pipeline can resolve them. Canonical set: `discharge`, `water_level`, `water_temperature`, `precipitation`, `temperature`, `relative_humidity`, `wind_speed`, `wind_direction`, `global_radiation`, `reference_et`, `snow_water_equivalent`, `runoff` (ROF). SAP3 soft-checks names at integration and rejects unknowns. **Sync obligation:** keep this list aligned with SAP3 and update it whenever a variable is added on either side.

**Units.** Every input variable declares the `unit` it expects (see properties table); outputs declare units via `TargetSpec` / `VariableMetadata`. The `Unit` enum must cover every parameter's unit and is a **sync contract with SAP3's `ParameterDefinition` units** — extended as needed (current additions for forcing: `PERCENT`, `M_PER_S`, `DEGREE`, `W_PER_M2`, `MM_PER_HOUR`).

**Aggregation.** When a model declares a variable at a resolution coarser than the delivered data, SAP3 aggregates with `SUM`, `MEAN` or `MAX` (`MAX` for peak channels, e.g. a window-max discharge a flood threshold is set on). Default follows the per-parameter convention (precipitation / reference_et = `SUM`; temperature, discharge, SWE and other state variables = `MEAN`); override via the optional `aggregation` property only for a non-default rule.

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
  PT24H:          # timedelta(hours=24) — daily
    data:
      basin_average:
        past_known:
          obs:
            discharge:
              lookback: 365
              max_nan: 10
              unit: "m³/s"
            precipitation:
              lookback: 30
              max_nan: 5
              unit: "mm/day"
              aggregation: sum   # override: sum hourly precip into daily
        future_known:
          ECMWF:
            precipitation:
              future_steps: 15          # ceiling: a 5-day feed still yields a 5-day forecast
              min_future_steps: 5
              horizon_semantics: at_most
              max_nan: 0
              ensemble_mode: ensemble
              unit: "mm/day"
            temperature:
              future_steps: 15          # no horizon_semantics -> exact, all 15 steps required
              max_nan: 0
              ensemble_mode: single
              unit: "°C"
      elevation_band:
        future_known:
          SnowMapper:
            swe:
              future_steps: 10
              max_nan: 0
              ensemble_mode: single
              unit: "mm"
            runoff:
              future_steps: 10
              max_nan: 0
              ensemble_mode: single
              unit: "mm"
  PT6H:           # timedelta(hours=6) — 6-hourly (sub-daily, now first-class)
    data:
      basin_average:
        past_known:
          obs:
            discharge:
              lookback: 72
              max_nan: 2
              unit: "m³/s"

static:
  - catchment_area
  - mean_slope
  - forest_fraction
```
