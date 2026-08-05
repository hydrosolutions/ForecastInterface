from collections.abc import Mapping, Sequence
from datetime import datetime
from random import Random
from typing import Any, Protocol, runtime_checkable

from forecast_interface.input import InputRequirement, ModelInputs

from .artifact import TrainedArtifact
from .result import ModelResult
from .scope import ArtifactScope


@runtime_checkable
class ForecastModel(Protocol):
    @property
    def input_requirement(self) -> InputRequirement: ...

    artifact_scope: ArtifactScope

    # REQUIRED training contract — cold full rebuild is the baseline.
    # `config` is an opaque mapping each model self-validates; `RunConfig`
    # is FI's generic cross-model subset a model may parse out of it.
    def train(
        self, inputs: ModelInputs, *, config: Mapping[str, Any], rng: Random
    ) -> TrainedArtifact: ...

    def predict(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: ModelInputs,
        issue_datetime: datetime,
        rng: Random,
    ) -> ModelResult: ...

    def serialize_artifact(self, artifact: TrainedArtifact) -> bytes: ...

    def deserialize_artifact(self, raw: bytes) -> TrainedArtifact: ...


@runtime_checkable
class BatchHindcastModel(ForecastModel, Protocol):
    # The plural `issue_datetimes: Sequence[datetime]` is a static contract;
    # runtime_checkable only verifies member presence.
    def hindcast(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: ModelInputs,
        issue_datetimes: Sequence[datetime],
        rng: Random,
    ) -> ModelResult: ...


@runtime_checkable
class RetrainableModel(ForecastModel, Protocol):
    # Warm-start retrain — OPTIONAL. SAP3 checks isinstance(model, RetrainableModel)
    # to know whether warm-start is supported; otherwise it falls back to `train`.
    # `config` is an opaque mapping each model self-validates; `RunConfig`
    # is FI's generic cross-model subset a model may parse out of it.
    def retrain(
        self,
        base_artifact: TrainedArtifact,
        inputs: ModelInputs,
        *,
        config: Mapping[str, Any],
        rng: Random,
    ) -> TrainedArtifact: ...
