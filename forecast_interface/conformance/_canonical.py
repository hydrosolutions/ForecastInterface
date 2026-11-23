import datetime
import math
from typing import Any

import polars as pl

from forecast_interface.interface import ModelFailure, ModelResult
from forecast_interface.output import VariableOutput

JsonValue = Any


def _scalar(value: object) -> object:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


def _frame(df: pl.DataFrame) -> dict[str, list[object]]:
    return {
        column: [_scalar(v) for v in values]
        for column, values in df.to_dict(as_series=False).items()
    }


def _variable(variable: VariableOutput) -> dict[str, JsonValue]:
    frames = {
        name: _frame(container.data)
        for name, container in (
            ("deterministic", variable.deterministic),
            ("quantiles", variable.quantiles),
            ("trajectories", variable.trajectories),
            ("epistemic_uncertainty", variable.epistemic_uncertainty),
        )
        if container is not None
    }
    return {
        "status": variable.status.name,
        "metadata": variable.metadata.model_dump(mode="json"),
        "flags": sorted(flag.name for flag in variable.flags),
        "frames": frames,
    }


def canonical(result: ModelResult) -> dict[str, JsonValue]:
    """JSON-able, comparable form of a ModelResult (also what a fresh process emits)."""
    if isinstance(result, ModelFailure):
        return {"kind": "failure", "cause": result.cause.name}
    output = result.output
    return {
        "kind": "success",
        "model_name": output.model_name,
        "issue_datetime": output.issue_datetime.isoformat(),
        "variables": {
            station: {name: _variable(v) for name, v in variables.items()}
            for station, variables in output.variables.items()
        },
    }


def differences(
    left: JsonValue, right: JsonValue, atol: float, path: str = "result"
) -> list[str]:
    match left, right:
        case dict(), dict():
            keys = sorted(set(left) | set(right))
            return [
                d
                for key in keys
                for d in (
                    differences(left[key], right[key], atol, f"{path}.{key}")
                    if key in left and key in right
                    else [f"{path}.{key}: present on one side only"]
                )
            ]
        case list(), list():
            if len(left) != len(right):
                return [f"{path}: length {len(left)} != {len(right)}"]
            return [
                d
                for i, (a, b) in enumerate(zip(left, right, strict=True))
                for d in differences(a, b, atol, f"{path}[{i}]")
            ]
        case float() | int(), float() | int() if not isinstance(
            left, bool
        ) and not isinstance(right, bool):
            if math.isnan(left) and math.isnan(right):
                return []
            if abs(left - right) <= atol:
                return []
            return [f"{path}: {left!r} != {right!r} (atol={atol})"]
        case _:
            return [] if left == right else [f"{path}: {left!r} != {right!r}"]
