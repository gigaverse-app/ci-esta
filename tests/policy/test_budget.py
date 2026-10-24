import pytest

from ci_esta.policy.budget import remaining_budget


def test_slow_deployment_wait_cannot_spend_cleanup_reserve():
    assert (
        remaining_budget(total_seconds=7200, elapsed_seconds=1800, reserve_seconds=900, requested_seconds=5400) == 4500
    )


@pytest.mark.parametrize("elapsed", [6300, 7200])
def test_exhausted_budget_fails_instead_of_turning_timeout_off(elapsed):
    with pytest.raises(ValueError, match="no execution budget"):
        remaining_budget(total_seconds=7200, elapsed_seconds=elapsed, reserve_seconds=900, requested_seconds=5400)
