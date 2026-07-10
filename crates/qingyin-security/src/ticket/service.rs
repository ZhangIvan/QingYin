use qingyin_state::{
    MonotonicTime, MutationOutcome, StateError, TenantScope, TtlKey, TtlPutResult, TtlStore,
    TtlTakeResult, TtlValue,
};
use serde::{Deserialize, Serialize};

use super::codec::TicketCodec;
use super::{
    ClientBinding, ConsumedTicket, IssuedTicket, TicketBinding, TicketChannel, TicketDigest,
    TicketEntropy, TicketLifecycle, TicketPepper, TicketPolicy, TicketSecret,
};
use crate::{PrincipalDigest, SecurityError, SecurityResult};

const STORED_TICKET_VERSION: u8 = 1;
const MAX_TICKET_GENERATION_ATTEMPTS: usize = 4;
const TICKET_NAMESPACE: &str = "session_ticket";

/// Ticket issuer and atomic consumer backed by a tenant-scoped TTL store.
pub struct TicketService<S, R> {
    store: S,
    codec: TicketCodec<R>,
    policy: TicketPolicy,
}

impl<S, R> TicketService<S, R>
where
    S: TtlStore,
    R: TicketEntropy,
{
    /// Creates a ticket service with fixed entropy, pepper, and TTL policy.
    #[must_use]
    pub const fn new(store: S, entropy: R, pepper: TicketPepper, policy: TicketPolicy) -> Self {
        Self {
            store,
            codec: TicketCodec::new(entropy, pepper),
            policy,
        }
    }

    /// Issues one ticket whose raw value is never written to state.
    pub async fn issue(&self, binding: &TicketBinding) -> SecurityResult<IssuedTicket> {
        let stored = StoredTicket::from_binding(binding);
        let encoded = stored.encode()?;

        for _ in 0..MAX_TICKET_GENERATION_ATTEMPTS {
            let secret = self.codec.generate()?;
            let digest = self.codec.digest(&secret)?;
            let key = ttl_key(digest)?;
            let value = TtlValue::new(encoded.clone()).map_err(map_state_error)?;
            match self
                .store
                .put_if_absent(binding.tenant_scope(), &key, value, self.policy.ttl())
                .await
                .map_err(map_state_error)?
            {
                TtlPutResult::Inserted(revision) => {
                    // Use the store-owned expiry; a process clock could overstate validity.
                    let entry = self
                        .store
                        .get(binding.tenant_scope(), &key)
                        .await
                        .map_err(map_state_error)?
                        .ok_or(SecurityError::StateUnavailable)?;
                    if entry.revision() != revision {
                        return Err(SecurityError::StateUnavailable);
                    }
                    let ttl_millis = u64::try_from(self.policy.ttl().as_millis())
                        .map_err(|_| SecurityError::InvalidArgument("ticket_ttl"))?;
                    let issued_at = entry
                        .expires_at()
                        .as_millis()
                        .checked_sub(ttl_millis)
                        .map(MonotonicTime::from_millis)
                        .ok_or(SecurityError::StateUnavailable)?;
                    return Ok(IssuedTicket {
                        secret,
                        digest,
                        ttl: self.policy.ttl(),
                        issued_at,
                        expires_at: entry.expires_at(),
                    });
                }
                TtlPutResult::Existing(_) => {}
            }
        }

        Err(SecurityError::TicketCollision)
    }

    /// Atomically consumes one correctly bound live ticket.
    ///
    /// All invalid, expired, revoked, replayed, and binding-mismatch paths use
    /// the same public error so callers cannot probe ticket existence.
    pub async fn consume(
        &self,
        ticket: &TicketSecret,
        expected: &TicketBinding,
    ) -> SecurityResult<ConsumedTicket> {
        let digest = self.codec.digest(ticket)?;
        let key = ttl_key(digest)?;
        let entry = self
            .store
            .get(expected.tenant_scope(), &key)
            .await
            .map_err(map_state_error)?
            .ok_or(SecurityError::TicketRejected)?;
        let stored = StoredTicket::decode(entry.value().as_bytes())?;
        if !stored.matches(expected) {
            return Err(SecurityError::TicketRejected);
        }

        match self
            .store
            .compare_and_take(expected.tenant_scope(), &key, entry.revision())
            .await
            .map_err(map_state_error)?
        {
            TtlTakeResult::Taken(value) => {
                let consumed = StoredTicket::decode(value.as_bytes())?;
                if !consumed.matches(expected) {
                    return Err(SecurityError::TicketRejected);
                }
                Ok(ConsumedTicket {
                    binding: expected.clone(),
                    expires_at: entry.expires_at(),
                })
            }
            TtlTakeResult::Missing | TtlTakeResult::RevisionMismatch { .. } => {
                Err(SecurityError::TicketRejected)
            }
        }
    }

    /// Revokes a ticket by safe digest without requiring its raw value.
    pub async fn revoke(&self, scope: &TenantScope, digest: TicketDigest) -> SecurityResult<bool> {
        let key = ttl_key(digest)?;
        let outcome = self
            .store
            .remove(scope, &key)
            .await
            .map_err(map_state_error)?;
        Ok(outcome == MutationOutcome::Applied)
    }

    /// Derives the safe revocation digest for a parsed raw ticket.
    pub fn digest(&self, ticket: &TicketSecret) -> SecurityResult<TicketDigest> {
        self.codec.digest(ticket)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredTicket {
    version: u8,
    lifecycle: TicketLifecycle,
    organization_id: String,
    workspace_id: String,
    project_id: String,
    environment_id: String,
    session_id: String,
    principal_digest: String,
    channel: TicketChannel,
    client_binding: Option<String>,
}

impl StoredTicket {
    fn from_binding(binding: &TicketBinding) -> Self {
        let scope = binding.tenant_scope();
        Self {
            version: STORED_TICKET_VERSION,
            lifecycle: TicketLifecycle::Unused,
            organization_id: scope.organization_id().as_resource_id().as_str().to_owned(),
            workspace_id: scope.workspace_id().as_resource_id().as_str().to_owned(),
            project_id: scope.project_id().as_resource_id().as_str().to_owned(),
            environment_id: scope.environment_id().as_resource_id().as_str().to_owned(),
            session_id: binding.session_id().as_str().to_owned(),
            principal_digest: binding.principal_digest().encode(),
            channel: binding.channel(),
            client_binding: binding.client_binding().map(ClientBinding::encode),
        }
    }

    fn encode(&self) -> SecurityResult<Vec<u8>> {
        serde_json::to_vec(self).map_err(|_| SecurityError::EncodingFailure)
    }

    fn decode(value: &[u8]) -> SecurityResult<Self> {
        let stored: Self =
            serde_json::from_slice(value).map_err(|_| SecurityError::EncodingFailure)?;
        if stored.version != STORED_TICKET_VERSION {
            return Err(SecurityError::EncodingFailure);
        }
        Ok(stored)
    }

    fn matches(&self, expected: &TicketBinding) -> bool {
        let scope = expected.tenant_scope();
        if self.lifecycle != TicketLifecycle::Unused
            || self.organization_id != scope.organization_id().as_resource_id().as_str()
            || self.workspace_id != scope.workspace_id().as_resource_id().as_str()
            || self.project_id != scope.project_id().as_resource_id().as_str()
            || self.environment_id != scope.environment_id().as_resource_id().as_str()
            || self.session_id != expected.session_id().as_str()
            || self.channel != expected.channel()
        {
            return false;
        }

        let Ok(stored_principal) = PrincipalDigest::from_encoded(&self.principal_digest) else {
            return false;
        };
        if !stored_principal.constant_time_eq(expected.principal_digest()) {
            return false;
        }

        match (&self.client_binding, expected.client_binding()) {
            (None, None) => true,
            (Some(stored), Some(expected)) => ClientBinding::from_encoded(stored)
                .is_ok_and(|decoded| decoded.constant_time_eq(expected)),
            (None, Some(_)) | (Some(_), None) => false,
        }
    }
}

fn ttl_key(digest: TicketDigest) -> SecurityResult<TtlKey> {
    TtlKey::new(TICKET_NAMESPACE, digest.storage_key()).map_err(map_state_error)
}

fn map_state_error(error: StateError) -> SecurityError {
    match error {
        StateError::InvalidArgument(_) => SecurityError::EncodingFailure,
        StateError::Conflict(_)
        | StateError::NotFound(_)
        | StateError::InvalidTransition { .. }
        | StateError::TransactionFinalized
        | StateError::StoreUnavailable => SecurityError::StateUnavailable,
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::{Arc, Barrier, mpsc};
    use std::thread;
    use std::time::Duration;

    use futures_executor::block_on;
    use qingyin_state::{
        EnvironmentId, MonotonicTime, OrganizationId, ProjectId, TenantScope, TtlStore, WorkspaceId,
    };
    use qingyin_testkit::{InMemoryTtlStore, VirtualClock};
    use qingyin_types::{ResourceId, SessionId};

    use super::*;
    use crate::{
        CredentialId, Principal, PrincipalDigest, PrincipalId, PrincipalKind, Role, Scope,
        ScopeSet, SecurityContext,
    };

    #[derive(Default)]
    struct DeterministicEntropy {
        sequence: AtomicU64,
    }

    impl TicketEntropy for DeterministicEntropy {
        fn fill(&self, destination: &mut [u8]) -> SecurityResult<()> {
            let sequence = self.sequence.fetch_add(1, Ordering::Relaxed) + 1;
            for (index, byte) in destination.iter_mut().enumerate() {
                let offset = u64::try_from(index).map_err(|_| SecurityError::EntropyUnavailable)?;
                *byte = sequence.wrapping_add(offset).to_le_bytes()[0];
            }
            Ok(())
        }
    }

    fn resource_id(value: &str) -> SecurityResult<ResourceId> {
        ResourceId::new(value).ok_or(SecurityError::InvalidArgument("test_resource_id"))
    }

    fn session_id(value: &str) -> SecurityResult<SessionId> {
        SessionId::new(value).ok_or(SecurityError::InvalidArgument("test_session_id"))
    }

    fn tenant(suffix: &str) -> SecurityResult<TenantScope> {
        Ok(TenantScope::new(
            OrganizationId::new(resource_id(&format!("org_{suffix}001"))?),
            WorkspaceId::new(resource_id(&format!("wsp_{suffix}001"))?),
            ProjectId::new(resource_id(&format!("prj_{suffix}001"))?),
            EnvironmentId::new(resource_id(&format!("env_{suffix}001"))?),
        ))
    }

    fn context(digest: u8, tenant_scope: TenantScope) -> SecurityResult<SecurityContext> {
        Ok(SecurityContext::from_verified_principal(
            Principal::from_verified(
                PrincipalId::new(resource_id("prn_test001")?),
                Some(CredentialId::new(resource_id("crd_test001")?)),
                PrincipalKind::ProjectCredential,
                Role::Developer,
                tenant_scope,
                ScopeSet::new([Scope::StreamConnect]),
                PrincipalDigest::new([digest; 32]),
            ),
        ))
    }

    fn binding(
        context: &SecurityContext,
        session: &str,
        channel: TicketChannel,
        client: Option<ClientBinding>,
    ) -> SecurityResult<TicketBinding> {
        TicketBinding::for_context(
            context,
            context.principal().tenant_scope(),
            session_id(session)?,
            channel,
            client,
        )
    }

    fn service(
        store: InMemoryTtlStore,
    ) -> SecurityResult<TicketService<InMemoryTtlStore, DeterministicEntropy>> {
        Ok(TicketService::new(
            store,
            DeterministicEntropy::default(),
            TicketPepper::new(vec![9; 32])?,
            TicketPolicy::new(Duration::from_secs(30))?,
        ))
    }

    #[test]
    fn state_contains_binding_metadata_but_never_raw_ticket() -> SecurityResult<()> {
        block_on(async {
            let clock = VirtualClock::new(MonotonicTime::from_millis(1_000));
            let store = InMemoryTtlStore::new(clock);
            let service = service(store.clone())?;
            let context = context(7, tenant("a")?)?;
            let binding = binding(
                &context,
                "ses_store01",
                TicketChannel::AsrWebSocket,
                Some(ClientBinding::new([3; 32])),
            )?;
            let issued = service.issue(&binding).await?;
            let raw = issued.secret().expose_for_transport();
            let key = ttl_key(issued.digest())?;
            let entry = store
                .get(binding.tenant_scope(), &key)
                .await
                .map_err(map_state_error)?
                .ok_or(SecurityError::TicketRejected)?;
            let stored = String::from_utf8_lossy(entry.value().as_bytes());
            assert!(!stored.contains(raw));
            assert!(stored.contains(binding.session_id().as_str()));
            assert!(!issued.digest().storage_key().contains(raw));
            assert_eq!(issued.issued_at(), MonotonicTime::from_millis(1_000));
            assert_eq!(issued.expires_at(), MonotonicTime::from_millis(31_000));
            assert_eq!(issued.lifecycle(), TicketLifecycle::Unused);
            let debug = format!("{issued:?}");
            assert!(!debug.contains(raw));
            Ok(())
        })
    }

    #[test]
    fn wrong_binding_does_not_consume_then_correct_binding_wins() -> SecurityResult<()> {
        block_on(async {
            let store = InMemoryTtlStore::default();
            let service = service(store)?;
            let correct_context = context(7, tenant("a")?)?;
            let correct = binding(
                &correct_context,
                "ses_bound01",
                TicketChannel::AsrWebSocket,
                Some(ClientBinding::new([3; 32])),
            )?;
            let wrong_channel = binding(
                &correct_context,
                "ses_bound01",
                TicketChannel::TtsWebSocket,
                Some(ClientBinding::new([3; 32])),
            )?;
            let other_tenant_context = context(7, tenant("b")?)?;
            let wrong_tenant = binding(
                &other_tenant_context,
                "ses_bound01",
                TicketChannel::AsrWebSocket,
                Some(ClientBinding::new([3; 32])),
            )?;
            let issued = service.issue(&correct).await?;
            assert_eq!(
                service.consume(issued.secret(), &wrong_channel).await,
                Err(SecurityError::TicketRejected)
            );
            assert_eq!(
                service.consume(issued.secret(), &wrong_tenant).await,
                Err(SecurityError::TicketRejected)
            );
            let consumed = service.consume(issued.secret(), &correct).await?;
            assert_eq!(consumed.binding(), &correct);
            assert_eq!(consumed.expires_at(), issued.expires_at());
            assert_eq!(consumed.lifecycle(), TicketLifecycle::Consumed);
            assert_eq!(
                service.consume(issued.secret(), &correct).await,
                Err(SecurityError::TicketRejected)
            );
            Ok(())
        })
    }

    #[test]
    fn expired_and_revoked_tickets_share_non_oracular_failure() -> SecurityResult<()> {
        block_on(async {
            let clock = VirtualClock::new(MonotonicTime::from_millis(0));
            let store = InMemoryTtlStore::new(clock.clone());
            let service = service(store)?;
            let context = context(7, tenant("a")?)?;
            let binding = binding(&context, "ses_expire1", TicketChannel::AsrWebSocket, None)?;
            let expired = service.issue(&binding).await?;
            clock
                .advance(Duration::from_secs(30))
                .map_err(map_state_error)?;
            assert_eq!(
                service.consume(expired.secret(), &binding).await,
                Err(SecurityError::TicketRejected)
            );

            let revoked = service.issue(&binding).await?;
            assert!(
                service
                    .revoke(binding.tenant_scope(), revoked.digest())
                    .await?
            );
            assert_eq!(
                service.consume(revoked.secret(), &binding).await,
                Err(SecurityError::TicketRejected)
            );
            assert!(
                !service
                    .revoke(binding.tenant_scope(), revoked.digest())
                    .await?
            );
            Ok(())
        })
    }

    #[test]
    fn concurrent_ticket_consumption_has_exactly_one_success() -> SecurityResult<()> {
        let store = InMemoryTtlStore::default();
        let service = Arc::new(service(store)?);
        let context = context(7, tenant("a")?)?;
        let binding = binding(&context, "ses_race001", TicketChannel::AsrWebSocket, None)?;
        let issued = block_on(service.issue(&binding))?;
        let first_ticket = TicketSecret::from_transport(issued.secret().expose_for_transport())?;
        let second_ticket = TicketSecret::from_transport(issued.secret().expose_for_transport())?;
        drop(issued);
        let barrier = Arc::new(Barrier::new(2));
        let (sender, receiver) = mpsc::channel();
        let mut handles = Vec::with_capacity(2);

        for ticket in [first_ticket, second_ticket] {
            let worker_service = Arc::clone(&service);
            let worker_binding = binding.clone();
            let worker_barrier = Arc::clone(&barrier);
            let worker_sender = sender.clone();
            handles.push(thread::spawn(move || {
                let _wait = worker_barrier.wait();
                let result = block_on(worker_service.consume(&ticket, &worker_binding));
                drop(worker_sender.send(result));
            }));
        }
        drop(sender);

        let mut success_count = 0;
        let mut rejected_count = 0;
        for _ in 0..2 {
            match receiver
                .recv()
                .map_err(|_| SecurityError::StateUnavailable)?
            {
                Ok(_) => success_count += 1,
                Err(SecurityError::TicketRejected) => rejected_count += 1,
                Err(error) => return Err(error),
            }
        }
        for handle in handles {
            if handle.join().is_err() {
                return Err(SecurityError::StateUnavailable);
            }
        }
        assert_eq!(success_count, 1);
        assert_eq!(rejected_count, 1);
        Ok(())
    }

    #[test]
    fn principal_and_client_binding_mismatches_do_not_consume() -> SecurityResult<()> {
        block_on(async {
            let store = InMemoryTtlStore::default();
            let service = service(store)?;
            let correct_context = context(7, tenant("a")?)?;
            let other_context = context(8, tenant("a")?)?;
            let correct = binding(
                &correct_context,
                "ses_mismatch",
                TicketChannel::AsrWebSocket,
                Some(ClientBinding::new([3; 32])),
            )?;
            let wrong_principal = binding(
                &other_context,
                "ses_mismatch",
                TicketChannel::AsrWebSocket,
                Some(ClientBinding::new([3; 32])),
            )?;
            let wrong_client = binding(
                &correct_context,
                "ses_mismatch",
                TicketChannel::AsrWebSocket,
                Some(ClientBinding::new([4; 32])),
            )?;
            let issued = service.issue(&correct).await?;
            assert_eq!(
                service.consume(issued.secret(), &wrong_principal).await,
                Err(SecurityError::TicketRejected)
            );
            assert_eq!(
                service.consume(issued.secret(), &wrong_client).await,
                Err(SecurityError::TicketRejected)
            );
            assert!(service.consume(issued.secret(), &correct).await.is_ok());
            Ok(())
        })
    }

    #[test]
    fn ticket_digest_is_deterministic_and_pepper_separated() -> SecurityResult<()> {
        block_on(async {
            let service = service(InMemoryTtlStore::default())?;
            let context = context(7, tenant("a")?)?;
            let binding = binding(&context, "ses_digest01", TicketChannel::AsrWebSocket, None)?;
            let issued = service.issue(&binding).await?;
            let first = service.digest(issued.secret())?;
            let second = service.digest(issued.secret())?;
            assert_eq!(first, second);
            assert_eq!(first, issued.digest());
            assert_ne!(first.storage_key(), issued.secret().expose_for_transport());

            let other_pepper_service = TicketService::new(
                InMemoryTtlStore::default(),
                DeterministicEntropy::default(),
                TicketPepper::new(vec![8; 32])?,
                TicketPolicy::new(Duration::from_secs(30))?,
            );
            assert_ne!(other_pepper_service.digest(issued.secret())?, first);
            Ok(())
        })
    }

    #[test]
    fn stored_ticket_decoder_rejects_unknown_version_and_fields() -> SecurityResult<()> {
        let invalid_version = br#"{
            "version":2,
            "lifecycle":"unused",
            "organization_id":"org_a001",
            "workspace_id":"wsp_a001",
            "project_id":"prj_a001",
            "environment_id":"env_a001",
            "session_id":"ses_test001",
            "principal_digest":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "channel":"asr_web_socket",
            "client_binding":null
        }"#;
        assert_eq!(
            StoredTicket::decode(invalid_version).err(),
            Some(SecurityError::EncodingFailure)
        );

        let unknown_field = br#"{
            "version":1,
            "lifecycle":"unused",
            "organization_id":"org_a001",
            "workspace_id":"wsp_a001",
            "project_id":"prj_a001",
            "environment_id":"env_a001",
            "session_id":"ses_test001",
            "principal_digest":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "channel":"asr_web_socket",
            "client_binding":null,
            "unexpected_field":"rejected"
        }"#;
        assert_eq!(
            StoredTicket::decode(unknown_field).err(),
            Some(SecurityError::EncodingFailure)
        );
        Ok(())
    }

    #[test]
    fn ticket_policy_enforces_short_whole_millisecond_lifetimes() {
        assert_eq!(
            TicketPolicy::new(Duration::ZERO),
            Err(SecurityError::InvalidArgument("ticket_ttl"))
        );
        assert_eq!(
            TicketPolicy::new(Duration::from_nanos(1)),
            Err(SecurityError::InvalidArgument("ticket_ttl"))
        );
        assert_eq!(
            TicketPolicy::new(Duration::from_secs(1) + Duration::from_nanos(1)),
            Err(SecurityError::InvalidArgument("ticket_ttl"))
        );
        assert_eq!(
            TicketPolicy::new(Duration::from_secs(5 * 60 + 1)),
            Err(SecurityError::InvalidArgument("ticket_ttl"))
        );
        assert!(TicketPolicy::new(Duration::from_secs(1)).is_ok());
        assert!(TicketPolicy::new(Duration::from_secs(5 * 60)).is_ok());
    }
}
