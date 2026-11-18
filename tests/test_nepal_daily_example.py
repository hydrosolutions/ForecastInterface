from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from pydantic import BaseModel, ValidationError

from forecast_interface.common import (
    AggregationMethod,
    Compatibility,
    GridMismatchError,
    PeriodLabel,
    SpatialRepresentation,
    TimeAnchor,
    TimeGrid,
    TrainingGridDeclaration,
    Unit,
    Unknown,
    compatibility,
    require_compatible,
)
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
from forecast_interface.interface.artifact import (
    GridDeclaringArtifact,
    artifact_training_grid,
)
from forecast_interface.output.metadata import VariableMetadata
from forecast_interface.output.status import VariableStatus
from forecast_interface.output.variable_output import (
    DeterministicData,
    VariableOutput,
)

DAY = timedelta(days=1)
BOUNDARY = timedelta(hours=18)
LABEL = PeriodLabel.END

DEPLOYMENT = TimeGrid(DAY, BOUNDARY, LABEL)
# Wed 18 Nov 2026 in Nepal: [2026-11-17T18:00Z, 2026-11-18T18:00Z)
WED_START = datetime(2026, 11, 17, 18, tzinfo=UTC)
WED_END = datetime(2026, 11, 18, 18, tzinfo=UTC)
ISSUE = datetime(2026, 11, 18, 6, tzinfo=UTC)


class FakeNepalModel:
    def requirement(self) -> InputRequirement:
        return InputRequirement(
            targets={
                "discharge": TargetSpec(
                    unit=Unit.M3_PER_S,
                    representations=frozenset({OutputRepresentation.DETERMINISTIC}),
                    aggregation=AggregationMethod.MEAN,
                    label=LABEL,
                )
            },
            dynamic={
                DAY: SpatialInputSpec(
                    data={
                        SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                            past_known={
                                "obs": {
                                    "discharge": PastKnownVariable(
                                        unit=Unit.M3_PER_S, lookback=7, max_nan=0
                                    )
                                }
                            }
                        )
                    },
                    anchor=TimeAnchor(origin=BOUNDARY, label=LABEL),
                )
            },
        )

    def metadata(self) -> VariableMetadata:
        return VariableMetadata(
            unit=Unit.M3_PER_S,
            timedelta=DAY,
            forecast_horizon=1,
            offset=0,
            origin=BOUNDARY,
            label=LABEL,
            aggregation=AggregationMethod.MEAN,
        )

    def predict(self, issue: datetime) -> VariableOutput:
        return self.hindcast([issue])

    def hindcast(self, issues: list[datetime]) -> VariableOutput:
        return build_output(issues, [_stamp(i) for i in issues], self.metadata())


def _day_start(issue: datetime) -> datetime:
    midnight = issue.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + BOUNDARY
    return start if start <= issue else start - DAY


def _stamp(issue: datetime) -> datetime:
    start = _day_start(issue)
    return start + DAY if LABEL is PeriodLabel.END else start


def build_output(
    issues: list[datetime], stamps: list[datetime], metadata: VariableMetadata
) -> VariableOutput:
    frame = pl.DataFrame(
        {"issue_datetime": issues, "datetime": stamps, "value": [1.0] * len(issues)}
    ).with_columns(pl.col(pl.Datetime).dt.replace_time_zone("UTC"))
    return VariableOutput(
        metadata=metadata,
        deterministic=DeterministicData(data=frame),
        status=VariableStatus.SUCCESS,
    )


class FakeArtifact(BaseModel):
    training_grid: TrainingGridDeclaration


class LegacyArtifact:
    pass


def _artifact(grid: TimeGrid) -> FakeArtifact:
    return FakeArtifact(training_grid=TrainingGridDeclaration(grid=grid))


class TestRequirement:
    def test_daily_branch_is_anchored_at_boundary_with_label(self) -> None:
        anchor = FakeNepalModel().requirement().dynamic[DAY].anchor

        assert anchor == TimeAnchor(origin=BOUNDARY, label=LABEL)

    def test_target_declares_aggregation_and_label(self) -> None:
        target = FakeNepalModel().requirement().targets["discharge"]

        assert (target.aggregation, target.label) == (AggregationMethod.MEAN, LABEL)


class TestArtifactRoundTrip:
    def test_implements_grid_declaring_protocol(self) -> None:
        assert isinstance(_artifact(DEPLOYMENT), GridDeclaringArtifact)

    def test_declaration_survives_json_persistence(self) -> None:
        stored = _artifact(DEPLOYMENT).model_dump_json()

        restored = FakeArtifact.model_validate_json(stored)

        assert artifact_training_grid(restored).grid == DEPLOYMENT


class TestCompatibility:
    def test_same_grid_is_compatible(self) -> None:
        declared = artifact_training_grid(_artifact(DEPLOYMENT)).grid

        assert compatibility(DEPLOYMENT, declared) is Compatibility.COMPATIBLE

    def test_dhm_discharge_at_1815_is_mismatch(self) -> None:
        declared = TimeGrid(DAY, BOUNDARY + timedelta(minutes=15), LABEL)

        assert compatibility(DEPLOYMENT, declared) is Compatibility.MISMATCH

    def test_different_label_is_mismatch(self) -> None:
        declared = TimeGrid(DAY, BOUNDARY, PeriodLabel.START)

        assert compatibility(DEPLOYMENT, declared) is Compatibility.MISMATCH

    def test_legacy_artifact_is_unknown(self) -> None:
        declared = artifact_training_grid(LegacyArtifact()).grid

        assert declared is Unknown.UNKNOWN
        assert compatibility(DEPLOYMENT, declared) is Compatibility.UNKNOWN

    def test_require_compatible_raises_only_on_mismatch(self) -> None:
        shifted = TimeGrid(DAY, BOUNDARY + timedelta(minutes=15), LABEL)

        with pytest.raises(GridMismatchError, match="origin"):
            require_compatible(DEPLOYMENT, shifted)
        assert require_compatible(DEPLOYMENT, DEPLOYMENT) is Compatibility.COMPATIBLE
        assert require_compatible(DEPLOYMENT, Unknown.UNKNOWN) is Compatibility.UNKNOWN


class TestWholeDayOutput:
    def test_live_predict_covers_current_hydrological_day(self) -> None:
        model = FakeNepalModel()

        out = model.predict(ISSUE)

        assert out.deterministic is not None
        assert out.deterministic.data["datetime"].to_list() == [WED_END]
        assert _day_start(ISSUE) == WED_START
        assert WED_END - WED_START == model.metadata().timedelta

    def test_metadata_echoes_origin_and_label(self) -> None:
        out = FakeNepalModel().predict(ISSUE)

        assert (out.metadata.origin, out.metadata.label) == (BOUNDARY, LABEL)

    def test_start_label_stamps_period_start(self) -> None:
        metadata = (
            FakeNepalModel().metadata().model_copy(update={"label": PeriodLabel.START})
        )

        out = build_output([ISSUE], [WED_START], metadata)

        assert out.deterministic is not None
        assert out.deterministic.data["datetime"].to_list() == [WED_START]

    def test_stamp_off_grid_is_rejected(self) -> None:
        off_grid = datetime(2026, 11, 18, 18, 15, tzinfo=UTC)

        with pytest.raises(ValidationError, match="off the declared grid"):
            build_output([ISSUE], [off_grid], FakeNepalModel().metadata())

    def test_hindcast_rows_are_whole_day_and_on_grid(self) -> None:
        issues = [ISSUE + timedelta(days=n, hours=3 * n) for n in range(4)]

        out = FakeNepalModel().hindcast(issues)

        assert out.deterministic is not None
        stamps = out.deterministic.data["datetime"].to_list()
        assert stamps == [WED_END + timedelta(days=n) for n in range(4)]
        assert all(s.time() == datetime(2000, 1, 1, 18).time() for s in stamps)


def _inputs_at(times: list[datetime]) -> ModelInputs:
    series = InputSeries(
        unit=Unit.M3_PER_S,
        data=pl.DataFrame({"datetime": times, "value": [1.0] * len(times)}),
    )
    dynamic = DynamicInputs(past_known={"obs": {"discharge": series}})
    station = StationInputs(
        dynamic={
            DAY: SpatialInputs(data={SpatialRepresentation.BASIN_AVERAGE: dynamic})
        }
    )
    return ModelInputs(stations={"s1": station}, grid=DEPLOYMENT)


class TestModelInputsGrid:
    def test_inputs_stamped_at_1800z_pass(self) -> None:
        inputs = _inputs_at([WED_START, WED_END])

        assert inputs.grid == DEPLOYMENT

    def test_inputs_stamped_at_1815z_fail(self) -> None:
        late = datetime(2026, 11, 18, 18, 15, tzinfo=UTC)

        with pytest.raises(ValidationError, match="off the declared grid"):
            _inputs_at([WED_START, late])
