# Model Interface

The primary goal of this package is to define the interface between any forecasting library and the forecasting model. The forecasting model can be implemented in any package / code base but needs to follow the protocol defined here.

Core functionalites include:
 **Forecast Function** forecast()
Takes as input the ModelInput and outputs the ModelOutput (Forecast).

**Hindcast Function** hindcast()
Takes as input the ModelInput and outputs the ModelOutput (Hindcast).

**Initialization** __init__():
The model should take the model specific config file which needs to provide the input requirements as an argument and loads internally all relevant artifacts / checkpoints etc.

For later integration:
**Calibrate**
    - can be
    - **Calibrate** (for conceptual or single basin ml model)
    - **Finetune** (if a base model is provided)
    - **Retrain** (if the model is already trained)

---

## ModelOutput

`ModelOutput` is the unified return type for both `forecast()` and `hindcast()`.

| Field | Type | Description |
|---|---|---|
| `model_name` | `str` | Identifier of the model that produced the output |
| `issue_datetime` | `datetime` (UTC) | Single issue datetime for the entire output |
| `variables` | `dict[str, VariableOutput]` | Mapping of variable name to its output |
| `success` | `bool` | Computed property — `True` when all variables contain valid data |

### DataFrame Column Schema

All data classes share a unified DataFrame schema with two required datetime columns:

| Column | Type | Description |
|---|---|---|
| `issue_datetime` | `datetime` (UTC) | When the forecast/hindcast was issued |
| `datetime` | `datetime` (UTC) | The target valid time of the prediction |

**Forecast**: `issue_datetime` is constant across all rows (single issue time).
**Hindcast**: `issue_datetime` varies across rows (multiple issue times).

### Data Classes

Each data class wraps a DataFrame with the two temporal columns above, plus class-specific value columns:

**DeterministicData** — columns: `[issue_datetime, datetime, value]`

**QuantileData** — columns: `[issue_datetime, datetime, <quantile_level>, ...]`
Quantile columns are named by their level as strings (e.g., `"0.1"`, `"0.5"`, `"0.9"`). Levels must be in (0, 1), sorted ascending, and unique.

**TrajectoryData** — columns: `[issue_datetime, datetime, "1", "2", ..., "<N>"]`
Sample columns are named `"1"` through `"<num_samples>"`.

**EpistemicUncertaintyData** — columns: `[issue_datetime, datetime, std, range]`
Captures model uncertainty as standard deviation and range.

### VariableOutput

Groups data for a single output variable:

| Field | Type | Description |
|---|---|---|
| `metadata` | `VariableMetadata` | Name, unit, resolution, timedelta, forecast_horizon, offset |
| `deterministic` | `DeterministicData \| None` | Point forecast |
| `quantiles` | `QuantileData \| None` | Quantile forecast |
| `trajectories` | `TrajectoryData \| None` | Ensemble trajectories |
| `epistemic_uncertainty` | `EpistemicUncertaintyData \| None` | Model uncertainty |
| `flags` | `frozenset[ForecastFlag]` | Quality flags (empty = trusted) |
| `status` | `VariableStatus` | `SUCCESS`, `FAILURE`, or `PARTIAL` |

At least one of `deterministic`, `quantiles`, or `trajectories` must be present when status is `SUCCESS`.

`variables` must contain at least one entry. When status is `PARTIAL`, at least one data representation must still be present (same rule as `SUCCESS`).

### ForecastFlag

Quality flags that can be attached to a variable output:

- `HIGH_EPISTEMIC_UNCERTAINTY` — model confidence is low
- `DATA_AVAILABILITY` — input data was degraded

A variable with no flags is considered `trusted`.
