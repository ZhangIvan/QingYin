use std::collections::{BTreeMap, HashMap, HashSet};
use std::hash::Hash;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use async_trait::async_trait;
use qingyin_admission::{
    ActualUsage, AdmissionAttempt, AdmissionError, AdmissionGate, AdmissionOperationKey,
    AdmissionPending, AdmissionRequest, AdmissionReservation, AdmissionResult, AdmissionStart,
    AdmissionStore, AttemptGeneration, BudgetAccountId, CapacitySnapshotId, CommitResolution,
    GateRejection, GateVerdict, GatewayPoolId, LifecycleMutation, PolicySnapshotId, ProviderPoolId,
    ReclaimReport, RejectionReason, ReleaseReason, RenewalId, ReservationIdentity,
    ReservationReceipt, ReservationRenewal, RetryAfterMs, TerminalOutcome,
};
use qingyin_state::{MonotonicClock, MonotonicTime, MutationOutcome, ReservationId, TenantScope};
use qingyin_types::ResourceId;

const MAX_RENEWAL_HISTORY: usize = 1_024;
const MAX_ATTEMPT_HISTORY_PER_IDENTITY: usize = 1_024;

/// Immutable capacity limits used by one deterministic admission store.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmissionCapacityProfile {
    snapshot_id: CapacitySnapshotId,
    request_rate_limit: u64,
    active_session_limit: u64,
    gateway_byte_limit: u64,
    provider_unit_limit: u64,
    budget_microunit_limit: u64,
    retry_after_ms: RetryAfterMs,
}

impl AdmissionCapacityProfile {
    /// Creates an immutable set of limits bound to one capacity snapshot.
    #[allow(clippy::too_many_arguments)]
    #[must_use]
    pub const fn new(
        snapshot_id: CapacitySnapshotId,
        request_rate_limit: u64,
        active_session_limit: u64,
        gateway_byte_limit: u64,
        provider_unit_limit: u64,
        budget_microunit_limit: u64,
        retry_after_ms: RetryAfterMs,
    ) -> Self {
        Self {
            snapshot_id,
            request_rate_limit,
            active_session_limit,
            gateway_byte_limit,
            provider_unit_limit,
            budget_microunit_limit,
            retry_after_ms,
        }
    }

    /// Returns the immutable snapshot accepted by this profile.
    #[must_use]
    pub const fn snapshot_id(&self) -> &CapacitySnapshotId {
        &self.snapshot_id
    }

    /// Returns the principal-scoped request-rate limit.
    #[must_use]
    pub const fn request_rate_limit(&self) -> u64 {
        self.request_rate_limit
    }

    /// Returns the project-scoped active-session limit.
    #[must_use]
    pub const fn active_session_limit(&self) -> u64 {
        self.active_session_limit
    }

    /// Returns the Gateway-pool byte limit.
    #[must_use]
    pub const fn gateway_byte_limit(&self) -> u64 {
        self.gateway_byte_limit
    }

    /// Returns the Provider-pool unit limit.
    #[must_use]
    pub const fn provider_unit_limit(&self) -> u64 {
        self.provider_unit_limit
    }

    /// Returns the budget-account microunit limit.
    #[must_use]
    pub const fn budget_microunit_limit(&self) -> u64 {
        self.budget_microunit_limit
    }

    /// Returns the deterministic retry delay for retryable capacity gates.
    #[must_use]
    pub const fn retry_after_ms(&self) -> RetryAfterMs {
        self.retry_after_ms
    }
}

/// Immutable decision attached to one policy snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmissionPolicyProfile {
    snapshot_id: PolicySnapshotId,
    allowed: bool,
}

impl AdmissionPolicyProfile {
    /// Creates a fixed allow or deny result for one policy snapshot.
    #[must_use]
    pub const fn new(snapshot_id: PolicySnapshotId, allowed: bool) -> Self {
        Self {
            snapshot_id,
            allowed,
        }
    }

    /// Returns the immutable snapshot accepted by this profile.
    #[must_use]
    pub const fn snapshot_id(&self) -> &PolicySnapshotId {
        &self.snapshot_id
    }

    /// Returns the fixed decision for the snapshot.
    #[must_use]
    pub const fn allowed(&self) -> bool {
        self.allowed
    }
}

/// Deterministic, process-local implementation of the admission state boundary.
///
/// This fake deliberately models atomic transitions and exact operation keys,
/// but it is not a production rate limiter or durable capacity backend.
#[derive(Clone)]
pub struct InMemoryAdmissionStore {
    inner: Arc<StoreInner>,
}

impl InMemoryAdmissionStore {
    /// Creates a store with an authoritative monotonic clock and frozen profiles.
    #[must_use]
    pub fn new<C>(
        clock: C,
        capacity: AdmissionCapacityProfile,
        policy: AdmissionPolicyProfile,
    ) -> Self
    where
        C: MonotonicClock + 'static,
    {
        Self {
            inner: Arc::new(StoreInner {
                clock: Arc::new(clock),
                capacity,
                policy,
                state: Mutex::new(StoreState::default()),
            }),
        }
    }

    fn state(&self) -> AdmissionResult<MutexGuard<'_, StoreState>> {
        self.inner
            .state
            .lock()
            .map_err(|_| AdmissionError::StoreUnavailable)
    }

    fn finish(
        &self,
        identity: &ReservationIdentity,
        outcome: TerminalOutcome,
    ) -> AdmissionResult<LifecycleMutation> {
        let key = IdentityKey::from_identity(identity);
        let mut state = self.state()?;
        let now = self.inner.clock.now();
        match state.records.get(&key).cloned() {
            Some(Record::Active(active)) => {
                if active.reservation.identity() != identity
                    || now >= active.reservation.expires_at()
                {
                    return Err(AdmissionError::Conflict);
                }
                let mut counters = state.counters.clone();
                counters.refund(&active.claims, false)?;
                let receipt = ReservationReceipt::new(active.reservation, outcome.clone(), now)?;
                state.counters = counters;
                state.records.insert(
                    key,
                    Record::Terminal(TerminalRecord {
                        receipt: receipt.clone(),
                    }),
                );
                Ok(LifecycleMutation::new(MutationOutcome::Applied, receipt))
            }
            Some(Record::Terminal(terminal))
                if terminal.receipt.reservation().identity() == identity
                    && terminal.receipt.outcome() == &outcome =>
            {
                Ok(LifecycleMutation::new(
                    MutationOutcome::Unchanged,
                    terminal.receipt,
                ))
            }
            Some(_) => Err(AdmissionError::Conflict),
            None => Err(AdmissionError::NotFound),
        }
    }
}

struct StoreInner {
    clock: Arc<dyn MonotonicClock>,
    capacity: AdmissionCapacityProfile,
    policy: AdmissionPolicyProfile,
    state: Mutex<StoreState>,
}

#[derive(Clone, Default)]
struct StoreState {
    last_generation: Option<AttemptGeneration>,
    records: HashMap<IdentityKey, Record>,
    attempt_history: HashMap<IdentityKey, BTreeMap<AttemptGeneration, HistoricalOutcome>>,
    counters: CapacityCounters,
}

impl StoreState {
    fn ensure_history_slot(
        &self,
        key: &IdentityKey,
        generation: AttemptGeneration,
    ) -> AdmissionResult<()> {
        let Some(history) = self.attempt_history.get(key) else {
            return Ok(());
        };
        if history.contains_key(&generation) {
            return Err(AdmissionError::InvariantViolation(
                "attempt_history_duplicate_generation",
            ));
        }
        if history.len() >= MAX_ATTEMPT_HISTORY_PER_IDENTITY {
            return Err(AdmissionError::Conflict);
        }
        Ok(())
    }

    fn archive_tombstone(&mut self, key: &IdentityKey, tombstone: &TombstoneRecord, expired: bool) {
        let outcome = if expired {
            HistoricalOutcome::Expired(tombstone.pending.clone())
        } else {
            HistoricalOutcome::Compensated(tombstone.pending.clone())
        };
        self.attempt_history
            .entry(key.clone())
            .or_default()
            .insert(tombstone.pending.identity().generation(), outcome);
    }

    fn allocate_generation(&mut self) -> AdmissionResult<AttemptGeneration> {
        let generation = match self.last_generation {
            Some(previous) => previous.checked_next()?,
            None => AttemptGeneration::first(),
        };
        self.last_generation = Some(generation);
        Ok(generation)
    }
}

#[derive(Clone, Eq, Hash, PartialEq)]
struct IdentityKey {
    scope: TenantScope,
    reservation_id: ReservationId,
}

impl IdentityKey {
    fn from_request(request: &AdmissionRequest) -> Self {
        Self {
            scope: request.tenant_scope().clone(),
            reservation_id: request.reservation_id().clone(),
        }
    }

    fn from_identity(identity: &ReservationIdentity) -> Self {
        Self {
            scope: identity.scope().clone(),
            reservation_id: identity.reservation_id().clone(),
        }
    }
}

#[derive(Clone)]
enum Record {
    Attempt(AttemptRecord),
    Active(ActiveRecord),
    Terminal(TerminalRecord),
    Compensated(TombstoneRecord),
    ExpiredAttempt(TombstoneRecord),
}

impl Record {
    fn operation_key(&self) -> &AdmissionOperationKey {
        match self {
            Self::Attempt(attempt) => attempt.request.operation_key(),
            Self::Active(active) => active.reservation.identity().operation_key(),
            Self::Terminal(terminal) => terminal.receipt.reservation().identity().operation_key(),
            Self::Compensated(tombstone) | Self::ExpiredAttempt(tombstone) => {
                tombstone.request.operation_key()
            }
        }
    }

    fn generation(&self) -> AttemptGeneration {
        match self {
            Self::Attempt(attempt) => attempt.pending.identity().generation(),
            Self::Active(active) => active.reservation.identity().generation(),
            Self::Terminal(terminal) => terminal.receipt.reservation().identity().generation(),
            Self::Compensated(tombstone) | Self::ExpiredAttempt(tombstone) => {
                tombstone.pending.identity().generation()
            }
        }
    }

    fn matches_request(&self, request: &AdmissionRequest) -> bool {
        match self {
            Self::Attempt(attempt) => attempt.request == *request,
            Self::Active(active) => active.reservation.matches_request(request),
            Self::Terminal(terminal) => terminal.receipt.reservation().matches_request(request),
            Self::Compensated(tombstone) | Self::ExpiredAttempt(tombstone) => {
                tombstone.request == *request
            }
        }
    }
}

#[derive(Clone)]
struct AttemptRecord {
    request: AdmissionRequest,
    pending: AdmissionPending,
    created_at: MonotonicTime,
    expires_at: MonotonicTime,
    next_gate: usize,
    rejected: bool,
    claims: Vec<CapacityClaim>,
}

#[derive(Clone)]
struct ActiveRecord {
    reservation: AdmissionReservation,
    claims: Vec<CapacityClaim>,
    renewals: HashSet<RenewalId>,
}

#[derive(Clone)]
struct TerminalRecord {
    receipt: ReservationReceipt,
}

#[derive(Clone)]
struct TombstoneRecord {
    request: AdmissionRequest,
    pending: AdmissionPending,
}

#[derive(Clone)]
enum HistoricalOutcome {
    Compensated(AdmissionPending),
    Expired(AdmissionPending),
}

impl HistoricalOutcome {
    fn pending(&self) -> &AdmissionPending {
        match self {
            Self::Compensated(pending) | Self::Expired(pending) => pending,
        }
    }
}

#[derive(Clone)]
enum CapacityClaim {
    RequestRate(RequestRateKey, u64),
    ActiveSessions(ProjectKey, u64),
    GatewayBytes(GatewayPoolId, u64),
    ProviderCapacity(ProviderPoolId, u64),
    Budget(BudgetKey, u64),
}

#[derive(Clone, Eq, Hash, PartialEq)]
struct ProjectKey {
    organization_id: ResourceId,
    workspace_id: ResourceId,
    project_id: ResourceId,
}

impl ProjectKey {
    fn from_scope(scope: &TenantScope) -> Self {
        Self {
            organization_id: scope.organization_id().as_resource_id().clone(),
            workspace_id: scope.workspace_id().as_resource_id().clone(),
            project_id: scope.project_id().as_resource_id().clone(),
        }
    }
}

#[derive(Clone, Eq, Hash, PartialEq)]
struct RequestRateKey {
    scope: TenantScope,
    principal_id: ResourceId,
}

#[derive(Clone, Eq, Hash, PartialEq)]
struct BudgetKey {
    scope: TenantScope,
    account: BudgetAccountId,
}

#[derive(Clone, Default)]
struct CapacityCounters {
    request_rate: HashMap<RequestRateKey, u64>,
    active_sessions: HashMap<ProjectKey, u64>,
    gateway_bytes: HashMap<GatewayPoolId, u64>,
    provider_units: HashMap<ProviderPoolId, u64>,
    budget_microunits: HashMap<BudgetKey, u64>,
}

impl CapacityCounters {
    fn can_reserve(&self, claim: &CapacityClaim, profile: &AdmissionCapacityProfile) -> bool {
        match claim {
            CapacityClaim::RequestRate(key, quantity) => can_add(
                &self.request_rate,
                key,
                *quantity,
                profile.request_rate_limit,
            ),
            CapacityClaim::ActiveSessions(key, quantity) => can_add(
                &self.active_sessions,
                key,
                *quantity,
                profile.active_session_limit,
            ),
            CapacityClaim::GatewayBytes(key, quantity) => can_add(
                &self.gateway_bytes,
                key,
                *quantity,
                profile.gateway_byte_limit,
            ),
            CapacityClaim::ProviderCapacity(key, quantity) => can_add(
                &self.provider_units,
                key,
                *quantity,
                profile.provider_unit_limit,
            ),
            CapacityClaim::Budget(key, quantity) => can_add(
                &self.budget_microunits,
                key,
                *quantity,
                profile.budget_microunit_limit,
            ),
        }
    }

    fn reserve(&mut self, claim: &CapacityClaim) -> AdmissionResult<()> {
        match claim {
            CapacityClaim::RequestRate(key, quantity) => {
                add(&mut self.request_rate, key, *quantity)
            }
            CapacityClaim::ActiveSessions(key, quantity) => {
                add(&mut self.active_sessions, key, *quantity)
            }
            CapacityClaim::GatewayBytes(key, quantity) => {
                add(&mut self.gateway_bytes, key, *quantity)
            }
            CapacityClaim::ProviderCapacity(key, quantity) => {
                add(&mut self.provider_units, key, *quantity)
            }
            CapacityClaim::Budget(key, quantity) => {
                add(&mut self.budget_microunits, key, *quantity)
            }
        }
    }

    fn can_refund(&self, claims: &[CapacityClaim], refund_request_rate: bool) -> bool {
        claims.iter().all(|claim| {
            if matches!(claim, CapacityClaim::RequestRate(_, _)) && !refund_request_rate {
                return true;
            }
            match claim {
                CapacityClaim::RequestRate(key, quantity) => {
                    can_subtract(&self.request_rate, key, *quantity)
                }
                CapacityClaim::ActiveSessions(key, quantity) => {
                    can_subtract(&self.active_sessions, key, *quantity)
                }
                CapacityClaim::GatewayBytes(key, quantity) => {
                    can_subtract(&self.gateway_bytes, key, *quantity)
                }
                CapacityClaim::ProviderCapacity(key, quantity) => {
                    can_subtract(&self.provider_units, key, *quantity)
                }
                CapacityClaim::Budget(key, quantity) => {
                    can_subtract(&self.budget_microunits, key, *quantity)
                }
            }
        })
    }

    fn refund(
        &mut self,
        claims: &[CapacityClaim],
        refund_request_rate: bool,
    ) -> AdmissionResult<()> {
        if !self.can_refund(claims, refund_request_rate) {
            return Err(AdmissionError::InvariantViolation(
                "admission_capacity_underflow",
            ));
        }
        for claim in claims {
            if matches!(claim, CapacityClaim::RequestRate(_, _)) && !refund_request_rate {
                continue;
            }
            match claim {
                CapacityClaim::RequestRate(key, quantity) => {
                    subtract(&mut self.request_rate, key, *quantity);
                }
                CapacityClaim::ActiveSessions(key, quantity) => {
                    subtract(&mut self.active_sessions, key, *quantity);
                }
                CapacityClaim::GatewayBytes(key, quantity) => {
                    subtract(&mut self.gateway_bytes, key, *quantity);
                }
                CapacityClaim::ProviderCapacity(key, quantity) => {
                    subtract(&mut self.provider_units, key, *quantity);
                }
                CapacityClaim::Budget(key, quantity) => {
                    subtract(&mut self.budget_microunits, key, *quantity);
                }
            }
        }
        Ok(())
    }
}

fn can_add<K>(values: &HashMap<K, u64>, key: &K, quantity: u64, limit: u64) -> bool
where
    K: Eq + Hash,
{
    values
        .get(key)
        .copied()
        .unwrap_or(0)
        .checked_add(quantity)
        .is_some_and(|next| next <= limit)
}

fn add<K>(values: &mut HashMap<K, u64>, key: &K, quantity: u64) -> AdmissionResult<()>
where
    K: Clone + Eq + Hash,
{
    if quantity == 0 {
        return Ok(());
    }
    let next = values
        .get(key)
        .copied()
        .unwrap_or(0)
        .checked_add(quantity)
        .ok_or(AdmissionError::InvariantViolation(
            "admission_capacity_overflow",
        ))?;
    values.insert(key.clone(), next);
    Ok(())
}

fn can_subtract<K>(values: &HashMap<K, u64>, key: &K, quantity: u64) -> bool
where
    K: Eq + Hash,
{
    values.get(key).copied().unwrap_or(0) >= quantity
}

fn subtract<K>(values: &mut HashMap<K, u64>, key: &K, quantity: u64)
where
    K: Clone + Eq + Hash,
{
    if quantity == 0 {
        return;
    }
    let current = values.get(key).copied().unwrap_or(0);
    let next = current - quantity;
    if next == 0 {
        values.remove(key);
    } else {
        values.insert(key.clone(), next);
    }
}

struct InMemoryAdmissionAttempt {
    store: InMemoryAdmissionStore,
    key: IdentityKey,
    pending: AdmissionPending,
    finalized: bool,
}

impl InMemoryAdmissionAttempt {
    fn rejection(
        gate: AdmissionGate,
        retry_after_ms: RetryAfterMs,
    ) -> AdmissionResult<GateVerdict> {
        let (reason, retry_after) = match gate {
            AdmissionGate::RequestRate => {
                (RejectionReason::RequestRateExceeded, Some(retry_after_ms))
            }
            AdmissionGate::ActiveSessions => {
                (RejectionReason::ActiveSessionLimit, Some(retry_after_ms))
            }
            AdmissionGate::GatewayBytes => (
                RejectionReason::GatewayByteBudgetExhausted,
                Some(retry_after_ms),
            ),
            AdmissionGate::ProviderCapacity => (
                RejectionReason::ProviderCapacityExhausted,
                Some(retry_after_ms),
            ),
            AdmissionGate::Policy => (RejectionReason::PolicyDenied, None),
            AdmissionGate::Budget => (RejectionReason::BudgetExceeded, None),
        };
        GateRejection::new(reason, retry_after).map(GateVerdict::Rejected)
    }

    fn capacity_claim(request: &AdmissionRequest, gate: AdmissionGate) -> Option<CapacityClaim> {
        let usage = request.projected_usage();
        match gate {
            AdmissionGate::RequestRate => Some(CapacityClaim::RequestRate(
                RequestRateKey {
                    scope: request.tenant_scope().clone(),
                    principal_id: request.principal_id().as_resource_id().clone(),
                },
                usage.request_units().get(),
            )),
            AdmissionGate::ActiveSessions => Some(CapacityClaim::ActiveSessions(
                ProjectKey::from_scope(request.tenant_scope()),
                usage.active_sessions().get(),
            )),
            AdmissionGate::GatewayBytes => Some(CapacityClaim::GatewayBytes(
                request.dimensions().gateway_pool().clone(),
                usage.gateway_bytes(),
            )),
            AdmissionGate::ProviderCapacity => Some(CapacityClaim::ProviderCapacity(
                request.dimensions().provider_pool().clone(),
                usage.provider_units(),
            )),
            AdmissionGate::Policy => None,
            AdmissionGate::Budget => Some(CapacityClaim::Budget(
                BudgetKey {
                    scope: request.tenant_scope().clone(),
                    account: request.dimensions().budget_account().clone(),
                },
                usage.budget_microunits(),
            )),
        }
    }

    fn transition_attempt(
        state: &mut StoreState,
        key: &IdentityKey,
        attempt: &AttemptRecord,
        expired: bool,
    ) -> AdmissionResult<MutationOutcome> {
        state.counters.refund(&attempt.claims, true)?;
        let tombstone = TombstoneRecord {
            request: attempt.request.clone(),
            pending: attempt.pending.clone(),
        };
        let record = if expired {
            Record::ExpiredAttempt(tombstone)
        } else {
            Record::Compensated(tombstone)
        };
        state.records.insert(key.clone(), record);
        Ok(MutationOutcome::Applied)
    }

    fn compensate_for_commit(
        state: &mut StoreState,
        key: &IdentityKey,
        attempt: &AttemptRecord,
    ) -> AdmissionResult<()> {
        Self::transition_attempt(state, key, attempt, false)
            .map(|_| ())
            .map_err(|_| AdmissionError::CommitUncertain)
    }

    fn expire_for_commit(
        state: &mut StoreState,
        key: &IdentityKey,
        attempt: &AttemptRecord,
    ) -> AdmissionResult<()> {
        Self::transition_attempt(state, key, attempt, true)
            .map(|_| ())
            .map_err(|_| AdmissionError::CommitUncertain)
    }

    fn exact_attempt(
        state: &StoreState,
        key: &IdentityKey,
        pending: &AdmissionPending,
    ) -> AdmissionResult<AttemptRecord> {
        let record = state.records.get(key).ok_or(AdmissionError::NotFound)?;
        if record.operation_key() != pending.identity().operation_key()
            || record.generation() != pending.identity().generation()
        {
            return Err(AdmissionError::Conflict);
        }
        match record {
            Record::Attempt(attempt) => Ok(attempt.clone()),
            _ => Err(AdmissionError::Conflict),
        }
    }
}

#[async_trait]
impl AdmissionAttempt for InMemoryAdmissionAttempt {
    fn pending(&self) -> &AdmissionPending {
        &self.pending
    }

    async fn evaluate(&mut self, gate: AdmissionGate) -> AdmissionResult<GateVerdict> {
        if self.finalized {
            return Err(AdmissionError::AttemptFinalized);
        }

        let mut state = self.store.state()?;
        let now = self.store.inner.clock.now();
        let mut attempt = Self::exact_attempt(&state, &self.key, &self.pending)?;
        if now >= attempt.expires_at {
            Self::transition_attempt(&mut state, &self.key, &attempt, true)?;
            return Err(AdmissionError::Conflict);
        }
        if attempt.rejected {
            return Err(AdmissionError::AttemptFinalized);
        }
        if AdmissionGate::ORDER.get(attempt.next_gate).copied() != Some(gate) {
            return Err(AdmissionError::InvariantViolation("admission_gate_order"));
        }

        if gate != AdmissionGate::Policy
            && attempt.request.snapshots().capacity() != self.store.inner.capacity.snapshot_id()
        {
            return Err(AdmissionError::Conflict);
        }
        if gate == AdmissionGate::Policy {
            if attempt.request.snapshots().policy() != self.store.inner.policy.snapshot_id() {
                return Err(AdmissionError::Conflict);
            }
            attempt.next_gate = attempt
                .next_gate
                .checked_add(1)
                .ok_or(AdmissionError::InvariantViolation("admission_gate_index"))?;
            if self.store.inner.policy.allowed() {
                state
                    .records
                    .insert(self.key.clone(), Record::Attempt(attempt));
                return Ok(GateVerdict::Allowed);
            }
            attempt.rejected = true;
            state
                .records
                .insert(self.key.clone(), Record::Attempt(attempt));
            return Self::rejection(gate, self.store.inner.capacity.retry_after_ms());
        }

        let claim = Self::capacity_claim(&attempt.request, gate).ok_or(
            AdmissionError::InvariantViolation("admission_capacity_gate"),
        )?;
        attempt.next_gate = attempt
            .next_gate
            .checked_add(1)
            .ok_or(AdmissionError::InvariantViolation("admission_gate_index"))?;
        if !state
            .counters
            .can_reserve(&claim, &self.store.inner.capacity)
        {
            attempt.rejected = true;
            state
                .records
                .insert(self.key.clone(), Record::Attempt(attempt));
            return Self::rejection(gate, self.store.inner.capacity.retry_after_ms());
        }

        state.counters.reserve(&claim)?;
        attempt.claims.push(claim);
        state
            .records
            .insert(self.key.clone(), Record::Attempt(attempt));
        Ok(GateVerdict::Allowed)
    }

    async fn commit(mut self: Box<Self>) -> AdmissionResult<AdmissionReservation> {
        if self.finalized {
            return Err(AdmissionError::Conflict);
        }
        let mut state = self
            .store
            .inner
            .state
            .lock()
            .map_err(|_| AdmissionError::CommitUncertain)?;
        let now = self.store.inner.clock.now();
        let current = match state.records.get(&self.key).cloned() {
            Some(record) => record,
            None => return Err(AdmissionError::CommitUncertain),
        };
        if current.operation_key() != self.pending.identity().operation_key() {
            return Err(AdmissionError::CommitUncertain);
        }
        let expected_generation = self.pending.identity().generation();
        if current.generation() > expected_generation {
            self.finalized = true;
            return Err(AdmissionError::Conflict);
        }
        if current.generation() < expected_generation {
            return Err(AdmissionError::CommitUncertain);
        }
        let attempt = match current {
            Record::Attempt(attempt) => attempt,
            Record::Compensated(_) | Record::ExpiredAttempt(_) => {
                self.finalized = true;
                return Err(AdmissionError::Conflict);
            }
            Record::Active(_) | Record::Terminal(_) => {
                return Err(AdmissionError::CommitUncertain);
            }
        };

        if now >= attempt.expires_at {
            Self::expire_for_commit(&mut state, &self.key, &attempt)?;
            self.finalized = true;
            return Err(AdmissionError::Conflict);
        }
        if attempt.rejected || attempt.next_gate != AdmissionGate::ORDER.len() {
            Self::compensate_for_commit(&mut state, &self.key, &attempt)?;
            self.finalized = true;
            return Err(AdmissionError::InvariantViolation(
                "incomplete_admission_attempt",
            ));
        }

        let reservation = match AdmissionReservation::from_admitted_request(
            &attempt.request,
            expected_generation,
            attempt.created_at,
            attempt.expires_at,
        ) {
            Ok(reservation) => reservation,
            Err(_) => {
                Self::compensate_for_commit(&mut state, &self.key, &attempt)?;
                self.finalized = true;
                return Err(AdmissionError::InvariantViolation(
                    "committed_reservation_construction",
                ));
            }
        };
        state.records.insert(
            self.key.clone(),
            Record::Active(ActiveRecord {
                reservation: reservation.clone(),
                claims: attempt.claims,
                renewals: HashSet::new(),
            }),
        );
        self.finalized = true;
        Ok(reservation)
    }

    async fn rollback(&mut self) -> AdmissionResult<MutationOutcome> {
        let mut state = self.store.state()?;
        let now = self.store.inner.clock.now();
        let current = state
            .records
            .get(&self.key)
            .cloned()
            .ok_or(AdmissionError::NotFound)?;
        if current.operation_key() != self.pending.identity().operation_key()
            || current.generation() != self.pending.identity().generation()
        {
            return Err(AdmissionError::Conflict);
        }
        match current {
            Record::Attempt(attempt) => {
                let expired = now >= attempt.expires_at;
                let outcome = Self::transition_attempt(&mut state, &self.key, &attempt, expired)?;
                self.finalized = true;
                Ok(outcome)
            }
            Record::Compensated(_) | Record::ExpiredAttempt(_) => {
                self.finalized = true;
                Ok(MutationOutcome::Unchanged)
            }
            Record::Active(_) | Record::Terminal(_) => Err(AdmissionError::Conflict),
        }
    }
}

#[async_trait]
impl AdmissionStore for InMemoryAdmissionStore {
    async fn begin(
        &self,
        request: &AdmissionRequest,
        ttl: Duration,
    ) -> AdmissionResult<AdmissionStart> {
        let key = IdentityKey::from_request(request);
        let mut state = self.state()?;
        let now = self.inner.clock.now();
        let expires_at = now
            .checked_add(ttl)
            .map_err(|_| AdmissionError::InvalidArgument("reservation_ttl"))?;
        if expires_at <= now {
            return Err(AdmissionError::InvalidArgument("reservation_ttl"));
        }

        let previous_tombstone = match state.records.get(&key).cloned() {
            Some(record) => {
                if record.operation_key() != request.operation_key()
                    || !record.matches_request(request)
                {
                    return Err(AdmissionError::Conflict);
                }
                match record {
                    Record::Attempt(attempt) => {
                        if now >= attempt.expires_at {
                            return Err(AdmissionError::Conflict);
                        }
                        return Ok(AdmissionStart::Pending(attempt.pending));
                    }
                    Record::Active(active) => {
                        if now >= active.reservation.expires_at() {
                            return Err(AdmissionError::Conflict);
                        }
                        return Ok(AdmissionStart::ExistingLive(active.reservation));
                    }
                    Record::Compensated(tombstone) => Some(tombstone),
                    Record::Terminal(_) | Record::ExpiredAttempt(_) => {
                        return Err(AdmissionError::Conflict);
                    }
                }
            }
            None => None,
        };

        if let Some(tombstone) = &previous_tombstone {
            state.ensure_history_slot(&key, tombstone.pending.identity().generation())?;
        }
        let generation = state.allocate_generation()?;
        if previous_tombstone
            .as_ref()
            .is_some_and(|previous| generation <= previous.pending.identity().generation())
        {
            return Err(AdmissionError::InvariantViolation(
                "attempt_generation_order",
            ));
        }
        if let Some(tombstone) = &previous_tombstone {
            state.archive_tombstone(&key, tombstone, false);
        }
        let identity =
            ReservationIdentity::from_operation_key(request.operation_key().clone(), generation);
        let pending = AdmissionPending::new(identity);
        state.records.insert(
            key.clone(),
            Record::Attempt(AttemptRecord {
                request: request.clone(),
                pending: pending.clone(),
                created_at: now,
                expires_at,
                next_gate: 0,
                rejected: false,
                claims: Vec::new(),
            }),
        );
        Ok(AdmissionStart::Attempt(Box::new(
            InMemoryAdmissionAttempt {
                store: self.clone(),
                key,
                pending,
                finalized: false,
            },
        )))
    }

    async fn reconcile(&self, pending: &AdmissionPending) -> AdmissionResult<CommitResolution> {
        let key = IdentityKey::from_identity(pending.identity());
        let mut state = self.state()?;
        let now = self.inner.clock.now();
        let current = state
            .records
            .get(&key)
            .cloned()
            .ok_or(AdmissionError::NotFound)?;
        if current.operation_key() != pending.identity().operation_key() {
            return Err(AdmissionError::Conflict);
        }
        let requested_generation = pending.identity().generation();
        if requested_generation < current.generation() {
            let historical = state
                .attempt_history
                .get(&key)
                .and_then(|history| history.get(&requested_generation));
            return match historical {
                Some(outcome) if outcome.pending() != pending => Err(AdmissionError::Conflict),
                Some(HistoricalOutcome::Compensated(historical)) => {
                    Ok(CommitResolution::Compensated(historical.clone()))
                }
                Some(HistoricalOutcome::Expired(historical)) => {
                    Ok(CommitResolution::Expired(historical.clone()))
                }
                None => Err(AdmissionError::Conflict),
            };
        }
        if requested_generation > current.generation() {
            return Err(AdmissionError::Conflict);
        }
        match current {
            Record::Attempt(attempt) if now < attempt.expires_at => Ok(CommitResolution::Pending {
                pending: attempt.pending,
                expires_at: attempt.expires_at,
            }),
            Record::Attempt(attempt) => {
                Self::expire_attempt(&mut state, &key, &attempt)?;
                Ok(CommitResolution::Expired(attempt.pending))
            }
            Record::Active(active) if now < active.reservation.expires_at() => {
                Ok(CommitResolution::Committed(active.reservation))
            }
            Record::Active(active) => {
                let mut counters = state.counters.clone();
                counters.refund(&active.claims, false)?;
                let receipt = ReservationReceipt::new(
                    active.reservation,
                    TerminalOutcome::Released(ReleaseReason::ReservationExpired),
                    now,
                )?;
                state.counters = counters;
                state.records.insert(
                    key,
                    Record::Terminal(TerminalRecord {
                        receipt: receipt.clone(),
                    }),
                );
                Ok(CommitResolution::Terminal(receipt))
            }
            Record::Terminal(terminal) => Ok(CommitResolution::Terminal(terminal.receipt)),
            Record::Compensated(tombstone) => Ok(CommitResolution::Compensated(tombstone.pending)),
            Record::ExpiredAttempt(tombstone) => Ok(CommitResolution::Expired(tombstone.pending)),
        }
    }

    async fn renew(
        &self,
        identity: &ReservationIdentity,
        renewal_id: &RenewalId,
        ttl: Duration,
    ) -> AdmissionResult<ReservationRenewal> {
        let key = IdentityKey::from_identity(identity);
        let mut state = self.state()?;
        let now = self.inner.clock.now();
        let mut active = match state.records.get(&key).cloned() {
            Some(Record::Active(active)) => active,
            None => return Err(AdmissionError::NotFound),
            Some(_) => return Err(AdmissionError::Conflict),
        };
        if active.reservation.identity() != identity || now >= active.reservation.expires_at() {
            return Err(AdmissionError::Conflict);
        }
        if active.renewals.contains(renewal_id) {
            return Ok(ReservationRenewal::new(
                MutationOutcome::Unchanged,
                active.reservation,
            ));
        }
        if active.renewals.len() >= MAX_RENEWAL_HISTORY {
            return Err(AdmissionError::Conflict);
        }

        let proposed = now
            .checked_add(ttl)
            .map_err(|_| AdmissionError::InvalidArgument("reservation_ttl"))?;
        let (mutation, resulting) = if proposed > active.reservation.expires_at() {
            (
                MutationOutcome::Applied,
                active.reservation.renewed_to(proposed)?,
            )
        } else {
            (MutationOutcome::Unchanged, active.reservation.clone())
        };
        active.renewals.insert(renewal_id.clone());
        active.reservation = resulting.clone();
        state.records.insert(key, Record::Active(active));
        Ok(ReservationRenewal::new(mutation, resulting))
    }

    async fn release(
        &self,
        identity: &ReservationIdentity,
        reason: ReleaseReason,
    ) -> AdmissionResult<LifecycleMutation> {
        self.finish(identity, TerminalOutcome::Released(reason))
    }

    async fn settle(
        &self,
        identity: &ReservationIdentity,
        usage: ActualUsage,
    ) -> AdmissionResult<LifecycleMutation> {
        self.finish(identity, TerminalOutcome::Settled(usage))
    }

    async fn reclaim_expired(
        &self,
        scope: &TenantScope,
        limit: usize,
    ) -> AdmissionResult<ReclaimReport> {
        if limit == 0 {
            return Ok(ReclaimReport::default());
        }
        let mut state = self.state()?;
        let now = self.inner.clock.now();
        let mut candidates = state
            .records
            .iter()
            .filter(|(key, _)| key.scope == *scope)
            .filter_map(|(key, record)| match record {
                Record::Attempt(attempt) if now >= attempt.expires_at => Some(ReclaimCandidate {
                    key: key.clone(),
                    expires_at: attempt.expires_at,
                    generation: attempt.pending.identity().generation(),
                }),
                Record::Active(active) if now >= active.reservation.expires_at() => {
                    Some(ReclaimCandidate {
                        key: key.clone(),
                        expires_at: active.reservation.expires_at(),
                        generation: active.reservation.identity().generation(),
                    })
                }
                _ => None,
            })
            .collect::<Vec<_>>();
        candidates.sort_by_key(|candidate| (candidate.expires_at, candidate.generation));
        candidates.truncate(limit);

        let mut working = state.clone();
        let mut abandoned_attempts = 0_usize;
        let mut released_reservations = 0_usize;
        for candidate in candidates {
            match working.records.get(&candidate.key).cloned() {
                Some(Record::Attempt(attempt))
                    if attempt.pending.identity().generation() == candidate.generation =>
                {
                    Self::expire_attempt(&mut working, &candidate.key, &attempt)?;
                    abandoned_attempts = abandoned_attempts
                        .checked_add(1)
                        .ok_or(AdmissionError::InvariantViolation("reclaim_attempt_count"))?;
                }
                Some(Record::Active(active))
                    if active.reservation.identity().generation() == candidate.generation =>
                {
                    working.counters.refund(&active.claims, false)?;
                    let receipt = ReservationReceipt::new(
                        active.reservation,
                        TerminalOutcome::Released(ReleaseReason::ReservationExpired),
                        now,
                    )?;
                    working
                        .records
                        .insert(candidate.key, Record::Terminal(TerminalRecord { receipt }));
                    released_reservations = released_reservations.checked_add(1).ok_or(
                        AdmissionError::InvariantViolation("reclaim_reservation_count"),
                    )?;
                }
                _ => {
                    return Err(AdmissionError::InvariantViolation(
                        "reclaim_candidate_changed",
                    ));
                }
            }
        }
        *state = working;
        Ok(ReclaimReport::new(
            abandoned_attempts,
            released_reservations,
        ))
    }
}

impl InMemoryAdmissionStore {
    fn expire_attempt(
        state: &mut StoreState,
        key: &IdentityKey,
        attempt: &AttemptRecord,
    ) -> AdmissionResult<()> {
        InMemoryAdmissionAttempt::transition_attempt(state, key, attempt, true).map(|_| ())
    }
}

struct ReclaimCandidate {
    key: IdentityKey,
    expires_at: MonotonicTime,
    generation: AttemptGeneration,
}
#[cfg(test)]
mod tests {
    use std::sync::{Arc, Barrier};
    use std::thread;
    use std::time::Duration;

    use crate::VirtualClock;
    use futures_executor::block_on;
    use qingyin_admission::{
        ActualUsage, AdmissionDecision, AdmissionDimensions, AdmissionGate, AdmissionPending,
        AdmissionRequest, AdmissionRequestDigest, AdmissionService, AdmissionSnapshots,
        BudgetAccountId, CapacitySnapshotId, CommitResolution, GatewayPoolId, PolicySnapshotId,
        ProjectedUsage, ProviderPoolId, RejectionReason, ReleaseReason, RenewalId,
        ReservationIdentity, ReservationPolicy, TerminalOutcome,
    };
    use qingyin_admission::{AdmissionError, AdmissionStart, AdmissionStore, GateVerdict};
    use qingyin_security::SecurityContext;
    use qingyin_security::test_support::{SecurityFixture, security_context};
    use qingyin_state::{
        EnvironmentId, MonotonicClock, MonotonicTime, MutationOutcome, OrganizationId, ProjectId,
        ReservationId, TenantScope, WorkspaceId,
    };
    use qingyin_types::{ResourceId, SessionId, SessionMode, TaskKind};

    use super::{
        AdmissionCapacityProfile, AdmissionPolicyProfile, InMemoryAdmissionStore, ProjectKey,
    };

    fn resource(value: &str) -> ResourceId {
        match ResourceId::new(value) {
            Some(value) => value,
            None => unreachable!("static test identifier is valid"),
        }
    }

    fn session(value: &str) -> SessionId {
        match SessionId::new(value) {
            Some(value) => value,
            None => unreachable!("static test session identifier is valid"),
        }
    }

    fn tenant(project: &str, environment: &str) -> TenantScope {
        TenantScope::new(
            OrganizationId::new(resource("org_test001")),
            WorkspaceId::new(resource("wsp_test001")),
            ProjectId::new(resource(project)),
            EnvironmentId::new(resource(environment)),
        )
    }

    fn context(fixture: SecurityFixture) -> SecurityContext {
        match security_context(fixture) {
            Ok(context) => context,
            Err(_) => unreachable!("closed security fixture is valid"),
        }
    }

    fn fixture_scope(fixture: SecurityFixture) -> TenantScope {
        context(fixture).principal().tenant_scope().clone()
    }

    struct Harness {
        clock: VirtualClock,
        store: InMemoryAdmissionStore,
        ttl: Duration,
    }

    impl Harness {
        fn new(limits: [u64; 5], policy_allowed: bool) -> Self {
            let clock = VirtualClock::new(MonotonicTime::from_millis(10_000));
            let retry = match qingyin_admission::RetryAfterMs::new(50) {
                Ok(value) => value,
                Err(_) => unreachable!("static retry is valid"),
            };
            let capacity = AdmissionCapacityProfile::new(
                CapacitySnapshotId::new(resource("cap_test001")),
                limits[0],
                limits[1],
                limits[2],
                limits[3],
                limits[4],
                retry,
            );
            let policy = AdmissionPolicyProfile::new(
                PolicySnapshotId::new(resource("pol_test001")),
                policy_allowed,
            );
            Self {
                clock: clock.clone(),
                store: InMemoryAdmissionStore::new(clock, capacity, policy),
                ttl: Duration::from_secs(2),
            }
        }

        fn service(&self) -> AdmissionService<InMemoryAdmissionStore> {
            let policy = match ReservationPolicy::new(self.ttl) {
                Ok(value) => value,
                Err(_) => unreachable!("static ttl is valid"),
            };
            AdmissionService::new(self.store.clone(), policy)
        }
    }

    fn request(
        context: SecurityContext,
        reservation: &str,
        session_id: &str,
        digest: u8,
        usage: [u64; 5],
    ) -> AdmissionRequest {
        let projected = match ProjectedUsage::new(usage[0], usage[1], usage[2], usage[3], usage[4])
        {
            Ok(value) => value,
            Err(_) => unreachable!("static usage is valid"),
        };
        match AdmissionRequest::new(
            context,
            AdmissionRequestDigest::new([digest; 32]),
            ReservationId::new(resource(reservation)),
            session(session_id),
            TaskKind::Asr,
            SessionMode::Streaming,
            AdmissionSnapshots::new(
                PolicySnapshotId::new(resource("pol_test001")),
                CapacitySnapshotId::new(resource("cap_test001")),
            ),
            AdmissionDimensions::new(
                GatewayPoolId::new(resource("gtw_test001")),
                ProviderPoolId::new(resource("prv_test001")),
                BudgetAccountId::new(resource("bud_test001")),
            ),
            projected,
        ) {
            Ok(value) => value,
            Err(_) => unreachable!("static request is valid"),
        }
    }

    fn base_request(reservation: &str) -> AdmissionRequest {
        request(
            context(SecurityFixture::SessionActorA),
            reservation,
            "ses_test001",
            9,
            [1, 1, 10, 10, 10],
        )
    }

    fn allowed(
        service: &AdmissionService<InMemoryAdmissionStore>,
        request: &AdmissionRequest,
    ) -> qingyin_admission::AdmissionReservation {
        match block_on(service.admit(request)) {
            Ok(AdmissionDecision::Allowed(reservation)) => reservation,
            _ => unreachable!("request is expected to be admitted"),
        }
    }

    fn renewal(value: &str) -> RenewalId {
        RenewalId::new(resource(value))
    }

    #[test]
    fn allows_all_gates_and_reconciles_pending_and_committed() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let request = base_request("rsv_allow001");
        let mut attempt = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens an attempt"),
        };
        let pending = attempt.pending().clone();
        assert!(matches!(
            block_on(harness.store.begin(&request, harness.ttl)),
            Ok(AdmissionStart::Pending(_))
        ));
        assert!(matches!(
            block_on(harness.store.reconcile(&pending)),
            Ok(CommitResolution::Pending { .. })
        ));
        for gate in AdmissionGate::ORDER {
            assert_eq!(block_on(attempt.evaluate(gate)), Ok(GateVerdict::Allowed));
        }
        let reservation = match block_on(attempt.commit()) {
            Ok(value) => value,
            Err(_) => unreachable!("complete attempt commits"),
        };
        assert_eq!(reservation.identity(), pending.identity());
        assert!(matches!(
            block_on(harness.store.reconcile(&pending)),
            Ok(CommitResolution::Committed(_))
        ));
        assert!(matches!(
            block_on(harness.store.begin(&request, harness.ttl)),
            Ok(AdmissionStart::ExistingLive(_))
        ));
    }

    #[test]
    fn each_gate_rejects_with_canonical_reason() {
        let cases = [
            (
                [0, 10, 100, 100, 100],
                true,
                RejectionReason::RequestRateExceeded,
            ),
            (
                [10, 0, 100, 100, 100],
                true,
                RejectionReason::ActiveSessionLimit,
            ),
            (
                [10, 10, 0, 100, 100],
                true,
                RejectionReason::GatewayByteBudgetExhausted,
            ),
            (
                [10, 10, 100, 0, 100],
                true,
                RejectionReason::ProviderCapacityExhausted,
            ),
            (
                [10, 10, 100, 100, 100],
                false,
                RejectionReason::PolicyDenied,
            ),
            ([10, 10, 100, 100, 0], true, RejectionReason::BudgetExceeded),
        ];
        for (index, (limits, policy, reason)) in cases.into_iter().enumerate() {
            let harness = Harness::new(limits, policy);
            let reservation = format!("rsv_reject{index:03}");
            let request = base_request(&reservation);
            match block_on(harness.service().admit(&request)) {
                Ok(AdmissionDecision::Rejected(rejection)) => {
                    assert_eq!(rejection.reason(), reason)
                }
                _ => unreachable!("configured gate rejects"),
            }
        }
    }

    #[test]
    fn order_violation_and_later_rejection_refund_all_provisional_claims() {
        let harness = Harness::new([1, 1, 10, 10, 0], true);
        let request = base_request("rsv_order001");
        let mut attempt = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens attempt"),
        };
        assert_eq!(
            block_on(attempt.evaluate(AdmissionGate::ActiveSessions)),
            Err(AdmissionError::InvariantViolation("admission_gate_order"))
        );
        assert_eq!(block_on(attempt.rollback()), Ok(MutationOutcome::Applied));

        let retry = base_request("rsv_order002");
        match block_on(harness.service().admit(&retry)) {
            Ok(AdmissionDecision::Rejected(rejection)) => {
                assert_eq!(rejection.reason(), RejectionReason::BudgetExceeded);
            }
            _ => unreachable!("rollback returned every earlier claim"),
        }
        let after = base_request("rsv_order003");
        match block_on(harness.service().admit(&after)) {
            Ok(AdmissionDecision::Rejected(rejection)) => {
                assert_eq!(rejection.reason(), RejectionReason::BudgetExceeded);
            }
            _ => unreachable!("rejection compensation returned earlier claims"),
        }
    }

    #[test]
    fn committed_request_rate_is_not_returned_by_terminal_lifecycle() {
        let harness = Harness::new([1, 10, 100, 100, 100], true);
        let service = harness.service();
        let first = base_request("rsv_rate001");
        let reservation = allowed(&service, &first);
        assert!(
            block_on(
                harness
                    .store
                    .release(reservation.identity(), ReleaseReason::ConnectionFailed)
            )
            .is_ok()
        );
        let second = base_request("rsv_rate002");
        match block_on(service.admit(&second)) {
            Ok(AdmissionDecision::Rejected(rejection)) => {
                assert_eq!(rejection.reason(), RejectionReason::RequestRateExceeded);
            }
            _ => unreachable!("committed rate debit remains consumed"),
        }
    }

    #[test]
    fn compensated_retry_advances_generation_and_stale_attempt_cannot_commit() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let request = base_request("rsv_aba0001");
        let mut first = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens attempt"),
        };
        let first_pending = first.pending().clone();
        assert_eq!(block_on(first.rollback()), Ok(MutationOutcome::Applied));
        assert_eq!(
            block_on(harness.store.reconcile(&first_pending)),
            Ok(CommitResolution::Compensated(first_pending.clone()))
        );
        let second = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("compensated operation opens next generation"),
        };
        assert!(second.pending().identity().generation() > first_pending.identity().generation());
        assert_eq!(block_on(first.commit()), Err(AdmissionError::Conflict));
        assert_eq!(
            block_on(harness.store.reconcile(&first_pending)),
            Ok(CommitResolution::Compensated(first_pending.clone()))
        );
    }

    #[test]
    fn operation_key_mismatch_in_actor_digest_request_digest_or_session_conflicts() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let original = request(
            context(SecurityFixture::SessionActorA),
            "rsv_match001",
            "ses_match001",
            1,
            [1, 1, 10, 10, 10],
        );
        assert!(matches!(
            block_on(harness.store.begin(&original, harness.ttl)),
            Ok(AdmissionStart::Attempt(_))
        ));
        let variants = [
            request(
                context(SecurityFixture::SessionActorB),
                "rsv_match001",
                "ses_match001",
                1,
                [1, 1, 10, 10, 10],
            ),
            request(
                context(SecurityFixture::SessionActorAReverified),
                "rsv_match001",
                "ses_match001",
                1,
                [1, 1, 10, 10, 10],
            ),
            request(
                context(SecurityFixture::SessionActorA),
                "rsv_match001",
                "ses_match001",
                2,
                [1, 1, 10, 10, 10],
            ),
            request(
                context(SecurityFixture::SessionActorA),
                "rsv_match001",
                "ses_other001",
                1,
                [1, 1, 10, 10, 10],
            ),
        ];
        for variant in variants {
            assert!(matches!(
                block_on(harness.store.begin(&variant, harness.ttl)),
                Err(AdmissionError::Conflict)
            ));
        }
    }

    #[test]
    fn evaluate_and_commit_at_exact_expiry_stay_expired() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let evaluate_request = base_request("rsv_expire001");
        let mut evaluating = match block_on(harness.store.begin(&evaluate_request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens attempt"),
        };
        let evaluate_pending = evaluating.pending().clone();
        assert!(harness.clock.advance(harness.ttl).is_ok());
        assert_eq!(
            block_on(evaluating.evaluate(AdmissionGate::RequestRate)),
            Err(AdmissionError::Conflict)
        );
        assert_eq!(
            block_on(evaluating.rollback()),
            Ok(MutationOutcome::Unchanged)
        );
        assert_eq!(
            block_on(harness.store.reconcile(&evaluate_pending)),
            Ok(CommitResolution::Expired(evaluate_pending.clone()))
        );
        assert!(matches!(
            block_on(harness.store.begin(&evaluate_request, harness.ttl)),
            Err(AdmissionError::Conflict)
        ));

        let commit_request = base_request("rsv_expire002");
        let mut committing = match block_on(harness.store.begin(&commit_request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens attempt"),
        };
        let commit_pending = committing.pending().clone();
        for gate in AdmissionGate::ORDER {
            assert_eq!(
                block_on(committing.evaluate(gate)),
                Ok(GateVerdict::Allowed)
            );
        }
        assert!(harness.clock.advance(harness.ttl).is_ok());
        assert_eq!(block_on(committing.commit()), Err(AdmissionError::Conflict));
        assert_eq!(
            block_on(harness.store.reconcile(&commit_pending)),
            Ok(CommitResolution::Expired(commit_pending.clone()))
        );
        assert!(matches!(
            block_on(harness.store.begin(&commit_request, harness.ttl)),
            Err(AdmissionError::Conflict)
        ));
    }

    #[test]
    fn reconcile_active_at_expiry_is_terminal_and_refunds_once() {
        let harness = Harness::new([10, 1, 10, 10, 10], true);
        let service = harness.service();
        let original_request = base_request("rsv_expire003");
        let reservation = allowed(&service, &original_request);
        let pending = reservation.pending();
        assert!(harness.clock.advance(harness.ttl).is_ok());
        let receipt = match block_on(harness.store.reconcile(&pending)) {
            Ok(CommitResolution::Terminal(receipt)) => receipt,
            _ => unreachable!("expired active reconciles terminal"),
        };
        assert_eq!(
            receipt.outcome(),
            &TerminalOutcome::Released(ReleaseReason::ReservationExpired)
        );
        assert!(matches!(
            block_on(harness.store.reconcile(&pending)),
            Ok(CommitResolution::Terminal(_))
        ));
        let different_actor = request(
            context(SecurityFixture::SessionActorB),
            "rsv_expire004",
            "ses_expire04",
            4,
            [1, 1, 10, 10, 10],
        );
        assert!(matches!(
            block_on(service.admit(&different_actor)),
            Ok(AdmissionDecision::Allowed(_))
        ));
    }

    #[test]
    fn expired_capacity_remains_fail_closed_until_reclaimer_runs() {
        let harness = Harness::new([10, 1, 10, 10, 10], true);
        let service = harness.service();
        let expired = allowed(&service, &base_request("rsv_expire005"));
        assert!(harness.clock.advance(harness.ttl).is_ok());

        let next_request = request(
            context(SecurityFixture::SessionActorB),
            "rsv_expire006",
            "ses_expire06",
            6,
            [1, 1, 10, 10, 10],
        );
        match block_on(service.admit(&next_request)) {
            Ok(AdmissionDecision::Rejected(rejection)) => {
                assert_eq!(rejection.reason(), RejectionReason::ActiveSessionLimit);
            }
            _ => unreachable!("expired claims remain fail-closed before reclaim"),
        }

        let report = match block_on(harness.store.reclaim_expired(expired.identity().scope(), 1)) {
            Ok(value) => value,
            Err(_) => unreachable!("bounded reclaimer releases expired capacity"),
        };
        assert_eq!(report.released_reservations(), 1);
        assert!(matches!(
            block_on(service.admit(&next_request)),
            Ok(AdmissionDecision::Allowed(_))
        ));
    }

    #[test]
    fn renewal_id_does_not_extend_twice_and_returns_current_state() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let reservation = allowed(&harness.service(), &base_request("rsv_renew001"));
        assert!(harness.clock.advance(Duration::from_millis(500)).is_ok());
        let renewal_id_a = renewal("ren_test001");
        let first = match block_on(harness.store.renew(
            reservation.identity(),
            &renewal_id_a,
            harness.ttl,
        )) {
            Ok(value) => value,
            Err(_) => unreachable!("first renewal succeeds"),
        };
        assert_eq!(first.mutation(), MutationOutcome::Applied);
        assert!(harness.clock.advance(Duration::from_millis(500)).is_ok());
        let second = match block_on(harness.store.renew(
            reservation.identity(),
            &renewal("ren_test002"),
            harness.ttl,
        )) {
            Ok(value) => value,
            Err(_) => unreachable!("different renewal id succeeds"),
        };
        assert_eq!(second.mutation(), MutationOutcome::Applied);
        assert!(second.reservation().expires_at() > first.reservation().expires_at());

        assert!(harness.clock.advance(Duration::from_millis(1_500)).is_ok());
        let replay = match block_on(harness.store.renew(
            reservation.identity(),
            &renewal_id_a,
            harness.ttl,
        )) {
            Ok(value) => value,
            Err(_) => unreachable!("same renewal id returns current active state"),
        };
        assert_eq!(replay.mutation(), MutationOutcome::Unchanged);
        assert_eq!(replay.reservation(), second.reservation());
        assert!(replay.reservation().expires_at() > harness.clock.now());
        assert!(matches!(
            block_on(harness.store.reconcile(&reservation.pending())),
            Ok(CommitResolution::Committed(current))
                if current == *second.reservation()
        ));
    }

    #[test]
    fn terminal_mutations_are_idempotent_and_conflicting_outcomes_fail() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let reservation = allowed(&harness.service(), &base_request("rsv_term0001"));
        let first = block_on(
            harness
                .store
                .release(reservation.identity(), ReleaseReason::ProviderFailed),
        );
        assert!(matches!(
            first,
            Ok(ref mutation) if mutation.mutation() == MutationOutcome::Applied
        ));
        let replay = block_on(
            harness
                .store
                .release(reservation.identity(), ReleaseReason::ProviderFailed),
        );
        assert!(matches!(
            replay,
            Ok(ref mutation) if mutation.mutation() == MutationOutcome::Unchanged
        ));
        assert_eq!(
            block_on(
                harness
                    .store
                    .release(reservation.identity(), ReleaseReason::ConnectionFailed,)
            ),
            Err(AdmissionError::Conflict)
        );
        let usage = match ActualUsage::new(1, 1, 1) {
            Ok(value) => value,
            Err(_) => unreachable!("static usage is valid"),
        };
        assert_eq!(
            block_on(harness.store.settle(reservation.identity(), usage)),
            Err(AdmissionError::Conflict)
        );
    }

    #[test]
    fn reclaim_is_bounded_and_tenant_scoped() {
        let harness = Harness::new([20, 20, 200, 200, 200], true);
        let scope_a = fixture_scope(SecurityFixture::SessionActorA);
        let scope_b = fixture_scope(SecurityFixture::OtherTenantActor);
        for (index, fixture) in [
            SecurityFixture::SessionActorA,
            SecurityFixture::SessionActorB,
            SecurityFixture::OtherTenantActor,
        ]
        .into_iter()
        .enumerate()
        {
            let request = request(
                context(fixture),
                &format!("rsv_scope{index:03}"),
                &format!("ses_scope{index:03}"),
                index as u8,
                [1, 1, 1, 1, 1],
            );
            assert!(matches!(
                block_on(harness.store.begin(&request, harness.ttl)),
                Ok(AdmissionStart::Attempt(_))
            ));
        }
        assert!(harness.clock.advance(harness.ttl).is_ok());
        let first = match block_on(harness.store.reclaim_expired(&scope_a, 1)) {
            Ok(value) => value,
            Err(_) => unreachable!("bounded reclaim succeeds"),
        };
        assert_eq!(first.abandoned_attempts(), 1);
        let second = match block_on(harness.store.reclaim_expired(&scope_a, 8)) {
            Ok(value) => value,
            Err(_) => unreachable!("remaining tenant reclaim succeeds"),
        };
        assert_eq!(second.abandoned_attempts(), 1);
        let other = match block_on(harness.store.reclaim_expired(&scope_b, 8)) {
            Ok(value) => value,
            Err(_) => unreachable!("other tenant reclaim succeeds"),
        };
        assert_eq!(other.abandoned_attempts(), 1);
    }

    #[test]
    fn active_limit_is_shared_within_project_but_tenants_isolate() {
        let harness = Harness::new([20, 1, 200, 200, 200], true);
        let first = request(
            context(SecurityFixture::SessionActorA),
            "rsv_project1",
            "ses_project1",
            1,
            [1, 1, 1, 1, 1],
        );
        let second = request(
            context(SecurityFixture::SessionActorB),
            "rsv_project2",
            "ses_project2",
            2,
            [1, 1, 1, 1, 1],
        );
        let isolated = request(
            context(SecurityFixture::OtherTenantActor),
            "rsv_project3",
            "ses_project3",
            3,
            [1, 1, 1, 1, 1],
        );
        assert!(matches!(
            block_on(harness.service().admit(&first)),
            Ok(AdmissionDecision::Allowed(_))
        ));
        match block_on(harness.service().admit(&second)) {
            Ok(AdmissionDecision::Rejected(rejection)) => {
                assert_eq!(rejection.reason(), RejectionReason::ActiveSessionLimit);
            }
            _ => unreachable!("same project shares active limit"),
        }
        assert!(matches!(
            block_on(harness.service().admit(&isolated)),
            Ok(AdmissionDecision::Allowed(_))
        ));
    }

    #[test]
    fn release_settle_race_has_one_terminal_winner() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let reservation = allowed(&harness.service(), &base_request("rsv_race0001"));
        let identity = reservation.identity().clone();
        let store_a = harness.store.clone();
        let store_b = harness.store.clone();
        let identity_a = identity.clone();
        let barrier = Arc::new(Barrier::new(3));
        let barrier_a = Arc::clone(&barrier);
        let release = thread::spawn(move || {
            barrier_a.wait();
            block_on(store_a.release(&identity_a, ReleaseReason::ClientCancelled))
        });
        let barrier_b = Arc::clone(&barrier);
        let settle = thread::spawn(move || {
            barrier_b.wait();
            let usage = match ActualUsage::new(1, 1, 1) {
                Ok(value) => value,
                Err(_) => unreachable!("static usage is valid"),
            };
            block_on(store_b.settle(&identity, usage))
        });
        barrier.wait();
        let released = release.join();
        let settled = settle.join();
        let applied = [released, settled]
            .into_iter()
            .filter(|result| {
                matches!(result, Ok(Ok(mutation)) if mutation.mutation() == MutationOutcome::Applied)
            })
            .count();
        assert_eq!(applied, 1);
    }

    #[test]
    fn identical_reservation_ids_are_isolated_by_complete_tenant_scope() {
        let harness = Harness::new([20, 20, 200, 200, 200], true);
        let first = request(
            context(SecurityFixture::SessionActorA),
            "rsv_same0001",
            "ses_same0001",
            1,
            [1, 1, 1, 1, 1],
        );
        let second = request(
            context(SecurityFixture::OtherTenantActor),
            "rsv_same0001",
            "ses_same0001",
            2,
            [1, 1, 1, 1, 1],
        );
        let first_reservation = allowed(&harness.service(), &first);
        let second_reservation = allowed(&harness.service(), &second);
        assert_ne!(first_reservation.identity(), second_reservation.identity());
        assert!(
            block_on(
                harness
                    .store
                    .release(first_reservation.identity(), ReleaseReason::ClientCancelled,)
            )
            .is_ok()
        );
        assert!(matches!(
            block_on(harness.store.reconcile(&second_reservation.pending())),
            Ok(CommitResolution::Committed(_))
        ));
    }

    #[test]
    fn renewal_history_is_bounded() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let reservation = allowed(&harness.service(), &base_request("rsv_bound001"));
        for index in 0..super::MAX_RENEWAL_HISTORY {
            let id = renewal(&format!("ren_bound{index:04}"));
            assert!(
                block_on(
                    harness
                        .store
                        .renew(reservation.identity(), &id, harness.ttl,)
                )
                .is_ok()
            );
        }
        let overflow = renewal("ren_overflow1");
        assert_eq!(
            block_on(
                harness
                    .store
                    .renew(reservation.identity(), &overflow, harness.ttl,)
            ),
            Err(AdmissionError::Conflict)
        );
    }

    #[test]
    fn mixed_reclaim_uses_expiry_then_generation_order() {
        let harness = Harness::new([20, 20, 200, 200, 200], true);
        let scope = fixture_scope(SecurityFixture::SessionActorA);
        let first_request = request(
            context(SecurityFixture::SessionActorA),
            "rsv_sorted01",
            "ses_sorted01",
            1,
            [1, 1, 1, 1, 1],
        );
        let first = match block_on(harness.store.begin(&first_request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("first operation opens attempt"),
        };
        let first_pending = first.pending().clone();
        assert!(harness.clock.advance(Duration::from_millis(500)).is_ok());
        let second_request = request(
            context(SecurityFixture::SessionActorB),
            "rsv_sorted02",
            "ses_sorted02",
            2,
            [1, 1, 1, 1, 1],
        );
        let second_reservation = allowed(&harness.service(), &second_request);
        assert!(harness.clock.advance(Duration::from_millis(1_500)).is_ok());
        let first_report = match block_on(harness.store.reclaim_expired(&scope, 1)) {
            Ok(value) => value,
            Err(_) => unreachable!("first bounded reclaim succeeds"),
        };
        assert_eq!(first_report.abandoned_attempts(), 1);
        assert_eq!(first_report.released_reservations(), 0);
        assert_eq!(
            block_on(harness.store.reconcile(&first_pending)),
            Ok(CommitResolution::Expired(first_pending.clone()))
        );
        assert!(matches!(
            block_on(harness.store.reconcile(&second_reservation.pending())),
            Ok(CommitResolution::Committed(_))
        ));
        assert!(harness.clock.advance(Duration::from_millis(500)).is_ok());
        let second_report = match block_on(harness.store.reclaim_expired(&scope, 1)) {
            Ok(value) => value,
            Err(_) => unreachable!("second bounded reclaim succeeds"),
        };
        assert_eq!(second_report.abandoned_attempts(), 0);
        assert_eq!(second_report.released_reservations(), 1);
        assert!(matches!(
            block_on(harness.store.reconcile(&second_reservation.pending())),
            Ok(CommitResolution::Terminal(_))
        ));
    }

    #[test]
    fn identical_settlement_is_idempotent_and_different_usage_conflicts() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let reservation = allowed(&harness.service(), &base_request("rsv_settle01"));
        let usage = match ActualUsage::new(5, 4, 3) {
            Ok(value) => value,
            Err(_) => unreachable!("static usage is valid"),
        };
        let first = block_on(harness.store.settle(reservation.identity(), usage));
        assert!(matches!(
            first,
            Ok(ref mutation) if mutation.mutation() == MutationOutcome::Applied
        ));
        let replay = block_on(harness.store.settle(reservation.identity(), usage));
        assert!(matches!(
            replay,
            Ok(ref mutation) if mutation.mutation() == MutationOutcome::Unchanged
        ));
        let different = match ActualUsage::new(5, 4, 2) {
            Ok(value) => value,
            Err(_) => unreachable!("static usage is valid"),
        };
        assert_eq!(
            block_on(harness.store.settle(reservation.identity(), different)),
            Err(AdmissionError::Conflict)
        );
    }
    #[test]
    fn rollback_at_exact_expiry_records_the_same_pending_as_expired() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let request = base_request("rsv_rbexpiry1");
        let mut attempt = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens attempt"),
        };
        let pending = attempt.pending().clone();
        assert!(harness.clock.advance(harness.ttl).is_ok());
        assert_eq!(block_on(attempt.rollback()), Ok(MutationOutcome::Applied));
        assert_eq!(
            block_on(harness.store.reconcile(&pending)),
            Ok(CommitResolution::Expired(pending.clone()))
        );
        assert_eq!(block_on(attempt.rollback()), Ok(MutationOutcome::Unchanged));
    }

    #[test]
    fn generation_history_distinguishes_known_outcomes_from_unknown_gaps() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let request = base_request("rsv_history01");
        let mut first = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("unseen operation opens attempt"),
        };
        let first_pending = first.pending().clone();
        assert_eq!(block_on(first.rollback()), Ok(MutationOutcome::Applied));

        let gap_request = base_request("rsv_history02");
        let mut gap = match block_on(harness.store.begin(&gap_request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("different identity opens global next generation"),
        };
        let gap_generation = gap.pending().identity().generation();
        assert_eq!(block_on(gap.rollback()), Ok(MutationOutcome::Applied));

        let second = match block_on(harness.store.begin(&request, harness.ttl)) {
            Ok(AdmissionStart::Attempt(attempt)) => attempt,
            _ => unreachable!("compensated operation opens another generation"),
        };
        assert!(second.pending().identity().generation() > gap_generation);
        assert_eq!(block_on(first.rollback()), Err(AdmissionError::Conflict));
        assert_eq!(
            block_on(harness.store.reconcile(&first_pending)),
            Ok(CommitResolution::Compensated(first_pending.clone()))
        );

        let unknown = AdmissionPending::new(ReservationIdentity::from_operation_key(
            request.operation_key().clone(),
            gap_generation,
        ));
        assert_eq!(
            block_on(harness.store.reconcile(&unknown)),
            Err(AdmissionError::Conflict)
        );
    }

    #[test]
    fn attempt_history_is_bounded_and_new_generation_fails_closed() {
        let harness = Harness::new([10, 10, 100, 100, 100], true);
        let request = base_request("rsv_histbound");
        for _ in 0..=super::MAX_ATTEMPT_HISTORY_PER_IDENTITY {
            let mut attempt = match block_on(harness.store.begin(&request, harness.ttl)) {
                Ok(AdmissionStart::Attempt(attempt)) => attempt,
                _ => unreachable!("history slot remains available"),
            };
            assert_eq!(block_on(attempt.rollback()), Ok(MutationOutcome::Applied));
        }
        assert!(matches!(
            block_on(harness.store.begin(&request, harness.ttl)),
            Err(AdmissionError::Conflict)
        ));
    }

    #[test]
    fn budget_account_ids_are_tenant_scoped() {
        let harness = Harness::new([10, 10, 100, 100, 1], true);
        let first = request(
            context(SecurityFixture::SessionActorA),
            "rsv_budget_a1",
            "ses_budget_a1",
            1,
            [1, 1, 1, 1, 1],
        );
        let other_tenant = request(
            context(SecurityFixture::OtherTenantActor),
            "rsv_budget_b1",
            "ses_budget_b1",
            2,
            [1, 1, 1, 1, 1],
        );
        let same_tenant = request(
            context(SecurityFixture::SessionActorB),
            "rsv_budget_a2",
            "ses_budget_a2",
            3,
            [1, 1, 1, 1, 1],
        );
        assert!(matches!(
            block_on(harness.service().admit(&first)),
            Ok(AdmissionDecision::Allowed(_))
        ));
        assert!(matches!(
            block_on(harness.service().admit(&other_tenant)),
            Ok(AdmissionDecision::Allowed(_))
        ));
        match block_on(harness.service().admit(&same_tenant)) {
            Ok(AdmissionDecision::Rejected(rejection)) => {
                assert_eq!(rejection.reason(), RejectionReason::BudgetExceeded);
            }
            _ => unreachable!("same tenant shares the budget-account limit"),
        }
    }

    #[test]
    fn project_capacity_key_ignores_environment_but_not_project() {
        let first = tenant("prj_keyshared", "env_key_a01");
        let other_environment = tenant("prj_keyshared", "env_key_b01");
        let other_project = tenant("prj_keyother1", "env_key_a01");
        assert!(ProjectKey::from_scope(&first) == ProjectKey::from_scope(&other_environment));
        assert!(ProjectKey::from_scope(&first) != ProjectKey::from_scope(&other_project));
    }
}
