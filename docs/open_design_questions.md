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

## 1.3 Model state / warm-up — RESOLVED (refined)

**Decision:** FI is **state-free in v0**, separating two things conflated as "warm-up":

- **Warm-up *period* (cold spin-up)** is declared as `lookback` in `InputRequirement` — no new channel, available to all model types.
- **Persisted warm *state* (cross-cycle snapshot)** — SAP3's `prior_state` / `new_state` bytes — is **deferred from v0** and **reserved** as an additive, non-breaking `StatefulModel` sub-protocol (the same `isinstance`-detected pattern as `RetrainableModel`), to be designed when a conceptual / hybrid model actually requires it.

**Rationale:** the v1 model is pure ML (see Q4, now answered) — it reconstructs state from its lookback window and needs neither a warm-up period nor persisted state. A state channel built now would tax every stateless author with unused ceremony, against the goal of a lightweight interface. The earlier framing — "`prior_state` handled entirely by the adapter" — was **incorrect**: an adapter cannot inject state into a `predict` that has no state parameter. The correct resolution is the additive sub-protocol above.

**SAP3 consistency:** a state-free FI model maps to a SAP3 model that ignores `prior_state` and always runs `WarmUpSource.FRESH`. The one recorded divergence: FI v0 does not use SAP3's warm-up-snapshot path.

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

## 1.5 Output floors & deterministic output — RESOLVED (refined)

**Decision:** FI enforces **deployment-independent structural floors** only; SAP3's deployment-configurable operational floors are checked **loudly at integration time**, not silently at runtime.

- **FI structural floors (hard validators):** QuantileData **≥ 3** levels (centre + two tails); TrajectoryData **≥ 8** samples. *(Code TODO: validators currently enforce ≥1 quantile / >0 trajectory — tighten to ≥3 / ≥8.)*
- **SAP3 operational floors (deployment config, SAP3-side):** `min_operational_quantile_levels` ≥ 7 with tail coverage (a level ≤0.05 and a level ≥0.95); `min_operational_ensemble_size` ≥ 20 members. Kept out of FI because they are deployment-specific.
- **Deterministic-only is allowed, not forbidden.** A deterministic model may be strong; FI accepts deterministic output as structurally valid. But SAP3 has **no deterministic channel**, so deterministic-only is **non-operational** until the model supplies forecast uncertainty (quantiles/trajectories it emits, or a downstream uncertainty wrapper).
- **No silent non-operational output.** The model declares its representation(s) and emitted count; SAP3 checks them against its deployment floor at **integration/registration time** and rejects incompatibles loudly. Net: *valid FI + declared counts ≥ deployment floor ⟹ operational.*

**Authority-rule refinement (from Q1):** the Q1 principle — "FI must not express a model SAP3 can't operate" — is refined to: FI **may** express not-yet-operational models (e.g. deterministic-only), provided the non-operational state is **never silent** — it is declared, caught loudly at the SAP3 boundary, and has a documented path to operational.

**Model developer input (Nepal):** the model emits **quantiles** (count configurable at training); **trajectories** typically ~50 (deployment-specific, may be fewer).

**Reflected in:** `docs/model_interface.md`, `docs/fi-sap3-mapping.md`.

## 1.6 Nepal v1 deployment specifics — RESOLVED (model developer)

**Decisions provided by the model developer:**

- **First artifact scope: the eastern regional group ships first.** The first production artifact is therefore **GROUP-scoped** (`ArtifactScope.GROUP`). This makes the station-keyed output of decision 1.1 and the GROUP adapter path **load-bearing from day one**, not a later concern.
- **SnowMapper forcing starts with SWE and ROF** (snow water equivalent and runoff), declared as dynamic forcing at **`BASIN_AVERAGE` or `ELEVATION_BAND`** (see decision 1.4; Q7 broadened this from ELEVATION_BAND-only). Lead times / resolutions follow the ECMWF forecast and ERA5-Land (Q7), with a possible SnowMapper availability lag (Q9).
- **Artifact transfer direction is east → west** (an eastern group artifact applied to western gauges). This makes the embedding-key / station-set-mismatch contract (Nepal §8) concrete: the eastern GROUP artifact **must define its behaviour when applied to the western station set** — handle gracefully or raise an explicit error, never silently associate a station with the wrong embedding.

**Reflected in:** `docs/nepal-model-requirements.md`, `docs/model_interface.md` (artifact portability), `docs/fi-sap3-mapping.md` (artifact metadata ownership).

## 1.7 Failure channel — RESOLVED

**Decision:** `predict` / `hindcast` return `ModelResult = ModelSuccess | ModelFailure` (structured), they do **not** raise. Two failure levels with a strict rule: `ModelFailure` = total inability to produce anything; `VariableStatus.FAILURE` = per-station/variable failure within an otherwise-successful run. **If even one station/variable is produced, return `ModelSuccess` with per-entry `FAILURE`/`PARTIAL`; reserve `ModelFailure` for total failure.**

**Rationale:** operational per-cycle / per-station failure is routine, not exceptional; a typed outcome with `FailureCause` beats SAP3's catch-and-stringify and is more type-safe. Divergence from SAP3 (which raises) and from Sandro's original (no failure channel) is justified on these grounds; SAP3's `except`-and-return remains a backstop for unanticipated bugs only.

**Deferred:** per-station `FailureCause` on `VariableOutput` (today only `status` + `flags`) — possible future enhancement, kept out to keep the per-entry surface light.

**Reflected in:** `docs/model_interface.md`.

## 1.8 Hindcast — RESOLVED (demoted to optional)

**Decision:** `hindcast` is **removed from the required `ForecastModel` surface** and moved to an optional `BatchHindcastModel(ForecastModel)` sub-protocol with a batch signature `hindcast(artifact, *, inputs, issue_datetimes, rng) -> ModelResult`. SAP3 detects it via `isinstance` and uses the batch path when present; otherwise it **loops `predict`** (its existing behaviour). It is **optional in the type system but strongly recommended** — SAP3 runs hindcasts routinely for skill evaluation, so batch efficiency matters.

**Rationale:** hindcast is functionally "predict over many historical issue times"; the live-vs-archive forcing difference is an *input* difference, not a method difference. A dedicated method buys only batch efficiency, so it is an optimization, not a capability — requiring it would tax every author with a second method. Demoting it makes the required surface minimal (`train` / `predict` / `serialize` / `deserialize`) and is **more** SAP3-consistent (SAP3 has no required `hindcast`). Divergence from Sandro's original (which treated `hindcast` as core) is justified on these grounds and flagged for the Sandro conversation.

**Knock-on:** the varying-per-row `issue_datetime` output schema now arises **only** from the `BatchHindcastModel` path; a plain `ForecastModel` always emits a constant `issue_datetime` (scopes Q6 — see below).

**Reflected in:** `docs/model_interface.md`.

## 1.15 Forecast horizon ownership & issue context — RESOLVED

**Decision:** the **model owns the forecast horizon** — it is not requested by SAP3.

- Three quantities: **capability** (model's max, from training), **forcing-limited** (bounded by delivered `future_steps`), **actual** (= f(capability, forcing)). Only the model knows capability and sees forcing, so only the model computes the actual horizon.
- The model **declares the actual horizon in `metadata.forecast_horizon`** (already in the output, per-variable). SAP3 **checks** it against operational need and flags/rejects if too short (loud-at-boundary), but never dictates it.
- **The bundle (`ModelInputs`) carries no issue scalar at all — it is pure data.** `issue_datetime` (predict) and `issue_datetimes` (batch hindcast) are **separate protocol parameters**, not bundle fields — training has no single issue time, and batch hindcast has many. No requested horizon and no output `time_step` either: the model forecasts at its own trained step/horizon. `future_steps` stays purely forcing extent. `ModelInputs` is therefore uniform across train / predict / hindcast.
- **Multi-horizon / multi-timestep is already structurally supported** — each `VariableOutput` carries its own `metadata.timedelta` + `forecast_horizon`. "Single horizon + single output step" is a v0 *convention*; going multi is a zero-schema-change additive step.

**Deferred (YAGNI):** an optional declared horizon-*capability* field in the input spec for integration-time validation; the output declaration + SAP3's check suffice. Add only if SAP3 needs to validate horizon before the first run.

**Reflected in:** `docs/model_interface.md` (issue context), future `ModelInputs` type (A2).

## 1.14 Output combinability — RESOLVED

**Decision:** combinability is **derived from the output representation**, with no new FI machinery.

- A target supporting **`TRAJECTORIES`** is combinable; **quantile-only or deterministic** output is **not** (SAP3's combination consumes MEMBERS and skips QUANTILES). No `CombinableModel` flag, no opt-out — eligibility rides on the representation.
- The model owes only **per-model internal consistency**: all trajectory members share the same valid times, unit, and horizon (already guaranteed by `TrajectoryData` + `VariableMetadata`). **No cross-model stable member ids** — SAP3 remaps ids (POOLED offsets, BMA resamples).
- **SAP3 owns the combination mechanism entirely:** cross-model compatibility checks (issue / valid times, unit, horizon must agree across models at a station), POOLED/BMA weighting, the `_pooled` / `_bma` sentinel models and `VIRTUAL` scope, and model selection (fallbacks excluded by priority ≥ 90). FI models are unaware they are combined.

**Rationale:** keeps FI minimal; combination is orchestration, not a model-author concern. Confirms FI's existing "combinability derived from TRAJECTORIES" stance and the deliberate omission of `VIRTUAL` scope.

**Reflected in:** `docs/input_requirement.md` (Targets), `docs/model_interface.md` (trajectories).

## 1.13 `max_nan` enforcement — RESOLVED

**Decision:** `max_nan` is the model's **declared per-variable tolerance**, and **SAP3 enforces it as a pre-`predict` gate** — the model is only ever called with inputs within tolerance (the `ModelInputs` bundle is valid-by-construction w.r.t. `max_nan`, per decision 1.9).

- NaNs **exceed** `max_nan` → SAP3 does **not** call the model for that station; it records the failure directly: per-station `VariableStatus.FAILURE` with the `DATA_AVAILABILITY` signal if other stations are serviceable, else whole-run `ModelFailure` (decision 1.7 two-level rule).
- NaNs **within** tolerance (≤ `max_nan`) → data delivered **as-is**; residual NaNs remain and the model handles them (impute/mask). `max_nan` gates the *unacceptable*; it does not promise zero NaNs.

**Rationale:** keeps models defensive-check-free, puts the gate where the data lives (SAP3 — which today delivers raw NaNs, closing that gap), and reuses the existing failure vocabulary (no new types).

**Reflected in:** `docs/input_requirement.md`.

## 1.12 Time step: `timedelta`, not an enum — RESOLVED

**Decision:** represent time step as **`timedelta`**, not the `TemporalResolution` enum. Driven by the v1 requirement for **3-hourly and 6-hourly** steps, which the coarse enum cannot express (`SUB_DAILY` cannot distinguish 3h from 6h — they would collide under one dict key).

- **Input:** the `dynamic` dict is keyed by **`timedelta`** (e.g. `timedelta(hours=3/6/1/24)`). Identity match to SAP3's `time_step` / `supported_time_steps` (already `timedelta`) — this *reduces* divergence, since FI's `TemporalResolution` had no SAP3 counterpart.
- **Output:** **drop the redundant `resolution` enum from `VariableMetadata`**; keep `timedelta` as the single source of truth (same two-sources-of-truth reasoning as dropping `name`, Q5).
- **Retire `TemporalResolution`** from the v1 contract. **Calendar resolutions** (`MONTHLY` / `SEASONAL` / `ANNUAL`, decadal — genuinely not fixed durations) are **out of v1 scope**; if SAPPHIRE later needs pentadal/decadal/monthly forecasting, introduce a dedicated `TimeStep = timedelta | CalendarResolution` type then.

**Deviation from Sandro:** the input hierarchy's level-1 "temporal resolution" is now keyed by `timedelta` rather than an enum — on the Sandro list — but forced by the 3h/6h requirement and more SAP3-consistent.

*(Code TODO: change `InputRequirement.dynamic` key type to `timedelta`; remove `resolution` from `VariableMetadata`; remove `TemporalResolution` from `common/resolutions.py`; update validators and tests.)*

**Reflected in:** `docs/input_requirement.md`, `docs/model_interface.md`.

## 1.11 Parameter identity: vocabulary, units, aggregation — RESOLVED

**Context:** SAP3 binds parameter name → unit → aggregation in one `ParameterDefinition`. FI had scattered this (free-string names, a closed disconnected `Unit` enum, no aggregation). Closed via three coordinated moves; all three are **sync contracts with SAP3** (keep aligned; update FI lists whenever a variable/unit is added on either side).

**(a) Vocabulary — documented canonical names.** Variable names stay free strings but must match SAP3's canonical set (`discharge`, `water_level`, `water_temperature`, `precipitation`, `temperature`, `relative_humidity`, `wind_speed`, `wind_direction`, `global_radiation`, `reference_et`, `snow_water_equivalent`, `runoff`). SAP3 soft-checks at integration. A documented contract, **not** a hard FI enum (avoids tracking SAP3's evolving set).

**(b) Aggregation — optional per-variable override.** Add optional `aggregation: AggregationMethod` (`SUM`/`MEAN`, mirroring SAP3) to `PastKnownVariable` / `FutureKnownVariable`, used when the declared resolution is coarser than delivered data. Default = per-parameter convention (precip/ref_et = SUM, rest = MEAN); declared only to override. Correctness-critical, hence expressible, but optional. *(Code TODO: add `AggregationMethod` enum + optional field.)*

**(c) Units — first-class on inputs and outputs ("no data without units").**
- Inputs: model **declares the expected `unit`** per input variable (`PastKnownVariable` / `FutureKnownVariable` gain `unit: Unit`); delivered `ModelInputs` series are **tagged with unit**; SAP3 **delivers in the declared unit or rejects loudly at integration** (auto-conversion deferred to a future adapter feature).
- Outputs: unchanged — `TargetSpec` / `VariableMetadata` already declare units.
- **`Unit` enum expansion:** add `PERCENT` (%), `M_PER_S` (m/s), `DEGREE`, `W_PER_M2` (W/m²), `MM_PER_HOUR`. *(Code TODO: expand `common/units.py`; add `unit` field to `input/variable.py`.)*

**Reflected in:** `docs/input_requirement.md`, `docs/model_interface.md`, and code (`common/units.py`, `input/variable.py`).

## 1.10 Station identity & group support — RESOLVED (refined)

**Station key type:** FI station keys are opaque `str` (not typed `StationId` / UUID) — FI stays dependency-free.

**But the string carries meaning and must be stable.** Correcting the initial "echo exactly, never interpret" framing: the model **does** use the station key to look up per-station state in its artifact — *the trained station strings are stored inside the artifact* — so the key is a **meaningful, stable identifier**, not an arbitrary token. Rules:

- The same station string must be used consistently across **train → artifact → predict → output**.
- The model may **read** the key (look it up in its artifact) but must **never alter** it; output is keyed by exactly the strings received.
- The string must be **stable across deployments** (staging → prod, east → west), because artifacts embed it and must be portable. This argues for a **deployment-stable human / network station code**, NOT a per-DB UUID. **Open coordination item:** confirm the exact string the modeller's artifacts store; the SAP3 adapter maps `StationId` (UUID) ↔ that string (via `StationConfig.code` if it is the code).

**Group support from v1:** `ArtifactScope.GROUP` is load-bearing from the start (consistent with 1.6). Multiple input stations may **share one group artifact**; output stays **1:1 station-in / station-out** — every input station gets an output entry. Grouping is about *artifact sharing*, not output cardinality.

**Station-set mismatch (known vs unknown stations):** a GROUP artifact stores its trained member stations. At predict time, **known** stations use the stored per-station state; **unknown** stations (e.g. western gauges under east→west transfer) must be handled by **generalizing from static attributes or raising an explicit error — never silently mis-associating** a prediction with the wrong station / embedding. This is the embedding-key contract (Nepal §8). **Timing flag:** decision 1.6 puts east→west in Nepal v1 and groups ship from the start, so this contract is likely **v1, not Phase 4** — re-evaluate the deferral.

**Reflected in:** `docs/model_interface.md`, `docs/fi-sap3-mapping.md` (§5, §7), `docs/nepal-model-requirements.md` (§8).

## 1.9 Input bundle (`inputs`) typing & v1 delivery scope — RESOLVED

**Decision:**
- Replace `Any` for `inputs` with a **concrete FI-owned input-bundle type** (working name `ModelInputs`), **isomorphic to `InputRequirement`**: addressed by the same `(TemporalResolution → SpatialRepresentation → {past_known | future_known} → product → variable)` keys, leaves being the actual time-series DataFrames, plus `static` and the issue context. It is **station-aware** to match the station-keyed output (decision 1.1) for GROUP models. The SAP3 adapter builds it from SAP3's `StationInputData` / `GroupModelInputs`; FI does **not** import SAP3 types.
- "Parse, don't validate": the bundle the model receives is **valid-by-construction** against its declared `InputRequirement`.

**v1 delivery scope (model developer input):**
- **Temporal resolution:** daily, hourly, or daily + hourly — all delivered in v1.
- **Spatial representation:** POINT (runoff / water level), BASIN_AVERAGE and ELEVATION_BAND (most variables) — delivered in v1. **GRIDDED is declarable-but-not-delivered in v1** (future models); marked loud — SAP3 rejects at integration, never silently delivers wrong data.
- **Product axis:** structure retained, but **v1 delivers a single product per variable.** Multi-product is a future extension (non-breaking — the product dict simply gains keys).
- The un-delivered dimensions (GRIDDED, multi-product) are SAP3's delivery growth backlog.

**`config` (train / predict): OPEN — modeller-owned** (see Q8). Until specified, `config` stays `Any`.

**Reflected in:** `docs/input_requirement.md`, `docs/fi-sap3-mapping.md` (§4), and a future `ModelInputs` type (code).

---

# 2. Open questions for the model developer

A decision-ready list. Each needs the model developer's input before the corresponding spec is frozen.

### Q1 — Station ID typing — ANSWERED

**Answer:** opaque `str` keys (not typed UUIDs), but they **carry meaning and are stable** across train / predict / deployment — the trained station strings are stored inside the artifact and read by the model for per-station lookup. Group artifacts shared across multiple stations are supported **from v1**; output is **1:1 station-in / station-out**; the station-set-mismatch case (unknown stations) is handled by the embedding-key contract (generalize or raise, never silent). **Residual coordination item:** the exact string identity (human code vs UUID-string) must match what the modeller's artifacts store — deployment portability argues for the code. See decision 1.10.

### Q2 — Past-target availability — ANSWERED

**Answer:** target-history is an **optional** declared input — declared under `past_known` only when the model uses it — so both autoregressive and pure-simulation models are supported. The Nepal model **uses past discharge** as input, so it declares discharge under `past_known` in addition to declaring it as a target (decision 1.2).

### Q3 — Quantile minimum — ANSWERED

**Answer:** FI structural floors are **≥ 3 quantiles** and **≥ 8 trajectories** (deployment-independent hard validators); no use case below those. Nepal emits quantiles with the count configurable at training. SAP3's operational floors (≥7 quantiles w/ tails, ≥20 members) stay deployment-side and are checked at integration. Deterministic-only output is allowed but non-operational without supplied uncertainty. See decision 1.5.

### Q4 — State reconstruction — ANSWERED

**Answer (model developer):** the current model is **pure ML** — it reconstructs its internal state from the lookback window each cycle and requires **no warm-up period and no persisted state**. Warm-up state is required for conceptual / distributed models and may be required for hybrid models, but none are in scope for v1. This confirms decision 1.3: state-free is correct for v0, with the reserved `StatefulModel` extension covering future conceptual / hybrid models.

### Q5 — `VariableMetadata` fields — ANSWERED

- **(a) Drop `name`.** Redundant with the `ModelOutput.variables[station][variable]` key; two sources of truth that can disagree is forbidden by the type ethos. Field removed. *(Code TODO: remove `name` from `VariableMetadata`; update tests.)*
- **(b) Keep `forecast_horizon`, add a per-issue-block cross-validator.** Kept because the adapter reads it directly (`ForecastEnsemble.forecast_horizon_steps`). Validator: for `predict`, `forecast_horizon == row count`; for batch `hindcast`, `forecast_horizon == rows per issue_datetime` (one block per issue time, decision 1.8). *(Code TODO: add validator.)*
- **(c) `offset` semantics confirmed:** number of steps (each `timedelta` long) between the **last observation and the first forecast step**. `offset = 1` ⇒ first forecast valid time is `last_obs + 1·timedelta` (usual next-step case); `offset = 2` ⇒ a one-step gap. Model and adapter both assume this convention.

**Reflected in:** `docs/model_interface.md`.

### Q6 — Per-row `issue_datetime` column

The adapter maps `ModelOutput.issue_datetime` → `ForecastEnsemble.issued_at` and renames the per-row datetime column → `valid_time`. The question is whether to **keep the per-row `issue_datetime` column requirement** — with a cross-validator that it matches the top-level `issue_datetime` for forecasts — or **relax it**. Frame this as a validator question, not a removal: the column is not "dropped", it is renamed and re-used.

**Now scoped by decision 1.8:** a plain `ForecastModel` (`predict`) always emits a constant per-row `issue_datetime` equal to the top-level one — so for the required surface this *can* carry a strict cross-validator. The varying-per-row case exists **only** on the optional `BatchHindcastModel` path, where the validator must instead check that the per-row `issue_datetime` matches the batch's declared `issue_datetimes`. So the answer likely differs by protocol: strict equality for `predict`, set-membership for batch `hindcast`.

### Q8 — `config` contents (train / predict) — OPEN (modeller-owned)

What does the model need in `config` at `train` and `predict` time, beyond `inputs` and the injected `rng`? Candidates: training hyperparameters, target quantile levels / trajectory count, forecast horizon, validation split, early-stopping criteria, seeds beyond `rng`. This is **modeller-owned** and must be specified before `config: Any` can be typed (decision 1.9).

### Q7 — SnowMapper lead times — ANSWERED (with caveat)

**Answer:** SnowMapper **SWE** and **RoF** are available at **BASIN_AVERAGE or ELEVATION_BAND** (the same spatial options as weather forcing — this **broadens** decision 1.6's "ELEVATION_BAND only"). They are derived from ECMWF forecasts, so assume the **same lead times and resolutions as the ECMWF forecast (future-known) and ERA5-Land (past / reanalysis)**.

**Caveat — SnowMapper lag:** because the SnowMapper model runs *after* ECMWF, its outputs may **lag** the ECMWF forecasts — the SnowMapper future-known series can be shorter or offset relative to the driving ECMWF series for the same issue time. See Q9.

**Reflected in:** `docs/input_requirement.md`, decision 1.6.

### Q9 — Per-product availability lag — OPEN

Products derived downstream (e.g. SnowMapper SWE / RoF, which run *after* their driving ECMWF forecast) may become available **later** than their nominal forcing — their future-known series lags the issue time. `InputRequirement`'s variable properties (`lookback`, `future_steps`, `max_nan`, `ensemble_mode`) have **no explicit lag / offset** field. Decide whether to **(a)** add a per-variable `availability_lag` (in steps), or **(b)** absorb it via `max_nan` / a shorter `future_steps`. Needs modeller + data-availability input.
