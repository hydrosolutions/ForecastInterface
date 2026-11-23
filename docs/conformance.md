# Conformance checker

`forecast_interface.conformance` lets a modeller check, before delivery, that a
model, a pre-trained artifact and a few fixtures conform to ForecastInterface
(FI). It is a library API (`run_conformance`); the `fi-check` CLI and
provenance checks arrive in later steps. Nothing here adds obligations: a check
without a fixture is reported `NOT_TESTED`, never failed.

```python
from forecast_interface.conformance import run_conformance, Strictness

report = run_conformance(fixtures, seed=42, fixtures_spec="my_pkg.fixtures:make")
print(report.to_text())
raise SystemExit(int(report.exit_code(Strictness.STRICT)))
```

## Fixtures contract

Required (`Fixtures` Protocol):

| Method | Meaning |
|---|---|
| `model_factory() -> ForecastModel` | build the model under test |
| `artifact_bytes() -> bytes \| None` | a PRE-TRAINED artifact (large models are never retrained); `None` = not supplied |
| `predict_inputs() -> tuple[ModelInputs, datetime]` | inputs the model can forecast, and a UTC issue datetime |

Optional (implement the matching Protocol; return `None` or omit to skip):

| Method | Meaning |
|---|---|
| `bad_cases() -> Mapping[str, BadCase]` | named bad inputs, `BadCase(inputs, expected_cause)`; the names `short_history` and `missing_data` feed `input.short_history` / `input.missing_data`, any other name feeds `failure.returned_not_raised` |
| `train_case() -> TrainCase \| None` | `TrainCase(inputs, config, seed)`; enables training determinism and retrain; also supplies the artifact when `artifact_bytes()` is `None` |
| `unknown_station_case() -> UnknownStationCase \| None` | `UnknownStationCase(inputs, unknown_station)`: inputs that include a station the artifact was not trained for |

Fixture methods other than `model_factory` that raise are a usage error (exit 2).
`fixtures_spec="package.module:callable"` (a zero-argument callable returning the
fixtures) must be importable in a fresh interpreter for the fresh-process reload;
without it that check is `NOT_TESTED`. The fresh interpreter uses
`random.Random(seed)`; with a custom `rng_factory`, keep prediction independent of
the factory's choice of generator.

## Checks

| check_id | Layer | What it verifies |
|---|---|---|
| `protocol.methods` | FI | `isinstance(model, ForecastModel)`; `input_requirement` is an `InputRequirement` |
| `protocol.signatures` | FI | `inspect.signature` of keyword-only args (`config`, `rng`, `inputs`, `issue_datetime`; `issue_datetimes` for hindcast) because `runtime_checkable` only checks names |
| `protocol.scope` | FI | `artifact_scope` is an `ArtifactScope` |
| `capabilities.declared` | FI | reports declared `RetrainableModel`, `BatchHindcastModel`, `GridDeclaringArtifact` |
| `capabilities.retrain` / `.hindcast` | FI | only present if declared; exercised only if fixtures allow |
| `output.matches_requirement` | FI | `ModelOutput` against `InputRequirement` (see below) |
| `failure.returned_not_raised` | FI | every extra bad case returns `ModelFailure` with the expected cause; a raise or a success is FAIL |
| `input.short_history`, `input.missing_data` | FI | the same for the two named cases |
| `station.unknown` | FI | unknown station gives `ModelFailure` or an explicit FAILURE entry, never a prediction |
| `artifact.roundtrip` | FI | serialize, deserialize, predict again; equal within `atol` |
| `artifact.reload_fresh_process` | FI | the serialized artifact loads and predicts equally in a new interpreter |
| `artifact.portable_paths` | FI | no current cwd or tempdir string in the artifact bytes (see below) |
| `repro.predict_seeded` | FI | two predicts with `rng_factory(seed)` are equal within `atol` |
| `repro.train_seeded` | FI | two trainings with the case seed predict equally (needs `train_case`) |
| `repro.train_byte_equal` | PROFILE | opt-in (`artifact_determinism=ArtifactDeterminism.BYTE_EQUAL`): two trainings serialize to identical bytes; absent from the report when off |

Each check is isolated: a failure or crash in one does not hide the others. If
`protocol.methods` or `protocol.signatures` fails, checks that would call the
model are `NOT_TESTED` (calling a mis-shaped model only produces misleading
crashes). Model code that raises is recorded, never propagated from
`run_conformance`.

### Output versus requirement

`output_requirement_mismatches(output, requirement, inputs, issue_datetime=...)`
returns one precise message per mismatch: output station set equals the input
station set (missing stations must be FAILURE entries, extras are errors);
every target present per station and no undeclared variables; unit equals the
declared unit; representations present are a subset of the declared ones;
aggregation and label agree where both are declared; origin agrees with the
anchor of the dynamic branch whose step equals the output `timedelta`; the
output `issue_datetime` equals the requested one. FAILURE-status variables are
only checked for presence. The requirement declares no output horizon or offset,
so those are not cross-checked (their internal consistency is already enforced
by the output validators), and an output step absent from `requirement.dynamic`
is allowed.

### Portability scan (heuristic)

The scan looks for the exact current working directory and temp directory
strings in the artifact bytes (both the fixture bytes and the re-serialized
bytes). Only those produce FAIL. A home directory, or anything shaped like
`/Users/<name>`, `/home/<name>` or `C:\Users\<name>`, produces a warning inside
a PASS. Compressed or encrypted payloads (zip, pickle protocol with
compression) are not inspected, so a PASS is evidence, not proof.

## Report and exit codes

`Report.to_text()` lists every result and a `NOT TESTED` section with reasons
such as "no fixture supplied". `Report.to_json()` emits a stable schema
(`report_schema_version` 1; keys `fi_version`, `summary`, `results[]` with
`check_id`, `status`, `layer`, `fault`, `message`, `remediation`, `warnings`).
Status values: `PASS`, `FAIL`, `NOT_TESTED`; layers: `FI`, `PROFILE`; faults:
`NONE`, `EXECUTION` (load failure, crash or timeout).

| Exit | Meaning |
|---|---|
| 0 | no FAIL (with `Strictness.STRICT` also no NOT_TESTED) |
| 1 | at least one FI-layer FAIL (under STRICT also any NOT_TESTED) |
| 2 | usage or specification error (`ConformanceUsageError`, raised before a report exists) |
| 3 | model or artifact failed to load, crashed or timed out |
| 4 | only PROFILE-layer FAIL |

When several apply the precedence is 3, then 1, then 4. PROFILE results report
deployment-profile expectations separately from FI conformance.

## SECURITY

Loading a model executes trusted code. For example aquacast artifacts use
`torch.load(weights_only=False)`, which runs arbitrary pickled code. The
checker imports and runs your model in-process, and re-loads the artifact in a
subprocess with a wall-clock timeout and, on POSIX, best-effort `RLIMIT_CPU` /
`RLIMIT_AS` limits (some platforms, such as macOS, do not honour the address
space limit). These limits are NOT a sandbox: nothing restricts the
filesystem, network or syscalls, and in-process model calls are not time
limited. The checker does not make untrusted checkpoints safe. Run it only on
code and artifacts you trust, preferably in a container or a throwaway virtual
environment with no network access.

## Not yet included

Provenance record checks (artifact, config and manifest binding) and the
`fi-check` command line interface are added in later steps.
