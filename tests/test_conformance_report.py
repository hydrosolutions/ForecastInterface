import json

from forecast_interface.conformance import (
    REPORT_SCHEMA_VERSION,
    CheckId,
    CheckResult,
    ExitCode,
    Fault,
    Layer,
    Report,
    Status,
    Strictness,
)


def _result(
    status: Status,
    layer: Layer = Layer.FI,
    fault: Fault = Fault.NONE,
    check: CheckId = CheckId.PROTOCOL_METHODS,
    message: str = "msg",
) -> CheckResult:
    return CheckResult(check, status, layer, message, "fix it", fault)


def _report(*results: CheckResult) -> Report:
    return Report(results, "9.9.9")


class TestReportJson:
    def test_top_level_schema(self) -> None:
        payload = json.loads(_report(_result(Status.PASS)).to_json())

        assert set(payload) == {
            "report_schema_version",
            "fi_version",
            "summary",
            "results",
        }
        assert payload["report_schema_version"] == REPORT_SCHEMA_VERSION == 1
        assert payload["fi_version"] == "9.9.9"
        assert payload["summary"] == {"pass": 1, "fail": 0, "not_tested": 0}

    def test_result_schema_and_enum_values(self) -> None:
        payload = json.loads(_report(_result(Status.NOT_TESTED)).to_json())

        assert payload["results"][0] == {
            "check_id": "protocol.methods",
            "status": "NOT_TESTED",
            "layer": "FI",
            "fault": "NONE",
            "message": "msg",
            "remediation": "fix it",
            "warnings": [],
        }

    def test_enum_vocabularies_are_stable(self) -> None:
        assert {s.value for s in Status} == {"PASS", "FAIL", "NOT_TESTED"}
        assert {layer.value for layer in Layer} == {"FI", "PROFILE"}
        assert {f.value for f in Fault} == {"NONE", "EXECUTION"}

    def test_check_ids_are_stable(self) -> None:
        assert {c.value for c in CheckId} >= {
            "protocol.methods",
            "protocol.signatures",
            "capabilities.declared",
            "output.matches_requirement",
            "failure.returned_not_raised",
            "input.short_history",
            "input.missing_data",
            "station.unknown",
            "artifact.roundtrip",
            "artifact.reload_fresh_process",
            "artifact.portable_paths",
            "repro.predict_seeded",
            "repro.train_seeded",
        }


class TestReportText:
    def test_lists_not_tested_with_reason(self) -> None:
        text = _report(
            _result(Status.NOT_TESTED, message="no fixture supplied: train_case")
        ).to_text()

        assert "NOT TESTED:" in text
        assert "protocol.methods: no fixture supplied: train_case" in text

    def test_shows_remediation_only_for_failures(self) -> None:
        text = _report(_result(Status.FAIL), _result(Status.PASS)).to_text()

        assert text.count("fix: fix it") == 1


class TestExitCode:
    def test_all_pass_is_zero(self) -> None:
        assert _report(_result(Status.PASS)).exit_code() is ExitCode.OK

    def test_fi_fail_is_one(self) -> None:
        assert _report(_result(Status.FAIL)).exit_code() == 1

    def test_profile_only_fail_is_four(self) -> None:
        report = _report(_result(Status.FAIL, Layer.PROFILE), _result(Status.PASS))

        assert report.exit_code() == 4

    def test_fi_fail_outranks_profile_fail(self) -> None:
        report = _report(_result(Status.FAIL, Layer.PROFILE), _result(Status.FAIL))

        assert report.exit_code() == 1

    def test_execution_fault_is_three_and_outranks_everything(self) -> None:
        report = _report(
            _result(Status.FAIL),
            _result(Status.FAIL, fault=Fault.EXECUTION),
        )

        assert report.exit_code() == 3

    def test_not_tested_passes_unless_strict(self) -> None:
        report = _report(_result(Status.PASS), _result(Status.NOT_TESTED))

        assert report.exit_code(Strictness.LENIENT) == 0
        assert report.exit_code(Strictness.STRICT) == 1

    def test_usage_code_value(self) -> None:
        assert int(ExitCode.USAGE) == 2
