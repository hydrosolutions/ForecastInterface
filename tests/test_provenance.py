import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from forecast_interface.interface import (
    ArtifactRef,
    ConfigIdentity,
    Exposure,
    ExposureComponent,
    ExposureRole,
    ExposureScope,
    ManifestDigestError,
    ProvenanceDeclaringArtifact,
    ProvenanceRecord,
    ProvenanceStatus,
    StageKind,
    TrainingStage,
    UnknownProvenance,
    UnknownReason,
    artifact_provenance,
    bind_manifest,
    manifest_from_json,
    manifest_to_json,
    parse_provenance,
    provenance_status,
    verify_manifest,
)
from forecast_interface.interface import provenance as provenance_module

_T0 = datetime(2026, 6, 1, 8, tzinfo=timezone.utc)
_T1 = datetime(2026, 6, 2, 11, tzinfo=timezone.utc)
_T2 = datetime(2026, 6, 3, 9, tzinfo=timezone.utc)
_DIGEST = "a" * 64


def _unknown(reason: UnknownReason) -> UnknownProvenance:
    return UnknownProvenance(reason=reason)


def _exposure(
    component: ExposureComponent = ExposureComponent.WEIGHTS,
    role: ExposureRole = ExposureRole.TRAIN,
    stations: tuple[str, ...] = ("A", "B"),
) -> Exposure:
    return Exposure(
        component=component,
        role=role,
        scope=ExposureScope(stations=stations),
        start=datetime(2000, 1, 1, tzinfo=timezone.utc),
        end=datetime(2019, 12, 31, tzinfo=timezone.utc),
    )


def _stage(**overrides: Any) -> TrainingStage:
    fields: dict[str, Any] = {
        "kind": StageKind.INITIAL,
        "parent": _unknown(UnknownReason.NOT_APPLICABLE),
        "training_completed_at": _T1,
        "exposures": (_exposure(),),
    }
    return TrainingStage(**{**fields, **overrides})


def _record(**overrides: Any) -> ProvenanceRecord:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "fi_version": "0.3.0",
        "config": ConfigIdentity(algorithm="sha256", digest=_DIGEST),
        "stages": (_stage(),),
        "preprocessing_fitted": (),
    }
    return ProvenanceRecord(**{**fields, **overrides})


class _Legacy:
    pass


class _Declaring:
    def __init__(self, value: Any) -> None:
        self._value = value

    @property
    def provenance(self) -> Any:
        return self._value


class _Raising:
    @property
    def provenance(self) -> ProvenanceRecord:
        raise RuntimeError("boom")


class TestRecordRoundTrip:
    def test_json_round_trip_full_record(self) -> None:
        record = _record(
            exported_at=_T2,
            source_revision=_unknown(UnknownReason.UNRECOVERABLE),
            package_versions={"aquacast": "0.1.346"},
        )
        restored = ProvenanceRecord.model_validate_json(record.model_dump_json())
        assert restored == record

    def test_json_round_trip_all_unknown_defaults(self) -> None:
        record = _record(fi_version=_unknown(UnknownReason.NOT_SUPPLIED))
        restored = ProvenanceRecord.model_validate_json(record.model_dump_json())
        assert restored == record
        assert restored.source_revision == _unknown(UnknownReason.NOT_SUPPLIED)

    def test_unknown_defaults_are_explicit_never_none(self) -> None:
        record = _record()
        assert isinstance(record.exported_at, UnknownProvenance)
        assert isinstance(record.package_versions, UnknownProvenance)
        assert isinstance(record.stages[0].checkpoint_created_at, UnknownProvenance)

    def test_multi_stage_with_different_scopes_round_trips(self) -> None:
        pretrain = _stage(kind=StageKind.PRETRAIN)
        fine_tune = _stage(
            kind=StageKind.FINE_TUNE,
            parent=ArtifactRef(sha256=_DIGEST),
            exposures=(_exposure(stations=("C",)),),
        )
        record = _record(stages=(pretrain, fine_tune))
        restored = ProvenanceRecord.model_validate_json(record.model_dump_json())
        assert restored.stages[0].exposures[0].scope.stations == ("A", "B")
        assert restored.stages[1].exposures[0].scope.stations == ("C",)
        assert restored.stages[1].parent == ArtifactRef(sha256=_DIGEST)


class TestValidation:
    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            _stage(training_completed_at=datetime(2026, 6, 2, 11))

    def test_non_utc_offset_rejected(self) -> None:
        local = datetime(2026, 6, 2, 11, tzinfo=timezone(timedelta(hours=5)))
        with pytest.raises(ValidationError, match="UTC"):
            _stage(training_completed_at=local)

    @pytest.mark.parametrize("delta", [timedelta(0), timedelta(days=-1)])
    def test_exposure_start_must_precede_end(self, delta: timedelta) -> None:
        with pytest.raises(ValidationError, match="must precede"):
            Exposure(
                component=ExposureComponent.WEIGHTS,
                role=ExposureRole.TRAIN,
                scope=ExposureScope(region="nepal"),
                start=_T1,
                end=_T1 + delta,
            )

    def test_checkpoint_after_completion_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ordering violated"):
            _stage(checkpoint_created_at=_T2)

    def test_completion_after_export_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ordering violated"):
            _record(exported_at=_T0)

    def test_unknown_timestamp_skips_ordering(self) -> None:
        stage = _stage(
            training_completed_at=_unknown(UnknownReason.UNRECOVERABLE),
            checkpoint_created_at=_T2,
        )
        assert _record(stages=(stage,))

    def test_scope_needs_exactly_one_of_stations_or_region(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            ExposureScope()
        with pytest.raises(ValidationError, match="exactly one"):
            ExposureScope(stations=("A",), region="x")

    def test_scope_rejects_empty_station_name_and_empty_tuple(self) -> None:
        with pytest.raises(ValidationError, match="at least 1"):
            ExposureScope(stations=("",))
        with pytest.raises(ValidationError, match="non-empty"):
            ExposureScope(stations=())

    def test_config_digest_length_checked(self) -> None:
        with pytest.raises(ValidationError, match="64"):
            ConfigIdentity(algorithm="sha256", digest="abc")

    def test_unknown_algorithm_rejected(self) -> None:
        with pytest.raises(ValidationError, match="sha256"):
            ConfigIdentity(algorithm="md5", digest=_DIGEST)  # type: ignore[arg-type]

    def test_record_requires_a_stage(self) -> None:
        with pytest.raises(ValidationError, match="at least 1"):
            _record(stages=())

    def test_record_is_frozen(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            _record().fi_version = "x"  # type: ignore[misc]


class TestProvenanceStatus:
    def test_unknown_is_absent(self) -> None:
        unknown = _unknown(UnknownReason.NOT_SUPPLIED)
        assert provenance_status(unknown) is ProvenanceStatus.ABSENT

    def test_complete_when_weights_known_and_nothing_else_fitted(self) -> None:
        assert provenance_status(_record()) is ProvenanceStatus.COMPLETE

    def test_unknown_preprocessing_fitted_is_partial(self) -> None:
        record = _record(preprocessing_fitted=_unknown(UnknownReason.NOT_SUPPLIED))
        assert provenance_status(record) is ProvenanceStatus.PARTIAL

    def test_declared_fitted_component_without_exposure_is_partial(self) -> None:
        record = _record(preprocessing_fitted=(ExposureComponent.NORMALISATION,))
        assert provenance_status(record) is ProvenanceStatus.PARTIAL

    def test_declared_fitted_component_with_exposure_is_complete(self) -> None:
        stage = _stage(
            exposures=(
                _exposure(),
                _exposure(ExposureComponent.NORMALISATION, ExposureRole.FIT),
            )
        )
        record = _record(
            stages=(stage,), preprocessing_fitted=(ExposureComponent.NORMALISATION,)
        )
        assert provenance_status(record) is ProvenanceStatus.COMPLETE

    def test_listed_preprocessing_required_in_every_stage(self) -> None:
        with_norm = _stage(
            exposures=(
                _exposure(),
                _exposure(ExposureComponent.NORMALISATION, ExposureRole.FIT),
            )
        )
        record = _record(stages=(with_norm, _stage(kind=StageKind.FINE_TUNE)))
        assert provenance_status(record) is ProvenanceStatus.PARTIAL

    def test_unknown_completion_time_is_partial(self) -> None:
        stage = _stage(training_completed_at=_unknown(UnknownReason.UNRECOVERABLE))
        assert provenance_status(_record(stages=(stage,))) is ProvenanceStatus.PARTIAL

    def test_missing_weights_train_exposure_is_partial(self) -> None:
        stage = _stage(exposures=())
        assert provenance_status(_record(stages=(stage,))) is ProvenanceStatus.PARTIAL

    def test_early_stopping_alone_is_not_weights_train(self) -> None:
        stage = _stage(exposures=(_exposure(role=ExposureRole.EARLY_STOPPING),))
        assert provenance_status(_record(stages=(stage,))) is ProvenanceStatus.PARTIAL

    def test_early_stopping_window_is_an_exposure_entry(self) -> None:
        stage = _stage(
            exposures=(
                _exposure(),
                _exposure(role=ExposureRole.EARLY_STOPPING, stations=("A",)),
            )
        )
        record = _record(stages=(stage,))
        roles = [e.role for e in record.stages[0].exposures]
        assert ExposureRole.EARLY_STOPPING in roles
        assert provenance_status(record) is ProvenanceStatus.COMPLETE


class TestArtifactProvenance:
    def test_legacy_artifact_is_not_supplied(self) -> None:
        result = artifact_provenance(_Legacy())
        assert result == _unknown(UnknownReason.NOT_SUPPLIED)

    def test_declared_record_returned(self) -> None:
        record = _record()
        assert artifact_provenance(_Declaring(record)) == record

    def test_raising_getter_is_unknown_not_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = artifact_provenance(_Raising())
        assert result == _unknown(UnknownReason.NOT_SUPPLIED)
        assert "getter raised" in caplog.text

    def test_ill_typed_value_is_not_supplied(self) -> None:
        result = artifact_provenance(_Declaring(42))
        assert result == _unknown(UnknownReason.NOT_SUPPLIED)

    def test_future_schema_version_is_unsupported(self) -> None:
        future = {"schema_version": 2, "anything": "goes"}
        result = artifact_provenance(_Declaring(future))
        assert result == _unknown(UnknownReason.UNSUPPORTED_VERSION)

    def test_malformed_current_version_is_not_supplied(self) -> None:
        result = artifact_provenance(_Declaring({"schema_version": 1}))
        assert result == _unknown(UnknownReason.NOT_SUPPLIED)

    def test_json_string_getter_is_parsed(self) -> None:
        record = _record()
        assert artifact_provenance(_Declaring(record.model_dump_json())) == record

    def test_conforming_artifact_matches_protocol(self) -> None:
        assert isinstance(_Declaring(_record()), ProvenanceDeclaringArtifact)
        assert not isinstance(_Legacy(), ProvenanceDeclaringArtifact)

    def test_parse_provenance_future_version(self) -> None:
        result = parse_provenance(json.dumps({"schema_version": 99}))
        assert result == _unknown(UnknownReason.UNSUPPORTED_VERSION)

    def test_record_survives_serialized_artifact_bytes(self) -> None:
        record = _record()
        payload = record.model_dump_json().encode()
        assert parse_provenance(payload) == record


class TestManifest:
    def test_bind_then_verify_passes(self) -> None:
        data = b"artifact-bytes"
        manifest = bind_manifest(data, _record())
        assert manifest.artifact_sha256 == hashlib.sha256(data).hexdigest()
        verify_manifest(manifest, data)

    def test_verify_mismatch_raises_naming_digests(self) -> None:
        manifest = bind_manifest(b"original", _record())
        with pytest.raises(ManifestDigestError, match="expected") as excinfo:
            verify_manifest(manifest, b"tampered")
        actual = hashlib.sha256(b"tampered").hexdigest()[:12]
        assert manifest.artifact_sha256[:12] in str(excinfo.value)
        assert actual in str(excinfo.value)

    def test_manifest_json_round_trip(self) -> None:
        manifest = bind_manifest(b"x", _record(exported_at=_T2))
        assert manifest_from_json(manifest_to_json(manifest)) == manifest
        assert manifest_from_json(manifest_to_json(manifest).encode()) == manifest

    def test_manifest_rejects_bad_digest(self) -> None:
        raw = bind_manifest(b"x", _record()).model_dump(mode="json")
        raw["artifact_sha256"] = "zz"
        with pytest.raises(ValidationError, match="64"):
            manifest_from_json(json.dumps(raw))


class TestNoClockOrFilesystem:
    def test_module_does_not_read_clock_or_files(self) -> None:
        source = inspect.getsource(provenance_module)
        for forbidden in ("now(", "utcnow", "time.time", "st_mtime", "open(", "Path"):
            assert forbidden not in source
