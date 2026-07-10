//! Trace, metrics, health, and redaction helpers.

/// Redacts values that must never be written to logs or metrics.
#[must_use]
pub fn redact_secret(value: &str) -> &'static str {
    if value.is_empty() {
        "<empty>"
    } else {
        "<redacted>"
    }
}
