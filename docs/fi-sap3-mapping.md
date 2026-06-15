# ForecastInterface ↔ SAPPHIRE Flow (SAP3) Adapter-Boundary Mapping

> **Status:** Forward contract (Phase 0, docs-only). No adapter exists in SAP3 yet.
> **FI side:** authoritative for output types; co-designs input types; owns the model protocol.
> **Companion document:** SAP3 `docs/plans/archive/014-forecast-interface-adapter-design.md`
> (referred to below as **doc 014**). This document is the **FI-side** formalization of doc 014.

This is the single authoritative place that says, type by type, how a ForecastInterface
(FI) model maps onto SAP3's `StationForecastModel` / `GroupForecastModel` contract across
the planned `ForecastInterfaceAdapter` boundary.

File references use `path:line`. FI paths are relative to this repo
(`/Users/bea/Documents/GitHub/ForecastInterface`); SAP3 paths are relative to the sibling
repo (`/Users/bea/Documents/GitHub/SAPPHIRE_flow`).

---

## 1. Purpose & governance

FI is the **model-author-facing contract**: a model developer implements `ForecastModel`
(`forecast_interface/interface/protocol.py:10`), declares its `InputRequirement`
(`forecast_interface/input/requirement.py:35`), and returns a `ModelResult`
(`forecast_interface/interface/result.py:40`) wrapping a `ModelOutput`
(`forecast_interface/output/model_output.py:9`). FI knows nothing about stations, groups,
batching, stacking, QC, alerts, or artifact storage.

SAP3 is the **operational system**. It plans to wrap FI models behind a thin
`ForecastInterfaceAdapter` (doc 014 §A Task 1, lines 157–240; naming per doc 014 line 343)
that translates between FI's contract and SAP3's `StationForecastModel` /
`GroupForecastModel` protocols (`src/sapphire_flow/protocols/forecast_model.py:23,49`).

### Governance split (doc 014 lines 300–305)

| Concern | Authority | Mechanism |
|---|---|---|
| FI **output** types (`ModelOutput`, `VariableOutput`, data containers, enums) | **FI** | Stable & test-locked; SAP3 adapts to them. |
| FI **input** types (`InputRequirement` & friends) | **Co-designed** | SAP3 contributes via a SAP3→FI PR (doc 014 Task 3, lines 257–283). |
| FI **interface / model Protocol** (`ForecastModel`) | **FI** | FI-owned; SAP3 wraps thin (doc 014 Task 4–5, lines 287–305). |

### Current state of the adapter (verified)

As of this writing there is **no adapter implemented in SAP3**:

- No import of the FI package anywhere in `SAPPHIRE_flow/src/`.
- No `ForecastInterfaceAdapter` class.
- No use of FI's `ModelOutput`. The only `ModelOutput`-named symbol in SAP3 src is
  `ModelOutputError` (`src/sapphire_flow/exceptions.py:17`) — the *planned* error subclass,
  not a use of FI's output type.

This document therefore describes a **forward contract**, not an implemented one. Everything
below states what the adapter *must* do when built; it is not a description of running code.

---

## 2. The two adapter paths

The adapter boundary sits between SAP3's assembly layer and the FI model. SAP3 selects a
path by `artifact_scope` (doc 014 lines 114–127).

```
STATION path (v0b — ships first):
  ModelDataRequirements → assembly → StationModelInputs → adapter → FI input
    → FI model → ModelOutput → adapter → tuple[dict[str, ForecastEnsemble], bytes | None]
        (SAP3)                 (boundary)    (FI)        (boundary)        (SAP3)

GROUP path (v1 — multi-station):
  ModelDataRequirements → assembly → GroupModelInputs → adapter → FI input
    → FI model → ModelOutput → adapter → dict[StationId, tuple[dict[str, ForecastEnsemble], bytes | None]]
        (SAP3)                 (boundary)    (FI)        (boundary)            (SAP3)
```

- **v0b ships the STATION path only.** FI-wrapped models implement
  `StationForecastModel` (`src/sapphire_flow/protocols/forecast_model.py:23`). Its
  `predict()` returns `tuple[dict[str, ForecastEnsemble], bytes | None]` (line 32–39).
- **GROUP / multi-station is v1.** `GroupForecastModel.predict_batch()` must return
  `dict[StationId, tuple[...]]` (`src/sapphire_flow/protocols/forecast_model.py:58–63`).
  Decomposing a single `ModelOutput` per station requires station-keyed FI output — see §5.

---

## 3. Output mapping (FI → SAP3)

FI's output is authoritative; SAP3 adapts. This table grounds and supersedes doc 014's
divergence table (lines 138–151) on the FI side.

| FI type / field (`path:line`) | SAP3 target (`path:line`) | Adapter responsibility |
|---|---|---|
| `ModelOutput` (`output/model_output.py:9`) | `tuple[dict[str, ForecastEnsemble], bytes \| None]` (`protocols/forecast_model.py:38`) | Convert whole container → forecast dict + state bytes. |
| `VariableOutput.deterministic` / `.quantiles` / `.trajectories` (`output/variable_output.py:109–111`) | `ForecastEnsemble` (`types/ensemble.py:18`) | Pick whichever is populated; route to the matching factory. |
| `TrajectoryData` (`output/variable_output.py:64`) | `ForecastEnsemble.from_members()` (`types/ensemble.py:39`) → `MEMBERS` | Reshape member columns → `member_id`/`value`; ≥1 member (SAP3 line 60–62). |
| `QuantileData` (`output/variable_output.py:33`) | `ForecastEnsemble.from_quantiles()` (`types/ensemble.py:76`) → `QUANTILES` | Reshape quantile columns → `quantile`/`value`. **See operational gap below.** |
| `DeterministicData` (`output/variable_output.py:20`) | single-member `MEMBERS` ensemble (`types/ensemble.py:39`) | Wrap the single `value` column as `member_id=1`; flagged `insufficient_ensemble_size`, skips operational alert thresholds (doc 014 lines 190–196). |
| `EpistemicUncertaintyData` (`output/variable_output.py:90`) | — (no SAP3 target) | **Dropped at the boundary in v0b** (FI-only; doc 014 lines 197–204). Revisit if models emit it. |
| `VariableOutput.flags: frozenset[ForecastFlag]` (`output/variable_output.py:113`; enum `output/flags.py:4`) | `QcFlag.rule_id` strings | Map to `fi_*` rule ids (table below). |
| `VariableStatus` (`output/status.py:4`) | `QcStatus` (`types/enums.py:4`) | Map per table below. |
| `VariableMetadata.unit: Unit` (`output/metadata.py:11`; enum `common/units.py:4`) | `ForecastEnsemble.units: str` (`types/ensemble.py:24`) | Map `Unit` enum → SAP3 canonical unit string (table below). |
| `ModelOutput.issue_datetime` (`output/model_output.py:13`) | `ForecastEnsemble.issued_at: UtcDatetime` (`types/ensemble.py:22`) | Apply `ensure_utc()`. |
| per-row `datetime` column (all FI data containers) | `valid_time` column (SAP3 factories require it: `types/ensemble.py:54,91`) | Rename `datetime` → `valid_time`. |
| `VariableMetadata.forecast_horizon: int` (`output/metadata.py:14`) | `ForecastEnsemble.forecast_horizon_steps: int` (`types/ensemble.py:25`) | **DIRECT** — both int, both step counts. **`forecast_horizon` IS consumed by the adapter** (corrects any prior "never consumed" belief). See note below. |
| `VariableMetadata.timedelta: timedelta` (`output/metadata.py:13`) | `ForecastEnsemble.time_step: timedelta` (`types/ensemble.py:23`) | **DIRECT** assignment. |
| `VariableMetadata.resolution: TemporalResolution` (`output/metadata.py:12`; enum `common/resolutions.py:4`) | — (no direct target) | Categorical label only; **cross-validate** against `timedelta`, never the conversion source. |
| `ModelOutput.variables` key / `VariableMetadata.name` (`output/model_output.py:14`, `output/metadata.py:10`) | `ForecastEnsemble.parameter: str` (`types/ensemble.py:23`) | Validate against `ForecastParameter = Literal["discharge","water_level"]` and `ModelDataRequirements.target_parameters` (`types/model.py:261`). |
| empty `ModelOutput.variables` **or** all-`FAILURE` | `ModelOutputError` (`exceptions.py:17`) | Adapter **raises** — zero usable ensembles (doc 014 lines 160–168, 218–223). |

### Status & flag mapping

`VariableStatus` → `QcStatus` (doc 014 lines 247–248):

| FI `VariableStatus` | SAP3 `QcStatus` (`types/enums.py:4`) | Note |
|---|---|---|
| `SUCCESS` | `QC_PASSED` (`"qc_passed"`) | — |
| `FAILURE` | `QC_FAILED` (`"qc_failed"`) | If **all** variables fail → raise `ModelOutputError` instead. |
| `PARTIAL` | `QC_SUSPECT` (`"qc_suspect"`) + flag | No exact equivalent; attach `fi_partial_output`. |

`ForecastFlag` → `QcFlag.rule_id` (doc 014 lines 250–253; `fi_` prefix marks FI-origin):

| FI flag (`output/flags.py:4`) / status | SAP3 `QcFlag.rule_id` |
|---|---|
| `VariableStatus.PARTIAL` | `fi_partial_output` |
| `ForecastFlag.HIGH_EPISTEMIC_UNCERTAINTY` | `fi_high_epistemic_uncertainty` |
| `ForecastFlag.DATA_AVAILABILITY` | `fi_data_availability` |

All FI enums use UPPER_CASE member names; SAP3 stores lowercase `.value`. Convert at the
boundary — never pass FI enum values into the SAP3 domain layer (doc 014 lines 151, 254).

### Unit mapping (`Unit` enum → SAP3 canonical unit string)

FI's `Unit.value` holds a glyph form (e.g. `"m³/s"`, `common/units.py:5`). SAP3 expects an
ASCII canonical string from its `parameters` table (doc 014 line 147). The adapter maps by
**enum member**, not by `.value`:

| FI `Unit` member (`common/units.py`) | FI `.value` | SAP3 canonical string |
|---|---|---|
| `M3_PER_S` | `m³/s` | `m3/s` |
| `MM_PER_DAY` | `mm/day` | `mm/day` |
| `MM_PER_S` | `mm/s` | `mm/s` |
| `MM` | `mm` | `mm` |
| `CM` | `cm` | `cm` |
| `M` | `m` | `m` |
| `DEG_C` | `°C` | `degC` |
| `UNITLESS` | `-` | `-` |

### `QuantileData` operational gap (FI valid ≠ SAP3 usable)

FI's `QuantileData` requires only **≥1** quantile level in `(0,1)`, sorted & unique
(`output/variable_output.py:39–51`). SAP3's `from_quantiles()` requires **≥7** quantile
levels **with tail coverage** (min ≤ 0.05 and max ≥ 0.95) (`types/ensemble.py:98–106`).

Consequently an FI model emitting fewer than 7 quantiles (or without tail coverage) is
**structurally valid FI output but NOT operationally usable by SAP3** — `from_quantiles()`
raises `ValueError`. State this to model authors explicitly: FI's quantile floor is a
permissive structural minimum; SAP3's operational floor is stricter.

### `forecast_horizon` consumption note

Two horizon notions coexist and must not be conflated:

- `VariableMetadata.forecast_horizon` (`output/metadata.py:14`) is the **declared** step
  count. The adapter assigns it directly to `ForecastEnsemble.forecast_horizon_steps`.
- SAP3's factories also recompute a horizon internally as
  `values["valid_time"].n_unique()` (`types/ensemble.py:63,107`). The adapter should ensure
  these agree (declared horizon == distinct `valid_time` count) and treat a mismatch as a
  structural error.

### `success` property caveat

`ModelOutput.success` returns `True` when `variables` is empty, because `all()` over an
empty iterable is `True` (`output/model_output.py:33–36`). The adapter **must not** rely on
`success` alone to gate conversion (doc 014 lines 219–223).

> **Discrepancy vs doc 014:** Current FI now *forbids* empty `variables` at construction —
> `ModelOutput._at_least_one_variable` raises if the dict is empty
> (`output/model_output.py:23–31`). So the empty-variables case is no longer constructible
> through the public API. The all-`FAILURE` → `ModelOutputError` guard remains live and
> necessary; the empty-variables guard is now defense-in-depth.

---

## 4. Input mapping (SAP3 → FI)

Per doc 014 Task 3 (lines 257–283), SAP3 will PR FI's input types. FI's input contract is
*already partially implemented* in this repo (`forecast_interface/input/`) — see the
discrepancy note at the end of this section.

### Concept → field mapping

| FI input concept (`path:line`) | SAP3 `ModelDataRequirements` field (`types/model.py:260`) |
|---|---|
| `past_known` temporality (`input/requirement.py:9`) | `past_dynamic_features: frozenset[str]` (line 262) |
| `future_known` temporality (`input/requirement.py:10`) | `future_dynamic_features: frozenset[str]` (line 263) |
| `InputRequirement.static` (`input/requirement.py:37`) | `static_features: frozenset[str]` (line 264) |
| `PastKnownVariable.lookback` (`input/variable.py:12`) | `lookback_steps: int` (line 266) |
| `FutureKnownVariable.future_steps` (`input/variable.py:31`) | `forecast_horizon_steps: int` (line 267) |
| `TemporalResolution` keys + `VariableMetadata.timedelta` | `supported_time_steps: frozenset[timedelta]` (line 265) |
| `SpatialRepresentation` keys (`input/requirement.py`) | `spatial_input_type: SpatialRepresentation` (line 268) |
| `InputRequirement.targets` keys + `TargetSpec.unit`/`.representations` (`input/target.py`) | `target_parameters: frozenset[str]` (line 261) |
| `PastKnownVariable.max_nan` / `FutureKnownVariable.max_nan` (`input/variable.py:13,32`) | Derivable from SAP3 QC config (doc 014 line 273) |
| `FutureKnownVariable.ensemble_mode` (`input/variable.py:33`) | Derivable from NWP ensemble config (doc 014 line 273) |

### Assembled inputs (4-slot)

After requirement matching, SAP3 assembles concrete DataFrames into a 4-slot shape, passed
to the FI model via the adapter. The slots are identical for station and group:

| Slot | `StationModelInputs` (`types/model.py:59`, via `StationInputData` line 51) | `GroupModelInputs` (`types/model.py:78`) |
|---|---|---|
| `past_targets` | target history | stacked, `station_id`-keyed |
| `past_dynamic` | past dynamic features | stacked |
| `future_dynamic` | future dynamic features | stacked |
| `static` (`pl.DataFrame \| None`) | catchment attributes | stacked, one row per station |

`GroupModelInputs.for_station()` (`types/model.py:89`) slices a group into per-station
`StationInputData`. Both carry `issue_time`, `forecast_horizon_steps`, `time_step`.

### Spatial enum mapping (FI → SAP3)

As of Phase 1, FI's `SpatialRepresentation` (`common/resolutions.py`) adopts SAP3's exact
member names and values (`types/enums.py:73`), so the mapping is **identity**:

| FI `SpatialRepresentation` | SAP3 `SpatialRepresentation` |
|---|---|
| `POINT` (`"point"`) | `POINT` (`"point"`) |
| `BASIN_AVERAGE` (`"basin_average"`) | `BASIN_AVERAGE` (`"basin_average"`) |
| `ELEVATION_BAND` (`"elevation_band"`) | `ELEVATION_BAND` (`"elevation_band"`) |
| `GRIDDED` (`"gridded"`) | `GRIDDED` (`"gridded"`) |

> The earlier `LUMPED`/`HRU` names were renamed to `BASIN_AVERAGE`/`ELEVATION_BAND` and
> `POINT` was added, completing the alignment proposed in the SAP3→FI input PR.

---

## 5. Station identity & the GROUP path (Option a)

FI's `ModelOutput.variables` is currently `dict[str, VariableOutput]`
(`output/model_output.py:14`) — keyed by **variable name**, with no station decomposition.
SAP3's `GroupForecastModel.predict_batch()` requires per-station results
(`dict[StationId, ...]`, `protocols/forecast_model.py:63`).

**Decision recorded (doc 014 "Option (a)", lines 208–217):** FI adopts **station-keyed
output** so the GROUP-path adapter can map per-station 1:1:

```
ModelOutput.variables : dict[station_id, dict[variable, VariableOutput]]
```

- Single-station models return a **one-key dict** (one station id → its variable map).
- The STATION-path adapter unwraps the single key into
  `tuple[dict[str, ForecastEnsemble], bytes | None]`.
- The GROUP-path adapter maps each station key → one `(forecast_dict, state)` entry of the
  `dict[StationId, tuple[...]]` return.

**Cross-repo coordination item (FLAG):** SAP3's adapter design in doc 014 is currently
**STATION-path-only** for v0b (lines 208–217 explicitly defer GROUP support). When FI moves
to station-keyed output, SAP3's `ForecastInterfaceAdapter` must be extended to consume it.
Until both sides land this change, GROUP-path FI wrapping is not possible. This is the
single largest open structural divergence between the two repos.

---

## 6. State bridge

FI is **state-free**: the `ForecastModel` protocol (`interface/protocol.py:10`) has no
state parameter or return, and `ModelOutput` carries no warm-up snapshot.

SAP3 carries warm-up state as `bytes | None`:

- `StationForecastModel.predict(..., prior_state: bytes | None = None)` →
  `tuple[..., bytes | None]` (`protocols/forecast_model.py:32–39`).
- The state lifecycle is handled **entirely by the adapter**, not by FI.

**v0b:** FI-wrapped models are stateless (doc 014 lines 205–207). The adapter:

- Ignores `prior_state` (nothing to feed an FI model).
- Returns `(forecast_dict, None)` — no state to snapshot.

**v1 (future):** optional `dump_state` / `restore_state` methods on the FI `ForecastModel`
protocol would let conceptual / hybrid models round-trip warm-up state through the adapter
(doc 014 lines 129–134, 206–207). Not part of the current FI protocol.

---

## 7. Artifact metadata ownership

Training provenance and storage metadata are split between FI-declared / artifact-embedded
fields and SAP3-stored fields (`ModelArtifactRecord`, `types/model.py:290`).

| Field / concept | Owner | Where |
|---|---|---|
| Model identity / name | FI / artifact | `ModelOutput.model_name` (`output/model_output.py:12`); embedded in artifact |
| `interface_version` | FI / artifact | declared by model, embedded in artifact |
| `model_version` | FI / artifact | declared by model, embedded in artifact |
| Training provenance hashes | FI / artifact | embedded in artifact |
| Training seed | FI / artifact | embedded in artifact (deterministic training) |
| Product / data-source versions | FI / artifact | embedded in artifact |
| Region scope | FI / artifact | declared by model, embedded in artifact |
| Embedding-key behaviour when station set differs | FI / artifact | model declares how it keys stations (relevant to GROUP path, §5) |
| `sha256_hash` | **SAP3** | `ModelArtifactRecord.sha256_hash` (`types/model.py:297`) |
| `training_period_start` / `_end` | **SAP3** | `types/model.py:298–299` |
| `trained_at` | **SAP3** | `types/model.py:300` |
| `status` | **SAP3** | `ModelArtifactStatus` (`types/model.py:295`; enum `types/enums.py:47`) |
| scope / `group_id` / `station_id` | **SAP3** | `types/model.py:293–294`; scope via `ArtifactScope` (`types/enums.py:41`) |

FI/artifact side answers *"what is this model and how was it built"*; SAP3 side answers
*"which trained binary is stored, for which scope, in what lifecycle state"*.

---

## 8. Open cross-repo items

| # | Item | Detail |
|---|---|---|
| 1 | Typed IDs vs str | SAP3 `StationId`/`StationGroupId` are `NewType(UUID)` but `ModelId` is `NewType(str)` (`types/ids.py:4,16,21`). FI uses free-form `str` for variable/model names. Decide whether FI adopts typed ids at the boundary or the adapter parses str→UUID. |
| 2 | SAP3 input-types PR scope | Whether the SAP3→FI PR lands `target_parameters` and `spatial_input_type`/`POINT` into FI's input spec (doc 014 lines 275–276; §4 above). |
| 3 | GROUP-path adapter extension | Station-keyed FI output (§5) requires SAP3's STATION-only adapter design to extend to GROUP. Largest structural divergence. |
| 4 | Quantile floor mismatch | FI requires ≥1 quantile (`output/variable_output.py:39–51`); SAP3 requires ≥7 with tail coverage (`types/ensemble.py:98–106`). FI output can be valid yet operationally unusable (§3). |
| 5 | Epistemic uncertainty | `EpistemicUncertaintyData` is dropped at the boundary in v0b (doc 014 lines 197–204). Revisit (add to `ForecastEnsemble` / store as metadata) if models emit it. |
| 6 | Interface module now exists | doc 014 assumes FI's `interface/` is unimplemented (lines 80, 287). It is now implemented (`ForecastModel`, `ModelResult`, `FailureCause`). SAP3 should re-evaluate Tasks 4–5 against the real protocol. |
| 7 | `ModelResult` failure channel | FI now returns `ModelResult = ModelSuccess \| ModelFailure` (`interface/result.py:40`) with a `FailureCause` enum (`interface/failure.py:4`). SAP3's `ModelOutputError` path must account for the `ModelFailure` branch, not only all-`FAILURE` `ModelOutput`. |
| 8 | Resolution enum split | FI split into `TemporalResolution` + `SpatialRepresentation` (`common/resolutions.py`); doc 014 references a single `Resolution`. Mapping tables above use the current split. |
```
