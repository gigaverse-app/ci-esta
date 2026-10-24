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


def main() -> None:
    """CLI for runners that reserve cleanup time before launching a command."""
    import argparse
    import os
    import time
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--started-at", type=int, required=True)
    parser.add_argument("--reserve", type=int, required=True)
    parser.add_argument("--requested", type=int, required=True)
    parser.add_argument("--resolution", type=int, choices=[1, 60], default=1)
    args = parser.parse_args()
    elapsed = int(time.time()) - args.started_at
    if elapsed < 0:
        raise ValueError("job start cannot be in the future")
    elapsed = elapsed // args.resolution * args.resolution
    seconds = remaining_budget(
        total_seconds=args.total,
        elapsed_seconds=elapsed,
        reserve_seconds=args.reserve,
        requested_seconds=args.requested,
    )
    print(f"Execution budget: {seconds} seconds; {args.reserve} seconds reserved for cleanup/reporting")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(f"seconds={seconds}\n")


if __name__ == "__main__":
    main()
