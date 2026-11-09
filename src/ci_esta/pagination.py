"""GitHub's bounded page protocol, independent of the HTTP or CLI transport."""
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def collect_pages(fetch: Callable[[int], list[T]], *, page_size: int = 100) -> list[T]:
    items: list[T] = []
    page = 1
    while True:
        batch = fetch(page)
        items.extend(batch)
        if len(batch) < page_size:
            return items
        page += 1
