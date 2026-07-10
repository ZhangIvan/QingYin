//! Admission decisions for capacity, budget, policy, and reservations.

/// Result of attempting to reserve capacity for a session.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdmissionDecision {
    /// Capacity was reserved.
    Allowed,
    /// Request was rejected with a retry hint in milliseconds.
    Rejected(AdmissionRejection),
}

/// Rejection details for an admission decision.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AdmissionRejection {
    /// Retry hint in milliseconds.
    pub retry_after_ms: u64,
}
