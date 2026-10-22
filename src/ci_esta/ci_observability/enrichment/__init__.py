"""Consumer enrichment profiles around the shared CI observability report.

backend-common owns GitHub timing/cost accounting, rendering, the sticky, and
bounded shared metrics (``ci_esta.ci_observability``). Each consumer
repo additionally measures what the shared reporter cannot infer — pytest
artifacts, Docker builds, infrastructure failures — and feeds it back through
the report's ``extensions``/``repository_signals`` seam.

Those enrichment layers were written twice, once per consumer, duplicating
the primitives byte-for-byte while the profiles drifted apart. This package
is their single home:

- ``primitives``/``models``/``prometheus`` — the genuinely shared layer.
- ``backend/`` — gigaverse-backend's profile (``CI-OBS-BACKEND-ENRICH-v1``):
  junit/coverage/timeline artifact parsing, EKS overhead classification,
  GitHub log enrichment, and the temporary legacy-dashboard bridge.
- ``ai`` — gigaverse-ai's profile (``CI-OBS-AI-ENRICH-v1``): workflow-class
  snapshots and Docker/uv build metrics.
- ``cli`` — the union command line (``python -m
  ci_esta.ci_observability.enrichment`` / ``gv-ci-enrichment``).

Each profile's wire contract (extension key, contract version, signal
strings, JSON formatting) is preserved exactly as the consumer wrote it;
consumers keep only the workflow invocations.
"""
