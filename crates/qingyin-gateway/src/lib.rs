//! Gateway composition boundary for HTTP, WebSocket, admission, state, and provider orchestration.

/// Returns the supported public API major version for the M1 bootstrap.
#[must_use]
pub const fn api_major_version() -> u8 {
    1
}
