//! Observability boundary adapters shared by logs, traces, metrics, and audit events.
//!
//! This crate accepts already-classified values and converts them into safe
//! representations before an observability backend can format or export them.

pub use qingyin_security::{RedactedValue, SensitiveKind};

/// Discards a sensitive source value and returns a fixed safe representation.
///
/// Callers must classify the value at the source boundary. The returned value
/// cannot expose the original text through `Display` or `Debug`.
#[must_use]
pub fn redact_sensitive(kind: SensitiveKind, value: &str) -> RedactedValue {
    RedactedValue::new(kind, value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use qingyin_security::SecurityError;

    #[test]
    fn observability_adapter_never_formats_the_source_value() {
        let raw = "synthetic-project-credential";
        let redacted = redact_sensitive(SensitiveKind::ProjectCredential, raw);

        assert!(!format!("{redacted}").contains(raw));
        assert!(!format!("{redacted:?}").contains(raw));
        assert_eq!(redacted.kind(), SensitiveKind::ProjectCredential);
    }

    #[test]
    fn nested_security_fields_redact_every_supported_secret_class() {
        let values = [
            (
                SensitiveKind::Authorization,
                ["Bearer", "synthetic.authorization.value"].join(" "),
            ),
            (
                SensitiveKind::ProjectCredential,
                ["qy", "live", "synthetic_project_credential"].join("_"),
            ),
            (
                SensitiveKind::SessionTicket,
                ["ws", "ticket", "synthetic_session_value"].join("_"),
            ),
            (
                SensitiveKind::ProviderToken,
                ["provider", "token", "synthetic_vendor_value"].join("_"),
            ),
            (
                SensitiveKind::SecretReference,
                ["secret", "ref", "synthetic_reference"].join(":"),
            ),
        ];
        let redacted = values
            .iter()
            .map(|(kind, value)| redact_sensitive(*kind, value))
            .collect::<Vec<_>>();
        let nested = format!(
            "{:?}",
            (
                redacted,
                vec![
                    SecurityError::CredentialRejected,
                    SecurityError::TicketRejected,
                    SecurityError::StateUnavailable,
                ],
            )
        );

        for (_, value) in values {
            assert!(!nested.contains(&value));
        }
    }
}
