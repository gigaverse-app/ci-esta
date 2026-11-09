"""Timing arithmetic shared by measurements, reporting and drill accounting."""
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, overload


@overload
def elapsed_seconds(start: datetime | None, end: datetime | None, *, strict: Literal[True]) -> float: ...


@overload
def elapsed_seconds(start: datetime | None, end: datetime | None, *, strict: Literal[False] = False) -> float | None: ...


def elapsed_seconds(start: datetime | None, end: datetime | None, *, strict: bool = False) -> float | None:
    if start is None or end is None or end < start:
        if strict:
            raise ValueError("measurement timestamps unavailable or invalid")
        return None
    return (end - start).total_seconds()


def span_seconds(starts: Iterable[float], ends: Iterable[float]) -> float | None:
    first, last = min(starts, default=None), max(ends, default=None)
    return None if first is None or last is None or last < first else last - first


def format_duration(seconds: float | None, *, rounded: bool = False, hours: bool = True) -> str:
    if seconds is None:
        return "unavailable"
    minutes, secs = divmod(round(seconds) if rounded else int(seconds), 60)
    if hours and minutes >= 60:
        whole_hours, minutes = divmod(minutes, 60)
        return f"{whole_hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"
