# Open Design Questions

Questions to discuss with the model developer before finalizing the interface.

---

## 1. Multi-Station Model Output

**Status:** Open, high priority — proposal for discussion

### Problem

The typical ML model predicts for many stations in one forward pass. Currently `ModelOutput.variables` is `dict[str, VariableOutput]` — keyed by variable name only, with no station dimension. This forces the orchestrator to call the model once per station, losing batching efficiency.

### Proposal

Add a station dimension to `ModelOutput`. The model receives station identifiers in its input data (as a grouping variable to correlate targets with features) and returns per-station results keyed by the same identifiers:

```python
class ModelOutput(BaseModel):
    model_name: str
    issue_datetime: datetime
    variables: dict[str, dict[str, VariableOutput]]
    #               ^station_id  ^variable_name
```

A single-station model simply returns a dict with one key. This keeps one protocol for both cases.

### How this works in SAPPHIRE_flow today

SAPPHIRE_flow uses this pattern for group (multi-station) models:

**Input side:** All per-station DataFrames are stacked into one long DataFrame with a `station_id` column (string type, always first column). The model receives one `GroupModelInputs` object containing all stations. A convenience method `for_station(sid)` filters and drops the column, giving clean per-station DataFrames.

**Output side:** The model returns `dict[StationId, dict[str, ForecastEnsemble]]` — the station dimension is in the dict structure, not in the DataFrames. Each `ForecastEnsemble` is already per-station.

**Pattern summary:**
```
Input:  stacked DataFrames with station_id column → model
Output: model → dict[station_id, dict[variable_name, data]]
```

### What changes for the model developer

- `predict()` returns a `ModelResult` wrapping a `ModelOutput` where `variables` is now `dict[str, dict[str, VariableOutput]]`
- Station identifiers come from the input data — the model echoes back the same IDs it received
- The per-variable DataFrames remain per-station (no `station_id` column in the forecast DataFrames themselves)
- Models that predict for a single station return `{"station_xyz": {"discharge": ..., "water_level": ...}}`

### Questions for the model developer

- Does this match how your models work? (station_id as grouping variable in, per-station results out)
- Are station identifiers always strings, or do you use typed IDs?
- Is there a case where the model defines its own spatial units that don't map 1:1 to input station IDs?

---

## 2. Target Variable Declaration

**Status:** Open

`InputRequirement` declares what data the model consumes, but does not distinguish between **target variables** (what the model forecasts) and **feature variables** (predictors).

In the current YAML example, `discharge` sits under `past_known` alongside `precipitation` — they look identical structurally. SAPPHIRE_flow's `ModelDataRequirements` has an explicit `target_parameters: frozenset[str]` field.

**Key constraint:** Target past observations are NOT always available. Pure simulation/process-based models can forecast a variable without having seen its history.

**Questions for the model developer:**

- Should `InputRequirement` declare which variables are forecast targets? Or should target declaration live elsewhere (e.g. a separate field on the model protocol)?
- Do your models always have historical observations of the target variable, or do some models forecast without past target data?
- Should the interface enforce that `ModelOutput.variables` keys match declared targets?

---

## 3. `VariableMetadata` Field Review

**Status:** Partially resolved

`VariableMetadata` currently has: `name`, `unit`, `resolution`, `timedelta`, `forecast_horizon`, `offset`.

### Fields confirmed as necessary
- **`unit`** — consumed by the SAPPHIRE_flow adapter (mapped to string)
- **`timedelta`** — consumed by the adapter as `time_step`
- **`resolution`** — not redundant with `timedelta`; it is the categorical label (e.g. SUB_DAILY) that `timedelta` refines (e.g. 15min). Could benefit from a cross-validator.
- **`offset`** — number of timesteps (of length `timedelta`) between the last observed data point and the first forecast step. Not currently consumed by SAPPHIRE_flow but potentially relevant for lead-time aware skill scoring.

### Fields to discuss
- **`name`** — currently redundant with the dict key in `ModelOutput.variables`. No validator enforces `key == metadata.name`. The adapter uses only the dict key. Should we remove `name` and rely solely on the dict key, or add a validator to keep them in sync?
- **`forecast_horizon`** — never consumed; SAPPHIRE_flow derives the horizon from the DataFrame row count. Is there a use case where a declared horizon that differs from actual rows is meaningful (e.g. the model intended to produce 48 steps but only managed 30)?

### DataFrame `issue_datetime` column
Every DataFrame requires an `issue_datetime` column, but the adapter drops it immediately and uses only the top-level `ModelOutput.issue_datetime` scalar. No cross-validation ensures they match. With multi-station output (question 1), the column could become meaningful (per-station issue times). Should we remove the column requirement for now, or add a validator?

---

## 4. Quantile Minimum Count

**Status:** Open

ForecastInterface currently allows ≥1 quantile level. SAPPHIRE_flow requires ≥7 with min ≤ 0.05 and max ≥ 0.95.

**Proposal:** Set ForecastInterface minimum to ≥3 (structurally meaningful: center + two tails) and leave SAPPHIRE's stricter constraint as an operational requirement enforced at the adapter boundary.

**Question for the model developer:**
- Is there a valid use case for producing fewer than 3 quantiles?

---

## 5. Model State for Recurrent Models

**Status:** Resolved — keep ForecastInterface state-free

SAPPHIRE_flow manages model state on the orchestrator side (`PgModelStateStore`, `WarmUpSource`, `prior_state` parameter on predict). ForecastInterface's `predict()` has no state parameter and no state in the return.

**Decision:** ForecastInterface remains state-free. Stateful models (LSTMs etc.) either:
- Reconstruct state from the lookback window provided in inputs (warm-up from data)
- Get state injected by a thin SAPPHIRE_flow adapter wrapping the FI model

If needed later, optional `restore_state(bytes)` / `dump_state() -> bytes` methods on the protocol would be a clean extension.

**Question for the model developer:**
- Can your stateful models always reconstruct their internal state from a sufficiently long lookback window? Or do some models strictly require persisted state between calls?
