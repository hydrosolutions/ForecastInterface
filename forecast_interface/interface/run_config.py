from pydantic import BaseModel, Field, field_validator


class RunConfig(BaseModel):
    quantile_levels: list[float] | None = None
    num_trajectories: int | None = Field(default=None, gt=0)
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
