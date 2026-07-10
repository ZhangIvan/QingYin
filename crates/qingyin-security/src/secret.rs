use std::fmt;

use zeroize::Zeroizing;

use crate::{SecurityError, SecurityResult};

const MAX_SECRET_STRING_BYTES: usize = 16 * 1024;

/// Zeroizing secret text with no raw `Debug` or `Display` representation.
pub struct SecretString(Zeroizing<String>);

impl SecretString {
    /// Creates a non-empty bounded secret string.
    pub fn new(value: impl Into<String>) -> SecurityResult<Self> {
        Self::from_zeroizing(Zeroizing::new(value.into()))
    }

    pub(crate) fn from_zeroizing(value: Zeroizing<String>) -> SecurityResult<Self> {
        if value.is_empty() || value.len() > MAX_SECRET_STRING_BYTES {
            return Err(SecurityError::InvalidArgument("secret"));
        }
        Ok(Self(value))
    }

    /// Exposes the raw value only at an explicit transport or cryptographic boundary.
    #[must_use]
    pub fn expose_secret(&self) -> &str {
        self.0.as_str()
    }
}

impl fmt::Debug for SecretString {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:secret>")
    }
}

/// Classification used by structured redaction adapters.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensitiveKind {
    /// HTTP Authorization header or equivalent bearer credential.
    Authorization,
    /// QingYin project API key or service-account credential.
    ProjectCredential,
    /// Short-lived QingYin session ticket.
    SessionTicket,
    /// Cloud Provider or local worker credential/token.
    ProviderToken,
    /// Reference to a secret managed outside process configuration.
    SecretReference,
    /// Other explicitly classified secret data.
    Generic,
}

impl SensitiveKind {
    const fn label(self) -> &'static str {
        match self {
            Self::Authorization => "authorization",
            Self::ProjectCredential => "project-credential",
            Self::SessionTicket => "session-ticket",
            Self::ProviderToken => "provider-token",
            Self::SecretReference => "secret-reference",
            Self::Generic => "secret",
        }
    }
}

/// Fixed redaction marker that records classification and presence, never input.
#[derive(Clone, Copy, Eq, PartialEq)]
pub struct RedactedValue {
    kind: SensitiveKind,
    present: bool,
}

impl RedactedValue {
    /// Creates a marker while deliberately discarding the supplied value.
    #[must_use]
    pub fn new(kind: SensitiveKind, value: &str) -> Self {
        Self {
            kind,
            present: !value.is_empty(),
        }
    }

    /// Returns whether an input was present without exposing its length or content.
    #[must_use]
    pub const fn is_present(self) -> bool {
        self.present
    }

    /// Returns the secret classification.
    #[must_use]
    pub const fn kind(self) -> SensitiveKind {
        self.kind
    }
}

impl fmt::Display for RedactedValue {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = if self.present { "redacted" } else { "empty" };
        write!(formatter, "<{state}:{}>", self.kind.label())
    }
}

impl fmt::Debug for RedactedValue {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, formatter)
    }
}

#[cfg(test)]
mod tests {
    use super::{RedactedValue, SecretString, SensitiveKind};
    use crate::SecurityResult;

    #[test]
    fn secret_and_redacted_formatting_never_contains_input() -> SecurityResult<()> {
        let raw = "project-secret-value";
        let secret = SecretString::new(raw)?;
        let secret_debug = format!("{secret:?}");
        assert!(!secret_debug.contains(raw));
        assert_eq!(secret_debug, "<redacted:secret>");

        let marker = RedactedValue::new(SensitiveKind::Authorization, raw);
        let display = marker.to_string();
        let debug = format!("{marker:?}");
        assert!(!display.contains(raw));
        assert!(!debug.contains(raw));
        assert_eq!(display, "<redacted:authorization>");
        assert_eq!(debug, display);
        Ok(())
    }

    #[test]
    fn empty_marker_reveals_no_length_or_content() {
        let marker = RedactedValue::new(SensitiveKind::SessionTicket, "");
        assert!(!marker.is_present());
        assert_eq!(marker.to_string(), "<empty:session-ticket>");
    }
}
