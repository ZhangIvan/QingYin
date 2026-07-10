#!/usr/bin/env python3
"""Check M1 crate dependency direction from the Rust bootstrap spec."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "qingyin-types": set(),
    "qingyin-contract": {"qingyin-types"},
    "qingyin-provider": {"qingyin-types", "qingyin-contract"},
    "qingyin-state": {"qingyin-types"},
    "qingyin-admission": {"qingyin-types", "qingyin-state"},
    "qingyin-observe": {"qingyin-types"},
    "qingyin-gateway": {"qingyin-types", "qingyin-contract", "qingyin-provider", "qingyin-state", "qingyin-admission", "qingyin-observe"},
    "qingyin-mock-provider": {"qingyin-types", "qingyin-provider"},
    "qingyin-testkit": {"qingyin-types", "qingyin-contract", "qingyin-provider", "qingyin-state", "qingyin-admission", "qingyin-observe", "qingyin-gateway", "qingyin-mock-provider"},
}


def main() -> None:
    for crate, allowed in ALLOWED.items():
        manifest = tomllib.loads((ROOT / "crates" / crate / "Cargo.toml").read_text())
        deps = set((manifest.get("dependencies") or {}).keys())
        internal = {dep for dep in deps if dep.startswith("qingyin-")}
        disallowed = internal - allowed
        if disallowed:
            raise SystemExit(f"{crate} has disallowed internal dependencies: {sorted(disallowed)}")
    print("workspace dependency boundaries OK")


if __name__ == "__main__":
    main()
