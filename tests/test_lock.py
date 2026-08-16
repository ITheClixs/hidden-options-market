"""Tests for the single-instance collector lock.

Two concurrent collectors were observed drawing throttling from the free endpoints,
which is how symbol-days get lost. The lock must be strict about live contention and
forgiving about crashes: a stale lock that blocks every future run would be worse
than the problem it solves.
"""

from __future__ import annotations

import os

import pytest

from absorb.collect.lock import AlreadyRunning, single_instance


class TestSingleInstance:
    def test_acquires_and_releases(self, tmp_path):
        lock = tmp_path / "c.lock"
        with single_instance(lock):
            assert lock.exists()
        assert not lock.exists()

    def test_writes_owning_pid(self, tmp_path):
        lock = tmp_path / "c.lock"
        with single_instance(lock):
            assert lock.read_text().strip() == str(os.getpid())

    def test_creates_missing_parent_directory(self, tmp_path):
        lock = tmp_path / "deep" / "nested" / "c.lock"
        with single_instance(lock):
            assert lock.exists()

    def test_second_instance_is_refused(self, tmp_path):
        # The nesting is the subject of the test: the inner acquisition must fail
        # while the outer one is still held. Flattening it would test nothing.
        lock = tmp_path / "c.lock"
        with single_instance(lock), pytest.raises(AlreadyRunning, match="Another"):  # noqa: SIM117
            with single_instance(lock):
                pass

    def test_error_names_the_owner_and_path(self, tmp_path):
        lock = tmp_path / "c.lock"
        with single_instance(lock), pytest.raises(AlreadyRunning) as exc:  # noqa: SIM117
            with single_instance(lock):
                pass
        assert str(os.getpid()) in str(exc.value)
        assert "c.lock" in str(exc.value)

    def test_stale_lock_from_dead_process_is_reclaimed(self, tmp_path):
        """A hard power-off must not stop collection forever."""
        lock = tmp_path / "c.lock"
        lock.write_text("999999")  # PID that does not exist
        with single_instance(lock):
            assert lock.read_text().strip() == str(os.getpid())

    def test_unreadable_lock_contents_are_reclaimed(self, tmp_path):
        lock = tmp_path / "c.lock"
        lock.write_text("not-a-pid")
        with single_instance(lock):
            assert lock.read_text().strip() == str(os.getpid())

    def test_empty_lock_file_is_reclaimed(self, tmp_path):
        lock = tmp_path / "c.lock"
        lock.touch()
        with single_instance(lock):
            assert lock.exists()

    def test_lock_released_after_exception(self, tmp_path):
        lock = tmp_path / "c.lock"
        with pytest.raises(ValueError), single_instance(lock):
            raise ValueError("collection blew up")
        assert not lock.exists()

    def test_lock_is_reusable_after_failure(self, tmp_path):
        lock = tmp_path / "c.lock"
        with pytest.raises(ValueError), single_instance(lock):
            raise ValueError("boom")
        with single_instance(lock):
            assert lock.exists()

    def test_does_not_delete_a_lock_it_does_not_own(self, tmp_path, monkeypatch):
        """Guards against a reclaiming run deleting the live owner's lock on exit."""
        lock = tmp_path / "c.lock"
        with single_instance(lock):
            lock.write_text("424242")  # another process took over the file
        assert lock.exists()
        lock.unlink()
