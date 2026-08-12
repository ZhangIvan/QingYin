use std::error::Error;
use std::fmt;

/// Stable reason that caused an admission attempt to enter compensation.
///
/// Variants deliberately exclude backend errors, identifiers, and policy data
/// so they are safe to use as low-cardinality diagnostic labels.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum CompensationTrigger {
    /// A gate evaluation returned an error after earlier provisional claims.
    GateEvaluation,
    /// A gate rejected the request after earlier provisional claims.
    GateRejection,
    /// A gate returned a rejection that violated the fixed-order contract.
    GateInvariant,
}

impl fmt::Display for CompensationTrigger {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            Self::GateEvaluation => "gate_evaluation",
            Self::GateRejection => "gate_rejection",
            Self::GateInvariant => "gate_invariant",
        };
        formatter.write_str(label)
    }
}

/// Sanitized admission failure that never embeds tenant or resource identifiers.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AdmissionError {
    /// A bounded public constructor argument is invalid.
    InvalidArgument(&'static str),
    /// The verified principal is not authorized for the exact tenant resource.
    AuthorizationDenied,
    /// An idempotency identity already has incompatible content or outcome.
    Conflict,
    /// No reservation exists under the exact trusted tenant identity.
    NotFound,
    /// The admission state backend could not complete an operation.
    StoreUnavailable,
    /// Commit state cannot be proven published or compensated; reconcile by
    /// idempotent lookup or bounded expiry reclamation before retrying.
    CommitUncertain,
    /// A lifecycle response failed identity or outcome post-validation; callers
    /// must reconcile the same generation before issuing another mutation.
    LifecycleUncertain,
    /// Partial gate reservations could not be fully compensated for this trigger.
    CompensationFailed(CompensationTrigger),
    /// An attempt was used after commit or rollback.
    AttemptFinalized,
    /// A backend violated a documented admission contract.
    InvariantViolation(&'static str),
}

impl fmt::Display for AdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidArgument(field) => {
                write!(formatter, "invalid admission argument: {field}")
            }
            Self::AuthorizationDenied => formatter.write_str("admission authorization denied"),
            Self::Conflict => formatter.write_str("admission state conflict"),
            Self::NotFound => formatter.write_str("admission reservation not found"),
            Self::StoreUnavailable => formatter.write_str("admission state unavailable"),
            Self::CommitUncertain => formatter.write_str("admission commit outcome uncertain"),
            Self::LifecycleUncertain => {
                formatter.write_str("admission lifecycle outcome uncertain")
            }
            Self::CompensationFailed(trigger) => {
                write!(formatter, "admission compensation failed after {trigger}")
            }
            Self::AttemptFinalized => formatter.write_str("admission attempt finalized"),
            Self::InvariantViolation(rule) => {
                write!(formatter, "admission invariant violated: {rule}")
            }
        }
    }
}

impl Error for AdmissionError {}

/// Result returned by admission boundaries.
pub type AdmissionResult<T> = Result<T, AdmissionError>;
