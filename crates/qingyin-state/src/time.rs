use std::time::Duration;

use crate::{StateError, StateResult};

/// Milliseconds from a store-owned monotonic epoch.
///
/// This value is intentionally unrelated to Unix time and must never be shown
/// to clients. It exists only for TTL, lease, and timeout decisions.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct MonotonicTime(u64);

impl MonotonicTime {
    /// Creates a monotonic timestamp from an implementation-owned millisecond counter.
    #[must_use]
    pub const fn from_millis(value: u64) -> Self {
        Self(value)
    }

    /// Returns the implementation-owned millisecond counter.
    #[must_use]
    pub const fn as_millis(self) -> u64 {
        self.0
    }

    /// Adds a bounded duration without wrapping the monotonic timeline.
    pub fn checked_add(self, duration: Duration) -> StateResult<Self> {
        let duration_ms = duration.as_millis();
        if !duration.is_zero() && duration_ms == 0 {
            return Err(StateError::InvalidArgument("duration"));
        }
        let delta =
            u64::try_from(duration_ms).map_err(|_| StateError::InvalidArgument("duration"))?;
        self.0
            .checked_add(delta)
            .map(Self)
            .ok_or(StateError::InvalidArgument("duration"))
    }
}

/// Source of server-side monotonic time for TTL and timeout decisions.
pub trait MonotonicClock: Send + Sync {
    /// Returns the current monotonic timestamp.
    fn now(&self) -> MonotonicTime;
}
