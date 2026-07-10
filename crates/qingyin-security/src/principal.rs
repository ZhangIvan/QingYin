use std::collections::BTreeSet;
use std::fmt;

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use qingyin_state::TenantScope;
use qingyin_types::ResourceId;
use subtle::ConstantTimeEq;

use crate::{SecurityError, SecurityResult};

macro_rules! security_resource_id {
    ($(#[$metadata:meta])* $name:ident) => {
        $(#[$metadata])*
        #[derive(Clone, Debug, Eq, Hash, PartialEq)]
        pub struct $name(ResourceId);

        impl $name {
            /// Creates a semantic security ID from a validated resource ID.
            #[must_use]
            pub const fn new(value: ResourceId) -> Self {
                Self(value)
            }

            /// Returns the underlying validated resource ID.
            #[must_use]
            pub const fn as_resource_id(&self) -> &ResourceId {
                &self.0
            }
        }
    };
}

security_resource_id!(
    /// Stable identity of an authenticated human or workload principal.
    PrincipalId
);
security_resource_id!(
    /// Stable identity of the credential that produced a principal.
    CredentialId
);

/// Irreversible digest bound into session tickets instead of principal data.
#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct PrincipalDigest([u8; 32]);

impl PrincipalDigest {
    /// Creates a digest produced by a trusted credential verifier.
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

impl fmt::Debug for PrincipalDigest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("<redacted:principal-digest>")
    }
}

/// Origin category of a verified principal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrincipalKind {
    /// Project API key used by a server application.
    ProjectCredential,
    /// Non-human service account.
    ServiceAccount,
    /// Authenticated human control-plane user.
    User,
    /// Time-bounded support delegation approved through break-glass workflow.
    SupportDelegation,
}

/// Human-facing role metadata. Roles never grant scopes implicitly.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Role {
    /// Organization or workspace owner.
    Owner,
    /// Administrative operator.
    Admin,
    /// Application developer.
    Developer,
    /// Runtime operator.
    Operator,
    /// Read-only user.
    Viewer,
}

/// Closed authorization capability checked by commands and handlers.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum Scope {
    /// Read capabilities available to the authenticated project/environment.
    CapabilitiesRead,
    /// Create a session lease.
    SessionCreate,
    /// Read a tenant-visible session summary.
    SessionRead,
    /// Cancel a session.
    SessionCancel,
    /// Connect to an authorized streaming channel.
    StreamConnect,
    /// Read tenant-scoped usage summaries.
    UsageRead,
    /// Read access-controlled diagnostics.
    DiagnosticsRead,
    /// Read administration resources.
    AdminRead,
    /// Mutate administration resources.
    AdminWrite,
}

/// Explicit scope set with deny-by-default behavior.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ScopeSet(BTreeSet<Scope>);

impl ScopeSet {
    /// Creates a deduplicated scope set.
    #[must_use]
    pub fn new(scopes: impl IntoIterator<Item = Scope>) -> Self {
        Self(scopes.into_iter().collect())
    }

    /// Returns whether the exact scope was explicitly granted.
    #[must_use]
    pub fn allows(&self, scope: Scope) -> bool {
        self.0.contains(&scope)
    }

    /// Returns whether no scope was granted.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

/// Immutable identity and authorization result produced by credential verification.
#[derive(Clone, Eq, PartialEq)]
pub struct Principal {
    principal_id: PrincipalId,
    credential_id: Option<CredentialId>,
    kind: PrincipalKind,
    role: Role,
    tenant_scope: TenantScope,
    scopes: ScopeSet,
    digest: PrincipalDigest,
}

impl Principal {
    /// Constructs a principal only from already verified credential results.
    ///
    /// Request DTOs, headers other than the credential, and metadata must never
    /// supply or override these fields.
    #[must_use]
    pub const fn from_verified(
        principal_id: PrincipalId,
        credential_id: Option<CredentialId>,
        kind: PrincipalKind,
        role: Role,
        tenant_scope: TenantScope,
        scopes: ScopeSet,
        digest: PrincipalDigest,
    ) -> Self {
        Self {
            principal_id,
            credential_id,
            kind,
            role,
            tenant_scope,
            scopes,
            digest,
        }
    }

    /// Returns the principal identifier.
    #[must_use]
    pub const fn principal_id(&self) -> &PrincipalId {
        &self.principal_id
    }

    /// Returns the credential identifier when authentication used a credential.
    #[must_use]
    pub const fn credential_id(&self) -> Option<&CredentialId> {
        self.credential_id.as_ref()
    }

    /// Returns the principal origin category.
    #[must_use]
    pub const fn kind(&self) -> PrincipalKind {
        self.kind
    }

    /// Returns role metadata without converting it to permissions.
    #[must_use]
    pub const fn role(&self) -> Role {
        self.role
    }

    /// Returns the trusted tenant ownership chain.
    #[must_use]
    pub const fn tenant_scope(&self) -> &TenantScope {
        &self.tenant_scope
    }

    /// Returns the explicit scope set.
    #[must_use]
    pub const fn scopes(&self) -> &ScopeSet {
        &self.scopes
    }

    /// Returns the irreversible digest used for ticket binding.
    #[must_use]
    pub const fn digest(&self) -> PrincipalDigest {
        self.digest
    }
}

impl fmt::Debug for Principal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Principal")
            .field("principal_id", &self.principal_id)
            .field("credential_id", &self.credential_id)
            .field("kind", &self.kind)
            .field("role", &self.role)
            .field("tenant_scope", &self.tenant_scope)
            .field("scopes", &self.scopes)
            .field("digest", &self.digest)
            .finish()
    }
}

/// Request-local trusted security context.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecurityContext {
    principal: Principal,
}

impl SecurityContext {
    /// Creates a request context from a verified principal.
    #[must_use]
    pub const fn from_verified_principal(principal: Principal) -> Self {
        Self { principal }
    }

    /// Returns the verified principal.
    #[must_use]
    pub const fn principal(&self) -> &Principal {
        &self.principal
    }

    /// Requires one explicitly granted scope.
    pub fn require_scope(&self, required: Scope) -> SecurityResult<()> {
        if self.principal.scopes.allows(required) {
            Ok(())
        } else {
            Err(SecurityError::PermissionDenied)
        }
    }

    /// Requires both an explicit scope and exact tenant ownership.
    pub fn authorize_resource(
        &self,
        resource_scope: &TenantScope,
        required: Scope,
    ) -> SecurityResult<()> {
        self.require_scope(required)?;
        if self.principal.tenant_scope == *resource_scope {
            Ok(())
        } else {
            Err(SecurityError::TenantScopeMismatch)
        }
    }
}

#[cfg(test)]
mod tests {
    use qingyin_state::{EnvironmentId, OrganizationId, ProjectId, TenantScope, WorkspaceId};
    use qingyin_types::ResourceId;

    use super::{
        CredentialId, Principal, PrincipalDigest, PrincipalId, PrincipalKind, Role, Scope,
        ScopeSet, SecurityContext,
    };
    use crate::{SecurityError, SecurityResult};

    fn resource_id(value: &str) -> SecurityResult<ResourceId> {
        ResourceId::new(value).ok_or(SecurityError::InvalidArgument("test_resource_id"))
    }

    fn tenant(suffix: &str) -> SecurityResult<TenantScope> {
        Ok(TenantScope::new(
            OrganizationId::new(resource_id(&format!("org_{suffix}001"))?),
            WorkspaceId::new(resource_id(&format!("wsp_{suffix}001"))?),
            ProjectId::new(resource_id(&format!("prj_{suffix}001"))?),
            EnvironmentId::new(resource_id(&format!("env_{suffix}001"))?),
        ))
    }

    fn context(role: Role, scopes: ScopeSet) -> SecurityResult<SecurityContext> {
        Ok(SecurityContext::from_verified_principal(
            Principal::from_verified(
                PrincipalId::new(resource_id("prn_test001")?),
                Some(CredentialId::new(resource_id("crd_test001")?)),
                PrincipalKind::ProjectCredential,
                role,
                tenant("a")?,
                scopes,
                PrincipalDigest::new([7; 32]),
            ),
        ))
    }

    #[test]
    fn scopes_deny_by_default_even_for_owner_role() -> SecurityResult<()> {
        let context = context(Role::Owner, ScopeSet::default())?;
        assert_eq!(
            context.require_scope(Scope::SessionCreate),
            Err(SecurityError::PermissionDenied)
        );
        assert!(context.principal().scopes().is_empty());
        Ok(())
    }

    #[test]
    fn exact_scope_and_tenant_are_both_required() -> SecurityResult<()> {
        let trusted_scope = tenant("a")?;
        let request_supplied_scope = tenant("b")?;
        let context = context(
            Role::Developer,
            ScopeSet::new([Scope::SessionCreate, Scope::SessionRead]),
        )?;
        assert_eq!(context.principal().tenant_scope(), &trusted_scope);
        assert!(
            context
                .authorize_resource(&trusted_scope, Scope::SessionCreate)
                .is_ok()
        );
        assert_eq!(
            context.authorize_resource(&request_supplied_scope, Scope::SessionCreate),
            Err(SecurityError::TenantScopeMismatch)
        );
        assert_eq!(
            context.authorize_resource(&trusted_scope, Scope::SessionCancel),
            Err(SecurityError::PermissionDenied)
        );
        assert_eq!(context.principal().tenant_scope(), &trusted_scope);
        Ok(())
    }

    #[test]
    fn principal_debug_redacts_subject_digest() -> SecurityResult<()> {
        let context = context(Role::Developer, ScopeSet::new([Scope::SessionRead]))?;
        let debug = format!("{:?}", context.principal());
        assert!(!debug.contains(&PrincipalDigest::new([7; 32]).encode()));
        assert!(debug.contains("<redacted:principal-digest>"));
        Ok(())
    }
}
