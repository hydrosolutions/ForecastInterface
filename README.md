# ForecastInterface

Importable protocol and schema package for forecasting models. Defines validated data containers for model inputs and outputs using Pydantic + Polars.

```
uv add forecastinterface
```

## Documentation

- [Model Interface Specification](docs/model_interface.md)
- [Input Requirement Specification](docs/input_requirement.md)

## ModelOutput

Top-level container holding forecast results, keyed by station then variable. Each variable can independently carry deterministic forecasts, quantile forecasts, trajectory ensembles, or any combination.

`variables` is station-keyed: `station_id → variable_name → VariableOutput`. A single-station model returns a one-key outer dict. Missing stations are explicit `FAILURE` entries (a `VariableOutput` with `status == FAILURE`), never absent keys — the model echoes back every station id it was given.

### Structure

```
ModelOutput
    model_name: str
    issue_datetime: datetime
    success: bool                                    # derived — True when all variables (across all stations) succeeded
    variables: dict[str, dict[str, VariableOutput]]  # station_id → variable_name → VariableOutput

VariableOutput
    metadata: VariableMetadata
    deterministic: DeterministicData | None
    quantiles: QuantileData | None
    trajectories: TrajectoryData | None
    epistemic_uncertainty: EpistemicUncertaintyData | None
    status: VariableStatus                 # SUCCESS | FAILURE | PARTIAL
    flags: frozenset[ForecastFlag]

VariableMetadata
    name: str
    unit: Unit                             # e.g. Unit.M3_PER_S → "m³/s"
    resolution: TemporalResolution                 # e.g. TemporalResolution.DAILY
    timedelta: timedelta                   # time step between forecast points
    forecast_horizon: int                  # number of forecast steps (> 0)
    offset: int                            # offset in steps (>= 0)

DeterministicData
    data: pl.DataFrame                     # columns: ["issue_datetime", "datetime", "value"]

QuantileData
    quantile_levels: list[float]           # e.g. [0.1, 0.5, 0.9] — sorted, in (0, 1)
    data: pl.DataFrame                     # columns: ["issue_datetime", "datetime", "0.1", "0.5", "0.9"]

TrajectoryData
    num_samples: int                       # number of ensemble members (> 0)
    data: pl.DataFrame                     # columns: ["issue_datetime", "datetime", "1", "2", ..., "N"]

EpistemicUncertaintyData
    data: pl.DataFrame                     # columns: ["issue_datetime", "datetime", "std", "range"]
```

### DataFrame Schemas

All DataFrames are validated on construction:

| Container | `issue_datetime` column | `datetime` column | Value columns |
|---|---|---|---|
| `DeterministicData` | `Datetime` | `Datetime` | `value` (numeric) |
| `QuantileData` | `Datetime` | `Datetime` | One per level, named as float strings: `"0.1"`, `"0.5"`, ... |
| `TrajectoryData` | `Datetime` | `Datetime` | One per sample, named `"1"`, `"2"`, ..., `"N"` |
| `EpistemicUncertaintyData` | `Datetime` | `Datetime` | `std` (numeric), `range` (numeric) |

### Enums

**Unit** -- `M3_PER_S`, `MM_PER_DAY`, `MM_PER_S`, `MM`, `CM`, `M`, `DEG_C`, `UNITLESS`

**TemporalResolution** -- `SUB_HOURLY`, `HOURLY`, `SUB_DAILY`, `DAILY`, `WEEKLY`, `MONTHLY`, `SEASONAL`, `ANNUAL`

**VariableStatus** -- `SUCCESS`, `FAILURE`, `PARTIAL`

**ForecastFlag** -- `HIGH_EPISTEMIC_UNCERTAINTY`, `DATA_AVAILABILITY`

### Usage

```python
from datetime import datetime, timedelta
import polars as pl
from forecast_interface import (
    ModelOutput, VariableOutput, VariableMetadata,
    DeterministicData, QuantileData, Unit, TemporalResolution, VariableStatus,
)

issue_dt = datetime(2024, 6, 1, 6, 0)
output = ModelOutput(
    model_name="MyModel",
    issue_datetime=issue_dt,
    variables={
        "station_1": {
            "streamflow": VariableOutput(
                metadata=VariableMetadata(
                    name="streamflow",
                    unit=Unit.M3_PER_S,
                    resolution=TemporalResolution.DAILY,
                    timedelta=timedelta(days=1),
                    forecast_horizon=10,
                    offset=0,
                ),
                deterministic=DeterministicData(
                    data=pl.DataFrame({
                        "issue_datetime": [issue_dt, issue_dt],
                        "datetime": [datetime(2024, 6, 1), datetime(2024, 6, 2)],
                        "value": [42.0, 43.5],
                    }),
                ),
                status=VariableStatus.SUCCESS,
            ),
        },
    },
)

assert output.success is True
```

## InputRequirement

Declares what data a forecasting model needs. The preprocessing pipeline reads this spec and provides exactly the required inputs.

See [Input Requirement Specification](docs/input_requirement.md) for full documentation.

### Structure

```
InputRequirement
    targets: dict[str, TargetSpec]                  # what the model forecasts
    dynamic: dict[TemporalResolution, SpatialInputSpec]
    static: set[str]

TargetSpec
    unit: Unit
    representations: frozenset[OutputRepresentation]  # DETERMINISTIC | QUANTILES | TRAJECTORIES

SpatialInputSpec
    data: dict[SpatialRepresentation, DynamicInputSpec]

DynamicInputSpec
    past_known: dict[str, dict[str, PastKnownVariable]]
    future_known: dict[str, dict[str, FutureKnownVariable]]

PastKnownVariable
    lookback: int
    max_nan: int

FutureKnownVariable
    future_steps: int
    max_nan: int
    ensemble_mode: EnsembleMode    # SINGLE or ENSEMBLE
```

### Enums

**SpatialRepresentation** -- `POINT`, `BASIN_AVERAGE`, `ELEVATION_BAND`, `GRIDDED`

**OutputRepresentation** -- `DETERMINISTIC`, `QUANTILES`, `TRAJECTORIES`
