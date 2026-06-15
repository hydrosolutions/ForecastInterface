# Model Interface

The primary goal of this package is to define the interface between any forecasting library and the forecasting model. The forecasting model can be implemented in any package / code base but needs to follow the protocol defined here.

There are **two protocols**: the required `ForecastModel`, and `RetrainableModel` (which extends `ForecastModel`) for the optional warm-start retrain capability. The scope of a model (single station vs. group / national) is **declared** via `artifact_scope`, not split into separate protocols. SAP3 consumes the FI protocol through a thin adapter that dispatches to its own `StationForecastModel` / `GroupForecastModel` — see [`docs/fi-sap3-mapping.md`](./fi-sap3-mapping.md). The driving requirements for the first (Nepal v1) integration are in [`docs/nepal-model-requirements.md`](./nepal-model-requirements.md).

Core functionalities include:

**Forecast Function** `predict()`
Takes as input the `ModelInput` and a trained artifact, and outputs the `ModelOutput` (Forecast).

**Hindcast Function** `hindcast()`
Takes as input the `ModelInput` and a trained artifact, and outputs the `ModelOutput` (Hindcast).

**Training Functions** `train()` / `retrain()`
Produce a `TrainedArtifact` from training inputs. See the Training & Lifecycle Protocol below.

---

## Training & Lifecycle Protocol

> **Status: implemented** in `forecast_interface/interface/` (`protocol.py`, `scope.py`, `artifact.py`). The `inputs` and `config` parameters remain **provisional** — typed `Any` until the assembled-input bundle and model-config types are co-designed with SAP3 (doc 014 Task 3, the SAP3→FI input-types PR). Rich `TrainedArtifact` provenance metadata and the group-artifact embedding-key / station-set-mismatch contract are **deferred to Phase 4** (see [`docs/nepal-model-requirements.md`](./nepal-model-requirements.md) §4 and §8).

### Scope: `ArtifactScope`

A model declares its scope via the `artifact_scope` attribute rather than implementing a scope-specific protocol.

```python
class ArtifactScope(Enum):
    STATION = "station"  # one artifact per station
    GROUP = "group"      # one artifact covering multiple stations
```

A "national-group" model is a `GROUP` (it is just a group whose station set happens to be national). There is no separate national scope. (SAP3 has an internal `VIRTUAL` scope for combination models; that is SAP3-internal and not model-author-facing, so it is not part of this enum.)

### The `ForecastModel` protocol surface

`train`, `predict`, `hindcast`, `serialize_artifact` and `deserialize_artifact` are **required**. The optional warm-start `retrain` lives on a **separate** protocol, `RetrainableModel` (which extends `ForecastModel`), so it is not forced on every model. SAP3 checks `isinstance(model, RetrainableModel)` to know whether warm-start is supported; otherwise it falls back to `train`.

| Member | Signature | Protocol | Notes |
|---|---|---|---|
| `input_requirement` | `property -> InputRequirement` | `ForecastModel` | Declares data needs **and forecast targets** — `InputRequirement.targets` (`dict[str, TargetSpec]`) names each target variable with its `unit` and supported output `representations` (see `docs/input_requirement.md`). |
| `artifact_scope` | `attribute: ArtifactScope` | `ForecastModel` | Declared scope (`STATION` / `GROUP`). |
| `train` | `train(inputs, *, config, rng) -> TrainedArtifact` | `ForecastModel` | Cold, full rebuild from scratch. The required baseline every model must support. |
| `predict` | `predict(artifact, *, inputs, issue_datetime, rng) -> ModelResult` | `ForecastModel` | Forecast. Returns FI's `ModelResult` → `ModelOutput`. |
| `hindcast` | `hindcast(artifact, *, inputs, issue_datetime, rng) -> ModelResult` | `ForecastModel` | Hindcast. Same return type as `predict`. |
| `serialize_artifact` | `serialize_artifact(artifact) -> bytes` | `ForecastModel` | Opaque byte serialization of a `TrainedArtifact`. |
| `deserialize_artifact` | `deserialize_artifact(raw: bytes) -> TrainedArtifact` | `ForecastModel` | Inverse of `serialize_artifact`. |
| `retrain` | `retrain(base_artifact, inputs, *, config, rng) -> TrainedArtifact` | `RetrainableModel` | **Optional.** Warm-start from an existing artifact, for models capable of it. Models that cannot warm-start simply do not implement it; callers fall back to `train`. |

The `inputs` and `config` parameters are typed `Any` (provisional, see status note above).

### Determinism (dependency injection)

`train`, `retrain`, `predict`, and `hindcast` all take an **injected** `rng: random.Random`. Models **MUST** be deterministic under a fixed `(data, config, seed)` triple: the same inputs, the same config, and an RNG seeded the same way must produce identical artifacts and identical outputs. No model may call `random` / `numpy.random` global state or `datetime.now()` directly in its forecast logic — all nondeterminism is injected. This matches both SAP3's contract and the repository's dependency-injection rule.

### `TrainedArtifact`

`TrainedArtifact` is implemented as a **marker `Protocol`** (no members) — a semantic boundary type. It is an **opaque, self-contained, deployment-portable** object representing everything a model needs to produce forecasts:

- **Opaque** to FI: FI never inspects its internals. It is produced by `train` / `retrain` and consumed by `predict` / `hindcast`.
- **Self-contained**: `serialize_artifact` produces `bytes` that embed all weights, scalers, and metadata — **with no absolute filesystem paths** and no machine-local references.
- **Deployment-portable**: `deserialize_artifact(serialize_artifact(a))` must reconstruct an artifact that runs **unchanged on another SAP3 instance**.

**Deferred to Phase 4.** Rich provenance metadata (scope, region, training period, hashes, seed, product versions) and the group-artifact embedding-key / station-set-mismatch contract are **not** part of the marker Protocol yet; they land in Phase 4 (see [`docs/nepal-model-requirements.md`](./nepal-model-requirements.md) §4 and §8). The intended contract: an artifact whose scope is `GROUP` typically embeds the station identifiers it was trained on, must document its embedding key, must define behaviour when the predict-time station set differs from the trained set, and must **never silently mis-associate** a prediction with the wrong station.

### State-free

FI's protocol is **state-free**: there is no `state` parameter and no state in the return value. SAP3's `prior_state` bytes are handled entirely inside the SAP3 adapter (see [`docs/fi-sap3-mapping.md`](./fi-sap3-mapping.md)), not by the FI protocol. An optional `dump_state` / `restore_state` pair is noted only as a **possible future extension** and is out of scope for v1.

### Output stays FI-authoritative

`predict` / `hindcast` **return** `ModelResult` → `ModelOutput` (defined below). `ModelOutput` is **not** replaced by SAP3's `ForecastEnsemble`: the SAP3 adapter maps `ModelOutput` *into* its own representation, never the other way around. See [`docs/fi-sap3-mapping.md`](./fi-sap3-mapping.md) for the field-level mapping.

---

## ModelOutput

`ModelOutput` is the unified return type for both `predict()` and `hindcast()`.

| Field | Type | Description |
|---|---|---|
| `model_name` | `str` | Identifier of the model that produced the output |
| `issue_datetime` | `datetime` (UTC) | Single issue datetime for the entire output |
| `variables` | `dict[str, dict[str, VariableOutput]]` | Station-keyed: `station_id → variable_name → VariableOutput` |
| `success` | `bool` | Computed property — `True` when all variables (across all stations) contain valid data |

### Station-keyed variables

`variables` is keyed first by `station_id`, then by `variable_name`. This supersedes the previous flat `dict[str, VariableOutput]`.

- A **single-station** model returns a one-key dict (`{station_id: {variable_name: VariableOutput}}`).
- A **group / national** model returns one entry per station it forecasts.
- **Missing stations are explicit `FAILURE` entries**, never absent keys. A caller can always look up every expected station; the absence of usable data is represented by a `VariableOutput` with `status == FAILURE`, not by a missing key.

### DataFrame Column Schema

All data classes share a unified DataFrame schema with two required datetime columns:

| Column | Type | Description |
|---|---|---|
| `issue_datetime` | `datetime` (UTC) | When the forecast/hindcast was issued |
| `datetime` | `datetime` (UTC) | The target valid time of the prediction |

**Forecast**: `issue_datetime` is constant across all rows (single issue time).
**Hindcast**: `issue_datetime` varies across rows (multiple issue times).

`predict` and `hindcast` return the **same** `ModelOutput` type; the only distinction is whether `issue_datetime` is constant (forecast) or varies (hindcast) across rows.

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

Groups data for a single output variable (within a single station):

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

`variables` must contain at least one station entry, and each station's inner dict must contain at least one variable. When status is `PARTIAL`, at least one data representation must still be present (same rule as `SUCCESS`). A station that produced no usable data is represented by a `FAILURE` `VariableOutput`, not by an empty or missing entry.

### ForecastFlag

Quality flags that can be attached to a variable output:

- `HIGH_EPISTEMIC_UNCERTAINTY` — model confidence is low
- `DATA_AVAILABILITY` — input data was degraded

A variable with no flags is considered `trusted`.
