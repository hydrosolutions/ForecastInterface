from datetime import datetime, timedelta
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from forecast_interface.input import (
    DynamicInputSpec,
    InputRequirement,
    OutputRepresentation,
    PastKnownVariable,
    SpatialInputSpec,
    SpatialRepresentation,
    TargetSpec,
    TemporalResolution as InputTemporalResolution,
)
from forecast_interface.interface import (
    FailureCause,
    ForecastModel,
    ModelFailure,
    ModelResult,
    ModelSuccess,
)
from forecast_interface.output import (
    DeterministicData,
    ModelOutput,
    TemporalResolution,
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
            "discharge": VariableOutput(
                metadata=VariableMetadata(
                    name="discharge",
                    unit=Unit.M3_PER_S,
                    resolution=TemporalResolution.DAILY,
                    timedelta=timedelta(days=1),
                    forecast_horizon=10,
                    offset=0,
                ),
                deterministic=DeterministicData(data=df),
                status=VariableStatus.SUCCESS,
            )
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
            InputTemporalResolution.DAILY: SpatialInputSpec(
                data={
                    SpatialRepresentation.BASIN_AVERAGE: DynamicInputSpec(
                        past_known={
                            "obs": {"q": PastKnownVariable(lookback=1, max_nan=0)}
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
# ForecastModel protocol
# ---------------------------------------------------------------------------


class TestForecastModel:
    def test_conforming_class_satisfies_protocol(self) -> None:
        class _ConformingModel:
            @property
            def input_requirement(self) -> InputRequirement:
                return _make_input_requirement()

            def predict(
                self, *, inputs: Any, issue_datetime: datetime
            ) -> ModelResult: ...

            def hindcast(
                self, *, inputs: Any, issue_datetime: datetime
            ) -> ModelResult: ...

        assert isinstance(_ConformingModel(), ForecastModel)

    def test_missing_predict_fails_protocol(self) -> None:
        class _Incomplete:
            @property
            def input_requirement(self) -> InputRequirement:
                return _make_input_requirement()

            def hindcast(
                self, *, inputs: Any, issue_datetime: datetime
            ) -> ModelResult: ...

        assert not isinstance(_Incomplete(), ForecastModel)
