//! Durable and ephemeral state abstractions for sessions, reservations, and outbox records.

use qingyin_types::{SessionId, SessionStatus};

/// Repository boundary for session state transitions.
pub trait SessionRepository {
    /// Persists a new status for a session.
    fn set_status(&mut self, session_id: &SessionId, status: SessionStatus);
}
