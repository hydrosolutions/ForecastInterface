import logging
from typing import Protocol, runtime_checkable

from forecast_interface.common import TrainingGridDeclaration, Unknown

logger = logging.getLogger(__name__)


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


@runtime_checkable
class GridDeclaringArtifact(TrainedArtifact, Protocol):
    @property
    def training_grid(self) -> TrainingGridDeclaration: ...


def artifact_training_grid(artifact: TrainedArtifact) -> TrainingGridDeclaration:
    unknown = TrainingGridDeclaration(grid=Unknown.UNKNOWN)
    try:
        if not isinstance(artifact, GridDeclaringArtifact):
            return unknown
        declaration = artifact.training_grid
    except Exception as exc:
        logger.debug("training_grid unreadable on %r: %s", type(artifact), exc)
        return unknown
    if not isinstance(declaration, TrainingGridDeclaration):
        logger.debug(
            "training_grid on %r is not a TrainingGridDeclaration: %r",
            type(artifact),
            declaration,
        )
        return unknown
    return declaration
