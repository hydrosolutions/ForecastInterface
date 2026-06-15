from typing import Protocol, runtime_checkable


@runtime_checkable
class TrainedArtifact(Protocol):
    """Opaque, model-defined trained-state object.

    A ``TrainedArtifact`` is produced by ``train`` / ``retrain`` and consumed by
    ``predict`` / ``hindcast``. FI never inspects its internals. It MUST be
    self-contained and deployment-portable: ``serialize_artifact`` produces
    ``bytes`` that embed all weights, scalers and metadata with **no absolute
    filesystem paths** and **no dependence on the training environment**, and
    ``deserialize_artifact`` reconstructs an artifact that runs unchanged on a
    different SAP3 instance.

    Rich provenance metadata (scope, region, training period, hashes, seed,
    product versions) and the group-artifact embedding-key / station-set-mismatch
    contract are deferred to a LATER phase (Phase 4); see
    ``docs/nepal-model-requirements.md`` §4 and §8.

    This is a marker Protocol (no members) used as a semantic boundary type.
    """
