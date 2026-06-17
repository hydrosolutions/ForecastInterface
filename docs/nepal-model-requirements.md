# Nepal Requirements for ForecastInterface and Model Implementers

**Date:** 2026-06-11
**Audience:** ForecastInterface maintainer, model implementer, SAPPHIRE Flow
maintainers

## Goal

ForecastInterface must support a Nepal workflow where SAPPHIRE Flow implements
and validates the eastern part of the country, while DHM/hydromet staff train
and configure models for the western part. The same interface must also allow
operators to test one model across all gauges or keep separate east/west models.

## Current Alignment With SAPPHIRE Flow

SAPPHIRE Flow already has these concepts internally:

- explicit model data requirements:
  - target parameters;
  - past dynamic features;
  - future dynamic features;
  - static features;
  - supported time steps;
  - lookback steps;
  - forecast horizon;
  - spatial input type;
- station-scoped and group-scoped model artifacts;
- stacked multi-station inputs for group models;
- per-station output from group models;
- active/superseded artifact lifecycle;
- hindcast and skill computation after training;
- multiple model assignments per station;
- pooled and BMA forecast combination for member ensembles.

ForecastInterface already has:

- an `InputRequirement` structure with temporal/spatial/product axes;
- `predict()` and `hindcast()` protocol methods;
- output containers for deterministic, quantile, trajectory, and epistemic
  uncertainty data.

The main missing pieces are training/retraining, artifact metadata/provenance,
target declaration, and the station dimension for multi-station models.

## Required Interface Capabilities

### 1. Explicit target declaration

ForecastInterface must declare what variables the model forecasts, separate
from predictor variables.

Required:

- `target_variables`, e.g. `{"discharge"}` or `{"water_level", "discharge"}`;
- units for each target;
- output representation supported for each target: deterministic, quantiles,
  trajectories/members, or combinations;
- validation that output variable keys match declared targets unless a model
  returns a documented subset with `PARTIAL` status.

Why: SAPPHIRE Flow uses target variables for station compatibility, skill
scoring, API storage, and deciding which observations are needed.

### 2. Station and group model output shape

ForecastInterface must support models that predict for many gauges in one call.

Required output shape:

```python
variables: dict[str, dict[str, VariableOutput]]
#          station_id  variable_name
```

Rules:

- station IDs in the output must match station IDs in the input;
- single-station models return a one-station mapping;
- forecast DataFrames can remain per-station and do not need a `station_id`
  column if the station dimension is in the outer dict;
- missing station outputs must be explicit failures, not absent keys.

### 3. Training and retraining protocol

ForecastInterface needs a training API in addition to `predict()` and
`hindcast()`.

Required operations:

```python
train(inputs, *, config, rng) -> TrainedArtifact
retrain(base_artifact, inputs, *, config, rng) -> TrainedArtifact
serialize_artifact(artifact) -> bytes
deserialize_artifact(raw: bytes) -> TrainedArtifact
```

Acceptable naming can be finalized by the ForecastInterface maintainer, but the
capabilities must exist.

Required behavior:

- `train()` creates a new model artifact from training data.
- `retrain()` can start from an existing artifact or checkpoint and update it
  with new data.
- Retraining must be deterministic when config, input data, and random seed are
  fixed.
- The model must fail with a clear error when the provided data does not satisfy
  declared requirements.
- Training and retraining must work for station-scoped, regional group-scoped,
  and national group-scoped models.

**Resolved (SAPPHIRE Flow, 2026-06-11): cold retrain required, warm-start optional.**
`train()` — a full rebuild on the (updated) dataset — is the **required** contract every
model must implement; it works for conceptual and ML models alike. `retrain(base_artifact,
…)` / warm-start (fine-tune from an existing artifact) is an **optional** capability for
models that support it; a model that does not implement it simply cold-trains. This
resolves the open question below: full rebuild is the required baseline, warm-start is an
optional optimisation.

### 4. Artifact metadata and provenance

Every trained artifact must carry metadata that SAPPHIRE Flow can store and use
for safe promotion/rollback.

Required artifact metadata:

| Field | Purpose |
|---|---|
| `model_name` / `model_id` | Stable model identity. |
| `interface_version` | Compatibility with ForecastInterface. |
| `model_version` | Code/config version from implementer. |
| `artifact_scope` | `station`, `group`, or `national`/country-level group. |
| `region_scope` | `east`, `west`, `national`, or another agreed label. |
| `station_ids` | Gauges used for training and valid application. |
| `training_period_start`, `training_period_end` | Reproducibility and skill context. |
| `input_requirement_hash` | Detects incompatible interface changes. |
| `training_data_hash` | Detects data changes. |
| `catchment_package_version` | Links artifact to gateway shapefile/catchment version. |
| `snowmapper_product_version` | Links artifact to SnowMapper inputs if used. |
| `weather_product_versions` | Links artifact to NWP/reanalysis inputs. |
| `random_seed` | Reproducibility. |
| `created_at_utc` | Audit trail. |

### 5. Region and application constraints

Model artifacts must make their valid application scope explicit.

Required:

- a national model can declare valid application to all listed Nepal gauges;
- an eastern model can declare valid application to eastern gauges only unless
  explicitly marked as transferable/test-only;
- a western model can declare valid application to western gauges only unless
  explicitly marked as transferable/test-only;
- applying a model outside its declared region must be possible in test mode but
  should require an explicit operator choice.

Why: DHM may want to test one model on all gauges, but accidental cross-region
promotion should be prevented.

### 6. Output requirements for model comparison and combination

If a model should participate in pooled/BMA combination in SAPPHIRE Flow, it
must output trajectory/member forecasts, not quantiles only.

Required:

- trajectory/member outputs must have stable member IDs;
- all members must share the same issue time, valid times, units, and horizon;
- quantile-only outputs are acceptable for primary/fallback operation but should
  be marked as not combinable for pooled/BMA.

### 7. Input requirements for SnowMapper and catchment data

ForecastInterface input requirements must be able to express:

- SnowMapper variables such as SWE and snowmelt as past and/or future dynamic
  features;
- product/source names and versions;
- spatial representation: POINT, BASIN_AVERAGE, ELEVATION_BAND, or GRIDDED;
- static catchment attributes required by the model;
- allowed missing-data thresholds per variable and product.

### 8. Artifact portability across deployments (staging → production)

HSOL trains models on a cloud **staging** instance; trained artifacts are then promoted to
the on-prem **production** deployment (where DHM also retrains). The interface must make
artifacts portable across instances.

Required:

- a trained artifact MUST be **self-contained and deployment-independent**: it serializes
  to bytes with no absolute paths and no dependence on the training environment, and
  **deserializes and runs unchanged on a different SAPPHIRE Flow instance**;
- if a group/national artifact embeds station identifiers (e.g. per-station ML
  embeddings), it MUST document the **embedding key** and its behaviour when the station
  set at predict time **differs** from training (a new western gauge; an identifier
  remapped between staging and production) — it must handle this gracefully or raise an
  **explicit error**, and never silently associate a station with the wrong embedding.

Why: SAPPHIRE Flow promotes the serialized artifact between instances; it cannot reach
inside the artifact, so the artifact must be honest about its environment and ID
assumptions. The provenance fields in §4 (`interface_version`, `input_requirement_hash`,
`station_ids`) support compatibility checks but do not by themselves guarantee runtime
portability.

## SAPPHIRE Flow Integration Implications

SAPPHIRE Flow can already store model artifacts and supersede old active
artifacts. It still needs additional work before full Nepal east/west operation:

- implement configurable retrain strategies;
- audit group-scoped model assignments and artifact lookup;
- implement merged data requirements before running multiple models with
  different inputs on one gauge;
- add operator workflows for test, promote, rollback, and regional assignment.

ForecastInterface should not assume these are solved by the model package; it
should expose enough metadata for SAPPHIRE Flow to implement them safely.

## Acceptance Criteria

- A model implementer can train an eastern, western, or national model artifact
  through ForecastInterface.
- DHM can retrain a model from an existing artifact using new western Nepal data.
- The artifact metadata tells SAPPHIRE Flow whether the model is valid for east,
  west, or all Nepal gauges.
- A group model can forecast multiple gauges in one call and return explicit
  per-station outputs.
- SAPPHIRE Flow can reject or warn on missing target variables, incompatible
  static/dynamic inputs, unsupported time steps, or invalid region application.
- Models intended for pooled/BMA combination provide trajectory/member outputs.

## Open Questions for the Model Implementer

- ~~Should retraining always start from a previous artifact, or can it also mean a
  full rebuild on an expanded dataset?~~ **Resolved:** full rebuild (cold) is the required
  baseline; warm-start from an artifact is optional (see §3).
- ~~What is the first intended artifact scope for Nepal: station, east/west group,
  or national group?~~ **Resolved:** the **eastern regional group** ships first, so the
  first production artifact is **GROUP-scoped**.
- ~~Which SnowMapper variables and lead times will the model consume?~~ **Resolved
  (partial):** starts with **SWE** and **ROF**, as banded forcing at elevation-band
  granularity (see §7). Lead times still to be confirmed.
- ~~Are western Nepal models expected to transfer to eastern gauges for testing,
  or only the other way around?~~ **Resolved:** transfer is **east → west** — an
  eastern group artifact is applied to western gauges. The eastern artifact must
  define its behaviour when the station set differs (see §8 embedding-key contract).
- Can all stateful models reconstruct state from lookback data, or do any
  require persisted hidden state between forecasts?

