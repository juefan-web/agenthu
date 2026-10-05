"""P0-1 slice 2: ledger, barrier and generation primitives (D-036 §8-8).

Covers the frozen rules the deletion/export API (P0-3) will rely on:
idempotent operation accept, durable cleanup queue with the 5/30/120/300/900s
backoff ladder inside a 24h window, barrier scope/target matching with the
FAILED-never-releases rule, monotonic generations with stale-observation
rejection, ledger survival of users-row deletion, and the fail-closed
dependency inventory.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Column, Integer, Table, select, text
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.data_lifecycle import DataBarrier, DataCleanupItem, DataOperation
from backend.models.enums import (
    CleanupItemAction,
    CleanupItemState,
    DataBarrierScope,
    DataBarrierState,
    DataOperationKind,
    DataOperationStatus,
)
from backend.models.user import User
from backend.services import data_lifecycle as dl
from backend.services.data_registry import (
    REGISTRY,
    Store,
    audit_inventory,
    redis_literals_in_source,
)


@pytest.fixture
def user(db_session: Session, auth_factory) -> User:
    """The single user registered through the API inside this transaction."""

    auth_factory()
    return db_session.scalars(select(User)).one()


@pytest.fixture
def handle(db_session: Session, user: User) -> str:
    return dl.owner_handle_of(db_session, user.id)


def _object_spec(ref: str = "objects/k1") -> dl.CleanupItemSpec:
    return dl.CleanupItemSpec("file_objects", ref, CleanupItemAction.DELETE_OBJECT.value)


def _deletion_request(target: dict | None, generation: int = 1) -> dl.OperationRequest:
    return dl.OperationRequest(
        kind=DataOperationKind.DELETION,
        client_request_id="req-1",
        target=target,
        data_generation=generation,
    )


class TestOwnerHandleAndGeneration:
    def test_new_user_gets_handle_and_generation(self, db_session, user):
        assert len(user.owner_handle) == 32
        int(user.owner_handle, 16)  # hex, opaque
        assert user.data_generation == 1

    def test_handles_are_unique(self, db_session, user, client, auth_factory):
        other_headers = auth_factory()
        assert other_headers  # registration alone proves uniqueness (unique idx)
        others = db_session.scalars(select(User).where(User.id != user.id)).all()
        assert len(others) == 1
        assert others[0].owner_handle != user.owner_handle

    def test_bump_is_monotonic(self, db_session, user):
        assert dl.bump_data_generation(db_session, user.id) == 2
        assert dl.bump_data_generation(db_session, user.id) == 3
        db_session.refresh(user)
        assert user.data_generation == 3

    def test_stale_generation_rejected_current_passes(self, db_session, user):
        dl.bump_data_generation(db_session, user.id)
        with pytest.raises(dl.GenerationStale):
            dl.assert_generation_current(db_session, user.id, observed_generation=1)
        dl.assert_generation_current(db_session, user.id, observed_generation=2)


class TestOperationIdempotency:
    def test_same_input_returns_same_operation(self, db_session, handle):
        target = {"kind": "source", "ids": ["a"]}
        first, created = dl.get_or_create_operation(db_session, handle, _deletion_request(target))
        assert created
        second, created_again = dl.get_or_create_operation(
            db_session, handle, _deletion_request(target)
        )
        assert not created_again
        assert second.id == first.id

    def test_different_input_conflicts(self, db_session, handle):
        dl.get_or_create_operation(
            db_session, handle, _deletion_request({"kind": "source", "ids": ["a"]})
        )
        with pytest.raises(dl.IdempotencyConflict):
            dl.get_or_create_operation(
                db_session, handle, _deletion_request({"kind": "source", "ids": ["b"]})
            )

    def test_generation_snapshot_is_not_compared_on_replay(self, db_session, handle, user):
        """Replaying after the operation's own confirm bumped the generation
        must return the same operation, not a false 409 (A-draft §4)."""

        target = {"kind": "memory", "ids": ["m"]}
        operation, _ = dl.get_or_create_operation(
            db_session, handle, _deletion_request(target, generation=1)
        )
        dl.bump_data_generation(db_session, user.id)
        replayed, created = dl.get_or_create_operation(
            db_session, handle, _deletion_request(target, generation=2)
        )
        assert not created
        assert replayed.id == operation.id
        assert replayed.data_generation == 1  # snapshot stays at acceptance


class TestLedgerSurvivesUserDeletion:
    def test_no_user_id_column_in_ledger(self):
        for table_name in ("data_operations", "data_cleanup_items", "data_barriers"):
            columns = Base.metadata.tables[table_name].columns.keys()
            assert "user_id" not in columns
            assert "email" not in columns

    def test_ledger_rows_outlive_the_users_row(self, db_session, handle, user):
        operation, _ = dl.get_or_create_operation(
            db_session, handle, _deletion_request({"kind": "account"})
        )
        dl.enqueue_cleanup_items(
            db_session,
            operation,
            [_object_spec()],
        )
        dl.raise_barrier(
            db_session,
            owner_handle=handle,
            scope=DataBarrierScope.ACCOUNT,
            raised_generation=2,
        )
        db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": str(user.id)})
        db_session.expire_all()

        # The ledger must still hold every row, keyed by the now-orphaned
        # opaque handle — no FK, no CASCADE (A-draft §4).
        assert db_session.scalars(select(DataOperation)).one().owner_handle == handle
        assert db_session.scalars(select(DataCleanupItem)).one().owner_handle == handle
        assert db_session.scalars(select(DataBarrier)).one().owner_handle == handle


class TestCleanupQueue:
    def _operation(self, db_session, handle) -> DataOperation:
        operation, _ = dl.get_or_create_operation(
            db_session, handle, _deletion_request({"kind": "source", "ids": ["a"]})
        )
        return operation

    def test_enqueue_dedupes_and_claim_is_exclusive(self, db_session, handle):
        operation = self._operation(db_session, handle)
        dl.enqueue_cleanup_items(
            db_session,
            operation,
            [_object_spec(), _object_spec()],
        )
        items = db_session.scalars(select(DataCleanupItem)).all()
        assert len(items) == 1  # unique (operation, resource, ref, action)

        claimed = dl.claim_cleanup_items(db_session)
        assert [item.id for item in claimed] == [items[0].id]
        assert claimed[0].state == CleanupItemState.CLAIMED
        assert claimed[0].attempts == 1
        # Second claimer (same session view) finds nothing free.
        assert dl.claim_cleanup_items(db_session) == []

    def test_complete_requires_claimed_state(self, db_session, handle):
        operation = self._operation(db_session, handle)
        (item,) = dl.enqueue_cleanup_items(
            db_session,
            operation,
            [_object_spec()],
        )
        assert dl.complete_cleanup_item(db_session, item.id) is None  # PENDING
        (claimed,) = dl.claim_cleanup_items(db_session)
        done = dl.complete_cleanup_item(db_session, claimed.id)
        assert done is not None
        assert done.state == CleanupItemState.DONE
        assert done.done_at is not None
        assert done.next_retry_at is None

    def test_backoff_ladder_and_gates(self, db_session, handle):
        operation = self._operation(db_session, handle)
        (item,) = dl.enqueue_cleanup_items(
            db_session,
            operation,
            [_object_spec()],
        )
        base = item.created_at
        ladder = dl.CLEANUP_BACKOFF_LADDER_S

        (claimed,) = dl.claim_cleanup_items(db_session, now=base)
        failed = dl.fail_cleanup_item(db_session, claimed.id, error_summary="s3 timeout", now=base)
        assert failed.state == CleanupItemState.PENDING
        assert failed.attempts == 1
        assert failed.next_retry_at == base + timedelta(seconds=ladder[0])
        # Backoff gate: not claimable before the step lapses.
        assert dl.claim_cleanup_items(db_session, now=base + timedelta(seconds=ladder[0] - 1)) == []
        # Claimable at/after the gate.
        second = dl.claim_cleanup_items(db_session, now=base + timedelta(seconds=ladder[0]))
        assert [c.id for c in second] == [item.id]

        # Walk the rest of the ladder to exhaustion: the 5th failed attempt
        # parks the item as FAILED, so the next claim finds nothing.
        now = base + timedelta(seconds=ladder[0])
        for step in ladder[1:]:
            dl.fail_cleanup_item(db_session, item.id, error_summary="s3 timeout", now=now)
            now = now + timedelta(seconds=step)
            claimed_now = dl.claim_cleanup_items(db_session, now=now)
            if not claimed_now:
                assert item.state == CleanupItemState.FAILED  # ladder exhausted
                break
            dl.fail_cleanup_item(db_session, claimed_now[0].id, error_summary="s3 timeout", now=now)
        else:
            pytest.fail("ladder walk never exhausted the item")
        db_session.refresh(item)
        assert item.attempts == 5
        assert item.state == CleanupItemState.FAILED
        assert item.last_error == "s3 timeout"
        assert item.next_retry_at is None
        assert dl.claim_cleanup_items(db_session, now=now + timedelta(hours=1)) == []

    def test_window_exhaustion_parks_failed_early(self, db_session, handle):
        operation = self._operation(db_session, handle)
        (item,) = dl.enqueue_cleanup_items(
            db_session,
            operation,
            [_object_spec()],
        )
        # Simulate an item created a day ago with attempts still left.
        item.created_at = item.created_at - dl.CLEANUP_AUTO_RETRY_WINDOW - timedelta(minutes=1)
        (claimed,) = dl.claim_cleanup_items(db_session)
        failed = dl.fail_cleanup_item(db_session, claimed.id, error_summary="late failure")
        assert failed.state == CleanupItemState.FAILED  # 24h window spent

    def test_crashed_claim_self_heals_after_lease(self, db_session, handle):
        operation = self._operation(db_session, handle)
        (item,) = dl.enqueue_cleanup_items(
            db_session,
            operation,
            [_object_spec()],
        )
        (claimed,) = dl.claim_cleanup_items(db_session)
        assert claimed.state == CleanupItemState.CLAIMED
        assert claimed.claimed_at is not None
        # Before the lease lapses: no reclaim.
        soon = claimed.claimed_at + dl.CLEANUP_CLAIM_LEASE - timedelta(seconds=1)
        assert dl.claim_cleanup_items(db_session, now=soon) == []
        # After: reclaimed (crashed executor's hold heals, attempts counted).
        later = claimed.claimed_at + dl.CLEANUP_CLAIM_LEASE + timedelta(seconds=1)
        (reclaimed,) = dl.claim_cleanup_items(db_session, now=later)
        assert reclaimed.id == item.id
        assert reclaimed.attempts == 2


class TestBarriers:
    def _raise(
        self, db_session, handle, scope=DataBarrierScope.SOURCE, ids=("a", "b")
    ) -> DataBarrier:
        target = {"kind": "source", "ids": list(ids)} if scope != DataBarrierScope.ACCOUNT else None
        return dl.raise_barrier(
            db_session, owner_handle=handle, scope=scope, raised_generation=2, target=target
        )

    def test_account_barrier_blocks_everything(self, db_session, handle):
        self._raise(db_session, handle, scope=DataBarrierScope.ACCOUNT)
        for scope in DataBarrierScope:
            with pytest.raises(dl.BarrierConflict):
                dl.assert_writable(db_session, owner_handle=handle, scope=scope, target_ids={"x"})

    def test_source_barrier_matches_targets_only(self, db_session, handle):
        self._raise(db_session, handle, scope=DataBarrierScope.SOURCE, ids=("a", "b"))
        with pytest.raises(dl.BarrierConflict):
            dl.assert_writable(
                db_session,
                owner_handle=handle,
                scope=DataBarrierScope.SOURCE,
                target_ids={"b", "c"},
            )
        # Touching only unaffected targets stays writable.
        dl.assert_writable(
            db_session, owner_handle=handle, scope=DataBarrierScope.SOURCE, target_ids={"c"}
        )

    def test_scoped_barrier_fails_closed_when_targets_unspecified(self, db_session, handle):
        # A same-scope write that does not say which ids it touches cannot
        # disprove overlap with the barrier, so it conflicts (B carry item
        # on #70: None must not bypass a scoped barrier).
        self._raise(db_session, handle, scope=DataBarrierScope.SOURCE, ids=("a", "b"))
        with pytest.raises(dl.BarrierConflict):
            dl.assert_writable(db_session, owner_handle=handle, scope=DataBarrierScope.SOURCE)
        # A different scope stays provable: no memory barrier exists, so a
        # memory-scope write is writable even without ids.
        dl.assert_writable(db_session, owner_handle=handle, scope=DataBarrierScope.MEMORY)

    def test_other_owners_are_not_blocked(self, db_session, handle):
        self._raise(db_session, handle, scope=DataBarrierScope.ACCOUNT)
        dl.assert_writable(
            db_session, owner_handle="0" * 32, scope=DataBarrierScope.SOURCE, target_ids={"a"}
        )

    def test_release_requires_completed_non_account(self, db_session, handle):
        operation, _ = dl.get_or_create_operation(
            db_session, handle, _deletion_request({"kind": "source", "ids": ["a"]})
        )
        barrier = self._raise(db_session, handle)
        # FAILED operation must NOT release the barrier (A-draft §2.2).
        operation.status = DataOperationStatus.FAILED
        with pytest.raises(dl.LifecycleError):
            dl.release_barrier(db_session, barrier.id, completed_operation=operation)
        db_session.refresh(barrier)
        assert barrier.state == DataBarrierState.ACTIVE
        # COMPLETED releases it; double release is refused.
        operation.status = DataOperationStatus.COMPLETED
        released = dl.release_barrier(db_session, barrier.id, completed_operation=operation)
        assert released.state == DataBarrierState.RELEASED
        with pytest.raises(dl.LifecycleError):
            dl.release_barrier(db_session, barrier.id, completed_operation=operation)
        # Account barriers are never auto-released.
        account = self._raise(db_session, handle, scope=DataBarrierScope.ACCOUNT)
        with pytest.raises(dl.LifecycleError):
            dl.release_barrier(db_session, account.id, completed_operation=operation)

    def test_lock_owner_barriers_rows(self, db_session, handle):
        self._raise(db_session, handle)
        self._raise(db_session, handle, scope=DataBarrierScope.ACCOUNT)
        locked = dl.lock_owner_barriers(db_session, handle)
        assert len(locked) == 2

    def test_assert_writable_checks_generation_too(self, db_session, handle, user):
        dl.assert_writable(
            db_session,
            owner_handle=handle,
            scope=DataBarrierScope.SOURCE,
            target_ids={"a"},
            observed_generation=1,
            user_id=user.id,
        )
        dl.bump_data_generation(db_session, user.id)
        with pytest.raises(dl.GenerationStale):
            dl.assert_writable(
                db_session,
                owner_handle=handle,
                scope=DataBarrierScope.SOURCE,
                target_ids={"a"},
                observed_generation=1,
                user_id=user.id,
            )


class TestDependencyInventory:
    def test_inventory_is_clean(self):
        report = audit_inventory()
        assert report.ok, report

    def test_unregistered_table_fails_closed(self):
        fake = Table("zz_fake_unregistered", Base.metadata, Column("id", Integer))
        try:
            report = audit_inventory()
            assert not report.ok
            assert "zz_fake_unregistered" in report.unregistered_tables
        finally:
            Base.metadata.remove(fake)

    def test_unregistered_redis_literal_fails_closed(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.data_registry.redis_literals_in_source",
            lambda: redis_literals_in_source() | {"agenthu:new:hotness"},
        )
        report = audit_inventory()
        assert not report.ok
        assert "agenthu:new:hotness" in report.unregistered_redis_literals

    def test_stale_redis_entry_fails_closed(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.data_registry.redis_literals_in_source",
            lambda: set(),
        )
        report = audit_inventory()
        assert report.stale_redis_entries  # registered but absent from code

    def test_registry_entries_are_meaningful(self):
        for entry in REGISTRY:
            assert entry.key and entry.store in {
                Store.POSTGRES,
                Store.REDIS,
                Store.OBJECT_STORAGE,
                Store.LOCAL_CLIENT,
            }
            if entry.store == Store.POSTGRES:
                assert entry.table and entry.owner and entry.disposal
                assert entry.classification
