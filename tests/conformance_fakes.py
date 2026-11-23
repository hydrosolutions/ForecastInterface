import itertools
import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from random import Random
from typing import Any

import polars as pl

from forecast_interface.common import SpatialRepresentation, Unit
from forecast_interface.conformance import BadCase, TrainCase, UnknownStationCase
from forecast_interface.input import (
    DynamicInputs,
    DynamicInputSpec,
    InputRequirement,
    InputSeries,
    ModelInputs,
    OutputRepresentation,
    PastKnownVariable,
    SpatialInputs,
    SpatialInputSpec,
    StationInputs,
    TargetSpec,
)
from forecast_interface.interface import (
    ArtifactScope,
    FailureCause,
    ForecastModel,
    ModelFailure,
    ModelResult,
    ModelSuccess,
    TrainedArtifact,
)
from forecast_interface.output import (
    DeterministicData,
    ModelOutput,
    VariableMetadata,
    VariableOutput,
    VariableStatus,
)

DAY = timedelta(days=1)
ISSUE = datetime(2024, 1, 1, tzinfo=UTC)
TRAINED_STATIONS = ("A", "B")

_counter = itertools.count()


class UnknownPolicy(Enum):
    FAILURE_ENTRY = auto()
    SILENT_PREDICTION = auto()


def requirement() -> InputRequirement:
    return InputRequirement(
        targets={
            "q": TargetSpec(
                unit=Unit.M3_PER_S,
                representations=frozenset({OutputRepresentation.DETERMINISTIC}),
            )
        },
        dynamic={
            DAY: SpatialInputSpec(
                data={
                    SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                        past_known={
                            "obs": {
                                "q": PastKnownVariable(
                                    unit=Unit.M3_PER_S, lookback=1, max_nan=0
                                )
                            }
                        }
                    )
                }
            )
        },
    )


def make_inputs(
    stations: tuple[str, ...] = TRAINED_STATIONS, case: str = ""
) -> ModelInputs:
    series = InputSeries(
        unit=Unit.M3_PER_S,
        data=pl.DataFrame({"datetime": [ISSUE], "value": [1.0]}),
    )
    station = StationInputs(
        dynamic={
            DAY: SpatialInputs(
                data={
                    SpatialRepresentation.BASIN_AVERAGE: DynamicInputs(
                        past_known={"obs": {"q": series}}
                    )
                }
            )
        },
        static={"case": case} if case else {},
    )
    return ModelInputs(stations={s: station for s in stations})


def variable(
    value: float, *, unit: Unit = Unit.M3_PER_S, status: VariableStatus
) -> VariableOutput:
    frame = pl.DataFrame(
        {
            "issue_datetime": [ISSUE],
            "datetime": [ISSUE + DAY],
            "value": [value],
        }
    ).with_columns(pl.col(pl.Datetime).dt.replace_time_zone("UTC"))
    metadata = VariableMetadata(unit=unit, timedelta=DAY, forecast_horizon=1, offset=0)
    if status is VariableStatus.FAILURE:
        return VariableOutput(metadata=metadata, status=status)
    return VariableOutput(
        metadata=metadata, deterministic=DeterministicData(data=frame), status=status
    )


class FakeArtifact:
    def __init__(self, stations: tuple[str, ...], marker: str = "") -> None:
        self.stations = stations
        self.marker = marker


class FakeModel:
    """Conforming by default; subclass or set attributes to break one thing."""

    artifact_scope = ArtifactScope.GROUP
    unit = Unit.M3_PER_S
    raise_in_predict = False
    nondeterministic = False
    drop_station: str | None = None
    extra_station: str | None = None
    unknown_policy = UnknownPolicy.FAILURE_ENTRY
    artifact_marker = ""

    @property
    def input_requirement(self) -> InputRequirement:
        return requirement()

    def train(
        self, inputs: ModelInputs, *, config: Mapping[str, Any], rng: Random
    ) -> TrainedArtifact:
        return FakeArtifact(tuple(inputs.stations), self.artifact_marker)

    def predict(
        self,
        artifact: TrainedArtifact,
        *,
        inputs: ModelInputs,
        issue_datetime: datetime,
        rng: Random,
    ) -> ModelResult:
        assert isinstance(artifact, FakeArtifact)
        if self.raise_in_predict:
            raise RuntimeError("model bug")
        cases = {s.static.get("case") for s in inputs.stations.values()}
        if "boom" in cases:
            raise ValueError("boom")
        if cases & {"short_history", "missing_data"}:
            return ModelFailure(
                model_name="fake",
                issue_datetime=issue_datetime,
                cause=FailureCause.INPUT_DATA,
                message="insufficient input data",
            )
        value = float(next(_counter)) if self.nondeterministic else rng.random()
        variables: dict[str, dict[str, VariableOutput]] = {}
        for station in inputs.stations:
            known = station in artifact.stations
            if station == self.drop_station:
                continue
            if known or self.unknown_policy is UnknownPolicy.SILENT_PREDICTION:
                variables[station] = {
                    "q": variable(value, unit=self.unit, status=VariableStatus.SUCCESS)
                }
            else:
                variables[station] = {"q": variable(0.0, status=VariableStatus.FAILURE)}
        if self.extra_station:
            variables[self.extra_station] = {
                "q": variable(value, status=VariableStatus.SUCCESS)
            }
        return ModelSuccess(
            output=ModelOutput(
                model_name="fake", issue_datetime=issue_datetime, variables=variables
            )
        )

    def serialize_artifact(self, artifact: TrainedArtifact) -> bytes:
        assert isinstance(artifact, FakeArtifact)
        return json.dumps(
            {"stations": artifact.stations, "marker": artifact.marker}
        ).encode()

    def deserialize_artifact(self, raw: bytes) -> TrainedArtifact:
        payload = json.loads(raw)
        return FakeArtifact(tuple(payload["stations"]), payload["marker"])


class MinimalFixtures:
    def __init__(self, model: ForecastModel | None = None, raw: bytes | None = None):
        self.model = model if model is not None else FakeModel()
        self.raw = raw

    def model_factory(self) -> ForecastModel:
        return self.model

    def artifact_bytes(self) -> bytes | None:
        return self.raw

    def predict_inputs(self) -> tuple[ModelInputs, datetime]:
        return make_inputs(), ISSUE


class FullFixtures(MinimalFixtures):
    def __init__(self, model: ForecastModel | None = None, marker: str = ""):
        raw = FakeModel().serialize_artifact(FakeArtifact(TRAINED_STATIONS, marker))
        super().__init__(model, raw)

    def bad_cases(self) -> Mapping[str, BadCase]:
        return {
            "short_history": BadCase(
                make_inputs(case="short_history"), FailureCause.INPUT_DATA
            ),
            "missing_data": BadCase(
                make_inputs(case="missing_data"), FailureCause.INPUT_DATA
            ),
            "garbage": BadCase(
                make_inputs(case="missing_data"), FailureCause.INPUT_DATA
            ),
        }

    def train_case(self) -> TrainCase | None:
        return TrainCase(make_inputs(), {}, seed=3)

    def unknown_station_case(self) -> UnknownStationCase | None:
        return UnknownStationCase(make_inputs(("A", "Z")), "Z")


def make_fixtures() -> FullFixtures:
    return FullFixtures()


def make_slow_fixtures() -> FullFixtures:
    time.sleep(5)
    return FullFixtures()


def make_crashing_fixtures() -> FullFixtures:
    os._exit(7)
