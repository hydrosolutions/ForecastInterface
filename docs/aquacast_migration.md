# aquacast migration note

For the aquacast model-framework maintainer. This note covers what changes when you adopt the two stacked pull requests:

- **#13** (stacked first): temporal contract, FI issue #9, decision 1.17.
- **#14** (stacked on #13): training time grid, FI issue #12, decision 1.18.

Neither is released or tagged. Status: aquacast PR #149 (merged) already makes aquacast emit UTC-aware datetimes and validate cadence per issue group, tested against #13 at bc16dfc, so section 2 is done on the aquacast side apart from re-checking the cases listed there. The production pin stays at v0.1.20 until the shared release. Adoption is lockstep with SAP3: both pin FI by exact tag, and SAP3 enforces the pin at run time. We cut one tag after you have confirmed the points in section 4. Until then, nothing here is final.

Section 2 lists the changes that will make existing code fail. Section 3 lists additions that are optional: a model that ignores them keeps working, and its artifacts are read as `Unknown`. The reasons behind each change are in `docs/open_design_questions.md`, decisions 1.17 and 1.18.

## 1. What changes, in short

- **#13** turns the time rules FI already documented into checks. Every datetime is a timezone-aware UTC datetime, there are no nulls, and forecast rows are spaced exactly by the declared step.
- **#14** lets a model say, and FI check, on which clock its time steps sit. A daily mean can be stamped at 00:00Z or at 18:00Z, and it can be stamped at the start or the end of the day it covers. A model trained on one convention and fed another degrades silently. FI now lets you declare the convention (`TimeGrid`: step, origin, label) and compares declarations by exact equality. FI never shifts or converts data.

## 2. Required changes (breaking)

Run your tests against the branch first (section 5). Anything in this list that your code does today will now raise a `ValidationError`.

### 2.1 Datetime columns must be timezone-aware UTC, with the literal zone name `UTC`

This applies to `issue_datetime` and `datetime` in all four output frames (deterministic, quantiles, trajectories, epistemic uncertainty) and to the `datetime` column of `InputSeries`.

- Naive datetimes are rejected.
- Other zones (for example `Asia/Kathmandu`) are rejected. Convert to UTC.
- The alias `Etc/UTC` is rejected on purpose. Only the string `UTC` is accepted, so that two systems never disagree on what "UTC" means.

Before, this worked:

```python
frame = pl.DataFrame({
    "issue_datetime": [datetime(2024, 6, 1)] * 2,   # naive
    "datetime": [datetime(2024, 6, 2), datetime(2024, 6, 3)],
    "value": [1.0, 2.0],
})
```

After, localise naive data that is already in UTC, or convert data in another zone:

```python
frame = frame.with_columns(
    pl.col("issue_datetime", "datetime").dt.replace_time_zone("UTC")
)
# Data stamped in a local zone: convert, do not relabel.
local = local.with_columns(pl.col("datetime").dt.convert_time_zone("UTC"))
# Data typed "Etc/UTC": convert to the literal "UTC".
etc = etc.with_columns(pl.col("datetime").dt.convert_time_zone("UTC"))
```

`replace_time_zone("UTC")` only attaches the label, so use it only when the values really are UTC. If they are local clock times, use `convert_time_zone` after attaching the true zone.

### 2.2 `ModelOutput.issue_datetime` and `ModelFailure.issue_datetime` must be UTC-aware

These scalars had no validator before. They now reject naive datetimes and any offset other than zero.

```python
issue = datetime(2024, 6, 1, 6, 0, tzinfo=UTC)   # was: datetime(2024, 6, 1, 6, 0)
failure = ModelFailure(
    model_name="aquacast",
    issue_datetime=issue,
    cause=FailureCause.INPUT_DATA,
    message="no discharge for the last 3 days",
)
```

A `+05:45` datetime is rejected too. Convert it with `.astimezone(UTC)` first.

### 2.3 No null datetimes

Neither `issue_datetime` nor `datetime` may contain a null, in any output frame. `InputSeries` already rejected null `datetime` values; the output side now does the same. Drop or fill such rows before building the output.

### 2.4 Cadence must match `VariableMetadata.timedelta` exactly

Within each `issue_datetime` group, consecutive `datetime` values must be spaced by exactly `metadata.timedelta`, and rows must be sorted ascending. A gap or a duplicate is an error. A group with a single row passes.

```python
issue = datetime(2024, 6, 1, 6, 0, tzinfo=UTC)
metadata = VariableMetadata(
    unit=Unit.M3_PER_S, timedelta=timedelta(days=1), forecast_horizon=2, offset=1
)
# Before: days 1 and 3 were accepted. After: this raises, because the gap is 2 days.
rows = [issue + timedelta(days=1), issue + timedelta(days=3)]
```

The error message names the `issue_datetime` group and the `datetime` where the gap occurs. If your model skips a day on purpose (for example a missing forecast step), pad it with a row, or declare the right `timedelta`.

### 2.5 `epistemic_uncertainty` must not be empty

A present but zero-row `epistemic_uncertainty` frame used to pass. It now raises. Pass `None` when you have nothing to report.

```python
output = VariableOutput(
    metadata=metadata,
    deterministic=deterministic,
    epistemic_uncertainty=None,      # not an empty frame
    status=VariableStatus.SUCCESS,
)
```

### 2.6 Checklist

- [ ] All frames use `Datetime(time_zone="UTC")`, never naive, never `Etc/UTC`.
- [ ] Every `issue_datetime` scalar given to `ModelOutput` and `ModelFailure` is UTC-aware.
- [ ] `InputSeries` frames you build (tests, fixtures, adapters) have a UTC `datetime` column.
- [ ] No null datetimes in any output frame.
- [ ] Each forecast block is evenly spaced by `VariableMetadata.timedelta`.
- [ ] No empty `epistemic_uncertainty` frames.

## 3. Optional additions (nothing is forced)

All of these have defaults of "unknown". A model that declares none of them runs as before, and its artifacts are read as `Unknown` (compatibility `UNKNOWN`, never an error). Declare them when you know the answer; FI never infers it.

### 3.1 Declare the training grid on the artifact

Implement the `GridDeclaringArtifact` protocol: a `training_grid` property returning a `TrainingGridDeclaration`. Artifacts without it are legacy and read as `Unknown`.

```python
class AquacastArtifact:
    training_grid = TrainingGridDeclaration(
        grid=TimeGrid(
            step=timedelta(days=1),
            origin=timedelta(0),          # offset from UTC midnight, whole minutes
            label=PeriodLabel.START,      # stamp t names [t, t + step)
        )
    )

isinstance(AquacastArtifact(), GridDeclaringArtifact)     # True
artifact_training_grid(AquacastArtifact())                # the declaration above
artifact_training_grid(object())                          # Unknown, no error
```

Rules for `TimeGrid`: `step` is a whole number of minutes and divides 24 h exactly; `0 <= origin < step`; `label` is `START`, `END` or `UNKNOWN`. A period is the same half-open interval `[a, b)` under either label; `START` stamps `a`, `END` stamps `b`. An origin alone does not tell them apart: a day stamped `18:00Z` on its start and one stamped `18:00Z` on its end are both `18:00` mod 24 h, which is why the label exists.

How the orchestrator compares declarations (you do not have to call this, but you can):

```python
deployment = TimeGrid(timedelta(days=1), timedelta(hours=18), PeriodLabel.END)
declared = AquacastArtifact.training_grid.grid
compatibility(deployment, declared)        # Compatibility.MISMATCH
try:
    require_compatible(deployment, declared)
except GridMismatchError as error:
    failure = grid_mismatch_failure(error, model_name="aquacast", issue_datetime=issue)
    failure.cause                          # FailureCause.GRID_MISMATCH
```

Equality is exact on step, origin and label. `UNKNOWN` is returned, never guessed, and `require_compatible` raises only on `MISMATCH`; whether `UNKNOWN` is acceptable is an operator decision. A deployment that uses 18:00Z as the UTC+5:45 day boundary (the real civil midnight is 18:15Z) is a deliberate 15-minute approximation, and data stamped 18:15Z will be a `MISMATCH`. See decision 1.18.

### 3.2 Declare the anchor and labels on the inputs

`SpatialInputSpec.anchor` is a `TimeAnchor` on the per-step branch. Each variable can override the branch label; with `label=None` it inherits.

```python
requirement = InputRequirement(
    targets={
        "discharge": TargetSpec(
            unit=Unit.M3_PER_S,
            representations=frozenset({OutputRepresentation.QUANTILES}),
            aggregation=AggregationMethod.MEAN,    # daily mean discharge
            label=PeriodLabel.START,
        )
    },
    dynamic={
        timedelta(days=1): SpatialInputSpec(
            anchor=TimeAnchor(origin=timedelta(0), label=PeriodLabel.START),
            data={
                SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                    past_known={
                        "era5": {
                            "precip": PastKnownVariable(
                                lookback=30, max_nan=0, unit=Unit.MM_PER_DAY,
                                aggregation=AggregationMethod.MEAN,
                            ),
                            "swe": PastKnownVariable(
                                lookback=1, max_nan=0, unit=Unit.MM,
                                aggregation=AggregationMethod.POINT,  # sampled value
                            ),
                        }
                    }
                )
            },
        )
    },
)
```

Notes:

- `AggregationMethod` gains `MIN` and `POINT` (`MAX` was added earlier). `POINT` is an instantaneous value sampled at the stamp, so a label is meaningless and FI rejects one; a `POINT` variable never inherits the branch label.
- `TargetSpec.aggregation` defaults to explicit `Unknown.UNKNOWN` (never `None`; `None` is rejected, since targets have no per-parameter convention). A `SUM` target with a rate unit (m³/s, mm/day, ...) is rejected. `MEAN` with `mm` or `m` stays legal (snow water equivalent, water level).
- `anchor.origin` must satisfy `0 <= origin < step`, and the step must divide 24 h once an origin is declared.

### 3.3 Echo the declaration in the output metadata

`VariableMetadata` has three new optional fields. If you set `origin`, FI checks that every `datetime` in the output sits on that phase.

```python
metadata = VariableMetadata(
    unit=Unit.M3_PER_S,
    timedelta=timedelta(days=1),
    forecast_horizon=10,
    offset=1,
    origin=timedelta(0),                    # whole minutes from UTC midnight
    label=PeriodLabel.START,
    aggregation=AggregationMethod.MEAN,     # echoes TargetSpec.aggregation
)
```

The orchestrator checks that `aggregation` agrees with the target declaration, so a `ModelOutput` describes itself. FI does not check whether the first output period includes its already-elapsed part (lead time 0); the agreed product is the whole current-day period, and the replacement model must show it (decision 1.18, scope limits).

### 3.4 Input bundles

`ModelInputs` has an optional `grid`. When it is a `TimeGrid`, FI checks that the datetimes of the branch with that step lie on the grid. Branches with other steps are not checked, and a grid that matches no station's branch raises, since that is a wiring error. This is for the orchestrator; models do not need to set it.

## 4. What aquacast needs to tell us

The open checklist for aquacast lives in one place: the **FI issue #12 thread**. Please answer there rather than in this note or by message, so there is a single record. The questions, in the order we need them:

1. **Training contract per variable.** aquacast issue #148 already records a start-label, `[start, end)` convention with the clock set per resolution (daily on gauge-local midnight, subdaily on a UTC grid). Is that what you would embed as the `TrainingGridDeclaration`? Note that a gauge-local daily clock (for example Nepal, UTC+5:45) becomes an `origin` in whole minutes from UTC midnight. For each variable the model is trained on (discharge, precipitation, temperature, SWE, snowmelt, and so on): the step, the origin (offset from UTC midnight) and the label (`START` or `END`). Is it the same for all of them, or per variable?
2. **Instantaneous or mixed-label inputs.** Which inputs are point values (`POINT`) and which are windowed? Are any labelled differently from the others?
3. **Non-daily steps.** Does any artifact use 3 h, 6 h or other steps? Do those share one origin?
4. **Embedding the declaration.** Can your artifacts store a `TrainingGridDeclaration` and return it from a `training_grid` property? If not, how do you want it supplied?
5. **Label granularity.** Is one label per branch enough, or do you need one per variable (the per-variable override covers this; we want to know if it is needed)?
6. **Other models' input types.** Which input types do other aquacast models use that the current `InputRequirement` cannot express?
7. **`BatchHindcastModel` return shape.** `hindcast` takes many issue times and returns one `ModelResult`, so one `ModelOutput` with one scalar `issue_datetime` must carry rows for many issue times. The proposed validator that checked every row against that scalar was dropped because it cannot work with this shape (decision 1.17). FI has to choose between a declared list of issue times on `ModelOutput` and a sequence of results. Which would suit aquacast?
8. **Issue #15 (per-row `issue_datetime` and `BatchHindcastModel`).** A strict per-row check against `ModelOutput.issue_datetime` was pulled because a batch hindcast returns one output with several issue times. Does aquacast implement `BatchHindcastModel`, and what does it return? Please answer in #15.

Also still open from earlier rounds and not part of these PRs: the station-code confirmation (that your artifacts key stations by station code) and the train-time `config` contents (Q8, Q10 in `docs/open_design_questions.md`).

## 5. Verification recipe

From a checkout of the FI repository, on the #14 branch (it contains #13):

```bash
uv sync
uv run pytest                      # full suite, includes temporal and grid tests
uv run mypy                        # strict type check
uv run ruff check
```

To try your own outputs, build them against the branch and look for `ValidationError`:

```bash
uv run python << 'EOF'
from datetime import UTC, datetime, timedelta
import polars as pl
from forecast_interface import DeterministicData

issue = datetime(2024, 6, 1, 6, tzinfo=UTC)
frame = pl.DataFrame({
    "issue_datetime": [issue] * 2,
    "datetime": [issue + timedelta(days=1), issue + timedelta(days=2)],
    "value": [1.0, 2.0],
})
DeterministicData(data=frame)
print(frame.schema)   # both temporal columns: Datetime(time_unit='us', time_zone='UTC')
EOF
```

In aquacast, install the branch of FI in a throwaway environment (`uv add` the git reference of the #14 branch) and run your test suite. Expect failures only from the list in section 2. The error messages say which column, group and row is at fault. When the release tag exists, pin that exact tag.
