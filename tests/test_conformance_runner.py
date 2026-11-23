from collections.abc import Mapping, Sequence
from datetime import datetime
from itertools import count
from random import Random
from typing import Any

import pytest

from forecast_interface.common import Unit
from forecast_interface.conformance import (
    ArtifactDeterminism,
    BadCase,
    CheckId,
    CheckResult,
    ConformanceUsageError,
    ExitCode,
    Fault,
    Layer,
    PathProbe,
    ReloadKind,
    ReloadOutcome,
    Report,
    Status,
    Strictness,
    SubprocessLimits,
    run_conformance,
)
from forecast_interface.conformance._canonical import canonical
from forecast_interface.input import ModelInputs
from forecast_interface.interface import (
    FailureCause,
    ForecastModel,
    ModelResult,
    TrainedArtifact,
)
from tests.conformance_fakes import (
    ISSUE,
    FakeArtifact,
    FakeModel,
    FullFixtures,
    MinimalFixtures,
    UnknownPolicy,
    make_inputs,
)

PROBE = PathProbe("/work/project", "/tmp", "/home/me")


def _run(fixtures: MinimalFixtures, **kwargs: Any) -> Report:
    kwargs.setdefault("seed", 1)
    kwargs.setdefault("paths", PROBE)
    return run_conformance(fixtures, **kwargs)


def _by_id(report: Report) -> dict[CheckId, CheckResult]:
    return {r.check_id: r for r in report.results}


class _FakeRunner:
    def __init__(self, outcome: ReloadOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def __call__(
        self,
        *,
        fixtures_spec: str,
        artifact: bytes,
        seed: int,
        limits: SubprocessLimits,
    ) -> ReloadOutcome:
        self.calls += 1
        return self.outcome


class TestConformingModel:
    def test_no_failures_and_fresh_process_not_tested_without_spec(self) -> None:
        report = _run(FullFixtures())

        by_id = _by_id(report)
        assert report.count(Status.FAIL) == 0
        assert by_id[CheckId.ARTIFACT_RELOAD_FRESH_PROCESS].status is Status.NOT_TESTED
        assert report.exit_code() is ExitCode.OK

    def test_every_check_passes_including_real_fresh_process(self) -> None:
        report = _run(
            FullFixtures(), fixtures_spec="tests.conformance_fakes:make_fixtures"
        )

        failing = [r for r in report.results if r.status is not Status.PASS]
        assert failing == []

    def test_fake_runner_receives_reserialized_artifact_and_seed(self) -> None:
        model = FakeModel()
        expected = model.predict(
            FakeArtifact(("A", "B")),
            inputs=make_inputs(),
            issue_datetime=ISSUE,
            rng=Random(1),
        )
        runner = _FakeRunner(ReloadOutcome(ReloadKind.OK, canonical(expected)))

        report = _run(FullFixtures(), fixtures_spec="m:f", reload_runner=runner)

        assert runner.calls == 1
        assert (
            _by_id(report)[CheckId.ARTIFACT_RELOAD_FRESH_PROCESS].status is Status.PASS
        )


class TestMissingFixtures:
    def test_everything_unsupplied_is_not_tested_with_reason(self) -> None:
        report = _run(MinimalFixtures())

        by_id = _by_id(report)
        for check in (
            CheckId.OUTPUT_MATCHES_REQUIREMENT,
            CheckId.ARTIFACT_ROUNDTRIP,
            CheckId.REPRO_PREDICT_SEEDED,
            CheckId.REPRO_TRAIN_SEEDED,
            CheckId.INPUT_SHORT_HISTORY,
            CheckId.STATION_UNKNOWN,
        ):
            assert by_id[check].status is Status.NOT_TESTED
            assert "no fixture supplied" in by_id[check].message

    def test_strict_exit_code_rejects_not_tested(self) -> None:
        report = _run(MinimalFixtures())

        assert report.exit_code(Strictness.LENIENT) is ExitCode.OK
        assert report.exit_code(Strictness.STRICT) is ExitCode.FI_FAILURE

    def test_train_case_alone_supplies_the_artifact(self) -> None:
        class _TrainOnly(MinimalFixtures):
            def train_case(self) -> Any:
                return FullFixtures().train_case()

        report = _run(_TrainOnly())

        assert _by_id(report)[CheckId.OUTPUT_MATCHES_REQUIREMENT].status is Status.PASS


class TestProtocolChecks:
    def test_wrong_signature_fails_and_blocks_model_calls(self) -> None:
        class _Positional(FakeModel):
            def predict(
                self,
                artifact: TrainedArtifact,
                inputs: ModelInputs,
                issue_datetime: datetime,
                rng: Random,
            ) -> ModelResult:
                raise AssertionError("must not be called")

        by_id = _by_id(_run(FullFixtures(_Positional())))

        result = by_id[CheckId.PROTOCOL_SIGNATURES]
        assert result.status is Status.FAIL
        assert "keyword-only" in result.message
        assert by_id[CheckId.OUTPUT_MATCHES_REQUIREMENT].status is Status.NOT_TESTED

    def test_object_without_methods_fails_protocol(self) -> None:
        class _Bare:
            pass

        fixtures = MinimalFixtures()
        fixtures.model = _Bare()  # type: ignore[assignment]

        by_id = _by_id(_run(fixtures))

        assert by_id[CheckId.PROTOCOL_METHODS].status is Status.FAIL
        assert "train" in by_id[CheckId.PROTOCOL_METHODS].message

    def test_non_enum_scope_fails(self) -> None:
        class _BadScope(FakeModel):
            artifact_scope = "group"  # type: ignore[assignment]

        fixtures = MinimalFixtures()
        fixtures.model = _BadScope()  # type: ignore[assignment]
        result = _by_id(_run(fixtures))[CheckId.PROTOCOL_SCOPE]

        assert result.status is Status.FAIL

    def test_declared_capabilities_are_reported_and_exercised(self) -> None:
        class _Full(FakeModel):
            def retrain(
                self,
                base_artifact: TrainedArtifact,
                inputs: ModelInputs,
                *,
                config: Mapping[str, Any],
                rng: Random,
            ) -> TrainedArtifact:
                return base_artifact

            def hindcast(
                self,
                artifact: TrainedArtifact,
                *,
                inputs: ModelInputs,
                issue_datetimes: Sequence[datetime],
                rng: Random,
            ) -> ModelResult:
                return self.predict(
                    artifact, inputs=inputs, issue_datetime=issue_datetimes[0], rng=rng
                )

        by_id = _by_id(_run(FullFixtures(_Full())))

        assert "RetrainableModel" in by_id[CheckId.CAPABILITIES_DECLARED].message
        assert by_id[CheckId.CAPABILITIES_RETRAIN].status is Status.PASS
        assert by_id[CheckId.CAPABILITIES_HINDCAST].status is Status.PASS


class TestModelBugsAreRecorded:
    def test_predict_raising_is_an_execution_failure_not_an_exception(self) -> None:
        class _Raises(FakeModel):
            raise_in_predict = True

        report = _run(FullFixtures(_Raises()))

        result = _by_id(report)[CheckId.OUTPUT_MATCHES_REQUIREMENT]
        assert result.status is Status.FAIL
        assert result.fault is Fault.EXECUTION
        assert "RuntimeError" in result.message
        assert report.exit_code() is ExitCode.EXECUTION

    def test_one_failing_check_does_not_hide_others(self) -> None:
        class _Raises(FakeModel):
            raise_in_predict = True

        by_id = _by_id(_run(FullFixtures(_Raises())))

        assert by_id[CheckId.PROTOCOL_SCOPE].status is Status.PASS
        assert by_id[CheckId.ARTIFACT_PORTABLE_PATHS].status is Status.PASS

    def test_model_factory_raising_is_exit_three(self) -> None:
        class _Fixtures(MinimalFixtures):
            def model_factory(self) -> ForecastModel:
                raise ImportError("torch missing")

        report = _run(_Fixtures())

        assert _by_id(report)[CheckId.PROTOCOL_METHODS].fault is Fault.EXECUTION
        assert report.exit_code() is ExitCode.EXECUTION
        assert len(report.results) == len(CheckId)

    def test_corrupt_artifact_bytes_are_a_load_failure(self) -> None:
        report = _run(MinimalFixtures(raw=b"not json"))

        result = _by_id(report)[CheckId.ARTIFACT_ROUNDTRIP]
        assert result.fault is Fault.EXECUTION
        assert "failed to load" in result.message
        assert report.exit_code() is ExitCode.EXECUTION


class TestOutputRequirement:
    def test_wrong_unit_fails(self) -> None:
        class _WrongUnit(FakeModel):
            unit = Unit.MM_PER_DAY

        result = _by_id(_run(FullFixtures(_WrongUnit())))[
            CheckId.OUTPUT_MATCHES_REQUIREMENT
        ]

        assert result.status is Status.FAIL
        assert "unit" in result.message

    def test_wrong_station_set_fails(self) -> None:
        class _Drops(FakeModel):
            drop_station = "B"

        result = _by_id(_run(FullFixtures(_Drops())))[
            CheckId.OUTPUT_MATCHES_REQUIREMENT
        ]

        assert result.status is Status.FAIL
        assert "missing" in result.message


class TestFailurePaths:
    def test_raise_on_bad_case_fails(self) -> None:
        class _Fixtures(FullFixtures):
            def bad_cases(self) -> Mapping[str, BadCase]:
                return {"x": BadCase(make_inputs(case="boom"), FailureCause.INPUT_DATA)}

        result = _by_id(_run(_Fixtures()))[CheckId.FAILURE_RETURNED_NOT_RAISED]

        assert result.status is Status.FAIL
        assert "raised" in result.message

    def test_wrong_cause_fails_named_case(self) -> None:
        class _Fixtures(FullFixtures):
            def bad_cases(self) -> Mapping[str, BadCase]:
                return {
                    "short_history": BadCase(
                        make_inputs(case="short_history"), FailureCause.RESOURCE
                    )
                }

        result = _by_id(_run(_Fixtures()))[CheckId.INPUT_SHORT_HISTORY]

        assert result.status is Status.FAIL
        assert "RESOURCE" in result.message

    def test_success_for_bad_input_fails(self) -> None:
        class _Fixtures(FullFixtures):
            def bad_cases(self) -> Mapping[str, BadCase]:
                return {"ok_data": BadCase(make_inputs(), FailureCause.INPUT_DATA)}

        result = _by_id(_run(_Fixtures()))[CheckId.FAILURE_RETURNED_NOT_RAISED]

        assert result.status is Status.FAIL
        assert "ModelSuccess" in result.message


class TestUnknownStation:
    def test_explicit_failure_entry_passes(self) -> None:
        result = _by_id(_run(FullFixtures()))[CheckId.STATION_UNKNOWN]

        assert result.status is Status.PASS

    def test_silent_prediction_for_unknown_station_fails(self) -> None:
        class _Silent(FakeModel):
            unknown_policy = UnknownPolicy.SILENT_PREDICTION

        result = _by_id(_run(FullFixtures(_Silent())))[CheckId.STATION_UNKNOWN]

        assert result.status is Status.FAIL
        assert "'Z'" in result.message

    def test_omitting_unknown_station_fails(self) -> None:
        class _Drops(FakeModel):
            drop_station = "Z"

        result = _by_id(_run(FullFixtures(_Drops())))[CheckId.STATION_UNKNOWN]

        assert result.status is Status.FAIL
        assert "absent" in result.message


class TestPortablePaths:
    def test_cwd_in_artifact_fails(self) -> None:
        result = _by_id(_run(FullFixtures(marker="/work/project/models/w.pt")))[
            CheckId.ARTIFACT_PORTABLE_PATHS
        ]

        assert result.status is Status.FAIL
        assert "/work/project" in result.message

    def test_home_directory_is_only_a_warning(self) -> None:
        result = _by_id(_run(FullFixtures(marker="/home/me/models/w.pt")))[
            CheckId.ARTIFACT_PORTABLE_PATHS
        ]

        assert result.status is Status.PASS
        assert any("/home/me" in w for w in result.warnings)

    def test_clean_artifact_passes_without_warnings(self) -> None:
        result = _by_id(_run(FullFixtures(marker="weights")))[
            CheckId.ARTIFACT_PORTABLE_PATHS
        ]

        assert (result.status, result.warnings) == (Status.PASS, ())


class TestReproducibility:
    def test_nondeterministic_predict_fails(self) -> None:
        class _Noisy(FakeModel):
            nondeterministic = True

        by_id = _by_id(_run(FullFixtures(_Noisy())))

        assert by_id[CheckId.REPRO_PREDICT_SEEDED].status is Status.FAIL
        assert by_id[CheckId.ARTIFACT_ROUNDTRIP].status is Status.FAIL

    def test_byte_equality_is_opt_in_and_profile_layer(self) -> None:
        counter = count()

        class _Stamped(FakeModel):
            def train(
                self, inputs: ModelInputs, *, config: Mapping[str, Any], rng: Random
            ) -> TrainedArtifact:
                return FakeArtifact(tuple(inputs.stations), str(next(counter)))

        off = _run(FullFixtures(_Stamped()))
        on = _run(
            FullFixtures(_Stamped()),
            artifact_determinism=ArtifactDeterminism.BYTE_EQUAL,
        )

        assert CheckId.REPRO_TRAIN_BYTE_EQUAL not in _by_id(off)
        result = _by_id(on)[CheckId.REPRO_TRAIN_BYTE_EQUAL]
        assert (result.status, result.layer) == (Status.FAIL, Layer.PROFILE)
        assert on.exit_code() is ExitCode.PROFILE_FAILURE


class TestFreshProcessOutcomes:
    @pytest.mark.parametrize("kind", [ReloadKind.TIMEOUT, ReloadKind.CRASHED])
    def test_timeout_and_crash_are_exit_three(self, kind: ReloadKind) -> None:
        runner = _FakeRunner(ReloadOutcome(kind, detail="boom", stderr="trace"))

        report = _run(FullFixtures(), fixtures_spec="m:f", reload_runner=runner)

        result = _by_id(report)[CheckId.ARTIFACT_RELOAD_FRESH_PROCESS]
        assert result.fault is Fault.EXECUTION
        assert "trace" in result.message
        assert report.exit_code() is ExitCode.EXECUTION

    def test_divergent_fresh_prediction_is_fi_failure(self) -> None:
        other = FakeModel().predict(
            FakeArtifact(("A", "B")),
            inputs=make_inputs(),
            issue_datetime=ISSUE,
            rng=Random(999),
        )
        runner = _FakeRunner(ReloadOutcome(ReloadKind.OK, canonical(other)))

        report = _run(FullFixtures(), fixtures_spec="m:f", reload_runner=runner)

        assert report.exit_code() is ExitCode.FI_FAILURE


class TestUsageErrors:
    @pytest.mark.parametrize(
        ("kwargs", "fragment"),
        [
            ({"seed": -1}, "seed"),
            ({"atol": -1.0}, "atol"),
            ({"fixtures_spec": "no_colon"}, "fixtures_spec"),
        ],
    )
    def test_invalid_options_raise(self, kwargs: dict[str, Any], fragment: str) -> None:
        with pytest.raises(ConformanceUsageError, match=fragment):
            _run(FullFixtures(), **kwargs)

    def test_object_without_fixture_methods_raises(self) -> None:
        with pytest.raises(ConformanceUsageError, match="model_factory"):
            run_conformance(object(), seed=1)  # type: ignore[arg-type]

    def test_raising_predict_inputs_fixture_raises(self) -> None:
        class _Broken(MinimalFixtures):
            def predict_inputs(self) -> tuple[ModelInputs, datetime]:
                raise OSError("missing data file")

        with pytest.raises(ConformanceUsageError, match="predict_inputs"):
            _run(_Broken())
