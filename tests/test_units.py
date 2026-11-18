from forecast_interface.common import Unit

_RATES = frozenset(
    {
        Unit.M3_PER_S,
        Unit.MM_PER_DAY,
        Unit.MM_PER_S,
        Unit.M_PER_S,
        Unit.MM_PER_HOUR,
        Unit.W_PER_M2,
    }
)
_NON_RATES = frozenset(
    {Unit.MM, Unit.CM, Unit.M, Unit.DEG_C, Unit.UNITLESS, Unit.PERCENT, Unit.DEGREE}
)


class TestUnitIsRate:
    def test_every_member_is_classified_deliberately(self) -> None:
        assert _RATES | _NON_RATES == frozenset(Unit)
        assert not _RATES & _NON_RATES

    def test_rate_members_are_rates(self) -> None:
        assert all(unit.is_rate for unit in _RATES)

    def test_non_rate_members_are_not_rates(self) -> None:
        assert not any(unit.is_rate for unit in _NON_RATES)
