from concurrent.futures import ThreadPoolExecutor

import pytest

from dashboard.components.session_registry import SessionRegistry


@pytest.fixture
def clock():
    class Clock:
        now = 0

        def __call__(self):
            return self.now

    return Clock()


def test_registration_is_idempotent_and_expires_at_ninety_seconds(clock):
    registry = SessionRegistry(clock)
    assert registry.active_count() == 0
    registry.register("reader")
    clock.now = 89
    registry.register("reader")
    assert registry.active_count() == 1
    clock.now = 90
    assert registry.active_count() == 0


def test_heartbeat_refreshes_only_its_session(clock):
    registry = SessionRegistry(clock)
    registry.heartbeat("disconnected")
    registry.heartbeat("passive")
    for clock.now in (30, 60, 90, 120):
        registry.heartbeat("passive")

    assert registry.active_count() == 1
    clock.now = 210
    assert registry.cleanup_expired() == 1
    assert registry.cleanup_expired() == 0
    registry.heartbeat("passive")
    assert registry.active_count() == 1


def test_cleanup_is_bounded_and_counts_exclude_remaining_expired_entries(clock):
    registry = SessionRegistry(clock)
    for index in range(512):
        registry.register(str(index))
    clock.now = 90
    registry.heartbeat("new")
    assert registry.active_count() == 1
    assert 0 < registry.cleanup_expired() < 512


def test_concurrent_registration_and_heartbeats(clock):
    registry = SessionRegistry(clock)

    def update(index):
        session_id = str(index % 50)
        registry.register(session_id)
        registry.heartbeat(session_id)
        return registry.active_count()

    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(update, range(1000)))
    assert all(1 <= count <= 50 for count in counts)
    assert registry.active_count() == 50
