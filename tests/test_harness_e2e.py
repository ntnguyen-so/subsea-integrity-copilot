"""Real HTTP, PostgreSQL, worker and checkpoint coverage with controlled scripted faults."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from subsea_copilot.config import Settings
from subsea_copilot.contracts import content_hash
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.store import Store

pytestmark = pytest.mark.integration


def test_http_investigation_compacts_repairs_and_preserves_harness_and_sources(tmp_path: Path):
    if not os.environ.get("SUBSEA_DB_APP_PASSWORD"):
        pytest.skip("Load the independently bootstrapped PostgreSQL environment")
    tenant = "harness-http-" + uuid4().hex
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ, "SUBSEA_TELEMETRY_ENABLED": "0", "SUBSEA_TRACE_CONTENT": "0",
    }
    trace_enabled = os.environ.get("SUBSEA_HARNESS_TRACE_TEST") == "1"
    if trace_enabled:
        environment.update({
            "SUBSEA_TELEMETRY_ENABLED": "1", "SUBSEA_TRACE_CONTENT": "1",
            "SUBSEA_SYNTHETIC_ONLY": "1",
        })
    with (tmp_path / "server.log").open("w") as output:
        server = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("harness_server.py")),
             "--port", str(port), "--tenant", tenant, "--runtime-dir", str(tmp_path)],
            env=environment, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
                for _ in range(100):
                    assert server.poll() is None, (tmp_path / "server.log").read_text()
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.2)
                else:
                    pytest.fail("Isolated HTTP server did not become ready")
                login = client.post("/api/login", json={
                    "username": "operator", "password": os.environ["SUBSEA_OPERATOR_PASSWORD"],
                })
                login.raise_for_status()
                client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                response = client.post("/api/replays", json={
                    "scenario": "S7", "mode": "scripted", "workflow": "agent_assisted",
                    "pause_on_anomaly": False,
                    "idempotency_key": "harness-replay",
                })
                assert response.is_success, response.text
                replay = response.json()
                for index in range(29):
                    response = client.post(f"/api/replays/{replay['id']}/control", json={
                        "action": "step", "idempotency_key": f"step-{index}",
                    })
                    response.raise_for_status()
                    replay = response.json()
                assert replay["clock_seconds"] == 145
                settings = Settings.from_env()
                with Store(settings.database_dsn, tenant_id=tenant) as store:
                    pinned = store.get_window(replay["latest_window_id"])

                def investigate(question: str, key: str) -> dict:
                    response = client.post(f"/api/replays/{replay['id']}/questions", json={
                        "question": question, "snapshot_id": replay["latest_window_id"],
                        "mode": "scripted", "idempotency_key": key,
                    })
                    response.raise_for_status()
                    task_id = response.json()["id"]
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        response = client.get(f"/api/tasks/{task_id}")
                        response.raise_for_status()
                        detail = response.json()
                        if detail["task"]["state"] in {
                            "SUCCEEDED", "ABSTAINED", "FAILED", "BUDGET_BLOCKED", "CANCELLED",
                        }:
                            return detail
                        time.sleep(0.2)
                    pytest.fail("HTTP investigation did not finish")

                accepted = investigate(
                    "What caused the event and where should we inspect?", "repair",
                )
                assert accepted["task"]["state"] == "SUCCEEDED", {
                    "task": accepted["task"],
                    "children": [(c["role"], c["state"], c["error_code"])
                                 for c in accepted["children"]],
                    "server_log": (tmp_path / "server.log").read_text(),
                }
                task_id = accepted["task"]["id"]
                response = client.get(f"/api/tasks/{task_id}/casefile")
                response.raise_for_status()
                assert response.json() == accepted["casefile"]
                children = [
                    client.get(f"/api/tasks/{child['id']}").json()
                    for child in accepted["children"]
                ]
                catalog_hash = accepted["task"]["prompt_catalog_sha256"]
                assert catalog_hash and all(
                    child["task"]["prompt_catalog_sha256"] == catalog_hash for child in children
                )
                diagnosis = next(
                    child for child in children if child["task"]["role"] == "event_diagnosis"
                )
                events = [
                    event for detail in [accepted, *children] for event in detail["harness_events"]
                ]
                rejections = [e["payload"] for e in events if e["type"] == "validation.rejected"]
                assert {"plan", "answer"} <= {e["phase"] for e in rejections}
                repairs = [
                    e["payload"]["rejection_id"] for e in events
                    if e["type"] == "validation.repair_requested"
                ]
                assert repairs and set(repairs) <= {e["rejection_id"] for e in rejections}
                resolved = {
                    identifier for event in events if event["type"] == "validation.passed"
                    for identifier in event["payload"]["resolved_rejection_ids"]
                }
                assert set(repairs) <= resolved
                assert all(e["issues"] and e["repair_instruction"] for e in rejections)
                assert (
                    "controlled_unknown_limitation"
                    not in accepted["task"]["result"]["limitations"]
                )
                compacted = [
                    e["payload"] for e in diagnosis["harness_events"]
                    if e["type"] == "model.context_compacted"
                ]
                assert compacted and any(e["archived_receipts"] for e in compacted)
                assert all(e["prompt_chars"] <= e["limit_chars"] for e in compacted)
                receipts = {r["call_id"]: r for r in diagnosis["receipts"]}
                retrieval = next(
                    r for r in receipts.values() if r["arguments"].get("receipt_id")
                )
                original = receipts[retrieval["arguments"]["receipt_id"]]
                restored = dict(retrieval["result"])
                provenance = restored.pop("retrieved_from_receipt")
                assert restored == original["result"]
                assert provenance["result_sha256"] == content_hash(original["result"])
                for event in compacted:
                    for archive in event["archived_receipts"]:
                        assert archive["result_sha256"] == content_hash(
                            receipts[archive["receipt_id"]]["result"]
                        )
                with Store(settings.database_dsn, tenant_id=tenant) as store:
                    for detail in [accepted, *children]:
                        manifests = {
                            e["payload"]["harness_id"]: e["payload"]
                            for e in detail["harness_events"] if e["type"] == "harness.started"
                        }
                        assert manifests
                        assert all(
                            manifest["prompt_catalog_sha256"] == catalog_hash
                            and manifest["prompt_asset"]["version"] == "1.0.0"
                            for manifest in manifests.values()
                        )
                        for call in store.list_model_calls(detail["task"]["id"]):
                            metadata = call
                            assert metadata["harness"]["harness_id"] in manifests
                            assert metadata["prompt_hash"] == metadata["test_prompt_sha256"]
                            assert len(metadata["harness"]["templates"]["system"]) == 64
                    snapshot = store.get_window(replay["latest_window_id"])
                    assert accepted["casefile"]["snapshot_id"] == snapshot.id
                    assert snapshot == pinned
                with postgres_checkpointer(settings.checkpoint_dsn) as saver:
                    task = diagnosis["task"]
                    thread_id = hashlib.sha256(json.dumps([
                        task["tenant_id"], task["site_id"], task["generation_id"],
                        task["snapshot_id"], task["role"], task["id"], "answer",
                    ]).encode()).hexdigest()
                    checkpoint = saver.get_tuple({"configurable": {"thread_id": thread_id}})
                    assert checkpoint is not None
                    messages = checkpoint.checkpoint["channel_values"]["messages"]
                    assert not any("context.claim_ledger" in str(m.content) for m in messages)
                    assert not any("archived_receipt_id" in str(m.content) for m in messages)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    response = client.get(f"/api/replays/{replay['id']}/projection")
                    response.raise_for_status()
                    if all(task["state"] in {
                        "SUCCEEDED", "ABSTAINED", "FAILED", "BUDGET_BLOCKED", "CANCELLED",
                    } for task in response.json()["tasks"]):
                        break
                    time.sleep(0.2)
                else:
                    pytest.fail("The isolated replay's automatic work did not become idle")
                browser = subprocess.run(
                    ["node", str(Path(__file__).with_name("harness_browser.cjs")),
                     str(client.base_url), replay["id"], task_id],
                    env=environment, capture_output=True, text=True, timeout=60,
                )
                assert browser.returncode == 0, browser.stdout + browser.stderr
                if trace_enabled:
                    with Store(settings.database_dsn, tenant_id=tenant) as store:
                        trace_id = store.first_task_trace(task_id)["trace_id"]
                        expected_generations = sum(
                            len(store.list_model_calls(detail["task"]["id"]))
                            for detail in [accepted, *children]
                        )
                    with httpx.Client(
                        base_url="http://127.0.0.1:3001",
                        auth=(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]),
                        timeout=30,
                    ) as langfuse:
                        deadline = time.monotonic() + 60
                        while time.monotonic() < deadline:
                            response = langfuse.get("/api/public/v2/observations", params={
                                "traceId": trace_id,
                                "fields": "core,basic,metadata,io", "limit": 100,
                            })
                            response.raise_for_status()
                            observations = response.json()["data"]
                            generations = [o for o in observations if o["type"] == "GENERATION"]
                            ids = {o["id"] for o in observations}
                            connected = all(
                                not o.get("parentObservationId")
                                or o["parentObservationId"] in ids for o in observations
                            )
                            if len(generations) == expected_generations and connected and any(
                                o["metadata"].get("attributes.context.stage", 0) > 0
                                for o in generations
                            ):
                                break
                            time.sleep(1)
                        else:
                            pytest.fail("Stored Langfuse generations were not visible")
                        assert all(
                            len(o["metadata"]["attributes.harness.template.system.sha256"]) == 64
                            for o in generations
                        )
                        assert all(
                            o["metadata"]["attributes.harness.asset.version"] == "1.0.0"
                            and o["metadata"]["attributes.harness.catalog.sha256"] == catalog_hash
                            for o in generations
                        )
                        failed = [
                            o for o in observations if o["metadata"].get(
                                "attributes.validation.status"
                            ) == "failed"
                        ]
                        assert failed and all(json.loads(o["output"])["issues"] for o in failed)
                        assert all(o["traceId"] == trace_id for o in observations)
                        ids = {o["id"] for o in observations}
                        assert all(
                            not o.get("parentObservationId") or o["parentObservationId"] in ids
                            for o in observations
                        )
                        print(
                            f"Verified controlled scripted trace: "
                            f"http://127.0.0.1:3001/project/subsea-copilot/traces/{trace_id}"
                        )
                denied = investigate("What caused the event? denial control", "denial")
                assert denied["task"]["state"] == "FAILED", denied
                denied_children = [
                    client.get(f"/api/tasks/{child['id']}").json()
                    for child in denied["children"]
                ]
                failures = [
                    e["payload"] for detail in [denied, *denied_children]
                    for e in detail["harness_events"] if e["type"] == "tool.rejected"
                ]
                assert any(
                    e["executed"] is False and e["result_accepted"] is False for e in failures
                )
                assert not denied["casefile"]
                assert client.get(f"/api/tasks/{denied['task']['id']}/casefile").status_code == 409
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=15)
