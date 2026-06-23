from enum import Enum


class ArtifactScope(Enum):
    STATION = "station"
    GROUP = "group"
    # A "national-group" model is a GROUP (its station set happens to be national).
    # SAP3 also has an internal VIRTUAL scope for combination models; that is
    # SAP3-internal and not model-author-facing, so it is intentionally omitted here.
