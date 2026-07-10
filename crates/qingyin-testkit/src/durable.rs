use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};

use async_trait::async_trait;
use qingyin_state::{
    DurableStateStore, MutationOutcome, OutboxEntry, OutboxId, OutboxRecord, ReservationId,
    ReservationRecord, SessionRecord, StateEntity, StateError, StateResult, StateTransaction,
    TenantScope,
};
use qingyin_types::{SessionId, SessionState, TimestampMs};

type SessionKey = (TenantScope, SessionId);
type ReservationKey = (TenantScope, ReservationId);
type OutboxKey = (TenantScope, OutboxId);

#[derive(Clone, Default)]
struct StoreData {
    generation: u64,
    sessions: HashMap<SessionKey, SessionRecord>,
    reservations: HashMap<ReservationKey, ReservationRecord>,
    outbox: HashMap<OutboxKey, OutboxEntry>,
    outbox_order: Vec<OutboxKey>,
}

/// Deterministic durable-state fake with optimistic snapshot transactions.
///
/// A transaction clones the small test snapshot. Commit replaces the shared
/// snapshot only when no other transaction committed after it began, making
/// uncommitted state invisible and concurrent conflicts reproducible.
#[derive(Clone, Default)]
pub struct InMemoryStateStore {
    inner: Arc<Mutex<StoreData>>,
}

impl InMemoryStateStore {
    fn lock(&self) -> StateResult<MutexGuard<'_, StoreData>> {
        self.inner.lock().map_err(|_| StateError::StoreUnavailable)
    }
}

#[async_trait]
impl DurableStateStore for InMemoryStateStore {
    async fn begin(&self) -> StateResult<Box<dyn StateTransaction>> {
        let snapshot = self.lock()?.clone();
        Ok(Box::new(InMemoryTransaction {
            shared: self.clone(),
            base_generation: snapshot.generation,
            working: snapshot,
            dirty: false,
            finalized: false,
        }))
    }
}

struct InMemoryTransaction {
    shared: InMemoryStateStore,
    base_generation: u64,
    working: StoreData,
    dirty: bool,
    finalized: bool,
}

impl InMemoryTransaction {
    fn ensure_active(&self) -> StateResult<()> {
        if self.finalized {
            Err(StateError::TransactionFinalized)
        } else {
            Ok(())
        }
    }
}

#[async_trait]
impl StateTransaction for InMemoryTransaction {
    async fn session(
        &mut self,
        scope: &TenantScope,
        session_id: &SessionId,
    ) -> StateResult<Option<SessionRecord>> {
        self.ensure_active()?;
        Ok(self
            .working
            .sessions
            .get(&(scope.clone(), session_id.clone()))
            .cloned())
    }

    async fn insert_session(&mut self, record: SessionRecord) -> StateResult<MutationOutcome> {
        self.ensure_active()?;
        let key = (record.scope().clone(), record.session_id().clone());
        if let Some(existing) = self.working.sessions.get(&key) {
            return if existing == &record {
                Ok(MutationOutcome::Unchanged)
            } else {
                Err(StateError::Conflict(StateEntity::Session))
            };
        }
        self.working.sessions.insert(key, record);
        self.dirty = true;
        Ok(MutationOutcome::Applied)
    }

    async fn transition_session(
        &mut self,
        scope: &TenantScope,
        session_id: &SessionId,
        expected_revision: u64,
        next: SessionState,
        updated_at_ms: TimestampMs,
    ) -> StateResult<SessionRecord> {
        self.ensure_active()?;
        let key = (scope.clone(), session_id.clone());
        let current = self
            .working
            .sessions
            .get(&key)
            .cloned()
            .ok_or(StateError::NotFound(StateEntity::Session))?;

        if current.state() == next {
            return Ok(current);
        }
        if current.revision() != expected_revision {
            return Err(StateError::Conflict(StateEntity::Session));
        }

        let transitioned = current.transitioned(next, updated_at_ms)?;
        self.working.sessions.insert(key, transitioned.clone());
        self.dirty = true;
        Ok(transitioned)
    }

    async fn reservation(
        &mut self,
        scope: &TenantScope,
        reservation_id: &ReservationId,
    ) -> StateResult<Option<ReservationRecord>> {
        self.ensure_active()?;
        Ok(self
            .working
            .reservations
            .get(&(scope.clone(), reservation_id.clone()))
            .cloned())
    }

    async fn insert_reservation(
        &mut self,
        record: ReservationRecord,
    ) -> StateResult<MutationOutcome> {
        self.ensure_active()?;
        let key = (record.scope().clone(), record.reservation_id().clone());
        if let Some(existing) = self.working.reservations.get(&key) {
            return if existing == &record {
                Ok(MutationOutcome::Unchanged)
            } else {
                Err(StateError::Conflict(StateEntity::Reservation))
            };
        }
        self.working.reservations.insert(key, record);
        self.dirty = true;
        Ok(MutationOutcome::Applied)
    }

    async fn append_outbox(&mut self, record: OutboxRecord) -> StateResult<MutationOutcome> {
        self.ensure_active()?;
        let key = (record.scope().clone(), record.outbox_id().clone());
        if let Some(existing) = self.working.outbox.get(&key) {
            return if existing.record() == &record {
                Ok(MutationOutcome::Unchanged)
            } else {
                Err(StateError::Conflict(StateEntity::Outbox))
            };
        }
        self.working.outbox_order.push(key.clone());
        self.working
            .outbox
            .insert(key, OutboxEntry::pending(record));
        self.dirty = true;
        Ok(MutationOutcome::Applied)
    }

    async fn outbox(
        &mut self,
        scope: &TenantScope,
        outbox_id: &OutboxId,
    ) -> StateResult<Option<OutboxEntry>> {
        self.ensure_active()?;
        Ok(self
            .working
            .outbox
            .get(&(scope.clone(), outbox_id.clone()))
            .cloned())
    }

    async fn pending_outbox(
        &mut self,
        scope: &TenantScope,
        limit: usize,
    ) -> StateResult<Vec<OutboxEntry>> {
        self.ensure_active()?;
        if limit == 0 {
            return Err(StateError::InvalidArgument("outbox_limit"));
        }

        Ok(self
            .working
            .outbox_order
            .iter()
            .filter(|(entry_scope, _)| entry_scope == scope)
            .filter_map(|key| self.working.outbox.get(key))
            .filter(|entry| entry.acknowledged_at_ms().is_none())
            .take(limit)
            .cloned()
            .collect())
    }

    async fn acknowledge_outbox(
        &mut self,
        scope: &TenantScope,
        outbox_id: &OutboxId,
        acknowledged_at_ms: TimestampMs,
    ) -> StateResult<MutationOutcome> {
        self.ensure_active()?;
        let entry = self
            .working
            .outbox
            .get_mut(&(scope.clone(), outbox_id.clone()))
            .ok_or(StateError::NotFound(StateEntity::Outbox))?;
        let outcome = entry.acknowledge(acknowledged_at_ms)?;
        if outcome == MutationOutcome::Applied {
            self.dirty = true;
        }
        Ok(outcome)
    }

    async fn commit(&mut self) -> StateResult<()> {
        self.ensure_active()?;
        self.finalized = true;
        if !self.dirty {
            return Ok(());
        }

        let mut shared = self.shared.lock()?;
        if shared.generation != self.base_generation {
            return Err(StateError::Conflict(StateEntity::Transaction));
        }
        self.working.generation = shared
            .generation
            .checked_add(1)
            .ok_or(StateError::Conflict(StateEntity::Transaction))?;
        *shared = self.working.clone();
        Ok(())
    }

    async fn rollback(&mut self) -> StateResult<()> {
        self.ensure_active()?;
        self.finalized = true;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU64;

    use futures_executor::block_on;
    use qingyin_state::{
        EnvironmentId, MonotonicTime, OrganizationId, OutboxPayload, ProjectId,
        ReservationKey as StateReservationKey, SessionReferences, WorkspaceId,
    };
    use qingyin_types::{ResourceId, SessionId, SessionState, TimestampMs, TraceId};

    use super::*;

    fn resource_id(value: &str) -> StateResult<ResourceId> {
        ResourceId::new(value).ok_or(StateError::InvalidArgument("test_resource_id"))
    }

    fn session_id(value: &str) -> StateResult<SessionId> {
        SessionId::new(value).ok_or(StateError::InvalidArgument("test_session_id"))
    }

    fn trace_id(value: &str) -> StateResult<TraceId> {
        TraceId::new(value).ok_or(StateError::InvalidArgument("test_trace_id"))
    }

    fn scope(suffix: &str) -> StateResult<TenantScope> {
        Ok(TenantScope::new(
            OrganizationId::new(resource_id(&format!("org_{suffix}001"))?),
            WorkspaceId::new(resource_id(&format!("wsp_{suffix}001"))?),
            ProjectId::new(resource_id(&format!("prj_{suffix}001"))?),
            EnvironmentId::new(resource_id(&format!("env_{suffix}001"))?),
        ))
    }

    fn session_record(
        scope: TenantScope,
        id: &str,
        state: SessionState,
    ) -> StateResult<SessionRecord> {
        Ok(SessionRecord::new(
            scope,
            session_id(id)?,
            trace_id("trc_test001")?,
            state,
            SessionReferences::new(
                resource_id("rte_test001")?,
                resource_id("pol_test001")?,
                resource_id("cap_test001")?,
                resource_id("pvd_test001")?,
            ),
            TimestampMs(1),
        ))
    }

    fn reservation_record(
        scope: TenantScope,
        reservation: &str,
        session: &str,
    ) -> StateResult<ReservationRecord> {
        let quantity =
            NonZeroU64::new(1).ok_or(StateError::InvalidArgument("test_reservation_quantity"))?;
        ReservationRecord::new(
            scope,
            ReservationId::new(resource_id(reservation)?),
            session_id(session)?,
            StateReservationKey::new("active_session")?,
            quantity,
            MonotonicTime::from_millis(0),
            MonotonicTime::from_millis(1_000),
        )
    }

    fn outbox_record(
        scope: TenantScope,
        outbox: &str,
        aggregate: &str,
        sequence: u64,
    ) -> StateResult<OutboxRecord> {
        OutboxRecord::new(
            scope,
            OutboxId::new(resource_id(outbox)?),
            resource_id(aggregate)?,
            "session.lifecycle",
            sequence,
            TimestampMs(sequence + 1),
            OutboxPayload::new(format!("event-{sequence}").into_bytes())?,
        )
    }

    #[test]
    fn commit_is_atomic_and_rollback_is_invisible() -> StateResult<()> {
        block_on(async {
            let store = InMemoryStateStore::default();
            let tenant = scope("a")?;
            let session = session_record(tenant.clone(), "ses_atom001", SessionState::Leased)?;
            let reservation = reservation_record(tenant.clone(), "rsv_atom001", "ses_atom001")?;
            let outbox = outbox_record(tenant.clone(), "obx_atom001", "ses_atom001", 0)?;

            let mut transaction = store.begin().await?;
            assert_eq!(
                transaction.insert_session(session.clone()).await?,
                MutationOutcome::Applied
            );
            assert_eq!(
                transaction.insert_reservation(reservation.clone()).await?,
                MutationOutcome::Applied
            );
            assert_eq!(
                transaction.append_outbox(outbox.clone()).await?,
                MutationOutcome::Applied
            );

            let mut before_commit = store.begin().await?;
            assert!(
                before_commit
                    .session(&tenant, session.session_id())
                    .await?
                    .is_none()
            );
            before_commit.rollback().await?;
            transaction.commit().await?;

            let mut after_commit = store.begin().await?;
            assert_eq!(
                after_commit.session(&tenant, session.session_id()).await?,
                Some(session)
            );
            assert_eq!(
                after_commit
                    .reservation(&tenant, reservation.reservation_id())
                    .await?,
                Some(reservation)
            );
            assert_eq!(after_commit.pending_outbox(&tenant, 10).await?.len(), 1);
            after_commit.rollback().await?;

            let rolled_back = session_record(tenant.clone(), "ses_roll001", SessionState::Created)?;
            let mut rollback = store.begin().await?;
            rollback.insert_session(rolled_back.clone()).await?;
            rollback.rollback().await?;
            let mut verify = store.begin().await?;
            assert!(
                verify
                    .session(&tenant, rolled_back.session_id())
                    .await?
                    .is_none()
            );
            Ok(())
        })
    }

    #[test]
    fn finalized_transaction_rejects_every_later_operation() -> StateResult<()> {
        block_on(async {
            let store = InMemoryStateStore::default();
            let tenant = scope("a")?;
            let mut transaction = store.begin().await?;
            transaction.rollback().await?;
            assert_eq!(
                transaction.rollback().await,
                Err(StateError::TransactionFinalized)
            );
            assert_eq!(
                transaction
                    .session(&tenant, &session_id("ses_done001")?)
                    .await,
                Err(StateError::TransactionFinalized)
            );

            let mut committed = store.begin().await?;
            committed.commit().await?;
            assert_eq!(
                committed.commit().await,
                Err(StateError::TransactionFinalized)
            );
            Ok(())
        })
    }

    #[test]
    fn session_transition_is_optimistic_idempotent_and_terminal() -> StateResult<()> {
        block_on(async {
            let store = InMemoryStateStore::default();
            let tenant = scope("a")?;
            let session = session_record(tenant.clone(), "ses_state01", SessionState::Created)?;
            let session_id = session.session_id().clone();
            let mut seed = store.begin().await?;
            seed.insert_session(session).await?;
            seed.commit().await?;

            let mut transaction = store.begin().await?;
            let authorized = transaction
                .transition_session(
                    &tenant,
                    &session_id,
                    0,
                    SessionState::Authorized,
                    TimestampMs(2),
                )
                .await?;
            assert_eq!(authorized.revision(), 1);
            let retry = transaction
                .transition_session(
                    &tenant,
                    &session_id,
                    0,
                    SessionState::Authorized,
                    TimestampMs(3),
                )
                .await?;
            assert_eq!(retry, authorized);
            assert_eq!(
                transaction
                    .transition_session(
                        &tenant,
                        &session_id,
                        0,
                        SessionState::Leased,
                        TimestampMs(3),
                    )
                    .await,
                Err(StateError::Conflict(StateEntity::Session))
            );
            let cancelled = transaction
                .transition_session(
                    &tenant,
                    &session_id,
                    1,
                    SessionState::Cancelled,
                    TimestampMs(3),
                )
                .await?;
            assert_eq!(cancelled.state(), SessionState::Cancelled);
            assert_eq!(
                transaction
                    .transition_session(
                        &tenant,
                        &session_id,
                        cancelled.revision(),
                        SessionState::Failed,
                        TimestampMs(4),
                    )
                    .await,
                Err(StateError::InvalidTransition {
                    from: SessionState::Cancelled,
                    to: SessionState::Failed,
                })
            );
            transaction.commit().await?;
            Ok(())
        })
    }

    #[test]
    fn concurrent_snapshot_commits_have_one_winner() -> StateResult<()> {
        block_on(async {
            let store = InMemoryStateStore::default();
            let tenant = scope("a")?;
            let mut first = store.begin().await?;
            let mut second = store.begin().await?;
            first
                .insert_session(session_record(
                    tenant.clone(),
                    "ses_win0001",
                    SessionState::Created,
                )?)
                .await?;
            second
                .insert_session(session_record(
                    tenant.clone(),
                    "ses_lose001",
                    SessionState::Created,
                )?)
                .await?;

            first.commit().await?;
            assert_eq!(
                second.commit().await,
                Err(StateError::Conflict(StateEntity::Transaction))
            );
            assert_eq!(
                second.rollback().await,
                Err(StateError::TransactionFinalized)
            );

            let mut verify = store.begin().await?;
            assert!(
                verify
                    .session(&tenant, &session_id("ses_win0001")?)
                    .await?
                    .is_some()
            );
            assert!(
                verify
                    .session(&tenant, &session_id("ses_lose001")?)
                    .await?
                    .is_none()
            );
            Ok(())
        })
    }

    #[test]
    fn reservation_and_outbox_writes_are_content_idempotent() -> StateResult<()> {
        block_on(async {
            let store = InMemoryStateStore::default();
            let tenant = scope("a")?;
            let reservation = reservation_record(tenant.clone(), "rsv_same001", "ses_same001")?;
            let first_outbox = outbox_record(tenant.clone(), "obx_same001", "ses_same001", 0)?;
            let second_outbox = outbox_record(tenant.clone(), "obx_next001", "ses_same001", 1)?;
            let mut transaction = store.begin().await?;

            assert_eq!(
                transaction.insert_reservation(reservation.clone()).await?,
                MutationOutcome::Applied
            );
            assert_eq!(
                transaction.insert_reservation(reservation).await?,
                MutationOutcome::Unchanged
            );
            let conflicting_reservation =
                reservation_record(tenant.clone(), "rsv_same001", "ses_other001")?;
            assert_eq!(
                transaction
                    .insert_reservation(conflicting_reservation)
                    .await,
                Err(StateError::Conflict(StateEntity::Reservation))
            );
            assert_eq!(
                transaction.append_outbox(first_outbox.clone()).await?,
                MutationOutcome::Applied
            );
            assert_eq!(
                transaction.append_outbox(first_outbox.clone()).await?,
                MutationOutcome::Unchanged
            );
            let conflicting_outbox =
                outbox_record(tenant.clone(), "obx_same001", "ses_same001", 99)?;
            assert_eq!(
                transaction.append_outbox(conflicting_outbox).await,
                Err(StateError::Conflict(StateEntity::Outbox))
            );
            transaction.append_outbox(second_outbox).await?;

            let pending = transaction.pending_outbox(&tenant, 10).await?;
            assert_eq!(pending.len(), 2);
            let first = pending
                .first()
                .ok_or(StateError::NotFound(StateEntity::Outbox))?;
            assert!(first.record() == &first_outbox);
            assert_eq!(
                transaction
                    .acknowledge_outbox(&tenant, first_outbox.outbox_id(), TimestampMs(10))
                    .await?,
                MutationOutcome::Applied
            );
            assert_eq!(
                transaction
                    .acknowledge_outbox(&tenant, first_outbox.outbox_id(), TimestampMs(11))
                    .await?,
                MutationOutcome::Unchanged
            );
            let acknowledged = transaction
                .outbox(&tenant, first_outbox.outbox_id())
                .await?
                .ok_or(StateError::NotFound(StateEntity::Outbox))?;
            assert_eq!(acknowledged.acknowledged_at_ms(), Some(TimestampMs(10)));
            assert_eq!(transaction.pending_outbox(&tenant, 10).await?.len(), 1);
            transaction.commit().await?;
            Ok(())
        })
    }

    #[test]
    fn identical_local_ids_remain_tenant_isolated() -> StateResult<()> {
        block_on(async {
            let store = InMemoryStateStore::default();
            let tenant_a = scope("a")?;
            let tenant_b = scope("b")?;
            let shared_id = "ses_scope01";
            let session_a = session_record(tenant_a.clone(), shared_id, SessionState::Created)?;
            let session_b = session_record(tenant_b.clone(), shared_id, SessionState::Leased)?;
            let mut seed = store.begin().await?;
            seed.insert_session(session_a.clone()).await?;
            seed.insert_session(session_b.clone()).await?;
            seed.commit().await?;

            let mut verify = store.begin().await?;
            assert_eq!(
                verify.session(&tenant_a, session_a.session_id()).await?,
                Some(session_a)
            );
            assert_eq!(
                verify.session(&tenant_b, session_b.session_id()).await?,
                Some(session_b)
            );
            Ok(())
        })
    }
}
