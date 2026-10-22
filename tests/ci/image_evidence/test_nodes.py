"""Ownership failures at the kubectl boundary; real nodes are a separate drill."""

import json
import os
import signal
from contextlib import nullcontext
from pathlib import Path

import pytest

from ci_esta.image_evidence import nodes
from ci_esta.image_evidence.nodes import (
    Kube,
    NodeProbeConfig,
    interrupt_on_termination,
    observe_pod,
    owned_pod,
    pod_document,
)
from ci_esta.image_evidence.plan import PullInputs, resolve_plan


class PodAPI(Kube):
    def __init__(self, config: NodeProbeConfig, *, lose_response: bool = False, existing: bool = False) -> None:
        super().__init__(config)
        self.exists = existing
        self.owner = "other" if existing else "our-owner"
        self.lose_response = lose_response
        self.deleted = False

    def request(self, *args: str, document: str | None = None) -> str:
        if args[0] == "get":
            return (
                json.dumps(
                    {"metadata": {"name": "probe", "uid": "pod-uid", "labels": {"gv-image-probe-owner": self.owner}}}
                )
                if self.exists
                else ""
            )
        if args[0] == "create":
            assert not self.exists
            self.exists = True
            if self.lose_response:
                raise TimeoutError("response lost after server created pod")
            return ""
        if args[0] == "delete":
            assert document is not None
            assert json.loads(document)["preconditions"]["uid"] == "pod-uid"
            self.exists = False
            self.deleted = True
            return ""
        raise AssertionError(args)


@pytest.mark.parametrize("lose_response", [False, True])
def test_cleanup_owns_success_and_unknown_create_outcome(lose_response: bool) -> None:
    config = NodeProbeConfig(context="dev-cluster", namespace="dev-test", nodes=("node-a",), run="test")
    api = PodAPI(config, lose_response=lose_response)
    if lose_response:
        with pytest.raises(TimeoutError, match="response lost"):
            with owned_pod(api, "probe", "our-owner", "{}"):
                pytest.fail("creation should fail")
    else:
        with pytest.raises(RuntimeError, match="probe failed"):
            with owned_pod(api, "probe", "our-owner", "{}"):
                raise RuntimeError("probe failed")
    assert api.deleted and not api.exists


def test_existing_pod_is_neither_adopted_nor_deleted() -> None:
    api = PodAPI(NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test"), existing=True)
    with pytest.raises(ValueError, match="already exists"):
        with owned_pod(api, "probe", "our-owner", "{}"):
            pytest.fail("must reject collision")
    assert api.exists and not api.deleted


def test_cleanup_refuses_replacement_with_another_owner() -> None:
    api = PodAPI(NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test"))
    with pytest.raises(ValueError, match="ownership"):
        with owned_pod(api, "probe", "our-owner", "{}"):
            api.owner = "replacement-owner"
    assert api.exists and not api.deleted


def test_pod_carries_frozen_observer_and_explicit_runtime_scope() -> None:
    config = NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test", probe_args=("--inventory",))
    pod = json.loads(
        pod_document("probe", "owner", "node", "registry/repo@sha256:" + "a" * 64, b"frozen", "os", config)
    )
    spec = pod["spec"]
    assert spec["nodeName"] == "node"
    assert spec["automountServiceAccountToken"] is False
    container = spec["containers"][0]
    assert container["command"][:3] == ["/app/.venv/bin/python", "-B", "-c"]
    assert container["command"][-1] == "--inventory"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["env"] == [{"name": "GV_IMAGE_PROBE_SCENARIO", "value": "os"}]


class DisappearingPodAPI(PodAPI):
    def request(self, *args: str, document: str | None = None) -> str:
        if args[:2] == ("get", "events"):
            assert "involvedObject.uid=pod-uid" in args
            return '{"items":[{"reason":"Evicted"}]}'
        if args[:2] == ("get", "pod"):
            return ""
        if args[0] == "logs":
            raise RuntimeError("pod was evicted")
        return super().request(*args, document=document)


def test_disappearing_pod_retains_identity_and_uid_scoped_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nodes.time, "sleep", lambda _: None)
    api = DisappearingPodAPI(NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test"))
    created = json.dumps({"metadata": {"uid": "pod-uid"}, "status": {"phase": "Pending"}})
    with pytest.raises(RuntimeError, match="disappeared"):
        observe_pod(api, "probe", tmp_path, created)
    assert json.loads((tmp_path / "probe-pod.json").read_text())["metadata"]["uid"] == "pod-uid"
    assert json.loads((tmp_path / "probe-events.json").read_text())["items"][0]["reason"] == "Evicted"


def test_termination_unwinds_owned_resource_and_restores_handler() -> None:
    api = PodAPI(NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test"))
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(KeyboardInterrupt):
        with interrupt_on_termination(), owned_pod(api, "probe", "our-owner", "{}"):
            os.kill(os.getpid(), signal.SIGTERM)
    assert api.deleted and not api.exists
    assert signal.getsignal(signal.SIGTERM) == previous


class LateEventAPI(PodAPI):
    event_reads = 0

    def request(self, *args: str, document: str | None = None) -> str:
        if args[:2] == ("get", "events"):
            self.event_reads += 1
            return json.dumps({"items": [] if self.event_reads == 1 else [{"reason": "Pulled", "message": "pulled"}]})
        if args[:2] == ("get", "pod"):
            return json.dumps({"metadata": {"uid": "pod-uid"}, "status": {"phase": "Succeeded"}})
        if args[0] == "logs":
            return "runtime passed"
        return super().request(*args, document=document)


def test_completed_probe_retains_late_pull_events_and_observed_wall_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = LateEventAPI(NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test"))
    monkeypatch.setattr(nodes.time, "sleep", lambda _: None)
    created = json.dumps({"metadata": {"uid": "pod-uid"}})
    result = observe_pod(api, "probe", tmp_path, created)
    events = json.loads((tmp_path / "probe-events.json").read_text())
    assert events["items"] == [{"reason": "Pulled", "message": "pulled"}]
    assert result.pull_events == ["pulled"]
    assert result.observed_seconds_including_client_polling >= 0


class CompletedRunAPI(PodAPI):
    phase: str = "Succeeded"

    def request(self, *args: str, document: str | None = None) -> str:
        if args[0] == "create":
            assert document is not None
            self.owner = json.loads(document)["metadata"]["labels"]["gv-image-probe-owner"]
            super().request(*args, document=document)
            return super().request("get", "pod", "probe")
        if args[:2] == ("get", "pod") and self.exists:
            return json.dumps(
                {
                    "metadata": {"uid": "pod-uid", "labels": {"gv-image-probe-owner": self.owner}},
                    "status": {"phase": self.phase},
                }
            )
        if args[:2] == ("get", "events"):
            return '{"items":[{"reason":"Pulled","message":"cached image pulled"}]}'
        if args[0] == "logs":
            return "runtime passed"
        return super().request(*args, document=document)


@pytest.mark.parametrize("phase", ["Succeeded", "Failed"])
def test_runner_streams_the_same_owned_results_it_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], phase: str
) -> None:
    config = NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test")
    api = CompletedRunAPI(config)
    api.phase = phase
    monkeypatch.setattr(nodes, "Kube", lambda _: api)
    digest = "sha256:" + "a" * 64
    inputs = PullInputs(repository="registry/repo", prefix="test", dind="docker@" + digest, pull_sequence=("cold",))
    rows = "\n".join(
        json.dumps({"arm": a, "scenario": "cold", "sample": 0, "digest": digest}) for a in ("baseline", "candidate")
    )
    observer = tmp_path / "observer.pyz"
    observer.write_bytes(b"frozen observer")
    with pytest.raises(ValueError, match="Runtime probe failed") if phase == "Failed" else nullcontext():
        nodes.run_node_probes(tmp_path, resolve_plan(inputs, rows), config, observer)
    saved = (tmp_path / "node-pulls/results.jsonl").read_text()
    assert capsys.readouterr().out == saved
    results = [json.loads(row) for row in saved.splitlines()]
    assert [r["arm"] for r in results] == (["baseline", "candidate"] if phase == "Succeeded" else ["baseline"])
    assert all(r["phase"] == phase for r in results)
    assert all(r["pull_events"] == ["cached image pulled"] for r in results)
    assert api.deleted and not api.exists


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_cancellation_during_delete_finishes_owned_cleanup(signum: signal.Signals) -> None:
    class InterruptedDeleteAPI(PodAPI):
        interrupted = False

        def request(self, *args: str, document: str | None = None) -> str:
            if args[0] == "delete" and not self.interrupted:
                self.interrupted = True
                os.kill(os.getpid(), signum)
            return super().request(*args, document=document)

    api = InterruptedDeleteAPI(NodeProbeConfig(context="dev", namespace="test", nodes=("node",), run="test"))
    with pytest.raises(KeyboardInterrupt):
        with interrupt_on_termination(), owned_pod(api, "probe", "our-owner", "{}"):
            pass
    assert api.deleted and not api.exists
