from forecast_interface.conformance._canonical import canonical, differences
from forecast_interface.interface import FailureCause, ModelFailure, ModelSuccess
from forecast_interface.output import ModelOutput, VariableStatus
from tests.conformance_fakes import ISSUE, variable


class TestDifferences:
    def test_equal_structures_have_no_difference(self) -> None:
        assert differences({"a": [1.0, 2.0]}, {"a": [1.0, 2.0]}, atol=0.0) == []

    def test_float_within_atol_is_equal(self) -> None:
        assert differences({"a": 1.0}, {"a": 1.0 + 1e-10}, atol=1e-9) == []

    def test_float_beyond_atol_reports_path(self) -> None:
        diffs = differences({"a": [1.0]}, {"a": [1.5]}, atol=1e-9)

        assert len(diffs) == 1
        assert diffs[0].startswith("result.a[0]:")

    def test_nan_equals_nan(self) -> None:
        assert differences(float("nan"), float("nan"), atol=0.0) == []

    def test_key_present_on_one_side_is_reported(self) -> None:
        diffs = differences({"a": 1}, {"b": 1}, atol=0.0)

        assert len(diffs) == 2

    def test_length_mismatch_is_reported(self) -> None:
        assert "length 1 != 2" in differences([1], [1, 2], atol=0.0)[0]


class TestCanonical:
    def test_failure_is_cause_only(self) -> None:
        failure = ModelFailure(
            model_name="m",
            issue_datetime=ISSUE,
            cause=FailureCause.INPUT_DATA,
            message="x",
        )

        assert canonical(failure) == {"kind": "failure", "cause": "INPUT_DATA"}

    def test_success_is_json_serializable(self) -> None:
        import json

        output = ModelOutput(
            model_name="m",
            issue_datetime=ISSUE,
            variables={"A": {"q": variable(1.0, status=VariableStatus.SUCCESS)}},
        )

        json.dumps(canonical(ModelSuccess(output=output)))
