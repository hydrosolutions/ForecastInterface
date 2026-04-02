from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from forecast_interface.input.requirement import InputRequirement

from .result import ModelResult


@runtime_checkable
class ForecastModel(Protocol):
    @property
    def input_requirement(self) -> InputRequirement: ...

    def predict(self, *, inputs: Any, issue_datetime: datetime) -> ModelResult: ...

    def hindcast(self, *, inputs: Any, issue_datetime: datetime) -> ModelResult: ...
