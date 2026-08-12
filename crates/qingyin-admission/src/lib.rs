//! Deterministic multi-gate admission and reservation lifecycle boundary.

mod error;
mod model;
mod service;
mod store;

pub use error::{AdmissionError, AdmissionResult, CompensationTrigger};
pub use model::{
    ActualUsage, AdmissionActorBinding, AdmissionDecision, AdmissionDimensions, AdmissionGate,
    AdmissionMetricLabels, AdmissionMetricOutcome, AdmissionOperation, AdmissionOperationKey,
    AdmissionPending, AdmissionRequest, AdmissionRequestDigest, AdmissionReservation,
    AdmissionRuntimeAuthority, AdmissionSnapshots, AttemptGeneration, BudgetAccountId,
    CapacitySnapshotId, CommitResolution, GateRejection, GateScope, GateVerdict, GatewayPoolId,
    LifecycleMutation, PolicySnapshotId, ProjectedUsage, ProviderPoolId, ReclaimReport,
    RejectionReason, ReleaseReason, RenewalId, ReservationIdentity, ReservationLifecycle,
    ReservationPolicy, ReservationReceipt, ReservationRenewal, RetryAfterMs, TerminalOutcome,
};
pub use service::AdmissionService;
pub use store::{AdmissionAttempt, AdmissionStart, AdmissionStore};
