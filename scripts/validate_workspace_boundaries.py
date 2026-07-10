"""Validate the allowed internal dependency graph for the QingYin workspace."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

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
    "qingyin-testkit": {
        "qingyin-admission",
        "qingyin-contract",
        "qingyin-provider",
        "qingyin-state",
        "qingyin-types",
    },
}


def cargo_metadata() -> dict[str, Any]:
    cargo = os.environ.get("CARGO", "cargo")
    result = subprocess.run(
        [cargo, "metadata", "--format-version", "1", "--no-deps"],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"cargo metadata failed:\n{result.stderr}")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError("cargo metadata did not return an object")
    return data


def main() -> int:
    try:
        packages = cargo_metadata().get("packages", [])
        package_dependencies = {
            package["name"]: {dependency["name"] for dependency in package["dependencies"]}
            for package in packages
        }
        actual_packages = set(package_dependencies)
        expected_packages = set(EXPECTED_INTERNAL_DEPENDENCIES)
        if actual_packages != expected_packages:
            raise ValueError(
                f"workspace package mismatch: expected {sorted(expected_packages)}, "
                f"got {sorted(actual_packages)}"
            )

        for package_name, expected_dependencies in EXPECTED_INTERNAL_DEPENDENCIES.items():
            actual_dependencies = package_dependencies[package_name] & expected_packages
            if actual_dependencies != expected_dependencies:
                raise ValueError(
                    f"{package_name} internal dependencies differ: "
                    f"expected {sorted(expected_dependencies)}, got {sorted(actual_dependencies)}"
                )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"workspace boundary validation failed: {exc}", file=sys.stderr)
        return 1

    print("workspace boundary validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
