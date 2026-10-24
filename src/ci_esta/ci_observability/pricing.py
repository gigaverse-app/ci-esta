"""Explicit overrides plus a dated, conservative standard-hosted runner price table."""

from decimal import Decimal

from ci_esta.ci_observability.models import ObservedJobV1, RunnerSkuRateV1

PRICING_URL = "https://docs.github.com/en/billing/reference/actions-runner-pricing"
# Verified 2026-10-24. Custom/larger/self-hosted labels require caller configuration.
STANDARD_PRICES = {
    "ubuntu-latest": ("actions_linux", "0.006"),
    "ubuntu-22.04": ("actions_linux", "0.006"),
    "ubuntu-24.04": ("actions_linux", "0.006"),
    "ubuntu-22.04-arm": ("actions_linux_arm", "0.005"),
    "ubuntu-24.04-arm": ("actions_linux_arm", "0.005"),
    "ubuntu-slim": ("actions_linux_slim", "0.002"),
    "windows-latest": ("actions_windows", "0.010"),
    "windows-2022": ("actions_windows", "0.010"),
    "windows-2025": ("actions_windows", "0.010"),
    "windows-11-arm": ("actions_windows_arm", "0.010"),
    "macos-latest": ("actions_macos", "0.062"),
    "macos-14": ("actions_macos", "0.062"),
    "macos-15": ("actions_macos", "0.062"),
    "macos-15-intel": ("actions_macos", "0.062"),
    "macos-26": ("actions_macos", "0.062"),
}


def matching_rate(job: ObservedJobV1, rates: list[RunnerSkuRateV1],
                  repository_private: bool | None) -> RunnerSkuRateV1 | None:
    matches = [rate for rate in rates if rate.runner_label in job.runner_labels]
    if len(matches) > 1:
        raise ValueError(f"runner labels match multiple configured SKUs: {job.runner_labels}")
    if matches:
        return matches[0]
    # Never infer hardware from an OS label in a self-hosted/custom label set.
    if len(job.runner_labels) != 1 or job.runner_labels[0] not in STANDARD_PRICES:
        return None
    label = job.runner_labels[0]
    sku, price = STANDARD_PRICES[label]
    public = repository_private is False
    # Versioned SKU names preserve provenance within the existing v1 contract;
    # strict older report readers reject additional fields on SKU entries.
    prefix = "github_public_" if public else "github_20261024_"
    return RunnerSkuRateV1(sku=prefix + sku, runner_label=label, usd_per_minute=Decimal(0 if public else price))
