use std::time::Duration;

use async_trait::async_trait;
use qingyin_types::{SessionId, SessionState, TimestampMs};

use crate::{
    MutationOutcome, OutboxEntry, OutboxId, OutboxRecord, ReservationId, ReservationRecord,
    SessionRecord, StateResult, TenantScope, TtlEntry, TtlExtendResult, TtlKey, TtlPutResult,
    TtlRevision, TtlTakeResult, TtlValue,
};

/// Durable state store capable of creating isolated atomic transactions.
#[async_trait]
pub trait DurableStateStore: Send + Sync {
    /// Starts a transaction with a consistent view of durable state.
    async fn begin(&self) -> StateResult<Box<dyn StateTransaction>>;
}

/// Atomic durable transaction for sessions, reservations, and outbox records.
///
/// Implementations must reject every operation after commit, rollback, or a
/// failed commit. Commit exposes all applied mutations together; rollback
/// exposes none of them.
#[async_trait]
pub trait StateTransaction: Send {
    /// Reads a session only inside the exact tenant scope.
    async fn session(
        &mut self,
        scope: &TenantScope,
        session_id: &SessionId,
    ) -> StateResult<Option<SessionRecord>>;

    /// Inserts a session idempotently when identical content already exists.
    async fn insert_session(&mut self, record: SessionRecord) -> StateResult<MutationOutcome>;

    /// Applies one canonical transition using optimistic revision control.
    ///
    /// Retrying the same target state is idempotent even when the caller still
    /// carries the preceding revision. A different target with a stale revision
    /// is a conflict.
    async fn transition_session(
        &mut self,
        scope: &TenantScope,
        session_id: &SessionId,
        expected_revision: u64,
        next: SessionState,
        updated_at_ms: TimestampMs,
    ) -> StateResult<SessionRecord>;

    /// Reads a reservation only inside the exact tenant scope.
    async fn reservation(
        &mut self,
        scope: &TenantScope,
        reservation_id: &ReservationId,
    ) -> StateResult<Option<ReservationRecord>>;

    /// Inserts a reservation idempotently when identical content already exists.
    async fn insert_reservation(
        &mut self,
        record: ReservationRecord,
    ) -> StateResult<MutationOutcome>;

    /// Appends an outbox record idempotently by its stable identity.
    async fn append_outbox(&mut self, record: OutboxRecord) -> StateResult<MutationOutcome>;

    /// Reads an outbox entry only inside the exact tenant scope.
    async fn outbox(
        &mut self,
        scope: &TenantScope,
        outbox_id: &OutboxId,
    ) -> StateResult<Option<OutboxEntry>>;

    /// Returns pending outbox records in deterministic append order.
    async fn pending_outbox(
        &mut self,
        scope: &TenantScope,
        limit: usize,
    ) -> StateResult<Vec<OutboxEntry>>;

    /// Acknowledges an outbox record once while preserving the first timestamp.
    async fn acknowledge_outbox(
        &mut self,
        scope: &TenantScope,
        outbox_id: &OutboxId,
        acknowledged_at_ms: TimestampMs,
    ) -> StateResult<MutationOutcome>;

    /// Atomically publishes every applied mutation.
    async fn commit(&mut self) -> StateResult<()>;

    /// Discards every applied mutation.
    async fn rollback(&mut self) -> StateResult<()>;
}

/// Ephemeral tenant-scoped state with atomic TTL operations.
///
/// Expiry uses store-owned monotonic time. Implementations must treat
/// `now >= expires_at` as absent and must never resurrect an expired value.
#[async_trait]
pub trait TtlStore: Send + Sync {
    /// Stores a value only when no live value occupies the key.
    async fn put_if_absent(
        &self,
        scope: &TenantScope,
        key: &TtlKey,
        value: TtlValue,
        ttl: Duration,
    ) -> StateResult<TtlPutResult>;

    /// Reads a live value and its conditional-operation revision.
    async fn get(&self, scope: &TenantScope, key: &TtlKey) -> StateResult<Option<TtlEntry>>;

    /// Extends one live value only when its revision still matches.
    ///
    /// A successful extension assigns a new revision so stale consumers cannot
    /// remove a lease that was concurrently renewed.
    async fn compare_and_extend(
        &self,
        scope: &TenantScope,
        key: &TtlKey,
        expected_revision: TtlRevision,
        ttl: Duration,
    ) -> StateResult<TtlExtendResult>;

    /// Removes and returns a live value only when its revision still matches.
    async fn compare_and_take(
        &self,
        scope: &TenantScope,
        key: &TtlKey,
        expected_revision: TtlRevision,
    ) -> StateResult<TtlTakeResult>;

    /// Removes a live value idempotently without returning its payload.
    async fn remove(&self, scope: &TenantScope, key: &TtlKey) -> StateResult<MutationOutcome>;
}
