from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from forecast_interface.common import PeriodLabel, TimeGrid, TrainingGridDeclaration
from forecast_interface.input import (
    DynamicInputSpec,
    InputRequirement,
    ModelInputs,
    OutputRepresentation,
    PastKnownVariable,
    SpatialInputSpec,
    SpatialRepresentation,
    TargetSpec,
)
from forecast_interface.interface import (
    ArtifactScope,
    BatchHindcastModel,
    FailureCause,
    ForecastModel,
    GridDeclaringArtifact,
    ModelFailure,
    ModelResult,
    ModelSuccess,
    RetrainableModel,
    TrainedArtifact,
    artifact_training_grid,
)
from forecast_interface.output import (
    DeterministicData,
    ModelOutput,
    Unit,
    VariableMetadata,
    VariableOutput,
    VariableStatus,
)

_ISSUE_DT = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
_DT1 = datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc)


def _make_model_output() -> ModelOutput:
    df = pl.DataFrame(
        {
            "issue_datetime": [_ISSUE_DT],
            "datetime": [_DT1],
            "value": [42.0],
        }
    )
    return ModelOutput(
        model_name="test_model",
        issue_datetime=_ISSUE_DT,
        variables={
            "station_1": {
                "discharge": VariableOutput(
                    metadata=VariableMetadata(
                        unit=Unit.M3_PER_S,
                        timedelta=timedelta(days=1),
                        forecast_horizon=1,
                        offset=0,
                    ),
                    deterministic=DeterministicData(data=df),
                    status=VariableStatus.SUCCESS,
                )
            }
        },
    )


def _make_input_requirement() -> InputRequirement:
    return InputRequirement(
        targets={
            "q": TargetSpec(
                unit=Unit.M3_PER_S,
                representations=frozenset({OutputRepresentation.DETERMINISTIC}),
            )
        },
        dynamic={
            timedelta(days=1): SpatialInputSpec(
                data={
                    SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                        past_known={
                            "obs": {
                                "q": PastKnownVariable(
                                    unit=Unit.M3_PER_S,
                                    lookback=1,
                                    max_nan=0,
                                )
                            }
                        }
                    )
                }
            )
        },
    )


# ---------------------------------------------------------------------------
# FailureCause
# ---------------------------------------------------------------------------


class TestFailureCause:
    def test_member_count(self) -> None:
        assert len(FailureCause) == 6

    def test_members_exist(self) -> None:
        assert FailureCause.INPUT_DATA is not None
        assert FailureCause.RESOURCE is not None
        assert FailureCause.MODEL_ERROR is not None
        assert FailureCause.CONFIGURATION is not None
        assert FailureCause.DEPENDENCY is not None


# ---------------------------------------------------------------------------
# ModelSuccess
# ---------------------------------------------------------------------------


class TestModelSuccess:
    def test_valid_construction(self) -> None:
        output = _make_model_output()
        result = ModelSuccess(output=output)
        assert result.kind == "success"
        assert result.output is output


# ---------------------------------------------------------------------------
# ModelFailure
# ---------------------------------------------------------------------------


class TestModelFailure:
    def test_valid_construction(self) -> None:
        failure = ModelFailure(
            model_name="my_model",
            issue_datetime=_ISSUE_DT,
            cause=FailureCause.INPUT_DATA,
            message="missing discharge data",
        )
        assert failure.kind == "failure"
        assert failure.model_name == "my_model"
        assert failure.issue_datetime == _ISSUE_DT
        assert failure.cause == FailureCause.INPUT_DATA
        assert failure.message == "missing discharge data"

    def test_empty_model_name_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="model_name must be a non-empty string"
        ):
            ModelFailure(
                model_name="",
                issue_datetime=_ISSUE_DT,
                cause=FailureCause.RESOURCE,
                message="some error",
            )

    def test_whitespace_model_name_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="model_name must be a non-empty string"
        ):
            ModelFailure(
                model_name="   ",
                issue_datetime=_ISSUE_DT,
                cause=FailureCause.RESOURCE,
                message="some error",
            )

    def test_naive_issue_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match="should have timezone info"):
            ModelFailure(
                model_name="my_model",
                issue_datetime=datetime(2024, 1, 1, 0, 0),
                cause=FailureCause.INPUT_DATA,
                message="some error",
            )

    def test_non_utc_issue_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match="issue_datetime must be UTC"):
            ModelFailure(
                model_name="my_model",
                issue_datetime=datetime(
                    2024, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=45))
                ),
                cause=FailureCause.INPUT_DATA,
                message="some error",
            )

    def test_utc_issue_datetime_accepted(self) -> None:
        failure = ModelFailure(
            model_name="my_model",
            issue_datetime=_ISSUE_DT,
            cause=FailureCause.INPUT_DATA,
            message="some error",
        )
        assert failure.issue_datetime == _ISSUE_DT

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="failure message must be a non-empty string"
        ):
            ModelFailure(
                model_name="my_model",
                issue_datetime=_ISSUE_DT,
                cause=FailureCause.MODEL_ERROR,
                message="",
            )


# ---------------------------------------------------------------------------
# ModelResult type alias
# ---------------------------------------------------------------------------


class TestModelResult:
    def test_success_is_model_result(self) -> None:
        result: ModelResult = ModelSuccess(output=_make_model_output())
        assert isinstance(result, ModelSuccess)

    def test_failure_is_model_result(self) -> None:
        result: ModelResult = ModelFailure(
            model_name="m",
            issue_datetime=_ISSUE_DT,
            cause=FailureCause.DEPENDENCY,
            message="timeout",
        )
        assert isinstance(result, ModelFailure)


# ---------------------------------------------------------------------------
# ArtifactScope
# ---------------------------------------------------------------------------


class TestArtifactScope:
    def test_member_count(self) -> None:
        assert len(ArtifactScope) == 2

    def test_members_exist(self) -> None:
        assert ArtifactScope.STATION is not None
        assert ArtifactScope.GROUP is not None


# ---------------------------------------------------------------------------
# TrainedArtifact (opaque marker Protocol)
# ---------------------------------------------------------------------------


class TestTrainedArtifact:
    def test_any_object_satisfies_marker_protocol(self) -> None:
        # TrainedArtifact is an opaque marker Protocol with no members, so any
        # object satisfies it via isinstance.
        assert isinstance(object(), TrainedArtifact)


# ---------------------------------------------------------------------------
# ForecastModel / RetrainableModel protocols
# ---------------------------------------------------------------------------


class _ConformingModel:
    artifact_scope = ArtifactScope.STATION

    @property
    def input_requirement(self) -> InputRequirement:
        return _make_input_requirement()

    def train(
        self, inputs: ModelInputs, *, config: Any, rng: Random
    ) -> TrainedArtifact:
        return object()

    def predict(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: ModelInputs,
        issue_datetime: datetime,
        rng: Random,
    ) -> ModelResult:
        return ModelSuccess(output=_make_model_output())

    def serialize_artifact(self, artifact: TrainedArtifact) -> bytes:
        return b""

    def deserialize_artifact(self, raw: bytes) -> TrainedArtifact:
        return object()


class _BatchHindcastModel(_ConformingModel):
    def hindcast(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: ModelInputs,
        issue_datetimes: Sequence[datetime],
        rng: Random,
    ) -> ModelResult:
        return ModelSuccess(output=_make_model_output())


class _RetrainableModel(_ConformingModel):
    def retrain(
        self,
        base_artifact: TrainedArtifact,
        inputs: ModelInputs,
        *,
        config: Any,
        rng: Random,
    ) -> TrainedArtifact:
        return object()


class TestForecastModel:
    def test_conforming_class_satisfies_protocol(self) -> None:
        assert isinstance(_ConformingModel(), ForecastModel)

    def test_missing_train_fails_protocol(self) -> None:
        class _NoTrain:
            artifact_scope = ArtifactScope.STATION

            @property
            def input_requirement(self) -> InputRequirement:
                return _make_input_requirement()

            def predict(
                self,
                artifact: TrainedArtifact,
                *,
                inputs: ModelInputs,
                issue_datetime: datetime,
                rng: Random,
            ) -> ModelResult:
                raise NotImplementedError

            def serialize_artifact(self, artifact: TrainedArtifact) -> bytes:
                raise NotImplementedError

            def deserialize_artifact(self, raw: bytes) -> TrainedArtifact: ...

        assert not isinstance(_NoTrain(), ForecastModel)

    def test_missing_serialize_fails_protocol(self) -> None:
        class _NoSerialize:
            artifact_scope = ArtifactScope.STATION

            @property
            def input_requirement(self) -> InputRequirement:
                return _make_input_requirement()

            def train(
                self, inputs: ModelInputs, *, config: Any, rng: Random
            ) -> TrainedArtifact: ...

            def predict(
                self,
                artifact: TrainedArtifact,
                *,
                inputs: ModelInputs,
                issue_datetime: datetime,
                rng: Random,
            ) -> ModelResult:
                raise NotImplementedError

            def deserialize_artifact(self, raw: bytes) -> TrainedArtifact: ...

        assert not isinstance(_NoSerialize(), ForecastModel)

    def test_conforming_without_retrain_is_not_retrainable(self) -> None:
        model = _ConformingModel()
        assert isinstance(model, ForecastModel)
        assert not isinstance(model, RetrainableModel)
        assert not isinstance(model, BatchHindcastModel)

    def test_model_with_retrain_satisfies_both(self) -> None:
        model = _RetrainableModel()
        assert isinstance(model, ForecastModel)
        assert isinstance(model, RetrainableModel)
        assert not isinstance(model, BatchHindcastModel)

    def test_batch_hindcast_model_satisfies_batch_protocol(self) -> None:
        model = _BatchHindcastModel()
        assert isinstance(model, BatchHindcastModel)
        assert isinstance(model, ForecastModel)


class _LegacyArtifact:
    pass


class _GridArtifact:
    def __init__(self, declaration: TrainingGridDeclaration) -> None:
        self._declaration = declaration

    @property
    def training_grid(self) -> TrainingGridDeclaration:
        return self._declaration


class _AttributeErrorArtifact:
    @property
    def training_grid(self) -> TrainingGridDeclaration:
        raise AttributeError("not ready")


class _RuntimeErrorArtifact:
    @property
    def training_grid(self) -> TrainingGridDeclaration:
        raise RuntimeError("boom")


class _RaisingArtifact:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    @property
    def training_grid(self) -> TrainingGridDeclaration:
        raise self._exc


class _ReturningArtifact:
    def __init__(self, value: object) -> None:
        self._value = value

    @property
    def training_grid(self) -> object:
        return self._value


_GRID = TimeGrid(step=timedelta(hours=1), origin=timedelta(0), label=PeriodLabel.START)
_UNKNOWN = TrainingGridDeclaration()


class _FakeGridModel:
    def serialize_artifact(self, artifact: _GridArtifact) -> bytes:
        return artifact.training_grid.model_dump_json().encode()

    def deserialize_artifact(self, data: bytes) -> _GridArtifact:
        return _GridArtifact(TrainingGridDeclaration.model_validate_json(data))


class TestArtifactTrainingGrid:
    def test_legacy_artifact_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_LegacyArtifact()) == _UNKNOWN

    def test_declared_grid_is_returned(self) -> None:
        declaration = TrainingGridDeclaration(grid=_GRID)
        assert artifact_training_grid(_GridArtifact(declaration)) == declaration

    def test_attribute_error_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_AttributeErrorArtifact()) == _UNKNOWN

    def test_runtime_error_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_RuntimeErrorArtifact()) == _UNKNOWN

    def test_value_error_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_RaisingArtifact(ValueError("bad"))) == _UNKNOWN

    def test_key_error_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_RaisingArtifact(KeyError("k"))) == _UNKNOWN

    def test_non_declaration_int_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_ReturningArtifact(5)) == _UNKNOWN

    def test_none_reads_as_unknown(self) -> None:
        assert artifact_training_grid(_ReturningArtifact(None)) == _UNKNOWN


class TestGridDeclaringArtifact:
    def test_conforming_class_is_detected(self) -> None:
        assert isinstance(_GridArtifact(_UNKNOWN), GridDeclaringArtifact)

    def test_non_conforming_class_is_not_detected(self) -> None:
        assert not isinstance(_LegacyArtifact(), GridDeclaringArtifact)


class TestGridRoundTrip:
    @pytest.mark.parametrize(
        "declaration",
        [TrainingGridDeclaration(grid=_GRID), _UNKNOWN],
        ids=["known", "unknown"],
    )
    def test_declaration_survives_serialization(
        self, declaration: TrainingGridDeclaration
    ) -> None:
        model = _FakeGridModel()
        restored = model.deserialize_artifact(
            model.serialize_artifact(_GridArtifact(declaration))
        )
        assert artifact_training_grid(restored) == declaration


class TestGridMismatchFailure:
    def test_cause_exists_and_is_appended(self) -> None:
        assert list(FailureCause)[-1] is FailureCause.GRID_MISMATCH

    def test_model_failure_accepts_it(self) -> None:
        failure = ModelFailure(
            model_name="my_model",
            issue_datetime=_ISSUE_DT,
            cause=FailureCause.GRID_MISMATCH,
            message="grid differs",
        )
        assert failure.cause is FailureCause.GRID_MISMATCH
