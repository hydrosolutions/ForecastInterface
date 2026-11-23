from collections.abc import Mapping
from datetime import datetime
from typing import Any, NamedTuple, Protocol, runtime_checkable

from forecast_interface.input import ModelInputs
from forecast_interface.interface import FailureCause, ForecastModel


class TrainCase(NamedTuple):
    inputs: ModelInputs
    config: Mapping[str, Any]
    seed: int


class BadCase(NamedTuple):
    inputs: ModelInputs
    expected_cause: FailureCause


class UnknownStationCase(NamedTuple):
    inputs: ModelInputs
    unknown_station: str


@runtime_checkable
class Fixtures(Protocol):
    def model_factory(self) -> ForecastModel: ...

    def artifact_bytes(self) -> bytes | None: ...

    def predict_inputs(self) -> tuple[ModelInputs, datetime]: ...


@runtime_checkable
class HasBadCases(Protocol):
    def bad_cases(self) -> Mapping[str, BadCase]: ...


@runtime_checkable
class HasTrainCase(Protocol):
    def train_case(self) -> TrainCase | None: ...


@runtime_checkable
class HasUnknownStationCase(Protocol):
    def unknown_station_case(self) -> UnknownStationCase | None: ...
