"""Versioned contracts for policy inputs and the exact work an executor must prove.

These models contain references and declarations, never credentials. A request is
normalized by a trusted integration; declaring a profile does not grant permission
to a GitHub commenter or provision a resource.
"""

from collections.abc import Iterable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(min_length=1, max_length=300, pattern=r"^[^\r\n]+$")]
Occasion = Literal["pr", "push", "schedule", "deployment", "manual"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Requirement(Contract):
    resource: Name
    provider: Name | None = None
    capabilities: frozenset[Name] = frozenset()


class Work(Contract):
    """An atomic suite or individual test. The adapter chooses the granularity.

    A conformance suite is one unit: admission must never split its validators
    from its tests. IDs and tags are data, never executable command strings.
    """

    id: Name
    tags: frozenset[Name] = frozenset()
    effects: frozenset[Name] = frozenset()
    environment: Name | None = None
    fresh: bool = False
    timeout_seconds: int | None = Field(default=None, gt=0)


class Profile(Contract):
    """A permitted occasion, selection scope and effect ceiling.

    Includes are tags. An empty include set selects no work; '*' selects every
    tag, but still cannot override environment or side-effect constraints.
    """

    extends: Name | None = Field(
        default=None, description="Inherit a built-in or project profile; explicit fields replace inherited fields."
    )
    occasions: frozenset[Occasion] = Field(
        default_factory=lambda: frozenset({"pr", "push", "manual", "schedule", "deployment"})
    )
    include: frozenset[Name] = Field(default_factory=lambda: frozenset({"*"}))
    exclude: frozenset[Name] = frozenset()
    scope: Literal["affected", "all", "explicit"] = "affected"
    allow_effects: frozenset[Name] = frozenset()
    environments: frozenset[Name] = frozenset()
    require_deployment: bool = False
    fresh: bool = False
    budget_seconds: int | None = Field(default=None, gt=0)
    reserve_seconds: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def usable_budget(self) -> "Profile":
        if self.budget_seconds is not None and self.reserve_seconds >= self.budget_seconds:
            raise ValueError("setup/cleanup reserve must leave execution time")
        if self.reserve_seconds and self.budget_seconds is None:
            raise ValueError("a reserve requires a total budget")
        if not self.occasions:
            raise ValueError("profile must allow at least one occasion")
        return self


class Policy(Contract):
    schema_version: Literal["ci-esta/test-policy/v1"] = "ci-esta/test-policy/v1"
    defaults: Literal["v1", "none"] = "v1"
    profiles: dict[Name, Profile] = Field(default_factory=dict)
    work: tuple[Work, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def expand_defaults(cls, value: Any) -> Any:
        from ci_esta.policy.defaults import resolve_profiles

        if isinstance(value, dict):
            value = dict(value)
            value["profiles"] = resolve_profiles(value.get("profiles", {}), value.get("defaults", "v1"))
        return value

    def inventory(self, ids: Iterable[str] | None = None) -> tuple[Work, ...]:
        """Overlay exceptional metadata on the selector's authoritative IDs."""
        if len({work.id for work in self.work}) != len(self.work):
            raise ValueError("inventory work IDs must be unique")
        if ids is None:
            return self.work
        names = tuple(ids)
        if len(set(names)) != len(names):
            raise ValueError("inventory work IDs must be unique")
        metadata = {work.id: work for work in self.work}
        if metadata.keys() - set(names):
            raise ValueError(f"policy metadata references unknown work: {sorted(metadata.keys() - set(names))}")
        return tuple(metadata.get(name, Work(id=name)) for name in names)


class Request(Contract):
    """Trusted context. None affected means unknown and conservatively broadens scope."""

    schema_version: Literal["ci-esta/test-request/v1"] = "ci-esta/test-request/v1"
    profile: Name
    occasion: Occasion
    revision: Name
    environment: Name | None = None
    deployed_revision: Name | None = None
    affected: frozenset[Name] | None = None
    requested: frozenset[Name] | None = None


class Decision(Contract):
    work: Work
    status: Literal["run", "unaffected", "deferred", "unavailable"]
    reason: str
    fresh: bool
    timeout_seconds: int | None = Field(default=None, gt=0)


class ExecutionPlan(Contract):
    schema_version: Literal["ci-esta/test-plan/v1"] = "ci-esta/test-plan/v1"
    request: Request
    decisions: tuple[Decision, ...]
    fallback: bool
    budget_seconds: int | None = Field(default=None, gt=0)
    reserve_seconds: int = Field(default=0, ge=0)

    @property
    def runnable(self) -> tuple[Decision, ...]:
        return tuple(decision for decision in self.decisions if decision.status == "run")

    @property
    def unavailable(self) -> tuple[Decision, ...]:
        return tuple(decision for decision in self.decisions if decision.status == "unavailable")
