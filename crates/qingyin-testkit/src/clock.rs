use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use qingyin_state::{MonotonicClock, MonotonicTime, StateResult};

/// Deterministic monotonic clock advanced explicitly by tests.
#[derive(Clone, Debug)]
pub struct VirtualClock {
    now: Arc<Mutex<MonotonicTime>>,
}

impl VirtualClock {
    /// Creates a virtual clock at the specified monotonic timestamp.
    #[must_use]
    pub fn new(start: MonotonicTime) -> Self {
        Self {
            now: Arc::new(Mutex::new(start)),
        }
    }

    /// Advances time without sleeping and returns the new timestamp.
    pub fn advance(&self, duration: Duration) -> StateResult<MonotonicTime> {
        let mut now = self.lock();
        *now = now.checked_add(duration)?;
        Ok(*now)
    }

    fn lock(&self) -> MutexGuard<'_, MonotonicTime> {
        match self.now.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }
}

impl Default for VirtualClock {
    fn default() -> Self {
        Self::new(MonotonicTime::from_millis(0))
    }
}

impl MonotonicClock for VirtualClock {
    fn now(&self) -> MonotonicTime {
        *self.lock()
    }
}
