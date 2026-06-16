from collections.abc import Sequence
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
    def train(
        self, inputs: ModelInputs, *, config: Any, rng: Random
    ) -> TrainedArtifact: ...

    # ^ PROVISIONAL: `config` model params are co-designed with SAP3 (Q8).
    #   Typed Any until that contract lands.

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
    def retrain(
        self,
        base_artifact: TrainedArtifact,
        inputs: ModelInputs,
        *,
        config: Any,  # PROVISIONAL: model params are co-designed with SAP3 (Q8).
        rng: Random,
    ) -> TrainedArtifact: ...
