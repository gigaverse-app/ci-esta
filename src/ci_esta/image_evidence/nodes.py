"""Image-only kubelet observations with explicit targets and owned pod cleanup."""

from __future__ import annotations

import base64
import hashlib
import json
import signal
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Iterator

from pydantic import BaseModel, Field, field_validator

from ci_esta.image_evidence.plan import PullPlan


class NodeProbeConfig(BaseModel):
    context: str = Field(min_length=1)
    namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    nodes: tuple[str, ...] = Field(min_length=1, max_length=20)
    run: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,24}$")
    probe_args: tuple[str, ...] = ()

    @field_validator("nodes")
    @classmethod
    def unique_nodes(cls, nodes: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(nodes)) != len(nodes) or any(not node.strip() for node in nodes):
            raise ValueError("Select distinct nonempty node names")
        return nodes


class PodMetadata(BaseModel):
    uid: str
    labels: dict[str, str] = Field(default_factory=dict)


class PodStatus(BaseModel):
    phase: str = "Pending"


class PodObservation(BaseModel):
    metadata: PodMetadata
    status: PodStatus = Field(default_factory=PodStatus)


class PodEvent(BaseModel):
    reason: str = ""
    message: str = ""


class PodEvents(BaseModel):
    items: list[PodEvent]


class NodeObservation(BaseModel):
    pod: PodObservation
    observed_seconds_including_client_polling: float
    pull_events: list[str]


class Kube:
    def __init__(self, config: NodeProbeConfig) -> None:
        self.config = config

    def request(self, *args: str, document: str | None = None) -> str:
        try:
            return subprocess.check_output(
                [
                    "kubectl",
                    "--context",
                    self.config.context,
                    "--namespace",
                    self.config.namespace,
                    "--request-timeout=20s",
                    *args,
                ],
                input=document,
                text=True,
                stderr=subprocess.PIPE,
                timeout=30,
            ).strip()
        except subprocess.CalledProcessError as error:
            if error.stderr:
                error.add_note(error.stderr)
            raise

    def pod(self, name: str) -> PodObservation | None:
        text = self.request("get", "pod", name, "--ignore-not-found", "-o", "json")
        return PodObservation.model_validate_json(text) if text else None


def delete_owned_pod(api: Kube, name: str, owner: str) -> None:
    observed = api.pod(name)
    if observed is None:
        return
    if observed.metadata.labels.get("gv-image-probe-owner") != owner:
        raise ValueError(f"Pod ownership changed: {name}")
    # UID preconditions close the get/delete race: a replacement cannot be deleted.
    api.request(
        "delete",
        "--raw",
        f"/api/v1/namespaces/{api.config.namespace}/pods/{name}",
        "-f",
        "-",
        document=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "gracePeriodSeconds": 0,
                "preconditions": {"uid": observed.metadata.uid},
            }
        ),
    )
    deadline = time.monotonic() + 30
    while api.pod(name) is not None:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Probe pod deletion not observed: {name}")
        time.sleep(0.5)


@contextmanager
def owned_pod(api: Kube, name: str, owner: str, document: str) -> Iterator[str]:
    if api.pod(name) is not None:
        raise ValueError(f"Probe pod already exists: {name}")
    # Register recovery BEFORE create: a lost response can hide a successful
    # acquisition. The unique owner token prevents adoption of someone else's pod.
    try:
        created = api.request("create", "-f", "-", "-o", "json", document=document)
        yield created
    finally:
        try:
            delete_owned_pod(api, name, owner)
        except KeyboardInterrupt:
            # Deletion is idempotent and UID-guarded. Finish one bounded recovery
            # if cancellation interrupts cleanup itself, then honor cancellation.
            delete_owned_pod(api, name, owner)
            raise


def pod_document(
    name: str, owner: str, node: str, image: str, payload: bytes, scenario: str, config: NodeProbeConfig
) -> str:
    command = (
        "import base64,pathlib,runpy,sys; "
        "p=pathlib.Path('/probe/observer.pyz'); "
        f"p.write_bytes(base64.b64decode({base64.b64encode(payload).decode()!r})); "
        "sys.argv=[str(p),*sys.argv[1:]]; runpy.run_path(str(p),run_name='__main__')"
    )
    return json.dumps(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "labels": {"gv-image-pull-probe": config.run, "gv-image-probe-owner": owner}},
            "spec": {
                "nodeName": node,
                "restartPolicy": "Never",
                "activeDeadlineSeconds": 180,
                "automountServiceAccountToken": False,
                "terminationGracePeriodSeconds": 0,
                "volumes": [{"name": "observer", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}}],
                "containers": [
                    {
                        "name": "image-only",
                        "image": image,
                        "imagePullPolicy": "Always",
                        "command": ["/app/.venv/bin/python", "-B", "-c", command, *config.probe_args],
                        "env": [{"name": "GV_IMAGE_PROBE_SCENARIO", "value": scenario}],
                        "volumeMounts": [{"name": "observer", "mountPath": "/probe"}],
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "32Mi"},
                            "limits": {"cpu": "100m", "memory": "256Mi"},
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                    }
                ],
            },
        }
    )


def save_events(api: Kube, name: str, uid: str, out: Path) -> PodEvents:
    # Kubelet events can arrive after container completion. Preserve the bounded
    # five-second grace used by the consumer probe, and keep the raw last read.
    for attempt in range(6):
        raw = api.request("get", "events", "--field-selector", f"involvedObject.uid={uid}", "-o", "json")
        events = PodEvents.model_validate_json(raw)
        (out / f"{name}-events.json").write_text(raw + "\n")
        if any(event.reason == "Pulled" for event in events.items) or attempt == 5:
            return events
        time.sleep(1)
    raise AssertionError("Event observation must finish within the bounded attempts")


def observe_pod(api: Kube, name: str, out: Path, created: str, *, started: float | None = None) -> NodeObservation:
    if started is None:
        started = time.monotonic()
    # Persist the create receipt before polling. Karpenter can remove a running
    # probe; its UID still lets us retrieve the eviction events after deletion.
    state = PodObservation.model_validate_json(created)
    uid = state.metadata.uid
    (out / f"{name}-pod.json").write_text(created + "\n")
    deadline = time.monotonic() + 210
    try:
        while True:
            raw = api.request("get", "pod", name, "--ignore-not-found", "-o", "json")
            if not raw:
                raise RuntimeError(f"Probe pod disappeared: {name}; inspect UID-scoped events")
            state = PodObservation.model_validate_json(raw)
            if state.metadata.uid != uid:
                raise RuntimeError(f"Probe pod replaced: {name}; refusing replacement evidence")
            (out / f"{name}-pod.json").write_text(raw + "\n")
            if state.status.phase in ("Succeeded", "Failed"):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Probe pod did not finish: {name}")
            time.sleep(1)
        elapsed = time.monotonic() - started
    finally:
        events = save_events(api, name, uid, out)
    (out / f"{name}.log").write_text(api.request("logs", name) + "\n")
    return NodeObservation(
        pod=state,
        observed_seconds_including_client_polling=elapsed,
        pull_events=[event.message for event in events.items if event.reason == "Pulled"],
    )


def _interrupt(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt(f"Image probe received signal {signum}")


@contextmanager
def interrupt_on_termination() -> Iterator[None]:
    # These CLI probes run on the main thread. Convert SIGTERM to normal Python
    # unwinding so owned pod cleanup also runs when an operator cancels a drill.
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@interrupt_on_termination()
def run_node_probes(evidence: Path, plan: PullPlan, config: NodeProbeConfig, observer: Path) -> None:
    # Freeze the observer once for all arms, never reread a changing checkout.
    payload = observer.read_bytes()
    out = evidence / "node-pulls"
    out.mkdir()  # Refuse to mix this observation with an earlier run.
    (out / "inputs.json").write_text(
        json.dumps(
            {
                "config": config.model_dump(),
                "plan": plan.model_dump(),
                "observer_sha256": hashlib.sha256(payload).hexdigest(),
                "scope": "Existing nodes; uncontrolled cache; image-only; no application entrypoint/readiness measurement",
            },
            indent=2,
        )
        + "\n"
    )
    api = Kube(config)
    owner = uuid.uuid4().hex
    for sample, node in enumerate(config.nodes):
        arms = ("baseline", "candidate") if sample % 2 == 0 else ("candidate", "baseline")
        for arm in arms:
            for index, scenario in enumerate(plan.sequence):
                name = f"image-probe-{config.run}-{sample}-{arm}-{index}"
                image = plan.images[arm][scenario]
                document = pod_document(name, owner, node, image, payload, scenario, config)
                started = time.monotonic()
                with owned_pod(api, name, owner, document) as created:
                    observed = observe_pod(api, name, out, created, started=started)
                    state = observed.pod
                    row = json.dumps(
                        {
                            "sample": sample,
                            "arm": arm,
                            "scenario": scenario,
                            "node": node,
                            "image": image,
                            "pod": name,
                            "uid": state.metadata.uid,
                            "phase": state.status.phase,
                            **observed.model_dump(exclude={"pod"}),
                        }
                    )
                    with (out / "results.jsonl").open("a") as stream:
                        stream.write(row + "\n")
                    print(row, flush=True)
                    if state.status.phase != "Succeeded":
                        raise ValueError(f"Runtime probe failed: {name}; inspect saved pod, events and logs")
    (out / "cleanup.json").write_text(json.dumps({"owned_pods_remaining": 0, "owner": owner}) + "\n")
