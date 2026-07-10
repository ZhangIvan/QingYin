//! Verified identity, authorization, session-ticket, and redaction boundaries.

mod error;
mod principal;
mod secret;
mod ticket;

pub use error::{SecurityError, SecurityResult};
pub use principal::{
    CredentialId, Principal, PrincipalDigest, PrincipalId, PrincipalKind, Role, Scope, ScopeSet,
    SecurityContext,
};
pub use secret::{RedactedValue, SecretString, SensitiveKind};
pub use ticket::{
    ClientBinding, ConsumedTicket, IssuedTicket, OsTicketEntropy, TicketBinding, TicketChannel,
    TicketDigest, TicketEntropy, TicketLifecycle, TicketPepper, TicketPolicy, TicketSecret,
    TicketService,
};
