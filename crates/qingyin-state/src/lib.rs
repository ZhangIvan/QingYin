//! Durable and ephemeral state boundaries for QingYin control-plane state.
//!
//! This crate defines storage semantics, not a database product. Production
//! adapters can use PostgreSQL, Redis, or equivalent systems only when they
//! preserve the transaction, tenant-isolation, idempotency, and TTL invariants
//! expressed by these interfaces.

mod error;
mod model;
mod store;
mod time;

pub use error::{StateEntity, StateError, StateResult};
pub use model::{
    EnvironmentId, MutationOutcome, OrganizationId, OutboxEntry, OutboxId, OutboxPayload,
    OutboxRecord, ProjectId, ReservationId, ReservationKey, ReservationRecord, SessionRecord,
    SessionReferences, TenantScope, TtlEntry, TtlExtendResult, TtlKey, TtlPutResult, TtlRevision,
    TtlTakeResult, TtlValue, WorkspaceId,
};
pub use store::{DurableStateStore, StateTransaction, TtlStore};
pub use time::{MonotonicClock, MonotonicTime};
