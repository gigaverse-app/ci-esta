"""Pure admission from an authoritative inventory and one normalized request."""

from ci_esta.policy.models import Decision, ExecutionPlan, Policy, Profile, Request, Work


def _decision(work: Work, profile: Profile, request: Request) -> Decision:
    fresh = work.fresh or profile.fresh or request.occasion in {"schedule", "deployment", "manual"}
    timeout = work.timeout_seconds
    if profile.budget_seconds is not None:
        remaining = profile.budget_seconds - profile.reserve_seconds
        timeout = min(timeout, remaining) if timeout is not None else remaining
    status = "run"
    reason = f"admitted by profile {request.profile}"
    tags = work.tags | {work.id}
    if profile.exclude.intersection(tags):
        status, reason = "deferred", "work tags are excluded by this profile"
    elif "*" not in profile.include and not profile.include.intersection(tags):
        status, reason = "deferred", "work tags are outside this profile"
    elif not work.effects.issubset(profile.allow_effects):
        status, reason = "deferred", "profile does not permit the declared side effects"
    elif request.requested is not None and work.id not in request.requested:
        status, reason = "deferred", "outside the explicit request"
    elif profile.scope == "affected" and request.requested is None and request.affected is not None:
        if work.id not in request.affected:
            status, reason = "unaffected", "not in the affected scope"
    if status == "run":
        if work.environment is not None and work.environment != request.environment:
            status, reason = "unavailable", f"requires environment {work.environment}"
        elif profile.environments and request.environment not in profile.environments:
            status, reason = "unavailable", "target environment is not permitted by this profile"
        elif profile.require_deployment and (
            request.environment is None or request.deployed_revision != request.revision
        ):
            status, reason = "unavailable", "requested revision is not confirmed deployed in the target environment"
    return Decision(work=work, status=status, reason=reason, fresh=fresh, timeout_seconds=timeout)


def plan(policy: Policy, request: Request, inventory: tuple[Work, ...]) -> ExecutionPlan:
    """Unknown impact broadens only eligible work; explicit requests never silently disappear."""
    profile = policy.profiles.get(request.profile)
    if profile is None:
        raise ValueError(f"unknown profile: {request.profile}")
    if request.occasion not in profile.occasions:
        raise ValueError(f"profile {request.profile} does not permit occasion {request.occasion}")
    ids = {work.id for work in inventory}
    if len(ids) != len(inventory):
        raise ValueError("inventory work IDs must be unique")
    if request.requested is not None and not request.requested:
        raise ValueError("an explicit request must name at least one work unit")
    if profile.scope == "explicit" and request.requested is None:
        raise ValueError("this profile requires an explicit scope")
    if request.requested is not None and request.requested - ids:
        raise ValueError(f"unknown requested work: {sorted(request.requested - ids)}")
    if request.affected is not None and request.affected - ids:
        raise ValueError(f"affected scope contains unknown work: {sorted(request.affected - ids)}")
    decisions = tuple(_decision(work, profile, request) for work in inventory)
    # An explicit request cannot report success after policy filtered out its target.
    rejected = [
        item.work.id
        for item in decisions
        if request.requested and item.work.id in request.requested and item.status == "deferred"
    ]
    if rejected:
        raise ValueError(f"explicit request is outside profile permissions: {rejected}")
    return ExecutionPlan(
        request=request,
        decisions=decisions,
        fallback=profile.scope == "affected" and request.affected is None and request.requested is None,
        budget_seconds=profile.budget_seconds,
        reserve_seconds=profile.reserve_seconds,
    )
