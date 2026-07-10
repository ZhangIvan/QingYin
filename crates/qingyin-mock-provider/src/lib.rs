//! Scripted `MockProvider` profiles used by contract and unit tests.

/// M1-required scripted mock profiles.
pub const MOCK_PROFILES: &[&str] = &[
    "happy",
    "slow_first",
    "create_reject",
    "fail_midstream",
    "hang_until_cancel",
    "quota_exhausted",
    "protocol_violation",
];
