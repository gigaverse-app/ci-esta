"""GitHub job naming conventions, independent of any test runner."""


def job_family(name: str) -> str:
    """
    A job's name without its matrix suffix.

    GitHub names an expanded matrix job `tests (3.11)` but a skipped matrix, which never expands,
    `tests (${{ matrix.python }})`: both belong to the family `tests`.
    """
    return name.split(" (", 1)[0]


