from pydantic import BaseModel, Field, field_validator


class RunConfig(BaseModel):
    """Runtime sampling counts for forecast generation and emission.

    num_samples is aleatoric draws per weight. num_weight_samples is epistemic
    weight draws. The pooled num_weight_samples * num_samples draws are the full
    predictive distribution. num_trajectories is how many raw paths to emit
    (<= pool, 0 = none): a retention count, not a generation count.
    """

    quantile_levels: list[float] | None = None
    num_weight_samples: int | None = Field(default=None, gt=0)
    num_trajectories: int | None = Field(default=None, ge=0)
    num_samples: int | None = Field(default=None, gt=0)

    @field_validator("quantile_levels")
    @classmethod
    def _validate_levels(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        for level in v:
            if not (0 < level < 1):
                raise ValueError(f"quantile levels must be in (0, 1), got {level}")
        return v
