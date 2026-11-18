# ForecastInterface

Importable protocol and schema package for forecasting models. Defines validated data containers for model inputs and outputs using Pydantic + Polars.

```
uv add forecastinterface
```

## Documentation

- [Model Interface Specification](docs/model_interface.md) — the `ForecastModel` protocol, training/lifecycle, and `ModelOutput` types
- [Input Requirement Specification](docs/input_requirement.md) — the `InputRequirement` declaration and the `ModelInputs` bundle

## ModelOutput

The result of `predict` / `hindcast` (returned via `ModelResult`). A **station-keyed** container — `variables: dict[station_id, dict[variable_name, VariableOutput]]` — where each `VariableOutput` carries any combination of deterministic, quantile, trajectory, and epistemic-uncertainty data, plus a `status` (`SUCCESS`/`FAILURE`/`PARTIAL`) and quality `flags`. A single-station model returns a one-key outer dict; missing stations are explicit `FAILURE` entries, never absent keys.

See the [Model Interface Specification](docs/model_interface.md) for the full schema, DataFrame layouts, and enums.

## InputRequirement

Declares what data a model needs: forecast `targets`, `dynamic` inputs nested as `timedelta` time step → spatial representation → past/future → product → variable (each with its `unit`, `lookback`/`future_steps`, `max_nan`, optional `aggregation`, and — for future-known variables — `horizon_semantics` declaring whether `future_steps` is a hard requirement or a maximum), and `static` attributes. At run time the model receives a `ModelInputs` bundle isomorphic to this declaration.

See the [Input Requirement Specification](docs/input_requirement.md) for the full structure and examples.

## Usage

```python
from datetime import UTC, datetime, timedelta
import polars as pl
from forecast_interface import (
    ModelOutput, VariableOutput, VariableMetadata,
    DeterministicData, Unit, VariableStatus,
)

# Datetimes are timezone-aware UTC throughout — tz-naive frames are rejected.
issue_dt = datetime(2024, 6, 1, 6, 0, tzinfo=UTC)
# offset=1: the first forecast step is one timedelta after the last observation
# (here the observation at the issue time), so valid times are 06-02 and 06-03.
valid_times = [issue_dt + timedelta(days=n) for n in (1, 2)]

output = ModelOutput(
    model_name="MyModel",
    issue_datetime=issue_dt,
    variables={
        "station_1": {
            "streamflow": VariableOutput(
                metadata=VariableMetadata(
                    unit=Unit.M3_PER_S,
                    timedelta=timedelta(days=1),
                    forecast_horizon=2,
                    offset=1,
                ),
                deterministic=DeterministicData(
                    data=pl.DataFrame({
                        "issue_datetime": [issue_dt, issue_dt],
                        "datetime": valid_times,
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
