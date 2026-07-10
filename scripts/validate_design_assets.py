"""Validate the versioned QingYin design and contract baseline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("PyYAML is required: python -m pip install -r requirements-dev.txt") from exc


ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DOCUMENTS = (
    "QingYin_系统设计目录与实施计划.md",
    "QingYin_设计冻结审阅与实现准入清单.md",
    "QingYin_工程实施总计划与GitHub治理.md",
    "QingYin_M1_Rust核心骨架与运行规范.md",
    "QingYin_M1_契约Fixture与MockProvider规范.md",
    "QingYin_M1_实施Backlog与CI门禁.md",
)


def load_yaml(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    if not path.is_file():
        raise ValueError(f"missing contract: {relative_path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"contract is not a YAML object: {relative_path}")
    return data


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def validate_documents() -> None:
    for relative_path in REQUIRED_DOCUMENTS:
        require((ROOT / relative_path).is_file(), f"missing design document: {relative_path}")


def validate_control_contract(contract: dict[str, Any]) -> None:
    require(contract.get("openapi") == "3.1.0", "control contract must use OpenAPI 3.1.0")
    require(contract.get("info", {}).get("title") == "QingYin Control API", "unexpected control API title")
    paths = contract.get("paths", {})
    require("/v1/capabilities" in paths, "control contract is missing capabilities")
    require("/v1/sessions" in paths, "control contract is missing session creation")
    require("/v1/tts/stream" in paths, "control contract is missing TTS streaming")


def validate_admin_contract(contract: dict[str, Any]) -> None:
    require(contract.get("openapi") == "3.1.0", "admin contract must use OpenAPI 3.1.0")
    require(contract.get("info", {}).get("title") == "QingYin Administration API", "unexpected admin API title")
    paths = contract.get("paths", {})
    required_paths = (
        "/v1/admin/workspaces",
        "/v1/admin/workspaces/{workspace_id}",
        "/v1/admin/sessions/{session_id}/diagnostic",
        "/v1/admin/operations/{operation_id}",
    )
    for path in required_paths:
        require(path in paths, f"admin contract is missing {path}")

    parameters = contract.get("components", {}).get("parameters", {})
    require("IfMatch" in parameters, "admin mutations require If-Match")
    require("ChangeReason" in parameters, "admin mutations require a change reason")


def validate_stream_contract(contract: dict[str, Any]) -> None:
    require(contract.get("asyncapi") == "3.0.0", "stream contract must use AsyncAPI 3.0.0")
    require(contract.get("info", {}).get("title") == "QingYin Streaming API", "unexpected streaming API title")
    operations = contract.get("operations", {})
    required_operations = {
        "sendAsrInput",
        "receiveAsrEvents",
        "sendTtsInput",
        "receiveTtsOutput",
        "sendRealtimeInput",
        "receiveRealtimeOutput",
    }
    require(required_operations.issubset(operations), "stream contract is missing a required operation")


def main() -> int:
    try:
        validate_documents()
        validate_control_contract(load_yaml("contracts/openapi/qingyin-control-v1.yaml"))
        validate_admin_contract(load_yaml("contracts/openapi/qingyin-admin-v1.yaml"))
        validate_stream_contract(load_yaml("contracts/asyncapi/qingyin-stream-v1.yaml"))
    except ValueError as exc:
        print(f"design asset validation failed: {exc}", file=sys.stderr)
        return 1

    print("design asset validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
