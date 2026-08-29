use std::fmt;
use std::num::NonZeroU64;
use std::time::Duration;

use qingyin_security::{
    CredentialId, PrincipalDigest, PrincipalId, PrincipalKind, Scope, SecurityContext,
};
use qingyin_state::{MonotonicTime, MutationOutcome, ReservationId, TenantScope};
use qingyin_types::{ResourceId, SessionId, SessionMode, TaskKind};

use crate::{AdmissionError, AdmissionResult};

const MAX_USAGE_UNITS: u64 = 1_000_000_000_000_000;
const MAX_RETRY_AFTER_MS: u64 = 24 * 60 * 60 * 1_000;
const MIN_RESERVATION_TTL: Duration = Duration::from_secs(1);
const MAX_RESERVATION_TTL: Duration = Duration::from_secs(15 * 60);

macro_rules! admission_resource_id {
    ($(#[$metadata:meta])* $name:ident) => {
        $(#[$metadata])*
        #[derive(Clone, Debug, Eq, Hash, PartialEq)]
        pub struct $name(ResourceId);

        impl $name {
            /// Creates a semantic admission ID from a validated resource ID.
            #[must_use]
            pub const fn new(value: ResourceId) -> Self {
                Self(value)
            }

            /// Returns the underlying validated resource ID.
            #[must_use]
            pub const fn as_resource_id(&self) -> &ResourceId {
                &self.0
            }
        }
    };
}

admission_resource_id!(
    /// Immutable policy snapshot selected before admission.
    PolicySnapshotId
);
admission_resource_id!(
    /// Immutable measured capacity snapshot selected before admission.
    CapacitySnapshotId
);
admission_resource_id!(
    /// Stable low-level Gateway capacity pool dimension.
    GatewayPoolId
);
admission_resource_id!(
    /// Stable Provider/account/model/region capacity pool dimension.
    ProviderPoolId
);
admission_resource_id!(
    /// Stable project or tenant budget account dimension.
    BudgetAccountId
);
admission_resource_id!(
    /// Stable idempotency identity for one renewal request.
    RenewalId
);

/// Immutable snapshots used for the complete admission decision.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct AdmissionSnapshots {
    policy: PolicySnapshotId,
    capacity: CapacitySnapshotId,
}

impl AdmissionSnapshots {
    /// Creates a pair that must remain unchanged for the full gate sequence.
    #[must_use]
    pub const fn new(policy: PolicySnapshotId, capacity: CapacitySnapshotId) -> Self {
        Self { policy, capacity }
    }

    /// Returns the policy snapshot identity.
    #[must_use]
    pub const fn policy(&self) -> &PolicySnapshotId {
        &self.policy
    }

    /// Returns the capacity snapshot identity.
    #[must_use]
    pub const fn capacity(&self) -> &CapacitySnapshotId {
        &self.capacity
    }
}

/// Capacity and budget pools resolved before gate evaluation.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct AdmissionDimensions {
    gateway_pool: GatewayPoolId,
    provider_pool: ProviderPoolId,
    budget_account: BudgetAccountId,
}

impl AdmissionDimensions {
    /// Creates immutable dimensions from trusted routing and policy resolution.
    #[must_use]
    pub const fn new(
        gateway_pool: GatewayPoolId,
        provider_pool: ProviderPoolId,
        budget_account: BudgetAccountId,
    ) -> Self {
        Self {
            gateway_pool,
            provider_pool,
            budget_account,
        }
    }

    /// Returns the Gateway capacity pool.
    #[must_use]
    pub const fn gateway_pool(&self) -> &GatewayPoolId {
        &self.gateway_pool
    }

    /// Returns the Provider capacity pool.
    #[must_use]
    pub const fn provider_pool(&self) -> &ProviderPoolId {
        &self.provider_pool
    }

    /// Returns the budget account.
    #[must_use]
    pub const fn budget_account(&self) -> &BudgetAccountId {
        &self.budget_account
    }
}

/// Bounded projected usage reserved before a session is created.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProjectedUsage {
    request_units: NonZeroU64,
    active_sessions: NonZeroU64,
    gateway_bytes: u64,
    provider_units: u64,
    budget_microunits: u64,
}

impl ProjectedUsage {
    /// Creates a bounded projection. Request and session claims must be nonzero.
    pub fn new(
        request_units: u64,
        active_sessions: u64,
        gateway_bytes: u64,
        provider_units: u64,
        budget_microunits: u64,
    ) -> AdmissionResult<Self> {
        let request_units = NonZeroU64::new(request_units)
            .ok_or(AdmissionError::InvalidArgument("request_units"))?;
        let active_sessions = NonZeroU64::new(active_sessions)
            .ok_or(AdmissionError::InvalidArgument("active_sessions"))?;
        if [
            request_units.get(),
            active_sessions.get(),
            gateway_bytes,
            provider_units,
            budget_microunits,
        ]
        .into_iter()
        .any(|value| value > MAX_USAGE_UNITS)
        {
            return Err(AdmissionError::InvalidArgument("projected_usage"));
        }
        Ok(Self {
            request_units,
            active_sessions,
            gateway_bytes,
            provider_units,
            budget_microunits,
        })
    }

    /// Returns request-rate units.
    #[must_use]
    pub const fn request_units(self) -> NonZeroU64 {
        self.request_units
    }

    /// Returns active-session units.
    #[must_use]
    pub const fn active_sessions(self) -> NonZeroU64 {
        self.active_sessions
    }

    /// Returns projected Gateway bytes.
    #[must_use]
    pub const fn gateway_bytes(self) -> u64 {
        self.gateway_bytes
    }

    /// Returns Provider capacity units.
    #[must_use]
    pub const fn provider_units(self) -> u64 {
        self.provider_units
    }

    /// Returns projected budget microunits.
    #[must_use]
    pub const fn budget_microunits(self) -> u64 {
        self.budget_microunits
    }

    /// Returns the quantity provisionally claimed by one gate.
    #[must_use]
    pub const fn quantity_for(self, gate: AdmissionGate) -> u64 {
        match gate {
            AdmissionGate::RequestRate => self.request_units.get(),
            AdmissionGate::ActiveSessions => self.active_sessions.get(),
            AdmissionGate::GatewayBytes => self.gateway_bytes,
            AdmissionGate::ProviderCapacity => self.provider_units,
            AdmissionGate::Policy => 0,
            AdmissionGate::Budget => self.budget_microunits,
        }
    }
}

/// Bounded observed usage supplied to an exactly-once settlement.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ActualUsage {
    gateway_bytes: u64,
    provider_units: u64,
    budget_microunits: u64,
}

impl ActualUsage {
    /// Creates observed usage without assuming it is below the projection.
    pub fn new(
        gateway_bytes: u64,
        provider_units: u64,
        budget_microunits: u64,
    ) -> AdmissionResult<Self> {
        if [gateway_bytes, provider_units, budget_microunits]
            .into_iter()
            .any(|value| value > MAX_USAGE_UNITS)
        {
            return Err(AdmissionError::InvalidArgument("actual_usage"));
        }
        Ok(Self {
            gateway_bytes,
            provider_units,
            budget_microunits,
        })
    }

    /// Returns observed Gateway bytes.
    #[must_use]
    pub const fn gateway_bytes(self) -> u64 {
        self.gateway_bytes
    }

    /// Returns observed Provider units.
    #[must_use]
    pub const fn provider_units(self) -> u64 {
        self.provider_units
    }

    /// Returns observed billable microunits.
    #[must_use]
    pub const fn budget_microunits(self) -> u64 {
        self.budget_microunits
    }
}

/// Canonical digest of the complete externally supplied admission request.
///
/// M1-07 owns canonicalization and HTTP idempotency-key parsing. This type only
/// accepts the fixed-width digest output and never renders its bytes in `Debug`.
#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct AdmissionRequestDigest([u8; 32]);

impl AdmissionRequestDigest {
    /// Creates a digest from the canonicalizer's exact 32-byte output.
    #[must_use]
    pub const fn new(value: [u8; 32]) -> Self {
        Self(value)
    }
}

impl fmt::Debug for AdmissionRequestDigest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:admission-request-digest>")
    }
}

/// Exact authenticated actor bound to an admission operation.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct AdmissionActorBinding {
    principal_id: PrincipalId,
    credential_id: Option<CredentialId>,
    principal_digest: PrincipalDigest,
}

impl AdmissionActorBinding {
    pub(crate) fn from_context(context: &SecurityContext) -> Self {
        Self {
            principal_id: context.principal().principal_id().clone(),
            credential_id: context.principal().credential_id().cloned(),
            principal_digest: context.principal().digest(),
        }
    }

    /// Returns whether all verified actor fields match exactly.
    #[must_use]
    pub fn matches_context(&self, context: &SecurityContext) -> bool {
        self.principal_id == *context.principal().principal_id()
            && self.credential_id.as_ref() == context.principal().credential_id()
            && self.principal_digest == context.principal().digest()
    }

    /// Returns the verified principal identity.
    #[must_use]
    pub const fn principal_id(&self) -> &PrincipalId {
        &self.principal_id
    }

    /// Returns the verified credential identity when one authenticated the actor.
    #[must_use]
    pub const fn credential_id(&self) -> Option<&CredentialId> {
        self.credential_id.as_ref()
    }

    /// Returns the irreversible verifier-produced principal digest.
    #[must_use]
    pub const fn principal_digest(&self) -> PrincipalDigest {
        self.principal_digest
    }
}

impl fmt::Debug for AdmissionActorBinding {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionActorBinding(<redacted>)")
    }
}

/// Closed admission operation namespace used in idempotency keys.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum AdmissionOperation {
    /// Create one session reservation.
    SessionCreate,
}

/// Complete immutable idempotency key for one authenticated admission request.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct AdmissionOperationKey {
    scope: TenantScope,
    actor: AdmissionActorBinding,
    operation: AdmissionOperation,
    reservation_id: ReservationId,
    request_digest: AdmissionRequestDigest,
    session_id: SessionId,
}

impl AdmissionOperationKey {
    fn from_context(
        context: &SecurityContext,
        operation: AdmissionOperation,
        reservation_id: ReservationId,
        request_digest: AdmissionRequestDigest,
        session_id: SessionId,
    ) -> Self {
        Self {
            scope: context.principal().tenant_scope().clone(),
            actor: AdmissionActorBinding::from_context(context),
            operation,
            reservation_id,
            request_digest,
            session_id,
        }
    }

    /// Returns the trusted tenant ownership chain.
    #[must_use]
    pub const fn scope(&self) -> &TenantScope {
        &self.scope
    }

    /// Returns the exact authenticated actor binding.
    #[must_use]
    pub const fn actor(&self) -> &AdmissionActorBinding {
        &self.actor
    }

    /// Returns the closed operation kind.
    #[must_use]
    pub const fn operation(&self) -> AdmissionOperation {
        self.operation
    }

    /// Returns the stable reservation identifier.
    #[must_use]
    pub const fn reservation_id(&self) -> &ReservationId {
        &self.reservation_id
    }

    /// Returns the canonical complete-request digest.
    #[must_use]
    pub const fn request_digest(&self) -> AdmissionRequestDigest {
        self.request_digest
    }

    /// Returns the target session identifier.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        &self.session_id
    }
}

impl fmt::Debug for AdmissionOperationKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionOperationKey(<redacted>)")
    }
}

/// Nonzero generation that prevents stale provisional ABA operations.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AttemptGeneration(NonZeroU64);

impl AttemptGeneration {
    /// Creates a nonzero generation persisted by a trusted store adapter.
    pub fn new(value: u64) -> AdmissionResult<Self> {
        NonZeroU64::new(value)
            .map(Self)
            .ok_or(AdmissionError::InvalidArgument("attempt_generation"))
    }

    /// Returns the initial generation for a previously unseen operation key.
    #[must_use]
    pub const fn first() -> Self {
        Self(NonZeroU64::MIN)
    }

    /// Returns the next generation, rejecting overflow without wrapping.
    pub fn checked_next(self) -> AdmissionResult<Self> {
        self.0
            .checked_add(1)
            .map(Self)
            .ok_or(AdmissionError::Conflict)
    }

    /// Returns the nonzero persisted value.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

/// Service-account authority for trusted lifecycle and expiry workers.
#[derive(Clone, Eq, PartialEq)]
pub struct AdmissionRuntimeAuthority {
    scope: TenantScope,
    actor: AdmissionActorBinding,
}

impl AdmissionRuntimeAuthority {
    /// Creates a tenant-bound authority only for an explicitly scoped service account.
    pub fn try_from_context(context: &SecurityContext) -> AdmissionResult<Self> {
        if context.principal().kind() != PrincipalKind::ServiceAccount {
            return Err(AdmissionError::AuthorizationDenied);
        }
        context
            .require_scope(Scope::AdmissionManage)
            .map_err(|_| AdmissionError::AuthorizationDenied)?;
        Ok(Self {
            scope: context.principal().tenant_scope().clone(),
            actor: AdmissionActorBinding::from_context(context),
        })
    }

    /// Returns the tenant boundary this runtime worker may mutate.
    #[must_use]
    pub const fn scope(&self) -> &TenantScope {
        &self.scope
    }

    /// Returns the verified service-account actor binding.
    #[must_use]
    pub const fn actor(&self) -> &AdmissionActorBinding {
        &self.actor
    }
}

impl fmt::Debug for AdmissionRuntimeAuthority {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionRuntimeAuthority(<redacted>)")
    }
}

/// Verified and fully resolved input to the admission boundary.
#[derive(Clone, Eq, PartialEq)]
pub struct AdmissionRequest {
    operation_key: AdmissionOperationKey,
    task: TaskKind,
    mode: SessionMode,
    snapshots: AdmissionSnapshots,
    dimensions: AdmissionDimensions,
    projected_usage: ProjectedUsage,
}

impl AdmissionRequest {
    /// Creates a request using only the tenant ownership in a verified context.
    ///
    /// No request DTO field can supply or replace organization, workspace,
    /// project, or environment ownership. `SessionCreate` is always required.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        context: SecurityContext,
        request_digest: AdmissionRequestDigest,
        reservation_id: ReservationId,
        session_id: SessionId,
        task: TaskKind,
        mode: SessionMode,
        snapshots: AdmissionSnapshots,
        dimensions: AdmissionDimensions,
        projected_usage: ProjectedUsage,
    ) -> AdmissionResult<Self> {
        context
            .require_scope(Scope::SessionCreate)
            .map_err(|_| AdmissionError::AuthorizationDenied)?;
        let operation_key = AdmissionOperationKey::from_context(
            &context,
            AdmissionOperation::SessionCreate,
            reservation_id,
            request_digest,
            session_id,
        );
        Ok(Self {
            operation_key,
            task,
            mode,
            snapshots,
            dimensions,
            projected_usage,
        })
    }

    /// Returns the complete immutable operation key.
    #[must_use]
    pub const fn operation_key(&self) -> &AdmissionOperationKey {
        &self.operation_key
    }

    /// Returns the immutable tenant chain from the verified principal.
    #[must_use]
    pub const fn tenant_scope(&self) -> &TenantScope {
        self.operation_key.scope()
    }

    /// Returns the complete verified actor binding.
    #[must_use]
    pub const fn actor(&self) -> &AdmissionActorBinding {
        self.operation_key.actor()
    }

    /// Returns the verified principal identity used by rate dimensions.
    #[must_use]
    pub const fn principal_id(&self) -> &PrincipalId {
        self.operation_key.actor().principal_id()
    }

    /// Returns the irreversible principal binding digest.
    #[must_use]
    pub const fn principal_digest(&self) -> PrincipalDigest {
        self.operation_key.actor().principal_digest()
    }

    /// Returns the stable idempotency and lifecycle identity.
    #[must_use]
    pub const fn reservation_id(&self) -> &ReservationId {
        self.operation_key.reservation_id()
    }

    /// Returns the canonical complete-request digest.
    #[must_use]
    pub const fn request_digest(&self) -> AdmissionRequestDigest {
        self.operation_key.request_digest()
    }

    /// Returns the target session identity.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        self.operation_key.session_id()
    }

    /// Returns the task family.
    #[must_use]
    pub const fn task(&self) -> TaskKind {
        self.task
    }

    /// Returns the execution mode.
    #[must_use]
    pub const fn mode(&self) -> SessionMode {
        self.mode
    }

    /// Returns the immutable policy/capacity snapshots.
    #[must_use]
    pub const fn snapshots(&self) -> &AdmissionSnapshots {
        &self.snapshots
    }

    /// Returns the pre-resolved resource dimensions.
    #[must_use]
    pub const fn dimensions(&self) -> &AdmissionDimensions {
        &self.dimensions
    }

    /// Returns the bounded projected usage.
    #[must_use]
    pub const fn projected_usage(&self) -> ProjectedUsage {
        self.projected_usage
    }
}

impl fmt::Debug for AdmissionRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionRequest(<redacted>)")
    }
}

/// Fixed fail-fast gate order. Variants are intentionally low cardinality.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum AdmissionGate {
    /// Principal/project request-rate budget.
    RequestRate,
    /// Active session permit.
    ActiveSessions,
    /// Gateway memory/bandwidth byte budget.
    GatewayBytes,
    /// Selected Provider pool capacity.
    ProviderCapacity,
    /// Immutable policy decision.
    Policy,
    /// Project/tenant monetary budget.
    Budget,
}

impl AdmissionGate {
    /// Canonical order used by every admission attempt.
    pub const ORDER: [Self; 6] = [
        Self::RequestRate,
        Self::ActiveSessions,
        Self::GatewayBytes,
        Self::ProviderCapacity,
        Self::Policy,
        Self::Budget,
    ];

    /// Returns the stable low-cardinality rejection scope.
    #[must_use]
    pub const fn scope(self) -> GateScope {
        match self {
            Self::RequestRate => GateScope::Principal,
            Self::ActiveSessions => GateScope::Project,
            Self::GatewayBytes => GateScope::Gateway,
            Self::ProviderCapacity => GateScope::Provider,
            Self::Policy => GateScope::Policy,
            Self::Budget => GateScope::Budget,
        }
    }
}

/// Stable scope category suitable for errors and metric labels.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum GateScope {
    /// Verified principal-scoped capacity.
    Principal,
    /// Trusted project-scoped capacity.
    Project,
    /// Gateway-pool capacity.
    Gateway,
    /// Provider-pool capacity.
    Provider,
    /// Immutable policy evaluation.
    Policy,
    /// Tenant budget account.
    Budget,
}

/// Stable canonical reason tied to exactly one gate.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum RejectionReason {
    /// Principal or project request-rate allowance was exhausted.
    RequestRateExceeded,
    /// Project active-session limit was reached.
    ActiveSessionLimit,
    /// Gateway byte budget was exhausted.
    GatewayByteBudgetExhausted,
    /// Selected provider pool lacked available capacity.
    ProviderCapacityExhausted,
    /// The immutable policy snapshot denied the request.
    PolicyDenied,
    /// The budget account could not cover projected usage.
    BudgetExceeded,
}

impl RejectionReason {
    /// Returns the only gate allowed to emit this reason.
    #[must_use]
    pub const fn gate(self) -> AdmissionGate {
        match self {
            Self::RequestRateExceeded => AdmissionGate::RequestRate,
            Self::ActiveSessionLimit => AdmissionGate::ActiveSessions,
            Self::GatewayByteBudgetExhausted => AdmissionGate::GatewayBytes,
            Self::ProviderCapacityExhausted => AdmissionGate::ProviderCapacity,
            Self::PolicyDenied => AdmissionGate::Policy,
            Self::BudgetExceeded => AdmissionGate::Budget,
        }
    }

    /// Returns whether a bounded retry-after is mandatory.
    #[must_use]
    pub const fn is_retryable(self) -> bool {
        matches!(
            self,
            Self::RequestRateExceeded
                | Self::ActiveSessionLimit
                | Self::GatewayByteBudgetExhausted
                | Self::ProviderCapacityExhausted
        )
    }
}

/// Bounded retry delay in milliseconds.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct RetryAfterMs(u64);

impl RetryAfterMs {
    /// Creates a positive delay no greater than 24 hours.
    pub fn new(value: u64) -> AdmissionResult<Self> {
        if value == 0 || value > MAX_RETRY_AFTER_MS {
            return Err(AdmissionError::InvalidArgument("retry_after_ms"));
        }
        Ok(Self(value))
    }

    /// Returns the canonical millisecond delay.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Canonical fail-fast rejection with validated retry semantics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GateRejection {
    gate: AdmissionGate,
    reason: RejectionReason,
    scope: GateScope,
    retry_after_ms: Option<RetryAfterMs>,
}

impl GateRejection {
    /// Creates a rejection and rejects inconsistent retry metadata.
    pub fn new(
        reason: RejectionReason,
        retry_after_ms: Option<RetryAfterMs>,
    ) -> AdmissionResult<Self> {
        if reason.is_retryable() != retry_after_ms.is_some() {
            return Err(AdmissionError::InvalidArgument("retry_after_ms"));
        }
        let gate = reason.gate();
        Ok(Self {
            gate,
            reason,
            scope: gate.scope(),
            retry_after_ms,
        })
    }

    /// Returns the gate that rejected the request.
    #[must_use]
    pub const fn gate(self) -> AdmissionGate {
        self.gate
    }

    /// Returns the stable rejection reason.
    #[must_use]
    pub const fn reason(self) -> RejectionReason {
        self.reason
    }

    /// Returns the stable resource scope category.
    #[must_use]
    pub const fn scope(self) -> GateScope {
        self.scope
    }

    /// Returns the bounded retry delay when the reason is retryable.
    #[must_use]
    pub const fn retry_after_ms(self) -> Option<RetryAfterMs> {
        self.retry_after_ms
    }
}

/// Result of one gate evaluation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GateVerdict {
    /// The gate provisionally allowed and reserved its requested claim.
    Allowed,
    /// The gate rejected the request with canonical retry metadata.
    Rejected(GateRejection),
}

/// Bounded lifetime passed to the store for provisional and committed reservations.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReservationPolicy {
    ttl: Duration,
}

impl ReservationPolicy {
    /// Creates a whole-millisecond TTL from one second through fifteen minutes.
    pub fn new(ttl: Duration) -> AdmissionResult<Self> {
        if !(MIN_RESERVATION_TTL..=MAX_RESERVATION_TTL).contains(&ttl)
            || ttl.subsec_nanos() % 1_000_000 != 0
        {
            return Err(AdmissionError::InvalidArgument("reservation_ttl"));
        }
        Ok(Self { ttl })
    }

    /// Returns the validated reservation lifetime.
    #[must_use]
    pub const fn ttl(self) -> Duration {
        self.ttl
    }
}

/// Complete operation and generation identity persisted by a trusted store.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct ReservationIdentity {
    operation_key: AdmissionOperationKey,
    generation: AttemptGeneration,
}

impl ReservationIdentity {
    /// Creates a generation-bound identity for a trusted store adapter.
    ///
    /// This constructor is public so infrastructure adapters can restore durable
    /// state. Possession of a value is never authorization: service boundaries
    /// independently verify tenant, actor, operation, and generation.
    #[must_use]
    pub const fn from_operation_key(
        operation_key: AdmissionOperationKey,
        generation: AttemptGeneration,
    ) -> Self {
        Self {
            operation_key,
            generation,
        }
    }

    /// Returns the immutable authenticated operation key.
    #[must_use]
    pub const fn operation_key(&self) -> &AdmissionOperationKey {
        &self.operation_key
    }

    /// Returns the complete trusted tenant scope.
    #[must_use]
    pub const fn scope(&self) -> &TenantScope {
        self.operation_key.scope()
    }

    /// Returns the stable reservation identifier.
    #[must_use]
    pub const fn reservation_id(&self) -> &ReservationId {
        self.operation_key.reservation_id()
    }

    /// Returns the exact authenticated actor bound at admission.
    #[must_use]
    pub const fn actor(&self) -> &AdmissionActorBinding {
        self.operation_key.actor()
    }

    /// Returns the canonical complete-request digest.
    #[must_use]
    pub const fn request_digest(&self) -> AdmissionRequestDigest {
        self.operation_key.request_digest()
    }

    /// Returns the bound target session identity.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        self.operation_key.session_id()
    }

    /// Returns the nonzero attempt generation used for ABA protection.
    #[must_use]
    pub const fn generation(&self) -> AttemptGeneration {
        self.generation
    }
}

impl fmt::Debug for ReservationIdentity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ReservationIdentity(<redacted>)")
    }
}

/// Reconciliation handle for an unresolved provisional commit.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct AdmissionPending {
    identity: ReservationIdentity,
}

impl AdmissionPending {
    /// Creates a pending handle from a store-issued complete identity.
    #[must_use]
    pub const fn new(identity: ReservationIdentity) -> Self {
        Self { identity }
    }

    /// Returns the exact operation and generation identity to reconcile.
    #[must_use]
    pub const fn identity(&self) -> &ReservationIdentity {
        &self.identity
    }
}

impl fmt::Debug for AdmissionPending {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionPending(<redacted>)")
    }
}

/// Public reservation lifecycle states.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationLifecycle {
    /// Capacity remains actively reserved.
    Reserved,
    /// Projected capacity was returned without settlement.
    Released,
    /// Observed usage was settled exactly once.
    Settled,
}

/// Committed composite reservation returned after all gates allow.
#[derive(Clone, Eq, PartialEq)]
pub struct AdmissionReservation {
    identity: ReservationIdentity,
    task: TaskKind,
    mode: SessionMode,
    snapshots: AdmissionSnapshots,
    dimensions: AdmissionDimensions,
    projected_usage: ProjectedUsage,
    created_at: MonotonicTime,
    expires_at: MonotonicTime,
}

impl AdmissionReservation {
    /// Builds a committed record after every gate has allowed.
    pub fn from_admitted_request(
        request: &AdmissionRequest,
        generation: AttemptGeneration,
        created_at: MonotonicTime,
        expires_at: MonotonicTime,
    ) -> AdmissionResult<Self> {
        if expires_at <= created_at {
            return Err(AdmissionError::InvalidArgument("reservation_expiry"));
        }
        Ok(Self {
            identity: ReservationIdentity::from_operation_key(
                request.operation_key().clone(),
                generation,
            ),
            task: request.task(),
            mode: request.mode(),
            snapshots: request.snapshots().clone(),
            dimensions: request.dimensions().clone(),
            projected_usage: request.projected_usage(),
            created_at,
            expires_at,
        })
    }

    /// Verifies an idempotent result against the complete original request.
    #[must_use]
    pub fn matches_request(&self, request: &AdmissionRequest) -> bool {
        self.identity.operation_key == *request.operation_key()
            && self.task == request.task()
            && self.mode == request.mode()
            && self.snapshots == *request.snapshots()
            && self.dimensions == *request.dimensions()
            && self.projected_usage == request.projected_usage()
    }

    /// Returns a copy extended to a strictly later authoritative expiry.
    ///
    /// Store adapters use this only after proving that the reservation is still
    /// active under the store's own clock. Creation time and request bindings
    /// remain unchanged.
    pub fn renewed_to(&self, expires_at: MonotonicTime) -> AdmissionResult<Self> {
        if expires_at <= self.expires_at {
            return Err(AdmissionError::InvalidArgument("renewed_expiry"));
        }
        let mut renewed = self.clone();
        renewed.expires_at = expires_at;
        Ok(renewed)
    }

    /// Returns the complete tenant-scoped reservation identity.
    #[must_use]
    pub const fn identity(&self) -> &ReservationIdentity {
        &self.identity
    }

    /// Returns a reconciliation handle for this same generation.
    #[must_use]
    pub fn pending(&self) -> AdmissionPending {
        AdmissionPending::new(self.identity.clone())
    }

    /// Returns the session bound to this reservation.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        self.identity.session_id()
    }

    /// Returns the exact authenticated actor bound at admission.
    #[must_use]
    pub const fn actor(&self) -> &AdmissionActorBinding {
        self.identity.actor()
    }

    /// Returns the irreversible principal binding digest.
    #[must_use]
    pub const fn principal_digest(&self) -> PrincipalDigest {
        self.identity.actor().principal_digest()
    }

    /// Returns the admitted task family.
    #[must_use]
    pub const fn task(&self) -> TaskKind {
        self.task
    }

    /// Returns the admitted execution mode.
    #[must_use]
    pub const fn mode(&self) -> SessionMode {
        self.mode
    }

    /// Returns the immutable snapshots used for admission.
    #[must_use]
    pub const fn snapshots(&self) -> &AdmissionSnapshots {
        &self.snapshots
    }

    /// Returns the reserved capacity and budget dimensions.
    #[must_use]
    pub const fn dimensions(&self) -> &AdmissionDimensions {
        &self.dimensions
    }

    /// Returns the projected usage reserved at admission.
    #[must_use]
    pub const fn projected_usage(&self) -> ProjectedUsage {
        self.projected_usage
    }

    /// Returns the authoritative store creation time.
    #[must_use]
    pub const fn created_at(&self) -> MonotonicTime {
        self.created_at
    }

    /// Returns the authoritative current expiry time.
    #[must_use]
    pub const fn expires_at(&self) -> MonotonicTime {
        self.expires_at
    }

    /// Returns the active lifecycle represented by this non-terminal record.
    #[must_use]
    pub const fn lifecycle(&self) -> ReservationLifecycle {
        ReservationLifecycle::Reserved
    }
}

impl fmt::Debug for AdmissionReservation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionReservation(<redacted>)")
    }
}

/// Result of renewing one active reservation with authoritative store time.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationRenewal {
    mutation: MutationOutcome,
    reservation: AdmissionReservation,
}

impl ReservationRenewal {
    /// Creates a renewal result from the store's authoritative updated record.
    ///
    /// `Applied` means the expiry moved later. `Unchanged` means the same
    /// authoritative expiry was already present, such as after a serialized
    /// retry. In both cases `reservation` must be the current active record.
    #[must_use]
    pub const fn new(mutation: MutationOutcome, reservation: AdmissionReservation) -> Self {
        Self {
            mutation,
            reservation,
        }
    }

    /// Returns whether durable expiry state changed.
    #[must_use]
    pub const fn mutation(&self) -> MutationOutcome {
        self.mutation
    }

    /// Returns the authoritative active reservation after renewal.
    #[must_use]
    pub const fn reservation(&self) -> &AdmissionReservation {
        &self.reservation
    }
}

/// Stable reason for returning projected capacity without usage settlement.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReleaseReason {
    /// The client cancelled before normal settlement.
    ClientCancelled,
    /// The admitted transport connection could not be established.
    ConnectionFailed,
    /// A required short-lived session ticket expired.
    TicketExpired,
    /// Provider startup or execution failed before settlement.
    ProviderFailed,
    /// The store reclaimed an expired active reservation.
    ReservationExpired,
    /// Internal orchestration explicitly compensated an active reservation.
    InternalCompensation,
}

/// First committed terminal outcome.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TerminalOutcome {
    /// Capacity returned without observed-usage settlement.
    Released(ReleaseReason),
    /// Observed usage settled exactly once.
    Settled(ActualUsage),
}

/// Immutable terminal record used for idempotent retries and audit output.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationReceipt {
    reservation: AdmissionReservation,
    outcome: TerminalOutcome,
    completed_at: MonotonicTime,
}

impl ReservationReceipt {
    /// Creates a terminal record after a store commits the first outcome.
    pub fn new(
        reservation: AdmissionReservation,
        outcome: TerminalOutcome,
        completed_at: MonotonicTime,
    ) -> AdmissionResult<Self> {
        if completed_at < reservation.created_at() {
            return Err(AdmissionError::InvalidArgument("completed_at"));
        }
        Ok(Self {
            reservation,
            outcome,
            completed_at,
        })
    }

    /// Returns the reservation that reached this terminal outcome.
    #[must_use]
    pub const fn reservation(&self) -> &AdmissionReservation {
        &self.reservation
    }

    /// Returns the authoritative first terminal outcome.
    #[must_use]
    pub const fn outcome(&self) -> &TerminalOutcome {
        &self.outcome
    }

    /// Returns the authoritative store completion time.
    #[must_use]
    pub const fn completed_at(&self) -> MonotonicTime {
        self.completed_at
    }

    /// Returns the lifecycle implied by the terminal outcome.
    #[must_use]
    pub const fn lifecycle(&self) -> ReservationLifecycle {
        match self.outcome {
            TerminalOutcome::Released(_) => ReservationLifecycle::Released,
            TerminalOutcome::Settled(_) => ReservationLifecycle::Settled,
        }
    }
}

/// Applied/unchanged lifecycle result with the authoritative first receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LifecycleMutation {
    mutation: MutationOutcome,
    receipt: ReservationReceipt,
}

impl LifecycleMutation {
    /// Creates a lifecycle result with its authoritative first receipt.
    #[must_use]
    pub const fn new(mutation: MutationOutcome, receipt: ReservationReceipt) -> Self {
        Self { mutation, receipt }
    }

    /// Returns whether terminal state changed.
    #[must_use]
    pub const fn mutation(&self) -> MutationOutcome {
        self.mutation
    }

    /// Returns the authoritative first terminal receipt.
    #[must_use]
    pub const fn receipt(&self) -> &ReservationReceipt {
        &self.receipt
    }
}

/// Authoritative resolution of one exact provisional generation.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CommitResolution {
    /// The same generation remains provisional until this authoritative expiry.
    Pending {
        /// Exact reconciliation handle returned by the store.
        pending: AdmissionPending,
        /// Authoritative expiry for the provisional generation.
        expires_at: MonotonicTime,
    },
    /// The generation committed and is still active.
    Committed(AdmissionReservation),
    /// The exact generation was compensated before publication.
    Compensated(AdmissionPending),
    /// The generation committed and later reached a terminal outcome.
    Terminal(ReservationReceipt),
    /// The exact provisional generation expired before publication.
    Expired(AdmissionPending),
}

/// Bounded result of one deterministic expiry-reclamation pass.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ReclaimReport {
    abandoned_attempts: usize,
    released_reservations: usize,
}

impl ReclaimReport {
    /// Creates a report from the two independently bounded reclaim counts.
    #[must_use]
    pub const fn new(abandoned_attempts: usize, released_reservations: usize) -> Self {
        Self {
            abandoned_attempts,
            released_reservations,
        }
    }

    /// Returns the number of unfinished attempts compensated.
    #[must_use]
    pub const fn abandoned_attempts(self) -> usize {
        self.abandoned_attempts
    }

    /// Returns the number of committed reservations released on expiry.
    #[must_use]
    pub const fn released_reservations(self) -> usize {
        self.released_reservations
    }

    /// Returns the total number of reclaimed records.
    #[must_use]
    pub const fn total(self) -> usize {
        self.abandoned_attempts
            .saturating_add(self.released_reservations)
    }
}

/// Canonical complete admission decision.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AdmissionDecision {
    /// Every gate allowed and the composite reservation was committed.
    Allowed(AdmissionReservation),
    /// One gate rejected without creating a committed reservation.
    Rejected(GateRejection),
    /// Publication or compensation is unresolved and must be reconciled.
    Pending(AdmissionPending),
}

/// Low-cardinality metric outcome.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum AdmissionMetricOutcome {
    /// Admission completed with a committed reservation.
    Allowed,
    /// Admission completed with a gate rejection.
    Rejected,
    /// Provisional claims were rolled back.
    Compensated,
    /// A provisional generation requires reconciliation.
    Pending,
}

/// Metric-safe labels that deliberately omit all IDs and secret-bearing values.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AdmissionMetricLabels {
    gate: AdmissionGate,
    outcome: AdmissionMetricOutcome,
    task: TaskKind,
    mode: SessionMode,
}

impl AdmissionMetricLabels {
    /// Creates metric-safe labels from bounded enum dimensions only.
    #[must_use]
    pub const fn new(
        gate: AdmissionGate,
        outcome: AdmissionMetricOutcome,
        task: TaskKind,
        mode: SessionMode,
    ) -> Self {
        Self {
            gate,
            outcome,
            task,
            mode,
        }
    }

    /// Returns the evaluated gate label.
    #[must_use]
    pub const fn gate(self) -> AdmissionGate {
        self.gate
    }

    /// Returns the stable admission outcome label.
    #[must_use]
    pub const fn outcome(self) -> AdmissionMetricOutcome {
        self.outcome
    }

    /// Returns the task-family label.
    #[must_use]
    pub const fn task(self) -> TaskKind {
        self.task
    }

    /// Returns the session-mode label.
    #[must_use]
    pub const fn mode(self) -> SessionMode {
        self.mode
    }
}

#[cfg(test)]
mod tests {
    use qingyin_security::test_support::{SecurityFixture, security_context};

    use super::*;

    fn resource_id(value: &str) -> AdmissionResult<ResourceId> {
        ResourceId::new(value).ok_or(AdmissionError::InvalidArgument("test_resource_id"))
    }

    fn fixture_context(fixture: SecurityFixture) -> AdmissionResult<SecurityContext> {
        security_context(fixture)
            .map_err(|_| AdmissionError::InvalidArgument("test_security_fixture"))
    }

    #[test]
    fn retry_and_ttl_bounds_reject_ambiguous_values() {
        assert_eq!(
            RetryAfterMs::new(0),
            Err(AdmissionError::InvalidArgument("retry_after_ms"))
        );
        assert_eq!(RetryAfterMs::new(1).map(RetryAfterMs::get), Ok(1));
        assert!(RetryAfterMs::new(MAX_RETRY_AFTER_MS).is_ok());
        assert_eq!(
            RetryAfterMs::new(MAX_RETRY_AFTER_MS + 1),
            Err(AdmissionError::InvalidArgument("retry_after_ms"))
        );
        assert_eq!(
            ReservationPolicy::new(Duration::from_millis(999)),
            Err(AdmissionError::InvalidArgument("reservation_ttl"))
        );
        assert_eq!(
            ReservationPolicy::new(Duration::from_secs(1) + Duration::from_nanos(1)),
            Err(AdmissionError::InvalidArgument("reservation_ttl"))
        );
        assert!(ReservationPolicy::new(Duration::from_secs(15 * 60)).is_ok());
    }

    #[test]
    fn rejection_reason_controls_gate_scope_and_retry_metadata() -> AdmissionResult<()> {
        let retry = RetryAfterMs::new(250)?;
        let busy = GateRejection::new(RejectionReason::ProviderCapacityExhausted, Some(retry))?;
        assert_eq!(busy.gate(), AdmissionGate::ProviderCapacity);
        assert_eq!(busy.scope(), GateScope::Provider);
        assert_eq!(busy.retry_after_ms(), Some(retry));

        let denied = GateRejection::new(RejectionReason::PolicyDenied, None)?;
        assert_eq!(denied.gate(), AdmissionGate::Policy);
        assert_eq!(denied.retry_after_ms(), None);
        assert_eq!(
            GateRejection::new(RejectionReason::BudgetExceeded, Some(retry)),
            Err(AdmissionError::InvalidArgument("retry_after_ms"))
        );
        Ok(())
    }

    #[test]
    fn operation_identity_generation_authority_and_debug_are_closed() -> AdmissionResult<()> {
        let actor = fixture_context(SecurityFixture::SessionActorA)?;
        let request = AdmissionRequest::new(
            actor.clone(),
            AdmissionRequestDigest::new([9; 32]),
            ReservationId::new(resource_id("rsv_model001")?),
            SessionId::new("ses_model001")
                .ok_or(AdmissionError::InvalidArgument("test_session_id"))?,
            TaskKind::Asr,
            SessionMode::Streaming,
            AdmissionSnapshots::new(
                PolicySnapshotId::new(resource_id("pol_model001")?),
                CapacitySnapshotId::new(resource_id("cap_model001")?),
            ),
            AdmissionDimensions::new(
                GatewayPoolId::new(resource_id("gwp_model001")?),
                ProviderPoolId::new(resource_id("pvp_model001")?),
                BudgetAccountId::new(resource_id("bud_model001")?),
            ),
            ProjectedUsage::new(1, 1, 10, 2, 3)?,
        )?;

        assert_eq!(
            request.operation_key().operation(),
            AdmissionOperation::SessionCreate
        );
        assert!(request.actor().matches_context(&actor));
        let different_actor = fixture_context(SecurityFixture::SessionActorB)?;
        assert!(!request.actor().matches_context(&different_actor));
        let reverified_actor = fixture_context(SecurityFixture::SessionActorAReverified)?;
        assert!(!request.actor().matches_context(&reverified_actor));

        assert_eq!(
            AttemptGeneration::new(0),
            Err(AdmissionError::InvalidArgument("attempt_generation"))
        );
        let generation = AttemptGeneration::first();
        assert_eq!(generation.checked_next()?.get(), 2);
        assert_eq!(
            AttemptGeneration::new(u64::MAX)?.checked_next(),
            Err(AdmissionError::Conflict)
        );

        let reservation = AdmissionReservation::from_admitted_request(
            &request,
            generation,
            MonotonicTime::from_millis(1),
            MonotonicTime::from_millis(1_001),
        )?;
        assert_eq!(reservation.identity().generation(), generation);
        assert_eq!(reservation.pending().identity(), reservation.identity());
        assert_eq!(format!("{request:?}"), "AdmissionRequest(<redacted>)");
        assert_eq!(
            format!("{:?}", request.operation_key()),
            "AdmissionOperationKey(<redacted>)"
        );
        assert_eq!(
            format!("{reservation:?}"),
            "AdmissionReservation(<redacted>)"
        );

        assert_eq!(
            AdmissionRuntimeAuthority::try_from_context(&actor),
            Err(AdmissionError::AuthorizationDenied)
        );
        let runtime = fixture_context(SecurityFixture::RuntimeA)?;
        assert!(AdmissionRuntimeAuthority::try_from_context(&runtime).is_ok());
        assert_eq!(ReclaimReport::new(usize::MAX, 1).total(), usize::MAX);
        Ok(())
    }
}
