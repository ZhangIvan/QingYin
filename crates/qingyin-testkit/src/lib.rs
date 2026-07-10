//! Deterministic test implementations shared across QingYin crates.
//!
//! Test doubles are deliberately kept outside production crates. They use no
//! network, wall-clock sleeps, database process, or runtime-global state.

mod clock;
mod durable;
mod ttl;

pub use clock::VirtualClock;
pub use durable::InMemoryStateStore;
pub use ttl::InMemoryTtlStore;

/// Fixture schema version supported by the M1 testkit.
pub const FIXTURE_SCHEMA_VERSION: &str = qingyin_types::SCHEMA_VERSION_V1;
