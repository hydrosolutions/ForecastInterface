from datetime import datetime
from random import Random
from typing import Any, Protocol, runtime_checkable

from forecast_interface.input.requirement import InputRequirement

from .artifact import TrainedArtifact
from .result import ModelResult
from .scope import ArtifactScope


@runtime_checkable
class ForecastModel(Protocol):
    @property
    def input_requirement(self) -> InputRequirement: ...

    artifact_scope: ArtifactScope

    # REQUIRED training contract — cold full rebuild is the baseline.
    def train(self, inputs: Any, *, config: Any, rng: Random) -> TrainedArtifact: ...

    # ^ PROVISIONAL: `inputs` is the assembled-input bundle, `config` model params;
    #   both co-designed with SAP3 (doc 014 Task 3). Typed Any until that PR lands.

    def predict(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: Any,  # PROVISIONAL: assembled-input bundle, co-designed with SAP3.
        issue_datetime: datetime,
        rng: Random,
    ) -> ModelResult: ...

    def hindcast(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: Any,  # PROVISIONAL: assembled-input bundle, co-designed with SAP3.
        issue_datetime: datetime,
        rng: Random,
    ) -> ModelResult: ...

    def serialize_artifact(self, artifact: TrainedArtifact) -> bytes: ...

    def deserialize_artifact(self, raw: bytes) -> TrainedArtifact: ...


@runtime_checkable
class RetrainableModel(ForecastModel, Protocol):
    # Warm-start retrain — OPTIONAL. SAP3 checks isinstance(model, RetrainableModel)
    # to know whether warm-start is supported; otherwise it falls back to `train`.
    def retrain(
        self,
        base_artifact: TrainedArtifact,
        inputs: Any,  # PROVISIONAL: assembled-input bundle, co-designed with SAP3.
        *,
        config: Any,  # PROVISIONAL: model params, co-designed with SAP3.
        rng: Random,
    ) -> TrainedArtifact: ...
