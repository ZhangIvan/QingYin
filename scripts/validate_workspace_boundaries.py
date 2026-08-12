#!/usr/bin/env python3
"""Validate the exact internal dependency graph for the current M1 baseline."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INTERNAL_DEPENDENCIES = {
    "qingyin-types": set(),
    "qingyin-contract": {"qingyin-types"},
    "qingyin-provider": {"qingyin-contract", "qingyin-types"},
    "qingyin-state": {"qingyin-types"},
    "qingyin-security": {"qingyin-state", "qingyin-types"},
    "qingyin-admission": {"qingyin-security", "qingyin-state", "qingyin-types"},
    "qingyin-observe": {"qingyin-security", "qingyin-types"},
    "qingyin-gateway": {
        "qingyin-admission",
        "qingyin-contract",
        "qingyin-observe",
        "qingyin-provider",
        "qingyin-state",
        "qingyin-types",
    },
    "qingyin-mock-provider": {"qingyin-provider", "qingyin-types"},
    # M1-05 adds the deterministic admission fake after the state fakes.
    "qingyin-testkit": {
        "qingyin-admission",
        "qingyin-contract",
        "qingyin-state",
        "qingyin-types",
    },
}

SECURITY_TEST_SUPPORT_RELEASE_ERROR = (
    "qingyin-security/test-support must not be enabled in release builds"
)
EXPECTED_SECURITY_FIXTURES = (
    "SessionActorA",
    "SessionActorCreateOnlyA",
    "SessionActorNoScopesA",
    "SessionActorB",
    "SessionActorAReverified",
    "OtherTenantActor",
    "RuntimeA",
    "RuntimeB",
)


def read_toml(path: Path) -> dict:
    """Read one UTF-8 TOML document."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def dependency_sections(
    table: dict, path: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], dict]]:
    """Return dependency tables, including target-specific declarations."""
    sections = []
    for key, value in table.items():
        if not isinstance(value, dict):
            continue
        current_path = (*path, key)
        if key in {"dependencies", "dev-dependencies", "build-dependencies"}:
            sections.append((current_path, value))
        else:
            sections.extend(dependency_sections(value, current_path))
    return sections


def dependency_features(specification: object) -> set[str]:
    """Return explicitly enabled features from one dependency specification."""
    if not isinstance(specification, dict):
        return set()
    features = specification.get("features", [])
    return set(features) if isinstance(features, list) else set()


def validate_security_test_support(owner: str, manifest: dict) -> None:
    """Allow qingyin-security/test-support only in development dependencies."""
    security_aliases = set()
    for section_path, dependencies in dependency_sections(manifest):
        for dependency_name, specification in dependencies.items():
            package_name = (
                specification.get("package")
                if isinstance(specification, dict)
                else None
            )
            if (
                dependency_name != "qingyin-security"
                and package_name != "qingyin-security"
            ):
                continue
            security_aliases.add(dependency_name)
            features = dependency_features(specification)
            if (
                "test-support" not in features
                or section_path[-1] == "dev-dependencies"
            ):
                continue
            section = ".".join(section_path)
            raise SystemExit(
                f"{owner} enables qingyin-security/test-support outside "
                f"dev-dependencies: section={section}"
            )

    for feature_name, forwarding in (manifest.get("features") or {}).items():
        if not isinstance(forwarding, list):
            continue
        for entry in forwarding:
            if not isinstance(entry, str) or "/" not in entry:
                continue
            dependency, dependency_feature = entry.split("/", maxsplit=1)
            if (
                dependency.removesuffix("?") in security_aliases
                and dependency_feature == "test-support"
            ):
                raise SystemExit(
                    f"{owner} forwards feature {feature_name} to "
                    "qingyin-security/test-support"
                )


def validate_security_test_support_api() -> None:
    """Require a closed fixture API and a release-build compile guard."""
    library = (ROOT / "crates/qingyin-security/src/lib.rs").read_text(
        encoding="utf-8"
    )
    support = (ROOT / "crates/qingyin-security/src/test_support.rs").read_text(
        encoding="utf-8"
    )
    build_script = (ROOT / "crates/qingyin-security/build.rs").read_text(
        encoding="utf-8"
    )
    compact_library = " ".join(library.split())
    compact_support = " ".join(support.split())
    compact_build_script = " ".join(build_script.split())
    release_guard = "#[cfg(qingyin_security_test_support_forbidden)]"
    build_guard_fragments = (
        'env::var_os("CARGO_FEATURE_TEST_SUPPORT")',
        'env::var("PROFILE")',
        'profile == "debug"',
        'cargo::rustc-cfg={FORBIDDEN_CFG}',
    )
    release_error = f'compile_error!("{SECURITY_TEST_SUPPORT_RELEASE_ERROR}");'
    fixture_signature = (
        "pub fn security_context(fixture: SecurityFixture) "
        "-> SecurityResult<SecurityContext>"
    )
    if (
        release_guard not in compact_library
        or release_error not in compact_library
        or any(
            fragment not in compact_build_script
            for fragment in build_guard_fragments
        )
    ):
        raise SystemExit("qingyin-security test-support release guard is missing")
    if "pub enum SecurityFixture" not in compact_support:
        raise SystemExit("qingyin-security closed SecurityFixture catalog is missing")
    if fixture_signature not in compact_support:
        raise SystemExit(
            "qingyin-security test helper must accept only SecurityFixture"
        )
    public_items = re.findall(
        r"^\s*pub\s+(?:(?:async|const|unsafe)\s+)*"
        r"(enum|fn|struct|trait|type|mod|use|const|static)\s+([A-Za-z_]\w*)",
        support,
        flags=re.MULTILINE,
    )
    expected_public_items = [
        ("enum", "SecurityFixture"),
        ("fn", "security_context"),
    ]
    if public_items != expected_public_items:
        raise SystemExit(
            "qingyin-security test-support exposes unexpected public items: "
            f"{public_items}"
        )
    fixture_match = re.search(
        r"pub enum SecurityFixture\s*\{(?P<body>.*?)^\}",
        support,
        flags=re.MULTILINE | re.DOTALL,
    )
    if fixture_match is None:
        raise SystemExit("qingyin-security SecurityFixture body is missing")
    variants = tuple(
        re.findall(
            r"^\s{4}([A-Z][A-Za-z0-9_]*)\s*,\s*$",
            fixture_match["body"],
            re.MULTILINE,
        )
    )
    if variants != EXPECTED_SECURITY_FIXTURES:
        raise SystemExit(
            f"qingyin-security fixture catalog mismatch: variants={variants}"
        )


def main() -> None:
    """Reject missing crates and both missing or unexpected internal edges."""
    workspace = read_toml(ROOT / "Cargo.toml")
    validate_security_test_support("workspace", workspace)
    validate_security_test_support_api()
    expected_members = {
        f"crates/{crate}" for crate in EXPECTED_INTERNAL_DEPENDENCIES
    }
    actual_members = set(workspace.get("workspace", {}).get("members", []))
    if actual_members != expected_members:
        missing = sorted(expected_members - actual_members)
        extra = sorted(actual_members - expected_members)
        raise SystemExit(
            f"workspace member mismatch: missing={missing} extra={extra}"
        )

    for crate, expected in EXPECTED_INTERNAL_DEPENDENCIES.items():
        manifest = read_toml(ROOT / "crates" / crate / "Cargo.toml")
        validate_security_test_support(crate, manifest)
        package_name = manifest.get("package", {}).get("name")
        if package_name != crate:
            raise SystemExit(
                f"crate path/name mismatch: path={crate} package={package_name}"
            )

        dependencies = set((manifest.get("dependencies") or {}).keys())
        actual = {name for name in dependencies if name.startswith("qingyin-")}
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise SystemExit(
                f"{crate} dependency mismatch: missing={missing} extra={extra}"
            )

    print("workspace dependency boundaries OK")


if __name__ == "__main__":
    main()
