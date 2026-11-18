from collections.abc import Iterable
from enum import Enum
from typing import Any, Literal, NamedTuple, TypeAlias

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, field_validator

_MINUTE = timedelta(minutes=1)


class PeriodLabel(Enum):
    # START: stamp t names [t, t+step); END: stamp t names (t-step, t].
    START = "start"
    END = "end"
    UNKNOWN = "unknown"


class Unknown(Enum):
    UNKNOWN = "unknown"


def validate_whole_minutes(value: timedelta, name: str) -> None:
    if value % _MINUTE != timedelta(0):
        raise ValueError(f"{name} must be a whole number of minutes, got {value}")


def validate_divides_day(step: timedelta, name: str) -> None:
    if timedelta(days=1) % step != timedelta(0):
        raise ValueError(f"{name} must divide 24 hours exactly, got {step}")


class _TimeGridFields(NamedTuple):
    step: timedelta
    origin: timedelta
    label: PeriodLabel


class TimeGrid(_TimeGridFields):
    __slots__ = ()

    def __new__(
        cls, step: timedelta, origin: timedelta, label: PeriodLabel
    ) -> "TimeGrid":
        if step <= timedelta(0):
            raise ValueError(f"step must be positive, got {step}")
        validate_whole_minutes(step, "step")
        validate_divides_day(step, "step")
        if not isinstance(label, PeriodLabel):
            raise ValueError(f"label must be a PeriodLabel, got {label!r}")
        validate_whole_minutes(origin, "origin")
        if not timedelta(0) <= origin < step:
            raise ValueError(f"origin must satisfy 0 <= origin < step, got {origin}")
        return super().__new__(cls, step, origin, label)

    def _replace(self, **kwargs: Any) -> "TimeGrid":
        fields = {**self._asdict(), **kwargs}
        return TimeGrid(**fields)

    @classmethod
    def _make(cls, iterable: Iterable[Any]) -> "TimeGrid":  # type: ignore[override]
        return cls(*iterable)


GridDeclaration: TypeAlias = TimeGrid | Unknown


class TimeAnchor(BaseModel):
    model_config = ConfigDict(frozen=True)

    origin: timedelta | Unknown = Unknown.UNKNOWN
    label: PeriodLabel = PeriodLabel.UNKNOWN

    @field_validator("origin")
    @classmethod
    def _check_origin(cls, v: timedelta | Unknown) -> timedelta | Unknown:
        if isinstance(v, timedelta):
            validate_whole_minutes(v, "origin")
            if v < timedelta(0):
                raise ValueError(f"origin must be >= 0, got {v}")
        return v


class TrainingGridDeclaration(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    grid: GridDeclaration = Unknown.UNKNOWN


class Compatibility(Enum):
    COMPATIBLE = "compatible"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


def _differences(deployment: TimeGrid, declared: TimeGrid) -> tuple[str, ...]:
    return tuple(
        name
        for name in ("step", "origin", "label")
        if getattr(deployment, name) != getattr(declared, name)
    )


def compatibility(
    deployment: GridDeclaration, declared: GridDeclaration
) -> Compatibility:
    if isinstance(deployment, Unknown) or isinstance(declared, Unknown):
        return Compatibility.UNKNOWN
    differing = _differences(deployment, declared)
    if differing == ("label",) and PeriodLabel.UNKNOWN in (
        deployment.label,
        declared.label,
    ):
        return Compatibility.UNKNOWN
    if differing:
        return Compatibility.MISMATCH
    if PeriodLabel.UNKNOWN is deployment.label:
        return Compatibility.UNKNOWN
    return Compatibility.COMPATIBLE


class GridMismatchError(ValueError):
    def __init__(
        self, differences: tuple[str, ...], deployment: TimeGrid, declared: TimeGrid
    ) -> None:
        self.differences = differences
        details = ", ".join(
            f"{n}: deployment={getattr(deployment, n)} vs declared={getattr(declared, n)}"
            for n in differences
        )
        super().__init__(f"time grid mismatch ({details})")


def require_compatible(
    deployment: GridDeclaration, declared: GridDeclaration
) -> Compatibility:
    result = compatibility(deployment, declared)
    if result is Compatibility.MISMATCH:
        assert isinstance(deployment, TimeGrid) and isinstance(declared, TimeGrid)
        raise GridMismatchError(
            _differences(deployment, declared), deployment, declared
        )
    return result
