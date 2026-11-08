"""Rules: the one way to say "when these files change, run that".

Every customization is a rule with a name, the files it watches and what it selects. CI-esta's own
defaults are named rules too, so a repository can read them (`ci-esta lanes`), replace one by giving a
rule the same name, or switch one off with `disable_rules`:

| Built-in rule | Watches | Selects |
| --- | --- | --- |
| `python-environment` | `pyproject.toml`, lockfiles, requirements and pytest configuration | every lane |
| `bun-environment` | `package.json`, `bun.lock`, `bunfig*.toml`, `tsconfig*.json` | every lane with Bun tests |

A rule selects `all`, `lane:NAME`, `job:WORKFLOW#JOB` (the lanes that job runs) or `package` (the lanes
of the jobs that build the package). Patterns match repository paths like gitignore patterns.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pytest_selective.impact_graph import matches
from pytest_selective.input_policy import DEFAULT_GLOBAL_INPUTS

PYTHON_ENVIRONMENT = "python-environment"
BUN_ENVIRONMENT = "bun-environment"
BUN_ENVIRONMENT_FILES = [
    pattern
    for name in ("package.json", "bun.lock", "bun.lockb", "bunfig*.toml", "tsconfig*.json")
    for pattern in (name, f"**/{name}")
]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    #: Repository path patterns; a change to any of them fires the rule.
    when: list[str] = Field(min_length=1)
    #: `all`, `lane:NAME`, `job:WORKFLOW#JOB` or `package`.
    select: list[str] = Field(min_length=1)
    reason: str = ""
    #: Where the rule came from, for people reading `ci-esta lanes`.
    origin: Literal["built-in", "lane file"] = "lane file"

    @field_validator("select")
    @classmethod
    def known_targets(cls, values: list[str]) -> list[str]:
        for value in values:
            if value not in {"all", "package", "bun"} and not value.startswith(("lane:", "job:")):
                raise ValueError(f"select {value!r}: use all, package, lane:NAME or job:WORKFLOW#JOB")
        return values

    def fired_by(self, changed: set[str]) -> list[str]:
        return sorted(path for path in changed if matches(path, self.when))


BUILT_IN = [
    Rule(
        name=PYTHON_ENVIRONMENT,
        when=list(DEFAULT_GLOBAL_INPUTS),
        select=["all"],
        reason="the Python environment every test runs in",
        origin="built-in",
    ),
    Rule(
        name=BUN_ENVIRONMENT,
        when=BUN_ENVIRONMENT_FILES,
        select=["bun"],
        reason="the Bun environment every Bun test runs in",
        origin="built-in",
    ),
]


def effective(custom: list[Rule], disabled: list[str]) -> list[Rule]:
    """Built-in rules, replaced by a custom rule of the same name or removed by `disabled`, then the rest."""
    unknown = sorted(set(disabled) - {rule.name for rule in BUILT_IN} - {rule.name for rule in custom})
    if unknown:
        raise ValueError(f"disable_rules names no rule: {', '.join(unknown)}")
    names = [rule.name for rule in custom]
    if duplicates := sorted({name for name in names if names.count(name) > 1}):
        raise ValueError(f"rules named more than once: {', '.join(duplicates)}")
    replaced = {rule.name: rule for rule in custom}
    rules = [replaced.pop(rule.name, rule) for rule in BUILT_IN]
    rules += [rule for rule in custom if rule.name in replaced]
    return [rule for rule in rules if rule.name not in disabled]


def by_name(rules: list[Rule], name: str) -> Rule | None:
    return next((rule for rule in rules if rule.name == name), None)
