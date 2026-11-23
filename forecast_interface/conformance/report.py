"""Conformance results, report and exit-code policy.

Exit codes (``Report.exit_code``; ``2`` is raised as ``ConformanceUsageError``
before a report exists and is mapped by the caller):

====  ===============================================================
0     no FAIL (STRICT additionally requires no NOT_TESTED)
1     at least one FI-layer FAIL (or, under STRICT, any NOT_TESTED)
2     usage / specification error (bad fixtures spec or options)
3     model or artifact failed to load, crashed or timed out
4     only PROFILE-layer FAIL
====  ===============================================================

Precedence when several apply: 3, then 1, then 4.

JSON schema (``report_schema_version`` 1)::

    {"report_schema_version": 1, "fi_version": str,
     "summary": {"pass": int, "fail": int, "not_tested": int},
     "results": [{"check_id": str, "status": "PASS"|"FAIL"|"NOT_TESTED",
                  "layer": "FI"|"PROFILE", "fault": "NONE"|"EXECUTION",
                  "message": str, "remediation": str, "warnings": [str]}]}
"""

import json
from enum import IntEnum, StrEnum
from typing import NamedTuple

REPORT_SCHEMA_VERSION = 1


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


class Layer(StrEnum):
    FI = "FI"
    PROFILE = "PROFILE"


class Fault(StrEnum):
    NONE = "NONE"
    EXECUTION = "EXECUTION"


class Strictness(StrEnum):
    LENIENT = "lenient"
    STRICT = "strict"


class ExitCode(IntEnum):
    OK = 0
    FI_FAILURE = 1
    USAGE = 2
    EXECUTION = 3
    PROFILE_FAILURE = 4


class CheckId(StrEnum):
    PROTOCOL_METHODS = "protocol.methods"
    PROTOCOL_SIGNATURES = "protocol.signatures"
    PROTOCOL_SCOPE = "protocol.scope"
    CAPABILITIES_DECLARED = "capabilities.declared"
    CAPABILITIES_RETRAIN = "capabilities.retrain"
    CAPABILITIES_HINDCAST = "capabilities.hindcast"
    OUTPUT_MATCHES_REQUIREMENT = "output.matches_requirement"
    FAILURE_RETURNED_NOT_RAISED = "failure.returned_not_raised"
    INPUT_SHORT_HISTORY = "input.short_history"
    INPUT_MISSING_DATA = "input.missing_data"
    STATION_UNKNOWN = "station.unknown"
    ARTIFACT_ROUNDTRIP = "artifact.roundtrip"
    ARTIFACT_RELOAD_FRESH_PROCESS = "artifact.reload_fresh_process"
    ARTIFACT_PORTABLE_PATHS = "artifact.portable_paths"
    REPRO_PREDICT_SEEDED = "repro.predict_seeded"
    REPRO_TRAIN_SEEDED = "repro.train_seeded"
    REPRO_TRAIN_BYTE_EQUAL = "repro.train_byte_equal"


class CheckResult(NamedTuple):
    check_id: CheckId
    status: Status
    layer: Layer
    message: str
    remediation: str = ""
    fault: Fault = Fault.NONE
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id.value,
            "status": self.status.value,
            "layer": self.layer.value,
            "fault": self.fault.value,
            "message": self.message,
            "remediation": self.remediation,
            "warnings": list(self.warnings),
        }


class Report(NamedTuple):
    results: tuple[CheckResult, ...]
    fi_version: str

    def count(self, status: Status) -> int:
        return sum(r.status is status for r in self.results)

    def to_json(self) -> str:
        return json.dumps(
            {
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "fi_version": self.fi_version,
                "summary": {
                    "pass": self.count(Status.PASS),
                    "fail": self.count(Status.FAIL),
                    "not_tested": self.count(Status.NOT_TESTED),
                },
                "results": [r.to_dict() for r in self.results],
            },
            indent=2,
        )

    def to_text(self) -> str:
        lines = [f"ForecastInterface conformance report (FI {self.fi_version})", ""]
        for result in self.results:
            lines.append(
                f"[{result.status.value}] {result.check_id.value} "
                f"({result.layer.value}): {result.message}"
            )
            if result.status is Status.FAIL and result.remediation:
                lines.append(f"    fix: {result.remediation}")
            lines.extend(f"    warning: {w}" for w in result.warnings)
        not_tested = [r for r in self.results if r.status is Status.NOT_TESTED]
        if not_tested:
            lines += ["", "NOT TESTED:"]
            lines += [f"  {r.check_id.value}: {r.message}" for r in not_tested]
        lines += [
            "",
            f"{self.count(Status.PASS)} passed, {self.count(Status.FAIL)} failed, "
            f"{len(not_tested)} not tested",
        ]
        return "\n".join(lines)

    def exit_code(self, strict: Strictness = Strictness.LENIENT) -> ExitCode:
        failures = [r for r in self.results if r.status is Status.FAIL]
        if any(r.fault is Fault.EXECUTION for r in failures):
            return ExitCode.EXECUTION
        if any(r.layer is Layer.FI for r in failures):
            return ExitCode.FI_FAILURE
        if failures:
            return ExitCode.PROFILE_FAILURE
        if strict is Strictness.STRICT and self.count(Status.NOT_TESTED):
            return ExitCode.FI_FAILURE
        return ExitCode.OK
