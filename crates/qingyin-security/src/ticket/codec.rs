use std::fmt;

use hmac::{Hmac, Mac};
use sha2::Sha256;
use zeroize::Zeroizing;

use super::{TicketDigest, TicketSecret};
use crate::{SecurityError, SecurityResult};

const TICKET_BYTES: usize = 32;
const MIN_PEPPER_BYTES: usize = 32;
const MAX_PEPPER_BYTES: usize = 4 * 1024;

type HmacSha256 = Hmac<Sha256>;

/// Secret deployment pepper used to derive non-reversible ticket state keys.
pub struct TicketPepper(Zeroizing<Vec<u8>>);

impl TicketPepper {
    /// Creates a bounded pepper with at least 256 bits of entropy material.
    pub fn new(value: impl Into<Vec<u8>>) -> SecurityResult<Self> {
        let value = Zeroizing::new(value.into());
        if !(MIN_PEPPER_BYTES..=MAX_PEPPER_BYTES).contains(&value.len()) {
            return Err(SecurityError::InvalidArgument("ticket_pepper"));
        }
        Ok(Self(value))
    }

    fn expose(&self) -> &[u8] {
        self.0.as_slice()
    }
}

impl fmt::Debug for TicketPepper {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:ticket-pepper>")
    }
}

/// Cryptographically secure entropy source for ticket generation.
pub trait TicketEntropy: Send + Sync {
    /// Fills the complete destination or returns a sanitized failure.
    fn fill(&self, destination: &mut [u8]) -> SecurityResult<()>;
}

/// Operating-system cryptographic entropy source.
#[derive(Clone, Copy, Debug, Default)]
pub struct OsTicketEntropy;

impl TicketEntropy for OsTicketEntropy {
    fn fill(&self, destination: &mut [u8]) -> SecurityResult<()> {
        getrandom::fill(destination).map_err(|_| SecurityError::EntropyUnavailable)
    }
}

pub(crate) struct TicketCodec<R> {
    entropy: R,
    pepper: TicketPepper,
}

impl<R: TicketEntropy> TicketCodec<R> {
    pub(crate) const fn new(entropy: R, pepper: TicketPepper) -> Self {
        Self { entropy, pepper }
    }

    pub(crate) fn generate(&self) -> SecurityResult<TicketSecret> {
        let mut bytes = Zeroizing::new([0_u8; TICKET_BYTES]);
        self.entropy.fill(bytes.as_mut())?;
        TicketSecret::from_entropy(&bytes)
    }

    pub(crate) fn digest(&self, ticket: &TicketSecret) -> SecurityResult<TicketDigest> {
        let mut mac = <HmacSha256 as Mac>::new_from_slice(self.pepper.expose())
            .map_err(|_| SecurityError::InvalidArgument("ticket_pepper"))?;
        mac.update(ticket.expose_for_transport().as_bytes());
        let output = mac.finalize().into_bytes();
        let mut digest = [0_u8; 32];
        digest.copy_from_slice(&output);
        Ok(TicketDigest::new(digest))
    }
}
