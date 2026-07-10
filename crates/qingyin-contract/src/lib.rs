//! DTO and fixture validation boundaries for QingYin public contracts.

use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize};

pub use qingyin_types::{AudioCodec, AudioContainer, AudioSpec};
use qingyin_types::{
    CanonicalError, DiagnosticId, ErrorCategory, ErrorCode, LeaseStatus, RequestId, SessionId,
    TimestampMs, TraceId,
};

/// Public transport mode selected for a leased session.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TransportMode {
    /// Direct connection through a controlled client SDK.
    DirectSdk,
    /// Session relayed through the QingYin gateway.
    Relay,
    /// Session relayed by an edge deployment.
    Edge,
    /// Session handled by a local worker.
    Local,
}

/// Session lease response matching the frozen control API v1 schema.
///
/// `C` remains transport-specific until M1-04 defines the short-lived ticket
/// representation. The lease deliberately has no `Debug` implementation so a
/// future secret-bearing connection value cannot enter logs by accident.
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionLease<C> {
    /// Public session identifier.
    pub session_id: SessionId,
    /// Initial public lease status.
    pub status: LeaseStatus,
    /// Public transport mode.
    pub transport_mode: TransportMode,
    /// Lease expiration timestamp.
    pub expires_at_ms: TimestampMs,
    /// Final negotiated input audio.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub accepted_audio: Option<AudioSpec>,
    /// Final negotiated output audio.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub accepted_output_audio: Option<AudioSpec>,
    /// Granted canonical capability names.
    pub capabilities: Vec<String>,
    /// Opaque, short-lived connection information.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub connect: Option<C>,
    /// Trace identifier for diagnostics.
    pub trace_id: TraceId,
}

impl<C> SessionLease<C> {
    /// Checks collection and nested audio bounds from the control API v1 schema.
    #[must_use]
    pub fn is_valid_for_v1(&self) -> bool {
        self.capabilities.len() <= 32
            && self
                .accepted_audio
                .is_none_or(|audio| audio.is_valid_for_v1())
            && self
                .accepted_output_audio
                .is_none_or(|audio| audio.is_valid_for_v1())
    }
}

/// Fixture envelope metadata required by the M1 contract suite.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
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
            && !self.category.is_empty()
    }
}

/// Public API error with an invariant category and required request correlation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ApiError {
    /// Stable canonical code.
    pub code: ErrorCode,
    category: ErrorCategory,
    /// Sanitized developer-facing message.
    pub message: String,
    /// Whether retry is safe for this occurrence.
    pub retryable: bool,
    /// Optional retry hint in milliseconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub retry_after_ms: Option<u64>,
    /// Optional reference to access-controlled diagnostic detail.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub diagnostic_id: Option<DiagnosticId>,
    /// Request identifier required by the public OpenAPI response.
    pub request_id: RequestId,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ApiErrorWire {
    code: ErrorCode,
    category: ErrorCategory,
    message: String,
    retryable: bool,
    retry_after_ms: Option<u64>,
    diagnostic_id: Option<DiagnosticId>,
    request_id: RequestId,
}

impl<'de> Deserialize<'de> for ApiError {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = ApiErrorWire::deserialize(deserializer)?;
        if wire.code.category() != wire.category {
            return Err(D::Error::custom(
                "API error category does not match its canonical code",
            ));
        }

        Ok(Self {
            code: wire.code,
            category: wire.category,
            message: wire.message,
            retryable: wire.retryable,
            retry_after_ms: wire.retry_after_ms,
            diagnostic_id: wire.diagnostic_id,
            request_id: wire.request_id,
        })
    }
}

impl ApiError {
    /// Attaches request correlation while deriving the category from the error code.
    #[must_use]
    pub fn from_canonical(error: CanonicalError, request_id: RequestId) -> Self {
        Self {
            code: error.code,
            category: error.category(),
            message: error.message,
            retryable: error.retryable,
            retry_after_ms: error.retry_after_ms,
            diagnostic_id: error.diagnostic_id,
            request_id,
        }
    }

    /// Returns the category fixed by the canonical error code.
    #[must_use]
    pub const fn category(&self) -> ErrorCategory {
        self.category
    }
}

/// Public error response wrapper.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ErrorResponse {
    /// Canonical sanitized API error.
    pub error: ApiError,
}

#[cfg(test)]
mod tests {
    use super::{
        ApiError, AudioCodec, AudioContainer, AudioSpec, FixtureEnvelope, SessionLease,
        TransportMode,
    };
    use qingyin_types::{
        CanonicalError, ErrorCategory, ErrorCode, LeaseStatus, RequestId, SessionId, TimestampMs,
        TraceId,
    };

    fn valid_audio_spec() -> AudioSpec {
        AudioSpec {
            codec: AudioCodec::PcmS16Le,
            container: Some(AudioContainer::Raw),
            sample_rate_hz: 16_000,
            channels: 1,
            frame_ms: Some(20),
        }
    }

    #[test]
    fn audio_spec_matches_frozen_openapi_bounds() {
        let valid = valid_audio_spec();
        assert!(valid.is_valid_for_v1());

        let invalid_frame = AudioSpec {
            frame_ms: Some(201),
            ..valid
        };
        assert!(!invalid_frame.is_valid_for_v1());

        let invalid_rate = AudioSpec {
            sample_rate_hz: 44_100,
            ..valid
        };
        assert!(!invalid_rate.is_valid_for_v1());
    }

    #[test]
    fn lease_enforces_capability_and_nested_audio_bounds() {
        let session_id = SessionId::new("ses_abc1");
        let trace_id = TraceId::new("trc_abc1");
        assert!(session_id.is_some());
        assert!(trace_id.is_some());

        if let (Some(session_id), Some(trace_id)) = (session_id, trace_id) {
            let lease = SessionLease::<()> {
                session_id,
                status: LeaseStatus::Leased,
                transport_mode: TransportMode::Relay,
                expires_at_ms: TimestampMs(1_700_000_000_000),
                accepted_audio: Some(valid_audio_spec()),
                accepted_output_audio: None,
                capabilities: vec!["asr.streaming".to_owned()],
                connect: None,
                trace_id,
            };
            assert!(lease.is_valid_for_v1());

            let too_many_capabilities = SessionLease {
                capabilities: vec!["capability".to_owned(); 33],
                ..lease
            };
            assert!(!too_many_capabilities.is_valid_for_v1());
        }
    }

    #[test]
    fn fixture_envelope_requires_synthetic_v1_metadata() {
        let envelope = FixtureEnvelope {
            fixture_id: "asr.ws.happy.v1".to_owned(),
            schema_version: "v1".to_owned(),
            category: "streaming".to_owned(),
            privacy_class: "synthetic".to_owned(),
        };
        assert!(envelope.is_m1_contract_fixture());
    }

    #[test]
    fn api_error_category_cannot_drift_from_its_code() {
        let request_id = RequestId::new("req_abc1");
        assert!(request_id.is_some());

        if let Some(request_id) = request_id {
            let error = ApiError::from_canonical(
                CanonicalError::new(ErrorCode::ProviderUnavailable, "provider unavailable"),
                request_id,
            );
            assert_eq!(error.category(), ErrorCategory::Upstream);
            assert!(error.retryable);
        }

        let inconsistent = r#"{
            "code": "provider_unavailable",
            "category": "auth",
            "message": "provider unavailable",
            "retryable": true,
            "request_id": "req_abc1"
        }"#;
        assert!(serde_json::from_str::<ApiError>(inconsistent).is_err());
    }
}
