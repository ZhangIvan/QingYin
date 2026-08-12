use qingyin_security::{Scope, SecurityContext};

use crate::{
    ActualUsage, AdmissionDecision, AdmissionError, AdmissionOperation, AdmissionPending,
    AdmissionRequest, AdmissionResult, AdmissionRuntimeAuthority, AdmissionStart, AdmissionStore,
    CommitResolution, GateVerdict, LifecycleMutation, ReclaimReport, ReleaseReason, RenewalId,
    ReservationIdentity, ReservationPolicy, ReservationRenewal, TerminalOutcome,
};

const MAX_RECLAIM_BATCH: usize = 1_000;

/// Fail-fast admission orchestrator with fixed gate order and recoverable outcomes.
pub struct AdmissionService<S> {
    store: S,
    policy: ReservationPolicy,
}

impl<S> AdmissionService<S>
where
    S: AdmissionStore,
{
    /// Creates a service from an explicit store and validated TTL policy.
    #[must_use]
    pub const fn new(store: S, policy: ReservationPolicy) -> Self {
        Self { store, policy }
    }

    /// Evaluates the six fixed gates without queueing an overloaded request.
    ///
    /// Every allowed gate may create a provisional reservation. Any later
    /// rejection/error is returned only after rollback succeeds. If rollback or
    /// publication cannot be proven, the exact generation is returned as
    /// [`AdmissionDecision::Pending`] for reconciliation. A dropped in-flight
    /// future remains discoverable through exact `begin` and bounded by TTL.
    pub async fn admit(&self, request: &AdmissionRequest) -> AdmissionResult<AdmissionDecision> {
        let start = self.store.begin(request, self.policy.ttl()).await?;
        let mut attempt = match start {
            AdmissionStart::ExistingLive(reservation) => {
                if !reservation.matches_request(request) {
                    return Err(AdmissionError::LifecycleUncertain);
                }
                return Ok(AdmissionDecision::Allowed(reservation));
            }
            AdmissionStart::Pending(pending) => {
                if !pending_matches_request(&pending, request) {
                    return Err(AdmissionError::LifecycleUncertain);
                }
                return Ok(AdmissionDecision::Pending(pending));
            }
            AdmissionStart::Attempt(attempt) => attempt,
        };
        let pending = attempt.pending().clone();
        if !pending_matches_request(&pending, request) {
            return Err(AdmissionError::LifecycleUncertain);
        }

        for gate in crate::AdmissionGate::ORDER {
            let verdict = match attempt.evaluate(gate).await {
                Ok(verdict) => verdict,
                Err(error) => {
                    return match attempt.rollback().await {
                        Ok(_) => Err(error),
                        Err(_) => Ok(AdmissionDecision::Pending(pending)),
                    };
                }
            };
            match verdict {
                GateVerdict::Allowed => {}
                GateVerdict::Rejected(rejection) => {
                    if rejection.gate() != gate {
                        return match attempt.rollback().await {
                            Ok(_) => {
                                Err(AdmissionError::InvariantViolation("gate_rejection_order"))
                            }
                            Err(_) => Ok(AdmissionDecision::Pending(pending)),
                        };
                    }
                    return match attempt.rollback().await {
                        Ok(_) => Ok(AdmissionDecision::Rejected(rejection)),
                        Err(_) => Ok(AdmissionDecision::Pending(pending)),
                    };
                }
            }
        }

        match attempt.commit().await {
            Ok(reservation)
                if reservation.identity() == pending.identity()
                    && reservation.matches_request(request) =>
            {
                Ok(AdmissionDecision::Allowed(reservation))
            }
            Ok(_) | Err(AdmissionError::CommitUncertain) => Ok(AdmissionDecision::Pending(pending)),
            Err(error) => Err(error),
        }
    }

    /// Reconciles one exact pending generation for its original actor and tenant.
    pub async fn reconcile(
        &self,
        context: &SecurityContext,
        pending: &AdmissionPending,
    ) -> AdmissionResult<CommitResolution> {
        authorize_original_actor(context, pending.identity(), Scope::SessionCreate)?;
        let resolution = self.store.reconcile(pending).await?;
        if resolution_matches_pending(&resolution, pending) {
            Ok(resolution)
        } else {
            Err(AdmissionError::LifecycleUncertain)
        }
    }

    /// Cancels one exact reservation as the original actor.
    ///
    /// The external surface fixes the outcome to `ClientCancelled`; arbitrary
    /// release reasons remain restricted to runtime authority.
    pub async fn cancel(
        &self,
        context: &SecurityContext,
        identity: &ReservationIdentity,
    ) -> AdmissionResult<LifecycleMutation> {
        authorize_original_actor(context, identity, Scope::SessionCancel)?;
        let mutation = self
            .store
            .release(identity, ReleaseReason::ClientCancelled)
            .await?;
        validate_terminal_mutation(
            mutation,
            identity,
            &TerminalOutcome::Released(ReleaseReason::ClientCancelled),
        )
    }

    /// Extends an active reservation using runtime authority and a renewal key.
    ///
    /// Repeating the same `renewal_id` never extends twice and returns the
    /// current active record unchanged. Only a different ID may extend it.
    pub async fn renew(
        &self,
        authority: &AdmissionRuntimeAuthority,
        identity: &ReservationIdentity,
        renewal_id: &RenewalId,
    ) -> AdmissionResult<ReservationRenewal> {
        authorize_runtime(authority, identity)?;
        let renewal = self
            .store
            .renew(identity, renewal_id, self.policy.ttl())
            .await?;
        if renewal.reservation().identity() == identity {
            Ok(renewal)
        } else {
            Err(AdmissionError::LifecycleUncertain)
        }
    }

    /// Idempotently releases projected capacity under runtime authority.
    ///
    /// `ReservationExpired` is store-owned and can only be produced by reclaim.
    pub async fn release(
        &self,
        authority: &AdmissionRuntimeAuthority,
        identity: &ReservationIdentity,
        reason: ReleaseReason,
    ) -> AdmissionResult<LifecycleMutation> {
        authorize_runtime(authority, identity)?;
        if reason == ReleaseReason::ReservationExpired {
            return Err(AdmissionError::InvalidArgument("release_reason"));
        }
        let mutation = self.store.release(identity, reason).await?;
        validate_terminal_mutation(mutation, identity, &TerminalOutcome::Released(reason))
    }

    /// Idempotently settles one exact observed usage value under runtime authority.
    pub async fn settle(
        &self,
        authority: &AdmissionRuntimeAuthority,
        identity: &ReservationIdentity,
        usage: ActualUsage,
    ) -> AdmissionResult<LifecycleMutation> {
        authorize_runtime(authority, identity)?;
        let mutation = self.store.settle(identity, usage).await?;
        validate_terminal_mutation(mutation, identity, &TerminalOutcome::Settled(usage))
    }

    /// Reclaims a bounded batch under explicit runtime authority.
    pub async fn reclaim_expired(
        &self,
        authority: &AdmissionRuntimeAuthority,
        limit: usize,
    ) -> AdmissionResult<ReclaimReport> {
        if limit == 0 || limit > MAX_RECLAIM_BATCH {
            return Err(AdmissionError::InvalidArgument("reclaim_limit"));
        }
        let report = self.store.reclaim_expired(authority.scope(), limit).await?;
        if report.total() > limit {
            Err(AdmissionError::LifecycleUncertain)
        } else {
            Ok(report)
        }
    }
}

fn pending_matches_request(pending: &AdmissionPending, request: &AdmissionRequest) -> bool {
    pending.identity().operation_key() == request.operation_key()
}

fn authorize_original_actor(
    context: &SecurityContext,
    identity: &ReservationIdentity,
    required: Scope,
) -> AdmissionResult<()> {
    context
        .authorize_resource(identity.scope(), required)
        .map_err(|_| AdmissionError::AuthorizationDenied)?;
    if identity.operation_key().operation() != AdmissionOperation::SessionCreate
        || !identity.actor().matches_context(context)
    {
        return Err(AdmissionError::AuthorizationDenied);
    }
    Ok(())
}

fn authorize_runtime(
    authority: &AdmissionRuntimeAuthority,
    identity: &ReservationIdentity,
) -> AdmissionResult<()> {
    if authority.scope() == identity.scope() {
        Ok(())
    } else {
        Err(AdmissionError::AuthorizationDenied)
    }
}

fn resolution_matches_pending(resolution: &CommitResolution, pending: &AdmissionPending) -> bool {
    match resolution {
        CommitResolution::Pending {
            pending: resolved, ..
        } => resolved.identity() == pending.identity(),
        CommitResolution::Committed(reservation) => reservation.identity() == pending.identity(),
        CommitResolution::Terminal(receipt) => {
            receipt.reservation().identity() == pending.identity()
        }
        CommitResolution::Compensated(resolved) | CommitResolution::Expired(resolved) => {
            resolved.identity() == pending.identity()
        }
    }
}

fn validate_terminal_mutation(
    mutation: LifecycleMutation,
    identity: &ReservationIdentity,
    expected: &TerminalOutcome,
) -> AdmissionResult<LifecycleMutation> {
    if mutation.receipt().reservation().identity() == identity
        && mutation.receipt().outcome() == expected
    {
        Ok(mutation)
    } else {
        Err(AdmissionError::LifecycleUncertain)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;
    use std::future::Future;
    use std::sync::{Arc, Mutex, MutexGuard};
    use std::task::{Context, Poll, Wake, Waker};
    use std::time::Duration;

    use async_trait::async_trait;
    use qingyin_security::{
        SecurityContext,
        test_support::{SecurityFixture, security_context},
    };
    use qingyin_state::{MonotonicTime, MutationOutcome, ReservationId, TenantScope};
    use qingyin_types::{ResourceId, SessionId, SessionMode, TaskKind};

    use super::*;
    use crate::{
        AdmissionAttempt, AdmissionDimensions, AdmissionGate, AdmissionRequestDigest,
        AdmissionReservation, AdmissionSnapshots, AttemptGeneration, BudgetAccountId,
        CapacitySnapshotId, CommitResolution, GateRejection, GatewayPoolId, PolicySnapshotId,
        ProjectedUsage, ProviderPoolId, RejectionReason, ReservationReceipt, RetryAfterMs,
        TerminalOutcome,
    };

    fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
        match mutex.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }

    struct NoopWake;

    impl Wake for NoopWake {
        fn wake(self: Arc<Self>) {}
    }

    fn block_on<F: Future>(future: F) -> F::Output {
        let waker = Waker::from(Arc::new(NoopWake));
        let mut context = Context::from_waker(&waker);
        let mut future = std::pin::pin!(future);
        loop {
            match future.as_mut().poll(&mut context) {
                Poll::Ready(output) => return output,
                Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    fn resource_id(value: &str) -> AdmissionResult<ResourceId> {
        ResourceId::new(value).ok_or(AdmissionError::InvalidArgument("test_resource_id"))
    }

    fn fixture_context(fixture: SecurityFixture) -> AdmissionResult<SecurityContext> {
        security_context(fixture)
            .map_err(|_| AdmissionError::InvalidArgument("test_security_fixture"))
    }

    fn runtime_authority(fixture: SecurityFixture) -> AdmissionResult<AdmissionRuntimeAuthority> {
        let context = fixture_context(fixture)?;
        AdmissionRuntimeAuthority::try_from_context(&context)
    }

    fn request(session: &str) -> AdmissionResult<AdmissionRequest> {
        request_with_fixture(session, SecurityFixture::SessionActorA)
    }

    fn request_with_fixture(
        session: &str,
        fixture: SecurityFixture,
    ) -> AdmissionResult<AdmissionRequest> {
        let session_id = SessionId::new(session.to_owned())
            .ok_or(AdmissionError::InvalidArgument("test_session_id"))?;
        AdmissionRequest::new(
            fixture_context(fixture)?,
            AdmissionRequestDigest::new([11; 32]),
            ReservationId::new(resource_id("rsv_test001")?),
            session_id,
            TaskKind::Asr,
            SessionMode::Streaming,
            AdmissionSnapshots::new(
                PolicySnapshotId::new(resource_id("pol_test001")?),
                CapacitySnapshotId::new(resource_id("cap_test001")?),
            ),
            AdmissionDimensions::new(
                GatewayPoolId::new(resource_id("gwp_test001")?),
                ProviderPoolId::new(resource_id("pvp_test001")?),
                BudgetAccountId::new(resource_id("bud_test001")?),
            ),
            ProjectedUsage::new(1, 1, 64, 2, 3)?,
        )
    }

    fn reservation(request: &AdmissionRequest) -> AdmissionResult<AdmissionReservation> {
        AdmissionReservation::from_admitted_request(
            request,
            AttemptGeneration::first(),
            MonotonicTime::from_millis(1_000),
            MonotonicTime::from_millis(31_000),
        )
    }

    struct FakeAttempt {
        pending: AdmissionPending,
        verdicts: VecDeque<AdmissionResult<GateVerdict>>,
        commit: Option<AdmissionResult<AdmissionReservation>>,
        rollback: AdmissionResult<MutationOutcome>,
        rolled_back: Arc<Mutex<usize>>,
    }

    #[async_trait]
    impl AdmissionAttempt for FakeAttempt {
        fn pending(&self) -> &AdmissionPending {
            &self.pending
        }

        async fn evaluate(&mut self, _gate: AdmissionGate) -> AdmissionResult<GateVerdict> {
            self.verdicts
                .pop_front()
                .unwrap_or(Ok(GateVerdict::Allowed))
        }

        async fn commit(mut self: Box<Self>) -> AdmissionResult<AdmissionReservation> {
            self.commit
                .take()
                .unwrap_or(Err(AdmissionError::AttemptFinalized))
        }

        async fn rollback(&mut self) -> AdmissionResult<MutationOutcome> {
            *lock(&self.rolled_back) += 1;
            self.rollback.clone()
        }
    }

    struct FakeStore {
        start: Mutex<Option<AdmissionResult<AdmissionStart>>>,
        begin_ttl: Mutex<Option<Duration>>,
        lifecycle_calls: Mutex<Vec<&'static str>>,
        reservation: Option<AdmissionReservation>,
    }

    impl FakeStore {
        fn new(start: AdmissionResult<AdmissionStart>) -> Self {
            Self {
                start: Mutex::new(Some(start)),
                begin_ttl: Mutex::new(None),
                lifecycle_calls: Mutex::new(Vec::new()),
                reservation: None,
            }
        }

        fn lifecycle(reservation: AdmissionReservation) -> Self {
            Self {
                start: Mutex::new(Some(Err(AdmissionError::NotFound))),
                begin_ttl: Mutex::new(None),
                lifecycle_calls: Mutex::new(Vec::new()),
                reservation: Some(reservation),
            }
        }
    }

    #[async_trait]
    impl AdmissionStore for FakeStore {
        async fn begin(
            &self,
            _request: &AdmissionRequest,
            ttl: Duration,
        ) -> AdmissionResult<AdmissionStart> {
            *lock(&self.begin_ttl) = Some(ttl);
            lock(&self.start)
                .take()
                .unwrap_or(Err(AdmissionError::Conflict))
        }

        async fn reconcile(&self, pending: &AdmissionPending) -> AdmissionResult<CommitResolution> {
            match self.reservation.as_ref() {
                Some(reservation) if reservation.identity() == pending.identity() => {
                    Ok(CommitResolution::Committed(reservation.clone()))
                }
                Some(_) => Err(AdmissionError::Conflict),
                None => Ok(CommitResolution::Compensated(pending.clone())),
            }
        }

        async fn renew(
            &self,
            _identity: &ReservationIdentity,
            _renewal_id: &RenewalId,
            ttl: Duration,
        ) -> AdmissionResult<ReservationRenewal> {
            lock(&self.lifecycle_calls).push("renew");
            let current = self.reservation.as_ref().ok_or(AdmissionError::NotFound)?;
            let expires_at = current
                .expires_at()
                .checked_add(ttl)
                .map_err(|_| AdmissionError::StoreUnavailable)?;
            Ok(ReservationRenewal::new(
                MutationOutcome::Applied,
                current.renewed_to(expires_at)?,
            ))
        }

        async fn release(
            &self,
            _identity: &ReservationIdentity,
            reason: ReleaseReason,
        ) -> AdmissionResult<LifecycleMutation> {
            lock(&self.lifecycle_calls).push("release");
            let current = self.reservation.as_ref().ok_or(AdmissionError::NotFound)?;
            Ok(LifecycleMutation::new(
                MutationOutcome::Applied,
                ReservationReceipt::new(
                    current.clone(),
                    TerminalOutcome::Released(reason),
                    current.created_at(),
                )?,
            ))
        }

        async fn settle(
            &self,
            _identity: &ReservationIdentity,
            usage: ActualUsage,
        ) -> AdmissionResult<LifecycleMutation> {
            lock(&self.lifecycle_calls).push("settle");
            let current = self.reservation.as_ref().ok_or(AdmissionError::NotFound)?;
            Ok(LifecycleMutation::new(
                MutationOutcome::Applied,
                ReservationReceipt::new(
                    current.clone(),
                    TerminalOutcome::Settled(usage),
                    current.created_at(),
                )?,
            ))
        }

        async fn reclaim_expired(
            &self,
            _scope: &TenantScope,
            _limit: usize,
        ) -> AdmissionResult<ReclaimReport> {
            Ok(ReclaimReport::default())
        }
    }

    #[test]
    fn commit_result_must_match_request_without_post_commit_rollback() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_match001")?;
            let other = request("ses_other001")?;
            let pending = reservation(&admitted)?.pending();
            let rolled_back = Arc::new(Mutex::new(0));
            let attempt = FakeAttempt {
                pending: pending.clone(),
                verdicts: VecDeque::new(),
                commit: Some(Ok(reservation(&other)?)),
                rollback: Ok(MutationOutcome::Applied),
                rolled_back: Arc::clone(&rolled_back),
            };
            let service = AdmissionService::new(
                FakeStore::new(Ok(AdmissionStart::Attempt(Box::new(attempt)))),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service.admit(&admitted).await,
                Ok(AdmissionDecision::Pending(pending))
            );
            assert_eq!(*lock(&rolled_back), 0);
            Ok(())
        })
    }

    #[test]
    fn commit_uncertain_returns_pending_then_reconciles_exact_commit() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_uncertain")?;
            let committed = reservation(&admitted)?;
            let pending = committed.pending();
            let original = fixture_context(SecurityFixture::SessionActorA)?;
            let rolled_back = Arc::new(Mutex::new(0));
            let attempt = FakeAttempt {
                pending: pending.clone(),
                verdicts: VecDeque::new(),
                commit: Some(Err(AdmissionError::CommitUncertain)),
                rollback: Ok(MutationOutcome::Applied),
                rolled_back: Arc::clone(&rolled_back),
            };
            let mut store = FakeStore::new(Ok(AdmissionStart::Attempt(Box::new(attempt))));
            store.reservation = Some(committed.clone());
            let service =
                AdmissionService::new(store, ReservationPolicy::new(Duration::from_secs(30))?);

            assert_eq!(
                service.admit(&admitted).await,
                Ok(AdmissionDecision::Pending(pending.clone()))
            );
            assert_eq!(*lock(&rolled_back), 0);
            assert_eq!(
                service.reconcile(&original, &pending).await,
                Ok(CommitResolution::Committed(committed))
            );
            Ok(())
        })
    }

    #[test]
    fn failed_commit_owns_compensation_and_preserves_error() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_commit01")?;
            let pending = reservation(&admitted)?.pending();
            let rolled_back = Arc::new(Mutex::new(0));
            let attempt = FakeAttempt {
                pending,
                verdicts: VecDeque::new(),
                commit: Some(Err(AdmissionError::StoreUnavailable)),
                rollback: Ok(MutationOutcome::Applied),
                rolled_back: Arc::clone(&rolled_back),
            };
            let service = AdmissionService::new(
                FakeStore::new(Ok(AdmissionStart::Attempt(Box::new(attempt)))),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service.admit(&admitted).await,
                Err(AdmissionError::StoreUnavailable)
            );
            assert_eq!(*lock(&rolled_back), 0);
            Ok(())
        })
    }

    #[test]
    fn rollback_failure_returns_reconcilable_pending() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_reject01")?;
            let rejection = GateRejection::new(
                RejectionReason::RequestRateExceeded,
                Some(RetryAfterMs::new(100)?),
            )?;
            let pending = reservation(&admitted)?.pending();
            let attempt = FakeAttempt {
                pending: pending.clone(),
                verdicts: VecDeque::from([Ok(GateVerdict::Rejected(rejection))]),
                commit: None,
                rollback: Err(AdmissionError::StoreUnavailable),
                rolled_back: Arc::new(Mutex::new(0)),
            };
            let service = AdmissionService::new(
                FakeStore::new(Ok(AdmissionStart::Attempt(Box::new(attempt)))),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service.admit(&admitted).await,
                Ok(AdmissionDecision::Pending(pending))
            );
            Ok(())
        })
    }

    #[test]
    fn runtime_authority_reaches_tenant_scoped_lifecycle_store() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_lifecycle")?;
            let reservation = reservation(&admitted)?;
            let identity = reservation.identity().clone();
            let authority = runtime_authority(SecurityFixture::RuntimeA)?;
            let renewal_id = RenewalId::new(resource_id("rnl_test001")?);
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );
            let usage = ActualUsage::new(16, 1, 2)?;

            assert!(
                service
                    .renew(&authority, &identity, &renewal_id)
                    .await
                    .is_ok()
            );
            assert!(
                service
                    .release(&authority, &identity, ReleaseReason::ConnectionFailed)
                    .await
                    .is_ok()
            );
            assert!(service.settle(&authority, &identity, usage).await.is_ok());
            assert_eq!(
                lock(&service.store.lifecycle_calls).as_slice(),
                ["renew", "release", "settle"]
            );
            Ok(())
        })
    }

    #[test]
    fn cancel_denies_missing_scope_before_store_access() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_no_scope")?;
            let reservation = reservation(&admitted)?;
            let identity = reservation.identity().clone();
            let unauthorized = fixture_context(SecurityFixture::SessionActorCreateOnlyA)?;
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service.cancel(&unauthorized, &identity).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert!(lock(&service.store.lifecycle_calls).is_empty());
            Ok(())
        })
    }

    #[test]
    fn cancel_denies_cross_tenant_before_store_access() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_cross_tenant")?;
            let reservation = reservation(&admitted)?;
            let identity = reservation.identity().clone();
            let other_tenant = fixture_context(SecurityFixture::OtherTenantActor)?;
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );
            assert_eq!(
                service.cancel(&other_tenant, &identity).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert!(lock(&service.store.lifecycle_calls).is_empty());
            Ok(())
        })
    }

    #[test]
    fn reconcile_and_cancel_require_the_exact_original_actor() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_reconcile")?;
            let reservation = reservation(&admitted)?;
            let pending = reservation.pending();
            let identity = reservation.identity().clone();
            let original = fixture_context(SecurityFixture::SessionActorA)?;
            let other_actor = fixture_context(SecurityFixture::SessionActorB)?;
            let reverified = fixture_context(SecurityFixture::SessionActorAReverified)?;
            let no_scopes = fixture_context(SecurityFixture::SessionActorNoScopesA)?;
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service.reconcile(&other_actor, &pending).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert_eq!(
                service.reconcile(&reverified, &pending).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert_eq!(
                service.reconcile(&no_scopes, &pending).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert_eq!(
                service.cancel(&other_actor, &identity).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert_eq!(
                service.cancel(&reverified, &identity).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert!(lock(&service.store.lifecycle_calls).is_empty());

            assert!(matches!(
                service.reconcile(&original, &pending).await?,
                CommitResolution::Committed(_)
            ));
            let cancelled = service.cancel(&original, &identity).await?;
            assert_eq!(
                cancelled.receipt().outcome(),
                &TerminalOutcome::Released(ReleaseReason::ClientCancelled)
            );
            assert_eq!(lock(&service.store.lifecycle_calls).as_slice(), ["release"]);
            Ok(())
        })
    }

    #[test]
    fn runtime_authority_denies_cross_tenant_before_store_access() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_runtime_scope")?;
            let reservation = reservation(&admitted)?;
            let identity = reservation.identity().clone();
            let authority = runtime_authority(SecurityFixture::RuntimeB)?;
            let renewal_id = RenewalId::new(resource_id("rnl_cross001")?);
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service.renew(&authority, &identity, &renewal_id).await,
                Err(AdmissionError::AuthorizationDenied)
            );
            assert!(lock(&service.store.lifecycle_calls).is_empty());
            Ok(())
        })
    }

    #[test]
    fn lifecycle_content_mismatch_is_uncertain_without_receipt() -> AdmissionResult<()> {
        block_on(async {
            let requested = request("ses_expected")?;
            let returned = request("ses_wrong001")?;
            let identity = reservation(&requested)?.identity().clone();
            let authority = runtime_authority(SecurityFixture::RuntimeA)?;
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation(&returned)?),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service
                    .release(&authority, &identity, ReleaseReason::ConnectionFailed)
                    .await,
                Err(AdmissionError::LifecycleUncertain)
            );
            Ok(())
        })
    }

    #[test]
    fn reservation_expiry_release_is_reclaim_only() -> AdmissionResult<()> {
        block_on(async {
            let admitted = request("ses_expiry001")?;
            let reservation = reservation(&admitted)?;
            let identity = reservation.identity().clone();
            let authority = runtime_authority(SecurityFixture::RuntimeA)?;
            let service = AdmissionService::new(
                FakeStore::lifecycle(reservation),
                ReservationPolicy::new(Duration::from_secs(30))?,
            );

            assert_eq!(
                service
                    .release(&authority, &identity, ReleaseReason::ReservationExpired)
                    .await,
                Err(AdmissionError::InvalidArgument("release_reason"))
            );
            assert!(lock(&service.store.lifecycle_calls).is_empty());
            Ok(())
        })
    }

    #[test]
    fn compensated_and_expired_resolution_require_exact_generation_identity() -> AdmissionResult<()>
    {
        let requested = reservation(&request("ses_resolve1")?)?.pending();
        let different = reservation(&request("ses_resolve2")?)?.pending();

        assert!(resolution_matches_pending(
            &CommitResolution::Compensated(requested.clone()),
            &requested
        ));
        assert!(resolution_matches_pending(
            &CommitResolution::Expired(requested.clone()),
            &requested
        ));
        assert!(!resolution_matches_pending(
            &CommitResolution::Compensated(different.clone()),
            &requested
        ));
        assert!(!resolution_matches_pending(
            &CommitResolution::Expired(different),
            &requested
        ));
        Ok(())
    }
}
