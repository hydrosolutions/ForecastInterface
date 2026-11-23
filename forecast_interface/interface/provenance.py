import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from forecast_interface.common.temporal import UtcDatetime

from .artifact import TrainedArtifact

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UnknownReason(Enum):
    NOT_SUPPLIED = "NOT_SUPPLIED"
    UNRECOVERABLE = "UNRECOVERABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"


class UnknownProvenance(_Frozen):
    reason: UnknownReason


_NOT_SUPPLIED = UnknownProvenance(reason=UnknownReason.NOT_SUPPLIED)


def _not_supplied() -> UnknownProvenance:
    return _NOT_SUPPLIED


class ExposureComponent(Enum):
    WEIGHTS = "WEIGHTS"
    NORMALISATION = "NORMALISATION"
    FEATURE_SELECTION = "FEATURE_SELECTION"
    OTHER = "OTHER"


class ExposureRole(Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    EARLY_STOPPING = "EARLY_STOPPING"
    FIT = "FIT"


class StageKind(Enum):
    INITIAL = "INITIAL"
    PRETRAIN = "PRETRAIN"
    FINE_TUNE = "FINE_TUNE"
    CONTINUE = "CONTINUE"


class ProvenanceStatus(Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    ABSENT = "ABSENT"


class ConfigIdentity(_Frozen):
    algorithm: Literal["sha256"]
    digest: str

    @field_validator("digest")
    @classmethod
    def _hex_digest(cls, v: str) -> str:
        if not _SHA256_HEX.fullmatch(v):
            raise ValueError("sha256 digest must be 64 lowercase hex characters")
        return v


class ArtifactRef(_Frozen):
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _hex_digest(cls, v: str) -> str:
        if not _SHA256_HEX.fullmatch(v):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return v


class ExposureScope(_Frozen):
    stations: tuple[_NonEmptyStr, ...] | None = None
    region: _NonEmptyStr | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ExposureScope":
        if (self.stations is None) == (self.region is None):
            raise ValueError("scope needs exactly one of stations or region")
        if self.stations is not None and not self.stations:
            raise ValueError("stations must be non-empty")
        return self


class Exposure(_Frozen):
    component: ExposureComponent
    role: ExposureRole
    scope: ExposureScope
    start: UtcDatetime
    end: UtcDatetime

    @model_validator(mode="after")
    def _start_before_end(self) -> "Exposure":
        if self.start >= self.end:
            raise ValueError(f"start {self.start} must precede end {self.end}")
        return self


def _check_order(earlier: object, later: object, names: str) -> None:
    if isinstance(earlier, datetime) and isinstance(later, datetime):
        if earlier > later:
            raise ValueError(f"ordering violated: {names}")


class TrainingStage(_Frozen):
    kind: StageKind
    # Root stages encode "no parent" as UnknownProvenance(NOT_APPLICABLE).
    parent: ArtifactRef | UnknownProvenance
    training_completed_at: UtcDatetime | UnknownProvenance
    exposures: tuple[Exposure, ...]
    checkpoint_created_at: UtcDatetime | UnknownProvenance = Field(
        default_factory=_not_supplied
    )

    @model_validator(mode="after")
    def _ordered(self) -> "TrainingStage":
        _check_order(
            self.checkpoint_created_at,
            self.training_completed_at,
            "checkpoint_created_at <= training_completed_at",
        )
        return self


class ProvenanceRecord(_Frozen):
    schema_version: Literal[1]
    fi_version: str | UnknownProvenance
    config: ConfigIdentity | UnknownProvenance
    stages: Annotated[tuple[TrainingStage, ...], Field(min_length=1)]
    exported_at: UtcDatetime | UnknownProvenance = Field(default_factory=_not_supplied)
    source_revision: str | UnknownProvenance = Field(default_factory=_not_supplied)
    package_versions: UnknownProvenance | Mapping[str, str] = Field(
        default_factory=_not_supplied, union_mode="left_to_right"
    )
    preprocessing_fitted: tuple[ExposureComponent, ...] | UnknownProvenance = Field(
        default_factory=_not_supplied
    )

    @model_validator(mode="after")
    def _ordered(self) -> "ProvenanceRecord":
        for stage in self.stages:
            _check_order(
                stage.training_completed_at,
                self.exported_at,
                "training_completed_at <= exported_at",
            )
            _check_order(
                stage.checkpoint_created_at,
                self.exported_at,
                "checkpoint_created_at <= exported_at",
            )
        return self


_PREPROCESSING = (ExposureComponent.NORMALISATION, ExposureComponent.FEATURE_SELECTION)


def _stage_complete(
    stage: TrainingStage, required: frozenset[ExposureComponent]
) -> bool:
    has_weights = any(
        e.component is ExposureComponent.WEIGHTS and e.role is ExposureRole.TRAIN
        for e in stage.exposures
    )
    present = {e.component for e in stage.exposures}
    known_completion = not isinstance(stage.training_completed_at, UnknownProvenance)
    return known_completion and has_weights and required <= present


def provenance_status(
    record: ProvenanceRecord | UnknownProvenance,
) -> ProvenanceStatus:
    """Completeness only; no status asserts that evaluation data were independent."""
    if isinstance(record, UnknownProvenance):
        return ProvenanceStatus.ABSENT
    if isinstance(record.preprocessing_fitted, UnknownProvenance):
        return ProvenanceStatus.PARTIAL
    listed = {
        e.component
        for stage in record.stages
        for e in stage.exposures
        if e.component in _PREPROCESSING
    }
    required = frozenset(listed | set(record.preprocessing_fitted))
    complete = all(_stage_complete(s, required) for s in record.stages)
    return ProvenanceStatus.COMPLETE if complete else ProvenanceStatus.PARTIAL


@runtime_checkable
class ProvenanceDeclaringArtifact(TrainedArtifact, Protocol):
    @property
    def provenance(self) -> ProvenanceRecord | UnknownProvenance: ...


def parse_provenance(
    data: str | bytes | Mapping[str, Any],
) -> ProvenanceRecord | UnknownProvenance:
    raw: Any = json.loads(data) if isinstance(data, str | bytes) else dict(data)
    if not isinstance(raw, dict):
        raise ValueError("provenance JSON must be an object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        return UnknownProvenance(reason=UnknownReason.UNSUPPORTED_VERSION)
    return ProvenanceRecord.model_validate(raw)


def artifact_provenance(
    artifact: TrainedArtifact,
) -> ProvenanceRecord | UnknownProvenance:
    try:
        declared = getattr(artifact, "provenance")
    except AttributeError:
        logger.debug("%r declares no provenance (legacy artifact)", type(artifact))
        return _NOT_SUPPLIED
    except Exception:
        logger.warning("provenance getter raised on %r", type(artifact), exc_info=True)
        return _NOT_SUPPLIED
    if isinstance(declared, ProvenanceRecord | UnknownProvenance):
        return declared
    if isinstance(declared, str | bytes | Mapping):
        try:
            return parse_provenance(declared)
        except (ValueError, ValidationError):
            logger.warning("malformed provenance on %r", type(artifact), exc_info=True)
            return _NOT_SUPPLIED
    logger.warning("provenance on %r is ill-typed: %r", type(artifact), declared)
    return _NOT_SUPPLIED


class ManifestDigestError(Exception):
    pass


class ProvenanceManifest(_Frozen):
    artifact_sha256: str
    record: ProvenanceRecord

    @field_validator("artifact_sha256")
    @classmethod
    def _hex_digest(cls, v: str) -> str:
        if not _SHA256_HEX.fullmatch(v):
            raise ValueError("artifact_sha256 must be 64 lowercase hex characters")
        return v


def bind_manifest(
    artifact_bytes: bytes, record: ProvenanceRecord
) -> ProvenanceManifest:
    return ProvenanceManifest(
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(), record=record
    )


def verify_manifest(manifest: ProvenanceManifest, artifact_bytes: bytes) -> None:
    actual = hashlib.sha256(artifact_bytes).hexdigest()
    if actual != manifest.artifact_sha256:
        raise ManifestDigestError(
            f"artifact digest mismatch: expected {manifest.artifact_sha256[:12]}..., "
            f"got {actual[:12]}..."
        )


def manifest_to_json(manifest: ProvenanceManifest) -> str:
    return manifest.model_dump_json()


def manifest_from_json(data: str | bytes) -> ProvenanceManifest:
    return ProvenanceManifest.model_validate_json(data)
