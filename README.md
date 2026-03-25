# ForecastInterface

Importable protocol and schema package for forecasting models. Defines validated data containers for model inputs and outputs using Pydantic + Polars.

```
uv add forecastinterface
```

## ModelOutput

Top-level container holding forecast results for one or more variables. Each variable can independently carry deterministic forecasts, quantile forecasts, trajectory ensembles, or any combination.

### Structure

```
ModelOutput
    model_name: str
    forecast_issue_date: datetime
    success: bool                          # derived — True when all variables succeeded
    variables: dict[str, VariableOutput]   # keyed by variable name

VariableOutput
    metadata: VariableMetadata
    deterministic: DeterministicData | None
    quantiles: QuantileData | None
    trajectories: TrajectoryData | None
    status: VariableStatus                 # SUCCESS | FAILURE | PARTIAL

VariableMetadata
    name: str
    unit: Unit                             # e.g. Unit.M3_PER_S → "m³/s"
    resolution: Resolution                 # e.g. Resolution.DAILY
    timedelta: timedelta                   # time step between forecast points
    forecast_horizon: int                  # number of forecast steps (> 0)
    offset: int                            # offset in steps (>= 0)

DeterministicData
    data: pl.DataFrame                     # columns: ["date", "value"]

QuantileData
    quantile_levels: list[float]           # e.g. [0.1, 0.5, 0.9] — sorted, in (0, 1)
    data: pl.DataFrame                     # columns: ["date", "0.1", "0.5", "0.9"]

TrajectoryData
    num_samples: int                       # number of ensemble members (> 0)
    data: pl.DataFrame                     # columns: ["date", "1", "2", ..., "N"]
```

### DataFrame Schemas

All DataFrames are validated on construction:

| Container | `date` column | Value columns |
|---|---|---|
| `DeterministicData` | `Date` or `Datetime` | `value` (numeric) |
| `QuantileData` | `Date` or `Datetime` | One per level, named as float strings: `"0.1"`, `"0.5"`, ... |
| `TrajectoryData` | `Date` or `Datetime` | One per sample, named `"1"`, `"2"`, ..., `"N"` |

### Enums

**Unit** — `M3_PER_S`, `MM_PER_DAY`, `MM_PER_S`, `MM`, `CM`, `M`, `DEG_C`, `UNITLESS`

**Resolution** — `SUB_HOURLY`, `HOURLY`, `SUB_DAILY`, `DAILY`, `WEEKLY`, `MONTHLY`, `SEASONAL`, `ANNUAL`

**VariableStatus** — `SUCCESS`, `FAILURE`, `PARTIAL`

### Usage

```python
from datetime import datetime, timedelta, date
import polars as pl
from forecast_interface import (
    ModelOutput, VariableOutput, VariableMetadata,
    DeterministicData, QuantileData, Unit, Resolution, VariableStatus,
)

output = ModelOutput(
    model_name="MyModel",
    forecast_issue_date=datetime(2024, 6, 1),
    variables={
        "streamflow": VariableOutput(
            metadata=VariableMetadata(
                name="streamflow",
                unit=Unit.M3_PER_S,
                resolution=Resolution.DAILY,
                timedelta=timedelta(days=1),
                forecast_horizon=10,
                offset=0,
            ),
            deterministic=DeterministicData(
                data=pl.DataFrame({
                    "date": [date(2024, 6, 1), date(2024, 6, 2)],
                    "value": [42.0, 43.5],
                }),
            ),
            quantiles=QuantileData(
                quantile_levels=[0.1, 0.5, 0.9],
                data=pl.DataFrame({
                    "date": [date(2024, 6, 1), date(2024, 6, 2)],
                    "0.1": [38.0, 39.0],
                    "0.5": [42.0, 43.5],
                    "0.9": [46.0, 48.0],
                }),
            ),
            status=VariableStatus.SUCCESS,
        ),
    },
)

assert output.success is True
assert output.variables["streamflow"].deterministic is not None
```

## ModelInput

Not yet implemented.
