# Open Design Questions

This file tracks design decisions for the ForecastInterface (FI) — the model-author-facing contract — and the questions still owed to the model developer.

## Context

ForecastInterface (FI) is the contract model authors implement. SAPPHIRE Flow (SAP3) consumes FI models through a thin, planned-but-not-yet-built `ForecastInterfaceAdapter`. Governance (SAP3 doc 014, "ForecastInterface Adapter Design") sets the ownership boundaries:

- **FI OUTPUT types are authoritative** — SAP3 adapts to them.
- **FI INPUT types are co-designed** via a SAP3 → FI PR.
- **FI's INTERFACE / protocol is FI-owned**, with SAP3 wrapping thin.

These decisions are reflected in `docs/model_interface.md` and the new `docs/fi-sap3-mapping.md` (the FI ↔ SAP3 adapter mapping). This file does not duplicate their content.

---

# 1. Resolved decisions

Questions that SAP3's behaviour already settles. Each is marked resolved with its rationale and where it will be reflected.

## 1.1 Multi-station output structure — RESOLVED

**Decision:** `ModelOutput.variables` becomes `dict[str, dict[str, VariableOutput]]` (station_id → variable_name → `VariableOutput`).

```python
class ModelOutput(BaseModel):
    model_name: str
    issue_datetime: datetime
    variables: dict[str, dict[str, VariableOutput]]
    #               ^station_id  ^variable_name
```

A single-station model returns a dict with one key, e.g. `{"station_xyz": {"discharge": ..., "water_level": ...}}`. The per-variable DataFrames stay per-station — the station dimension lives in the dict structure, not in a `station_id` column inside the forecast DataFrames.

**Rationale:** matches SAP3's GROUP-path output `dict[StationId, dict[str, ForecastEnsemble]]` and Nepal requirement §2. Missing stations must be explicit **FAILURE entries**, never absent keys.

**Cross-repo note:** this advances a v1-deferred GROUP-path item and requires SAP3's adapter to extend from STATION-only to GROUP — a cross-repo coordination item.

**Reflected in:** `docs/model_interface.md`, `docs/fi-sap3-mapping.md`.

## 1.2 Target declaration — RESOLVED

**Decision:** FI will declare `target_parameters` (plus, per target, its unit and supported output representation), parallel to feature inputs.

**Rationale:** mirrors SAP3's `ModelDataRequirements.target_parameters`. SAP3 doc 014 Task 3 explicitly plans to PR `target_parameters` + `spatial_input_type` into FI's input spec.

**Reflected in:** `docs/input_requirement.md` (later phase).

## 1.3 Model state — RESOLVED (already)

**Decision:** FI stays **state-free**. SAP3's `prior_state` bytes are handled entirely by the adapter. An optional `dump_state()` / `restore_state(bytes)` pair on the protocol is a **future extension only**, not part of the current contract.

**Rationale:** state management is orchestrator-side concern (SAP3's `PgModelStateStore`, `WarmUpSource`, `prior_state` on predict). FI's `predict()` has no state parameter and no state in its return.

**Reflected in:** `docs/model_interface.md`.

## 1.4 Spatial vocabulary — RESOLVED

**Decision:** align FI's spatial vocabulary to SAP3's `SpatialRepresentation` enum:

| FI value | Notes |
|---|---|
| `POINT` | |
| `BASIN_AVERAGE` | replaces the old `LUMPED` |
| `ELEVATION_BAND` | replaces the old `HRU` |
| `GRIDDED` | |

Banded Snowmapper SWE / snowmelt is declared at `ELEVATION_BAND`.

**Reflected in:** `docs/input_requirement.md`, `docs/model_interface.md`.

## 1.5 Quantile floor — RESOLVED (split responsibility)

**Decision:** FI proposes a **structural minimum of ≥3 quantiles** (center + two tails). SAP3's operational requirement of **≥7 quantiles with tail coverage** (a level ≤ 0.05 and a level ≥ 0.95) is enforced at the **adapter boundary**, NOT in FI.

An FI model emitting fewer than 7 quantiles is **structurally valid but NOT operationally usable in SAP3**.

**Reflected in:** `docs/model_interface.md`, `docs/fi-sap3-mapping.md`.

## 1.6 Nepal v1 deployment specifics — RESOLVED (model developer)

**Decisions provided by the model developer:**

- **First artifact scope: the eastern regional group ships first.** The first production artifact is therefore **GROUP-scoped** (`ArtifactScope.GROUP`). This makes the station-keyed output of decision 1.1 and the GROUP adapter path **load-bearing from day one**, not a later concern.
- **SnowMapper forcing starts with SWE and ROF** (snow water equivalent and runoff), declared as **banded dynamic forcing at `ELEVATION_BAND`** (see decision 1.4). Specific **lead times** are still to be confirmed — see Q7 residual.
- **Artifact transfer direction is east → west** (an eastern group artifact applied to western gauges). This makes the embedding-key / station-set-mismatch contract (Nepal §8) concrete: the eastern GROUP artifact **must define its behaviour when applied to the western station set** — handle gracefully or raise an explicit error, never silently associate a station with the wrong embedding.

**Reflected in:** `docs/nepal-model-requirements.md`, `docs/model_interface.md` (artifact portability), `docs/fi-sap3-mapping.md` (artifact metadata ownership).

---

# 2. Open questions for the model developer

A decision-ready list. Each needs the model developer's input before the corresponding spec is frozen.

### Q1 — Station ID typing

SAP3 uses a typed `StationId = NewType(..., UUID)`. Should FI expose **opaque `str` station keys** (the adapter maps them to/from `StationId`), or **adopt typed IDs** directly? And: is there any case where the model defines its own spatial units that do **not** map 1:1 to the input station IDs?

### Q2 — Past-target availability

Do all your models see the **target's own history**, or do some pure-simulation / process-based models forecast a target **without** any past observations of it? This determines whether past-target is a *required* declared input or an optional one.

### Q3 — Quantile minimum

Is there any valid use case for emitting **fewer than 3 quantiles**? (Reminder: anything below 7 is non-operational in SAP3.)

### Q4 — State reconstruction

Can every stateful model rebuild its internal state from a **sufficiently long lookback window**, or does any model **strictly require persisted hidden state** between calls? (Confirms decision 1.3 covers all cases.)

### Q5 — `VariableMetadata` fields

`VariableMetadata` currently has `name`, `unit`, `resolution`, `timedelta`, `forecast_horizon`, `offset`. Three points to settle:

- **(a) `name`** — redundant with the dict key in `ModelOutput.variables`. Drop `name`, or keep it and add a validator enforcing `key == metadata.name`?
- **(b) `forecast_horizon`** — this **is consumed** by the (designed) adapter: SAP3 doc 014 (lines 149, 228–229) assigns `ForecastEnsemble.forecast_horizon_steps` directly from `VariableMetadata.forecast_horizon`. The open question is **not** whether to keep it (we do) but whether to add a **cross-validator** that it matches the DataFrame row count.
- **(c) `offset`** — confirm semantics: number of steps (each of length `timedelta`) between the last observed point and the first forecast step.

### Q6 — Per-row `issue_datetime` column

The adapter maps `ModelOutput.issue_datetime` → `ForecastEnsemble.issued_at` and renames the per-row datetime column → `valid_time`. The question is whether to **keep the per-row `issue_datetime` column requirement** — with a cross-validator that it matches the top-level `issue_datetime` for forecasts — or **relax it**. Frame this as a validator question, not a removal: the column is not "dropped", it is renamed and re-used.

### Q7 — SnowMapper lead times (residual)

The Nepal deployment specifics are otherwise settled (see decision 1.6): the eastern regional group ships first, SnowMapper forcing starts with **SWE** and **ROF**, and artifact transfer is **east → west**. The one residual: which **lead times** of SWE and ROF will the model consume — past-known lookback, future-known horizon, and how far in each?
