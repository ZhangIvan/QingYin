#!/usr/bin/env python3
"""Validate the exact internal dependency graph for the current M1 baseline."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INTERNAL_DEPENDENCIES = {
    "qingyin-types": set(),
    "qingyin-contract": {"qingyin-types"},
    "qingyin-provider": {"qingyin-contract", "qingyin-types"},
    "qingyin-state": {"qingyin-types"},
    "qingyin-admission": {"qingyin-state", "qingyin-types"},
    "qingyin-observe": {"qingyin-types"},
    "qingyin-gateway": {
        "qingyin-admission",
        "qingyin-contract",
        "qingyin-observe",
        "qingyin-provider",
        "qingyin-state",
        "qingyin-types",
    },
    "qingyin-mock-provider": {"qingyin-provider", "qingyin-types"},
    # Testkit grows only by the accepted interface stage; M1-03 adds state first.
    "qingyin-testkit": {"qingyin-contract", "qingyin-state", "qingyin-types"},
}


def read_toml(path: Path) -> dict:
    """Read one UTF-8 TOML document."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """Reject missing crates and both missing or unexpected internal edges."""
    workspace = read_toml(ROOT / "Cargo.toml")
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
