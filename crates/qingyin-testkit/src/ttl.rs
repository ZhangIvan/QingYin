use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use async_trait::async_trait;
use qingyin_state::{
    MonotonicClock, MutationOutcome, StateEntity, StateError, StateResult, TenantScope, TtlEntry,
    TtlExtendResult, TtlKey, TtlPutResult, TtlRevision, TtlStore, TtlTakeResult, TtlValue,
};

use crate::VirtualClock;

type ScopedTtlKey = (TenantScope, TtlKey);

#[derive(Default)]
struct TtlData {
    next_revision: u64,
    entries: HashMap<ScopedTtlKey, TtlEntry>,
}

/// Deterministic tenant-scoped TTL fake driven by an injected monotonic clock.
#[derive(Clone)]
pub struct InMemoryTtlStore<C = VirtualClock> {
    clock: C,
    inner: Arc<Mutex<TtlData>>,
}

impl<C> InMemoryTtlStore<C> {
    /// Creates an empty TTL store using the supplied monotonic clock.
    #[must_use]
    pub fn new(clock: C) -> Self {
        Self {
            clock,
            inner: Arc::new(Mutex::new(TtlData::default())),
        }
    }

    /// Returns the injected clock so tests can advance shared virtual time.
    #[must_use]
    pub const fn clock(&self) -> &C {
        &self.clock
    }

    fn lock(&self) -> StateResult<MutexGuard<'_, TtlData>> {
        self.inner.lock().map_err(|_| StateError::StoreUnavailable)
    }
}

impl Default for InMemoryTtlStore<VirtualClock> {
    fn default() -> Self {
        Self::new(VirtualClock::default())
    }
}

impl<C: MonotonicClock> InMemoryTtlStore<C> {
    fn purge_if_expired(data: &mut TtlData, key: &ScopedTtlKey, now: qingyin_state::MonotonicTime) {
        let expired = data
            .entries
            .get(key)
            .is_some_and(|entry| now >= entry.expires_at());
        if expired {
            data.entries.remove(key);
        }
    }

    fn next_revision(data: &mut TtlData) -> StateResult<TtlRevision> {
        data.next_revision = data
            .next_revision
            .checked_add(1)
            .ok_or(StateError::Conflict(StateEntity::TtlValue))?;
        Ok(TtlRevision::new(data.next_revision))
    }
}

#[async_trait]
impl<C> TtlStore for InMemoryTtlStore<C>
where
    C: MonotonicClock + Send + Sync,
{
    async fn put_if_absent(
        &self,
        scope: &TenantScope,
        key: &TtlKey,
        value: TtlValue,
        ttl: Duration,
    ) -> StateResult<TtlPutResult> {
        if ttl.is_zero() {
            return Err(StateError::InvalidArgument("ttl"));
        }
        let now = self.clock.now();
        let expires_at = now.checked_add(ttl)?;
        let scoped_key = (scope.clone(), key.clone());
        let mut data = self.lock()?;
        Self::purge_if_expired(&mut data, &scoped_key, now);
        if let Some(existing) = data.entries.get(&scoped_key) {
            return Ok(TtlPutResult::Existing(existing.revision()));
        }

        let revision = Self::next_revision(&mut data)?;
        data.entries
            .insert(scoped_key, TtlEntry::new(value, revision, expires_at));
        Ok(TtlPutResult::Inserted(revision))
    }

    async fn get(&self, scope: &TenantScope, key: &TtlKey) -> StateResult<Option<TtlEntry>> {
        let now = self.clock.now();
        let scoped_key = (scope.clone(), key.clone());
        let mut data = self.lock()?;
        Self::purge_if_expired(&mut data, &scoped_key, now);
        Ok(data.entries.get(&scoped_key).cloned())
    }

    async fn compare_and_extend(
        &self,
        scope: &TenantScope,
        key: &TtlKey,
        expected_revision: TtlRevision,
        ttl: Duration,
    ) -> StateResult<TtlExtendResult> {
        if ttl.is_zero() {
            return Err(StateError::InvalidArgument("ttl"));
        }
        let now = self.clock.now();
        let expires_at = now.checked_add(ttl)?;
        let scoped_key = (scope.clone(), key.clone());
        let mut data = self.lock()?;
        Self::purge_if_expired(&mut data, &scoped_key, now);
        let Some(entry) = data.entries.get(&scoped_key) else {
            return Ok(TtlExtendResult::Missing);
        };
        if entry.revision() != expected_revision {
            return Ok(TtlExtendResult::RevisionMismatch {
                current: entry.revision(),
            });
        }

        let value = entry.value().clone();
        let revision = Self::next_revision(&mut data)?;
        data.entries
            .insert(scoped_key, TtlEntry::new(value, revision, expires_at));
        Ok(TtlExtendResult::Extended {
            revision,
            expires_at,
        })
    }

    async fn compare_and_take(
        &self,
        scope: &TenantScope,
        key: &TtlKey,
        expected_revision: TtlRevision,
    ) -> StateResult<TtlTakeResult> {
        let now = self.clock.now();
        let scoped_key = (scope.clone(), key.clone());
        let mut data = self.lock()?;
        Self::purge_if_expired(&mut data, &scoped_key, now);
        let Some(entry) = data.entries.get(&scoped_key) else {
            return Ok(TtlTakeResult::Missing);
        };
        if entry.revision() != expected_revision {
            return Ok(TtlTakeResult::RevisionMismatch {
                current: entry.revision(),
            });
        }

        match data.entries.remove(&scoped_key) {
            Some(removed) => Ok(TtlTakeResult::Taken(removed.value().clone())),
            None => Ok(TtlTakeResult::Missing),
        }
    }

    async fn remove(&self, scope: &TenantScope, key: &TtlKey) -> StateResult<MutationOutcome> {
        let now = self.clock.now();
        let scoped_key = (scope.clone(), key.clone());
        let mut data = self.lock()?;
        Self::purge_if_expired(&mut data, &scoped_key, now);
        if data.entries.remove(&scoped_key).is_some() {
            Ok(MutationOutcome::Applied)
        } else {
            Ok(MutationOutcome::Unchanged)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Barrier, mpsc};
    use std::thread;

    use futures_executor::block_on;
    use qingyin_state::{EnvironmentId, MonotonicTime, OrganizationId, ProjectId, WorkspaceId};
    use qingyin_types::ResourceId;

    use super::*;

    fn resource_id(value: &str) -> StateResult<ResourceId> {
        ResourceId::new(value).ok_or(StateError::InvalidArgument("test_resource_id"))
    }

    fn scope(suffix: &str) -> StateResult<TenantScope> {
        Ok(TenantScope::new(
            OrganizationId::new(resource_id(&format!("org_{suffix}001"))?),
            WorkspaceId::new(resource_id(&format!("wsp_{suffix}001"))?),
            ProjectId::new(resource_id(&format!("prj_{suffix}001"))?),
            EnvironmentId::new(resource_id(&format!("env_{suffix}001"))?),
        ))
    }

    fn key() -> StateResult<TtlKey> {
        TtlKey::new("ticket", "digest-001")
    }

    fn value(value: &str) -> StateResult<TtlValue> {
        TtlValue::new(value.as_bytes().to_vec())
    }

    #[test]
    fn value_is_absent_at_exact_expiry_and_never_resurrects() -> StateResult<()> {
        block_on(async {
            let clock = VirtualClock::new(MonotonicTime::from_millis(1_000));
            let store = InMemoryTtlStore::new(clock.clone());
            let tenant = scope("a")?;
            let key = key()?;
            let inserted = store
                .put_if_absent(&tenant, &key, value("first")?, Duration::from_millis(10))
                .await?;
            assert!(matches!(inserted, TtlPutResult::Inserted(_)));

            clock.advance(Duration::from_millis(9))?;
            assert!(store.get(&tenant, &key).await?.is_some());
            clock.advance(Duration::from_millis(1))?;
            assert!(store.get(&tenant, &key).await?.is_none());
            clock.advance(Duration::from_secs(1))?;
            assert!(store.get(&tenant, &key).await?.is_none());

            let replaced = store
                .put_if_absent(&tenant, &key, value("second")?, Duration::from_millis(10))
                .await?;
            assert!(matches!(replaced, TtlPutResult::Inserted(_)));
            Ok(())
        })
    }

    #[test]
    fn put_if_absent_preserves_the_first_live_value() -> StateResult<()> {
        block_on(async {
            let store = InMemoryTtlStore::default();
            let tenant = scope("a")?;
            let key = key()?;
            let inserted = store
                .put_if_absent(&tenant, &key, value("first")?, Duration::from_secs(1))
                .await?;
            let revision = match inserted {
                TtlPutResult::Inserted(revision) => revision,
                TtlPutResult::Existing(_) => {
                    return Err(StateError::Conflict(StateEntity::TtlValue));
                }
            };
            assert_eq!(
                store
                    .put_if_absent(&tenant, &key, value("second")?, Duration::from_secs(2))
                    .await?,
                TtlPutResult::Existing(revision)
            );
            let live = store
                .get(&tenant, &key)
                .await?
                .ok_or(StateError::NotFound(StateEntity::TtlValue))?;
            assert_eq!(live.value().as_bytes(), b"first");
            assert_eq!(live.revision(), revision);
            Ok(())
        })
    }

    #[test]
    fn compare_and_take_has_exactly_one_winner() -> StateResult<()> {
        block_on(async {
            let store = InMemoryTtlStore::default();
            let tenant = scope("a")?;
            let key = key()?;
            let inserted = store
                .put_if_absent(
                    &tenant,
                    &key,
                    value("bound-record")?,
                    Duration::from_secs(1),
                )
                .await?;
            let revision = match inserted {
                TtlPutResult::Inserted(revision) => revision,
                TtlPutResult::Existing(_) => {
                    return Err(StateError::Conflict(StateEntity::TtlValue));
                }
            };

            assert!(matches!(
                store
                    .compare_and_take(&tenant, &key, TtlRevision::new(revision.get() + 1))
                    .await?,
                TtlTakeResult::RevisionMismatch { current } if current == revision
            ));
            let taken = store.compare_and_take(&tenant, &key, revision).await?;
            match taken {
                TtlTakeResult::Taken(value) => {
                    assert_eq!(value.as_bytes(), b"bound-record");
                }
                TtlTakeResult::Missing | TtlTakeResult::RevisionMismatch { .. } => {
                    return Err(StateError::Conflict(StateEntity::TtlValue));
                }
            }
            assert!(matches!(
                store.compare_and_take(&tenant, &key, revision).await?,
                TtlTakeResult::Missing
            ));
            Ok(())
        })
    }

    #[test]
    fn conditional_extension_renews_expiry_and_invalidates_old_revision() -> StateResult<()> {
        block_on(async {
            let clock = VirtualClock::new(MonotonicTime::from_millis(100));
            let store = InMemoryTtlStore::new(clock.clone());
            let tenant = scope("a")?;
            let key = key()?;
            let inserted = store
                .put_if_absent(&tenant, &key, value("lease")?, Duration::from_millis(10))
                .await?;
            let original_revision = match inserted {
                TtlPutResult::Inserted(revision) => revision,
                TtlPutResult::Existing(_) => {
                    return Err(StateError::Conflict(StateEntity::TtlValue));
                }
            };

            clock.advance(Duration::from_millis(5))?;
            let extended = store
                .compare_and_extend(&tenant, &key, original_revision, Duration::from_millis(10))
                .await?;
            let renewed_revision = match extended {
                TtlExtendResult::Extended {
                    revision,
                    expires_at,
                } => {
                    assert_eq!(expires_at, MonotonicTime::from_millis(115));
                    revision
                }
                TtlExtendResult::Missing | TtlExtendResult::RevisionMismatch { .. } => {
                    return Err(StateError::Conflict(StateEntity::TtlValue));
                }
            };
            assert!(renewed_revision > original_revision);
            assert!(matches!(
                store
                    .compare_and_take(&tenant, &key, original_revision)
                    .await?,
                TtlTakeResult::RevisionMismatch { current } if current == renewed_revision
            ));

            clock.advance(Duration::from_millis(9))?;
            assert!(store.get(&tenant, &key).await?.is_some());
            clock.advance(Duration::from_millis(1))?;
            assert!(store.get(&tenant, &key).await?.is_none());
            Ok(())
        })
    }

    #[test]
    fn concurrent_compare_and_take_has_exactly_one_winner() -> StateResult<()> {
        let store = Arc::new(InMemoryTtlStore::default());
        let tenant = scope("a")?;
        let key = key()?;
        let inserted = block_on(store.put_if_absent(
            &tenant,
            &key,
            value("bound-record")?,
            Duration::from_secs(1),
        ))?;
        let revision = match inserted {
            TtlPutResult::Inserted(revision) => revision,
            TtlPutResult::Existing(_) => {
                return Err(StateError::Conflict(StateEntity::TtlValue));
            }
        };

        let barrier = Arc::new(Barrier::new(2));
        let (sender, receiver) = mpsc::channel();
        let mut handles = Vec::with_capacity(2);
        for _ in 0..2 {
            let worker_store = Arc::clone(&store);
            let worker_scope = tenant.clone();
            let worker_key = key.clone();
            let worker_barrier = Arc::clone(&barrier);
            let worker_sender = sender.clone();
            handles.push(thread::spawn(move || {
                let _wait = worker_barrier.wait();
                let result =
                    block_on(worker_store.compare_and_take(&worker_scope, &worker_key, revision));
                drop(worker_sender.send(result));
            }));
        }
        drop(sender);

        let mut taken_count = 0;
        for _ in 0..2 {
            let result = receiver
                .recv()
                .map_err(|_| StateError::StoreUnavailable)??;
            match result {
                TtlTakeResult::Taken(value) => {
                    assert_eq!(value.as_bytes(), b"bound-record");
                    taken_count += 1;
                }
                TtlTakeResult::Missing => {}
                TtlTakeResult::RevisionMismatch { .. } => {
                    return Err(StateError::Conflict(StateEntity::TtlValue));
                }
            }
        }
        for handle in handles {
            if handle.join().is_err() {
                return Err(StateError::StoreUnavailable);
            }
        }
        assert_eq!(taken_count, 1);
        Ok(())
    }

    #[test]
    fn ttl_keys_are_tenant_isolated_and_remove_is_idempotent() -> StateResult<()> {
        block_on(async {
            let store = InMemoryTtlStore::default();
            let tenant_a = scope("a")?;
            let tenant_b = scope("b")?;
            let key = key()?;
            store
                .put_if_absent(&tenant_a, &key, value("a")?, Duration::from_secs(1))
                .await?;
            store
                .put_if_absent(&tenant_b, &key, value("b")?, Duration::from_secs(1))
                .await?;

            assert_eq!(
                store.remove(&tenant_a, &key).await?,
                MutationOutcome::Applied
            );
            assert_eq!(
                store.remove(&tenant_a, &key).await?,
                MutationOutcome::Unchanged
            );
            assert!(store.get(&tenant_a, &key).await?.is_none());
            let tenant_b_value = store
                .get(&tenant_b, &key)
                .await?
                .ok_or(StateError::NotFound(StateEntity::TtlValue))?;
            assert_eq!(tenant_b_value.value().as_bytes(), b"b");
            Ok(())
        })
    }

    #[test]
    fn zero_ttl_is_rejected_without_writing() -> StateResult<()> {
        block_on(async {
            let store = InMemoryTtlStore::default();
            let tenant = scope("a")?;
            let key = key()?;
            assert_eq!(
                store
                    .put_if_absent(&tenant, &key, value("value")?, Duration::ZERO)
                    .await,
                Err(StateError::InvalidArgument("ttl"))
            );
            assert_eq!(
                store
                    .put_if_absent(&tenant, &key, value("value")?, Duration::from_nanos(1),)
                    .await,
                Err(StateError::InvalidArgument("duration"))
            );
            assert!(store.get(&tenant, &key).await?.is_none());
            Ok(())
        })
    }
}
