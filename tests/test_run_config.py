from pydantic import ValidationError
import pytest

from forecast_interface import RunConfig


class TestRunConfig:
    def test_empty_config_valid(self) -> None:
        config = RunConfig()

        assert config.quantile_levels is None
        assert config.num_weight_samples is None
        assert config.num_trajectories is None
        assert config.num_samples is None

    def test_four_fields_validate(self) -> None:
        config = RunConfig(
            quantile_levels=[0.1, 0.5, 0.9],
            num_trajectories=50,
            num_samples=100,
            num_weight_samples=5,
        )

        assert config.quantile_levels == [0.1, 0.5, 0.9]
        assert config.num_weight_samples == 5
        assert config.num_trajectories == 50
        assert config.num_samples == 100

    @pytest.mark.parametrize(
        "quantile_levels",
        ([0.1, 0.5, 1.0], [0.0, 0.5, 0.9], [-0.1, 0.5, 0.9]),
    )
    def test_quantile_level_out_of_range_raises(
        self,
        quantile_levels: list[float],
    ) -> None:
        with pytest.raises(ValidationError, match="quantile levels must be in"):
            RunConfig(quantile_levels=quantile_levels)

    def test_negative_counts_raise(self) -> None:
        with pytest.raises(ValidationError):
            RunConfig(num_trajectories=-1)

        with pytest.raises(ValidationError):
            RunConfig(num_samples=0)

    def test_num_weight_samples_validates(self) -> None:
        config = RunConfig(num_weight_samples=3)

        assert config.num_weight_samples == 3

        with pytest.raises(ValidationError):
            RunConfig(num_weight_samples=0)

    def test_num_trajectories_zero_allowed(self) -> None:
        config = RunConfig(num_trajectories=0)

        assert config.num_trajectories == 0

        with pytest.raises(ValidationError):
            RunConfig(num_trajectories=-1)
