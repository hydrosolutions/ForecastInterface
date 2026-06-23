from collections.abc import Sequence
from datetime import datetime, timedelta
from random import Random
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

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
    ModelFailure,
    ModelResult,
    ModelSuccess,
    RetrainableModel,
    TrainedArtifact,
)
from forecast_interface.output import (
    DeterministicData,
    ModelOutput,
    Unit,
    VariableMetadata,
    VariableOutput,
    VariableStatus,
)

_ISSUE_DT = datetime(2024, 1, 1, 0, 0)
_DT1 = datetime(2024, 1, 2, 0, 0)


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
        assert len(FailureCause) == 5

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
