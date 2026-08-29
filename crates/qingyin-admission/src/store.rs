use std::time::Duration;

use async_trait::async_trait;
use qingyin_state::{MutationOutcome, TenantScope};

use crate::{
    ActualUsage, AdmissionGate, AdmissionPending, AdmissionRequest, AdmissionReservation,
    AdmissionResult, CommitResolution, GateVerdict, LifecycleMutation, ReclaimReport,
    ReleaseReason, RenewalId, ReservationIdentity, ReservationRenewal,
};

/// One isolated multi-gate reservation attempt.
///
/// Implementations reserve resources during `evaluate`, publish them during
/// `commit`, and must compensate every provisional mutation during `rollback`.
/// A dropped unfinished attempt remains reclaimable through its TTL.
#[async_trait]
pub trait AdmissionAttempt: Send {
    /// Returns the exact operation and generation handle before any async mutation.
    #[must_use]
    fn pending(&self) -> &AdmissionPending;

    /// Evaluates and provisionally reserves exactly one requested gate.
    ///
    /// A `RequestRate` claim is an attempt-local provisional debit: rollback
    /// returns it, while a successful commit consumes it permanently. Releasing,
    /// settling, or reclaiming a committed reservation never returns that debit.
    async fn evaluate(&mut self, gate: AdmissionGate) -> AdmissionResult<GateVerdict>;

    /// Consumes the attempt and atomically publishes the exact composite reservation.
    ///
    /// `Ok` is final and must contain the complete reservation for the request
    /// that opened this attempt. Any ordinary `Err` guarantees every provisional
    /// mutation was compensated and no committed reservation exists.
    /// [`crate::AdmissionError::CommitUncertain`] means the adapter cannot prove
    /// either publication or compensation; callers must reconcile through an
    /// exact [`AdmissionStore::reconcile`] query or expiry reclamation.
    async fn commit(self: Box<Self>) -> AdmissionResult<AdmissionReservation>;

    /// Idempotently compensates every provisional gate reservation.
    ///
    /// This is used only while the attempt remains provisional. Commit consumes
    /// the attempt and owns compensation for every error it returns.
    async fn rollback(&mut self) -> AdmissionResult<MutationOutcome>;
}

/// Result of opening a stable reservation identity.
#[allow(clippy::large_enum_variant)]
pub enum AdmissionStart {
    /// The same matching request has an unexpired active reservation.
    ExistingLive(AdmissionReservation),
    /// The exact operation already has an unresolved provisional generation.
    Pending(AdmissionPending),
    /// A previously unseen identity opened a new isolated attempt.
    Attempt(Box<dyn AdmissionAttempt>),
}

/// State boundary for admission attempts and committed reservation outcomes.
///
/// Implementations own the authoritative monotonic clock. They must isolate the
/// complete tenant scope and reservation ID, serialize conflicting terminal
/// transitions, and preserve the first release or settle outcome. Limits come
/// from immutable snapshots, never this trait.
///
/// This trait is a trusted infrastructure-adapter boundary. Raw lifecycle
/// methods are never transport entry points. [`crate::AdmissionService::cancel`]
/// verifies the exact original actor and tenant with `SessionCancel`; internal
/// renew, release, settle, and tenant-filtered reclaim require a service-account
/// [`crate::AdmissionRuntimeAuthority`] with `AdmissionManage`. Transports and
/// other untrusted callers must never invoke an adapter directly.
///
/// The durable state machine is `unseen -> provisional -> committed ->
/// released|settled|expired`, with `provisional -> compensated|expired`.
/// An exact retry of a provisional request returns [`AdmissionStart::Pending`],
/// including after cancellation of the future that opened or evaluated it. An
/// exact compensated request may open a checked next generation. Any content
/// mismatch and any terminal or expired operation-key reuse is a conflict.
/// Every mutation and reconciliation is generation-exact; a stale generation is
/// an ABA conflict and must never observe or mutate a later generation.
#[async_trait]
pub trait AdmissionStore: Send + Sync {
    /// Begins a new attempt or replays one matching live reservation.
    ///
    /// The store samples its clock atomically with state inspection, derives
    /// creation and expiry times from `ttl`, and returns them in the committed
    /// reservation. `ttl` has already been validated by [`crate::ReservationPolicy`].
    async fn begin(
        &self,
        request: &AdmissionRequest,
        ttl: Duration,
    ) -> AdmissionResult<AdmissionStart>;

    /// Resolves the exact provisional generation without starting a new attempt.
    ///
    /// The result must describe only `pending.identity()`. A later generation is
    /// never substituted for a stale handle. Compensated and expired results
    /// carry that same handle for post-validation. Committed terminal state
    /// remains queryable as its first immutable receipt.
    async fn reconcile(&self, pending: &AdmissionPending) -> AdmissionResult<CommitResolution>;

    /// Extends one matching active reservation using authoritative store time.
    ///
    /// The store must reject missing, expired, or terminal reservations and must
    /// derive the new expiry from its own current time plus the validated `ttl`.
    /// `renewal_id` is an idempotency identity: repeating the same ID never
    /// extends twice and returns the current active record with
    /// [`MutationOutcome::Unchanged`]. A later distinct ID may therefore be
    /// observable in that response. Only a new ID may extend the expiry.
    async fn renew(
        &self,
        identity: &ReservationIdentity,
        renewal_id: &RenewalId,
        ttl: Duration,
    ) -> AdmissionResult<ReservationRenewal>;

    /// Releases active capacity once using authoritative store time.
    ///
    /// Repeating the same reason is unchanged; a different terminal outcome is
    /// a conflict. A committed `RequestRate` debit is never returned.
    async fn release(
        &self,
        identity: &ReservationIdentity,
        reason: ReleaseReason,
    ) -> AdmissionResult<LifecycleMutation>;

    /// Settles observed usage once using authoritative store time.
    ///
    /// Repeating identical usage is unchanged; a different terminal outcome is
    /// a conflict. A committed `RequestRate` debit is never returned.
    async fn settle(
        &self,
        identity: &ReservationIdentity,
        usage: ActualUsage,
    ) -> AdmissionResult<LifecycleMutation>;

    /// Reclaims a bounded batch using authoritative store time.
    ///
    /// Only records in the exact `scope` may be inspected or mutated. Each
    /// expired attempt or reservation is reclaimed exactly once. Reclaiming a
    /// committed reservation never returns its `RequestRate` debit.
    /// Runtime integration must invoke this bounded sweep within its declared
    /// reclaimer SLO. Until reconciliation or reclaim runs, an expired record
    /// remains fail-closed and may continue to hold capacity; `begin` must never
    /// reuse its operation identity or silently reclaim it.
    async fn reclaim_expired(
        &self,
        scope: &TenantScope,
        limit: usize,
    ) -> AdmissionResult<ReclaimReport>;
}
