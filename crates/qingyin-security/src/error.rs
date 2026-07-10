use std::error::Error;
use std::fmt;

/// Sanitized security failure that never embeds credentials or ticket values.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SecurityError {
    /// A credential could not be authenticated or is no longer active.
    CredentialRejected,
    /// The authenticated principal lacks an explicitly required scope.
    PermissionDenied,
    /// A resource does not belong to the authenticated tenant chain.
    TenantScopeMismatch,
    /// A ticket is invalid, expired, revoked, already consumed, or incorrectly bound.
    TicketRejected,
    /// Ticket generation exhausted the bounded collision retry budget.
    TicketCollision,
    /// The operating-system entropy source failed.
    EntropyUnavailable,
    /// A bounded security argument is invalid.
    InvalidArgument(&'static str),
    /// Structured security metadata could not be encoded or decoded safely.
    EncodingFailure,
    /// The backing state store could not complete a security operation.
    StateUnavailable,
}

impl fmt::Display for SecurityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CredentialRejected => formatter.write_str("credential rejected"),
            Self::PermissionDenied => formatter.write_str("permission denied"),
            Self::TenantScopeMismatch => formatter.write_str("resource scope is unavailable"),
            Self::TicketRejected => formatter.write_str("session ticket rejected"),
            Self::TicketCollision => formatter.write_str("session ticket generation failed"),
            Self::EntropyUnavailable => formatter.write_str("secure entropy is unavailable"),
            Self::InvalidArgument(field) => write!(formatter, "invalid security argument: {field}"),
            Self::EncodingFailure => formatter.write_str("security metadata is invalid"),
            Self::StateUnavailable => formatter.write_str("security state is unavailable"),
        }
    }
}

impl Error for SecurityError {}

/// Result returned by security boundaries.
pub type SecurityResult<T> = Result<T, SecurityError>;
