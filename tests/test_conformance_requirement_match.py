from datetime import timedelta

from forecast_interface.common import AggregationMethod, PeriodLabel, TimeAnchor, Unit
from forecast_interface.conformance import output_requirement_mismatches
from forecast_interface.input import (
    DynamicInputSpec,
    InputRequirement,
    OutputRepresentation,
    PastKnownVariable,
    SpatialInputSpec,
    SpatialRepresentation,
    TargetSpec,
)
from forecast_interface.output import ModelOutput, VariableOutput, VariableStatus

from tests.conformance_fakes import DAY, ISSUE, make_inputs, requirement, variable


def _output(variables: dict[str, dict[str, VariableOutput]]) -> ModelOutput:
    return ModelOutput(model_name="m", issue_datetime=ISSUE, variables=variables)


def _good(stations: tuple[str, ...] = ("A", "B")) -> ModelOutput:
    return _output(
        {s: {"q": variable(1.0, status=VariableStatus.SUCCESS)} for s in stations}
    )


def _requirement_with_target(spec: TargetSpec, origin: timedelta | None = None):  # type: ignore[no-untyped-def]
    anchor = TimeAnchor(origin=origin) if origin is not None else TimeAnchor()
    return InputRequirement(
        targets={"q": spec},
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
                },
                anchor=anchor,
            )
        },
    )


def _spec(**kwargs) -> TargetSpec:  # type: ignore[no-untyped-def]
    return TargetSpec(
        unit=kwargs.pop("unit", Unit.M3_PER_S),
        representations=kwargs.pop(
            "representations", frozenset({OutputRepresentation.DETERMINISTIC})
        ),
        **kwargs,
    )


class TestOutputRequirementMismatches:
    def test_conforming_output_has_no_mismatch(self) -> None:
        assert (
            output_requirement_mismatches(
                _good(), requirement(), make_inputs(), issue_datetime=ISSUE
            )
            == []
        )

    def test_wrong_unit_is_reported_with_both_units(self) -> None:
        output = _output(
            {
                s: {
                    "q": variable(
                        1.0, unit=Unit.MM_PER_DAY, status=VariableStatus.SUCCESS
                    )
                }
                for s in ("A", "B")
            }
        )

        mismatches = output_requirement_mismatches(output, requirement(), make_inputs())

        assert any("A/q: unit" in m and "declared" in m for m in mismatches)

    def test_missing_station_is_reported(self) -> None:
        mismatches = output_requirement_mismatches(
            _good(("A",)), requirement(), make_inputs()
        )

        assert mismatches == [
            "stations missing from output (use FAILURE entries): ['B']"
        ]

    def test_extra_station_is_reported(self) -> None:
        mismatches = output_requirement_mismatches(
            _good(("A", "B", "C")), requirement(), make_inputs()
        )

        assert any("not in the inputs: ['C']" in m for m in mismatches)

    def test_failure_entry_for_a_station_is_allowed(self) -> None:
        output = _output(
            {
                "A": {"q": variable(1.0, status=VariableStatus.SUCCESS)},
                "B": {"q": variable(0.0, status=VariableStatus.FAILURE)},
            }
        )

        assert output_requirement_mismatches(output, requirement(), make_inputs()) == []

    def test_missing_and_undeclared_variables_are_reported(self) -> None:
        output = _output(
            {
                s: {"other": variable(1.0, status=VariableStatus.SUCCESS)}
                for s in ("A", "B")
            }
        )

        mismatches = output_requirement_mismatches(output, requirement(), make_inputs())

        assert any("targets missing" in m for m in mismatches)
        assert any("not declared as targets" in m for m in mismatches)

    def test_wrong_issue_datetime_is_reported(self) -> None:
        mismatches = output_requirement_mismatches(
            _good(),
            requirement(),
            make_inputs(),
            issue_datetime=ISSUE + timedelta(days=1),
        )

        assert any("issue_datetime" in m for m in mismatches)

    def test_undeclared_representation_is_reported(self) -> None:
        spec = _spec(representations=frozenset({OutputRepresentation.QUANTILES}))

        mismatches = output_requirement_mismatches(
            _good(), _requirement_with_target(spec), make_inputs()
        )

        assert any("representations not declared" in m for m in mismatches)

    def test_aggregation_disagreement_is_reported_only_when_both_declared(
        self,
    ) -> None:
        spec = _spec(aggregation=AggregationMethod.MEAN)
        requirement_ = _requirement_with_target(spec)

        assert output_requirement_mismatches(_good(), requirement_, make_inputs()) == []

    def test_label_disagreement_is_reported(self) -> None:
        spec = _spec(aggregation=AggregationMethod.MEAN, label=PeriodLabel.END)
        meta_output = _good()
        for station in meta_output.variables.values():
            station["q"].metadata.label = PeriodLabel.START

        mismatches = output_requirement_mismatches(
            meta_output, _requirement_with_target(spec), make_inputs()
        )

        assert any("label START != declared END" in m for m in mismatches)

    def test_origin_disagreement_with_matching_branch_is_reported(self) -> None:
        output = _good()
        for station in output.variables.values():
            station["q"].metadata.origin = timedelta(hours=6)

        mismatches = output_requirement_mismatches(
            output,
            _requirement_with_target(_spec(), origin=timedelta(hours=18)),
            make_inputs(),
        )

        assert any("origin" in m and "anchor" in m for m in mismatches)
