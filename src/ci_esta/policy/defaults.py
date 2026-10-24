"""Versioned opinionated defaults. Consumers declare work and only their exceptions."""

from collections.abc import Iterable
from typing import Any

from ci_esta.policy.models import Profile


def builtin_profiles() -> dict[str, Profile]:
    # No default grants side effects. Expensive work can be affected without being
    # permitted; manual-only work additionally requires an explicit probe.
    affected = Profile(occasions={"pr", "push", "manual"}, exclude={"expensive", "manual"})
    affected_deep = Profile(occasions={"pr", "push", "manual", "schedule"}, exclude={"manual"}, fresh=True)
    full = Profile(occasions={"pr", "manual", "schedule"}, exclude={"manual"}, scope="all", fresh=True)
    return {
        "affected": affected,
        "affected_deep": affected_deep,
        "ci": affected,  # Compatibility spelling; new callers use affected.
        "legacy": Profile(),
        "thorough": Profile(occasions={"manual", "schedule"}, exclude={"expensive", "manual"}, scope="all", fresh=True),
        "full": full,
        "deep": affected_deep,  # Compatibility spelling; scope now stays affected.
        "exhaustive": full,
        "weekly": full.model_copy(update={"occasions": frozenset({"manual", "schedule"})}),
        "smoke": Profile(
            occasions={"push", "manual", "deployment"}, include={"smoke"}, exclude={"manual"}, scope="all", fresh=True
        ),
        "performance": Profile(
            occasions={"manual", "schedule"}, include={"performance"}, exclude={"manual"}, scope="all", fresh=True
        ),
        "probe": Profile(occasions={"manual"}, scope="explicit", fresh=True),
    }


def profile_for_run(*, occasion: str, profile: str = "", labels: Iterable[str] = ()) -> str:
    """An explicit profile wins; otherwise select the shared occasion/label defaults.

    Callers authorize label/comment handling before this function. A full label
    takes precedence over affected-deep so an explicit checkpoint stays complete.
    """
    if profile:
        return profile
    if occasion == "schedule":
        return "weekly"
    if occasion == "pr":
        names = set(labels)
        if "test:full" in names:
            return "full"
        if names.intersection({"test:affected-deep", "test:affected_deep", "test:deep"}):
            return "affected_deep"
    return "affected"


def resolve_profiles(overrides: dict[str, Any], defaults: str) -> dict[str, Profile]:
    """Merge fields once. Lists replace, never union; cycles/typos are errors.

    A typed Profile is already resolved and is used exactly as supplied. JSON
    definitions inherit the same-name built-in or an explicit `extends` parent.
    Custom standalone profiles must explicitly declare occasions and include.
    """
    if not isinstance(overrides, dict):
        raise ValueError("profiles must be a mapping")
    resolved = builtin_profiles() if defaults == "v1" else {}
    visiting: set[str] = set()
    completed: set[str] = set()

    def resolve(name: str) -> Profile:
        if name in completed or name not in overrides:
            if name not in resolved:
                raise ValueError(f"unknown inherited profile: {name}")
            return resolved[name]
        if name in visiting:
            raise ValueError(f"profile inheritance cycle at {name}")
        visiting.add(name)
        raw = overrides[name]
        if isinstance(raw, Profile) and raw.extends is not None:
            raw = raw.model_dump(exclude_unset=True)
        if isinstance(raw, Profile):
            result = raw
        else:
            if not isinstance(raw, dict):
                raise ValueError(f"profile {name} must be an object")
            fields = dict(raw)
            parent = fields.pop("extends", None)
            if parent is not None:
                base = resolve(parent)
            else:
                base = resolved.get(name)
            if base is None and not {"occasions", "include"}.issubset(fields):
                raise ValueError(f"custom profile {name} needs extends or explicit occasions and include")
            result = Profile.model_validate({**(base.model_dump() if base else {}), **fields})
        resolved[name] = result
        visiting.remove(name)
        completed.add(name)
        return result

    for name in overrides:
        resolve(name)
    return resolved
