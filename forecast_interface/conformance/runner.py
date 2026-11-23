import inspect
import logging
import random
import re
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import NamedTuple, TypeVar

from forecast_interface import __version__
from forecast_interface.input import InputRequirement, ModelInputs
from forecast_interface.interface import (
    ArtifactScope,
    BatchHindcastModel,
    ForecastModel,
    GridDeclaringArtifact,
    ModelFailure,
    ModelResult,
    ModelSuccess,
    RetrainableModel,
    TrainedArtifact,
    artifact_training_grid,
)
from forecast_interface.common import Unknown
from forecast_interface.output import VariableStatus

from ._canonical import canonical, differences
from ._subprocess import (
    ReloadKind,
    ReloadRunner,
    SubprocessLimits,
    run_fresh_reload,
)
from .errors import ConformanceUsageError
from .fixtures import (
    BadCase,
    Fixtures,
    HasBadCases,
    HasTrainCase,
    HasUnknownStationCase,
    TrainCase,
)
from .report import CheckId, CheckResult, Fault, Layer, Report, Status
from .requirement_match import output_requirement_mismatches

logger = logging.getLogger(__name__)

T = TypeVar("T")

SHORT_HISTORY_CASE = "short_history"
MISSING_DATA_CASE = "missing_data"


class ArtifactDeterminism(StrEnum):
    OFF = "off"
    BYTE_EQUAL = "byte_equal"


class PathProbe(NamedTuple):
    cwd: str
    tempdir: str
    home: str

    @classmethod
    def current(cls) -> "PathProbe":
        return cls(str(Path.cwd()), tempfile.gettempdir(), str(Path.home()))


class Raised(NamedTuple):
    detail: str


def _try(fn: Callable[[], T]) -> T | Raised:
    try:
        return fn()
    except Exception as exc:  # model/fixture code is untrusted: record, never propagate
        logger.debug("call raised", exc_info=True)
        return Raised(f"{type(exc).__name__}: {exc}")


_REQUIRED_METHODS = (
    "train",
    "predict",
    "serialize_artifact",
    "deserialize_artifact",
)

# method -> (number of leading positional params, required keyword-only names)
_SIGNATURES: Mapping[str, tuple[int, frozenset[str]]] = {
    "train": (1, frozenset({"config", "rng"})),
    "predict": (1, frozenset({"inputs", "issue_datetime", "rng"})),
    "serialize_artifact": (1, frozenset()),
    "deserialize_artifact": (1, frozenset()),
    "retrain": (2, frozenset({"config", "rng"})),
    "hindcast": (1, frozenset({"inputs", "issue_datetimes", "rng"})),
}

_HOME_LIKE = re.compile(
    rb"(?:/Users|/home)/[A-Za-z0-9_.-]+|[A-Za-z]:\\+Users\\+[^\\\s]+"
)


def signature_problems(method: Callable[..., object], name: str) -> list[str]:
    n_positional, keyword_only = _SIGNATURES[name]
    params = list(inspect.signature(method).parameters.values())
    positional = [
        p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    has_var_kw = any(p.kind is p.VAR_KEYWORD for p in params)
    has_var_pos = any(p.kind is p.VAR_POSITIONAL for p in params)
    by_name = {p.name: p for p in params}
    problems: list[str] = []
    if len(positional) < n_positional and not has_var_pos:
        problems.append(
            f"{name}: expected {n_positional} leading positional parameter(s)"
        )
    for kw in sorted(keyword_only):
        param = by_name.get(kw)
        if param is None and not has_var_kw:
            problems.append(f"{name}: missing keyword-only parameter {kw!r}")
        elif param is not None and param.kind is not param.KEYWORD_ONLY:
            problems.append(f"{name}: parameter {kw!r} must be keyword-only")
    allowed = {p.name for p in positional[:n_positional]} | keyword_only
    problems.extend(
        f"{name}: unexpected required parameter {p.name!r}"
        for p in params
        if p.default is p.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        and p.name not in allowed
    )
    return problems


def _ok(
    check: CheckId,
    message: str,
    *,
    layer: Layer = Layer.FI,
    warnings: tuple[str, ...] = (),
) -> CheckResult:
    return CheckResult(check, Status.PASS, layer, message, warnings=warnings)


def _fail(
    check: CheckId,
    message: str,
    remediation: str,
    *,
    layer: Layer = Layer.FI,
    fault: Fault = Fault.NONE,
) -> CheckResult:
    return CheckResult(check, Status.FAIL, layer, message, remediation, fault)


def _skip(check: CheckId, reason: str, *, layer: Layer = Layer.FI) -> CheckResult:
    return CheckResult(check, Status.NOT_TESTED, layer, reason)


def _crash(
    check: CheckId, what: str, detail: str, *, layer: Layer = Layer.FI
) -> CheckResult:
    return _fail(
        check,
        f"{what}: {detail}",
        "model code must not raise on conforming inputs; fix the model or fixtures",
        layer=layer,
        fault=Fault.EXECUTION,
    )


def _first(items: list[str], limit: int = 5) -> str:
    more = f" (+{len(items) - limit} more)" if len(items) > limit else ""
    return "; ".join(items[:limit]) + more


class _Context:
    def __init__(
        self,
        fixtures: Fixtures,
        model: ForecastModel,
        *,
        seed: int,
        rng_factory: Callable[[int], random.Random],
        atol: float,
    ) -> None:
        self.fixtures = fixtures
        self.model = model
        self.seed = seed
        self.rng_factory = rng_factory
        self.atol = atol
        self.inputs: ModelInputs
        self.issue: datetime
        fixture_inputs = _try(fixtures.predict_inputs)
        if isinstance(fixture_inputs, Raised):
            raise ConformanceUsageError(
                f"fixtures.predict_inputs() raised {fixture_inputs.detail}"
            )
        self.inputs, self.issue = fixture_inputs
        raw = _try(fixtures.artifact_bytes)
        if isinstance(raw, Raised):
            raise ConformanceUsageError(
                f"fixtures.artifact_bytes() raised {raw.detail}"
            )
        self.raw: bytes | None = raw

    @cached_property
    def train_case(self) -> TrainCase | None:
        if not isinstance(self.fixtures, HasTrainCase):
            return None
        case = _try(self.fixtures.train_case)
        if isinstance(case, Raised):
            raise ConformanceUsageError(f"fixtures.train_case() raised {case.detail}")
        return case

    @cached_property
    def bad_cases(self) -> Mapping[str, BadCase]:
        if not isinstance(self.fixtures, HasBadCases):
            return {}
        cases = _try(self.fixtures.bad_cases)
        if isinstance(cases, Raised):
            raise ConformanceUsageError(f"fixtures.bad_cases() raised {cases.detail}")
        return cases

    @cached_property
    def requirement(self) -> InputRequirement:
        return self.model.input_requirement

    def predict(
        self, artifact: TrainedArtifact, inputs: ModelInputs | None = None
    ) -> ModelResult | Raised:
        return _try(
            lambda: self.model.predict(
                artifact,
                inputs=inputs if inputs is not None else self.inputs,
                issue_datetime=self.issue,
                rng=self.rng_factory(self.seed),
            )
        )

    @cached_property
    def artifact(self) -> TrainedArtifact | Raised | None:
        if self.raw is not None:
            return _try(lambda: self.model.deserialize_artifact(self.raw or b""))
        case = self.train_case
        if case is None:
            return None
        return _try(
            lambda: self.model.train(
                case.inputs, config=case.config, rng=self.rng_factory(case.seed)
            )
        )

    @cached_property
    def baseline(self) -> ModelResult | Raised | None:
        artifact = self.artifact
        if artifact is None or isinstance(artifact, Raised):
            return None
        return self.predict(artifact)

    @cached_property
    def reserialized(self) -> bytes | Raised | None:
        artifact = self.artifact
        if artifact is None or isinstance(artifact, Raised):
            return None
        raw = _try(lambda: self.model.serialize_artifact(artifact))
        if isinstance(raw, Raised) or isinstance(raw, bytes):
            return raw
        return Raised(f"serialize_artifact returned {type(raw).__name__}, not bytes")

    def blocked(
        self, check: CheckId, *, needs_baseline: bool = False
    ) -> CheckResult | None:
        artifact = self.artifact
        if artifact is None:
            return _skip(
                check, "no fixture supplied: artifact_bytes() is None and no train_case"
            )
        if isinstance(artifact, Raised):
            if check is CheckId.ARTIFACT_ROUNDTRIP:
                return _crash(check, "artifact failed to load", artifact.detail)
            return _skip(check, "artifact failed to load (see artifact.roundtrip)")
        if needs_baseline and isinstance(self.baseline, Raised):
            if check is CheckId.OUTPUT_MATCHES_REQUIREMENT:
                return _crash(
                    check, "predict raised on conforming inputs", self.baseline.detail
                )
            return _skip(
                check, "baseline predict raised (see output.matches_requirement)"
            )
        return None


def _check_methods(ctx: _Context) -> CheckResult:
    check = CheckId.PROTOCOL_METHODS
    model = ctx.model
    if not isinstance(model, ForecastModel):
        missing = [
            m for m in _REQUIRED_METHODS if not callable(getattr(model, m, None))
        ]
        missing += [
            a for a in ("input_requirement", "artifact_scope") if not hasattr(model, a)
        ]
        return _fail(
            check,
            f"not a ForecastModel; missing: {missing}",
            "implement the members of forecast_interface.interface.ForecastModel",
        )
    if not isinstance(ctx.requirement, InputRequirement):
        return _fail(
            check,
            f"input_requirement is {type(ctx.requirement).__name__}, not InputRequirement",
            "return an InputRequirement from the input_requirement property",
        )
    return _ok(
        check, "implements ForecastModel; input_requirement is an InputRequirement"
    )


def _check_signatures(ctx: _Context) -> CheckResult:
    check = CheckId.PROTOCOL_SIGNATURES
    names = list(_REQUIRED_METHODS) + [
        n for n in ("retrain", "hindcast") if callable(getattr(ctx.model, n, None))
    ]
    problems = [p for n in names for p in signature_problems(getattr(ctx.model, n), n)]
    if problems:
        return _fail(
            check,
            _first(problems),
            "match the keyword-only signatures declared in forecast_interface.interface",
        )
    return _ok(check, f"signatures match for {names}")


def _check_scope(ctx: _Context) -> CheckResult:
    scope = ctx.model.artifact_scope
    if isinstance(scope, ArtifactScope):
        return _ok(CheckId.PROTOCOL_SCOPE, f"artifact_scope is {scope.name}")
    return _fail(
        CheckId.PROTOCOL_SCOPE,
        f"artifact_scope is {scope!r}, not an ArtifactScope",
        "set artifact_scope to ArtifactScope.STATION or ArtifactScope.GROUP",
    )


def _declared(ctx: _Context) -> list[str]:
    declared = [
        name
        for name, protocol in (
            ("RetrainableModel", RetrainableModel),
            ("BatchHindcastModel", BatchHindcastModel),
        )
        if isinstance(ctx.model, protocol)
    ]
    artifact = ctx.artifact
    if (
        artifact is not None
        and not isinstance(artifact, Raised)
        and isinstance(artifact, GridDeclaringArtifact)
        and artifact_training_grid(artifact).grid is not Unknown.UNKNOWN
    ):
        declared.append("GridDeclaringArtifact")
    return declared


def _check_declared(ctx: _Context) -> CheckResult:
    declared = _declared(ctx)
    return _ok(
        CheckId.CAPABILITIES_DECLARED,
        f"declared optional capabilities: {declared or 'none'}",
    )


def _check_retrain(ctx: _Context) -> CheckResult:
    check = CheckId.CAPABILITIES_RETRAIN
    case = ctx.train_case
    if case is None:
        return _skip(check, "no fixture supplied: train_case() is None")
    if (blocked := ctx.blocked(check)) is not None:
        return blocked
    base = ctx.artifact
    assert base is not None and not isinstance(base, Raised)
    model = ctx.model
    assert isinstance(model, RetrainableModel)
    retrained = _try(
        lambda: model.retrain(
            base, case.inputs, config=case.config, rng=ctx.rng_factory(case.seed)
        )
    )
    if isinstance(retrained, Raised):
        return _crash(check, "retrain raised", retrained.detail)
    serialized = _try(lambda: model.serialize_artifact(retrained))
    if isinstance(serialized, Raised) or not isinstance(serialized, bytes):
        return _fail(
            check,
            f"retrained artifact does not serialize to bytes: {serialized!r}",
            "retrain must return a TrainedArtifact accepted by serialize_artifact",
        )
    return _ok(check, "retrain returned an artifact that serializes")


def _check_hindcast(ctx: _Context) -> CheckResult:
    check = CheckId.CAPABILITIES_HINDCAST
    if (blocked := ctx.blocked(check)) is not None:
        return blocked
    artifact = ctx.artifact
    assert artifact is not None and not isinstance(artifact, Raised)
    model = ctx.model
    assert isinstance(model, BatchHindcastModel)
    result = _try(
        lambda: model.hindcast(
            artifact,
            inputs=ctx.inputs,
            issue_datetimes=[ctx.issue],
            rng=ctx.rng_factory(ctx.seed),
        )
    )
    if isinstance(result, Raised):
        return _crash(check, "hindcast raised", result.detail)
    if not isinstance(result, (ModelSuccess, ModelFailure)):
        return _fail(
            check,
            f"hindcast returned {type(result).__name__}, not a ModelResult",
            "return ModelSuccess or ModelFailure",
        )
    return _ok(check, f"hindcast returned a {type(result).__name__}")


def _check_output(ctx: _Context) -> CheckResult:
    check = CheckId.OUTPUT_MATCHES_REQUIREMENT
    if (blocked := ctx.blocked(check, needs_baseline=True)) is not None:
        return blocked
    result = ctx.baseline
    assert result is not None and not isinstance(result, Raised)
    if isinstance(result, ModelFailure):
        return _fail(
            check,
            f"predict on the conforming fixture returned ModelFailure "
            f"({result.cause.name}): {result.message}",
            "the predict_inputs fixture must be a case the model can forecast",
        )
    mismatches = output_requirement_mismatches(
        result.output, ctx.requirement, ctx.inputs, issue_datetime=ctx.issue
    )
    if mismatches:
        return _fail(
            check,
            _first(mismatches),
            "align the output metadata and stations with input_requirement",
        )
    return _ok(check, "output matches the declared requirement and station set")


def _bad_case_problem(ctx: _Context, case: BadCase) -> str | None:
    artifact = ctx.artifact
    assert artifact is not None and not isinstance(artifact, Raised)
    result = ctx.predict(artifact, case.inputs)
    match result:
        case Raised(detail):
            return f"raised instead of returning ModelFailure ({detail})"
        case ModelSuccess():
            return "returned a ModelSuccess for a bad input"
        case ModelFailure(cause=cause) if cause is not case.expected_cause:
            return f"cause {cause.name}, expected {case.expected_cause.name}"
        case _:
            return None


def _check_named_case(ctx: _Context, check: CheckId, name: str) -> CheckResult:
    case = ctx.bad_cases.get(name)
    if case is None:
        return _skip(check, f"no fixture supplied: bad_cases() has no {name!r} case")
    if (blocked := ctx.blocked(check)) is not None:
        return blocked
    problem = _bad_case_problem(ctx, case)
    if problem is not None:
        return _fail(
            check,
            f"{name}: {problem}",
            "return ModelFailure(cause=...) for unusable inputs; never raise",
        )
    return _ok(check, f"{name}: returned ModelFailure({case.expected_cause.name})")


def _check_failures(ctx: _Context) -> CheckResult:
    check = CheckId.FAILURE_RETURNED_NOT_RAISED
    special = {SHORT_HISTORY_CASE, MISSING_DATA_CASE}
    cases = {k: v for k, v in ctx.bad_cases.items() if k not in special}
    if not cases:
        return _skip(
            check,
            "no fixture supplied: bad_cases() has no cases beyond the named input checks",
        )
    if (blocked := ctx.blocked(check)) is not None:
        return blocked
    problems = [
        f"{name}: {problem}"
        for name, case in cases.items()
        if (problem := _bad_case_problem(ctx, case)) is not None
    ]
    if problems:
        return _fail(
            check,
            _first(problems),
            "return ModelFailure(cause=...) for unusable inputs; never raise",
        )
    return _ok(check, f"{len(cases)} bad case(s) returned the expected ModelFailure")


def _check_unknown_station(ctx: _Context) -> CheckResult:
    check = CheckId.STATION_UNKNOWN
    fixtures = ctx.fixtures
    case = (
        fixtures.unknown_station_case()
        if isinstance(fixtures, HasUnknownStationCase)
        else None
    )
    if case is None:
        return _skip(check, "no fixture supplied: unknown_station_case() is None")
    if (blocked := ctx.blocked(check)) is not None:
        return blocked
    artifact = ctx.artifact
    assert artifact is not None and not isinstance(artifact, Raised)
    result = ctx.predict(artifact, case.inputs)
    remediation = (
        "return ModelFailure, or mark the unknown station with FAILURE entries; "
        "never forecast a station the artifact was not trained for"
    )
    match result:
        case Raised(detail):
            return _fail(check, f"raised on unknown station ({detail})", remediation)
        case ModelFailure():
            return _ok(check, f"returned ModelFailure({result.cause.name})")
        case ModelSuccess(output=output):
            entries = output.variables.get(case.unknown_station)
            if entries is None:
                return _fail(
                    check,
                    f"station {case.unknown_station!r} is absent from the output "
                    "instead of an explicit FAILURE entry",
                    remediation,
                )
            if any(v.status is not VariableStatus.FAILURE for v in entries.values()):
                return _fail(
                    check,
                    f"a prediction was produced for unknown station {case.unknown_station!r}",
                    remediation,
                )
            return _ok(check, "unknown station reported with explicit FAILURE entries")
    raise AssertionError("unreachable")


def _scan_paths(raw: bytes, probe: PathProbe) -> tuple[list[str], list[str]]:
    exact = {probe.cwd, str(Path(probe.cwd).resolve()), probe.tempdir}
    found = sorted(p for p in exact if len(p) > 1 and p.encode() in raw)
    warnings = (
        [f"contains home directory {probe.home!r}"]
        if len(probe.home) > 1 and probe.home.encode() in raw
        else []
    )
    warnings += [
        f"contains a home-like absolute path: {m.decode(errors='replace')!r}"
        for m in sorted(set(_HOME_LIKE.findall(raw)))[:3]
    ]
    return found, warnings


def _check_paths(ctx: _Context, probe: PathProbe) -> CheckResult:
    check = CheckId.ARTIFACT_PORTABLE_PATHS
    candidates = [raw for raw in (ctx.raw, ctx.reserialized) if isinstance(raw, bytes)]
    if not candidates:
        return _skip(check, "no fixture supplied: no artifact bytes to scan")
    scans = [_scan_paths(raw, probe) for raw in candidates]
    found = sorted({p for f, _ in scans for p in f})
    warnings = tuple(dict.fromkeys(w for _, ws in scans for w in ws))
    if found:
        return _fail(
            check,
            f"serialized artifact embeds absolute path(s): {found}",
            "store only relative or logical names in the artifact bytes",
        )
    return _ok(
        check,
        "no current cwd/tempdir path found (heuristic; compressed payloads are not inspected)",
        warnings=warnings,
    )


def _compare(ctx: _Context, left: ModelResult, right: ModelResult) -> list[str]:
    return differences(canonical(left), canonical(right), ctx.atol)


def _check_roundtrip(ctx: _Context) -> CheckResult:
    check = CheckId.ARTIFACT_ROUNDTRIP
    if (blocked := ctx.blocked(check, needs_baseline=True)) is not None:
        return blocked
    raw = ctx.reserialized
    if isinstance(raw, Raised):
        return _crash(check, "serialize_artifact failed", raw.detail)
    assert raw is not None
    restored = _try(lambda: ctx.model.deserialize_artifact(raw))
    if isinstance(restored, Raised):
        return _crash(
            check, "deserialize_artifact failed on its own output", restored.detail
        )
    again = ctx.predict(restored)
    baseline = ctx.baseline
    assert baseline is not None and not isinstance(baseline, Raised)
    if isinstance(again, Raised):
        return _crash(check, "predict raised after round trip", again.detail)
    diffs = _compare(ctx, baseline, again)
    if diffs:
        return _fail(
            check,
            f"predict differs after serialize/deserialize: {_first(diffs)}",
            "serialize all state that predict depends on (weights, scalers, config)",
        )
    return _ok(check, f"round trip reproduces predictions within atol={ctx.atol}")


def _check_fresh_process(
    ctx: _Context,
    fixtures_spec: str | None,
    runner: ReloadRunner,
    limits: SubprocessLimits,
) -> CheckResult:
    check = CheckId.ARTIFACT_RELOAD_FRESH_PROCESS
    if fixtures_spec is None:
        return _skip(
            check,
            "no fixture supplied: no importable fixtures spec ('module:callable')",
        )
    if (blocked := ctx.blocked(check, needs_baseline=True)) is not None:
        return blocked
    raw = ctx.reserialized
    baseline = ctx.baseline
    if not isinstance(raw, bytes):
        return _skip(check, "artifact could not be serialized (see artifact.roundtrip)")
    assert baseline is not None and not isinstance(baseline, Raised)
    outcome = runner(
        fixtures_spec=fixtures_spec, artifact=raw, seed=ctx.seed, limits=limits
    )
    if outcome.kind is not ReloadKind.OK or outcome.result is None:
        tail = (
            f" | stderr: {outcome.stderr.strip()[-300:]}"
            if outcome.stderr.strip()
            else ""
        )
        return _fail(
            check,
            f"fresh process {outcome.kind.value}: {outcome.detail}{tail}",
            "the artifact must load and predict in a new interpreter with no training state",
            fault=Fault.EXECUTION,
        )
    diffs = differences(canonical(baseline), outcome.result, ctx.atol)
    if diffs:
        return _fail(
            check,
            f"fresh-process predict differs: {_first(diffs)}",
            "do not rely on in-process state (globals, caches, training-time objects)",
        )
    return _ok(check, "fresh interpreter reproduces predictions")


def _check_predict_seeded(ctx: _Context) -> CheckResult:
    check = CheckId.REPRO_PREDICT_SEEDED
    if (blocked := ctx.blocked(check, needs_baseline=True)) is not None:
        return blocked
    artifact = ctx.artifact
    baseline = ctx.baseline
    assert artifact is not None and not isinstance(artifact, Raised)
    assert baseline is not None and not isinstance(baseline, Raised)
    second = ctx.predict(artifact)
    if isinstance(second, Raised):
        return _crash(check, "second predict raised", second.detail)
    diffs = _compare(ctx, baseline, second)
    if diffs:
        return _fail(
            check,
            f"two seeded predicts differ: {_first(diffs)}",
            "draw all randomness from the injected rng",
        )
    return _ok(check, "two predicts with the same seed are equal")


def _train_twice(
    ctx: _Context, case: TrainCase
) -> tuple[TrainedArtifact, TrainedArtifact] | Raised:
    runs = [
        _try(
            lambda: ctx.model.train(
                case.inputs, config=case.config, rng=ctx.rng_factory(case.seed)
            )
        )
        for _ in range(2)
    ]
    first, second = runs
    if isinstance(first, Raised):
        return first
    if isinstance(second, Raised):
        return second
    return first, second


def _check_train_seeded(ctx: _Context) -> CheckResult:
    check = CheckId.REPRO_TRAIN_SEEDED
    case = ctx.train_case
    if case is None:
        return _skip(check, "no fixture supplied: train_case() is None")
    trained = _train_twice(ctx, case)
    if isinstance(trained, Raised):
        return _crash(check, "train raised", trained.detail)
    results = [ctx.predict(a) for a in trained]
    first, second = results
    if isinstance(first, Raised) or isinstance(second, Raised):
        raised = first if isinstance(first, Raised) else second
        assert isinstance(raised, Raised)
        return _crash(check, "predict on a trained artifact raised", raised.detail)
    diffs = _compare(ctx, first, second)
    if diffs:
        return _fail(
            check,
            f"two seeded trainings predict differently: {_first(diffs)}",
            "draw all training randomness from the injected rng",
        )
    return _ok(check, "two seeded trainings give equal predictions")


def _check_byte_equal(ctx: _Context) -> CheckResult:
    check = CheckId.REPRO_TRAIN_BYTE_EQUAL
    case = ctx.train_case
    if case is None:
        return _skip(
            check, "no fixture supplied: train_case() is None", layer=Layer.PROFILE
        )
    trained = _train_twice(ctx, case)
    if isinstance(trained, Raised):
        return _crash(check, "train raised", trained.detail, layer=Layer.PROFILE)
    raws = [_try(lambda: ctx.model.serialize_artifact(a)) for a in trained]
    if any(isinstance(r, Raised) for r in raws):
        return _crash(
            check, "serialize_artifact raised", str(raws), layer=Layer.PROFILE
        )
    if raws[0] != raws[1]:
        return _fail(
            check,
            "two seeded trainings serialize to different bytes",
            "make serialization deterministic (sorted keys, no timestamps)",
            layer=Layer.PROFILE,
        )
    return _ok(
        check, "seeded trainings serialize to identical bytes", layer=Layer.PROFILE
    )


_ALL_CHECKS = tuple(CheckId)


def run_conformance(
    fixtures: Fixtures,
    *,
    seed: int,
    rng_factory: Callable[[int], random.Random] = random.Random,
    timeout: timedelta = timedelta(seconds=300),
    atol: float = 1e-9,
    fixtures_spec: str | None = None,
    artifact_determinism: ArtifactDeterminism = ArtifactDeterminism.OFF,
    address_space_bytes: int | None = None,
    reload_runner: ReloadRunner = run_fresh_reload,
    paths: PathProbe | None = None,
) -> Report:
    """Run the checks; model bugs are recorded in the report, never raised.

    ``timeout`` and ``address_space_bytes`` bound only the fresh-process reload;
    in-process model calls are not interruptible. Raises
    ``ConformanceUsageError`` for invalid options or fixtures.
    """
    if seed < 0:
        raise ConformanceUsageError(f"seed must be non-negative, got {seed}")
    if atol < 0:
        raise ConformanceUsageError(f"atol must be non-negative, got {atol}")
    if timeout <= timedelta(0):
        raise ConformanceUsageError(f"timeout must be positive, got {timeout}")
    if fixtures_spec is not None and ":" not in fixtures_spec:
        raise ConformanceUsageError(
            f"fixtures_spec must look like 'package.module:callable', got {fixtures_spec!r}"
        )
    if not isinstance(fixtures, Fixtures):
        raise ConformanceUsageError(
            "fixtures must implement model_factory, artifact_bytes and predict_inputs"
        )
    model = _try(fixtures.model_factory)
    if isinstance(model, Raised):
        crash = _crash(CheckId.PROTOCOL_METHODS, "model_factory raised", model.detail)
        rest = [
            _skip(c, "model could not be constructed", layer=_layer(c))
            for c in _ALL_CHECKS
            if c is not CheckId.PROTOCOL_METHODS
        ]
        return Report((crash, *rest), __version__)
    ctx = _Context(fixtures, model, seed=seed, rng_factory=rng_factory, atol=atol)
    limits = SubprocessLimits(timeout, address_space_bytes=address_space_bytes)
    probe = paths if paths is not None else PathProbe.current()

    def guarded(check: CheckId, fn: Callable[[], CheckResult]) -> CheckResult:
        outcome = _try(fn)
        if isinstance(outcome, Raised):
            return _crash(check, "check crashed", outcome.detail, layer=_layer(check))
        return outcome

    structural = [
        guarded(CheckId.PROTOCOL_METHODS, lambda: _check_methods(ctx)),
    ]
    methods_ok = structural[0].status is Status.PASS
    if methods_ok:
        structural.append(
            guarded(CheckId.PROTOCOL_SIGNATURES, lambda: _check_signatures(ctx))
        )
        structural.append(guarded(CheckId.PROTOCOL_SCOPE, lambda: _check_scope(ctx)))
    callable_ok = methods_ok and structural[1].status is Status.PASS
    reason = (
        "protocol.methods failed" if not methods_ok else "protocol.signatures failed"
    )

    exercised: list[tuple[CheckId, Callable[[], CheckResult]]] = [
        (CheckId.CAPABILITIES_DECLARED, lambda: _check_declared(ctx)),
        (CheckId.OUTPUT_MATCHES_REQUIREMENT, lambda: _check_output(ctx)),
        (CheckId.FAILURE_RETURNED_NOT_RAISED, lambda: _check_failures(ctx)),
        (
            CheckId.INPUT_SHORT_HISTORY,
            lambda: _check_named_case(
                ctx, CheckId.INPUT_SHORT_HISTORY, SHORT_HISTORY_CASE
            ),
        ),
        (
            CheckId.INPUT_MISSING_DATA,
            lambda: _check_named_case(
                ctx, CheckId.INPUT_MISSING_DATA, MISSING_DATA_CASE
            ),
        ),
        (CheckId.STATION_UNKNOWN, lambda: _check_unknown_station(ctx)),
        (CheckId.ARTIFACT_ROUNDTRIP, lambda: _check_roundtrip(ctx)),
        (
            CheckId.ARTIFACT_RELOAD_FRESH_PROCESS,
            lambda: _check_fresh_process(ctx, fixtures_spec, reload_runner, limits),
        ),
        (CheckId.ARTIFACT_PORTABLE_PATHS, lambda: _check_paths(ctx, probe)),
        (CheckId.REPRO_PREDICT_SEEDED, lambda: _check_predict_seeded(ctx)),
        (CheckId.REPRO_TRAIN_SEEDED, lambda: _check_train_seeded(ctx)),
    ]
    if isinstance(model, RetrainableModel):
        exercised.append((CheckId.CAPABILITIES_RETRAIN, lambda: _check_retrain(ctx)))
    if isinstance(model, BatchHindcastModel):
        exercised.append((CheckId.CAPABILITIES_HINDCAST, lambda: _check_hindcast(ctx)))
    if artifact_determinism is ArtifactDeterminism.BYTE_EQUAL:
        exercised.append(
            (CheckId.REPRO_TRAIN_BYTE_EQUAL, lambda: _check_byte_equal(ctx))
        )

    later = [
        guarded(check, fn)
        if callable_ok
        else _skip(
            check, f"{reason}; model calls were not attempted", layer=_layer(check)
        )
        for check, fn in exercised
    ]
    order = {check: i for i, check in enumerate(_ALL_CHECKS)}
    results = sorted([*structural, *later], key=lambda r: order[r.check_id])
    return Report(tuple(results), __version__)


def _layer(check: CheckId) -> Layer:
    return Layer.PROFILE if check is CheckId.REPRO_TRAIN_BYTE_EQUAL else Layer.FI
