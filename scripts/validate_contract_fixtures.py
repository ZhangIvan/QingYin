#!/usr/bin/env python3
"""Validate the M1 contract fixture manifest bootstrap."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "contracts" / "fixtures" / "v1" / "manifest.json"
REQUIRED_GOLDEN = {
    "control.session.create.asr.v1",
    "asr.ws.happy.v1",
    "tts.ws.happy.v1",
    "tts.http.happy.v1",
    "control.session.cancel.v1",
    "capabilities.scoped.v1",
}
REQUIRED_ERRORS = {
    "control.idempotency.same.v1",
    "control.idempotency.conflict.v1",
    "stream.ticket.race.v1",
    "stream.start.invalid.v1",
    "stream.audio.rate.v1",
    "provider.create.failure.v1",
    "provider.stream.failure.v1",
    "provider.timeout.v1",
    "stream.slow.consumer.v1",
    "stream.cancel.race.v1",
    "state.ttl.recovery.v1",
    "policy.local_only.v1",
}
REQUIRED_PROFILES = {
    "happy",
    "slow_first",
    "create_reject",
    "fail_midstream",
    "hang_until_cancel",
    "quota_exhausted",
    "protocol_violation",
}


def require_exact(name: str, actual: list[str], expected: set[str]) -> None:
    actual_set = set(actual)
    if actual_set != expected:
        missing = sorted(expected - actual_set)
        extra = sorted(actual_set - expected)
        raise SystemExit(f"{name} mismatch: missing={missing} extra={extra}")


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema_version") != "v1":
        raise SystemExit("fixture manifest schema_version must be v1")
    if data.get("privacy_class") != "synthetic":
        raise SystemExit("fixture manifest privacy_class must be synthetic")
    require_exact("golden_paths", data.get("golden_paths", []), REQUIRED_GOLDEN)
    require_exact("error_and_resilience", data.get("error_and_resilience", []), REQUIRED_ERRORS)
    require_exact("mock_profiles", data.get("mock_profiles", []), REQUIRED_PROFILES)
    print("contract fixture manifest OK")


if __name__ == "__main__":
    main()
