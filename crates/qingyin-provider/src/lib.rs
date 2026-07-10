//! Provider-facing traits and canonical capability boundaries.

use qingyin_types::TaskKind;

/// Canonical capability advertised by an adapter through the registry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderCapability {
    /// Stable provider capability name, never a secret or URL.
    pub name: &'static str,
    /// Task supported by this capability.
    pub task: TaskKind,
}

/// Minimal provider contract used by the M1 workspace bootstrap.
pub trait Provider {
    /// Returns the canonical capabilities for this provider.
    fn capabilities(&self) -> &[ProviderCapability];
}
