from datetime import datetime

from forecast_interface.common import GridMismatchError

from .failure import FailureCause
from .result import ModelFailure


def grid_mismatch_failure(
    error: GridMismatchError, *, model_name: str, issue_datetime: datetime
) -> ModelFailure:
    return ModelFailure(
        model_name=model_name,
        issue_datetime=issue_datetime,
        cause=FailureCause.GRID_MISMATCH,
        message=str(error),
    )
