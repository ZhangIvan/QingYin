use std::num::NonZeroU64;

use qingyin_types::{ResourceId, SessionId, SessionState, TimestampMs, TraceId};

use crate::{MonotonicTime, StateEntity, StateError, StateResult};

const MAX_STATE_KEY_LENGTH: usize = 256;
const MAX_NAMESPACE_LENGTH: usize = 64;
const MAX_TOPIC_LENGTH: usize = 128;
const MAX_STORED_VALUE_BYTES: usize = 64 * 1024;

macro_rules! state_resource_id {
    ($(#[$metadata:meta])* $name:ident) => {
        $(#[$metadata])*
        #[derive(Clone, Debug, Eq, Hash, PartialEq)]
        pub struct $name(ResourceId);

        impl $name {
            /// Creates a typed state identifier from a validated resource ID.
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

state_resource_id!(
    /// Organization identity at the enterprise tenant boundary.
    OrganizationId
);
state_resource_id!(
    /// Workspace identity at the default data-isolation boundary.
    WorkspaceId
);
state_resource_id!(
    /// Project identity inside one workspace.
    ProjectId
);
state_resource_id!(
    /// Environment identity separating development and production state.
    EnvironmentId
);

/// Complete ownership chain used in every durable and ephemeral state key.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct TenantScope {
    organization_id: OrganizationId,
    workspace_id: WorkspaceId,
    project_id: ProjectId,
    environment_id: EnvironmentId,
}

impl TenantScope {
    /// Creates an immutable tenant ownership chain resolved by trusted code.
    #[must_use]
    pub const fn new(
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        project_id: ProjectId,
        environment_id: EnvironmentId,
    ) -> Self {
        Self {
            organization_id,
            workspace_id,
            project_id,
            environment_id,
        }
    }

    /// Returns the organization identifier.
    #[must_use]
    pub const fn organization_id(&self) -> &OrganizationId {
        &self.organization_id
    }

    /// Returns the workspace identifier, the default data-isolation boundary.
    #[must_use]
    pub const fn workspace_id(&self) -> &WorkspaceId {
        &self.workspace_id
    }

    /// Returns the project identifier.
    #[must_use]
    pub const fn project_id(&self) -> &ProjectId {
        &self.project_id
    }

    /// Returns the environment identifier.
    #[must_use]
    pub const fn environment_id(&self) -> &EnvironmentId {
        &self.environment_id
    }
}

state_resource_id!(
    /// Stable identity of one resource reservation.
    ReservationId
);
state_resource_id!(
    /// Stable deduplication identity of one outbox record.
    OutboxId
);

/// Immutable snapshot references attached to a durable session intent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SessionReferences {
    route_snapshot_id: ResourceId,
    policy_snapshot_id: ResourceId,
    capacity_snapshot_id: ResourceId,
    provider_snapshot_id: ResourceId,
}

impl SessionReferences {
    /// Creates the complete immutable reference set required for later audit.
    #[must_use]
    pub const fn new(
        route_snapshot_id: ResourceId,
        policy_snapshot_id: ResourceId,
        capacity_snapshot_id: ResourceId,
        provider_snapshot_id: ResourceId,
    ) -> Self {
        Self {
            route_snapshot_id,
            policy_snapshot_id,
            capacity_snapshot_id,
            provider_snapshot_id,
        }
    }

    /// Returns the routing decision snapshot identifier.
    #[must_use]
    pub const fn route_snapshot_id(&self) -> &ResourceId {
        &self.route_snapshot_id
    }

    /// Returns the policy snapshot identifier.
    #[must_use]
    pub const fn policy_snapshot_id(&self) -> &ResourceId {
        &self.policy_snapshot_id
    }

    /// Returns the capacity-card snapshot identifier.
    #[must_use]
    pub const fn capacity_snapshot_id(&self) -> &ResourceId {
        &self.capacity_snapshot_id
    }

    /// Returns the provider capability snapshot identifier.
    #[must_use]
    pub const fn provider_snapshot_id(&self) -> &ResourceId {
        &self.provider_snapshot_id
    }
}

/// Durable tenant-scoped session summary and optimistic revision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SessionRecord {
    scope: TenantScope,
    session_id: SessionId,
    trace_id: TraceId,
    state: SessionState,
    references: SessionReferences,
    revision: u64,
    created_at_ms: TimestampMs,
    updated_at_ms: TimestampMs,
}

impl SessionRecord {
    /// Creates a new durable session record at revision zero.
    #[must_use]
    pub const fn new(
        scope: TenantScope,
        session_id: SessionId,
        trace_id: TraceId,
        state: SessionState,
        references: SessionReferences,
        created_at_ms: TimestampMs,
    ) -> Self {
        Self {
            scope,
            session_id,
            trace_id,
            state,
            references,
            revision: 0,
            created_at_ms,
            updated_at_ms: created_at_ms,
        }
    }

    /// Produces the next record while preserving idempotent same-state retries.
    pub fn transitioned(
        &self,
        next: SessionState,
        updated_at_ms: TimestampMs,
    ) -> StateResult<Self> {
        if self.state == next {
            return Ok(self.clone());
        }
        if !self.state.can_transition_to(next) {
            return Err(StateError::InvalidTransition {
                from: self.state,
                to: next,
            });
        }
        if updated_at_ms < self.updated_at_ms {
            return Err(StateError::InvalidArgument("updated_at_ms"));
        }

        let revision = self
            .revision
            .checked_add(1)
            .ok_or(StateError::Conflict(StateEntity::Session))?;
        let mut transitioned = self.clone();
        transitioned.state = next;
        transitioned.revision = revision;
        transitioned.updated_at_ms = updated_at_ms;
        Ok(transitioned)
    }

    /// Returns the immutable tenant scope.
    #[must_use]
    pub const fn scope(&self) -> &TenantScope {
        &self.scope
    }

    /// Returns the public session identifier.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        &self.session_id
    }

    /// Returns the cross-service trace identifier.
    #[must_use]
    pub const fn trace_id(&self) -> &TraceId {
        &self.trace_id
    }

    /// Returns the current internal session state.
    #[must_use]
    pub const fn state(&self) -> SessionState {
        self.state
    }

    /// Returns immutable route, policy, capacity, and provider references.
    #[must_use]
    pub const fn references(&self) -> &SessionReferences {
        &self.references
    }

    /// Returns the optimistic revision used by state transitions.
    #[must_use]
    pub const fn revision(&self) -> u64 {
        self.revision
    }

    /// Returns the creation time in Unix milliseconds.
    #[must_use]
    pub const fn created_at_ms(&self) -> TimestampMs {
        self.created_at_ms
    }

    /// Returns the most recent state-change time in Unix milliseconds.
    #[must_use]
    pub const fn updated_at_ms(&self) -> TimestampMs {
        self.updated_at_ms
    }
}

/// Stable, non-secret resource dimension reserved by later admission logic.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ReservationKey(String);

impl ReservationKey {
    /// Creates a bounded reservation dimension key.
    pub fn new(value: impl Into<String>) -> StateResult<Self> {
        let value = value.into();
        if value.is_empty() || value.len() > MAX_STATE_KEY_LENGTH {
            return Err(StateError::InvalidArgument("reservation_key"));
        }
        Ok(Self(value))
    }

    /// Returns the canonical reservation dimension.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Immutable reservation intent stored atomically with a session and outbox record.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationRecord {
    scope: TenantScope,
    reservation_id: ReservationId,
    session_id: SessionId,
    resource: ReservationKey,
    quantity: NonZeroU64,
    created_at: MonotonicTime,
    expires_at: MonotonicTime,
}

impl ReservationRecord {
    /// Creates a bounded reservation whose expiry is strictly after creation.
    pub fn new(
        scope: TenantScope,
        reservation_id: ReservationId,
        session_id: SessionId,
        resource: ReservationKey,
        quantity: NonZeroU64,
        created_at: MonotonicTime,
        expires_at: MonotonicTime,
    ) -> StateResult<Self> {
        if expires_at <= created_at {
            return Err(StateError::InvalidArgument("reservation_expiry"));
        }
        Ok(Self {
            scope,
            reservation_id,
            session_id,
            resource,
            quantity,
            created_at,
            expires_at,
        })
    }

    /// Returns the immutable tenant scope.
    #[must_use]
    pub const fn scope(&self) -> &TenantScope {
        &self.scope
    }

    /// Returns the reservation identifier.
    #[must_use]
    pub const fn reservation_id(&self) -> &ReservationId {
        &self.reservation_id
    }

    /// Returns the owner session identifier.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        &self.session_id
    }

    /// Returns the reserved resource dimension.
    #[must_use]
    pub const fn resource(&self) -> &ReservationKey {
        &self.resource
    }

    /// Returns the nonzero reserved quantity.
    #[must_use]
    pub const fn quantity(&self) -> NonZeroU64 {
        self.quantity
    }

    /// Returns the monotonic creation time.
    #[must_use]
    pub const fn created_at(&self) -> MonotonicTime {
        self.created_at
    }

    /// Returns the monotonic expiry boundary.
    #[must_use]
    pub const fn expires_at(&self) -> MonotonicTime {
        self.expires_at
    }
}

/// Bounded opaque payload stored in the transactional outbox.
#[derive(Clone, Eq, PartialEq)]
pub struct OutboxPayload(Vec<u8>);

impl OutboxPayload {
    /// Creates a non-empty payload within the M1 control-plane bound.
    pub fn new(value: impl Into<Vec<u8>>) -> StateResult<Self> {
        let value = value.into();
        if value.is_empty() || value.len() > MAX_STORED_VALUE_BYTES {
            return Err(StateError::InvalidArgument("outbox_payload"));
        }
        Ok(Self(value))
    }

    /// Returns the opaque bytes without providing a `Debug` representation.
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
}

/// Append-only outbox record staged with a durable state mutation.
#[derive(Clone, Eq, PartialEq)]
pub struct OutboxRecord {
    scope: TenantScope,
    outbox_id: OutboxId,
    aggregate_id: ResourceId,
    topic: String,
    source_sequence: u64,
    occurred_at_ms: TimestampMs,
    payload: OutboxPayload,
}

impl OutboxRecord {
    /// Creates a bounded outbox record with a stable deduplication identity.
    pub fn new(
        scope: TenantScope,
        outbox_id: OutboxId,
        aggregate_id: ResourceId,
        topic: impl Into<String>,
        source_sequence: u64,
        occurred_at_ms: TimestampMs,
        payload: OutboxPayload,
    ) -> StateResult<Self> {
        let topic = topic.into();
        if topic.is_empty() || topic.len() > MAX_TOPIC_LENGTH {
            return Err(StateError::InvalidArgument("outbox_topic"));
        }
        Ok(Self {
            scope,
            outbox_id,
            aggregate_id,
            topic,
            source_sequence,
            occurred_at_ms,
            payload,
        })
    }

    /// Returns the immutable tenant scope.
    #[must_use]
    pub const fn scope(&self) -> &TenantScope {
        &self.scope
    }

    /// Returns the outbox deduplication identifier.
    #[must_use]
    pub const fn outbox_id(&self) -> &OutboxId {
        &self.outbox_id
    }

    /// Returns the aggregate resource identifier.
    #[must_use]
    pub const fn aggregate_id(&self) -> &ResourceId {
        &self.aggregate_id
    }

    /// Returns the stable outbox topic.
    #[must_use]
    pub fn topic(&self) -> &str {
        &self.topic
    }

    /// Returns the source-local deduplication sequence.
    #[must_use]
    pub const fn source_sequence(&self) -> u64 {
        self.source_sequence
    }

    /// Returns the durable event time in Unix milliseconds.
    #[must_use]
    pub const fn occurred_at_ms(&self) -> TimestampMs {
        self.occurred_at_ms
    }

    /// Returns the opaque bounded payload.
    #[must_use]
    pub const fn payload(&self) -> &OutboxPayload {
        &self.payload
    }
}

/// Outbox record plus its first successful acknowledgement time.
#[derive(Clone, Eq, PartialEq)]
pub struct OutboxEntry {
    record: OutboxRecord,
    acknowledged_at_ms: Option<TimestampMs>,
}

impl OutboxEntry {
    /// Wraps a newly appended record in pending state.
    #[must_use]
    pub const fn pending(record: OutboxRecord) -> Self {
        Self {
            record,
            acknowledged_at_ms: None,
        }
    }

    /// Marks the record acknowledged once while preserving the first time.
    pub fn acknowledge(&mut self, at_ms: TimestampMs) -> StateResult<MutationOutcome> {
        if self.acknowledged_at_ms.is_some() {
            return Ok(MutationOutcome::Unchanged);
        }
        if at_ms < self.record.occurred_at_ms {
            return Err(StateError::InvalidArgument("outbox_acknowledged_at_ms"));
        }
        self.acknowledged_at_ms = Some(at_ms);
        Ok(MutationOutcome::Applied)
    }

    /// Returns the immutable outbox record.
    #[must_use]
    pub const fn record(&self) -> &OutboxRecord {
        &self.record
    }

    /// Returns the first acknowledgement time, if acknowledged.
    #[must_use]
    pub const fn acknowledged_at_ms(&self) -> Option<TimestampMs> {
        self.acknowledged_at_ms
    }
}

/// Result of an idempotent durable mutation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MutationOutcome {
    /// State changed exactly once.
    Applied,
    /// The requested state already existed and no state changed.
    Unchanged,
}

/// Tenant-local TTL namespace and key.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct TtlKey {
    namespace: String,
    key: String,
}

impl TtlKey {
    /// Creates a bounded namespace/key pair. Values, not keys, carry secret data.
    pub fn new(namespace: impl Into<String>, key: impl Into<String>) -> StateResult<Self> {
        let namespace = namespace.into();
        let key = key.into();
        if namespace.is_empty() || namespace.len() > MAX_NAMESPACE_LENGTH {
            return Err(StateError::InvalidArgument("ttl_namespace"));
        }
        if key.is_empty() || key.len() > MAX_STATE_KEY_LENGTH {
            return Err(StateError::InvalidArgument("ttl_key"));
        }
        Ok(Self { namespace, key })
    }

    /// Returns the bounded namespace.
    #[must_use]
    pub fn namespace(&self) -> &str {
        &self.namespace
    }

    /// Returns the tenant-local key.
    #[must_use]
    pub fn key(&self) -> &str {
        &self.key
    }
}

/// Opaque bounded bytes stored under TTL.
#[derive(Clone, Eq, PartialEq)]
pub struct TtlValue(Vec<u8>);

impl TtlValue {
    /// Creates a non-empty ephemeral value within the M1 control-plane bound.
    pub fn new(value: impl Into<Vec<u8>>) -> StateResult<Self> {
        let value = value.into();
        if value.is_empty() || value.len() > MAX_STORED_VALUE_BYTES {
            return Err(StateError::InvalidArgument("ttl_value"));
        }
        Ok(Self(value))
    }

    /// Returns the bytes without providing a `Debug` representation.
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
}

/// Monotonic revision used by conditional TTL operations.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct TtlRevision(u64);

impl TtlRevision {
    /// Creates a store-owned revision.
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    /// Returns the store-owned revision value.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Ephemeral value, revision, and exact monotonic expiry boundary.
#[derive(Clone, Eq, PartialEq)]
pub struct TtlEntry {
    value: TtlValue,
    revision: TtlRevision,
    expires_at: MonotonicTime,
}

impl TtlEntry {
    /// Creates an entry returned by a TTL store implementation.
    #[must_use]
    pub const fn new(value: TtlValue, revision: TtlRevision, expires_at: MonotonicTime) -> Self {
        Self {
            value,
            revision,
            expires_at,
        }
    }

    /// Returns the opaque value.
    #[must_use]
    pub const fn value(&self) -> &TtlValue {
        &self.value
    }

    /// Returns the conditional-operation revision.
    #[must_use]
    pub const fn revision(&self) -> TtlRevision {
        self.revision
    }

    /// Returns the exact monotonic expiry boundary.
    #[must_use]
    pub const fn expires_at(&self) -> MonotonicTime {
        self.expires_at
    }
}

/// Result of atomically inserting only when no live TTL value exists.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TtlPutResult {
    /// A new value was stored with this revision.
    Inserted(TtlRevision),
    /// A live value already occupied the key with this revision.
    Existing(TtlRevision),
}

/// Result of atomically extending one matching live TTL value.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TtlExtendResult {
    /// Expiry was extended and the value received a new revision.
    Extended {
        /// New conditional-operation revision.
        revision: TtlRevision,
        /// New exact monotonic expiry boundary.
        expires_at: MonotonicTime,
    },
    /// No live value exists at the key.
    Missing,
    /// A different revision is live, so expiry was not changed.
    RevisionMismatch {
        /// Current live revision.
        current: TtlRevision,
    },
}

/// Result of an atomic conditional remove-and-return operation.
#[derive(Clone, Eq, PartialEq)]
pub enum TtlTakeResult {
    /// The expected live value was removed and returned.
    Taken(TtlValue),
    /// No live value exists at the key.
    Missing,
    /// A different revision is live, so no value was removed.
    RevisionMismatch {
        /// Current live revision.
        current: TtlRevision,
    },
}
