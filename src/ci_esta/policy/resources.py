"""Resource and placement contracts extracted from AI's exercised resolver.

The project owns provider registrations and credential discovery. This module is
pure: it never reads credentials, starts a service, or acquires an account lease.
"""

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ci_esta.policy.models import Requirement

EnvScope = str
ExecutionMode = Literal["runner", "kubernetes_job"]
RequiresPin = Requirement


class KubernetesJobProfile(BaseModel):
    """
    The bundle of fields the workflow's kubernetes_job code path needs to build a pytest Job pod.

    Attached to providers that resolve to ``kubernetes_job`` mode so the selector can fail at selection time
    when a cluster_internal provider lacks its profile, instead of failing late inside the Job step with an empty
    image/service setup.
    """

    model_config = ConfigDict(frozen=True)

    service: str = Field(
        ...,
        description="Service name used both for the Docker image build and as the K8s service identity.",
    )
    service_account: str = Field(
        default="default",
        description="ServiceAccount used by the Job for IAM/IRSA.",
    )
    config_map: str | None = Field(
        default=None,
        description=("Name of the ConfigMap to mount as env. Resolved by the consumer when omitted."),
    )
    timeout_seconds: int = Field(
        default=600,
        description="Active deadline for the Job pod.",
    )


class ServiceContainer(BaseModel):
    """
    Definition of a runner-side ephemeral container — maps 1:1 to one entry of GitHub Actions' ``services:`` block.

    Provided by ephemeral providers (``image=redis:7-alpine``, etc.) so the
    framework can spin up real-but-disposable infrastructure on the runner
    without paying the k8s round-trip.
    """

    model_config = ConfigDict(frozen=True)

    service_name: str = Field(
        ...,
        description=(
            "Key under ``services:`` in the resulting workflow YAML. Used as the "
            "deduplication key when multiple providers contribute containers — "
            "two containers with the same service_name is a configuration error."
        ),
    )
    image: str = Field(..., description="Container image, e.g. ``redis:7-alpine``.")
    ports: list[str] | None = Field(default=None, description="Optional port mappings, e.g. ``['6379:6379']``.")
    options: str | None = Field(
        default=None,
        description="Raw ``--health-cmd`` / ``--health-interval`` etc. for the container.",
    )
    env: dict[str, str] | None = Field(default=None, description="Environment variables passed into the container.")
    volumes: list[str] | None = Field(default=None, description="Optional volume mounts.")
    credentials: dict[str, str] | None = Field(
        default=None, description="Registry credentials for pulling private images."
    )


class Provider(BaseModel):
    """
    One concrete way to satisfy a :class:`Resource`.

    Providers are ordered within a Resource by *preference* (cheapest first).
    The framework resolves a test's ``requires(...)`` to the first provider
    that is *available* in the current environment (see
    :func:`is_provider_available`). Tests can pin a specific provider with
    ``provider="..."`` when they genuinely need that flavour (e.g. a Lua-script
    test that fakeredis can't execute).

    Combinations of fields encode the placement decision:

    * ``cluster_internal=True`` — placement is forced to ``kubernetes_job``;
      ``runner_secrets`` must be empty (the runner never holds them) and
      ``cluster_secrets`` documents what the in-cluster Job needs from its
      service ConfigMap.
    * Every provider is assumed runnable in the target Kubernetes environment.
      If the runner cannot satisfy ``runner_secrets`` but the selector chooses
      k8s execution, those names are treated as target-env ConfigMap/Secret
      requirements instead of GitHub Actions requirements.
    * ``service_container is not None`` — placement adds a ``services:`` entry on the runner.
    * ``runner_secrets`` non-empty — those secrets must be exported on the runner;
      provider counts as available only when every name is present (and non-empty)
      in the workflow's ``available_secrets`` list (unless we're resolving in
      cluster mode, where target-env config is authoritative).
    * ``runtime_env`` — env vars consumers expect when this provider is the
      chosen one. The workflow's "Start placement services" step exports them
      after the service container is healthy, so tests don't need to special-
      case "is fakeredis or real Redis" — both expose ``GV_REDIS_HOST`` etc.
    * ``env_scope != "any"`` — provider only resolves in that target environment.
    """

    model_config = ConfigDict(frozen=True)

    capabilities: frozenset[str] = frozenset()

    name: str = Field(
        ...,
        description=("Human-readable provider id, unique within its Resource. Tests pin via ``provider=<name>``."),
    )
    runner_secrets: list[str] = Field(
        default_factory=list,
        description=(
            "Env-var names that must be present (non-empty) on the runner for this provider to be available. "
            "Only meaningful for runner-mode providers — by definition the runner can't carry secrets that "
            "only exist inside the target Kubernetes cluster."
        ),
    )
    cluster_secrets: list[str] = Field(
        default_factory=list,
        description=(
            "Env-var names this provider's tests will read from the target environment's service ConfigMap when "
            "running as a Kubernetes Job. Documentation only — the cluster mounts these, the runner never sees them. "
            "Only meaningful for cluster_internal=True providers."
        ),
    )
    runtime_env: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Static env vars the workflow exports after this provider's services are up. Consumed by tests via the "
            "ordinary env mechanism — e.g. fakeredis declares ``{}`` so consumers fall through to their default Redis "
            "host, while ``redis-ephemeral`` declares ``{'GV_REDIS_HOST': 'localhost', 'GV_REDIS_PORT': '6379'}`` so "
            "the same test code reads the right host without a plugin mutating env at collection time."
        ),
    )
    service_container: ServiceContainer | None = Field(
        default=None,
        description=(
            "Runner-side ephemeral container, if this provider needs one. "
            "Mutually compatible with ``runner_secrets`` (a containerized Postgres "
            "still might need a password env var)."
        ),
    )
    cluster_internal: bool = Field(
        default=False,
        description=(
            "True if this provider needs Kubernetes execution — in-cluster DNS, "
            "deployed services, or namespace ConfigMaps. Forces ``kubernetes_job`` mode."
        ),
    )
    kubernetes_job_profile: KubernetesJobProfile | None = Field(
        default=None,
        description=(
            "Required when ``cluster_internal=True`` — declares the image/service/config-map/timeout the workflow "
            "needs to build a Job pod. Without this, the selector fails fast instead of letting the Job step run "
            "with an empty image setup."
        ),
    )
    env_scope: EnvScope = Field(
        default="any",
        description=(
            "Target environment binding. ``any`` resolves under any active env; "
            "``dev`` / ``stg`` / ``prd`` only resolve when the runner targets that env."
        ),
    )

    @field_validator("runner_secrets", "cluster_secrets")
    @classmethod
    def _no_empty_secret_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if not name:
                raise ValueError("secret name cannot be empty")
        return value

    @field_validator("runtime_env")
    @classmethod
    def _no_empty_runtime_env_names(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if not name:
                raise ValueError("runtime_env key cannot be empty")
        return value

    @model_validator(mode="after")
    def _secrets_match_provider_kind(self) -> "Provider":
        if self.cluster_internal and self.runner_secrets:
            raise ValueError(
                f"provider {self.name!r}: cluster_internal=True providers must not declare runner_secrets "
                f"(those don't reach the in-cluster Job); use cluster_secrets instead"
            )
        if not self.cluster_internal and self.cluster_secrets:
            raise ValueError(
                f"provider {self.name!r}: cluster_secrets is only meaningful for cluster_internal=True providers"
            )
        if self.cluster_internal and self.kubernetes_job_profile is None:
            raise ValueError(
                f"provider {self.name!r}: cluster_internal=True providers must carry a kubernetes_job_profile so "
                "the workflow knows which image/service/config-map to use; the selector won't infer it from the area"
            )
        if not self.cluster_internal and self.kubernetes_job_profile is not None:
            raise ValueError(
                f"provider {self.name!r}: kubernetes_job_profile is only meaningful for cluster_internal=True providers"
            )
        return self


class Resource(BaseModel):
    """
    Named external dependency a test can declare via ``@pytest.mark.requires(ResourceName.X)``.

    Holds the ordered list of providers that can satisfy the resource. Order
    is preference: cheapest first, fall back to more expensive providers when
    the cheaper ones aren't available in the current environment.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Resource id, used as the argument to ``requires(...)``.")
    providers: list[Provider] = Field(
        ...,
        min_length=1,
        description="Providers in preference order; the first available wins.",
    )


class Placement(BaseModel):
    """
    Reduction of a test's required-providers list to a CI matrix entry.

    The selector calls :func:`placement_for` per test (or per group of tests
    sharing identical placements) and emits one matrix entry per unique
    placement. The workflow then computes its ``env:`` block from
    :attr:`secrets`, its ``services:`` block from :attr:`services`, and picks
    the runner vs k8s-job code path from :attr:`mode`.
    """

    model_config = ConfigDict(frozen=True)

    mode: ExecutionMode = Field(..., description="Where pytest executes.")
    secrets: list[str] = Field(
        default_factory=list,
        description=(
            "Sorted, deduplicated list of secret env-var names the *runner* must export. Cluster-internal providers "
            "contribute via :attr:`cluster_secrets` instead — those are mounted by the cluster, not by GitHub Actions."
        ),
    )
    cluster_secrets: list[str] = Field(
        default_factory=list,
        description=(
            "Sorted, deduplicated list of env-var names the in-cluster Job needs from its service ConfigMap. "
            "Documentation only — the workflow doesn't pass them, the cluster mounts them. Runner "
            "providers' ``runner_secrets`` are promoted here when the placement is k8s mode."
        ),
    )
    services: list[ServiceContainer] = Field(
        default_factory=list,
        description="Runner-side ``services:`` containers, one per service_name.",
    )
    runtime_env: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Aggregated static env vars the workflow exports after services are up. Union of every chosen provider's "
            "``runtime_env``; conflicting values for the same key raise."
        ),
    )
    env_scope: EnvScope = Field(
        default="any",
        description="Strictest env binding across required providers.",
    )

    @model_validator(mode="after")
    def _services_unique_by_name(self) -> "Placement":
        names = [s.service_name for s in self.services]
        if len(names) != len(set(names)):
            raise ValueError(f"services list has duplicate service_name: {names}")
        return self


def is_provider_available(
    provider: Provider,
    *,
    env_vars: dict[str, str],
    active_env_scope: EnvScope,
    cluster_mode: bool = False,
) -> bool:
    """
    True iff this provider can satisfy a test in the current environment.

    Checks both axes:

    * Every name in :attr:`Provider.runner_secrets` is present in ``env_vars`` with a
      non-empty value. (GitHub passes ``""`` for missing secrets, so empty
      string is treated as unset.) :attr:`Provider.cluster_secrets` is intentionally
      *not* checked here — those come from the in-cluster ConfigMap, never from
      the runner-visible env. When ``cluster_mode=True``, the runner_secrets
      check is skipped: the target environment is assumed to have them. If it
      does not, that is an environment misconfiguration and the in-cluster
      pytest run should fail loudly.
    * The provider's :attr:`Provider.env_scope` is ``"any"`` or matches
      ``active_env_scope`` exactly.

    Pure function — no I/O, no side effects.
    """
    if cluster_mode and provider.service_container is not None:
        # Runner-side ephemeral service containers are not available inside the
        # target environment. Tests that need real target-env infrastructure
        # should pin a cluster_internal provider instead.
        return False
    if not cluster_mode:
        for secret_name in provider.runner_secrets:
            if not env_vars.get(secret_name):
                return False
    if provider.env_scope != "any" and provider.env_scope != active_env_scope:
        return False
    return True


def pick_provider(
    resource: Resource,
    *,
    env_vars: dict[str, str],
    active_env_scope: EnvScope,
    pinned_name: str | None = None,
    cluster_mode: bool = False,
    required_capabilities: frozenset[str] = frozenset(),
) -> Provider | None:
    """
    Return the chosen provider for this resource in the current environment, or ``None`` if none qualify.

    Resolution rules:

    * If ``pinned_name`` is given, that exact provider is returned iff it
      exists and is available; otherwise ``None``. We do **not** silently
      fall back to a different provider — pinning means the test author
      asserted "no other provider is acceptable here," and silently
      substituting would produce false-green tests.
    * Otherwise, return the first available provider in preference order.

    ``cluster_mode`` is forwarded to :func:`is_provider_available`. The selector
    uses a two-pass resolution: pass 1 with ``cluster_mode=False``; if any
    chosen provider is ``cluster_internal``, pass 2 with ``cluster_mode=True``
    so runner-secret providers can resolve against target-env config.
    """
    if pinned_name is not None:
        for provider in resource.providers:
            if provider.name == pinned_name:
                if not required_capabilities.issubset(provider.capabilities):
                    return None
                if is_provider_available(
                    provider,
                    env_vars=env_vars,
                    active_env_scope=active_env_scope,
                    cluster_mode=cluster_mode,
                ):
                    return provider
                return None
        return None

    for provider in resource.providers:
        if not required_capabilities.issubset(provider.capabilities):
            continue
        if is_provider_available(
            provider, env_vars=env_vars, active_env_scope=active_env_scope, cluster_mode=cluster_mode
        ):
            return provider
    return None


def resolve_pins(
    pins: Iterable[RequiresPin | tuple[str, str | None]],
    *,
    resources: Mapping[str, Resource],
    env_vars: Mapping[str, str],
    active_env_scope: EnvScope,
    cluster_mode: bool = False,
) -> tuple[list[Provider], list[str]]:
    """
    Resolve a single test's ``requires(...)`` declarations against the supplied registry.

    Returns ``(chosen_providers, skip_reasons)``. Both the pytest plugin (``tests/_resource_plugin.py``) and the
    CI selector (``.github/scripts/test-lanes/select-expensive-tests.py``) call this with their own pin shapes:

    * The plugin extracts pins from ``pytest.Mark.args`` at collection time.
    * The selector reads pins from the pytest collection JSON emitted by the plugin.

    The plugin runs single-pass (cluster_mode comes from the ``GV_TEST_RESOURCE_CLUSTER_MODE`` env var on the
    in-cluster Job). The selector wraps this in an outer two-pass loop: first ``cluster_mode=False``, retrying with
    ``cluster_mode=True`` whenever any chosen provider is ``cluster_internal`` so runner-secret pins resolve from the
    target environment instead of from GitHub Actions secrets.

    Pure function — no I/O, no side effects.
    """
    chosen: list[Provider] = []
    skip_reasons: list[str] = []
    env_vars_dict = dict(env_vars)
    for pin in pins:
        if isinstance(pin, tuple):
            resource_name, pinned = pin
            capabilities = frozenset()
        else:
            resource_name, pinned = pin.resource, pin.provider
            capabilities = pin.capabilities
        resource = resources.get(resource_name)
        if resource is None:
            skip_reasons.append(f"unknown resource: {resource_name!r}")
            continue
        provider = pick_provider(
            resource,
            env_vars=env_vars_dict,
            active_env_scope=active_env_scope,
            pinned_name=pinned,
            cluster_mode=cluster_mode,
            required_capabilities=capabilities,
        )
        if provider is None:
            if pinned:
                skip_reasons.append(f"resource {resource_name!r}: pinned provider {pinned!r} unavailable")
            else:
                skip_reasons.append(f"resource {resource_name!r}: no available provider")
            continue
        chosen.append(provider)
    return chosen, skip_reasons


def placement_for(providers: list[Provider]) -> Placement:
    """
    Reduce a list of resolved providers to a single :class:`Placement`.

    Reduction rules:

    * ``mode``: ``kubernetes_job`` if any provider has ``cluster_internal=True``, else ``runner``.
    * ``secrets``: sorted union across providers' ``runner_secrets``; deduplicated. Runner-secret providers
      contribute to ``cluster_secrets`` instead when the placement is k8s mode (their secrets are in the target
      environment, not in GitHub Actions).
    * ``cluster_secrets``: sorted union of cluster_internal providers' ``cluster_secrets`` PLUS, when mode is k8s,
      runner providers' ``runner_secrets``.
    * ``services``: every provider's ``service_container`` collected; collision
      on ``service_name`` raises (config bug, fail loudly).
    * ``runtime_env``: union of every provider's ``runtime_env``; conflicting values raise.
    * ``env_scope``: strictest of the inputs. ``"any"`` loses to any specific
      scope; two different specific scopes raise (a single matrix entry can't
      target both ``dev`` and ``prd``).

    Pure function. The selector calls this per group of tests with identical
    resolved-provider sets to produce one matrix entry per group.
    """
    mode: ExecutionMode = "kubernetes_job" if any(p.cluster_internal for p in providers) else "runner"

    runner_secrets_set: set[str] = set()
    cluster_secrets_set: set[str] = set()
    for provider in providers:
        if provider.cluster_internal:
            cluster_secrets_set.update(provider.cluster_secrets)
        elif mode == "kubernetes_job":
            # Runner-secret providers running inside a k8s entry: their secrets
            # come from the target environment, not from GitHub Actions.
            cluster_secrets_set.update(provider.runner_secrets)
        else:
            runner_secrets_set.update(provider.runner_secrets)
    secrets = sorted(runner_secrets_set)
    cluster_secrets = sorted(cluster_secrets_set)

    services_by_name: dict[str, ServiceContainer] = {}
    for provider in providers:
        if provider.service_container is None:
            continue
        existing = services_by_name.get(provider.service_container.service_name)
        if existing is not None and existing != provider.service_container:
            raise ValueError(
                "Two providers contribute conflicting service_container entries for "
                f"service_name={provider.service_container.service_name!r}"
            )
        services_by_name[provider.service_container.service_name] = provider.service_container
    services = list(services_by_name.values())

    runtime_env: dict[str, str] = {}
    for provider in providers:
        for key, value in provider.runtime_env.items():
            existing_value = runtime_env.get(key)
            if existing_value is not None and existing_value != value:
                raise ValueError(f"providers contribute conflicting runtime_env values for key {key!r}")
            runtime_env[key] = value

    env_scope = _reduce_env_scope([p.env_scope for p in providers])

    return Placement(
        mode=mode,
        secrets=secrets,
        cluster_secrets=cluster_secrets,
        services=services,
        runtime_env=runtime_env,
        env_scope=env_scope,
    )


def _reduce_env_scope(scopes: list[EnvScope]) -> EnvScope:
    """
    Pick the strictest env_scope across providers; raise on conflict.

    ``"any"`` is the weakest — it loses to anything specific. Two different
    specific scopes (e.g. ``dev`` and ``prd``) cannot be satisfied by a single
    matrix entry, so we raise.
    """
    specific: set[EnvScope] = {s for s in scopes if s != "any"}
    if len(specific) > 1:
        raise ValueError(f"conflicting env_scope values across providers: {sorted(specific)}")
    if specific:
        return specific.pop()
    return "any"
