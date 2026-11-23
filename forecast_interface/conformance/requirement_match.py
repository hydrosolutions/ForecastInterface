import datetime

from forecast_interface.common import PeriodLabel, Unknown
from forecast_interface.input import (
    InputRequirement,
    ModelInputs,
    OutputRepresentation,
)
from forecast_interface.output import ModelOutput, VariableOutput, VariableStatus


def present_representations(
    variable: VariableOutput,
) -> frozenset[OutputRepresentation]:
    return frozenset(
        representation
        for representation, container in (
            (OutputRepresentation.DETERMINISTIC, variable.deterministic),
            (OutputRepresentation.QUANTILES, variable.quantiles),
            (OutputRepresentation.TRAJECTORIES, variable.trajectories),
        )
        if container is not None
    )


def output_requirement_mismatches(
    output: ModelOutput,
    requirement: InputRequirement,
    inputs: ModelInputs,
    *,
    issue_datetime: datetime.datetime | None = None,
) -> list[str]:
    """Cross-check a ModelOutput against the model's InputRequirement.

    Horizon and offset are not declared by the requirement and are not checked
    here (the output's own validators enforce internal consistency). Cadence
    origin is checked only through the branch whose step equals the output
    timedelta: an output step absent from ``requirement.dynamic`` is allowed.
    """
    mismatches: list[str] = []
    if issue_datetime is not None and output.issue_datetime != issue_datetime:
        mismatches.append(
            f"output issue_datetime {output.issue_datetime} != requested "
            f"{issue_datetime}"
        )
    expected_stations = set(inputs.stations)
    got_stations = set(output.variables)
    if missing := sorted(expected_stations - got_stations):
        mismatches.append(
            f"stations missing from output (use FAILURE entries): {missing}"
        )
    if extra := sorted(got_stations - expected_stations):
        mismatches.append(f"output contains stations not in the inputs: {extra}")

    targets = set(requirement.targets)
    for station, variables in output.variables.items():
        if missing_targets := sorted(targets - set(variables)):
            mismatches.append(
                f"{station}: targets missing from output: {missing_targets}"
            )
        if extra_vars := sorted(set(variables) - targets):
            mismatches.append(
                f"{station}: variables not declared as targets: {extra_vars}"
            )
    mismatches.extend(
        mismatch
        for station, variables in output.variables.items()
        for name, variable in variables.items()
        if name in targets and variable.status is not VariableStatus.FAILURE
        for mismatch in _variable_mismatches(
            f"{station}/{name}", variable, requirement, name
        )
    )
    return mismatches


def _variable_mismatches(
    where: str, variable: VariableOutput, requirement: InputRequirement, target: str
) -> list[str]:
    spec = requirement.targets[target]
    meta = variable.metadata
    problems: list[str] = []
    if meta.unit != spec.unit:
        problems.append(
            f"{where}: unit {meta.unit.value!r} != declared {spec.unit.value!r}"
        )
    if undeclared := present_representations(variable) - spec.representations:
        names = sorted(r.value for r in undeclared)
        problems.append(f"{where}: representations not declared by the target: {names}")
    if (
        spec.aggregation is not None
        and not isinstance(meta.aggregation, Unknown)
        and meta.aggregation is not spec.aggregation
    ):
        problems.append(
            f"{where}: aggregation {meta.aggregation.name} != declared "
            f"{spec.aggregation.name}"
        )
    if (
        PeriodLabel.UNKNOWN not in (spec.label, meta.label)
        and meta.label is not spec.label
    ):
        problems.append(
            f"{where}: label {meta.label.name} != declared {spec.label.name}"
        )
    branch = requirement.dynamic.get(meta.timedelta)
    if (
        branch is not None
        and isinstance(branch.anchor.origin, datetime.timedelta)
        and isinstance(meta.origin, datetime.timedelta)
        and meta.origin != branch.anchor.origin
    ):
        problems.append(
            f"{where}: origin {meta.origin} != requirement anchor origin "
            f"{branch.anchor.origin} for step {meta.timedelta}"
        )
    return problems
