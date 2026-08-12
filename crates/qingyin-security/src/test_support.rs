//! Deterministic constructors for tests outside the security trust boundary.
//!
//! This module exists only with the `test-support` feature. It exposes a closed
//! set of synthetic identities instead of an arbitrary trusted-context mint.
//! Production dependencies must never enable the feature, and release builds
//! fail to compile if it is accidentally enabled.

use qingyin_state::{EnvironmentId, OrganizationId, ProjectId, TenantScope, WorkspaceId};
use qingyin_types::ResourceId;

use crate::{
    CredentialId, Principal, PrincipalDigest, PrincipalId, PrincipalKind, Role, Scope, ScopeSet,
    SecurityContext, SecurityError, SecurityResult,
};

/// Closed deterministic identities available to cross-crate tests.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum SecurityFixture {
    /// Session actor A in tenant A with create and cancel permission.
    SessionActorA,
    /// Session actor A in tenant A with create permission but no cancel permission.
    SessionActorCreateOnlyA,
    /// Session actor A in tenant A without any granted scope.
    SessionActorNoScopesA,
    /// A distinct session actor in tenant A with the same bounded permissions.
    SessionActorB,
    /// Session actor A reverified with a rotated digest and otherwise identical binding.
    SessionActorAReverified,
    /// A session actor in tenant B for negative tenant-isolation tests.
    OtherTenantActor,
    /// Trusted admission runtime for tenant A.
    RuntimeA,
    /// Trusted admission runtime for tenant B.
    RuntimeB,
}

struct FixtureSpec {
    principal_id: &'static str,
    credential_id: &'static str,
    kind: PrincipalKind,
    role: Role,
    tenant: FixtureTenant,
    scopes: &'static [Scope],
    digest: [u8; 32],
}

#[derive(Clone, Copy)]
enum FixtureTenant {
    A,
    B,
}

const SESSION_SCOPES: &[Scope] = &[Scope::SessionCreate, Scope::SessionCancel];
const SESSION_CREATE_SCOPE: &[Scope] = &[Scope::SessionCreate];
const NO_SCOPES: &[Scope] = &[];
const RUNTIME_SCOPES: &[Scope] = &[Scope::AdmissionManage];

/// Returns one deterministic security context from the closed fixture catalog.
///
/// The fixture controls tenant ownership, actor identity, credential identity,
/// principal kind, scopes, and digest together; callers cannot override any
/// trusted field.
pub fn security_context(fixture: SecurityFixture) -> SecurityResult<SecurityContext> {
    let spec = match fixture {
        SecurityFixture::SessionActorA => FixtureSpec {
            principal_id: "prn_session_actor_a",
            credential_id: "crd_session_actor_a",
            kind: PrincipalKind::ProjectCredential,
            role: Role::Developer,
            tenant: FixtureTenant::A,
            scopes: SESSION_SCOPES,
            digest: [0xa1; 32],
        },
        SecurityFixture::SessionActorCreateOnlyA => FixtureSpec {
            principal_id: "prn_session_actor_a",
            credential_id: "crd_session_actor_a",
            kind: PrincipalKind::ProjectCredential,
            role: Role::Developer,
            tenant: FixtureTenant::A,
            scopes: SESSION_CREATE_SCOPE,
            digest: [0xa1; 32],
        },
        SecurityFixture::SessionActorNoScopesA => FixtureSpec {
            principal_id: "prn_session_actor_a",
            credential_id: "crd_session_actor_a",
            kind: PrincipalKind::ProjectCredential,
            role: Role::Developer,
            tenant: FixtureTenant::A,
            scopes: NO_SCOPES,
            digest: [0xa1; 32],
        },
        SecurityFixture::SessionActorB => FixtureSpec {
            principal_id: "prn_session_actor_b",
            credential_id: "crd_session_actor_b",
            kind: PrincipalKind::ProjectCredential,
            role: Role::Developer,
            tenant: FixtureTenant::A,
            scopes: SESSION_SCOPES,
            digest: [0xb2; 32],
        },
        SecurityFixture::SessionActorAReverified => FixtureSpec {
            principal_id: "prn_session_actor_a",
            credential_id: "crd_session_actor_a",
            kind: PrincipalKind::ProjectCredential,
            role: Role::Developer,
            tenant: FixtureTenant::A,
            scopes: SESSION_SCOPES,
            digest: [0xa2; 32],
        },
        SecurityFixture::OtherTenantActor => FixtureSpec {
            principal_id: "prn_other_tenant_actor",
            credential_id: "crd_other_tenant_actor",
            kind: PrincipalKind::ProjectCredential,
            role: Role::Developer,
            tenant: FixtureTenant::B,
            scopes: SESSION_SCOPES,
            digest: [0xc3; 32],
        },
        SecurityFixture::RuntimeA => FixtureSpec {
            principal_id: "prn_admission_runtime_a",
            credential_id: "crd_admission_runtime_a",
            kind: PrincipalKind::ServiceAccount,
            role: Role::Operator,
            tenant: FixtureTenant::A,
            scopes: RUNTIME_SCOPES,
            digest: [0xd4; 32],
        },
        SecurityFixture::RuntimeB => FixtureSpec {
            principal_id: "prn_admission_runtime_b",
            credential_id: "crd_admission_runtime_b",
            kind: PrincipalKind::ServiceAccount,
            role: Role::Operator,
            tenant: FixtureTenant::B,
            scopes: RUNTIME_SCOPES,
            digest: [0xe5; 32],
        },
    };

    let principal = Principal::from_verified(
        PrincipalId::new(resource_id(spec.principal_id)?),
        Some(CredentialId::new(resource_id(spec.credential_id)?)),
        spec.kind,
        spec.role,
        tenant_scope(spec.tenant)?,
        ScopeSet::new(spec.scopes.iter().copied()),
        PrincipalDigest::new(spec.digest),
    );
    Ok(SecurityContext::from_verified_principal(principal))
}

fn resource_id(value: &'static str) -> SecurityResult<ResourceId> {
    ResourceId::new(value).ok_or(SecurityError::InvalidArgument("security_fixture_id"))
}

fn tenant_scope(tenant: FixtureTenant) -> SecurityResult<TenantScope> {
    let (organization, workspace, project, environment) = match tenant {
        FixtureTenant::A => (
            "org_fixture_a",
            "wsp_fixture_a",
            "prj_fixture_a",
            "env_fixture_a",
        ),
        FixtureTenant::B => (
            "org_fixture_b",
            "wsp_fixture_b",
            "prj_fixture_b",
            "env_fixture_b",
        ),
    };
    Ok(TenantScope::new(
        OrganizationId::new(resource_id(organization)?),
        WorkspaceId::new(resource_id(workspace)?),
        ProjectId::new(resource_id(project)?),
        EnvironmentId::new(resource_id(environment)?),
    ))
}

#[cfg(test)]
mod tests {
    use super::{SecurityFixture, security_context};
    use crate::{PrincipalKind, Scope, SecurityError, SecurityResult};

    #[test]
    fn session_fixtures_are_bounded_and_actor_distinct() -> SecurityResult<()> {
        let actor_a = security_context(SecurityFixture::SessionActorA)?;
        let actor_b = security_context(SecurityFixture::SessionActorB)?;
        let other = security_context(SecurityFixture::OtherTenantActor)?;

        for actor in [&actor_a, &actor_b, &other] {
            actor.require_scope(Scope::SessionCreate)?;
            actor.require_scope(Scope::SessionCancel)?;
            assert_eq!(
                actor.require_scope(Scope::AdmissionManage),
                Err(SecurityError::PermissionDenied)
            );
            assert_eq!(actor.principal().kind(), PrincipalKind::ProjectCredential);
        }
        assert_eq!(
            actor_a.principal().tenant_scope(),
            actor_b.principal().tenant_scope()
        );
        assert_ne!(
            actor_a.principal().principal_id(),
            actor_b.principal().principal_id()
        );
        assert_ne!(
            actor_a.principal().credential_id(),
            actor_b.principal().credential_id()
        );
        assert_ne!(actor_a.principal().digest(), actor_b.principal().digest());
        assert_ne!(
            actor_a.principal().tenant_scope(),
            other.principal().tenant_scope()
        );
        Ok(())
    }

    #[test]
    fn bounded_negative_and_reverified_session_scenarios_are_exact() -> SecurityResult<()> {
        let actor_a = security_context(SecurityFixture::SessionActorA)?;
        let create_only = security_context(SecurityFixture::SessionActorCreateOnlyA)?;
        let no_scopes = security_context(SecurityFixture::SessionActorNoScopesA)?;
        let reverified = security_context(SecurityFixture::SessionActorAReverified)?;

        create_only.require_scope(Scope::SessionCreate)?;
        assert_eq!(
            create_only.require_scope(Scope::SessionCancel),
            Err(SecurityError::PermissionDenied)
        );
        for scope in [
            Scope::SessionCreate,
            Scope::SessionCancel,
            Scope::AdmissionManage,
        ] {
            assert_eq!(
                no_scopes.require_scope(scope),
                Err(SecurityError::PermissionDenied)
            );
        }

        assert_eq!(
            actor_a.principal().principal_id(),
            reverified.principal().principal_id()
        );
        assert_eq!(
            actor_a.principal().credential_id(),
            reverified.principal().credential_id()
        );
        assert_eq!(
            actor_a.principal().tenant_scope(),
            reverified.principal().tenant_scope()
        );
        assert_ne!(
            actor_a.principal().digest(),
            reverified.principal().digest()
        );
        Ok(())
    }

    #[test]
    fn runtime_fixtures_are_manage_only_and_tenant_distinct() -> SecurityResult<()> {
        let runtime_a = security_context(SecurityFixture::RuntimeA)?;
        let runtime_b = security_context(SecurityFixture::RuntimeB)?;

        for runtime in [&runtime_a, &runtime_b] {
            runtime.require_scope(Scope::AdmissionManage)?;
            assert_eq!(
                runtime.require_scope(Scope::SessionCreate),
                Err(SecurityError::PermissionDenied)
            );
            assert_eq!(
                runtime.require_scope(Scope::SessionCancel),
                Err(SecurityError::PermissionDenied)
            );
            assert_eq!(runtime.principal().kind(), PrincipalKind::ServiceAccount);
        }
        assert_ne!(
            runtime_a.principal().tenant_scope(),
            runtime_b.principal().tenant_scope()
        );
        Ok(())
    }
}
