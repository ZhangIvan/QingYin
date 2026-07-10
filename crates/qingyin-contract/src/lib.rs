//! DTO and fixture validation boundaries for `QingYin` public contracts.

use qingyin_types::{ApiError, ResourceId, SessionId, SessionStatus, TaskKind, TimestampMs};

/// Public transport mode selected for a leased session.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TransportMode {
    /// Session is relayed through `QingYin` Gateway.
    Relay,
    /// Direct SDK mode; reserved for post-M1 providers.
    DirectSdk,
    /// Local worker mode; reserved for post-M1 workers.
    Local,
    /// Edge relay mode; reserved for later deployments.
    Edge,
}

/// Minimal audio format negotiated at the public contract boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AudioSpec {
    /// Audio codec name from the capability snapshot.
    pub codec: String,
    /// Optional container name for stream or file responses.
    pub container: Option<String>,
    /// Sample rate in hertz.
    pub sample_rate_hz: u32,
    /// Channel count.
    pub channels: u8,
    /// Optional frame duration in milliseconds.
    pub frame_ms: Option<u16>,
}

impl AudioSpec {
    /// Validates the narrow M1 synthetic audio bounds used by fixtures.
    #[must_use]
    pub fn is_valid_for_m1(&self) -> bool {
        !self.codec.is_empty()
            && matches!(self.sample_rate_hz, 8_000 | 16_000 | 24_000 | 48_000)
            && matches!(self.channels, 1 | 2)
            && self
                .frame_ms
                .map_or(true, |frame_ms| (10..=60).contains(&frame_ms))
    }
}

/// Minimal session lease shape shared by early contract tests.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SessionLease {
    /// Public session identifier.
    pub session_id: SessionId,
    /// Initial public status.
    pub status: SessionStatus,
    /// Task granted by admission and routing.
    pub task: TaskKind,
    /// Public transport mode.
    pub transport_mode: TransportMode,
    /// Lease expiration timestamp.
    pub expires_at_ms: TimestampMs,
    /// Opaque single-use ticket; callers must treat it as secret.
    pub ticket: String,
    /// Trace identifier for diagnostics.
    pub trace_id: ResourceId,
}

/// Fixture envelope metadata required by the M1 contract suite.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FixtureEnvelope {
    /// Stable fixture identifier.
    pub fixture_id: String,
    /// Fixture schema version.
    pub schema_version: String,
    /// Fixture category.
    pub category: String,
    /// Fixture privacy class.
    pub privacy_class: String,
}

impl FixtureEnvelope {
    /// Returns whether the envelope metadata can enter the M1 fixture suite.
    #[must_use]
    pub fn is_m1_contract_fixture(&self) -> bool {
        self.schema_version == "v1"
            && self.privacy_class == "synthetic"
            && !self.fixture_id.is_empty()
    }
}

/// Public error response wrapper.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ErrorResponse {
    /// Canonical sanitized error.
    pub error: ApiError,
}

/// Redacts ticket-bearing DTOs for logs and assertion failures.
#[must_use]
pub fn redact_ticket(ticket: &str) -> &'static str {
    if ticket.is_empty() {
        "<empty>"
    } else {
        "<redacted>"
    }
}

#[cfg(test)]
mod tests {
    use super::{redact_ticket, AudioSpec, FixtureEnvelope};

    #[test]
    fn audio_spec_accepts_only_m1_synthetic_bounds() {
        let valid = AudioSpec {
            codec: "pcm_s16le".to_owned(),
            container: None,
            sample_rate_hz: 16_000,
            channels: 1,
            frame_ms: Some(20),
        };
        assert!(valid.is_valid_for_m1());

        let invalid = AudioSpec {
            sample_rate_hz: 44_100,
            ..valid
        };
        assert!(!invalid.is_valid_for_m1());
    }

    #[test]
    fn fixture_envelope_validates_required_metadata() {
        let envelope = FixtureEnvelope {
            fixture_id: "asr.ws.happy.v1".to_owned(),
            schema_version: "v1".to_owned(),
            category: "streaming".to_owned(),
            privacy_class: "synthetic".to_owned(),
        };
        assert!(envelope.is_m1_contract_fixture());
    }

    #[test]
    fn ticket_redaction_never_returns_input_secret() {
        assert_eq!(redact_ticket("ticket-secret"), "<redacted>");
        assert_eq!(redact_ticket(""), "<empty>");
    }
}
