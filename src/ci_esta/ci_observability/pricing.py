"""One dated GitHub SKU price catalog, official labels, and caller overrides."""

from decimal import Decimal

from ci_esta.ci_observability.models import ObservedJobV1, RunnerSkuRateV1

PRICING_URL = "https://docs.github.com/en/billing/reference/actions-runner-pricing"
# Verified 2026-10-24 against PRICING_URL. Each SKU's price is defined once.
GITHUB_SKU_PRICES = {
    "actions_linux": "0.006",
    "actions_linux_arm": "0.005",
    "actions_linux_slim": "0.002",
    "actions_windows": "0.010",
    "actions_windows_arm": "0.010",
    "actions_macos": "0.062",
    "linux_2_core_advanced": "0.006",
    "linux_4_core": "0.012",
    "linux_8_core": "0.022",
    "linux_16_core": "0.042",
    "linux_32_core": "0.082",
    "linux_64_core": "0.162",
    "linux_96_core": "0.252",
    "windows_4_core": "0.022",
    "windows_8_core": "0.042",
    "windows_16_core": "0.082",
    "windows_32_core": "0.162",
    "windows_64_core": "0.322",
    "windows_96_core": "0.552",
    "macos_l": "0.077",
    "linux_2_core_arm": "0.005",
    "linux_4_core_arm": "0.008",
    "linux_8_core_arm": "0.014",
    "linux_16_core_arm": "0.026",
    "linux_32_core_arm": "0.050",
    "linux_64_core_arm": "0.098",
    "windows_2_core_arm": "0.008",
    "windows_4_core_arm": "0.014",
    "windows_8_core_arm": "0.026",
    "windows_16_core_arm": "0.050",
    "windows_32_core_arm": "0.098",
    "windows_64_core_arm": "0.194",
    "macos_xl": "0.102",
    "linux_4_core_gpu": "0.052",
    "windows_4_core_gpu": "0.102",
}

STANDARD_LABEL_SKUS = {
    **dict.fromkeys(("ubuntu-latest", "ubuntu-22.04", "ubuntu-24.04"), "actions_linux"),
    **dict.fromkeys(("ubuntu-22.04-arm", "ubuntu-24.04-arm"), "actions_linux_arm"),
    "ubuntu-slim": "actions_linux_slim",
    **dict.fromkeys(("windows-latest", "windows-2022", "windows-2025"), "actions_windows"),
    "windows-11-arm": "actions_windows_arm",
    **dict.fromkeys(("macos-latest", "macos-14", "macos-15", "macos-15-intel", "macos-26"), "actions_macos"),
}
OFFICIAL_LABEL_SKUS = {
    **STANDARD_LABEL_SKUS,
    **dict.fromkeys(("macos-latest-large", "macos-14-large", "macos-15-large", "macos-26-large"), "macos_l"),
    **dict.fromkeys(("macos-latest-xlarge", "macos-14-xlarge", "macos-15-xlarge", "macos-26-xlarge", "xcode-27-xlarge"),
                    "macos_xl"),
}
PUBLIC_FREE_SKUS = frozenset(STANDARD_LABEL_SKUS.values())


def matching_rate(job: ObservedJobV1, rates: list[RunnerSkuRateV1],
                  repository_private: bool | None) -> RunnerSkuRateV1 | None:
    matches = [rate for rate in rates if rate.runner_label in job.runner_labels]
    if len(matches) > 1:
        raise ValueError(f"runner labels match multiple configured SKUs: {job.runner_labels}")
    if matches and matches[0].usd_per_minute is not None:
        return matches[0]
    if matches:
        label, sku = matches[0].runner_label, matches[0].sku
    elif len(job.runner_labels) == 1 and job.runner_labels[0] in OFFICIAL_LABEL_SKUS:
        label = job.runner_labels[0]
        sku = OFFICIAL_LABEL_SKUS[label]
    else:
        # Never infer hardware from an OS label in a self-hosted/custom label set.
        return None
    if sku not in GITHUB_SKU_PRICES:
        return None
    public_free = repository_private is False and sku in PUBLIC_FREE_SKUS
    # Versioned SKU names preserve provenance within the existing v1 contract;
    # strict older report readers reject additional fields on SKU entries.
    prefix = "github_public_" if public_free else "github_20261024_"
    return RunnerSkuRateV1(sku=prefix + sku, runner_label=label,
                           usd_per_minute=Decimal(0 if public_free else GITHUB_SKU_PRICES[sku]))
