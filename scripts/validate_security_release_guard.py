#!/usr/bin/env python3
"""Prove that security test fixtures cannot enter a release artifact."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_GUARD = (
    "qingyin-security/test-support must not be enabled in release builds"
)


def run_cargo(
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one locked Cargo check from the workspace root."""
    process_environment = os.environ.copy()
    if environment is not None:
        process_environment.update(environment)
    return subprocess.run(
        ["cargo", "check", *arguments, "--locked"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        env=process_environment,
        text=True,
    )


def print_failure(label: str, result: subprocess.CompletedProcess[str]) -> None:
    """Emit captured Cargo diagnostics only when a validation fails."""
    print(f"security release guard validation failed: {label}", file=sys.stderr)
    if result.stdout:
        print(result.stdout, file=sys.stderr, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")


def main() -> int:
    """Require normal release builds and reject release test-support builds."""
    release = run_cargo(
        "--release",
        "-p",
        "qingyin-security",
        "--no-default-features",
    )
    if release.returncode != 0:
        print_failure("normal release build did not compile", release)
        return 1

    guard_cases = (
        ("release mode", None),
        (
            "release mode with debug assertions",
            {"CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS": "true"},
        ),
    )
    for label, environment in guard_cases:
        guarded = run_cargo(
            "--release",
            "-p",
            "qingyin-security",
            "--all-features",
            environment=environment,
        )
        diagnostics = f"{guarded.stdout}\n{guarded.stderr}"
        if guarded.returncode == 0:
            print_failure(f"test-support compiled in {label}", guarded)
            return 1
        if EXPECTED_GUARD not in diagnostics:
            print_failure(f"{label} failed without the expected guard", guarded)
            return 1

    print("security release feature guard OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
