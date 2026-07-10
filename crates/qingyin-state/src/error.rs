use std::error::Error;
use std::fmt;

use qingyin_types::SessionState;

/// State entity category used in sanitized errors and metrics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StateEntity {
    /// A durable transaction.
    Transaction,
    /// A session record.
    Session,
    /// A resource reservation.
    Reservation,
    /// A transactional outbox record.
    Outbox,
    /// An ephemeral TTL value.
    TtlValue,
}

/// Storage-neutral state failure.
///
/// Variants identify the operation class without embedding tenant IDs, stored
/// payloads, credentials, or implementation-specific database messages.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StateError {
    /// An entity with the same identity already has different content.
    Conflict(StateEntity),
    /// A required entity does not exist in the caller's tenant scope.
    NotFound(StateEntity),
    /// A session transition is not permitted by the canonical state machine.
    InvalidTransition {
        /// Current persisted state.
        from: SessionState,
        /// Requested next state.
        to: SessionState,
    },
    /// A public operation received an invalid bounded argument.
    InvalidArgument(&'static str),
    /// A transaction was used after commit, rollback, or failed commit.
    TransactionFinalized,
    /// The backing store could not complete an operation safely.
    StoreUnavailable,
}

impl fmt::Display for StateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Conflict(entity) => write!(formatter, "state conflict for {entity}"),
            Self::NotFound(entity) => write!(formatter, "state entity not found: {entity}"),
            Self::InvalidTransition { from, to } => {
                write!(formatter, "invalid session transition: {from:?} -> {to:?}")
            }
            Self::InvalidArgument(field) => write!(formatter, "invalid state argument: {field}"),
            Self::TransactionFinalized => formatter.write_str("state transaction is finalized"),
            Self::StoreUnavailable => formatter.write_str("state store is unavailable"),
        }
    }
}

impl fmt::Display for StateEntity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::Transaction => "transaction",
            Self::Session => "session",
            Self::Reservation => "reservation",
            Self::Outbox => "outbox",
            Self::TtlValue => "ttl_value",
        };
        formatter.write_str(name)
    }
}

impl Error for StateError {}

/// Result returned by state boundaries and deterministic test implementations.
pub type StateResult<T> = Result<T, StateError>;
