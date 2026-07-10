use std::fmt;
use std::time::Duration;

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use qingyin_state::{MonotonicTime, TenantScope};
use qingyin_types::SessionId;
use serde::{Deserialize, Serialize};
use subtle::ConstantTimeEq;
use zeroize::Zeroizing;

use crate::{PrincipalDigest, Scope, SecretString, SecurityContext, SecurityError, SecurityResult};

const TICKET_ENTROPY_BYTES: usize = 32;
const MIN_TICKET_TTL: Duration = Duration::from_secs(1);
const MAX_TICKET_TTL: Duration = Duration::from_secs(5 * 60);

/// Data-plane channel authorized by a short-lived ticket.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TicketChannel {
    /// ASR WebSocket relay.
    AsrWebSocket,
    /// TTS WebSocket relay.
    TtsWebSocket,
    /// Realtime orchestration WebSocket.
    RealtimeWebSocket,
    /// One-shot TTS HTTP byte stream.
    TtsHttpStream,
}

/// Observable lifecycle around the atomic state transition.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TicketLifecycle {
    /// A live TTL record exists and can be consumed once.
    Unused,
    /// The live record was removed by a successful atomic consume.
    Consumed,
}

/// Optional irreversible browser/device/origin binding digest.
#[derive(Clone, Copy, Eq, PartialEq)]
pub struct ClientBinding([u8; 32]);

impl ClientBinding {
    /// Creates a digest produced by a trusted client-binding policy.
    #[must_use]
    pub const fn new(value: [u8; 32]) -> Self {
        Self(value)
    }

    pub(crate) fn encode(self) -> String {
        URL_SAFE_NO_PAD.encode(self.0)
    }

    pub(crate) fn from_encoded(value: &str) -> SecurityResult<Self> {
        let decoded = URL_SAFE_NO_PAD
            .decode(value)
            .map_err(|_| SecurityError::EncodingFailure)?;
        let bytes = <[u8; 32]>::try_from(decoded).map_err(|_| SecurityError::EncodingFailure)?;
        Ok(Self(bytes))
    }

    pub(crate) fn constant_time_eq(self, other: Self) -> bool {
        bool::from(self.0.ct_eq(&other.0))
    }
}

impl fmt::Debug for ClientBinding {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:client-binding>")
    }
}

/// HMAC digest used as the state key for one raw ticket.
#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct TicketDigest([u8; 32]);

impl TicketDigest {
    pub(crate) const fn new(value: [u8; 32]) -> Self {
        Self(value)
    }

    pub(crate) fn storage_key(self) -> String {
        URL_SAFE_NO_PAD.encode(self.0)
    }
}

impl fmt::Debug for TicketDigest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:ticket-digest>")
    }
}

/// Raw single-use ticket. The value zeroizes on drop and has no raw formatter.
pub struct TicketSecret(SecretString);

impl TicketSecret {
    /// Parses one canonical 256-bit base64url ticket received from transport.
    pub fn from_transport(value: impl Into<String>) -> SecurityResult<Self> {
        let value = Zeroizing::new(value.into());
        let decoded = Zeroizing::new(
            URL_SAFE_NO_PAD
                .decode(value.as_bytes())
                .map_err(|_| SecurityError::TicketRejected)?,
        );
        if decoded.len() != TICKET_ENTROPY_BYTES {
            return Err(SecurityError::TicketRejected);
        }
        let canonical = Zeroizing::new(URL_SAFE_NO_PAD.encode(decoded.as_slice()));
        if canonical.as_str() != value.as_str() {
            return Err(SecurityError::TicketRejected);
        }
        Ok(Self(SecretString::from_zeroizing(value)?))
    }

    pub(crate) fn from_entropy(value: &[u8; TICKET_ENTROPY_BYTES]) -> SecurityResult<Self> {
        Self::from_transport(URL_SAFE_NO_PAD.encode(value))
    }

    /// Exposes the ticket only for an explicit response or cryptographic operation.
    #[must_use]
    pub fn expose_for_transport(&self) -> &str {
        self.0.expose_secret()
    }
}

impl fmt::Debug for TicketSecret {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:session-ticket>")
    }
}

/// Exact authorization metadata bound to one session ticket.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TicketBinding {
    tenant_scope: TenantScope,
    session_id: SessionId,
    principal_digest: PrincipalDigest,
    channel: TicketChannel,
    client_binding: Option<ClientBinding>,
}

impl TicketBinding {
    /// Creates a binding from an authorized context and exact target tenant.
    pub fn for_context(
        context: &SecurityContext,
        target_scope: &TenantScope,
        session_id: SessionId,
        channel: TicketChannel,
        client_binding: Option<ClientBinding>,
    ) -> SecurityResult<Self> {
        context.authorize_resource(target_scope, Scope::StreamConnect)?;
        Ok(Self {
            tenant_scope: target_scope.clone(),
            session_id,
            principal_digest: context.principal().digest(),
            channel,
            client_binding,
        })
    }

    /// Returns the trusted tenant ownership chain.
    #[must_use]
    pub const fn tenant_scope(&self) -> &TenantScope {
        &self.tenant_scope
    }

    /// Returns the authorized session identifier.
    #[must_use]
    pub const fn session_id(&self) -> &SessionId {
        &self.session_id
    }

    /// Returns the irreversible principal binding digest.
    #[must_use]
    pub const fn principal_digest(&self) -> PrincipalDigest {
        self.principal_digest
    }

    /// Returns the authorized data-plane channel.
    #[must_use]
    pub const fn channel(&self) -> TicketChannel {
        self.channel
    }

    /// Returns the optional irreversible client binding.
    #[must_use]
    pub const fn client_binding(&self) -> Option<ClientBinding> {
        self.client_binding
    }
}

/// Fixed service-side ticket lifetime policy.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TicketPolicy {
    ttl: Duration,
}

impl TicketPolicy {
    /// Creates a whole-millisecond lifetime between one second and five minutes.
    pub fn new(ttl: Duration) -> SecurityResult<Self> {
        if !(MIN_TICKET_TTL..=MAX_TICKET_TTL).contains(&ttl) || ttl.subsec_nanos() % 1_000_000 != 0
        {
            return Err(SecurityError::InvalidArgument("ticket_ttl"));
        }
        Ok(Self { ttl })
    }

    /// Returns the fixed ticket lifetime used by the issuer.
    #[must_use]
    pub const fn ttl(self) -> Duration {
        self.ttl
    }
}

/// Newly issued raw ticket and safe metadata.
pub struct IssuedTicket {
    pub(crate) secret: TicketSecret,
    pub(crate) digest: TicketDigest,
    pub(crate) ttl: Duration,
    pub(crate) issued_at: MonotonicTime,
    pub(crate) expires_at: MonotonicTime,
}

impl IssuedTicket {
    /// Returns the raw ticket for an explicit response boundary.
    #[must_use]
    pub const fn secret(&self) -> &TicketSecret {
        &self.secret
    }

    /// Consumes the wrapper and returns the zeroizing raw ticket.
    #[must_use]
    pub fn into_secret(self) -> TicketSecret {
        self.secret
    }

    /// Returns the safe HMAC digest used for revocation.
    #[must_use]
    pub const fn digest(&self) -> TicketDigest {
        self.digest
    }

    /// Returns the configured ticket lifetime.
    #[must_use]
    pub const fn ttl(&self) -> Duration {
        self.ttl
    }

    /// Returns the store-owned monotonic time at which the TTL began.
    #[must_use]
    pub const fn issued_at(&self) -> MonotonicTime {
        self.issued_at
    }

    /// Returns the authoritative store-owned monotonic expiry boundary.
    #[must_use]
    pub const fn expires_at(&self) -> MonotonicTime {
        self.expires_at
    }

    /// Returns the lifecycle represented by the live state record.
    #[must_use]
    pub const fn lifecycle(&self) -> TicketLifecycle {
        TicketLifecycle::Unused
    }
}

impl fmt::Debug for IssuedTicket {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("IssuedTicket")
            .field("secret", &self.secret)
            .field("digest", &self.digest)
            .field("ttl", &self.ttl)
            .field("issued_at", &self.issued_at)
            .field("expires_at", &self.expires_at)
            .field("lifecycle", &self.lifecycle())
            .finish()
    }
}

/// Binding and authoritative monotonic expiry returned by successful consume.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConsumedTicket {
    pub(crate) binding: TicketBinding,
    pub(crate) expires_at: MonotonicTime,
}

impl ConsumedTicket {
    /// Returns the consumed authorization binding.
    #[must_use]
    pub const fn binding(&self) -> &TicketBinding {
        &self.binding
    }

    /// Returns the state-store monotonic expiry boundary.
    #[must_use]
    pub const fn expires_at(&self) -> MonotonicTime {
        self.expires_at
    }

    /// Returns the lifecycle reached by the successful atomic take.
    #[must_use]
    pub const fn lifecycle(&self) -> TicketLifecycle {
        TicketLifecycle::Consumed
    }
}
