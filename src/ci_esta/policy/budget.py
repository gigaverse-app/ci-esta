"""Execution-time budget, after setup and deployment waiting have consumed time."""


def remaining_budget(*, total_seconds: int, elapsed_seconds: int, reserve_seconds: int, requested_seconds: int) -> int:
    """Reserve reporting/cleanup time and fail before starting unbounded work.

    The caller supplies monotonic elapsed time and applies the result to its
    runner's timeout. This does not implement cancellation or kill processes.
    """
    if any(type(value) is not int for value in (total_seconds, elapsed_seconds, reserve_seconds, requested_seconds)):
        raise ValueError("budgets must be integer seconds")
    if total_seconds <= 0 or requested_seconds <= 0 or elapsed_seconds < 0 or reserve_seconds < 0:
        raise ValueError("budgets must be positive and elapsed/reserve nonnegative")
    remaining = min(requested_seconds, total_seconds - elapsed_seconds - reserve_seconds)
    if remaining <= 0:
        raise ValueError("no execution budget remains after reserving cleanup/reporting time")
    return remaining
