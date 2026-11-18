# Open Design Questions

This file tracks design decisions for the ForecastInterface (FI) — the model-author-facing contract — and the questions still owed to the model developer.

## Context

ForecastInterface (FI) is the contract model authors implement. SAPPHIRE Flow (SAP3) consumes FI models through a thin, planned-but-not-yet-built `ForecastInterfaceAdapter`. Governance (SAP3 doc 014, "ForecastInterface Adapter Design") sets the ownership boundaries:

- **FI OUTPUT types are authoritative** — SAP3 adapts to them.
- **FI INPUT types are co-designed** via a SAP3 → FI PR.
- **FI's INTERFACE / protocol is FI-owned**, with SAP3 wrapping thin.

These decisions are reflected in `docs/model_interface.md` and `docs/input_requirement.md`. This file does not duplicate their content. The FI ↔ SAP3 adapter mapping lives with the adapter in SAPPHIRE_flow.

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

**Reflected in:** `docs/model_interface.md`.

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

- **FI structural floors (hard validators):** QuantileData **≥ 3** levels (centre + two tails); TrajectoryData **≥ 8** samples. *(Implemented.)*
- **SAP3 operational floors (deployment config, SAP3-side):** `min_operational_quantile_levels` ≥ 7 with tail coverage (a level ≤0.05 and a level ≥0.95); `min_operational_ensemble_size` ≥ 20 members. Kept out of FI because they are deployment-specific.
- **Deterministic-only is allowed, not forbidden.** A deterministic model may be strong; FI accepts deterministic output as structurally valid. But SAP3 has **no deterministic channel**, so deterministic-only is **non-operational** until the model supplies forecast uncertainty (quantiles/trajectories it emits, or a downstream uncertainty wrapper).
- **No silent non-operational output.** The model declares its representation(s) and emitted count; SAP3 checks them against its deployment floor at **integration/registration time** and rejects incompatibles loudly. Net: *valid FI + declared counts ≥ deployment floor ⟹ operational.*

**Authority-rule refinement (from Q1):** the Q1 principle — "FI must not express a model SAP3 can't operate" — is refined to: FI **may** express not-yet-operational models (e.g. deterministic-only), provided the non-operational state is **never silent** — it is declared, caught loudly at the SAP3 boundary, and has a documented path to operational.

**Model developer input (Nepal):** the model emits **quantiles** (count configurable at training); **trajectories** typically ~50 (deployment-specific, may be fewer).

**Reflected in:** `docs/model_interface.md`.

## 1.6 Nepal v1 deployment specifics — RESOLVED (model developer)

**Decisions provided by the model developer:**

- **First artifact scope: the eastern regional group ships first.** The first production artifact is therefore **GROUP-scoped** (`ArtifactScope.GROUP`). This makes the station-keyed output of decision 1.1 and the GROUP adapter path **load-bearing from day one**, not a later concern.
- **SnowMapper forcing starts with SWE and ROF** (snow water equivalent and runoff), declared as dynamic forcing at **`BASIN_AVERAGE` or `ELEVATION_BAND`** (see decision 1.4; Q7 broadened this from ELEVATION_BAND-only). Lead times / resolutions follow the ECMWF forecast and ERA5-Land (Q7), with a possible SnowMapper availability lag (Q9).
- **Artifact transfer direction is east → west** (an eastern group artifact applied to western gauges). This makes the embedding-key / station-set-mismatch contract (Nepal §8) concrete: the eastern GROUP artifact **must define its behaviour when applied to the western station set** — handle gracefully or raise an explicit error, never silently associate a station with the wrong embedding.

**Reflected in:** `docs/model_interface.md` (artifact portability).

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

## 1.18 Training time grid declaration — RESOLVED (pending review)

**Decision:** FI declares and checks the time grid of a trained artifact and of its inputs and outputs, additively and without any calendar framework.

- **Types.** `TimeGrid(step, origin, label)` with `origin` an offset from UTC midnight in whole minutes, `0 <= origin < step`, a step that divides 24 h exactly, and `label: PeriodLabel` (`START` = stamp `t` names `[t, t+step)`, `END` = `(t-step, t]`, `UNKNOWN`). `Unknown.UNKNOWN` is the explicit "not declared" sentinel.
- **Declaration points.** `TimeAnchor` on the per-step input branch, with a per-variable `label` override that inherits the branch label; `TargetSpec.aggregation` / `label`; `ModelInputs.grid` (on-grid check on the matching branch); `VariableMetadata.origin` / `label` (output phase check); `GridDeclaringArtifact` + `TrainingGridDeclaration` for the artifact.
- **Comparison.** `compatibility()` / `require_compatible()` / `GridMismatchError`: exact equality on step, origin and label; `UNKNOWN` is returned, never inferred; FI never shifts. `FailureCause.GRID_MISMATCH` reports a refusal. Whether `UNKNOWN` is accepted is an operator decision.
- **Aggregation.** `AggregationMethod` gains `MIN` and `POINT` (a sampled value, label meaningless). Targets reject `SUM` with a rate unit; `MEAN` with `mm` / `m` stays legal (SWE, water level).

**Rationale:** raised as FI issue #12 (https://github.com/hydrosolutions/ForecastInterface/issues/12). A model trained on daily means stamped at one phase silently degrades when fed the same step at another. Origin alone is not enough: the same physical day is stamped 18:00Z on its start or on its end, both 18:00 mod 24h, so a label is required to tell `START` from `END`.

**Limitations.**

- `ModelInputs.grid` checks only the branch keyed by `grid.step`; branches with other steps are not checked, and an unknown grid is not checked. A `TimeGrid` that matches no station's branch at all now raises (a wiring error); stations that individually lack the branch are skipped while at least one has it.
- A `POINT` variable ignores the inherited branch label (the branch label applies to its windowed variables).
- A step that does not divide 24 h is accepted while the origin is `Unknown`, but rejected once an origin is declared, so declaring a grid later can fail on such a step; otherwise the change is additive.

**Bounded, deliberate difference.** Civil midnight in a UTC+5:45 zone is 18:15Z the previous day, but deployments declare 18:00Z. That 15-minute approximation is accepted as a deliberate, bounded difference, and exact equality refuses it: data imported on 18:15Z is a `MISMATCH` against an 18:00Z declaration, and an orchestrator must resolve it explicitly (re-stamp or retrain). FI does not tolerate or shift.

**Scope limits.**

- FI declares only **finished products**. Deaccumulation (ICON, ERA5-Land) and forecast-cycle handling belong to the orchestrator.
- **First / last partial periods and lead-time 0.** A daily model issued mid-period gets a partial first period live but a full one in hindcast. The declaration does not capture this and FI does not check it.
- **No calendar / DST framework.** A DST deployment picks a fixed-offset UTC boundary and uses its zone for display only.
- Issue time is not part of the declaration.

**Relation to other items:** completes the aggregation part of #7 (`POINT`, `MIN`, `TargetSpec.aggregation`) and builds on the temporal enforcement of #9 / decision 1.17.

**Adoption:** lockstep with SAP3 and aquacast, which pin FI by exact tag. There is no release until that is coordinated.

**Open (awaiting Sandro):** the aquacast-side checklist (grid and label of trained artifacts, instantaneous or mixed-label inputs, non-daily steps, whether artifacts can embed the declaration, label granularity) lives in the issue #12 thread, which is the single source for these questions.

**Reflected in:** `docs/input_requirement.md`, `docs/model_interface.md`, and code.

## 1.17 Temporal contract enforcement: declared cadence & tz-aware datetimes — RESOLVED

**Decision:** FI validates the temporal contract it already declares, in three parts.

1. **Cadence is enforced.** Within each `issue_datetime` group, consecutive `datetime` values must be
   spaced by exactly the declared `VariableMetadata.timedelta`. Non-uniform spacing is rejected —
   `forecast_horizon` and `offset` are counts of uniform steps and have no meaning otherwise. A
   **single-row group passes vacuously**: it has no measurable spacing, `forecast_horizon = 1` is
   valid, and FI must not fabricate a cadence for it. Strictly-increasing order comes free with the
   check, since the required diff is positive.
2. **Datetimes must be timezone-aware UTC** — both temporal columns, the
   `ModelOutput.issue_datetime` scalar, which today has no validator at all, and the `datetime`
   column of `InputSeries`.
3. **Null temporal values are rejected.** Neither `issue_datetime` nor `datetime` may carry a null,
   in any of the four data containers. This aligns the output side with the rule the input side has
   always enforced (`'datetime' values must not be null`), and closes a hole the cadence check alone
   could not: `.diff().over(...)` emits a null gap for a null timestamp, which `.drop_nulls()` then
   swallows, so a null `datetime` slipped past an otherwise strict cadence validator.

**Not taken: Q6 cross-validator.** A strict per-row check — every row's `issue_datetime` equals
`ModelOutput.issue_datetime` — was implemented alongside the above and then **pulled**, because it
makes `BatchHindcastModel` unimplementable. `hindcast` takes a `Sequence[datetime]` of issue times
and returns a *single* `ModelResult`; `ModelSuccess` holds exactly one `ModelOutput`, which holds one
scalar `issue_datetime`. Decision 1.8's knock-on requires precisely the opposite of strict equality
on that path: the per-row column **varies** across the batch. Q6's set-membership half is no escape —
it needs a declared list of issue times on `ModelOutput`, and no such field exists. Q6 was answered
against a shape that was never built.

**Q6 is therefore ANSWERED IN PRINCIPLE BUT NOT IMPLEMENTABLE** against the current `ModelOutput`
shape, and the shape needs its own decision before any validator lands. Candidate
directions, neither chosen here: `ModelOutput` gains an `issue_datetimes` declaration the validator
can check membership against, or `hindcast` returns a *sequence* of results so each output keeps a
single issue time. Do not re-attempt the unconditional validator without settling that shape first.

**Rationale:** raised by SAPPHIRE Flow as FI issue #9. `_validate_forecast_horizon`
(`variable_output.py:145`; `:132` at the revision the issue was filed against) already cross-checks
the frame against the metadata — the row count per issue group — but never the spacing, so a model
may declare `1 day`, emit three rows one hour apart, and FI accepts it: three rows is what a horizon
of three asks for. There is no principled line on which the count is FI's job and the spacing is
each consumer's. This is the same shape as 1.16
(fi-issues/002): a declaration with two readings in the wild, settled in the type rather than in each
consumer's adapter. SAP3 *could* compare metadata and frame in its own adapter — it holds both at one
point — but then only the consumer that wrote the guard is protected.

For the timezone half, the contract **already states UTC** (`docs/model_interface.md:112,130-131`),
so this enforces an existing statement rather than adding a requirement — and the shipped README
example contradicted it by constructing naive datetimes. The exposure is concrete: SAPPHIRE is
extending to Nepal at **UTC+05:45**, where a naive timestamp read as UTC is off by 345 minutes and
can land in the wrong day. Note precisely where the hazard sits: **tz-naive is the whole hazard**,
because it fabricates an instant. The *display* zone does not affect spacing — polars stores
instants, and a Zurich-local daily series and its UTC conversion both diff to `[1 day, 23:00:00]`
across a DST transition (verified). UTC specifically is therefore required for **contract clarity,
not correctness**, and the producer's escape is a one-line `.dt.convert_time_zone("UTC")`.
The `Etc/UTC` alias is rejected too, intentionally: the check is the literal string `"UTC"`, keeping one canonical spelling for the contract.

**Reject, not deprecate:** the consumer set is closed and known — aquacast and SAPPHIRE Flow, both
pinning FI by exact tag, SAP3 additionally enforcing `SUPPORTED_FI_VERSION` at run time — so a
stricter validator lands only when each side chooses to bump, exactly the adoption model 1.16 relies
on. SAP3 measured all five models on staging on 2026-09-08: cadence is exactly `1 day` for every one,
matching aquacast's declaration, so there is **no known violator** to deprecate for. FI also has no
warning infrastructure — every validator raises — and building `warnings` plumbing into a contract
package for a violator set of zero is not worth it.

**Placement:** `validate_temporal_columns` keeps its signature. It is called from all four data
containers (`DeterministicData`, `QuantileData`, `TrajectoryData`, `EpistemicUncertaintyData`), none
of which holds the metadata, so threading metadata through them would break standalone construction
for no gain. `VariableOutput` is the only place where metadata and frames coexist, so
`validate_cadence(df, timedelta)` is called from there. The cadence check covers
`epistemic_uncertainty`; **open sub-point:** `_validate_forecast_horizon` skips
`epistemic_uncertainty`, and it is not clear from the record whether that omission is deliberate.
**Half closed:** the *emptiness* consequence of that skip is fixed — a present
`epistemic_uncertainty` frame with zero rows used to be accepted, and non-emptiness now lives in its
own `VariableOutput` validator that walks all four frames, so it no longer rides on the horizon
check. The *row-count* half remains open: `epistemic_uncertainty` is still not checked for
`forecast_horizon` rows per `issue_datetime`, deliberately left as-is pending that decision.

**Relation to 1.12:** a strict uniform-spacing check hard-codes 1.12's fixed-duration assumption. It
is correct for every step v1 admits, and it becomes the natural extension point when 1.12's deferred
`TimeStep = timedelta | CalendarResolution` lands — a decadal series legitimately shows 8–11 day
gaps.

**Adoption (cross-repo):** SAPPHIRE Flow consumes aquacast and both are installed in the same
environment with exact pins, so the two must move in lockstep and neither can adopt ahead of the
other. Shipped as a **single minor release (v0.2.0)** rather than split, because a split buys nothing
on the timeline and costs a second coordinated migration. aquacast adoption is expected **October
2026**; cutting the tag ahead of that gives aquacast a fixed target to develop against. The cadence
half is measured safe; the timezone half is expected to require an aquacast change, since SAP3's
adapter carries the comment `# FI datetimes are UTC by contract; tz-naive values are localized, not
shifted.` — a code path that exists only because naive values arrive today.

**Reflected in:** `docs/model_interface.md`, `docs/input_requirement.md`, `README.md`, and code.

## 1.16 `future_steps` semantics: floor vs. ceiling — RESOLVED

**Decision:** the requirement states its own semantics. `FutureKnownVariable` gains a
`horizon_semantics: HorizonSemantics` field (`EXACT` | `AT_MOST`, **default `EXACT`**) and a
`min_future_steps: int | None`, **required when — and only when — `AT_MOST`**.

- **`EXACT`** (default) — `future_steps` is a floor: fewer delivered steps is an error, and the
  provider must not call the model. Identical to today's behaviour, so no existing declaration
  changes meaning and no provider starts truncating silently after an upgrade.
- **`AT_MOST`** — `future_steps` is a ceiling: any count in `[min_future_steps, future_steps]` is
  acceptable and yields a correspondingly shorter forecast. Below the floor, the provider must
  refuse as under `EXACT`.
- **A short delivery is a genuinely shorter series, not a full-length one padded with NaN.** The
  undelivered steps are *not* counted against `max_nan` — `max_nan` (decision 1.13) continues to
  gate only NaNs *within* the delivered extent. Padding a fixed-length frame with a trailing NaN
  block is a contract violation, not an `AT_MOST` delivery.
- The delivered steps are the **contiguous prefix** starting at the first future step; `AT_MOST`
  licenses a short tail, never an interior or leading gap.
- The floor is **mandatory** under `AT_MOST` because "fewer is fine" is rarely unbounded — a 15-day
  model may be useless at 1 day. Optional would put that judgement back with each provider, which is
  the coordination failure this change exists to remove.

**Rationale:** raised by SAP3 as FI issue 002. `future_steps` had two incompatible readings in the
wild with no way to tell them apart: aquacast declares its **trained maximum** and degrades
gracefully below it (`_relax_horizon`), while SAP3 reads the same field as a **hard requirement** and
refuses to invoke a model whose future forcing is short. Both are correct against the contract as
written; the contract was the problem. Concretely it blocked Swiss stations, where ICON-CH2-EPS
publishes 120 h against a 15-day declared horizon, so a model that would happily produce a 5-day
forecast was never called.

**Why variable-level, not model-level:** a model may need one forcing in full while tolerating
truncation in another, and the same model tolerates truncation only for some configurations —
aquacast's `_relax_horizon` refuses to shrink a multi-resolution window unless
`forecast_hours == forecast_days * 24`. Semantics therefore belong where `future_steps` already
lives.

**Relation to 1.15:** this does **not** move horizon ownership. The model still owns the horizon and
declares the *actual* one in `metadata.forecast_horizon`; `future_steps` stays forcing extent. What
is added is only whether that extent is a floor or a ceiling — the narrowest form of the
horizon-*capability* field 1.15 deferred as YAGNI, now driven by a concrete blocking case.

**Relation to Q9 (availability lag):** unchanged. A *systematically* shorter product still declares
a smaller `future_steps` (e.g. SnowMapper SWE 13 vs ECMWF precip 15). `AT_MOST` covers the different
case where the delivered extent varies per run with the upstream feed.

**Alternatives rejected:** a separate `max_future_steps` alongside `future_steps` (equal expressive
power, but invites inconsistent pairs and leaves `future_steps` itself ambiguous); a model-level flag
(too coarse, see above); documentation only (the status quo, which produced two correct
implementations that cannot interoperate).

**Adoption (cross-repo, not carried by this change):** the FI type is implemented; the behaviour it
licenses is not yet live on either side. aquacast must declare `AT_MOST` plus a floor where
`_relax_horizon` actually applies (it refuses to shrink some window geometries, so some
configurations stay `EXACT`). SAP3 must read both fields — today its adapter collapses the
requirement to `max(future_steps)` across variables and gates every future feature on that single
maximum, so an `AT_MOST` declaration changes nothing until that path becomes per-variable. Both pin
FI exactly (SAP3 additionally enforces `SUPPORTED_FI_VERSION` at run time), so each side adopts on
its own schedule and a stale consumer keeps today's strict behaviour rather than misreading the new
one.

**Reflected in:** `docs/input_requirement.md`. *(Implemented in FI; downstream adoption pending.)*

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

*(Implemented.)*

**Reflected in:** `docs/input_requirement.md`, `docs/model_interface.md`.

## 1.11 Parameter identity: vocabulary, units, aggregation — RESOLVED

**Context:** SAP3 binds parameter name → unit → aggregation in one `ParameterDefinition`. FI had scattered this (free-string names, a closed disconnected `Unit` enum, no aggregation). Closed via three coordinated moves; all three are **sync contracts with SAP3** (keep aligned; update FI lists whenever a variable/unit is added on either side).

**(a) Vocabulary — documented canonical names.** Variable names stay free strings but must match SAP3's canonical set (`discharge`, `water_level`, `water_temperature`, `precipitation`, `temperature`, `relative_humidity`, `wind_speed`, `wind_direction`, `global_radiation`, `reference_et`, `snow_water_equivalent`, `runoff`). SAP3 soft-checks at integration. A documented contract, **not** a hard FI enum (avoids tracking SAP3's evolving set).

**(b) Aggregation — optional per-variable override.** Add optional `aggregation: AggregationMethod` (`SUM`/`MEAN`, mirroring SAP3) to `PastKnownVariable` / `FutureKnownVariable`, used when the declared resolution is coarser than delivered data. Default = per-parameter convention (precip/ref_et = SUM, rest = MEAN); declared only to override. Correctness-critical, hence expressible, but optional. *(Implemented.)*

**(c) Units — first-class on inputs and outputs ("no data without units").**
- Inputs: model **declares the expected `unit`** per input variable (`PastKnownVariable` / `FutureKnownVariable` gain `unit: Unit`); delivered `ModelInputs` series are **tagged with unit**; SAP3 **delivers in the declared unit or rejects loudly at integration** (auto-conversion deferred to a future adapter feature).
- Outputs: unchanged — `TargetSpec` / `VariableMetadata` already declare units.
- **`Unit` enum expansion:** add `PERCENT` (%), `M_PER_S` (m/s), `DEGREE`, `W_PER_M2` (W/m²), `MM_PER_HOUR`. *(Implemented.)*

**Reflected in:** `docs/input_requirement.md`, `docs/model_interface.md`, and code (`common/units.py`, `input/variable.py`).

## 1.10 Station identity & group support — RESOLVED (refined)

**Station key type:** FI station keys are opaque `str` (not typed `StationId` / UUID) — FI stays dependency-free.

**But the string carries meaning and must be stable.** Correcting the initial "echo exactly, never interpret" framing: the model **does** use the station key to look up per-station state in its artifact — *the trained station strings are stored inside the artifact* — so the key is a **meaningful, stable identifier**, not an arbitrary token. Rules:

- The same station string must be used consistently across **train → artifact → predict → output**.
- The model may **read** the key (look it up in its artifact) but must **never alter** it; output is keyed by exactly the strings received.
- The string must be **stable across deployments** (staging → prod, east → west), because artifacts embed it and must be portable. **Resolved (Q10):** the key is the **station / gauge code**, not a per-DB UUID; the SAP3 adapter maps `StationId` (UUID) ↔ code (via `StationConfig.code`). Residual: Sandro confirms his trained artifacts key on the code.

**Group support from v1:** `ArtifactScope.GROUP` is load-bearing from the start (consistent with 1.6). Multiple input stations may **share one group artifact**; output stays **1:1 station-in / station-out** — every input station gets an output entry. Grouping is about *artifact sharing*, not output cardinality.

**Station-set mismatch (known vs unknown stations):** a GROUP artifact stores its trained member stations. At predict time, **known** stations use the stored per-station state; **unknown** stations (e.g. western gauges under east→west transfer) must be handled by **generalizing from static attributes or raising an explicit error — never silently mis-associating** a prediction with the wrong station / embedding. This is the embedding-key contract (Nepal §8). **Timing flag:** decision 1.6 puts east→west in Nepal v1 and groups ship from the start, so this contract is likely **v1, not Phase 4** — re-evaluate the deferral.

**Reflected in:** `docs/model_interface.md`.

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

**Reflected in:** `docs/input_requirement.md`, and the `ModelInputs` type (code).

---

# 2. For the model developer

This section is the single place for what we need from / owe to the model developer: **open questions** still awaiting input, and **deviations** from the original proposal we'd like confirmed. The full Q&A record (answered + open) follows.

## Still open — needs your input

- **`config` contents (Q8)** — Sandro must enumerate the train-time config before we partition ownership and type it. *(The main open item.)*
- **Availability-lag values (Q9)** — mechanism settled (reduced per-variable `future_steps`); the concrete SnowMapper step-counts are owed by Sandro / data availability.
- **Training time grid (decision 1.18, issue #12)** — Sandro answers the checklist in the issue #12 thread.
- **Station-code confirmation (Q10)** — key decided (station code); Sandro confirms his artifacts key on it (re-key if not).

## Deviations from the original proposal — please confirm

The interface diverged from the original `init` proposal in these ways. Each is justified (see the linked decision / spec), but they change the original design, so we'd like your sign-off:

- **Lifecycle ownership** — artifacts are **framework-owned** (`train` → `serialize_artifact` → SAP3 stores → `deserialize_artifact`) rather than loaded inside `__init__`; the model is artifact-stateless (see `docs/model_interface.md`, *Training & Lifecycle Protocol*).
- **`forecast()` → `predict()`** — renamed to match SAP3.
- **Output keying** — `dict[variable]` → **station-keyed** `dict[station][variable]` (decision 1.1).
- **Spatial vocabulary** — `distributed` / `lumped` → `POINT` / `BASIN_AVERAGE` / `ELEVATION_BAND` / `GRIDDED` (decision 1.4).
- **Ensemble flag** — `ensemble: bool` → `EnsembleMode` enum.
- **Failure channel** — `forecast() → ModelOutput` → `predict() → ModelResult` (`Success | Failure`) (decision 1.7).
- **Hindcast** — demoted from a core method to the optional `BatchHindcastModel` (decision 1.8).
- **Time step** — `TemporalResolution` enum → `timedelta` keys (decision 1.12).

## Question record

A decision-ready list. Each needs the model developer's input before the corresponding spec is frozen.

### Q1 — Station ID typing — ANSWERED

**Answer:** opaque `str` keys (not typed UUIDs), but they **carry meaning and are stable** across train / predict / deployment — the trained station strings are stored inside the artifact and read by the model for per-station lookup. Group artifacts shared across multiple stations are supported **from v1**; output is **1:1 station-in / station-out**; the station-set-mismatch case (unknown stations) is handled by the embedding-key contract (generalize or raise, never silent). **Residual:** resolved to the **station code** (Q10 / decision 1.10); Sandro confirms his artifacts key on it.

### Q2 — Past-target availability — ANSWERED

**Answer:** target-history is an **optional** declared input — declared under `past_known` only when the model uses it — so both autoregressive and pure-simulation models are supported. The Nepal model **uses past discharge** as input, so it declares discharge under `past_known` in addition to declaring it as a target (decision 1.2).

### Q3 — Quantile minimum — ANSWERED

**Answer:** FI structural floors are **≥ 3 quantiles** and **≥ 8 trajectories** (deployment-independent hard validators); no use case below those. Nepal emits quantiles with the count configurable at training. SAP3's operational floors (≥7 quantiles w/ tails, ≥20 members) stay deployment-side and are checked at integration. Deterministic-only output is allowed but non-operational without supplied uncertainty. See decision 1.5.

### Q4 — State reconstruction — ANSWERED

**Answer (model developer):** the current model is **pure ML** — it reconstructs its internal state from the lookback window each cycle and requires **no warm-up period and no persisted state**. Warm-up state is required for conceptual / distributed models and may be required for hybrid models, but none are in scope for v1. This confirms decision 1.3: state-free is correct for v0, with the reserved `StatefulModel` extension covering future conceptual / hybrid models.

### Q5 — `VariableMetadata` fields — ANSWERED

- **(a) Drop `name`.** Redundant with the `ModelOutput.variables[station][variable]` key; two sources of truth that can disagree is forbidden by the type ethos. Field removed. *(Implemented.)*
- **(b) Keep `forecast_horizon`, add a per-issue-block cross-validator.** Kept because the adapter reads it directly (`ForecastEnsemble.forecast_horizon_steps`). Validator: for `predict`, `forecast_horizon == row count`; for batch `hindcast`, `forecast_horizon == rows per issue_datetime` (one block per issue time, decision 1.8). *(Implemented.)*
- **(c) `offset` semantics confirmed:** number of steps (each `timedelta` long) between the **last observation and the first forecast step**. `offset = 1` ⇒ first forecast valid time is `last_obs + 1·timedelta` (usual next-step case); `offset = 2` ⇒ a one-step gap. Model and adapter both assume this convention.

**Reflected in:** `docs/model_interface.md`.

### Q6 — Per-row `issue_datetime` column — ANSWERED IN PRINCIPLE, NOT IMPLEMENTABLE (scoped by decision 1.8)

The adapter maps `ModelOutput.issue_datetime` → `ForecastEnsemble.issued_at` and renames the per-row datetime column → `valid_time`. The question is whether to **keep the per-row `issue_datetime` column requirement** — with a cross-validator that it matches the top-level `issue_datetime` for forecasts — or **relax it**. Frame this as a validator question, not a removal: the column is not "dropped", it is renamed and re-used.

**Now scoped by decision 1.8:** a plain `ForecastModel` (`predict`) always emits a constant per-row `issue_datetime` equal to the top-level one — so for the required surface this *can* carry a strict cross-validator. The varying-per-row case exists **only** on the optional `BatchHindcastModel` path, where the validator must instead check that the per-row `issue_datetime` matches the batch's declared `issue_datetimes`. So the answer likely differs by protocol: strict equality for `predict`, set-membership for batch `hindcast`.

**Implementation attempted and pulled (decision 1.17).** The strict-equality half was written as an unconditional `ModelOutput` validator and removed again: it makes `BatchHindcastModel` unimplementable. `hindcast` takes a `Sequence[datetime]` and returns one `ModelResult`, whose `ModelSuccess` holds one `ModelOutput` with one scalar `issue_datetime` — so a batch over N issue times *must* emit one output whose rows carry N distinct per-row values, exactly what strict equality forbids. The set-membership half cannot stand in: it needs a declared list of issue times on `ModelOutput`, and there is no such field. **Do not retry the validator as-is.** The answer above stands in principle; it is simply not implementable against the current `ModelOutput` shape, so the *shape* question is what remains open (see decision 1.17). Settle the shape first — either `ModelOutput` gains an `issue_datetimes` declaration, or `hindcast` returns a sequence of results — then decide.

### Q8 — `config` contents — OPEN (awaiting Sandro, then partition)

`config` is passed to **`train` / `retrain` only** — `predict` / `hindcast` take no `config`.

**Resolution process (two steps):**
1. **Sandro enumerates** what the model puts in `config` at train time — hyperparameters, the **quantile levels** it emits, trajectory/sample count, validation-split date, early-stopping criteria, etc. (Not forecast horizon — the model owns that, decision 1.15. Not seeds — `rng` is injected.)
2. **We partition** each field into **model-private** (opaque to FI/SAP3) vs **operationally-shared** (FI/SAP3 needs to read or set it). The likely shared candidate is the **quantile levels** (SAP3 may need specific quantiles for danger thresholds).

**Interim typing:** `config` stays `Any` until the partition is known; the expected end state is an opaque `dict[str, Any]` for model-private params (mirroring SAP3's `ModelParams`), with any operationally-shared fields lifted into a typed slot. (decision 1.9)

### Q7 — SnowMapper lead times — ANSWERED (with caveat)

**Answer:** SnowMapper **SWE** and **RoF** are available at **BASIN_AVERAGE or ELEVATION_BAND** (the same spatial options as weather forcing — this **broadens** decision 1.6's "ELEVATION_BAND only"). They are derived from ECMWF forecasts, so assume the **same lead times and resolutions as the ECMWF forecast (future-known) and ERA5-Land (past / reanalysis)**.

**Caveat — SnowMapper lag:** because the SnowMapper model runs *after* ECMWF, its outputs may **lag** the ECMWF forecasts — the SnowMapper future-known series can be shorter or offset relative to the driving ECMWF series for the same issue time. See Q9.

**Reflected in:** `docs/input_requirement.md`, decision 1.6.

### Q9 — Per-product availability lag — RESOLVED (mechanism); values owed

Products derived downstream (e.g. SnowMapper SWE / RoF, which run *after* their driving ECMWF forecast) become available **later** than their nominal forcing — at issue time T their future-known series reaches fewer steps ahead than the ECMWF series driving them.

**Mechanism — option (b):** represent the lag as **reduced per-variable `future_steps`** (the lagging product simply declares fewer future steps than its driving forcing, e.g. ECMWF precip `future_steps=15` vs SnowMapper SWE `future_steps=13`), with `max_nan` absorbing any residual ragged tail. **No dedicated `availability_lag` field** — it would be speculative complexity; the existing per-variable knobs already express the shorter-future-coverage case. If a genuine *leading-gap / offset* case ever appears that `future_steps` can't express, add the field then (additive, non-breaking).

**Still owed (Sandro / data availability):** the concrete step counts — how many fewer future steps SnowMapper SWE / ROF actually cover vs. the ECMWF horizon.

### Q10 — Station-string identity — RESOLVED (station code)

**Decision:** the station key is the **station / gauge code** (the deployment-stable human / network identifier), **not** a per-DB UUID. The UUID stays internal to SAP3; its adapter maps `StationId` (UUID) ↔ code (via `StationConfig.code`) at the boundary. Chosen for portability — the artifact embeds these strings, and they must survive staging → prod and east → west transfer, where UUIDs are not stable across databases but codes are.

**Residual (Sandro):** confirm his already-trained artifacts key on the station code (and re-key if they currently use a UUID / internal id).
