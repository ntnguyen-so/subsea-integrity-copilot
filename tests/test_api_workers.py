"""Use controlled thread events to verify root dispatch and independent map failures."""

from contextlib import contextmanager
from datetime import timedelta
from threading import Event
from unittest.mock import MagicMock

from subsea_copilot.api import AgentWorker
from subsea_copilot.contracts import AgentTask, utc_now
from subsea_copilot.runtime.workflow import AgentService


def report_task(identifier="report"):
    return AgentTask(
        id=identifier, root_id=identifier, generation_id="replay", snapshot_id="window",
        site_id="northsea",
        role="operator_response", purpose="answer_incident_question",
        question="Explain the measured pressure pattern.", mode="scripted",
        deadline=utc_now() + timedelta(minutes=5),
    )


def test_every_root_starts_independently_without_a_fixed_worker_cap():
    primary = MagicMock(spec=AgentService)
    primary.store = MagicMock()
    roots = {f"root-{index}": report_task(f"root-{index}") for index in range(8)}
    started = {identifier: Event() for identifier in roots}
    release = Event()
    contexts = []
    primary.store.pending_root_ids.return_value = list(roots)
    primary.store.get_task.side_effect = roots.__getitem__

    @contextmanager
    def factory(root_id):
        service = MagicMock(spec=AgentService)
        contexts.append(service)

        def run_once():
            started[root_id].set()
            assert release.wait(5)
            return False

        service.run_once.side_effect = run_once
        yield service

    worker = AgentWorker(primary, service_factory=factory)
    worker.start()
    try:
        assert all(event.wait(5) for event in started.values())
        assert worker.active_workers == 8
        assert len({id(service) for service in contexts}) == 8
        assert not release.is_set()
    finally:
        release.set()
        worker.close()
    assert worker.error is None


def test_slow_map_does_not_block_a_newly_admitted_investigation():
    primary = MagicMock(spec=AgentService)
    primary.store = MagicMock()
    first, second = report_task("first"), report_task("second")
    admitted, mapping_started, second_started, release = Event(), Event(), Event(), Event()
    primary.store.pending_root_ids.side_effect = lambda: (
        (["first"] if first.state == "QUEUED" else [])
        + (["second"] if admitted.is_set() else [])
    )
    primary.store.get_task.side_effect = {"first": first, "second": second}.__getitem__

    @contextmanager
    def factory(root_id):
        service = MagicMock(spec=AgentService)

        def run_once():
            if root_id == "first":
                first.state = "SUCCEEDED"
                return True
            second_started.set()
            assert release.wait(5)
            return False

        service.run_once.side_effect = run_once
        yield service

    def map_report(task):
        mapping_started.set()
        assert release.wait(5)

    worker = AgentWorker(primary, map_report, service_factory=factory)
    worker.start()
    try:
        assert mapping_started.wait(5)
        admitted.set()
        assert second_started.wait(5)
        assert not release.is_set()
    finally:
        release.set()
        worker.close()
    assert worker.error is None


def test_mapping_failure_is_reported_without_stopping_dispatch():
    primary = MagicMock(spec=AgentService)
    primary.store = MagicMock()
    task = report_task()
    primary.store.pending_root_ids.side_effect = lambda: (
        [task.id] if task.state == "QUEUED" else []
    )
    primary.store.get_task.return_value = task
    published = Event()
    primary.store.publish_event.side_effect = lambda *args, **kwargs: published.set()

    @contextmanager
    def factory(root_id):
        service = MagicMock(spec=AgentService)

        def run_once():
            task.state = "SUCCEEDED"
            return True

        service.run_once.side_effect = run_once
        yield service

    worker = AgentWorker(
        primary, MagicMock(side_effect=ValueError("Invalid source binding")),
        service_factory=factory,
    )
    worker.start()
    try:
        assert published.wait(5)
    finally:
        worker.close()
    assert worker.error is None
    assert worker.mapping_error == "mapping_worker_failed"
    primary.store.publish_event.assert_called_once_with(
        task.generation_id, "mapping.completed",
        {"status": "failed", "error_code": "mapping_worker_failed"},
        task_id=task.id, snapshot_id=task.snapshot_id,
    )
