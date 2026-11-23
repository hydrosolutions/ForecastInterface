from datetime import timedelta

from forecast_interface.conformance import (
    ReloadKind,
    SubprocessLimits,
    run_fresh_reload,
)
from forecast_interface.conformance._canonical import canonical
from forecast_interface.interface import ModelSuccess
from tests.conformance_fakes import FakeArtifact, FakeModel, make_inputs, ISSUE
from random import Random

_LIMITS = SubprocessLimits(timedelta(seconds=30))


def _raw() -> bytes:
    return FakeModel().serialize_artifact(FakeArtifact(("A", "B")))


class TestRunFreshReload:
    def test_fresh_interpreter_reproduces_in_process_prediction(self) -> None:
        model = FakeModel()
        expected = model.predict(
            model.deserialize_artifact(_raw()),
            inputs=make_inputs(),
            issue_datetime=ISSUE,
            rng=Random(5),
        )
        assert isinstance(expected, ModelSuccess)

        outcome = run_fresh_reload(
            fixtures_spec="tests.conformance_fakes:make_fixtures",
            artifact=_raw(),
            seed=5,
            limits=_LIMITS,
        )

        assert outcome.kind is ReloadKind.OK
        assert outcome.result == canonical(expected)

    def test_timeout_is_reported_and_child_killed(self) -> None:
        outcome = run_fresh_reload(
            fixtures_spec="tests.conformance_fakes:make_slow_fixtures",
            artifact=_raw(),
            seed=0,
            limits=SubprocessLimits(timedelta(seconds=1)),
        )

        assert outcome.kind is ReloadKind.TIMEOUT
        assert "timed out" in outcome.detail

    def test_hard_exit_is_reported_as_crash(self) -> None:
        outcome = run_fresh_reload(
            fixtures_spec="tests.conformance_fakes:make_crashing_fixtures",
            artifact=_raw(),
            seed=0,
            limits=_LIMITS,
        )

        assert outcome.kind is ReloadKind.CRASHED
        assert "code 7" in outcome.detail

    def test_unimportable_fixtures_are_a_load_error(self) -> None:
        outcome = run_fresh_reload(
            fixtures_spec="tests.conformance_fakes:does_not_exist",
            artifact=_raw(),
            seed=0,
            limits=_LIMITS,
        )

        assert outcome.kind is ReloadKind.LOAD_ERROR
        assert "AttributeError" in outcome.detail
