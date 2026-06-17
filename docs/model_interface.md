# Model Interface

The primary goal of this package is to define the interface between any forecasting library and the forecasting model. The forecasting model can be implemented in any package / code base but needs to follow the protocol defined here.

There are **three protocols**: the required `ForecastModel`, plus two optional extensions — `RetrainableModel` (warm-start `retrain`) and `BatchHindcastModel` (efficient batch `hindcast`), both of which extend `ForecastModel`. A `StatefulModel` extension is **reserved** for future conceptual / hybrid models (see *Warm-up and state* below). The scope of a model (single station vs. group / national) is **declared** via `artifact_scope`, not split into separate protocols. SAP3 consumes the FI protocol through a thin adapter that dispatches to its own `StationForecastModel` / `GroupForecastModel` — see [`docs/fi-sap3-mapping.md`](./fi-sap3-mapping.md). The driving requirements for the first (Nepal v1) integration are in [`docs/nepal-model-requirements.md`](./nepal-model-requirements.md).

Core functionalities include:

**Forecast Function** `predict()`
Takes as input the `ModelInputs` and a trained artifact, and outputs the `ModelOutput` (Forecast).

**Hindcast Function** `hindcast()` — *optional, strongly recommended*
Lives on the optional `BatchHindcastModel` extension. Takes a trained artifact and a **batch** of issue datetimes, and outputs the `ModelOutput` (Hindcast) for all of them in one call. Functionally equivalent to looping `predict()` over historical issue times, but vectorized for efficiency. SAP3 uses the batch path whenever the model implements it and falls back to looping `predict()` otherwise — because SAP3 runs hindcasts routinely (skill evaluation), implementing it is strongly recommended.

**Training Functions** `train()` / `retrain()`
Produce a `TrainedArtifact` from training inputs. See the Training & Lifecycle Protocol below.

---

## Training & Lifecycle Protocol

> **Status: implemented** in `forecast_interface/interface/` (`protocol.py`, `scope.py`, `artifact.py`). The `inputs` parameters use FI-owned `ModelInputs`; only `config` remains **provisional** — typed `Any` until the model-config type is co-designed with SAP3 (Q8). Rich `TrainedArtifact` provenance metadata is **deferred to Phase 4** (see [`docs/nepal-model-requirements.md`](./nepal-model-requirements.md) §4); the group-artifact embedding-key / station-set-mismatch contract is **v1 load-bearing** (see the `TrainedArtifact` section below and decision 1.10).

### Scope: `ArtifactScope`

A model declares its scope via the `artifact_scope` attribute rather than implementing a scope-specific protocol.

```python
class ArtifactScope(Enum):
    STATION = "station"  # one artifact per station
    GROUP = "group"      # one artifact covering multiple stations
```

A "national-group" model is a `GROUP` (it is just a group whose station set happens to be national). There is no separate national scope. (SAP3 has an internal `VIRTUAL` scope for combination models; that is SAP3-internal and not model-author-facing, so it is not part of this enum.)

### The `ForecastModel` protocol surface

`train`, `predict`, `serialize_artifact` and `deserialize_artifact` are **required**. Two optional capabilities each live on a **separate** extension protocol, so they are not forced on every model: warm-start `retrain` on `RetrainableModel`, and batch `hindcast` on `BatchHindcastModel`. SAP3 detects each with `isinstance` — `isinstance(model, RetrainableModel)` to decide whether to warm-start (else it falls back to `train`), and `isinstance(model, BatchHindcastModel)` to decide whether to batch-hindcast (else it loops `predict`).

| Member | Signature | Protocol | Notes |
|---|---|---|---|
| `input_requirement` | `property -> InputRequirement` | `ForecastModel` | Declares data needs **and forecast targets** — `InputRequirement.targets` (`dict[str, TargetSpec]`) names each target variable with its `unit` and supported output `representations` (see `docs/input_requirement.md`). |
| `artifact_scope` | `attribute: ArtifactScope` | `ForecastModel` | Declared scope (`STATION` / `GROUP`). |
| `train` | `train(inputs, *, config, rng) -> TrainedArtifact` | `ForecastModel` | Cold, full rebuild from scratch. The required baseline every model must support. |
| `predict` | `predict(artifact, *, inputs, issue_datetime, rng) -> ModelResult` | `ForecastModel` | Forecast. Returns FI's `ModelResult` → `ModelOutput`. |
| `hindcast` | `hindcast(artifact, *, inputs, issue_datetimes, rng) -> ModelResult` | `BatchHindcastModel` | **Optional, strongly recommended.** Batch hindcast over many issue datetimes in one call; same `ModelResult` return as `predict`. Absent it, SAP3 loops `predict`. |
| `serialize_artifact` | `serialize_artifact(artifact) -> bytes` | `ForecastModel` | Opaque byte serialization of a `TrainedArtifact`. |
| `deserialize_artifact` | `deserialize_artifact(raw: bytes) -> TrainedArtifact` | `ForecastModel` | Inverse of `serialize_artifact`. |
| `retrain` | `retrain(base_artifact, inputs, *, config, rng) -> TrainedArtifact` | `RetrainableModel` | **Optional.** Warm-start from an existing artifact, for models capable of it. Models that cannot warm-start simply do not implement it; callers fall back to `train`. |

The `inputs` parameters use `ModelInputs`; only `config` is typed `Any` (provisional, see status note above).

### Determinism (dependency injection)

`train`, `retrain`, `predict`, and `hindcast` all take an **injected** `rng: random.Random`. Models **MUST** be deterministic under a fixed `(data, config, seed)` triple: the same inputs, the same config, and an RNG seeded the same way must produce identical artifacts and identical outputs. No model may call `random` / `numpy.random` global state or `datetime.now()` directly in its forecast logic — all nondeterminism is injected. This matches both SAP3's contract and the repository's dependency-injection rule.

### `TrainedArtifact`

`TrainedArtifact` is implemented as a **marker `Protocol`** (no members) — a semantic boundary type. It is an **opaque, self-contained, deployment-portable** object representing everything a model needs to produce forecasts:

- **Opaque** to FI: FI never inspects its internals. It is produced by `train` / `retrain` and consumed by `predict` / `hindcast`.
- **Self-contained**: `serialize_artifact` produces `bytes` that embed all weights, scalers, and metadata — **with no absolute filesystem paths** and no machine-local references.
- **Deployment-portable**: `deserialize_artifact(serialize_artifact(a))` must reconstruct an artifact that runs **unchanged on another SAP3 instance**.

**Partly deferred.** Rich provenance metadata (scope, region, training period, hashes, seed, product versions) is **not** part of the marker Protocol yet and lands in Phase 4 (see [`docs/nepal-model-requirements.md`](./nepal-model-requirements.md) §4).

The **group-artifact embedding-key / station-set-mismatch contract**, however, is **load-bearing from v1**, because `GROUP` artifacts ship from the start (decision 1.10) and east→west transfer is a Nepal v1 target (decision 1.6) — re-evaluate its earlier Phase 4 deferral. The contract: a `GROUP` artifact **embeds the meaningful station strings it was trained on** (which the model reads to key per-station state); it must define behaviour when the predict-time station set differs from the trained set — **known** stations use stored state, **unknown** stations are generalized from static attributes or rejected with an explicit error — and it must **never silently mis-associate** a prediction with the wrong station. Station strings are **stable, meaningful identifiers** that round-trip unchanged through `serialize_artifact` / `deserialize_artifact` and across deployments; the model never alters them.

### Warm-up and state (state-free in v0)

FI's protocol is **state-free in v0**: `predict` / `hindcast` take no `state` parameter and return no state. This is a deliberate, lightweight default. It rests on separating two things commonly conflated as "warm-up":

- **Warm-up *period* (cold spin-up)** — the run of forcing a model needs *before* the issue time to spin its internal stores up from nothing. This needs **no new channel**: it is declared as `lookback` in `InputRequirement`. Any model that needs a spin-up period simply requires a sufficiently long lookback. Covered for **all** model types in v0.
- **Persisted warm *state* (cross-cycle snapshot)** — SAP3's `prior_state` / `new_state` bytes, carrying spun-up state from the previous cycle so it need not be re-spun each run. This is purely an **optimization**, and it is **deferred from v0**.

**Why deferred, not dropped.** The model integrating in v1 is **pure ML**: it reconstructs everything from its lookback window each cycle and needs neither a warm-up period nor persisted state. Warm-up state is required for conceptual / distributed models and *may* be required for hybrid models — but none exist in the interface yet. Building a state channel now would tax every (currently stateless) model author with state ceremony they never use, which conflicts with keeping the interface lightweight and easy for humans and machines to adhere to. We therefore ship the single clean signature and **reserve** state as a future extension.

**The reserved extension is additive and non-breaking.** When a conceptual / hybrid model that genuinely needs persisted state arrives, state support is added as an **optional `StatefulModel` sub-protocol** extending `ForecastModel` — exactly as `RetrainableModel` already does for warm-start. SAP3 detects it via `isinstance(model, StatefulModel)` and threads `prior_state` only for those models; existing `ForecastModel` implementations do not change a line. The precise shape of that extension (state as an extra `predict` parameter, a distinct method, or carried inside `ModelResult`) is **deliberately left open** until a real stateful model forces the decision — designing it against a concrete model beats guessing now.

> **Correction to the earlier framing.** A previous note claimed `prior_state` could be "handled entirely inside the SAP3 adapter." That is not implementable: an adapter cannot inject state into a `predict` that has no state parameter. The correct resolution is the additive `StatefulModel` sub-protocol above.

**SAP3 consistency.** A state-free FI model maps onto SAP3 as a model that ignores `prior_state` and always runs `WarmUpSource.FRESH` — already legal SAP3 behaviour for stateless models. The single divergence to record: **FI v0 does not use SAP3's warm-up-snapshot path; FI models warm up from `lookback`.**

### Output stays FI-authoritative

`predict` / `hindcast` **return** `ModelResult` → `ModelOutput` (defined below). `ModelOutput` is **not** replaced by SAP3's `ForecastEnsemble`: the SAP3 adapter maps `ModelOutput` *into* its own representation, never the other way around. See [`docs/fi-sap3-mapping.md`](./fi-sap3-mapping.md) for the field-level mapping.

### Failure & result model

`predict` / `hindcast` return `ModelResult = ModelSuccess | ModelFailure` rather than raising. In operational forecasting, failure for a given cycle or station is **routine, not exceptional** (gauges offline, degraded inputs), so it is modelled as a typed outcome carrying a structured `FailureCause`, not an exception. SAP3's `except`-and-return path stays only as a **backstop** for unanticipated bugs — *anticipated* failure must be returned, not raised.

Failure is represented at **two levels**, with a strict rule for which to use:

| Level | Type | Means | When |
|---|---|---|---|
| Whole-run | `ModelFailure` (the union branch) | the model produced **nothing at all** | no artifact, invalid config, dependency down, whole input bundle malformed |
| Per-station / variable | `VariableStatus.FAILURE` inside `ModelOutput` | the model ran and produced output for some stations/variables, but **this one** could not | that station's inputs missing or too degraded |

**Rule:** if the model can produce output for **even one** station/variable, it returns `ModelSuccess` with per-entry `FAILURE` / `PARTIAL` status; `ModelFailure` is reserved for **total** inability to produce anything.

`ModelFailure` carries `cause: FailureCause` (`INPUT_DATA` / `RESOURCE` / `MODEL_ERROR` / `CONFIGURATION` / `DEPENDENCY`) and a human-readable `message`. Per-station `FAILURE` entries currently carry only `status` + `flags` (e.g. `DATA_AVAILABILITY`); attaching a per-station `FailureCause` is a **possible future enhancement**, deferred to keep the per-entry surface light.

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

**Forecast** (`predict`): `issue_datetime` is constant across all rows (a single issue time).
**Batch hindcast** (`BatchHindcastModel.hindcast`): `issue_datetime` **varies** across rows (one block of rows per issue time in the batch).

`predict` and `hindcast` return the **same** `ModelOutput` type; the only distinction is whether `issue_datetime` is constant (forecast) or varies (batch hindcast) across rows. The varying-`issue_datetime` schema therefore only arises from the optional `BatchHindcastModel` path — a plain `ForecastModel` always emits a constant `issue_datetime`.

### Data Classes

Each data class wraps a DataFrame with the two temporal columns above, plus class-specific value columns:

**DeterministicData** — columns: `[issue_datetime, datetime, value]`. A single point forecast. **Valid output, but not operationally consumable by SAP3 on its own** — SAP3 has no deterministic channel (it is always probabilistic). A deterministic-only model is a legitimate, possibly strong model; to deploy it operationally it must *also* supply forecast uncertainty — quantiles or trajectories it emits itself, or a downstream uncertainty wrapper that produces them. See the operational-floor note below.

**QuantileData** — columns: `[issue_datetime, datetime, <quantile_level>, ...]`
Quantile columns are named by their level as strings (e.g., `"0.1"`, `"0.5"`, `"0.9"`). Levels must be in (0, 1), sorted ascending, and unique. **FI structural minimum: ≥ 3 levels** (a centre plus two tails).

**TrajectoryData** — columns: `[issue_datetime, datetime, "1", "2", ..., "<N>"]`
Sample columns are named `"1"` through `"<num_samples>"`. **FI structural minimum: ≥ 8 samples.** Models typically emit ~50 (deployment-specific, may be fewer).

**EpistemicUncertaintyData** — columns: `[issue_datetime, datetime, std, range]`
Captures model uncertainty as standard deviation and range. (Dropped at the SAP3 boundary in v0b; see the mapping doc.)

#### Operational floor — structural vs. operational

FI enforces only **deployment-independent structural floors** (≥3 quantiles, ≥8 trajectories; a probabilistic representation is required for operational use). The **operational floors are SAP3 deployment config** — `min_operational_quantile_levels` (≥7, with tail coverage ≤0.05 / ≥0.95) and `min_operational_ensemble_size` (≥20 members) — so they live on the SAP3 side, not in FI. To stop this failing *silently* at runtime, the model **declares the representation(s) and the count it will emit** (via `TargetSpec` / metadata), and SAP3 checks compatibility against its deployment floor at **integration / registration time**. Net rule: *valid FI output **and** declared counts ≥ the deployment floor ⟹ operational*; anything short is rejected loudly before any forecast runs, never silently dropped.

### VariableOutput

Groups data for a single output variable (within a single station):

| Field | Type | Description |
|---|---|---|
| `metadata` | `VariableMetadata` | `unit`, `timedelta`, `forecast_horizon`, `offset` (no `name` — variable name is the dict key; no `resolution` enum — `timedelta` is the single time-step source). See *Metadata semantics* below. |
| `deterministic` | `DeterministicData \| None` | Point forecast |
| `quantiles` | `QuantileData \| None` | Quantile forecast |
| `trajectories` | `TrajectoryData \| None` | Ensemble trajectories |
| `epistemic_uncertainty` | `EpistemicUncertaintyData \| None` | Model uncertainty |
| `flags` | `frozenset[ForecastFlag]` | Quality flags (empty = trusted) |
| `status` | `VariableStatus` | `SUCCESS`, `FAILURE`, or `PARTIAL` |

At least one of `deterministic`, `quantiles`, or `trajectories` must be present when status is `SUCCESS`.

`variables` must contain at least one station entry, and each station's inner dict must contain at least one variable. When status is `PARTIAL`, at least one data representation must still be present (same rule as `SUCCESS`). A station that produced no usable data is represented by a `FAILURE` `VariableOutput`, not by an empty or missing entry.

### Metadata semantics

- **`forecast_horizon`** — number of forecast steps; **consumed directly by the SAP3 adapter** (`ForecastEnsemble.forecast_horizon_steps`). A cross-validator enforces it against the data: for `predict`, `forecast_horizon` equals the row count; for batch `hindcast` it equals the rows **per `issue_datetime`** (one block per issue time).
- `forecast_horizon` equals the actual forecast steps present per issue block, so a `PARTIAL` / short forecast declares a smaller `forecast_horizon` and still satisfies the validator.
- **`offset`** — number of steps (each `timedelta` long) between the **last observation and the first forecast step**. `offset = 1` ⇒ the first forecast valid time is `last_obs + 1·timedelta` (the usual next-step case); `offset = 2` ⇒ a one-step gap.
- **No `name`** — the variable name is the `ModelOutput.variables[station][variable]` dict key; duplicating it in metadata is omitted to avoid two disagreeing sources of truth.
- **`timedelta` is the single time-step source** — there is no `resolution` enum (it would be a second, disagreeable source of truth). The time step is a precise `timedelta`, matching the `timedelta`-keyed input requirement (decision 1.12).

### ForecastFlag

Quality flags that can be attached to a variable output:

- `HIGH_EPISTEMIC_UNCERTAINTY` — model confidence is low
- `DATA_AVAILABILITY` — input data was degraded

A variable with no flags is considered `trusted`.
