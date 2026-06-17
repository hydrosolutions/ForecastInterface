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

Declares what data a model needs: forecast `targets`, `dynamic` inputs nested as `timedelta` time step → spatial representation → past/future → product → variable (each with its `unit`, `lookback`/`future_steps`, `max_nan`, and optional `aggregation`), and `static` attributes. At run time the model receives a `ModelInputs` bundle isomorphic to this declaration.

See the [Input Requirement Specification](docs/input_requirement.md) for the full structure and examples.

## Usage

```python
from datetime import datetime, timedelta
import polars as pl
from forecast_interface import (
    ModelOutput, VariableOutput, VariableMetadata,
    DeterministicData, Unit, VariableStatus,
)

issue_dt = datetime(2024, 6, 1, 6, 0)
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
