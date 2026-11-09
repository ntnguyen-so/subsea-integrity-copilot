import pytest

from subsea_copilot.replay import (
    ReplayClock,
    affected_endpoints,
    arrived_records,
    completed_endpoints,
)
from subsea_copilot.synthetic import generate_pack, generate_scenario


def test_every_hop_at_accelerated_speed_and_clock_through_total_outage():
    pack = generate_pack()
    clocks = [ReplayClock(duration_seconds=100, speed=speed) for speed in (1, 10, 20, 30)]
    endpoints = []
    for clock in clocks:
        clock.play()
        result = []
        last = 0
        while clock.playing:
            clock.advance(1)
            new = completed_endpoints(clock.clock_seconds, pack, last)
            result.extend(new)
            if new:
                last = new[-1]
        endpoints.append(result)
    assert all(result == list(range(5, 100, 5)) for result in endpoints)
    assert completed_endpoints(180, pack)[-1] == 175
    assert completed_endpoints(9, pack) == []
    assert completed_endpoints(10, pack) == [5]


def test_pause_step_speed_continuity():
    clock = ReplayClock()
    clock.play()
    assert clock.advance(3) == 3
    clock.set_speed(10)
    assert clock.advance(2) == 23
    clock.pause()
    assert clock.advance(100) == 23
    assert clock.step() == 28
    clock.play()
    with pytest.raises(ValueError):
        clock.step()
    assert clock.advance(1) == 38
    with pytest.raises(ValueError):
        clock.advance(float("nan"))


@pytest.mark.parametrize("speed", [20, 30])
def test_high_speed_changes_preserve_clock_pause_and_completion(speed):
    clock = ReplayClock(duration_seconds=60)
    clock.play()
    assert clock.advance(3) == 3
    clock.set_speed(speed)
    assert clock.advance(0.5) == 3 + speed / 2
    clock.pause()
    assert clock.advance(10) == 3 + speed / 2
    clock.play()
    assert clock.advance(10) == 60
    assert not clock.playing


def test_half_open_late_revision_horizon():
    pack = generate_pack()
    assert 60 in affected_endpoints(0, 65, pack)
    assert 60 not in affected_endpoints(60, 65, pack)
    assert 60 not in affected_endpoints(0, 200, pack)


def test_arrival_release_never_reads_future_or_baseline_as_replay():
    dataset = generate_scenario("S6", duration_seconds=10)
    first = arrived_records(dataset, 0)
    assert first
    assert all(row.received_at <= dataset.epoch.isoformat() for row in first)
    assert not any(row in dataset.baseline for row in first)
    assert len(arrived_records(dataset, 7)) < len(dataset.records)
