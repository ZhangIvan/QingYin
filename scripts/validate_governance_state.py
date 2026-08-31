#!/usr/bin/env python3
"""Fail closed on local QingYin governance structure and Git-lineage drift."""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
from dataclasses import dataclass
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import tokenize
import tomllib
import unicodedata
from unittest.mock import patch
import zipfile
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, NoReturn

import yaml


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def construct_unique_yaml_mapping(loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_yaml_mapping,
)


ROOT = Path(__file__).resolve().parent.parent
DEC_PATH = Path("docs/04-delivery/QingYin_DEC-20260829-001_单维护者合并治理.md")
PLAN_PATH = Path("docs/04-delivery/QingYin_工程实施总计划与GitHub治理.md")
INDEX_PATH = Path("docs/04-delivery/INDEX.md")
WORKFLOW_PATH = Path(".github/workflows/design-contracts.yml")
RUST_WORKFLOW_PATH = Path(".github/workflows/rust.yml")
VALIDATOR_PATH = Path("scripts/validate_governance_state.py")
GOVERNANCE_PATHS = (INDEX_PATH, DEC_PATH, PLAN_PATH)
BOOTSTRAP_PATHS = (WORKFLOW_PATH, RUST_WORKFLOW_PATH, INDEX_PATH, DEC_PATH, PLAN_PATH, VALIDATOR_PATH)
BOOTSTRAP_STATUS = {
    WORKFLOW_PATH: "M",
    RUST_WORKFLOW_PATH: "M",
    INDEX_PATH: "M",
    DEC_PATH: "A",
    PLAN_PATH: "M",
    VALIDATOR_PATH: "A",
}
EXPECTED_GOVERNANCE_PR = 19
SOURCE_COMMIT = "27320e74f8cb920add83d6094fb81233dbb29636"
REAL_SOURCE_COMMIT = SOURCE_COMMIT
SOURCE_BLOB = "72bad2a3d7d72babd4c60554ed8e531ae8d7c841"
SOURCE_ANCHORS = (
    "CI 通过后进行独立 reviewer 审阅",
    "高风险变更必须增加第二位维护者或安全/SRE",
)
COMMON_RESIDUAL_IDS = ("GVN-P1-001", "GVN-P1-002", "GVN-P1-003")
ONE_TIME_RESIDUAL_IDS = ("GVN-P1-005",)
RESIDUAL_IDS = (*COMMON_RESIDUAL_IDS, *ONE_TIME_RESIDUAL_IDS)
ONE_TIME_TARGET_TYPES = ("governance-bootstrap", "activation-evidence")
FRESHNESS_UNVERIFIED_MARKER = "stable-window capture-time freshness (GVN-P1-005)"
RESIDUAL_VALID_UNTIL = "2026-09-29T00:00:00Z"
RESIDUAL_SECTION_SHA256 = {
    "GVN-P1-001": "7d3671ecdf6cce7157f4b9e92f2ff8cb7165144002d48ab348410776164c658d",
    "GVN-P1-002": "d58448eeafaff19c3e4ef0d225ae6278e3e2b16cb12a928336f6c7bd03cb3ef3",
    "GVN-P1-003": "c9b761b32d82dece4a013417b309bffb8a59db59cd76aff6e5f60f45a34ad9aa",
    "GVN-P1-005": "c9b0855ee9915d3c3a62e598ca219d54d2814cdea69ce3b71be669eabbaec5ba",
}
RESIDUAL_FIELD_ORDER = {
    "GVN-P1-001": ("status", "accepted_by", "reason", "scope", "mitigation", "rollback", "fallback", "valid_until", "invalidators", "review_date", "evidence"),
    "GVN-P1-002": ("status", "accepted_by", "reason", "scope", "mitigation", "mismatch_finding", "rollback", "fallback", "valid_until", "invalidators", "evidence"),
    "GVN-P1-003": ("status", "accepted_by", "reason", "scope", "mitigation", "rollback", "fallback", "valid_until", "invalidators", "evidence"),
    "GVN-P1-005": ("status", "accepted_by", "reason", "scope", "mitigation", "rollback", "fallback", "valid_until", "invalidators", "evidence"),
}
RESIDUAL_SCOPES = {
    "GVN-P1-001": "本仓库 `CR0–CR3` 的普通受保护 PR 合并证据；不适用于 `CR4` 真实操作、生产、secret、租户、客户数据或外部门。",
    "GVN-P1-002": "仅本仓库 `CR0–CR3` 的普通受保护同步 PR merge；不适用于 `CR4`、生产、secret、租户、客户数据、部署、release/tag、流量或外部门。",
    "GVN-P1-003": "仅本仓库 `CR0–CR3` 的 Agent review transcript 证据；不适用于 `CR4`、生产、secret、租户、客户数据、部署、release/tag、流量或外部门。",
    "GVN-P1-005": "仅 `DEC-20260829-001` 本次一次性 `CR3` governance bootstrap PR `#19` 与其唯一 activation evidence PR 的 candidate-bound evidence sequence，包括 activation binding 内嵌的 PR #19 start/end/post sequence；不得用于普通 PR（包括 CR0–CR3）、业务代码、生产、部署、发布、secret、credential、tenant、customer data、traffic 或 external gate。",
}
REQUIRED_CONTEXTS = ("contract-fixtures", "format-lint", "msrv", "security", "unit")
AGENT_REVIEW_SCOPE = ("acceptance", "compatibility", "rollback", "scope", "security-privacy", "tests")
CONTEXT_WORKFLOW_PATHS = {
    "contract-fixtures": ".github/workflows/design-contracts.yml",
    "format-lint": ".github/workflows/rust.yml",
    "msrv": ".github/workflows/rust.yml",
    "security": ".github/workflows/rust.yml",
    "unit": ".github/workflows/rust.yml",
}
EXPECTED_RUNNER_LABEL = "ubuntu-24.04"
EXPECTED_WORKFLOW_SHA256 = {
    ".github/workflows/design-contracts.yml": "40e0789932fa6a2230abd5e0d965e1bc59a0b27fb107f4796234a8d24845d904",
    ".github/workflows/rust.yml": "8a4bea492e9643cdfc4c855b2ad0874ae465fc235010960fa6757da90290a010",
}
EXPECTED_WORKFLOW_PATHS = tuple(sorted(EXPECTED_WORKFLOW_SHA256, key=lambda value: value.encode("utf-16-be")))
EXPECTED_RUN_SHA256 = {
    ".github/workflows/design-contracts.yml|design-contracts|3|Record immutable execution evidence": "eea59e2b00167b901517962bbe5df22b1043d3a3893c265d15ffc460445296f3",
    ".github/workflows/design-contracts.yml|design-contracts|4|Install validation dependency": "794531013a8e366d1f6d3bc56ccb9dea182430f39e886e0d398a7c65d6067b00",
    ".github/workflows/design-contracts.yml|design-contracts|5|Validate design and contract assets": "49025e300c4818d56174bc8c108eee06fa919fd74ac264971a553162d31e05a4",
    ".github/workflows/design-contracts.yml|design-contracts|6|Validate documentation links": "6c8e29cd46f2056c3d41cb7e933825f0459a2c12bdbefa74d0c1f45e61718356",
    ".github/workflows/design-contracts.yml|design-contracts|7|Validate governance state": "cde84479c0e5b2564dc62808f758a6f1627c217253491fca7e3b3a2b9da5dc8d",
    ".github/workflows/rust.yml|msrv|2|Install declared MSRV": "87b0b8ac7b7731b22dd9995946145c659ce42f0d38c681ef57959f46cc78e3ef",
    ".github/workflows/rust.yml|msrv|3|Record immutable execution evidence": "6e27e1c319ab0f83d9a00edc985d01e2eb711502f7bd020f9ed7f9e37fc640be",
    ".github/workflows/rust.yml|msrv|4|Record runner and toolchain evidence": "bed309132a1ed79c3b8f16574df699c3635381e2de1ba4beeb71e90cffd3e77c",
    ".github/workflows/rust.yml|msrv|5|Compile workspace on declared MSRV": "a111e76858b15582ea754a481258df0025635a19b2d46ef4562065ab6ec71417",
    ".github/workflows/rust.yml|format-lint|2|Check formatting": "2d009b4c2fff7c140a0e853344ad59d7dd2bd2a362627a962da72a2e39704a8f",
    ".github/workflows/rust.yml|format-lint|3|Record immutable execution evidence": "1a0ad50791351d9d09f1a98e094463adc39581d045d8ab8f3d56be8ab7c04306",
    ".github/workflows/rust.yml|format-lint|4|Check workspace": "4a8047559bd33bc64e4b94d23030f29cfcbbaf9776777a31ba6e549881db6903",
    ".github/workflows/rust.yml|format-lint|5|Run Clippy": "0acdad6d86d7a11595eb289ecce9e7cba55302778eebd1a91509af8c2059bafe",
    ".github/workflows/rust.yml|format-lint|6|Validate crate boundaries": "358af583f71b4653db0fa710e3305c8bc84287176d51e76a407d751410dbda50",
    ".github/workflows/rust.yml|format-lint|7|Validate fixture manifest": "fa217d9dd553900ede999b0dbc65b03e83205dc03cbaf07e073288737f4a568f",
    ".github/workflows/rust.yml|unit|2|Run workspace tests": "e1201e7b2ba0d98bcde1be592e63961c293365f4e2a40c010ecba941b0e2042c",
    ".github/workflows/rust.yml|unit|3|Record immutable execution evidence": "1bf90074737c06dab363abefc60fc388cd1c65309bb70c8c69b230fdac186365",
    ".github/workflows/rust.yml|security|2|Scan for credential regressions": "8e8ae11e74a0fe1213065b97acf2e9f88c306dcb6e0997f0debc5f7da2faa2d4",
    ".github/workflows/rust.yml|security|3|Record immutable execution evidence": "8d7bb01693eb2d64df31393a62c6078da3a46a87682596dd3b1d5c85e9039aed",
    ".github/workflows/rust.yml|security|4|Run security boundary tests": "ab551b47c2a0691af19371898484a262fdce4e7c4ae186dd1a2620cd1ce1cd66",
}
EXPECTED_ACTION_PINS = {
    "actions/checkout": "11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
}
EXPECTED_RUST_PUSH_PATHS = [
    ".cargo/**",
    "crates/**",
    "scripts/validate_contract_fixtures.py",
    "scripts/validate_secret_regressions.py",
    "scripts/validate_workspace_boundaries.py",
    "Cargo.lock",
    "Cargo.toml",
    "rust-toolchain.toml",
    "rustfmt.toml",
    ".github/workflows/rust.yml",
]
GITHUB_ACTIONS_APP_ID = 15368
OWNER_GITHUB_ID = 25630763
SAFE_INTEGER_LIMIT = 2**53 - 1
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")
RFC3339_UTC_PATTERN = re.compile(r"20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z")
PULL_METADATA_QUERY = "query QingYinPullMetadata($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){id number title body updatedAt baseRefName headRefName baseRefOid headRefOid isDraft mergeable labels(first:100){nodes{id name} pageInfo{hasNextPage endCursor}} reviewRequests(first:100){nodes{requestedReviewer{... on User{id databaseId login} ... on Team{id databaseId name}}} pageInfo{hasNextPage endCursor}} milestone{id title} assignees(first:100){nodes{id databaseId login} pageInfo{hasNextPage endCursor}} autoMergeRequest{enabledAt mergeMethod} mergeQueueEntry{id position}}}}"
REVIEW_THREADS_QUERY = "query QingYinReviewThreads($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){id number baseRefOid headRefOid reviewThreads(first:100){nodes{id isResolved isOutdated comments(first:100){nodes{id databaseId author{login ... on User{id databaseId} ... on Bot{id databaseId} ... on Organization{id databaseId} ... on Mannequin{id databaseId}} body createdAt updatedAt outdated state commit{oid}} pageInfo{hasNextPage endCursor}}} pageInfo{hasNextPage endCursor}}}}}"
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_VALIDATOR_SOURCE_BYTES = 4 * 1024 * 1024
MAX_VALIDATOR_SOURCE_TOKENS = 100_000
MAX_EVIDENCE_ARCHIVE_DEPTH = 4
MAX_EVIDENCE_PACKAGE_DEPTH = 3
ZIP_EOCD_SIZE = 22
ZIP_CENTRAL_DIRECTORY_HEADER_SIZE = 46
MAX_ZIP_COMMENT_BYTES = 0xFFFF
MAX_ZIP_EOCD_SEARCH_BYTES = ZIP_EOCD_SIZE + MAX_ZIP_COMMENT_BYTES
EVIDENCE_DIRECTORY_NAME = "qingyin-governance-evidence"
EVIDENCE_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[0-9A-Za-z]{36,255}\b"),
    re.compile(rb"\bgithub_pat_[0-9A-Za-z_]{22,255}\b"),
    re.compile(rb"\b(?:AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,})\b"),
    re.compile(rb"\b(?:xox[baprs]-[0-9A-Za-z-]{10,}|glpat-[0-9A-Za-z_-]{20,})\b"),
    re.compile(rb"\b(?:sq0atp-|sq0csp-)[0-9A-Za-z_-]{20,}\b"),
    re.compile(rb"\b(?:eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b"),
    re.compile(rb"\bsk-(?:proj-)?[0-9A-Za-z_-]{20,}\b"),
    re.compile(rb"(?i)\bBearer\s+[0-9A-Za-z._~+/-]{20,}={0,2}\b"),
    re.compile(rb"(?i)\b(?:Authorization|Proxy-Authorization|Cookie|Set-Cookie)\s*:\s*[^\r\n\"]{8,}"),
    re.compile(rb'(?i)"(?:authorization|cookie|access[_-]?token|client[_-]?secret|password|private[_-]?key)"\s*:'),
)

DEC_HEADER_PREFIXES = (
    "- 状态：",
    "- 生效状态：",
    "- 日期：",
    "- 决策所有者：",
    "- 基线：",
    "- 适用范围：",
    "- 非目标：",
    "- `effective_commit`：",
    "- `governance_pr`：",
    "- `governance_candidate_head`：",
    "- `governance_merge_commit`：",
    "- `governance_merge_tree`：",
    "- `governance_merge_parent`：",
    "- `governance_postmerge_manifest_sha256`：",
    "- `governance_attestation_sha256`：",
    "- `governance_validator_blob_git_sha1`：",
    "- `activation_evidence_pr`：",
    "- `superseded_source_path`：",
    "- `superseded_source_commit`：",
    "- `superseded_source_blob_git_sha1`：",
    "- `supersedes`：",
    "- 回滚：",
)
EXPECTED_SUPERSEDES_LINE = "- `supersedes`：仅在本决策变为 `ACTIVE` 后，替代上述精确 path/commit/Git blob 中的 `V02-SUP-4.6`——第 4 节第 6 步“CI 通过后进行独立 reviewer 审阅；只有所有讨论解决、必要审批完成、必需检查通过才合并”中对第二位人类审批的解释，以及 `V02-SUP-HR`——紧随段落“自动化检查不能替代独立人工审阅……高风险变更必须增加第二位维护者或安全/SRE 审阅后才允许合并”中的仓库合并前置。验证者必须先确认 source path 在 source commit 的 Git blob SHA-1 与上述值一致并定位两个原文锚点；任一不符即 `INCONCLUSIVE`。替代范围不包含这些条款的技术审阅维度、讨论解决、required checks、生产审批、安全门或旧文档的其他内容，也不使其他旧文档自动获得 `ACTIVE` 权威"

PRE_ATTESTATION_COMPONENTS = (
    "pr",
    "paths",
    "metadata",
    "review",
    "discussion",
    "checks",
    "control",
    "identity",
    "security",
    "runner",
    "finding",
)
STABLE_COMPONENTS = (*PRE_ATTESTATION_COMPONENTS, "attestation")
POST_MERGE_COMPONENTS = (*STABLE_COMPONENTS, "merge")
COMPONENT_INVENTORY = {
    "pr": ("pull",),
    "paths": ("candidate-commit", "candidate-tree", "pull-files"),
    "metadata": ("pull-metadata",),
    "review": ("agent-reviews", "github-reviews"),
    "discussion": ("issue-comments", "review-threads"),
    "checks": ("check-runs", "workflow-jobs", "workflow-logs", "workflow-runs"),
    "control": ("action-pins", "branch-protection", "repository-settings", "rulesets", "validator-source", "workflow-blobs"),
    "identity": ("collaborators", "owner-identity"),
    "security": ("security-settings",),
    "runner": ("execution-objects", "runner-provenance", "toolchain-lockfiles"),
    "finding": ("finding-ledger",),
    "attestation": ("attestation-comment", "attestation-payload"),
    "merge": ("main-ref", "merge-commit", "merge-response", "merged-pull", "post-merge-checks", "post-merge-metadata"),
}
LABEL_REQUEST_RULES = {
    "pull": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/pulls/[1-9][0-9]*"),
    "pull-files": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/pulls/[1-9][0-9]*/files"),
    "candidate-commit": ("git", "READ", r"/git/commits/[0-9a-f]{40}"),
    "candidate-tree": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/git/trees/[0-9a-f]{40}"),
    "pull-metadata": ("github-api", "POST", r"/graphql"),
    "agent-reviews": ("agent", "READ", r"/reviews/[0-9a-f]{40}"),
    "github-reviews": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/pulls/[1-9][0-9]*/reviews"),
    "issue-comments": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/issues/[1-9][0-9]*/comments"),
    "review-threads": ("github-api", "POST", r"/graphql"),
    "check-runs": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/commits/[0-9a-f]{40}/check-runs"),
    "workflow-jobs": ("derived", "DERIVE", r"/workflow-jobs"),
    "workflow-logs": ("derived", "DERIVE", r"/workflow-logs"),
    "workflow-runs": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/actions/runs"),
    "action-pins": ("git", "READ", r"/git/action-pins"),
    "branch-protection": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/branches/main/protection"),
    "repository-settings": ("github-api", "GET", r"/repos/ZhangIvan/QingYin"),
    "rulesets": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/rulesets"),
    "validator-source": ("git", "READ", r"/git/validator-source"),
    "workflow-blobs": ("git", "READ", r"/git/workflows"),
    "collaborators": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/collaborators"),
    "owner-identity": ("github-api", "GET", r"/users/ZhangIvan"),
    "security-settings": ("github-api", "GET", r"/repos/ZhangIvan/QingYin"),
    "runner-provenance": ("derived", "DERIVE", r"/runner/provenance"),
    "execution-objects": ("git", "READ", r"/git/execution-objects"),
    "toolchain-lockfiles": ("git", "READ", r"/git/toolchain-lockfiles"),
    "finding-ledger": ("derived", "DERIVE", r"/finding-ledger"),
    "attestation-comment": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/issues/comments/[1-9][0-9]*"),
    "attestation-payload": ("derived", "DERIVE", r"/attestation-payload"),
    "main-ref": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/git/ref/heads/main"),
    "merge-commit": ("git", "READ", r"/git/merge-commit"),
    "merge-response": ("github-api", "PUT", r"/repos/ZhangIvan/QingYin/pulls/[1-9][0-9]*/merge"),
    "merged-pull": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/pulls/[1-9][0-9]*"),
    "post-merge-checks": ("github-api", "GET", r"/repos/ZhangIvan/QingYin/commits/[0-9a-f]{40}/check-runs"),
    "post-merge-metadata": ("github-api", "POST", r"/graphql"),
}
SAMPLE_REQUEST_PATHS = {
    "pull": "/repos/ZhangIvan/QingYin/pulls/19",
    "pull-files": "/repos/ZhangIvan/QingYin/pulls/19/files",
    "candidate-commit": f"/git/commits/{'b' * 40}",
    "candidate-tree": f"/repos/ZhangIvan/QingYin/git/trees/{'c' * 40}",
    "pull-metadata": "/graphql",
    "agent-reviews": f"/reviews/{'b' * 40}",
    "github-reviews": "/repos/ZhangIvan/QingYin/pulls/19/reviews",
    "issue-comments": "/repos/ZhangIvan/QingYin/issues/19/comments",
    "review-threads": "/graphql",
    "check-runs": f"/repos/ZhangIvan/QingYin/commits/{'b' * 40}/check-runs",
    "workflow-jobs": "/workflow-jobs",
    "workflow-logs": "/workflow-logs",
    "workflow-runs": "/repos/ZhangIvan/QingYin/actions/runs",
    "action-pins": "/git/action-pins",
    "branch-protection": "/repos/ZhangIvan/QingYin/branches/main/protection",
    "repository-settings": "/repos/ZhangIvan/QingYin",
    "rulesets": "/repos/ZhangIvan/QingYin/rulesets",
    "validator-source": "/git/validator-source",
    "workflow-blobs": "/git/workflows",
    "collaborators": "/repos/ZhangIvan/QingYin/collaborators",
    "owner-identity": "/users/ZhangIvan",
    "security-settings": "/repos/ZhangIvan/QingYin",
    "runner-provenance": "/runner/provenance",
    "execution-objects": "/git/execution-objects",
    "toolchain-lockfiles": "/git/toolchain-lockfiles",
    "finding-ledger": "/finding-ledger",
    "attestation-comment": "/repos/ZhangIvan/QingYin/issues/comments/1",
    "attestation-payload": "/attestation-payload",
    "main-ref": "/repos/ZhangIvan/QingYin/git/ref/heads/main",
    "merge-commit": "/git/merge-commit",
    "merge-response": "/repos/ZhangIvan/QingYin/pulls/19/merge",
    "merged-pull": "/repos/ZhangIvan/QingYin/pulls/19",
    "post-merge-checks": f"/repos/ZhangIvan/QingYin/commits/{'d' * 40}/check-runs",
    "post-merge-metadata": "/graphql",
}
PAGINATED_ARRAY_LABELS = (
    "pull-files",
    "github-reviews",
    "issue-comments",
    "rulesets",
    "collaborators",
)
PAGINATED_OBJECT_LABELS = {
    "check-runs": "check_runs",
    "workflow-runs": "workflow_runs",
    "post-merge-checks": "check_runs",
}

DEC_MUTABLE_PREFIXES = (
    "- 状态：",
    "- 生效状态：",
    "- `effective_commit`：",
    "- `governance_candidate_head`：",
    "- `governance_merge_commit`：",
    "- `governance_merge_tree`：",
    "- `governance_merge_parent`：",
    "- `governance_postmerge_manifest_sha256`：",
    "- `governance_attestation_sha256`：",
    "- `activation_evidence_pr`：",
)
PLAN_MUTABLE_PREFIXES = ("状态：实施基线；",)
INDEX_MUTABLE_PREFIXES = ("2. [DEC-20260829-001：",)


class GovernanceValidationError(ValueError):
    """A deterministic governance validation failure."""


@dataclass(frozen=True)
class CurrentPRContext:
    base_sha: str
    base_ref: str
    candidate_head: str
    candidate_tree: str
    pr_number: int


def fail(message: str) -> NoReturn:
    raise GovernanceValidationError(message)


def require(value: bool, message: str) -> None:
    if not value:
        fail(message)


def require_positive_int(value: Any, label: str) -> int:
    """Require a non-boolean positive integer within the JSON safe range."""

    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    require(0 < value <= SAFE_INTEGER_LIMIT, f"{label} must be a positive safe integer")
    return value


def require_nonnegative_int(value: Any, label: str) -> int:
    """Require a non-boolean non-negative integer within the JSON safe range."""

    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    require(0 <= value <= SAFE_INTEGER_LIMIT, f"{label} must be a non-negative safe integer")
    return value


def parse_positive_decimal(value: Any, label: str) -> int:
    """Parse an ASCII decimal without allowing unbounded ``int`` conversion."""
    require(
        isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value) is not None,
        f"{label} must be a positive decimal integer",
    )
    require(
        len(value) <= len(str(SAFE_INTEGER_LIMIT)),
        f"{label} must be a positive safe integer",
    )
    return require_positive_int(int(value), label)


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        fail(f"git {' '.join(arguments)} failed: {detail}")
    return result


def validate_utf8_bytes(data: bytes, label: str) -> str:
    require(not data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")), f"BOM forbidden: {label}")
    require(b"\r" not in data, f"CR/CRLF forbidden: {label}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"invalid UTF-8: {label}: {exc}")
    require(unicodedata.normalize("NFC", text) == text, f"non-NFC text: {label}")
    require(not any(0xD800 <= ord(character) <= 0xDFFF for character in text), f"surrogate forbidden: {label}")
    return text


def read_document(relative_path: Path) -> str:
    path = ROOT / relative_path
    require(path.exists(), f"missing governance document: {relative_path}")
    require(path.is_file() and not path.is_symlink(), f"governance document must be a regular file: {relative_path}")
    require(stat.S_IMODE(path.stat().st_mode) & 0o111 == 0, f"governance document must not be executable: {relative_path}")
    return validate_utf8_bytes(path.read_bytes(), str(relative_path))


def git_text_at(commit: str, relative_path: Path) -> str:
    result = git("show", f"{commit}:{relative_path.as_posix()}")
    return validate_utf8_bytes(result.stdout, f"{commit}:{relative_path}")


def extract_one(pattern: str, text: str, label: str) -> str:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    require(len(matches) == 1, f"expected exactly one {label}, found {len(matches)}")
    value = matches[0]
    return value if isinstance(value, str) else value[0]


def validate_dec_header_shape(dec: str) -> None:
    parts = dec.split("\n## 1. 背景与问题\n", maxsplit=1)
    require(len(parts) == 2, "DEC header boundary missing or duplicated")
    header_lines = [line for line in parts[0].splitlines() if line.startswith("- ")]
    require(len(header_lines) == len(DEC_HEADER_PREFIXES), "DEC header field count mismatch")
    counts = {prefix: 0 for prefix in DEC_HEADER_PREFIXES}
    for line in header_lines:
        matches = [prefix for prefix in DEC_HEADER_PREFIXES if line.startswith(prefix)]
        require(len(matches) == 1, f"unknown or ambiguous DEC header field: {line}")
        counts[matches[0]] += 1
    require(all(count == 1 for count in counts.values()), f"missing or duplicate DEC header field: {counts}")
    require(header_lines.count(EXPECTED_SUPERSEDES_LINE) == 1, "supersedes line does not match the frozen decision scope")
    for exact_line in (
        "- 日期：2026-08-29",
        "- 决策所有者：`ZhangIvan`",
        f"- 基线：`main@{SOURCE_COMMIT}`",
    ):
        require(header_lines.count(exact_line) == 1, f"frozen DEC header value mismatch: {exact_line}")


def parse_triplet(dec: str, plan: str, index: str) -> dict[str, str | int]:
    validate_dec_header_shape(dec)
    status = extract_one(r"^- 状态：`(PROPOSED|ACTIVE)`$", dec, "DEC status")
    effective_status = extract_one(r"^- 生效状态：`(PENDING|ACTIVE)`$", dec, "DEC effective status")
    effective_commit = extract_one(
        r"^- `effective_commit`：`(PENDING|[0-9a-f]{40})`$",
        dec,
        "effective_commit",
    )
    governance_pr = parse_positive_decimal(
        extract_one(r"^- `governance_pr`：`#([1-9][0-9]*)`$", dec, "governance_pr"),
        "governance_pr",
    )
    candidate_head = extract_one(r"^- `governance_candidate_head`：`(PENDING|[0-9a-f]{40})`$", dec, "governance_candidate_head")
    merge_commit = extract_one(r"^- `governance_merge_commit`：`(PENDING|[0-9a-f]{40})`$", dec, "governance_merge_commit")
    merge_tree = extract_one(r"^- `governance_merge_tree`：`(PENDING|[0-9a-f]{40})`$", dec, "governance_merge_tree")
    merge_parent = extract_one(r"^- `governance_merge_parent`：`(PENDING|[0-9a-f]{40})`$", dec, "governance_merge_parent")
    governance_postmerge_manifest_sha = extract_one(
        r"^- `governance_postmerge_manifest_sha256`：`(PENDING|[0-9a-f]{64})`$",
        dec,
        "governance_postmerge_manifest_sha256",
    )
    governance_attestation_sha = extract_one(
        r"^- `governance_attestation_sha256`：`(PENDING|[0-9a-f]{64})`$",
        dec,
        "governance_attestation_sha256",
    )
    governance_validator_blob = extract_one(
        r"^- `governance_validator_blob_git_sha1`：`(PENDING|[0-9a-f]{40})`$",
        dec,
        "governance_validator_blob_git_sha1",
    )
    activation_value = extract_one(
        r"^- `activation_evidence_pr`：`(PENDING|#[1-9][0-9]*)`$",
        dec,
        "activation_evidence_pr",
    )
    require(governance_pr == EXPECTED_GOVERNANCE_PR, f"governance_pr must be #{EXPECTED_GOVERNANCE_PR}")

    if status == "PROPOSED":
        require(effective_status == "PENDING", "PROPOSED requires effective=PENDING")
        require(effective_commit == "PENDING", "PROPOSED requires effective_commit=PENDING")
        require(
            all(
                value == "PENDING"
                for value in (
                    candidate_head,
                    merge_commit,
                    merge_tree,
                    merge_parent,
                    governance_postmerge_manifest_sha,
                    governance_attestation_sha,
                )
            ),
            "PROPOSED requires all governance/activation evidence pointers PENDING",
        )
        require(activation_value == "PENDING", "PROPOSED requires activation_evidence_pr=PENDING")
        label = "PROPOSED / effective=PENDING"
        activation_pr = 0
    else:
        require(effective_status == "ACTIVE", "ACTIVE requires effective status ACTIVE")
        require(re.fullmatch(r"[0-9a-f]{40}", effective_commit) is not None, "ACTIVE requires a lowercase 40-hex effective_commit")
        require(effective_commit == merge_commit, "ACTIVE requires effective_commit == governance_merge_commit")
        require(all(re.fullmatch(r"[0-9a-f]{40}", value) is not None for value in (candidate_head, merge_tree, merge_parent)), "ACTIVE requires candidate/tree/parent 40-hex pointers")
        require(
            all(
                re.fullmatch(r"[0-9a-f]{64}", value) is not None
                for value in (governance_postmerge_manifest_sha, governance_attestation_sha)
            ),
            "ACTIVE requires governance post-merge manifest/attestation SHA-256 pointers",
        )
        require(re.fullmatch(r"#[1-9][0-9]*", activation_value) is not None, "ACTIVE requires activation_evidence_pr=#N")
        require(re.fullmatch(r"[0-9a-f]{40}", governance_validator_blob) is not None, "ACTIVE requires an immutable validator Git blob")
        label = f"ACTIVE / effective={effective_commit}"
        activation_pr = parse_positive_decimal(activation_value[1:], "activation_evidence_pr")
        require(activation_pr != EXPECTED_GOVERNANCE_PR, "activation evidence PR must be distinct from governance bootstrap PR #19")

    plan_label = extract_one(
        r"^状态：实施基线；\[DEC-20260829-001\]\(QingYin_DEC-20260829-001_单维护者合并治理\.md\) 为 `([^`]+)`$",
        plan,
        "plan state label",
    )
    index_label = extract_one(
        r"^2\. \[DEC-20260829-001：单维护者合并治理（([^）]+)）\]\(QingYin_DEC-20260829-001_单维护者合并治理\.md\)$",
        index,
        "index state label",
    )
    require(plan_label == label, f"plan state mismatch: expected {label!r}, got {plan_label!r}")
    require(index_label == label, f"index state mismatch: expected {label!r}, got {index_label!r}")
    return {
        "status": status,
        "effective_status": effective_status,
        "effective_commit": effective_commit,
        "governance_pr": governance_pr,
        "candidate_head": candidate_head,
        "merge_commit": merge_commit,
        "merge_tree": merge_tree,
        "merge_parent": merge_parent,
        "governance_postmerge_manifest_sha": governance_postmerge_manifest_sha,
        "governance_attestation_sha": governance_attestation_sha,
        "governance_validator_blob": governance_validator_blob,
        "activation_pr": activation_pr,
        "label": label,
    }


def validate_index_modes() -> None:
    for relative_path in (*BOOTSTRAP_PATHS, Path("Cargo.lock"), Path("rust-toolchain.toml")):
        absolute_path = ROOT / relative_path
        require(not absolute_path.is_symlink() and absolute_path.is_file(), f"expected regular non-symlink file: {relative_path}")
        require(stat.S_IMODE(absolute_path.stat().st_mode) & 0o111 == 0, f"file must not be executable: {relative_path}")
        validate_utf8_bytes(absolute_path.read_bytes(), str(relative_path))
        result = git("ls-files", "--stage", "--", relative_path.as_posix())
        line = result.stdout.decode("utf-8", errors="strict").strip()
        if not line:
            require(relative_path == VALIDATOR_PATH, f"required control file is not tracked: {relative_path}")
            continue
        fields = line.split(maxsplit=3)
        require(len(fields) == 4 and fields[0] == "100644", f"expected tracked 100644 regular file: {relative_path}: {line}")


def require_main_base(base_ref: str | None, label: str) -> None:
    require(base_ref == "main", f"{label} must target base.ref=main, got {base_ref!r}")


def require_governance_bootstrap_base(base_sha: str) -> None:
    require(base_sha == SOURCE_COMMIT, "governance bootstrap base must equal frozen source commit")


def tree_entry(commit: str, relative_path: Path, required: bool = True) -> tuple[str, str, str] | None:
    line = git("-c", "core.quotePath=false", "ls-tree", commit, "--", relative_path.as_posix()).stdout.decode("utf-8").strip()
    if not line:
        require(not required, f"missing Git tree entry: {commit}:{relative_path}")
        return None
    fields = line.split(maxsplit=3)
    require(len(fields) == 4, f"invalid Git tree entry: {commit}:{relative_path}: {line}")
    mode, object_type, object_id, path = fields
    require(path == relative_path.as_posix(), f"unexpected Git tree path: {commit}:{relative_path}: {line}")
    return mode, object_type, object_id


def cumulative_name_status(base_sha: str) -> dict[Path, str]:
    output = git(
        "-c",
        "core.quotePath=false",
        "diff",
        "--name-status",
        "--no-renames",
        f"{base_sha}..HEAD",
    ).stdout.decode("utf-8")
    entries: dict[Path, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        require(len(fields) == 2, f"invalid name-status entry: {line}")
        status, path = fields
        relative_path = Path(path)
        require(relative_path not in entries, f"duplicate changed path: {path}")
        entries[relative_path] = status
    return entries


def reachable_history_changes(base_sha: str, target_sha: str) -> list[tuple[str, Path, str, str, str]]:
    require(git("merge-base", "--is-ancestor", base_sha, target_sha, check=False).returncode == 0, f"history base is not an ancestor: {base_sha}..{target_sha}")
    commits = git("rev-list", "--reverse", "--topo-order", f"{base_sha}..{target_sha}").stdout.decode("ascii").splitlines()
    changes: list[tuple[str, Path, str, str, str]] = []
    for commit in commits:
        output = git(
            "-c",
            "core.quotePath=false",
            "diff-tree",
            "-m",
            "--root",
            "-r",
            "--no-commit-id",
            "--raw",
            "--no-renames",
            commit,
        ).stdout.decode("utf-8")
        for line in output.splitlines():
            match = re.fullmatch(r":([0-7]{6}) ([0-7]{6}) [0-9a-f]+ [0-9a-f]+ ([A-Z][0-9]*)\t(.+)", line)
            require(match is not None, f"invalid raw history entry at {commit}: {line}")
            old_mode, new_mode, status, path = match.groups()
            changes.append((commit, Path(path), old_mode, new_mode, status))
    return changes


def validate_history_allowlist(base_sha: str, target_sha: str, allowed_paths: set[Path], label: str) -> None:
    for commit, path, old_mode, new_mode, status in reachable_history_changes(base_sha, target_sha):
        require(path in allowed_paths, f"{label} history touched an out-of-scope path: {commit}:{path}")
        require(old_mode in ("000000", "100644") and new_mode in ("000000", "100644"), f"{label} history used a forbidden mode/type: {commit}:{path}:{old_mode}->{new_mode}")
        require(status[:1] in ("A", "M", "D"), f"{label} history used a forbidden change type: {commit}:{path}:{status}")


def validate_history_forbidden_paths(base_sha: str, target_sha: str, forbidden_paths: set[Path], label: str) -> None:
    for commit, path, _, _, _ in reachable_history_changes(base_sha, target_sha):
        require(path not in forbidden_paths, f"{label} history touched a frozen control even though the net diff may hide it: {commit}:{path}")


def validate_bootstrap_diff(base_sha: str) -> None:
    validate_history_allowlist(base_sha, "HEAD", set(BOOTSTRAP_PATHS), "governance bootstrap")
    entries = cumulative_name_status(base_sha)
    require(entries == BOOTSTRAP_STATUS, f"governance bootstrap diff mismatch: {entries}")
    for relative_path, expected_status in BOOTSTRAP_STATUS.items():
        current_entry = tree_entry("HEAD", relative_path)
        require(current_entry is not None and current_entry[:2] == ("100644", "blob"), f"bootstrap file must be a 100644 blob: {relative_path}")
        base_entry = tree_entry(base_sha, relative_path, required=expected_status != "A")
        if expected_status == "A":
            require(base_entry is None, f"bootstrap added path already exists in base: {relative_path}")
        else:
            require(base_entry is not None and base_entry[:2] == ("100644", "blob"), f"bootstrap base file must be a 100644 blob: {relative_path}")


def require_active_dec_immutable(current_status: str | int, base_dec: str, current_dec: str) -> None:
    require(current_status == "ACTIVE", "an ACTIVE DEC cannot be downgraded or redirected")
    require(current_dec == base_dec, "an ACTIVE DEC is immutable; use a new superseding DEC")


def validate_first_parent_lineage_untouched(effective_commit: str, base_sha: str) -> None:
    resolved_effective = git("rev-parse", f"{effective_commit}^{{commit}}").stdout.decode("ascii").strip()
    resolved_base = git("rev-parse", f"{base_sha}^{{commit}}").stdout.decode("ascii").strip()
    first_parent_chain = git("rev-list", "--first-parent", resolved_base).stdout.decode("ascii").splitlines()
    require(resolved_effective in first_parent_chain, "effective_commit must be on activation base first-parent history")
    validate_history_forbidden_paths(
        resolved_effective,
        resolved_base,
        set(BOOTSTRAP_PATHS),
        "post-bootstrap activation lineage",
    )


def validate_source_binding(dec: str) -> None:
    source_path = extract_one(r"^- `superseded_source_path`：`([^`]+)`$", dec, "superseded source path")
    source_commit = extract_one(r"^- `superseded_source_commit`：`([0-9a-f]{40})`$", dec, "superseded source commit")
    source_blob = extract_one(r"^- `superseded_source_blob_git_sha1`：`([0-9a-f]{40})`$", dec, "superseded source blob")
    require(source_path == PLAN_PATH.as_posix(), "unexpected superseded source path")
    require(source_commit == SOURCE_COMMIT, "unexpected superseded source commit")
    require(source_blob == SOURCE_BLOB, "unexpected superseded source blob")
    actual_blob = git("rev-parse", f"{source_commit}:{source_path}").stdout.decode("ascii").strip()
    require(actual_blob == source_blob, f"superseded source blob mismatch: {actual_blob}")
    source_text = git_text_at(source_commit, Path(source_path))
    for anchor in SOURCE_ANCHORS:
        require(anchor in source_text, f"superseded source anchor missing: {anchor}")
    residual_markers = RESIDUAL_IDS
    for index, finding_id in enumerate(residual_markers):
        start_marker = f"当前透明 residual `{finding_id}`"
        require(dec.count(start_marker) == 1, f"residual section marker must appear exactly once: {finding_id}")
        start = dec.find(start_marker)
        require(start >= 0, f"missing residual section: {finding_id}")
        if index + 1 < len(residual_markers):
            end = dec.find(f"当前透明 residual `{residual_markers[index + 1]}`", start + 1)
        else:
            end = dec.find("\n## 6. 独立审阅协议", start + 1)
        require(end > start, f"invalid residual section boundary: {finding_id}")
        section = dec[start:end]
        require(hashlib.sha256(section.encode("utf-8")).hexdigest() == RESIDUAL_SECTION_SHA256[finding_id], f"residual section bytes drifted: {finding_id}")
        fields = re.findall(r"^- `([^`]+)`：(.+)$", section, flags=re.MULTILINE)
        require(tuple(name for name, _ in fields) == RESIDUAL_FIELD_ORDER[finding_id], f"residual field order/set mismatch: {finding_id}")
        require(all(value.strip() for _, value in fields), f"empty residual field: {finding_id}")
        field_map = dict(fields)
        require(field_map["status"].startswith("`Accepted-Residual`"), f"residual status mismatch: {finding_id}")
        require(field_map["accepted_by"].startswith("`ZhangIvan`"), f"residual owner mismatch: {finding_id}")
        require(field_map["scope"] == RESIDUAL_SCOPES[finding_id], f"residual scope mismatch: {finding_id}")
        expiries = re.findall(r"^- `valid_until`：`([^`]+)`。$", section, flags=re.MULTILINE)
        require(expiries == [RESIDUAL_VALID_UNTIL], f"residual expiry mismatch: {finding_id}: {expiries}")
        require_utc_timestamp(expiries[0], f"residual {finding_id} valid_until")


def normalize_frozen(text: str, prefixes: tuple[str, ...], label: str) -> str:
    counts = {prefix: 0 for prefix in prefixes}
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        plain = line.removesuffix("\n")
        matching = [prefix for prefix in prefixes if plain.startswith(prefix)]
        require(len(matching) <= 1, f"ambiguous mutable line in {label}: {plain}")
        if matching:
            prefix = matching[0]
            counts[prefix] += 1
            output.append(f"{prefix}<MUTABLE>\n" if line.endswith("\n") else f"{prefix}<MUTABLE>")
        else:
            output.append(line)
    missing_or_duplicate = {prefix: count for prefix, count in counts.items() if count != 1}
    require(not missing_or_duplicate, f"mutable line count mismatch in {label}: {missing_or_duplicate}")
    return "".join(output)


def validate_activation_diff(
    base_sha: str,
    base_ref: str | None,
    pr_number: int,
    current: dict[str, str | int],
) -> None:
    if current["status"] == "PROPOSED" and pr_number == EXPECTED_GOVERNANCE_PR:
        require_governance_bootstrap_base(base_sha)
    base_exists = git("cat-file", "-e", f"{base_sha}:{DEC_PATH.as_posix()}", check=False).returncode == 0
    if not base_exists:
        require(current["status"] == "PROPOSED", "a new governance decision must begin PROPOSED")
        require_main_base(base_ref, "governance bootstrap")
        require(pr_number == EXPECTED_GOVERNANCE_PR, f"governance bootstrap must be PR #{EXPECTED_GOVERNANCE_PR}")
        validate_bootstrap_diff(base_sha)
        return

    base_dec = git_text_at(base_sha, DEC_PATH)
    base_plan = git_text_at(base_sha, PLAN_PATH)
    base_index = git_text_at(base_sha, INDEX_PATH)
    base = parse_triplet(base_dec, base_plan, base_index)
    entries = cumulative_name_status(base_sha)
    if base["status"] == "ACTIVE":
        require_main_base(base_ref, "ACTIVE governance PR")
        require_active_dec_immutable(current["status"], base_dec, read_document(DEC_PATH))
        frozen_controls = {WORKFLOW_PATH, RUST_WORKFLOW_PATH, DEC_PATH, VALIDATOR_PATH}
        require(not frozen_controls.intersection(entries), f"ACTIVE governance controls are immutable; use a superseding DEC: {entries}")
        validate_history_forbidden_paths(base_sha, "HEAD", frozen_controls, "ACTIVE governance")
        return
    require(base["status"] == "PROPOSED", "activation base must be PROPOSED")
    if current["status"] != "ACTIVE":
        require(not set(BOOTSTRAP_PATHS).intersection(entries), f"PROPOSED governance controls cannot drift before activation: {entries}")
        validate_history_forbidden_paths(base_sha, "HEAD", set(BOOTSTRAP_PATHS), "PROPOSED governance")
        return
    require_main_base(base_ref, "governance activation")
    require_positive_int(pr_number, "ACTIVE transition PR number")
    require(current["activation_pr"] == pr_number, "activation_evidence_pr must equal current PR number")

    expected_entries = {path: "M" for path in GOVERNANCE_PATHS}
    require(entries == expected_entries, f"activation diff must contain exactly three modified governance files: {entries}")
    validate_history_allowlist(base_sha, "HEAD", set(GOVERNANCE_PATHS), "governance activation")
    require(not git("diff", "--summary", f"{base_sha}..HEAD").stdout, "activation diff contains rename/mode/type changes")

    for relative_path in GOVERNANCE_PATHS:
        for commit in (base_sha, "HEAD"):
            entry = tree_entry(commit, relative_path)
            require(
                entry is not None and entry[:2] == ("100644", "blob"),
                f"activation file must remain a 100644 blob: {commit}:{relative_path}: {entry}",
            )

    current_dec = read_document(DEC_PATH)
    current_plan = read_document(PLAN_PATH)
    current_index = read_document(INDEX_PATH)
    comparisons = (
        (base_dec, current_dec, DEC_MUTABLE_PREFIXES, str(DEC_PATH)),
        (base_plan, current_plan, PLAN_MUTABLE_PREFIXES, str(PLAN_PATH)),
        (base_index, current_index, INDEX_MUTABLE_PREFIXES, str(INDEX_PATH)),
    )
    for old, new, prefixes, label in comparisons:
        require(normalize_frozen(old, prefixes, label) == normalize_frozen(new, prefixes, label), f"activation changed frozen bytes: {label}")

    effective_commit = str(current["effective_commit"])
    require(git("cat-file", "-t", effective_commit).stdout == b"commit\n", "effective_commit must name a Git commit")
    require(git("merge-base", "--is-ancestor", effective_commit, base_sha, check=False).returncode == 0, "effective_commit must be an ancestor of the activation base")
    validate_first_parent_lineage_untouched(effective_commit, base_sha)
    for relative_path in BOOTSTRAP_PATHS:
        effective_entry = tree_entry(effective_commit, relative_path)
        base_entry = tree_entry(base_sha, relative_path)
        require(
            effective_entry == base_entry,
            f"governance control drifted between effective_commit and activation base: {relative_path}",
        )
    effective_dec = git_text_at(effective_commit, DEC_PATH)
    require(extract_one(r"^- 状态：`(PROPOSED|ACTIVE)`$", effective_dec, "effective DEC status") == "PROPOSED", "effective_commit must contain the merged PROPOSED governance decision")
    effective_governance_pr = parse_positive_decimal(
        extract_one(r"^- `governance_pr`：`#([1-9][0-9]*)`$", effective_dec, "effective governance_pr"),
        "effective governance_pr",
    )
    require(effective_governance_pr == EXPECTED_GOVERNANCE_PR, "effective_commit governance_pr mismatch")
    require(git("rev-parse", f"{effective_commit}^{{tree}}").stdout.decode("ascii").strip() == current["merge_tree"], "governance_merge_tree mismatch")
    require(git("rev-parse", f"{effective_commit}^").stdout.decode("ascii").strip() == current["merge_parent"], "governance_merge_parent mismatch")


def validate_scalar(value: Any, label: str) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        require(-SAFE_INTEGER_LIMIT <= value <= SAFE_INTEGER_LIMIT, f"integer outside IEEE-754 safe range: {label}")
        return
    if isinstance(value, float):
        fail(f"floating-point values are forbidden in gvn-manifest-v1: {label}")
    if isinstance(value, str):
        require(unicodedata.normalize("NFC", value) == value, f"non-NFC string: {label}")
        require(not any(0xD800 <= ord(character) <= 0xDFFF for character in value), f"surrogate forbidden: {label}")
        return
    fail(f"unsupported canonical scalar at {label}: {type(value).__name__}")


def utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be")


StableOrderComponent = tuple[int, int | bytes]
StableOrderKey = tuple[StableOrderComponent, ...]


def stable_integer_component(value: Any, label: str) -> StableOrderComponent:
    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    validate_scalar(value, label)
    return (0, value)


def stable_string_component(value: Any, label: str) -> StableOrderComponent:
    require(isinstance(value, str) and value != "", f"{label} must be a non-empty string")
    validate_scalar(value, label)
    return (1, utf16_sort_key(value))


def derive_stable_array_view(
    values: Any,
    label: str,
    primary_key: Callable[[Any, int], StableOrderKey],
    unique_key: Callable[[Any, int], StableOrderKey] | None = None,
) -> list[Any]:
    """Validate an unordered array and return a stable, non-mutating view.

    Sort and uniqueness keys are schema-specific. The complete canonical item is a
    deterministic final tie-break, but never masks duplicate immutable identities.
    The input list and its items remain in their provider-native order so the raw
    response bytes and hashes continue to describe exactly what was captured.
    """

    require(isinstance(values, list), f"{label} must be an array")
    seen: set[StableOrderKey] = set()
    decorated: list[tuple[StableOrderKey, Any]] = []
    for index, item in enumerate(values):
        key = primary_key(item, index)
        require(isinstance(key, tuple) and key, f"{label}[{index}] stable primary key missing")
        identity = key if unique_key is None else unique_key(item, index)
        require(isinstance(identity, tuple) and identity, f"{label}[{index}] stable unique key missing")
        require(identity not in seen, f"{label} contains a duplicate stable unique key")
        seen.add(identity)
        order_key = (*key, (2, canonical_json_v1(item, f"{label}[{index}]")))
        decorated.append((order_key, item))
    return [item for _, item in sorted(decorated, key=lambda entry: entry[0])]


def require_stable_array_order(
    values: Any,
    label: str,
    primary_key: Callable[[Any, int], StableOrderKey],
    unique_key: Callable[[Any, int], StableOrderKey] | None = None,
) -> None:
    """Require a collector-derived array to use its frozen canonical order."""

    stable_view = derive_stable_array_view(values, label, primary_key, unique_key)
    require(values == stable_view, f"{label} must be in stable canonical order")


def canonical_json_v1(value: Any, label: str = "root") -> bytes:
    if isinstance(value, dict):
        keys = list(value)
        require(all(isinstance(key, str) for key in keys), f"object keys must be strings: {label}")
        normalized = [unicodedata.normalize("NFC", key) for key in keys]
        require(len(set(normalized)) == len(normalized), f"duplicate/NFC-colliding keys: {label}")
        for key in keys:
            validate_scalar(key, f"{label}.<key>")
        parts = []
        for key in sorted(keys, key=utf16_sort_key):
            key_bytes = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            parts.append(key_bytes + b":" + canonical_json_v1(value[key], f"{label}.{key}"))
        return b"{" + b",".join(parts) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(canonical_json_v1(item, f"{label}[{index}]") for index, item in enumerate(value)) + b"]"
    validate_scalar(value, label)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalized_keys: set[str] = set()
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        normalized = unicodedata.normalize("NFC", key)
        require(normalized not in normalized_keys, f"NFC-colliding JSON key: {key}")
        normalized_keys.add(normalized)
        result[key] = value
    return result


def parse_json_integer(value: str) -> int:
    """Parse a JSON integer without unbounded conversion or bare ValueError."""

    if value == "-0":
        fail("negative zero is forbidden")
    digits = value[1:] if value.startswith("-") else value
    require(
        len(digits) <= len(str(SAFE_INTEGER_LIMIT)),
        "integer outside IEEE-754 safe range",
    )
    try:
        parsed = int(value)
    except (ValueError, OverflowError) as exc:
        fail(f"invalid JSON integer: {exc}")
    require(-SAFE_INTEGER_LIMIT <= parsed <= SAFE_INTEGER_LIMIT, "integer outside IEEE-754 safe range")
    return parsed


def parse_json_strict(source: str) -> Any:
    return json.loads(
        source,
        object_pairs_hook=strict_object,
        parse_int=parse_json_integer,
        parse_float=lambda value: fail(f"floating-point JSON value forbidden: {value}"),
        parse_constant=lambda value: fail(f"non-finite JSON value forbidden: {value}"),
    )


def require_exact_object(value: Any, keys: tuple[str, ...], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == set(keys), f"{label} key mismatch: expected={keys}, actual={tuple(value)}")
    return value


def require_sha256(value: Any, label: str) -> None:
    require(isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None, f"{label} must be lowercase SHA-256")


def require_sha1(value: Any, label: str) -> None:
    require(isinstance(value, str) and SHA1_PATTERN.fullmatch(value) is not None, f"{label} must be lowercase 40-hex Git SHA")


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def require_utc_timestamp(value: Any, label: str) -> None:
    require(isinstance(value, str) and RFC3339_UTC_PATTERN.fullmatch(value) is not None, f"{label} must be second-precision RFC3339 UTC")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        fail(f"{label} is not a real UTC calendar timestamp: {exc}")


def require_sorted_unique_strings(value: Any, label: str) -> list[str]:
    require(isinstance(value, list) and all(isinstance(item, str) for item in value), f"{label} must be a string array")
    require(len(set(value)) == len(value), f"{label} contains duplicates")
    require(value == sorted(value, key=utf16_sort_key), f"{label} must use UTF-16 code-unit order")
    return value


def validate_named_digests(value: Any, expected_names: tuple[str, ...], label: str) -> None:
    require(isinstance(value, list) and len(value) == len(expected_names), f"{label} cardinality mismatch")
    actual_names: list[str] = []
    for index, item in enumerate(value):
        entry = require_exact_object(item, ("name", "endpoint_bundle_sha256"), f"{label}[{index}]")
        require(isinstance(entry["name"], str), f"{label}[{index}].name must be a string")
        require_sha256(entry["endpoint_bundle_sha256"], f"{label}[{index}].endpoint_bundle_sha256")
        actual_names.append(entry["name"])
    require(tuple(actual_names) == expected_names, f"{label} component order mismatch: {actual_names}")


def validate_request_v1(value: Any) -> None:
    request = require_exact_object(value, ("schema", "source", "method", "authority", "path", "query", "body"), "evidence request")
    require(request["schema"] == "gvn-request-v1", "request schema mismatch")
    require(request["source"] in ("github-api", "git", "agent", "derived"), "request source invalid")
    require(isinstance(request["path"], str) and request["path"].startswith("/") and "?" not in request["path"], "request path invalid")
    query = request["query"]
    require(isinstance(query, list), "request query must be an array")
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(query):
        require(isinstance(item, list) and len(item) == 2 and all(isinstance(part, str) for part in item), f"request query[{index}] must be a string pair")
        pairs.append((item[0], item[1]))
    require(len(set(pairs)) == len(pairs), "request query contains duplicate pairs")
    require(pairs == sorted(pairs, key=lambda item: (utf16_sort_key(item[0]), utf16_sort_key(item[1]))), "request query is not canonically sorted")
    if request["source"] == "github-api":
        require(request["authority"] == "api.github.com", "GitHub request authority mismatch")
        require(request["method"] in ("GET", "POST", "PUT"), "GitHub request method invalid")
        if request["method"] == "GET":
            require(request["body"] is None, "GET request body must be null")
        else:
            require(isinstance(request["body"], (dict, list)), "POST/PUT request body preimage must be embedded JSON")
    else:
        expected = {
            "git": ("ZhangIvan/QingYin", "READ"),
            "agent": ("codex-orchestrator", "READ"),
            "derived": ("local", "DERIVE"),
        }[str(request["source"])]
        require((request["authority"], request["method"]) == expected, f"{request['source']} request authority/method mismatch")
        if request["source"] in ("git", "agent"):
            require(request["body"] is None, f"{request['source']} request body must be null")
        else:
            require(isinstance(request["body"], (dict, list)), "derived request body must embed its canonical input")


def canonical_human_body_id(value: Any, label: str) -> str:
    """Return one unambiguous text representation for an immutable API id."""

    if isinstance(value, int) and not isinstance(value, bool):
        return str(require_positive_int(value, label))
    require(isinstance(value, str) and value.strip() == value and value, f"{label} must be a non-empty immutable id")
    validate_scalar(value, label)
    return value


def human_body_hash_entry(kind: str, immutable_id: Any, value: dict[str, Any], label: str) -> dict[str, Any]:
    body_state = "missing" if "body" not in value else "null" if value["body"] is None else "string" if isinstance(value["body"], str) else "invalid"
    require(body_state != "invalid", f"{label}.body must be missing, null, or a string")
    body_sha256 = hashlib.sha256(value["body"].encode("utf-8")).hexdigest() if body_state == "string" else None
    return {
        "kind": kind,
        "immutable_id": canonical_human_body_id(immutable_id, f"{label} immutable id"),
        "field": "body",
        "state": body_state,
        "sha256": body_sha256,
    }


def derive_human_body_hashes(label: str, response_value_item: Any) -> list[dict[str, Any]]:
    """Derive field-level hashes from the decoded raw response without rewriting it."""

    values: list[dict[str, Any]] = []
    if label == "pull":
        require(isinstance(response_value_item, dict), "pull body hash source must be an object")
        values.append(human_body_hash_entry("pull-rest", response_value_item.get("id"), response_value_item, "pull"))
    elif label in ("pull-metadata", "post-merge-metadata"):
        require(isinstance(response_value_item, dict), f"{label} body hash source must be an object")
        data = response_value_item.get("data")
        require(isinstance(data, dict), f"{label} body hash source data must be an object")
        repository = data.get("repository")
        require(isinstance(repository, dict), f"{label} body hash source repository must be an object")
        pull_request = repository.get("pullRequest")
        require(isinstance(pull_request, dict), f"{label} body hash source pullRequest must be an object")
        kind = "pull-metadata-graphql" if label == "pull-metadata" else "post-merge-metadata-graphql"
        values.append(human_body_hash_entry(kind, pull_request.get("id"), pull_request, label))
    elif label == "github-reviews":
        require(isinstance(response_value_item, list), "github-reviews body hash source must be an array")
        for index, review in enumerate(response_value_item):
            require(isinstance(review, dict), f"github-review body hash source[{index}] must be an object")
            values.append(human_body_hash_entry("github-review-rest", review.get("id"), review, f"github-review[{index}]"))
    elif label == "review-threads":
        require(isinstance(response_value_item, dict), "review-thread body hash source must be an object")
        data = response_value_item.get("data")
        require(isinstance(data, dict), "review-thread body hash source data must be an object")
        repository = data.get("repository")
        require(isinstance(repository, dict), "review-thread body hash source repository must be an object")
        pull_request = repository.get("pullRequest")
        require(isinstance(pull_request, dict), "review-thread body hash source pullRequest must be an object")
        review_threads = pull_request.get("reviewThreads")
        require(isinstance(review_threads, dict), "review-thread body hash source reviewThreads must be an object")
        nodes = review_threads.get("nodes")
        require(isinstance(nodes, list), "review-thread body hash source nodes must be an array")
        for thread_index, thread in enumerate(nodes):
            require(isinstance(thread, dict), f"review-thread body hash source[{thread_index}] must be an object")
            comments = thread.get("comments")
            require(isinstance(comments, dict), f"review-thread body hash comments[{thread_index}] must be an object")
            comment_nodes = comments.get("nodes")
            require(isinstance(comment_nodes, list), f"review-thread body hash comments[{thread_index}] must be an array")
            for comment_index, comment in enumerate(comment_nodes):
                require(isinstance(comment, dict), f"review-thread body hash comment[{thread_index}:{comment_index}] must be an object")
                values.append(
                    human_body_hash_entry(
                        "review-thread-comment-graphql",
                        comment.get("id"),
                        comment,
                        f"review-thread comment[{thread_index}:{comment_index}]",
                    )
                )
    elif label == "issue-comments":
        require(isinstance(response_value_item, list), "issue-comments body hash source must be an array")
        for index, comment in enumerate(response_value_item):
            require(isinstance(comment, dict), f"issue-comment body hash source[{index}] must be an object")
            values.append(human_body_hash_entry("issue-comment-rest", comment.get("id"), comment, f"issue-comment[{index}]"))
    elif label == "attestation-comment":
        require(isinstance(response_value_item, dict), "attestation-comment body hash source must be an object")
        values.append(human_body_hash_entry("attestation-comment-rest", response_value_item.get("id"), response_value_item, "attestation-comment"))

    values.sort(key=lambda item: (utf16_sort_key(item["kind"]), utf16_sort_key(item["immutable_id"])))
    keys = [(item["kind"], item["immutable_id"]) for item in values]
    require(len(keys) == len(set(keys)), f"duplicate human body immutable id in {label}")
    return values


def validate_human_body_hashes(value: Any, label: str) -> list[dict[str, Any]]:
    require(isinstance(value, list), f"{label} must be an array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        entry = require_exact_object(item, ("kind", "immutable_id", "field", "state", "sha256"), f"{label}[{index}]")
        require(
            entry["kind"]
            in (
                "pull-rest",
                "pull-metadata-graphql",
                "post-merge-metadata-graphql",
                "github-review-rest",
                "review-thread-comment-graphql",
                "issue-comment-rest",
                "attestation-comment-rest",
            ),
            f"{label}[{index}].kind invalid",
        )
        require(isinstance(entry["immutable_id"], str), f"{label}[{index}].immutable_id must be a string")
        canonical_human_body_id(entry["immutable_id"], f"{label}[{index}].immutable_id")
        if entry["kind"] in ("pull-rest", "github-review-rest", "issue-comment-rest", "attestation-comment-rest"):
            require(re.fullmatch(r"[1-9][0-9]*", entry["immutable_id"]) is not None, f"{label}[{index}].immutable_id must be an unpadded REST decimal id")
        require(entry["field"] == "body", f"{label}[{index}].field must be body")
        require(entry["state"] in ("missing", "null", "string"), f"{label}[{index}].state invalid")
        if entry["state"] == "string":
            require_sha256(entry["sha256"], f"{label}[{index}].sha256")
        else:
            require(entry["sha256"] is None, f"{label}[{index}].sha256 must be null for {entry['state']}")
        normalized.append(entry)
    keys = [(item["kind"], item["immutable_id"]) for item in normalized]
    require(len(keys) == len(set(keys)), f"{label} contains duplicate kind/id pairs")
    require(keys == sorted(keys, key=lambda item: (utf16_sort_key(item[0]), utf16_sort_key(item[1]))), f"{label} is not canonically sorted")
    return normalized


def validate_endpoint_bundle_v3(value: Any) -> None:
    bundle = require_exact_object(value, ("schema", "component", "responses"), "endpoint bundle")
    require(bundle["schema"] == "gvn-endpoint-bundle-v3", "endpoint bundle schema mismatch")
    allowed_components = set(POST_MERGE_COMPONENTS)
    require(bundle["component"] in allowed_components, f"unknown endpoint bundle component: {bundle['component']!r}")
    responses = bundle["responses"]
    require(isinstance(responses, list) and responses, "endpoint bundle responses must be non-empty")
    labels: list[str] = []
    tuples: list[tuple[str, str, str, str]] = []
    for index, item in enumerate(responses):
        response = require_exact_object(
            item,
            (
                "label",
                "request",
                "request_canonical_sha256",
                "response_status",
                "response_media_type",
                "response_body_base64",
                "response_body_sha256",
                "response_canonical_sha256",
                "human_body_hashes",
            ),
            f"endpoint bundle response[{index}]",
        )
        require(isinstance(response["label"], str) and response["label"], f"response[{index}].label must be non-empty")
        validate_request_v1(response["request"])
        request_rule = LABEL_REQUEST_RULES.get(response["label"])
        require(request_rule is not None, f"response[{index}] has unknown inventory label: {response['label']}")
        expected_source, expected_method, expected_path = request_rule
        require(
            response["request"]["source"] == expected_source
            and response["request"]["method"] == expected_method
            and re.fullmatch(expected_path, response["request"]["path"]) is not None,
            f"response[{index}] request does not match inventory rule for {response['label']}",
        )
        require_sha256(response["request_canonical_sha256"], f"response[{index}].request_canonical_sha256")
        actual_request_sha = hashlib.sha256(canonical_json_v1(response["request"])).hexdigest()
        require(response["request_canonical_sha256"] == actual_request_sha, f"response[{index}] request hash mismatch")
        require_positive_int(response["response_status"], f"response[{index}].response_status")
        require(response["response_status"] == 200, f"response[{index}] must record an exact successful status 200")
        require(
            response["response_media_type"] in ("application/json", "application/zip", "application/octet-stream", "text/plain; charset=utf-8"),
            f"response[{index}].response_media_type unsupported",
        )
        require(isinstance(response["response_body_base64"], str), f"response[{index}].response_body_base64 must be a string")
        try:
            response_bytes = base64.b64decode(response["response_body_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            fail(f"response[{index}] invalid base64 body: {exc}")
        require_sha256(response["response_body_sha256"], f"response[{index}].response_body_sha256")
        require_sha256(response["response_canonical_sha256"], f"response[{index}].response_canonical_sha256")
        require(response["response_body_sha256"] == hashlib.sha256(response_bytes).hexdigest(), f"response[{index}] raw body hash mismatch")
        response_value_item: Any = None
        human_labels = {
            "pull",
            "pull-metadata",
            "post-merge-metadata",
            "github-reviews",
            "review-threads",
            "issue-comments",
            "attestation-comment",
        }
        if response["label"] in human_labels:
            require(response["response_media_type"] == "application/json", f"response[{index}] human body source must use application/json")
        if response["response_media_type"] == "application/json":
            response_text = validate_utf8_bytes(response_bytes, f"response[{index}] JSON body")
            response_value_item = parse_json_strict(response_text)
            actual_response_canonical_sha = hashlib.sha256(canonical_json_v1(response_value_item)).hexdigest()
        else:
            if response["response_media_type"].startswith("text/plain"):
                validate_utf8_bytes(response_bytes, f"response[{index}] text body")
            actual_response_canonical_sha = hashlib.sha256(response_bytes).hexdigest()
        require(response["response_canonical_sha256"] == actual_response_canonical_sha, f"response[{index}] canonical body hash mismatch")
        human_body_hashes = validate_human_body_hashes(response["human_body_hashes"], f"response[{index}].human_body_hashes")
        expected_human_body_hashes = (
            derive_human_body_hashes(response["label"], response_value_item)
            if response["response_media_type"] == "application/json"
            else []
        )
        require(human_body_hashes == expected_human_body_hashes, f"response[{index}] human body hashes differ from decoded raw response")
        labels.append(response["label"])
        tuples.append(
            (
                response["label"],
                response["request_canonical_sha256"],
                response["response_body_sha256"],
                response["response_canonical_sha256"],
            )
        )
    require(len(set(tuples)) == len(tuples), "endpoint bundle contains duplicate response tuples")
    require(tuples == sorted(tuples, key=lambda item: tuple(utf16_sort_key(part) for part in item)), "endpoint bundle responses are not canonically sorted")
    require(tuple(labels) == COMPONENT_INVENTORY[str(bundle["component"])], f"endpoint inventory mismatch for {bundle['component']}: {labels}")


def validate_pre_attestation_v1(value: Any) -> None:
    root = require_exact_object(
        value,
        (
            "schema",
            "repository",
            "pr_number",
            "base_sha",
            "candidate_head",
            "candidate_tree",
            "snapshot_cutoff_utc",
            "component_digests",
        ),
        "pre-attestation root",
    )
    require(root["schema"] == "gvn-pre-attestation-v1", "pre-attestation schema mismatch")
    require(root["repository"] == "ZhangIvan/QingYin", "pre-attestation repository mismatch")
    require_positive_int(root["pr_number"], "pre-attestation PR number")
    for field in ("base_sha", "candidate_head", "candidate_tree"):
        require_sha1(root[field], f"pre-attestation {field}")
    require_utc_timestamp(root["snapshot_cutoff_utc"], "pre-attestation snapshot_cutoff_utc")
    validate_named_digests(root["component_digests"], PRE_ATTESTATION_COMPONENTS, "pre-attestation component_digests")


def validate_attestation_v1(value: Any) -> None:
    payload = require_exact_object(
        value,
        (
            "schema",
            "repository",
            "pr_number",
            "base_sha",
            "candidate_head",
            "candidate_tree",
            "attestor_login",
            "attestor_id",
            "changed_paths_sha256",
            "pull_body_sha256",
            "risk_class",
            "pre_attestation_sha256",
            "finding_ids",
            "accepted_residual_ids",
            "checks_status",
            "reviews_status",
            "trusted_control_status",
            "unknowns",
            "rollback",
            "no_production_authorization",
        ),
        "attestation payload",
    )
    require(payload["schema"] == "gvn-attestation-v1", "attestation schema mismatch")
    require(payload["repository"] == "ZhangIvan/QingYin", "attestation repository mismatch")
    require_positive_int(payload["pr_number"], "attestation PR number")
    for field in ("base_sha", "candidate_head", "candidate_tree"):
        require_sha1(payload[field], f"attestation {field}")
    require(payload["attestor_login"] == "ZhangIvan", "attestation login must be ZhangIvan")
    require_positive_int(payload["attestor_id"], "attestor_id")
    require_sha256(payload["changed_paths_sha256"], "attestation changed_paths_sha256")
    require_sha256(payload["pull_body_sha256"], "attestation pull_body_sha256")
    require_sha256(payload["pre_attestation_sha256"], "attestation pre_attestation_sha256")
    require(payload["risk_class"] == "CR3", "bootstrap attestation risk_class must be CR3")
    require_sorted_unique_strings(payload["finding_ids"], "attestation finding_ids")
    require_sorted_unique_strings(payload["accepted_residual_ids"], "attestation accepted_residual_ids")
    for field in ("checks_status", "reviews_status", "trusted_control_status"):
        require(payload[field] == "VERIFIED", f"attestation {field} must be VERIFIED")
    unknowns = require_sorted_unique_strings(payload["unknowns"], "attestation unknowns")
    require(not unknowns, "bootstrap attestation unknowns must be empty")
    require(isinstance(payload["rollback"], str) and payload["rollback"], "attestation rollback must be non-empty")
    require(payload["no_production_authorization"] is True, "attestation must explicitly deny production authorization")


def validate_manifest_v1(value: Any) -> None:
    manifest = require_exact_object(
        value,
        (
            "schema",
            "phase",
            "repository",
            "pr_number",
            "base_sha",
            "candidate_head",
            "candidate_tree",
            "snapshot_cutoff_utc",
            "component_digests",
            "effective_merge_sha",
        ),
        "governance manifest",
    )
    require(manifest["schema"] == "gvn-manifest-v1", "manifest schema mismatch")
    require(manifest["phase"] in ("stable-window-start", "stable-window-end", "post-merge"), "manifest phase invalid")
    require(manifest["repository"] == "ZhangIvan/QingYin", "manifest repository mismatch")
    require_positive_int(manifest["pr_number"], "manifest PR number")
    for field in ("base_sha", "candidate_head", "candidate_tree"):
        require_sha1(manifest[field], f"manifest {field}")
    require_utc_timestamp(manifest["snapshot_cutoff_utc"], "manifest snapshot_cutoff_utc")
    if manifest["phase"] == "post-merge":
        require_sha1(manifest["effective_merge_sha"], "manifest effective_merge_sha")
        expected_components = POST_MERGE_COMPONENTS
    else:
        require(manifest["effective_merge_sha"] is None, "pre-merge manifest effective_merge_sha must be null")
        expected_components = STABLE_COMPONENTS
    validate_named_digests(manifest["component_digests"], expected_components, "manifest component_digests")


def response_value(bundle: dict[str, Any], label: str) -> Any:
    matches = [item for item in bundle["responses"] if item["label"] == label]
    require(len(matches) == 1, f"expected exactly one response label {label!r} in {bundle['component']}")
    require(matches[0]["response_media_type"] == "application/json", f"response label {label!r} must be JSON")
    response_bytes = base64.b64decode(matches[0]["response_body_base64"], validate=True)
    return parse_json_strict(response_bytes.decode("utf-8"))


def response_item(bundle: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [item for item in bundle["responses"] if item["label"] == label]
    require(len(matches) == 1, f"expected exactly one response label {label!r} in {bundle['component']}")
    return matches[0]


def workflow_log_records(bundle: dict[str, Any]) -> dict[int, tuple[str, bytes]]:
    item = response_item(bundle, "workflow-logs")
    require(item["response_media_type"] == "application/zip", "workflow-logs must be a ZIP archive")
    try:
        archive_bytes = base64.b64decode(item["response_body_base64"], validate=True)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            records: dict[int, tuple[str, bytes]] = {}
            for member in archive.infolist():
                require(not member.is_dir(), "workflow-logs archive cannot contain directories")
                match = re.fullmatch(r"([1-9][0-9]*)\.log", member.filename)
                require(match is not None, f"workflow log member name invalid: {member.filename}")
                job_id = parse_positive_decimal(match.group(1), "workflow log job id")
                require(job_id not in records, f"duplicate workflow log job id: {job_id}")
                log_bytes = archive.read(member)
                records[job_id] = (hashlib.sha256(log_bytes).hexdigest(), log_bytes)
    except (binascii.Error, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        fail(f"invalid workflow-logs archive: {exc}")
    require(records, "workflow-logs archive cannot be empty")
    return records


def validate_package_request_bindings(
    bundles: dict[str, dict[str, Any]],
    pr_number: int,
    candidate_head: str,
    candidate_tree: str,
    effective_merge_sha: str | None,
) -> None:
    expected_paths = {
        "pull": f"/repos/ZhangIvan/QingYin/pulls/{pr_number}",
        "pull-files": f"/repos/ZhangIvan/QingYin/pulls/{pr_number}/files",
        "candidate-commit": f"/git/commits/{candidate_head}",
        "candidate-tree": f"/repos/ZhangIvan/QingYin/git/trees/{candidate_tree}",
        "github-reviews": f"/repos/ZhangIvan/QingYin/pulls/{pr_number}/reviews",
        "issue-comments": f"/repos/ZhangIvan/QingYin/issues/{pr_number}/comments",
        "check-runs": f"/repos/ZhangIvan/QingYin/commits/{candidate_head}/check-runs",
        "agent-reviews": f"/reviews/{candidate_head}",
    }
    for bundle in bundles.values():
        for item in bundle["responses"]:
            expected_path = expected_paths.get(item["label"])
            if expected_path is not None:
                require(item["request"]["path"] == expected_path, f"request target is not bound to package identity: {item['label']}")
            if item["label"] == "candidate-tree":
                require(item["request"]["query"] == [["recursive", "1"]], "candidate-tree request must be recursive")
            elif item["label"] == "workflow-runs":
                require(
                    item["request"]["query"] == [["event", "pull_request"], ["head_sha", candidate_head], ["page", "1"], ["per_page", "100"]],
                    "workflow-runs request must be filtered to the candidate pull_request runs",
                )
            elif item["label"] in (*PAGINATED_ARRAY_LABELS, *PAGINATED_OBJECT_LABELS):
                require(item["request"]["query"] == [["page", "1"], ["per_page", "100"]], f"paginated request query drifted: {item['label']}")
            else:
                require(item["request"]["query"] == [], f"non-paginated request query must be empty: {item['label']}")
            if item["label"] in ("workflow-jobs", "workflow-logs", "runner-provenance", "finding-ledger"):
                require(
                    item["request"]["body"] == {"label": item["label"]},
                    f"derived request operation descriptor mismatch: {item['label']}",
                )

    graphql_queries = {
        "pull-metadata": PULL_METADATA_QUERY,
        "review-threads": REVIEW_THREADS_QUERY,
    }
    graphql_labels: list[tuple[str, str]] = [("pull-metadata", "metadata"), ("review-threads", "discussion")]
    if "merge" in bundles:
        graphql_labels.append(("post-merge-metadata", "merge"))
    for label, component in graphql_labels:
        request = response_item(bundles[component], label)["request"]
        body = request["body"]
        require_exact_object(body, ("query", "variables"), f"{label} GraphQL body")
        expected_query = PULL_METADATA_QUERY if label == "post-merge-metadata" else graphql_queries[label]
        require(body["query"] == expected_query, f"{label} GraphQL query text mismatch")
        require_exact_object(body["variables"], ("owner", "name", "number"), f"{label} GraphQL variables")
        variables = body["variables"]
        require(
            variables.get("owner") == "ZhangIvan"
            and variables.get("name") == "QingYin"
            and variables.get("number") == pr_number,
            f"{label} GraphQL variables are not bound to package PR",
        )

    metadata_response = response_value(bundles["metadata"], "pull-metadata")
    threads_response = response_value(bundles["discussion"], "review-threads")
    for label, response in (("pull-metadata", metadata_response), ("review-threads", threads_response)):
        require_exact_object(response, ("data",), f"{label} GraphQL response")
        require(isinstance(response.get("data"), dict), f"{label} GraphQL response missing data")
        repository = response["data"].get("repository")
        require(isinstance(repository, dict) and isinstance(repository.get("pullRequest"), dict), f"{label} GraphQL pullRequest missing")
    metadata_pr = metadata_response["data"]["repository"]["pullRequest"]
    for connection_name in ("labels", "reviewRequests", "assignees"):
        connection = metadata_pr.get(connection_name)
        require(isinstance(connection, dict) and isinstance(connection.get("nodes"), list) and isinstance(connection.get("pageInfo"), dict), f"pull-metadata {connection_name} connection invalid")
        require(connection["pageInfo"].get("hasNextPage") is False and len(connection["nodes"]) < 100, f"pull-metadata {connection_name} may be truncated")
    thread_connection = threads_response["data"]["repository"]["pullRequest"].get("reviewThreads")
    require(isinstance(thread_connection, dict) and isinstance(thread_connection.get("nodes"), list) and isinstance(thread_connection.get("pageInfo"), dict), "reviewThreads connection invalid")
    require(thread_connection["pageInfo"].get("hasNextPage") is False and len(thread_connection["nodes"]) < 100, "reviewThreads may be truncated")
    for index, thread in enumerate(thread_connection["nodes"]):
        require(isinstance(thread, dict) and isinstance(thread.get("comments"), dict), f"reviewThreads node[{index}] invalid")
        comments = thread["comments"]
        require(isinstance(comments.get("nodes"), list) and isinstance(comments.get("pageInfo"), dict), f"reviewThreads comments[{index}] invalid")
        require(comments["pageInfo"].get("hasNextPage") is False and len(comments["nodes"]) < 100, f"reviewThreads comments[{index}] may be truncated")
    if "attestation" in bundles:
        comment = response_value(bundles["attestation"], "attestation-comment")
        require(isinstance(comment, dict), "attestation comment response invalid")
        require_positive_int(comment.get("id"), "attestation comment id")
        comment_path = response_item(bundles["attestation"], "attestation-comment")["request"]["path"]
        require(comment_path == f"/repos/ZhangIvan/QingYin/issues/comments/{comment['id']}", "attestation comment request path/id mismatch")
    if "merge" in bundles:
        require(effective_merge_sha is not None, "post-merge request binding requires effective merge SHA")
        request = response_item(bundles["merge"], "merge-response")["request"]
        require(request["path"] == f"/repos/ZhangIvan/QingYin/pulls/{pr_number}/merge", "merge-response PR path mismatch")
        require(request["body"] == {"merge_method": "squash", "sha": candidate_head}, "merge-response body is not bound to exact candidate")
        merged_pull_path = response_item(bundles["merge"], "merged-pull")["request"]["path"]
        require(merged_pull_path == f"/repos/ZhangIvan/QingYin/pulls/{pr_number}", "merged-pull PR path mismatch")
        post_checks_path = response_item(bundles["merge"], "post-merge-checks")["request"]["path"]
        require(post_checks_path == f"/repos/ZhangIvan/QingYin/commits/{effective_merge_sha}/check-runs", "post-merge checks path mismatch")

    paginated_labels = (*PAGINATED_ARRAY_LABELS, *PAGINATED_OBJECT_LABELS)
    response_by_label = {
        item["label"]: item
        for bundle in bundles.values()
        for item in bundle["responses"]
    }
    expected_query = [["page", "1"], ["per_page", "100"]]
    for label in paginated_labels:
        if label not in response_by_label:
            continue
        item = response_by_label[label]
        label_expected_query = (
            [["event", "pull_request"], ["head_sha", candidate_head], *expected_query]
            if label == "workflow-runs"
            else expected_query
        )
        require(item["request"]["query"] == label_expected_query, f"{label} must request the complete filtered first page explicitly")
        response = response_value(next(bundle for bundle in bundles.values() if label in COMPONENT_INVENTORY[bundle["component"]]), label)
        if label in PAGINATED_ARRAY_LABELS:
            require(isinstance(response, list), f"{label} paginated response must be an array")
            require(len(response) < 100, f"{label} may have an unrecorded next page")
        else:
            array_field = PAGINATED_OBJECT_LABELS[label]
            require(isinstance(response, dict), f"{label} paginated response must be an object")
            require_nonnegative_int(response.get("total_count"), f"{label}.total_count")
            require(isinstance(response.get(array_field), list), f"{label}.{array_field} invalid")
            require(response["total_count"] == len(response[array_field]), f"{label} response is incomplete")
            require(len(response[array_field]) < 100, f"{label} may have an unrecorded next page")


def validate_package_response_semantics(
    bundles: dict[str, dict[str, Any]],
    root: dict[str, Any],
    cutoff_utc: str | None = None,
    target_type: str | None = None,
) -> None:
    pr_number = root["pr_number"]
    base_sha = root["base_sha"]
    candidate_head = root["candidate_head"]
    candidate_tree = root["candidate_tree"]
    effective_cutoff = root["snapshot_cutoff_utc"] if cutoff_utc is None else cutoff_utc
    effective_target_type = ("governance-bootstrap" if pr_number == EXPECTED_GOVERNANCE_PR else "ordinary") if target_type is None else target_type
    require_utc_timestamp(effective_cutoff, "package response cutoff")
    effective_cutoff_time = datetime.strptime(effective_cutoff, "%Y-%m-%dT%H:%M:%SZ")
    require(effective_target_type in (*ONE_TIME_TARGET_TYPES, "ordinary"), "package response target type invalid")
    if effective_target_type == "governance-bootstrap":
        require_governance_bootstrap_base(base_sha)

    pull = response_value(bundles["pr"], "pull")
    require(isinstance(pull, dict), "pull response must be an object")
    require_positive_int(pull.get("number"), "pull response number")
    require(pull.get("number") == pr_number, "pull response number differs from package PR")
    require(isinstance(pull.get("base"), dict) and pull["base"].get("sha") == base_sha, "pull response base SHA mismatch")
    require(isinstance(pull.get("head"), dict) and pull["head"].get("sha") == candidate_head, "pull response head SHA mismatch")
    require(pull["base"].get("ref") == "main", "pull response base ref must be main")
    require(isinstance(pull["head"].get("ref"), str) and pull["head"]["ref"], "pull response head ref missing")
    if pr_number == EXPECTED_GOVERNANCE_PR:
        require(pull["head"]["ref"] == "docs/g0-single-maintainer-governance", "PR #19 head ref mismatch")
    require(pull.get("state") == "open" and pull.get("draft") is False, "pull response must be open and non-draft")
    require_positive_int(pull.get("id"), "pull immutable database id")
    require(isinstance(pull.get("node_id"), str) and pull["node_id"].strip(), "pull immutable GraphQL id missing")
    require(pull.get("mergeable") is True and pull.get("mergeable_state") == "clean", "pull response must be cleanly mergeable")
    require(pull.get("locked") is False and pull.get("auto_merge") is None, "pull must not be locked or auto-merged")
    require(isinstance(pull.get("title"), str) and pull["title"].strip(), "pull title missing")
    require(isinstance(pull.get("body"), str) and pull["body"].strip(), "pull body missing")
    require_utc_timestamp(pull.get("updated_at"), "pull updated_at")
    pull_updated_at_time = datetime.strptime(pull["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
    require(pull_updated_at_time <= effective_cutoff_time, "pull updated_at is newer than package response cutoff")
    require_positive_int(pull.get("commits"), "pull commit count")
    require_nonnegative_int(pull.get("comments"), "pull comment count")
    require_nonnegative_int(pull.get("changed_files"), "pull changed_files")

    candidate = response_value(bundles["paths"], "candidate-commit")
    candidate = require_exact_object(candidate, ("object_type", "commit", "tree", "committed_at"), "candidate commit evidence")
    require(candidate["object_type"] == "commit", "candidate Git object type mismatch")
    require(candidate["commit"] == candidate_head and candidate["tree"] == candidate_tree, "candidate commit/tree evidence mismatch")
    require_utc_timestamp(candidate["committed_at"], "candidate commit committed_at")
    require(candidate["committed_at"] <= effective_cutoff, "candidate commit is newer than the package response cutoff")
    tree_response = response_value(bundles["paths"], "candidate-tree")
    require(isinstance(tree_response, dict), "candidate tree response must be an object")
    require(tree_response.get("sha") == candidate_tree and tree_response.get("truncated") is False, "candidate tree response SHA/truncation mismatch")
    require(isinstance(tree_response.get("tree"), list) and tree_response["tree"], "candidate tree entries missing")
    tree_values = derive_stable_array_view(
        tree_response["tree"],
        "candidate-tree.tree",
        lambda item, item_index: (
            stable_string_component(item.get("path") if isinstance(item, dict) else None, f"candidate-tree.tree[{item_index}].path"),
        ),
    )
    tree_entries: dict[str, dict[str, Any]] = {}
    for index, tree_value in enumerate(tree_values):
        require(isinstance(tree_value, dict), f"candidate tree entry[{index}] must be an object")
        path = tree_value.get("path")
        require(isinstance(path, str) and path and path not in tree_entries, f"candidate tree entry[{index}] path invalid or duplicate")
        require(tree_value.get("type") in ("blob", "tree"), f"candidate tree entry[{index}] type invalid")
        expected_modes = ("100644", "100755") if tree_value["type"] == "blob" else ("040000",)
        require(tree_value.get("mode") in expected_modes, f"candidate tree entry[{index}] mode invalid")
        require_sha1(tree_value.get("sha"), f"candidate tree entry[{index}].sha")
        tree_entries[path] = tree_value
    files = response_value(bundles["paths"], "pull-files")
    require(isinstance(files, list), "pull-files response must be an array")
    files = derive_stable_array_view(
        files,
        "pull-files",
        lambda item, item_index: (
            stable_string_component(item.get("filename") if isinstance(item, dict) else None, f"pull-files[{item_index}].filename"),
        ),
    )
    filenames = [item.get("filename") if isinstance(item, dict) else None for item in files]
    require(all(isinstance(filename, str) and filename for filename in filenames), "pull-files filename missing")
    require(len(set(filenames)) == len(filenames), "pull-files contains duplicate filenames")
    require(pull["changed_files"] == len(files), "pull changed_files differs from complete pull-files response")
    for index, file_item in enumerate(files):
        require(file_item.get("status") in ("added", "modified", "removed"), f"pull-files[{index}] status invalid")
        require_sha1(file_item.get("sha"), f"pull-files[{index}].sha")
        for field in ("additions", "deletions", "changes"):
            require_nonnegative_int(file_item.get(field), f"pull-files[{index}].{field}")
        require(file_item["changes"] == file_item["additions"] + file_item["deletions"], f"pull-files[{index}] change totals mismatch")
        if file_item["status"] in ("added", "modified"):
            tree_entry_value = tree_entries.get(file_item["filename"])
            require(isinstance(tree_entry_value, dict) and tree_entry_value.get("type") == "blob", f"pull-files[{index}] candidate tree entry missing")
            require(tree_entry_value.get("sha") == file_item["sha"], f"pull-files[{index}] blob differs from candidate tree")
        else:
            require(file_item["filename"] not in tree_entries, f"removed pull-files[{index}] still exists in candidate tree")
    if pr_number == EXPECTED_GOVERNANCE_PR and base_sha == SOURCE_COMMIT:
        expected_file_statuses = {
            path.as_posix(): "added" if status == "A" else "modified"
            for path, status in BOOTSTRAP_STATUS.items()
        }
        actual_file_statuses = {item["filename"]: item["status"] for item in files}
        require(actual_file_statuses == expected_file_statuses, "PR #19 pull-files does not match the exact six-file bootstrap scope")

    metadata_pr = response_value(bundles["metadata"], "pull-metadata")["data"]["repository"]["pullRequest"]
    threads_pr = response_value(bundles["discussion"], "review-threads")["data"]["repository"]["pullRequest"]
    derive_stable_array_view(
        metadata_pr["labels"]["nodes"],
        "pull-metadata.labels.nodes",
        lambda item, item_index: (
            stable_string_component(item.get("id") if isinstance(item, dict) else None, f"pull-metadata.labels.nodes[{item_index}].id"),
            stable_string_component(item.get("name") if isinstance(item, dict) else None, f"pull-metadata.labels.nodes[{item_index}].name"),
        ),
        lambda item, item_index: (
            stable_string_component(item.get("id") if isinstance(item, dict) else None, f"pull-metadata.labels.nodes[{item_index}].id"),
        ),
    )
    derive_stable_array_view(
        metadata_pr["reviewRequests"]["nodes"],
        "pull-metadata.reviewRequests.nodes",
        lambda item, item_index: (
            stable_string_component(
                item.get("requestedReviewer", {}).get("id") if isinstance(item, dict) and isinstance(item.get("requestedReviewer"), dict) else None,
                f"pull-metadata.reviewRequests.nodes[{item_index}].requestedReviewer.id",
            ),
            stable_string_component(
                (
                    item["requestedReviewer"].get("login")
                    if isinstance(item, dict)
                    and isinstance(item.get("requestedReviewer"), dict)
                    and isinstance(item["requestedReviewer"].get("login"), str)
                    else item["requestedReviewer"].get("name")
                    if isinstance(item, dict) and isinstance(item.get("requestedReviewer"), dict)
                    else None
                ),
                f"pull-metadata.reviewRequests.nodes[{item_index}].requestedReviewer.name-or-login",
            ),
        ),
        lambda item, item_index: (
            stable_string_component(
                item.get("requestedReviewer", {}).get("id") if isinstance(item, dict) and isinstance(item.get("requestedReviewer"), dict) else None,
                f"pull-metadata.reviewRequests.nodes[{item_index}].requestedReviewer.id",
            ),
        ),
    )
    derive_stable_array_view(
        metadata_pr["assignees"]["nodes"],
        "pull-metadata.assignees.nodes",
        lambda item, item_index: (
            stable_string_component(item.get("id") if isinstance(item, dict) else None, f"pull-metadata.assignees.nodes[{item_index}].id"),
            stable_string_component(item.get("login") if isinstance(item, dict) else None, f"pull-metadata.assignees.nodes[{item_index}].login"),
        ),
        lambda item, item_index: (
            stable_string_component(item.get("id") if isinstance(item, dict) else None, f"pull-metadata.assignees.nodes[{item_index}].id"),
        ),
    )
    for label, graphql_pr in (("pull-metadata", metadata_pr), ("review-threads", threads_pr)):
        require(graphql_pr.get("id") == pull["node_id"], f"{label} immutable PR id differs from REST pull")
        require_positive_int(graphql_pr.get("number"), f"{label} response PR number")
        require(graphql_pr.get("number") == pr_number, f"{label} response PR number mismatch")
        require(graphql_pr.get("baseRefOid") == base_sha, f"{label} response base SHA mismatch")
        require(graphql_pr.get("headRefOid") == candidate_head, f"{label} response head SHA mismatch")
    require(metadata_pr.get("isDraft") is False, "GraphQL pull metadata must be non-draft")
    require_utc_timestamp(metadata_pr.get("updatedAt"), "pull metadata updatedAt")
    metadata_updated_at_time = datetime.strptime(metadata_pr["updatedAt"], "%Y-%m-%dT%H:%M:%SZ")
    require(metadata_updated_at_time <= effective_cutoff_time, "pull metadata updatedAt is newer than package response cutoff")
    require(metadata_pr.get("updatedAt") == pull["updated_at"], "GraphQL/REST pull updated timestamp mismatch")
    require(metadata_pr.get("title") == pull["title"] and metadata_pr.get("body") == pull["body"], "GraphQL/REST pull title or body mismatch")
    require(metadata_pr.get("baseRefName") == "main" and metadata_pr.get("headRefName") == pull["head"]["ref"], "GraphQL/REST pull refs mismatch")
    require(metadata_pr.get("mergeable") == "MERGEABLE", "GraphQL pull must be mergeable")
    require(metadata_pr.get("autoMergeRequest") is None and metadata_pr.get("mergeQueueEntry") is None, "auto-merge/merge queue must be empty")
    require(metadata_pr["reviewRequests"].get("nodes") == [], "pending review requests must be empty")

    github_reviews = response_value(bundles["review"], "github-reviews")
    require(isinstance(github_reviews, list), "GitHub reviews response must be an array")
    github_reviews = derive_stable_array_view(
        github_reviews,
        "github-reviews",
        lambda item, item_index: (
            stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"github-reviews[{item_index}].id"),
        ),
    )
    github_review_ids: list[int] = []
    github_review_node_ids: list[str] = []
    for index, review in enumerate(github_reviews):
        require(isinstance(review, dict), f"GitHub review[{index}] must be an object")
        require(review.get("state") in ("APPROVED", "COMMENTED"), f"GitHub review[{index}] is pending, dismissed or requests changes")
        require_positive_int(review.get("id"), f"GitHub review[{index}] immutable id")
        require(isinstance(review.get("node_id"), str) and review["node_id"].strip(), f"GitHub review[{index}] GraphQL id missing")
        require(isinstance(review.get("user"), dict), f"GitHub review[{index}] author missing")
        require_positive_int(review["user"].get("id"), f"GitHub review[{index}] author id")
        require(isinstance(review["user"].get("login"), str) and review["user"]["login"], f"GitHub review[{index}] author identity invalid")
        require(review["user"].get("type") in ("User", "Bot"), f"GitHub review[{index}] author type invalid")
        require(isinstance(review.get("body"), str), f"GitHub review[{index}] body missing")
        require(review.get("commit_id") == candidate_head, f"GitHub review[{index}] is stale for another candidate")
        require_utc_timestamp(review.get("submitted_at"), f"GitHub review[{index}].submitted_at")
        require(candidate["committed_at"] <= review["submitted_at"] <= effective_cutoff, f"GitHub review[{index}] is outside the candidate/cutoff interval")
        github_review_ids.append(review["id"])
        github_review_node_ids.append(review["node_id"])
    require(len(github_review_ids) == len(set(github_review_ids)), "GitHub review immutable ids are duplicated")
    require(len(github_review_node_ids) == len(set(github_review_node_ids)), "GitHub review GraphQL ids are duplicated")
    review_threads = threads_pr["reviewThreads"]["nodes"]
    review_threads = derive_stable_array_view(
        review_threads,
        "reviewThreads.nodes",
        lambda item, item_index: (
            stable_string_component(item.get("id") if isinstance(item, dict) else None, f"reviewThreads.nodes[{item_index}].id"),
        ),
    )
    thread_ids: list[str] = []
    comment_ids: list[str] = []
    comment_database_ids: list[int] = []
    for thread_index, thread in enumerate(review_threads):
        require(isinstance(thread, dict), f"review thread[{thread_index}] must be an object")
        require(isinstance(thread.get("id"), str) and thread["id"].strip(), f"review thread[{thread_index}] immutable id missing")
        require(thread.get("isResolved") is True and isinstance(thread.get("isOutdated"), bool), f"review thread[{thread_index}] unresolved or outdated flag missing")
        comments = thread.get("comments", {}).get("nodes")
        require(isinstance(comments, list) and comments, f"review thread[{thread_index}] must contain complete comments")
        comments = derive_stable_array_view(
            comments,
            f"reviewThreads.nodes[{thread_index}].comments.nodes",
            lambda item, item_index: (
                stable_string_component(item.get("id") if isinstance(item, dict) else None, f"reviewThreads.nodes[{thread_index}].comments.nodes[{item_index}].id"),
            ),
        )
        current_comments = 0
        for comment_index, comment in enumerate(comments):
            require(isinstance(comment, dict), f"review thread[{thread_index}] comment[{comment_index}] invalid")
            require(isinstance(comment.get("id"), str) and comment["id"].strip(), f"review comment immutable id missing: {thread_index}:{comment_index}")
            require_positive_int(comment.get("databaseId"), f"review comment database id: {thread_index}:{comment_index}")
            author = comment.get("author")
            require(isinstance(author, dict) and isinstance(author.get("login"), str) and author["login"] and isinstance(author.get("id"), str) and author["id"], f"review comment author identity invalid: {thread_index}:{comment_index}")
            require_positive_int(author.get("databaseId"), f"review comment author database id: {thread_index}:{comment_index}")
            require(isinstance(comment.get("body"), str) and comment["body"].strip(), f"review comment body missing: {thread_index}:{comment_index}")
            require_utc_timestamp(comment.get("createdAt"), f"review comment createdAt: {thread_index}:{comment_index}")
            require_utc_timestamp(comment.get("updatedAt"), f"review comment updatedAt: {thread_index}:{comment_index}")
            require(comment["createdAt"] <= comment["updatedAt"] <= effective_cutoff, f"review comment timestamps invalid: {thread_index}:{comment_index}")
            require(comment.get("state") == "SUBMITTED" and isinstance(comment.get("outdated"), bool), f"review comment state/outdated invalid: {thread_index}:{comment_index}")
            require(isinstance(comment.get("commit"), dict) and isinstance(comment["commit"].get("oid"), str), f"review comment commit missing: {thread_index}:{comment_index}")
            if comment["outdated"]:
                require(comment["commit"]["oid"] != candidate_head, f"outdated review comment unexpectedly names current candidate: {thread_index}:{comment_index}")
            else:
                require(comment["commit"]["oid"] == candidate_head, f"current review comment is not bound to candidate: {thread_index}:{comment_index}")
                require(candidate["committed_at"] <= comment["createdAt"], f"current review comment predates the candidate: {thread_index}:{comment_index}")
                current_comments += 1
            comment_ids.append(comment["id"])
            comment_database_ids.append(comment["databaseId"])
        if thread["isOutdated"]:
            require(current_comments == 0, f"outdated review thread contains current comments: {thread_index}")
        else:
            require(current_comments > 0, f"current review thread has no candidate-bound comment: {thread_index}")
        thread_ids.append(thread["id"])
    require(len(thread_ids) == len(set(thread_ids)), "review thread immutable ids are duplicated")
    require(len(comment_ids) == len(set(comment_ids)) and len(comment_database_ids) == len(set(comment_database_ids)), "review comment immutable ids are duplicated")

    issue_comments = response_value(bundles["discussion"], "issue-comments")
    require(isinstance(issue_comments, list), "issue-comments response must be an array")
    issue_comments = derive_stable_array_view(
        issue_comments,
        "issue-comments",
        lambda item, item_index: (
            stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"issue-comments[{item_index}].id"),
        ),
    )
    issue_comment_ids: list[int] = []
    issue_comment_node_ids: list[str] = []
    for comment_index, comment in enumerate(issue_comments):
        require(isinstance(comment, dict), f"issue comment[{comment_index}] must be an object")
        require_positive_int(comment.get("id"), f"issue comment[{comment_index}] immutable id")
        require(isinstance(comment.get("node_id"), str) and comment["node_id"].strip(), f"issue comment[{comment_index}] GraphQL id missing")
        require(isinstance(comment.get("user"), dict), f"issue comment[{comment_index}] author missing")
        require_positive_int(comment["user"].get("id"), f"issue comment[{comment_index}] author id")
        require(isinstance(comment["user"].get("login"), str) and comment["user"]["login"], f"issue comment[{comment_index}] author login missing")
        require(isinstance(comment.get("body"), str) and comment["body"].strip(), f"issue comment[{comment_index}] body missing")
        require_utc_timestamp(comment.get("created_at"), f"issue comment[{comment_index}].created_at")
        require_utc_timestamp(comment.get("updated_at"), f"issue comment[{comment_index}].updated_at")
        require(comment["created_at"] <= comment["updated_at"] <= effective_cutoff, f"issue comment[{comment_index}] timestamps invalid")
        issue_comment_ids.append(comment["id"])
        issue_comment_node_ids.append(comment["node_id"])
    require(len(issue_comment_ids) == len(set(issue_comment_ids)), "issue comment immutable ids are duplicated")
    require(len(issue_comment_node_ids) == len(set(issue_comment_node_ids)), "issue comment GraphQL ids are duplicated")

    agent_reviews = require_exact_object(response_value(bundles["review"], "agent-reviews"), ("schema", "reviews"), "agent reviews evidence")
    require(agent_reviews["schema"] == "gvn-agent-reviews-v1", "agent reviews schema mismatch")
    require(isinstance(agent_reviews["reviews"], list) and len(agent_reviews["reviews"]) == 2, "bootstrap requires exactly two fresh agent reviews")
    reviewer_ids: list[str] = []
    report_hashes: list[str] = []
    for index, review_value in enumerate(agent_reviews["reviews"]):
        review = require_exact_object(
            review_value,
            (
                "reviewer_id",
                "task_name",
                "model",
                "reasoning_effort",
                "source_authentication",
                "implementation_participant",
                "started_at",
                "completed_at",
                "base_sha",
                "candidate_head",
                "candidate_tree",
                "verdict",
                "p0",
                "p1",
                "p2",
                "review_scope",
                "verified",
                "inferred",
                "unverified",
                "verification",
                "findings",
                "review_input_body",
                "review_input_sha256",
                "report_body",
                "report_sha256",
            ),
            f"agent review[{index}]",
        )
        require(isinstance(review["reviewer_id"], str) and review["reviewer_id"].startswith("/root/") and review["reviewer_id"] != "/root/ZhangIvan", f"agent review[{index}] reviewer id invalid or owner-like")
        require(review["task_name"] == review["reviewer_id"], f"agent review[{index}] task/reviewer identity mismatch")
        require(review["model"] == "gpt-5.6-luna" and review["reasoning_effort"] == "xhigh", f"agent review[{index}] model routing mismatch")
        require(review["source_authentication"] == "owner-attested-orchestrator-transcript", f"agent review[{index}] source authentication boundary is not explicit")
        require(review["implementation_participant"] is False, f"agent review[{index}] was not independent of implementation")
        require_utc_timestamp(review["started_at"], f"agent review[{index}].started_at")
        require_utc_timestamp(review["completed_at"], f"agent review[{index}].completed_at")
        require(candidate["committed_at"] <= review["started_at"] <= review["completed_at"] <= effective_cutoff, f"agent review[{index}] timestamps are outside the candidate/cutoff interval")
        require((review["base_sha"], review["candidate_head"], review["candidate_tree"]) == (base_sha, candidate_head, candidate_tree), f"agent review[{index}] candidate binding mismatch")
        require_nonnegative_int(review["p0"], f"agent review[{index}].p0")
        require_nonnegative_int(review["p1"], f"agent review[{index}].p1")
        require_nonnegative_int(review["p2"], f"agent review[{index}].p2")
        require(review["verdict"] == "ACCEPT" and review["p0"] == 0 and review["p1"] == 0, f"agent review[{index}] is not an unblocked ACCEPT")
        require(tuple(review["review_scope"]) == AGENT_REVIEW_SCOPE, f"agent review[{index}] scope inventory mismatch")
        for field in ("verified", "inferred", "unverified"):
            values = require_sorted_unique_strings(review[field], f"agent review[{index}].{field}")
            if field == "verified":
                require(values, f"agent review[{index}] verified evidence cannot be empty")
        require(FRESHNESS_UNVERIFIED_MARKER not in review["verified"], f"agent review[{index}] falsely verifies stable-window capture freshness")
        if effective_target_type in ONE_TIME_TARGET_TYPES:
            require(FRESHNESS_UNVERIFIED_MARKER in review["unverified"], f"agent review[{index}] does not disclose GVN-P1-005 freshness as unverified")
        require(isinstance(review["verification"], list) and review["verification"], f"agent review[{index}] verification records missing")
        verification_commands: list[str] = []
        for verification_index, verification_value in enumerate(review["verification"]):
            verification = require_exact_object(verification_value, ("command", "result", "evidence"), f"agent review[{index}] verification[{verification_index}]")
            require(isinstance(verification["command"], str) and verification["command"].strip() == verification["command"] and verification["command"], f"agent review[{index}] verification command invalid")
            require(verification["result"] in ("PASS", "PENDING"), f"agent review[{index}] verification result invalid")
            require(isinstance(verification["evidence"], str) and verification["evidence"].strip() == verification["evidence"] and verification["evidence"], f"agent review[{index}] verification evidence invalid")
            verification_commands.append(verification["command"])
        require(verification_commands == sorted(set(verification_commands), key=utf16_sort_key), f"agent review[{index}] verification commands must be unique and sorted")
        require(isinstance(review["findings"], list) and len(review["findings"]) == review["p2"], f"agent review[{index}] structured finding count mismatch")
        finding_ids_for_review: list[str] = []
        for finding_index, finding_value in enumerate(review["findings"]):
            finding = require_exact_object(finding_value, ("id", "severity", "status", "summary"), f"agent review[{index}] finding[{finding_index}]")
            require(isinstance(finding["id"], str) and re.fullmatch(r"REV-P2-[0-9]{3}", finding["id"]) is not None, f"agent review[{index}] finding id invalid")
            require(finding["severity"] == "P2" and finding["status"] in ("Resolved", "Deferred-P2"), f"agent review[{index}] finding disposition invalid")
            require(isinstance(finding["summary"], str) and finding["summary"].strip() == finding["summary"] and finding["summary"], f"agent review[{index}] finding summary invalid")
            finding_ids_for_review.append(finding["id"])
        require(finding_ids_for_review == sorted(set(finding_ids_for_review), key=utf16_sort_key), f"agent review[{index}] findings must be unique and sorted")
        require(isinstance(review["review_input_body"], str) and review["review_input_body"].strip() == review["review_input_body"] and len(review["review_input_body"]) >= 64, f"agent review[{index}] review input missing or incomplete")
        require_sha256(review["review_input_sha256"], f"agent review[{index}] review_input_sha256")
        require(hashlib.sha256(review["review_input_body"].encode("utf-8")).hexdigest() == review["review_input_sha256"], f"agent review[{index}] review input hash mismatch")
        require(isinstance(review["report_body"], str) and review["report_body"].strip() == review["report_body"] and len(review["report_body"]) >= 128, f"agent review[{index}] report body missing or incomplete")
        for marker in ("P0", "P1", "已验证", "未验证"):
            require(marker in review["report_body"], f"agent review[{index}] report body lacks required section marker: {marker}")
        require_sha256(review["report_sha256"], f"agent review[{index}] report_sha256")
        require(hashlib.sha256(review["report_body"].encode("utf-8")).hexdigest() == review["report_sha256"], f"agent review[{index}] report body hash mismatch")
        reviewer_ids.append(review["reviewer_id"])
        report_hashes.append(review["report_sha256"])
    require(reviewer_ids == sorted(set(reviewer_ids), key=utf16_sort_key), "agent reviewer ids must be unique and sorted")
    require(len(set(report_hashes)) == len(report_hashes), "agent review reports must be distinct")

    check_response = response_value(bundles["checks"], "check-runs")
    check_runs = check_response["check_runs"]
    check_runs = derive_stable_array_view(
        check_runs,
        "check-runs.check_runs",
        lambda item, item_index: (
            stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"check-runs.check_runs[{item_index}].id"),
        ),
    )
    require_nonnegative_int(check_response.get("total_count"), "check-runs.total_count")
    require(check_response["total_count"] == len(REQUIRED_CONTEXTS) and len(check_runs) == len(REQUIRED_CONTEXTS), "check-runs must contain exactly the required contexts")
    require(tuple(sorted((item.get("name") for item in check_runs if isinstance(item, dict)), key=utf16_sort_key)) == REQUIRED_CONTEXTS, "check-run context inventory mismatch")
    for index, check_run in enumerate(check_runs):
        require(isinstance(check_run, dict), f"check-run[{index}] must be an object")
        require(check_run.get("head_sha") == candidate_head, f"check-run[{index}] head SHA mismatch")
        require_positive_int(check_run.get("id"), f"check-run[{index}] id")
        require(isinstance(check_run.get("check_suite"), dict), f"check-run[{index}] check suite missing")
        require_positive_int(check_run["check_suite"].get("id"), f"check-run[{index}] suite id")
        require(isinstance(check_run.get("external_id"), str) and check_run["external_id"].strip(), f"check-run[{index}] external id missing")
        require(isinstance(check_run.get("details_url"), str) and check_run["details_url"].startswith("https://github.com/ZhangIvan/QingYin/actions/runs/"), f"check-run[{index}] details URL invalid")
        require_utc_timestamp(check_run.get("started_at"), f"check-run[{index}].started_at")
        require_utc_timestamp(check_run.get("completed_at"), f"check-run[{index}].completed_at")
        require(candidate["committed_at"] <= check_run["started_at"] <= check_run["completed_at"] <= effective_cutoff, f"check-run[{index}] timestamps are outside the candidate/cutoff interval")
    protection = response_value(bundles["control"], "branch-protection")
    require(isinstance(protection, dict) and isinstance(protection.get("required_status_checks"), dict), "branch protection required checks missing")
    required = protection["required_status_checks"]
    require(required.get("strict") is True, "branch protection strict must be true")
    required_contexts = derive_stable_array_view(
        required.get("contexts"),
        "branch-protection.required_status_checks.contexts",
        lambda item, item_index: (
            stable_string_component(item, f"branch-protection.required_status_checks.contexts[{item_index}]"),
        ),
    )
    require(tuple(required_contexts) == REQUIRED_CONTEXTS, "required context set mismatch")
    require(isinstance(required.get("checks"), list), "branch protection required app checks missing")
    required_checks = derive_stable_array_view(
        required["checks"],
        "branch-protection.required_status_checks.checks",
        lambda item, item_index: (
            stable_string_component(item.get("context") if isinstance(item, dict) else None, f"branch-protection.required_status_checks.checks[{item_index}].context"),
        ),
    )
    required_apps = {
        item.get("context"): item.get("app_id")
        for item in required_checks
        if isinstance(item, dict)
    }
    require(len(required_checks) == len(REQUIRED_CONTEXTS), "required check/app list contains duplicates or extras")
    require(tuple(required_apps) == REQUIRED_CONTEXTS, "required check/app context set mismatch")
    for context in REQUIRED_CONTEXTS:
        require_positive_int(required_apps[context], f"required check app id: {context}")
        matches = [item for item in check_runs if item.get("name") == context]
        require(len(matches) == 1, f"required check must appear exactly once: {context}")
        check_run = matches[0]
        require(check_run.get("status") == "completed" and check_run.get("conclusion") == "success", f"required check is not successful: {context}")
        require(required_apps[context] == GITHUB_ACTIONS_APP_ID, f"required context is not bound to the GitHub Actions app: {context}")
        require(
            isinstance(check_run.get("app"), dict)
            and check_run["app"].get("slug") == "github-actions"
            and isinstance(check_run["app"].get("owner"), dict)
            and check_run["app"]["owner"].get("login") == "github",
            f"required check app mismatch: {context}",
        )
        require_positive_int(check_run["app"].get("id"), f"check-run[{context}] app id")
        require(check_run["app"]["id"] == GITHUB_ACTIONS_APP_ID, f"required check app mismatch: {context}")
    pull_review_protection = protection.get("required_pull_request_reviews")
    require(isinstance(pull_review_protection, dict), "required pull-request review protection missing")
    require_nonnegative_int(
        pull_review_protection.get("required_approving_review_count"),
        "required approving review count",
    )
    require(pull_review_protection.get("required_approving_review_count") == 0, "bootstrap approval count must remain zero")
    require(pull_review_protection.get("dismiss_stale_reviews") is True, "stale review dismissal must be enabled")
    require(pull_review_protection.get("require_code_owner_reviews") is False, "code-owner review requirement drifted")
    require(pull_review_protection.get("require_last_push_approval") is False, "last-push approval requirement drifted")
    for field in ("enforce_admins", "required_linear_history", "required_conversation_resolution"):
        require(isinstance(protection.get(field), dict) and protection[field].get("enabled") is True, f"branch protection {field} must be enabled")
    for field in ("allow_force_pushes", "allow_deletions"):
        require(isinstance(protection.get(field), dict) and protection[field].get("enabled") is False, f"branch protection {field} must be disabled")

    repository_settings = response_value(bundles["control"], "repository-settings")
    require(isinstance(repository_settings, dict), "repository settings response must be an object")
    expected_repository_settings = {
        "full_name": "ZhangIvan/QingYin",
        "default_branch": "main",
        "private": False,
        "fork": False,
        "archived": False,
        "disabled": False,
        "allow_squash_merge": True,
        "allow_merge_commit": True,
        "allow_rebase_merge": True,
        "allow_auto_merge": False,
        "delete_branch_on_merge": False,
    }
    for field, expected in expected_repository_settings.items():
        require(repository_settings.get(field) == expected, f"repository setting drifted: {field}")
    require(
        isinstance(repository_settings.get("owner"), dict)
        and repository_settings["owner"].get("login") == "ZhangIvan",
        "repository owner identity mismatch",
    )
    require_positive_int(repository_settings["owner"].get("id"), "repository owner id")
    require(repository_settings["owner"]["id"] == OWNER_GITHUB_ID, "repository owner identity mismatch")

    rulesets = derive_stable_array_view(
        response_value(bundles["control"], "rulesets"),
        "rulesets",
        lambda item, item_index: (
            stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"rulesets[{item_index}].id"),
        ),
    )
    ruleset_ids: list[int] = []
    for index, ruleset in enumerate(rulesets):
        require(isinstance(ruleset, dict), f"ruleset[{index}] must be an object")
        require_positive_int(ruleset.get("id"), f"ruleset[{index}] id")
        require(isinstance(ruleset.get("name"), str) and ruleset["name"].strip(), f"ruleset[{index}] name missing")
        require(ruleset.get("target") == "branch" and ruleset.get("enforcement") == "active", f"ruleset[{index}] is not an active branch ruleset")
        require(ruleset.get("bypass_actors") == [], f"ruleset[{index}] contains bypass actors or incomplete bypass evidence")
        require(isinstance(ruleset.get("conditions"), dict) and isinstance(ruleset.get("rules"), list), f"ruleset[{index}] policy details missing")
        require(
            ruleset["conditions"] == {} and ruleset["rules"] == [],
            f"ruleset[{index}] contains unsupported non-empty policy details; freeze a new schema before accepting it",
        )
        ruleset_ids.append(ruleset["id"])
    require(len(ruleset_ids) == len(set(ruleset_ids)), "ruleset ids must be unique")

    validator_source = require_exact_object(
        response_value(bundles["control"], "validator-source"),
        ("schema", "candidate_head", "candidate_tree", "path", "mode", "type", "blob_sha1", "content_base64", "content_sha256"),
        "validator source evidence",
    )
    require(validator_source["schema"] == "gvn-validator-source-v1", "validator source schema mismatch")
    require(
        (validator_source["candidate_head"], validator_source["candidate_tree"]) == (candidate_head, candidate_tree),
        "validator source candidate binding mismatch",
    )
    require(validator_source["path"] == VALIDATOR_PATH.as_posix(), "validator source path mismatch")
    require(validator_source["mode"] == "100644" and validator_source["type"] == "blob", "validator source mode/type mismatch")
    require_sha1(validator_source["blob_sha1"], "validator source Git blob")
    require_sha256(validator_source["content_sha256"], "validator source content SHA-256")
    try:
        validator_source_bytes = base64.b64decode(validator_source["content_base64"], validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        fail(f"validator source content is not valid base64: {exc}")
    require(len(validator_source_bytes) <= MAX_VALIDATOR_SOURCE_BYTES, "validator source exceeds evidence size limit")
    validator_source_text = validate_utf8_bytes(validator_source_bytes, "validator source content")
    require_no_evidence_secret(validator_source_bytes, "validator source content")
    scan_python_literal_secrets(validator_source_text, "validator source content")
    require(hashlib.sha256(validator_source_bytes).hexdigest() == validator_source["content_sha256"], "validator source content SHA-256 mismatch")
    require(git_blob_sha1(validator_source_bytes) == validator_source["blob_sha1"], "validator source Git blob mismatch")
    validator_tree_entry = tree_entries.get(VALIDATOR_PATH.as_posix())
    require(
        isinstance(validator_tree_entry, dict)
        and (validator_tree_entry.get("mode"), validator_tree_entry.get("type"), validator_tree_entry.get("sha"))
        == (validator_source["mode"], validator_source["type"], validator_source["blob_sha1"]),
        "validator source is not bound to the candidate tree",
    )

    candidate_workflow_paths: list[str] = []
    for tree_path, tree_entry in tree_entries.items():
        if not tree_path.startswith(".github/workflows/") or not tree_path.endswith((".yml", ".yaml")):
            continue
        require(
            tree_path == unicodedata.normalize("NFC", tree_path)
            and "\x00" not in tree_path
            and all(segment not in ("", ".", "..") for segment in tree_path.split("/")),
            f"candidate workflow path is invalid: {tree_path!r}",
        )
        require(
            (tree_entry.get("mode"), tree_entry.get("type")) == ("100644", "blob"),
            f"candidate workflow must be a non-executable regular blob: {tree_path}",
        )
        candidate_workflow_paths.append(tree_path)
    candidate_workflow_paths.sort(key=utf16_sort_key)
    require(
        tuple(candidate_workflow_paths) == EXPECTED_WORKFLOW_PATHS,
        "candidate tree workflow inventory differs from the exact frozen workflow set",
    )

    workflow_blobs = require_exact_object(response_value(bundles["control"], "workflow-blobs"), ("candidate_head", "candidate_tree", "workflows"), "workflow blob evidence")
    require((workflow_blobs["candidate_head"], workflow_blobs["candidate_tree"]) == (candidate_head, candidate_tree), "workflow blob evidence candidate mismatch")
    require(isinstance(workflow_blobs["workflows"], list), "workflow blob evidence workflows must be an array")
    workflow_paths: list[str] = []
    expected_action_occurrences: list[dict[str, Any]] = []
    actual_run_hashes: dict[str, str] = {}
    for index, workflow_value in enumerate(workflow_blobs["workflows"]):
        workflow = require_exact_object(workflow_value, ("path", "blob", "content_base64", "content_sha256"), f"workflow blob[{index}]")
        require(isinstance(workflow["path"], str) and workflow["path"].startswith(".github/workflows/"), f"workflow blob[{index}] path invalid")
        require_sha1(workflow["blob"], f"workflow blob[{index}].blob")
        require_sha256(workflow["content_sha256"], f"workflow blob[{index}].content_sha256")
        try:
            workflow_bytes = base64.b64decode(workflow["content_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            fail(f"workflow blob[{index}] content is not valid base64: {exc}")
        workflow_text = validate_utf8_bytes(workflow_bytes, f"workflow blob[{index}] content")
        require(hashlib.sha256(workflow_bytes).hexdigest() == workflow["content_sha256"], f"workflow blob[{index}] content SHA-256 mismatch")
        require(
            workflow["content_sha256"] == EXPECTED_WORKFLOW_SHA256.get(workflow["path"]),
            f"workflow blob[{index}] differs from the frozen reviewed bytes",
        )
        require(git_blob_sha1(workflow_bytes) == workflow["blob"], f"workflow blob[{index}] Git blob mismatch")
        workflow_tree_entry = tree_entries.get(workflow["path"])
        require(
            isinstance(workflow_tree_entry, dict)
            and (workflow_tree_entry.get("mode"), workflow_tree_entry.get("type"), workflow_tree_entry.get("sha")) == ("100644", "blob", workflow["blob"]),
            f"workflow blob[{index}] is not bound to the candidate tree",
        )
        try:
            workflow_document = yaml.load(workflow_text, Loader=UniqueKeySafeLoader)
        except yaml.YAMLError as exc:
            fail(f"workflow blob[{index}] YAML invalid or ambiguous: {exc}")
        require(isinstance(workflow_document, dict), f"workflow blob[{index}] YAML root invalid")
        require(workflow_document.get("permissions") == {"contents": "read"}, f"workflow blob[{index}] top-level permissions must be contents: read")
        triggers = workflow_document.get("on", workflow_document.get(True))
        require(isinstance(triggers, dict), f"workflow blob[{index}] trigger map missing")
        require(set(triggers) == {"pull_request", "push"}, f"workflow blob[{index}] trigger set drifted")
        require("pull_request" in triggers and triggers["pull_request"] is None, f"workflow blob[{index}] must run on every pull request")
        push_trigger = triggers.get("push")
        require(isinstance(push_trigger, dict) and push_trigger.get("branches") == ["main"], f"workflow blob[{index}] main push trigger missing")
        expected_push_keys = {"branches"} if workflow["path"] == ".github/workflows/design-contracts.yml" else {"branches", "paths"}
        require(set(push_trigger) == expected_push_keys, f"workflow blob[{index}] push trigger fields drifted")
        if workflow["path"] == ".github/workflows/rust.yml":
            require(push_trigger.get("paths") == EXPECTED_RUST_PUSH_PATHS, "Rust workflow push path filter drifted")
        jobs = workflow_document.get("jobs")
        require(isinstance(jobs, dict) and jobs, f"workflow blob[{index}] jobs missing")
        if workflow["path"] == ".github/workflows/design-contracts.yml":
            require(set(jobs) == {"design-contracts"}, "design-contracts workflow job set drifted")
        else:
            require(set(jobs) == {"msrv", "format-lint", "unit", "security"}, "Rust workflow required job set drifted")
        for job_name, job in jobs.items():
            require(isinstance(job_name, str) and isinstance(job, dict), f"workflow blob[{index}] job invalid")
            require("permissions" not in job, f"workflow blob[{index}] job-level permissions override forbidden: {job_name}")
            require("if" not in job and job.get("continue-on-error", False) is False, f"workflow job cannot be conditional or continue-on-error: {workflow['path']}:{job_name}")
            require(job.get("name") in REQUIRED_CONTEXTS, f"workflow job context is not required: {workflow['path']}:{job_name}")
            require(job.get("runs-on") == EXPECTED_RUNNER_LABEL, f"workflow runner label drifted: {workflow['path']}:{job_name}")
            steps = job.get("steps")
            require(isinstance(steps, list) and steps, f"workflow blob[{index}] steps missing: {job_name}")
            step_names = [step.get("name") for step in steps if isinstance(step, dict)]
            expected_step_names = {
                "design-contracts": [
                    None,
                    None,
                    "Record immutable execution evidence",
                    "Install validation dependency",
                    "Validate design and contract assets",
                    "Validate documentation links",
                    "Validate governance state",
                ],
                "msrv": [
                    "Checkout repository",
                    "Install declared MSRV",
                    "Record immutable execution evidence",
                    "Record runner and toolchain evidence",
                    "Compile workspace on declared MSRV",
                ],
                "format-lint": [
                    "Checkout repository",
                    "Check formatting",
                    "Record immutable execution evidence",
                    "Check workspace",
                    "Run Clippy",
                    "Validate crate boundaries",
                    "Validate fixture manifest",
                ],
                "unit": ["Checkout repository", "Run workspace tests", "Record immutable execution evidence"],
                "security": [
                    "Checkout repository",
                    "Scan for credential regressions",
                    "Record immutable execution evidence",
                    "Run security boundary tests",
                ],
            }
            require(step_names == expected_step_names[job_name], f"workflow critical step sequence drifted: {workflow['path']}:{job_name}")
            require(step_names.count("Record immutable execution evidence") == 1, f"workflow execution evidence step missing or duplicated: {workflow['path']}:{job_name}")
            if workflow["path"] == ".github/workflows/design-contracts.yml":
                require(step_names.count("Validate governance state") == 1, "governance validator step missing or duplicated")
            for step_number, step in enumerate(steps, start=1):
                require(isinstance(step, dict), f"workflow blob[{index}] step invalid: {job_name}[{step_number}]")
                require("if" not in step and step.get("continue-on-error", False) is False, f"workflow step cannot be conditional or continue-on-error: {workflow['path']}:{job_name}[{step_number}]")
                has_uses = "uses" in step
                has_run = "run" in step
                require(has_uses != has_run, f"workflow step must contain exactly one of uses/run: {workflow['path']}:{job_name}[{step_number}]")
                if has_uses:
                    require(set(step).issubset({"name", "uses", "with"}), f"workflow action step contains unknown fields: {workflow['path']}:{job_name}[{step_number}]")
                    uses_value = step["uses"]
                    require(isinstance(uses_value, str), f"workflow action reference must be a scalar string: {workflow['path']}:{job_name}[{step_number}]")
                    action_match = re.fullmatch(r"([0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+)@([0-9a-f]{40})", uses_value)
                    require(action_match is not None, f"workflow action is not pinned to a lowercase 40-hex SHA: {workflow['path']}:{job_name}[{step_number}]")
                    require(
                        EXPECTED_ACTION_PINS.get(action_match.group(1)) == action_match.group(2),
                        f"workflow action is not in the frozen action/SHA allowlist: {workflow['path']}:{job_name}[{step_number}]",
                    )
                    expected_action_occurrences.append(
                        {
                            "path": workflow["path"],
                            "job": job_name,
                            "step": step_number,
                            "action": action_match.group(1),
                            "sha": action_match.group(2),
                        }
                    )
                    if action_match.group(1) == "actions/checkout":
                        require(
                            step.get("with") == {"fetch-depth": 0, "persist-credentials": False},
                            f"checkout must fetch full history without persisted credentials: {workflow['path']}:{job_name}[{step_number}]",
                        )
                    if action_match.group(1) == "actions/setup-python":
                        require(step.get("with") == {"python-version": "3.11"}, f"setup-python inputs drifted: {workflow['path']}:{job_name}[{step_number}]")
                else:
                    require(set(step) == {"name", "run"}, f"workflow run step fields drifted: {workflow['path']}:{job_name}[{step_number}]")
                    run_value = step["run"]
                    require(isinstance(step["name"], str) and step["name"].strip(), f"workflow run step name missing: {workflow['path']}:{job_name}[{step_number}]")
                    require(isinstance(run_value, str) and run_value.strip(), f"workflow run command must be a non-empty string: {workflow['path']}:{job_name}[{step_number}]")
                    run_key = f"{workflow['path']}|{job_name}|{step_number}|{step['name']}"
                    require(run_key not in actual_run_hashes, f"duplicate workflow run occurrence: {run_key}")
                    actual_run_hashes[run_key] = hashlib.sha256(run_value.encode("utf-8")).hexdigest()
                    require(EXPECTED_RUN_SHA256.get(run_key) == actual_run_hashes[run_key], f"workflow run scalar differs from frozen command: {run_key}")
                    if step["name"] == "Validate governance state":
                        require(run_value == "python scripts/validate_governance_state.py --self-test", "governance validator command drifted")
                    if step["name"] == "Record immutable execution evidence":
                        context_name = job["name"]
                        require(run_value.count("GVN_EXECUTION") == 1 and run_value.count("GVN_RUNNER") == 1, f"workflow marker count mismatch: {run_key}")
                        require(
                            run_value.count(f"context={context_name}") == 2 and run_value.count("context=") == 2,
                            f"workflow marker context mismatch: {run_key}",
                        )
                        for marker_field in ("sha=%s", "tree=%s", "parents=%s", "label=ubuntu-24.04", "os=%s", "arch=%s", "image_os=%s", "image_version=%s", "repository=%s", "event=%s", "shallow=false"):
                            require(marker_field in run_value, f"workflow marker field missing ({marker_field}): {run_key}")
                    if re.search(r"(?:^|\s)cargo(?:\s+\+\S+)?\s+(?:check|clippy|test)\b", run_value):
                        require("--locked" in run_value.split(), f"Cargo execution must use --locked: {workflow['path']}:{job_name}[{step_number}]")
        workflow_paths.append(workflow["path"])
    require(workflow_paths == sorted(set(workflow_paths), key=utf16_sort_key), "workflow blob paths must be unique and sorted")
    require(tuple(workflow_paths) == EXPECTED_WORKFLOW_PATHS, "workflow blob inventory must contain the exact frozen workflow set")
    require(workflow_paths == candidate_workflow_paths, "workflow evidence inventory differs from the candidate recursive tree")
    require(actual_run_hashes == EXPECTED_RUN_SHA256, "workflow run occurrence inventory differs from the frozen command set")
    require(expected_action_occurrences, "workflow action inventory cannot be empty")
    expected_action_occurrences.sort(key=lambda item: (utf16_sort_key(item["path"]), utf16_sort_key(item["job"]), item["step"], utf16_sort_key(item["action"]), utf16_sort_key(item["sha"])))

    action_pins = require_exact_object(
        response_value(bundles["control"], "action-pins"),
        ("schema", "candidate_head", "candidate_tree", "occurrences"),
        "action pin evidence",
    )
    require(action_pins["schema"] == "gvn-action-pins-v1", "action pin schema mismatch")
    require((action_pins["candidate_head"], action_pins["candidate_tree"]) == (candidate_head, candidate_tree), "action pin candidate mismatch")
    require(action_pins["occurrences"] == expected_action_occurrences, "action pin inventory differs from the complete workflow content")

    owner_identity = response_value(bundles["identity"], "owner-identity")
    require(
        isinstance(owner_identity, dict)
        and owner_identity.get("login") == "ZhangIvan"
        and owner_identity.get("type") == "User",
        "owner immutable identity evidence mismatch",
    )
    require_positive_int(owner_identity.get("id"), "owner immutable identity id")
    require(owner_identity["id"] == OWNER_GITHUB_ID, "owner immutable identity evidence mismatch")
    collaborators = response_value(bundles["identity"], "collaborators")
    require(isinstance(collaborators, list) and len(collaborators) == 1, "repository must have exactly one collaborator for the single-maintainer decision")
    collaborator = collaborators[0]
    require(isinstance(collaborator, dict), "collaborator response item invalid")
    require_positive_int(collaborator.get("id"), "collaborator id")
    require((collaborator.get("login"), collaborator.get("role_name")) == ("ZhangIvan", "admin"), "collaborator identity/role mismatch")
    require(collaborator["id"] == OWNER_GITHUB_ID, "collaborator identity/role mismatch")
    permissions = collaborator.get("permissions")
    require(isinstance(permissions, dict) and all(permissions.get(name) is True for name in ("admin", "maintain", "push", "triage", "pull")), "owner collaborator permissions incomplete")

    security_settings = response_value(bundles["security"], "security-settings")
    require(isinstance(security_settings, dict), "security settings response must be an object")
    security_and_analysis = security_settings.get("security_and_analysis")
    require(isinstance(security_and_analysis, dict), "repository security_and_analysis settings missing")
    for field in ("secret_scanning", "secret_scanning_push_protection", "dependabot_security_updates"):
        require(isinstance(security_and_analysis.get(field), dict) and security_and_analysis[field].get("status") == "enabled", f"security setting is not enabled: {field}")

    lockfiles = require_exact_object(
        response_value(bundles["runner"], "toolchain-lockfiles"),
        ("schema", "candidate_head", "candidate_tree", "files"),
        "toolchain lockfile evidence",
    )
    require(lockfiles["schema"] == "gvn-toolchain-lockfiles-v1", "toolchain lockfile schema mismatch")
    require((lockfiles["candidate_head"], lockfiles["candidate_tree"]) == (candidate_head, candidate_tree), "toolchain lockfile candidate mismatch")
    require(isinstance(lockfiles["files"], list) and len(lockfiles["files"]) == 2, "toolchain lockfile inventory cardinality mismatch")
    lockfile_contents: dict[str, bytes] = {}
    lockfile_paths: list[str] = []
    for index, file_value in enumerate(lockfiles["files"]):
        file_item = require_exact_object(file_value, ("path", "mode", "blob", "content_base64", "content_sha256"), f"toolchain lockfile[{index}]")
        require(file_item["path"] in ("Cargo.lock", "rust-toolchain.toml"), f"toolchain lockfile[{index}] path invalid")
        require(file_item["mode"] == "100644", f"toolchain lockfile[{index}] mode invalid")
        require_sha1(file_item["blob"], f"toolchain lockfile[{index}].blob")
        require_sha256(file_item["content_sha256"], f"toolchain lockfile[{index}].content_sha256")
        try:
            content = base64.b64decode(file_item["content_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            fail(f"toolchain lockfile[{index}] content is not valid base64: {exc}")
        validate_utf8_bytes(content, f"toolchain lockfile[{index}] content")
        require(hashlib.sha256(content).hexdigest() == file_item["content_sha256"], f"toolchain lockfile[{index}] content SHA-256 mismatch")
        require(git_blob_sha1(content) == file_item["blob"], f"toolchain lockfile[{index}] Git blob mismatch")
        lockfile_tree_entry = tree_entries.get(file_item["path"])
        require(
            isinstance(lockfile_tree_entry, dict)
            and (lockfile_tree_entry.get("mode"), lockfile_tree_entry.get("type"), lockfile_tree_entry.get("sha"))
            == (file_item["mode"], "blob", file_item["blob"]),
            f"toolchain lockfile[{index}] is not bound to the candidate tree",
        )
        lockfile_contents[file_item["path"]] = content
        lockfile_paths.append(file_item["path"])
    require(lockfile_paths == ["Cargo.lock", "rust-toolchain.toml"], "toolchain lockfiles must be unique and canonically ordered")
    try:
        cargo_lock = tomllib.loads(lockfile_contents["Cargo.lock"].decode("utf-8"))
        toolchain = tomllib.loads(lockfile_contents["rust-toolchain.toml"].decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        fail(f"toolchain lockfile TOML invalid: {exc}")
    require(cargo_lock.get("version") == 4 and isinstance(cargo_lock.get("package"), list) and cargo_lock["package"], "Cargo.lock format or package inventory invalid")
    toolchain_table = toolchain.get("toolchain")
    require(isinstance(toolchain_table, dict), "rust-toolchain.toml toolchain table missing")
    require(toolchain_table.get("channel") == "1.97.0", "repository toolchain channel drifted")
    require(toolchain_table.get("components") == ["clippy", "rustfmt"] and toolchain_table.get("profile") == "minimal", "repository toolchain components/profile drifted")

    provenance = require_exact_object(
        response_value(bundles["runner"], "runner-provenance"),
        ("schema", "base_sha", "candidate_head", "candidate_tree", "executions"),
        "runner provenance",
    )
    require(provenance["schema"] == "gvn-runner-provenance-v1", "runner provenance schema mismatch")
    require((provenance["base_sha"], provenance["candidate_head"], provenance["candidate_tree"]) == (base_sha, candidate_head, candidate_tree), "runner provenance candidate mismatch")
    require(isinstance(provenance["executions"], list) and len(provenance["executions"]) == len(REQUIRED_CONTEXTS), "runner provenance execution cardinality mismatch")
    workflow_runs_response = response_value(bundles["checks"], "workflow-runs")
    workflow_runs = workflow_runs_response["workflow_runs"]
    workflow_runs = derive_stable_array_view(
        workflow_runs,
        "workflow-runs.workflow_runs",
        lambda item, item_index: (
            stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"workflow-runs.workflow_runs[{item_index}].id"),
        ),
    )
    for run_index, run in enumerate(workflow_runs):
        require(isinstance(run, dict), f"workflow-run[{run_index}] must be an object")
        require_positive_int(run.get("id"), f"workflow-run[{run_index}] id")
        require_positive_int(run.get("run_attempt"), f"workflow-run[{run_index}] run_attempt")
        require(isinstance(run.get("check_suite"), dict), f"workflow-run[{run_index}] check suite missing")
        require_positive_int(run["check_suite"].get("id"), f"workflow-run[{run_index}] check suite id")
        for field in ("created_at", "run_started_at", "updated_at"):
            require_utc_timestamp(run.get(field), f"workflow-run[{run_index}].{field}")
        require(
            candidate["committed_at"] <= run["created_at"] <= run["run_started_at"] <= run["updated_at"] <= effective_cutoff,
            f"workflow-run[{run_index}] timestamps are outside the candidate/cutoff interval",
        )
    contexts: list[str] = []
    check_run_ids: list[int] = []
    for index, execution_value in enumerate(provenance["executions"]):
        execution = require_exact_object(
            execution_value,
            (
                "context",
                "check_run_id",
                "check_suite_id",
                "external_id",
                "run_id",
                "job_id",
                "workflow_path",
                "event",
                "run_attempt",
                "runner_label",
                "runner_os",
                "runner_arch",
                "image_os",
                "image_version",
                "repository",
                "shallow",
                "started_at",
                "completed_at",
                "log_sha256",
                "execution_sha",
                "execution_tree",
                "ordered_parents",
            ),
            f"runner execution[{index}]",
        )
        require(execution["context"] in REQUIRED_CONTEXTS, f"runner execution[{index}] context invalid")
        for field in ("check_run_id", "check_suite_id", "run_id", "job_id", "run_attempt"):
            require_positive_int(execution[field], f"runner execution[{index}].{field}")
        require(execution["workflow_path"] == CONTEXT_WORKFLOW_PATHS[execution["context"]], f"runner execution[{index}] workflow path mismatch")
        require(execution["event"] == "pull_request", f"runner execution[{index}] event mismatch")
        require(execution["runner_label"] == EXPECTED_RUNNER_LABEL, f"runner execution[{index}] label mismatch")
        require(execution["runner_os"] == "Linux" and execution["runner_arch"] == "X64", f"runner execution[{index}] OS/architecture mismatch")
        for field in ("image_os", "image_version"):
            require(
                isinstance(execution[field], str)
                and re.fullmatch(r"[0-9A-Za-z._-]{1,64}", execution[field]) is not None
                and execution[field].casefold() != "unknown",
                f"runner execution[{index}].{field} missing or unsafe",
            )
        require(execution["repository"] == "ZhangIvan/QingYin", f"runner execution[{index}] repository mismatch")
        require(execution["shallow"] is False, f"runner execution[{index}] used a shallow checkout")
        require(isinstance(execution["external_id"], str) and execution["external_id"].strip(), f"runner execution[{index}] external id missing")
        require_utc_timestamp(execution["started_at"], f"runner execution[{index}].started_at")
        require_utc_timestamp(execution["completed_at"], f"runner execution[{index}].completed_at")
        require(candidate["committed_at"] <= execution["started_at"] <= execution["completed_at"] <= effective_cutoff, f"runner execution[{index}] timestamps are outside the candidate/cutoff interval")
        require_sha1(execution["execution_sha"], f"runner execution[{index}].execution_sha")
        require_sha256(execution["log_sha256"], f"runner execution[{index}].log_sha256")
        require(execution["execution_tree"] == candidate_tree, f"runner execution[{index}] tree mismatch")
        require(execution["ordered_parents"] == [base_sha, candidate_head], f"runner execution[{index}] ordered parents mismatch")
        matching_checks = [item for item in check_runs if item.get("id") == execution["check_run_id"] and item.get("name") == execution["context"]]
        require(len(matching_checks) == 1, f"runner execution[{index}] check-run binding mismatch")
        check_run = matching_checks[0]
        require(check_run["check_suite"].get("id") == execution["check_suite_id"], f"runner execution[{index}] check-suite binding mismatch")
        require(check_run.get("external_id") == execution["external_id"], f"runner execution[{index}] external-id binding mismatch")
        require((check_run.get("started_at"), check_run.get("completed_at")) == (execution["started_at"], execution["completed_at"]), f"runner execution[{index}] check timing mismatch")
        require(check_run.get("details_url") == f"https://github.com/ZhangIvan/QingYin/actions/runs/{execution['run_id']}/job/{execution['job_id']}", f"runner execution[{index}] details URL does not bind run/job")
        matching_runs = [item for item in workflow_runs if isinstance(item, dict) and item.get("id") == execution["run_id"]]
        require(len(matching_runs) == 1 and matching_runs[0].get("head_sha") == candidate_head, f"runner execution[{index}] workflow-run binding mismatch")
        run = matching_runs[0]
        require(
            run.get("event") == execution["event"]
            and run.get("path") == execution["workflow_path"]
            and run.get("run_attempt") == execution["run_attempt"]
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and isinstance(run.get("check_suite"), dict)
            and run["check_suite"].get("id") == execution["check_suite_id"],
            f"runner execution[{index}] workflow run provenance mismatch",
        )
        contexts.append(execution["context"])
        check_run_ids.append(execution["check_run_id"])
    require(tuple(contexts) == REQUIRED_CONTEXTS, "runner execution contexts must be unique and sorted")
    require(len(set(check_run_ids)) == len(check_run_ids), "runner execution check-run ids must be unique")
    require(len({item["job_id"] for item in provenance["executions"]}) == len(REQUIRED_CONTEXTS), "runner execution job ids must be unique")
    require(len({item["external_id"] for item in provenance["executions"]}) == len(REQUIRED_CONTEXTS), "runner execution external ids must be unique")
    require({item.get("id") for item in workflow_runs if isinstance(item, dict)} == {item["run_id"] for item in provenance["executions"]}, "workflow-runs contains missing or unrelated runs")
    jobs_response = require_exact_object(response_value(bundles["checks"], "workflow-jobs"), ("jobs",), "workflow jobs aggregate")
    require(isinstance(jobs_response["jobs"], list) and len(jobs_response["jobs"]) == len(REQUIRED_CONTEXTS), "workflow jobs aggregate must contain exactly five required jobs")
    require_stable_array_order(
        jobs_response["jobs"],
        "workflow-jobs.jobs",
        lambda item, item_index: (
            stable_integer_component(item.get("job_id") if isinstance(item, dict) else None, f"workflow-jobs.jobs[{item_index}].job_id"),
        ),
    )
    for job_index, job in enumerate(jobs_response["jobs"]):
        require(isinstance(job, dict), f"workflow job[{job_index}] must be an object")
        for field in ("job_id", "run_id", "check_run_id"):
            require_positive_int(job.get(field), f"workflow job[{job_index}].{field}")
        require_utc_timestamp(job.get("started_at"), f"workflow job[{job_index}].started_at")
        require_utc_timestamp(job.get("completed_at"), f"workflow job[{job_index}].completed_at")
        require(candidate["committed_at"] <= job["started_at"] <= job["completed_at"] <= effective_cutoff, f"workflow job[{job_index}] timestamps are outside the candidate/cutoff interval")
    log_records = workflow_log_records(bundles["checks"])
    require(set(log_records) == {item["job_id"] for item in provenance["executions"]}, "workflow logs contain missing or unrelated job logs")
    execution_objects = require_exact_object(response_value(bundles["runner"], "execution-objects"), ("objects",), "execution Git objects")
    require(isinstance(execution_objects["objects"], list) and len(execution_objects["objects"]) == len(REQUIRED_CONTEXTS), "execution Git objects must contain exactly five required contexts")
    require(
        tuple(item.get("context") for item in execution_objects["objects"] if isinstance(item, dict)) == REQUIRED_CONTEXTS,
        "execution Git objects must follow the fixed required-context sequence",
    )
    for execution in provenance["executions"]:
        matching_jobs = [
            job
            for job in jobs_response["jobs"]
            if isinstance(job, dict)
            and job.get("job_id") == execution["job_id"]
            and job.get("run_id") == execution["run_id"]
            and job.get("context") == execution["context"]
            and job.get("check_run_id") == execution["check_run_id"]
        ]
        require(len(matching_jobs) == 1, f"runner execution job binding mismatch: {execution['context']}")
        require(matching_jobs[0].get("status") == "completed" and matching_jobs[0].get("conclusion") == "success", f"workflow job is not successful: {execution['context']}")
        require(matching_jobs[0].get("name") == execution["context"] and matching_jobs[0].get("workflow_path") == execution["workflow_path"], f"workflow job name/path mismatch: {execution['context']}")
        require((matching_jobs[0].get("started_at"), matching_jobs[0].get("completed_at")) == (execution["started_at"], execution["completed_at"]), f"workflow job timing mismatch: {execution['context']}")
        log_record = log_records.get(execution["job_id"])
        require(log_record is not None and log_record[0] == execution["log_sha256"], f"workflow log hash mismatch: {execution['context']}")
        log_text = validate_utf8_bytes(log_record[1], f"workflow log for {execution['context']}")
        marker = (
            f"GVN_EXECUTION context={execution['context']} sha={execution['execution_sha']} "
            f"tree={execution['execution_tree']} parents={root['base_sha']} {root['candidate_head']}"
        )
        require(log_text.count(marker) == 1, f"workflow log execution marker missing or ambiguous: {execution['context']}")
        runner_marker = (
            f"GVN_RUNNER context={execution['context']} label={execution['runner_label']} os={execution['runner_os']} "
            f"arch={execution['runner_arch']} image_os={execution['image_os']} image_version={execution['image_version']} "
            f"repository={execution['repository']} event={execution['event']} shallow=false"
        )
        require(log_text.count(runner_marker) == 1, f"workflow log runner marker missing or ambiguous: {execution['context']}")
        matching_objects = [
            item
            for item in execution_objects["objects"]
            if isinstance(item, dict)
            and item.get("context") == execution["context"]
            and item.get("execution_sha") == execution["execution_sha"]
        ]
        require(len(matching_objects) == 1, f"execution Git object missing: {execution['context']}")
        require(matching_objects[0].get("object_type") == "commit", f"execution Git object type mismatch: {execution['context']}")
        require(matching_objects[0].get("tree") == execution["execution_tree"], f"execution Git tree mismatch: {execution['context']}")
        require(matching_objects[0].get("ordered_parents") == execution["ordered_parents"], f"execution Git parents mismatch: {execution['context']}")


def validate_merge_response_semantics(
    merge_bundle: dict[str, Any],
    root: dict[str, Any],
    effective_merge_sha: str,
    owner_id: int,
    changed_paths: list[str],
    post_cutoff_utc: str,
) -> None:
    require_utc_timestamp(post_cutoff_utc, "post-merge cutoff")
    require(effective_merge_sha != root["candidate_head"], "squash merge commit cannot equal the candidate head")
    main_ref = response_value(merge_bundle, "main-ref")
    require(isinstance(main_ref, dict) and isinstance(main_ref.get("object"), dict), "post-merge main ref response invalid")
    require(main_ref.get("ref") == "refs/heads/main", "post-merge ref is not refs/heads/main")
    require(main_ref["object"].get("type") == "commit", "post-merge main ref does not name a commit")
    require(main_ref["object"].get("sha") == effective_merge_sha, "post-merge main ref does not equal merge SHA")
    commit = require_exact_object(response_value(merge_bundle, "merge-commit"), ("object_type", "commit", "tree", "parents"), "merge commit evidence")
    require(commit["object_type"] == "commit", "merge Git object type mismatch")
    require(commit["commit"] == effective_merge_sha, "merge commit evidence SHA mismatch")
    require(commit["tree"] == root["candidate_tree"], "squash merge tree differs from candidate tree")
    require(commit["parents"] == [root["base_sha"]], "squash merge must have the exact base as its single parent")
    merge_response = response_value(merge_bundle, "merge-response")
    require(isinstance(merge_response, dict) and merge_response.get("merged") is True, "merge response did not confirm merged=true")
    require(merge_response.get("sha") == effective_merge_sha, "merge response SHA mismatch")
    require(isinstance(merge_response.get("message"), str) and merge_response["message"].strip(), "merge response message missing")
    merged_pull = response_value(merge_bundle, "merged-pull")
    require(isinstance(merged_pull, dict), "merged pull response invalid")
    require_positive_int(merged_pull.get("number"), "merged pull number")
    require(merged_pull.get("number") == root["pr_number"], "merged pull number mismatch")
    require(merged_pull.get("state") == "closed" and merged_pull.get("merged") is True, "pull is not closed and merged")
    require(merged_pull.get("merge_commit_sha") == effective_merge_sha, "merged pull commit SHA mismatch")
    require(
        isinstance(merged_pull.get("merged_by"), dict)
        and merged_pull["merged_by"].get("login") == "ZhangIvan",
        "merge actor does not match the owner immutable identity",
    )
    require_positive_int(merged_pull["merged_by"].get("id"), "merge actor id")
    require(merged_pull["merged_by"]["id"] == owner_id, "merge actor does not match the owner immutable identity")
    require_utc_timestamp(merged_pull.get("merged_at"), "merged pull merged_at")
    require(merged_pull["merged_at"] <= post_cutoff_utc, "merged pull is newer than the post-merge cutoff")
    require(merged_pull.get("auto_merge") is None, "auto-merge must remain disabled")
    post_metadata = response_value(merge_bundle, "post-merge-metadata")
    post_metadata_root = require_exact_object(post_metadata, ("data",), "post-merge GraphQL response")
    repository = post_metadata_root["data"].get("repository") if isinstance(post_metadata_root["data"], dict) else None
    post_pr = repository.get("pullRequest") if isinstance(repository, dict) else None
    require(isinstance(post_pr, dict), "post-merge GraphQL pull request missing")
    require_positive_int(post_pr.get("number"), "post-merge GraphQL PR number")
    require(post_pr.get("number") == root["pr_number"], "post-merge GraphQL PR number mismatch")
    require(post_pr.get("baseRefOid") == root["base_sha"] and post_pr.get("headRefOid") == root["candidate_head"], "post-merge GraphQL candidate binding mismatch")
    require(post_pr.get("autoMergeRequest") is None and post_pr.get("mergeQueueEntry") is None, "post-merge auto-merge/queue state must be empty")
    post_checks = response_value(merge_bundle, "post-merge-checks")
    require(isinstance(post_checks, dict) and isinstance(post_checks.get("check_runs"), list), "post-merge checks response invalid")
    rust_exact_paths = set(EXPECTED_RUST_PUSH_PATHS[2:])
    rust_scheduled = any(path.startswith(".cargo/") or path.startswith("crates/") or path in rust_exact_paths for path in changed_paths)
    expected_post_contexts = REQUIRED_CONTEXTS if rust_scheduled else ("contract-fixtures",)
    require_nonnegative_int(post_checks.get("total_count"), "post-merge checks.total_count")
    require(post_checks.get("total_count") == len(post_checks["check_runs"]) == len(expected_post_contexts), "post-merge checks response is incomplete or has unexpected scheduling")
    post_check_runs = derive_stable_array_view(
        post_checks["check_runs"],
        "post-merge-checks.check_runs",
        lambda item, item_index: (
            stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"post-merge-checks.check_runs[{item_index}].id"),
        ),
    )
    post_check_names: list[str] = []
    for index, item in enumerate(post_check_runs):
        require(isinstance(item, dict), f"post-merge check[{index}] must be an object")
        require(item.get("head_sha") == effective_merge_sha, f"post-merge check[{index}] head SHA mismatch")
        require(item.get("status") == "completed" and item.get("conclusion") == "success", f"post-merge check[{index}] is not successful")
        require(isinstance(item.get("name"), str) and item["name"], f"post-merge check[{index}] name missing")
        require_positive_int(item.get("id"), f"post-merge check[{index}] id")
        require(isinstance(item.get("check_suite"), dict), f"post-merge check[{index}] check suite missing")
        require_positive_int(item["check_suite"].get("id"), f"post-merge check[{index}] suite id")
        require(isinstance(item.get("external_id"), str) and item["external_id"].strip(), f"post-merge check[{index}] external id missing")
        require(isinstance(item.get("details_url"), str) and item["details_url"].startswith("https://github.com/ZhangIvan/QingYin/actions/runs/"), f"post-merge check[{index}] details URL invalid")
        require_utc_timestamp(item.get("started_at"), f"post-merge check[{index}].started_at")
        require_utc_timestamp(item.get("completed_at"), f"post-merge check[{index}].completed_at")
        require(
            merged_pull["merged_at"] <= item["started_at"] <= item["completed_at"] <= post_cutoff_utc,
            f"post-merge check[{index}] timing is outside the merge/post-cutoff interval",
        )
        require(
            isinstance(item.get("app"), dict)
            and item["app"].get("slug") == "github-actions"
            and isinstance(item["app"].get("owner"), dict)
            and item["app"]["owner"].get("login") == "github",
            f"post-merge check[{index}] app identity mismatch",
        )
        require_positive_int(item["app"].get("id"), f"post-merge check[{index}] app id")
        require(item["app"]["id"] == GITHUB_ACTIONS_APP_ID, f"post-merge check[{index}] app identity mismatch")
        post_check_names.append(item["name"])
    require(tuple(sorted(post_check_names, key=utf16_sort_key)) == expected_post_contexts, "post-merge scheduled/NOT_SCHEDULED context derivation mismatch")
    require(len({item["id"] for item in post_checks["check_runs"]}) == len(expected_post_contexts), "post-merge check ids must be unique")
    require(len({item["external_id"] for item in post_checks["check_runs"]}) == len(expected_post_contexts), "post-merge external ids must be unique")


def bundle_digest_map(values: Any, expected_components: tuple[str, ...], label: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    require(isinstance(values, list) and len(values) == len(expected_components), f"{label} bundle cardinality mismatch")
    bundles: list[dict[str, Any]] = []
    bundle_map: dict[str, dict[str, Any]] = {}
    digest_map: dict[str, str] = {}
    for index, bundle_value in enumerate(values):
        validate_endpoint_bundle_v3(bundle_value)
        component = str(bundle_value["component"])
        require(component == expected_components[index], f"{label} component order mismatch at {index}: {component}")
        require(component not in bundle_map, f"duplicate {label} component: {component}")
        bundles.append(bundle_value)
        bundle_map[component] = bundle_value
        digest_map[component] = hashlib.sha256(canonical_json_v1(bundle_value)).hexdigest()
    return bundles, bundle_map, digest_map


def validate_publication_delta_v1(
    value: Any,
    pre_bundles: dict[str, dict[str, Any]],
    snapshot_bundles: dict[str, dict[str, Any]],
    attestation: dict[str, Any],
    pre_cutoff: str,
    snapshot_cutoff: str,
) -> None:
    delta = require_exact_object(
        value,
        (
            "schema",
            "attestation_comment_id",
            "attestation_comment_created_at",
            "attestation_comment_updated_at",
            "pull_updated_at_before",
            "pull_updated_at_after",
            "pull_comments_before",
            "pull_comments_after",
        ),
        "publication delta",
    )
    require(delta["schema"] == "gvn-publication-delta-v1", "publication delta schema mismatch")
    require_positive_int(delta["attestation_comment_id"], "publication delta comment id")
    for field in (
        "attestation_comment_created_at",
        "attestation_comment_updated_at",
        "pull_updated_at_before",
        "pull_updated_at_after",
    ):
        require_utc_timestamp(delta[field], f"publication delta {field}")
    for field in ("pull_comments_before", "pull_comments_after"):
        require_nonnegative_int(delta[field], f"publication delta {field}")

    for component in PRE_ATTESTATION_COMPONENTS:
        if component not in ("pr", "metadata", "discussion"):
            require(
                canonical_json_v1(pre_bundles[component]) == canonical_json_v1(snapshot_bundles[component]),
                f"publication changed forbidden component: {component}",
            )

    pre_pull = response_value(pre_bundles["pr"], "pull")
    snapshot_pull = response_value(snapshot_bundles["pr"], "pull")
    require(isinstance(pre_pull, dict) and isinstance(snapshot_pull, dict), "pull responses must be objects")
    require(set(pre_pull) == set(snapshot_pull), "pull response keys changed across publication")
    require_positive_int(pre_pull.get("number"), "pre-snapshot pull number")
    require_positive_int(snapshot_pull.get("number"), "snapshot pull number")
    require_nonnegative_int(pre_pull.get("comments"), "pre-snapshot pull comment count")
    require_nonnegative_int(snapshot_pull.get("comments"), "snapshot pull comment count")
    for key in pre_pull:
        if key not in ("updated_at", "comments"):
            require(pre_pull[key] == snapshot_pull[key], f"pull field changed across publication: {key}")
    require(pre_pull.get("updated_at") == delta["pull_updated_at_before"], "publication delta pull_updated_at_before mismatch")
    require(snapshot_pull.get("updated_at") == delta["pull_updated_at_after"], "publication delta pull_updated_at_after mismatch")
    require(pre_pull.get("comments") == delta["pull_comments_before"], "publication delta pull_comments_before mismatch")
    require(snapshot_pull.get("comments") == delta["pull_comments_after"], "publication delta pull_comments_after mismatch")
    require(delta["pull_comments_after"] == delta["pull_comments_before"] + 1, "publication must increase pull comment count by exactly one")

    pre_metadata_item = response_item(pre_bundles["metadata"], "pull-metadata")
    snapshot_metadata_item = response_item(snapshot_bundles["metadata"], "pull-metadata")
    require(pre_metadata_item["request"] == snapshot_metadata_item["request"], "pull metadata request changed across publication")
    pre_metadata_pr = response_value(pre_bundles["metadata"], "pull-metadata")["data"]["repository"]["pullRequest"]
    snapshot_metadata_pr = response_value(snapshot_bundles["metadata"], "pull-metadata")["data"]["repository"]["pullRequest"]
    require(set(pre_metadata_pr) == set(snapshot_metadata_pr), "pull metadata fields changed across publication")
    for key in pre_metadata_pr:
        if key != "updatedAt":
            require(pre_metadata_pr[key] == snapshot_metadata_pr[key], f"pull metadata field changed across publication: {key}")
    require(pre_metadata_pr.get("updatedAt") == delta["pull_updated_at_before"], "publication metadata updatedAt before mismatch")
    require(snapshot_metadata_pr.get("updatedAt") == delta["pull_updated_at_after"], "publication metadata updatedAt after mismatch")

    pre_discussion = pre_bundles["discussion"]
    snapshot_discussion = snapshot_bundles["discussion"]
    require(
        response_value(pre_discussion, "review-threads") == response_value(snapshot_discussion, "review-threads"),
        "review threads changed across attestation publication",
    )
    pre_comments = response_value(pre_discussion, "issue-comments")
    snapshot_comments = response_value(snapshot_discussion, "issue-comments")
    comment = response_value(snapshot_bundles["attestation"], "attestation-comment")
    require(isinstance(pre_comments, list) and isinstance(snapshot_comments, list), "issue-comments responses must be arrays")
    require(isinstance(comment, dict) and isinstance(comment.get("user"), dict), "attestation comment response shape invalid")
    require_positive_int(comment.get("id"), "publication attestation comment id")
    require_positive_int(comment["user"].get("id"), "publication attestation comment author id")
    pre_comment_ids = [item.get("id") if isinstance(item, dict) else None for item in pre_comments]
    snapshot_comment_ids = [item.get("id") if isinstance(item, dict) else None for item in snapshot_comments]
    for comment_index, item_id in enumerate(pre_comment_ids):
        require_positive_int(item_id, f"pre-snapshot comment[{comment_index}] id")
    for comment_index, item_id in enumerate(snapshot_comment_ids):
        require_positive_int(item_id, f"snapshot comment[{comment_index}] id")
    require(len(set(pre_comment_ids)) == len(pre_comment_ids), "pre-snapshot comment ids are not unique")
    require(len(set(snapshot_comment_ids)) == len(snapshot_comment_ids), "snapshot comment ids are not unique")
    require(snapshot_comments == [*pre_comments, comment], "publication must append exactly the attestation comment")
    require(comment.get("id") not in pre_comment_ids, "attestation comment id already existed before publication")
    require(comment.get("id") == delta["attestation_comment_id"], "publication delta comment id mismatch")
    require(comment.get("created_at") == delta["attestation_comment_created_at"], "publication delta comment created_at mismatch")
    require(comment.get("updated_at") == delta["attestation_comment_updated_at"], "publication delta comment updated_at mismatch")
    require(comment["user"].get("login") == attestation["attestor_login"], "publication comment author identity mismatch")
    require(comment["user"]["id"] == attestation["attestor_id"], "publication comment author identity mismatch")
    require(comment.get("body") == canonical_json_v1(attestation).decode("utf-8"), "publication comment body differs from canonical attestation")
    require(delta["pull_updated_at_after"] == delta["attestation_comment_updated_at"], "pull updated_at is not attributable to the attestation comment")
    require(delta["pull_comments_before"] == len(pre_comments), "pull comment count does not match pre-snapshot comments")
    require(delta["pull_comments_after"] == len(snapshot_comments), "pull comment count does not match snapshot comments")
    pre_time = datetime.strptime(pre_cutoff, "%Y-%m-%dT%H:%M:%SZ")
    snapshot_time = datetime.strptime(snapshot_cutoff, "%Y-%m-%dT%H:%M:%SZ")
    created_time = datetime.strptime(delta["attestation_comment_created_at"], "%Y-%m-%dT%H:%M:%SZ")
    updated_time = datetime.strptime(delta["attestation_comment_updated_at"], "%Y-%m-%dT%H:%M:%SZ")
    require(pre_time < created_time <= updated_time <= snapshot_time, "attestation publication timestamps fall outside snapshot cutoffs")


def agent_review_references(review_bundle: dict[str, Any]) -> list[dict[str, str]]:
    artifact = response_value(review_bundle, "agent-reviews")
    require(isinstance(artifact, dict) and isinstance(artifact.get("reviews"), list), "agent review references missing")
    return [
        {"reviewer_id": review["reviewer_id"], "report_sha256": review["report_sha256"]}
        for review in artifact["reviews"]
    ]


def derive_evidence_target_type(
    package: dict[str, Any],
    root: dict[str, Any],
    authorized_target_type: str | None = None,
) -> str:
    require(authorized_target_type in (None, "activation-evidence"), "authorized evidence target type invalid")
    binding = package["activation_binding"]
    if authorized_target_type is None:
        require(binding is None, "non-authorized evidence must not carry an activation binding")
        target_type = "governance-bootstrap" if root["pr_number"] == EXPECTED_GOVERNANCE_PR else "ordinary"
        if target_type == "governance-bootstrap":
            require_governance_bootstrap_base(root["base_sha"])
        return target_type
    require(isinstance(binding, dict), "activation binding must be an object")
    require_positive_int(binding.get("activation_evidence_pr"), "activation binding PR number")
    require(binding["activation_evidence_pr"] == root["pr_number"], "activation binding PR differs from evidence root")
    require(binding.get("activation_candidate_head") == root["candidate_head"], "activation binding head differs from evidence root")
    require(binding.get("activation_candidate_tree") == root["candidate_tree"], "activation binding tree differs from evidence root")
    return authorized_target_type


def require_merge_ready_freshness(target_type: str) -> None:
    require(
        target_type in ONE_TIME_TARGET_TYPES,
        "ordinary merge-ready evidence requires a trusted freshness receipt schema",
    )


def validate_finding_ledger(
    bundle: dict[str, Any],
    review_bundle: dict[str, Any],
    cutoff_utc: str,
    root: dict[str, Any],
    attestation: dict[str, Any] | None,
    target_type: str,
) -> None:
    require(target_type in (*ONE_TIME_TARGET_TYPES, "ordinary"), "evidence target type invalid")
    candidate_head = root["candidate_head"]
    expected_residual_ids = RESIDUAL_IDS if target_type in ONE_TIME_TARGET_TYPES else COMMON_RESIDUAL_IDS
    ledger = require_exact_object(response_value(bundle, "finding-ledger"), ("findings",), "finding ledger")
    require(isinstance(ledger["findings"], list), "finding ledger findings must be an array")
    finding_ids: list[str] = []
    accepted_residual_ids: list[str] = []
    cutoff = datetime.strptime(cutoff_utc, "%Y-%m-%dT%H:%M:%SZ")
    expected_verification_reports = agent_review_references(review_bundle)
    review_artifact = response_value(review_bundle, "agent-reviews")
    latest_review_completion = max(
        datetime.strptime(review["completed_at"], "%Y-%m-%dT%H:%M:%SZ")
        for review in review_artifact["reviews"]
    )
    for index, value in enumerate(ledger["findings"]):
        finding = require_exact_object(
            value,
            (
                "id",
                "severity",
                "status",
                "owner",
                "scope",
                "reason",
                "mitigation",
                "rollback",
                "evidence",
                "valid_until",
                "invalidators",
                "disposition",
            ),
            f"finding ledger item[{index}]",
        )
        require(isinstance(finding["id"], str) and re.fullmatch(r"(?:GVN|REV)-P[0-2]-[0-9]{3}", finding["id"]) is not None, f"finding[{index}] id invalid")
        require(finding["severity"] in ("P0", "P1", "P2"), f"finding[{index}] severity invalid")
        require(finding["id"].split("-")[1] == finding["severity"], f"finding[{index}] id/severity mismatch")
        require(finding["status"] in ("Open", "Accepted-Residual", "Resolved", "Deferred-P2"), f"finding[{index}] status invalid")
        require(
            target_type != "ordinary" or finding["id"] not in ONE_TIME_RESIDUAL_IDS,
            f"ordinary evidence cannot carry one-time residual finding: {finding['id']}",
        )
        for field in ("owner", "scope", "reason", "mitigation", "rollback", "disposition"):
            require(isinstance(finding[field], str), f"finding[{index}].{field} must be a string")
        for field in ("owner", "scope", "reason", "mitigation", "rollback", "disposition"):
            require(finding[field].strip() == finding[field] and finding[field], f"finding[{index}].{field} must be non-empty and trimmed")
        if finding["id"] not in RESIDUAL_IDS:
            require(finding["scope"].startswith("repository-only: "), f"finding[{index}] scope must be explicitly repository-only")
            normalized_scope = finding["scope"].removeprefix("repository-only: ").casefold()
            forbidden_scope_terms = (
                "production",
                "prod",
                "secret",
                "credential",
                "credentials",
                "token",
                "tenant",
                "customer",
                "deploy",
                "release",
                "traffic",
                "external gate",
                "生产",
                "密钥",
                "凭据",
                "租户",
                "客户",
                "部署",
                "发布",
                "流量",
                "外部门",
            )
            require(not any(term in normalized_scope for term in forbidden_scope_terms), f"finding[{index}] scope crosses a forbidden authorization boundary")
        require_sorted_unique_strings(finding["invalidators"], f"finding[{index}].invalidators")
        if finding["status"] == "Open":
            require(finding["severity"] == "P2", f"open {finding['severity']} finding blocks governance")
            fail(f"open finding has no disposition: {finding['id']}")
        elif finding["status"] == "Accepted-Residual":
            require(finding["severity"] == "P1", "only P1 may be Accepted-Residual")
            require(finding["id"] in expected_residual_ids, f"evidence target cannot accept residual: {finding['id']}")
            require(finding["owner"] == "ZhangIvan", "Accepted-Residual owner must be ZhangIvan")
            require(finding["scope"] == RESIDUAL_SCOPES[finding["id"]], f"Accepted-Residual scope mismatch: {finding['id']}")
            require(finding["invalidators"], f"Accepted-Residual invalidators missing: {finding['id']}")
            require_utc_timestamp(finding["valid_until"], f"finding[{index}].valid_until")
            require(finding["valid_until"] == RESIDUAL_VALID_UNTIL, f"Accepted-Residual expiry drifted: {finding['id']}")
            require(cutoff < datetime.strptime(finding["valid_until"], "%Y-%m-%dT%H:%M:%SZ"), f"Accepted-Residual expired at snapshot cutoff: {finding['id']}")
            if finding["id"] == "GVN-P1-005":
                acceptance = require_exact_object(
                    finding["evidence"],
                    (
                        "schema",
                        "from_status",
                        "transition",
                        "finding_id",
                        "pr_number",
                        "base_sha",
                        "candidate_head",
                        "candidate_tree",
                        "target_type",
                        "accepted_at",
                        "accepted_by",
                        "accepted_by_id",
                        "decision",
                        "section_sha256",
                        "verification_reports",
                        "resolution_trigger",
                        "derived_status",
                        "owner_attestation_required",
                    ),
                    "Accepted-Residual evidence: GVN-P1-005",
                )
                require(acceptance["schema"] == "gvn-finding-acceptance-v2", "GVN-P1-005 acceptance schema mismatch")
                require(acceptance["finding_id"] == finding["id"], "GVN-P1-005 acceptance finding id mismatch")
                require(
                    (acceptance["pr_number"], acceptance["base_sha"], acceptance["candidate_head"], acceptance["candidate_tree"], acceptance["target_type"])
                    == (root["pr_number"], root["base_sha"], root["candidate_head"], root["candidate_tree"], target_type),
                    "GVN-P1-005 acceptance target binding mismatch",
                )
                require(
                    acceptance["resolution_trigger"] == "trusted-signed-time-or-validator-direct-fetch-or-trusted-collector",
                    "GVN-P1-005 resolution trigger mismatch",
                )
                derived_status = require_exact_object(
                    acceptance["derived_status"],
                    ("stable_window_integrity", "stable_window_freshness", "activation_authorization"),
                    "GVN-P1-005 derived status",
                )
                require(
                    derived_status
                    == {
                        "stable_window_integrity": "VERIFIED",
                        "stable_window_freshness": "UNVERIFIED",
                        "activation_authorization": "CONDITIONAL_ACCEPTED_RESIDUAL",
                    },
                    "GVN-P1-005 derived status mismatch",
                )
            else:
                acceptance = require_exact_object(
                    finding["evidence"],
                    (
                        "schema",
                        "from_status",
                        "transition",
                        "candidate_head",
                        "accepted_at",
                        "accepted_by",
                        "accepted_by_id",
                        "decision",
                        "section_sha256",
                        "verification_reports",
                        "owner_attestation_required",
                    ),
                    f"Accepted-Residual evidence: {finding['id']}",
                )
                require(acceptance["schema"] == "gvn-finding-acceptance-v1", f"Accepted-Residual schema mismatch: {finding['id']}")
            require(acceptance["from_status"] == "Open" and acceptance["transition"] == "Open->Accepted-Residual", f"Accepted-Residual transition invalid: {finding['id']}")
            require(acceptance["candidate_head"] == candidate_head, f"Accepted-Residual candidate mismatch: {finding['id']}")
            require_utc_timestamp(acceptance["accepted_at"], f"Accepted-Residual accepted_at: {finding['id']}")
            acceptance_time = datetime.strptime(acceptance["accepted_at"], "%Y-%m-%dT%H:%M:%SZ")
            require(latest_review_completion <= acceptance_time <= cutoff, f"Accepted-Residual transition is outside the fresh-review/cutoff interval: {finding['id']}")
            require(acceptance["accepted_by"] == "ZhangIvan", f"Accepted-Residual owner identity mismatch: {finding['id']}")
            require_positive_int(acceptance["accepted_by_id"], f"Accepted-Residual accepted_by_id: {finding['id']}")
            require(acceptance["accepted_by_id"] == OWNER_GITHUB_ID, f"Accepted-Residual owner identity mismatch: {finding['id']}")
            require(acceptance["decision"] == "DEC-20260829-001", f"Accepted-Residual decision mismatch: {finding['id']}")
            require(acceptance["section_sha256"] == RESIDUAL_SECTION_SHA256[finding["id"]], f"Accepted-Residual section digest mismatch: {finding['id']}")
            require(acceptance["verification_reports"] == expected_verification_reports, f"Accepted-Residual verifier reports differ from fresh Agent reviews: {finding['id']}")
            require(acceptance["owner_attestation_required"] is True, f"Accepted-Residual must remain pending exact owner attestation: {finding['id']}")
            accepted_residual_ids.append(finding["id"])
        elif finding["status"] == "Resolved":
            resolution = require_exact_object(
                finding["evidence"],
                ("schema", "from_status", "transition", "candidate_head", "resolved_at", "patch_sha256", "verification_reports"),
                f"Resolved finding evidence: {finding['id']}",
            )
            require(resolution["schema"] == "gvn-finding-resolution-v1", f"Resolved finding schema mismatch: {finding['id']}")
            require(resolution["from_status"] == "Open" and resolution["transition"] == "Open->Resolved", f"Resolved finding transition invalid: {finding['id']}")
            require(resolution["candidate_head"] == candidate_head, f"Resolved finding candidate mismatch: {finding['id']}")
            require_utc_timestamp(resolution["resolved_at"], f"Resolved finding resolved_at: {finding['id']}")
            resolution_time = datetime.strptime(resolution["resolved_at"], "%Y-%m-%dT%H:%M:%SZ")
            require(latest_review_completion <= resolution_time <= cutoff, f"Resolved transition is outside the fresh-review/cutoff interval: {finding['id']}")
            require_sha256(resolution["patch_sha256"], f"Resolved finding patch_sha256: {finding['id']}")
            require(isinstance(resolution["verification_reports"], list) and len(resolution["verification_reports"]) == 2, f"Resolved finding requires two fresh verifier reports: {finding['id']}")
            require(resolution["verification_reports"] == expected_verification_reports, f"Resolved finding verifier reports differ from fresh Agent reviews: {finding['id']}")
            require(finding["invalidators"], f"Resolved finding invalidators missing: {finding['id']}")
            require(finding["valid_until"] is None, f"Resolved finding valid_until must be null: {finding['id']}")
        else:
            require(finding["severity"] == "P2" and finding["disposition"], f"Deferred-P2 disposition invalid: {finding['id']}")
            require(finding["valid_until"] is None, f"Deferred-P2 valid_until must be null: {finding['id']}")
            deferral = require_exact_object(
                finding["evidence"],
                ("schema", "from_status", "transition", "candidate_head", "deferred_at", "deferred_by", "deferred_by_id", "disposition", "verification_reports"),
                f"Deferred-P2 evidence: {finding['id']}",
            )
            require(deferral["schema"] == "gvn-finding-deferral-v1", f"Deferred-P2 schema mismatch: {finding['id']}")
            require(deferral["from_status"] == "Open" and deferral["transition"] == "Open->Deferred-P2", f"Deferred-P2 transition invalid: {finding['id']}")
            require(deferral["candidate_head"] == candidate_head, f"Deferred-P2 candidate mismatch: {finding['id']}")
            require_utc_timestamp(deferral["deferred_at"], f"Deferred-P2 deferred_at: {finding['id']}")
            deferral_time = datetime.strptime(deferral["deferred_at"], "%Y-%m-%dT%H:%M:%SZ")
            require(latest_review_completion <= deferral_time <= cutoff, f"Deferred-P2 transition is outside the fresh-review/cutoff interval: {finding['id']}")
            require(deferral["deferred_by"] == "ZhangIvan", f"Deferred-P2 owner identity mismatch: {finding['id']}")
            require_positive_int(deferral["deferred_by_id"], f"Deferred-P2 deferred_by_id: {finding['id']}")
            require(deferral["deferred_by_id"] == OWNER_GITHUB_ID, f"Deferred-P2 owner identity mismatch: {finding['id']}")
            require(deferral["disposition"] == finding["disposition"], f"Deferred-P2 disposition evidence mismatch: {finding['id']}")
            require(deferral["verification_reports"] == expected_verification_reports, f"Deferred-P2 verifier reports differ from fresh Agent reviews: {finding['id']}")
        finding_ids.append(finding["id"])
    require(finding_ids == sorted(set(finding_ids), key=utf16_sort_key), "finding ledger ids must be unique and sorted")
    require(tuple(accepted_residual_ids) == expected_residual_ids, "accepted residual set does not match the evidence target")
    if attestation is not None:
        require(attestation["finding_ids"] == finding_ids, "attestation finding_ids differ from finding ledger")
        require(attestation["accepted_residual_ids"] == accepted_residual_ids, "attestation accepted_residual_ids differ from finding ledger")


def validate_evidence_package_v2(
    value: Any,
    current_context: CurrentPRContext | None = None,
    authorized_target_type: str | None = None,
) -> None:
    package = require_exact_object(
        value,
        (
            "schema",
            "phase",
            "pre_endpoint_bundles",
            "snapshot_endpoint_bundles",
            "pre_attestation",
            "attestation",
            "publication_delta",
            "manifest",
            "activation_binding",
        ),
        "evidence package",
    )
    require(package["schema"] == "gvn-evidence-package-v2", "evidence package schema mismatch")
    require(package["activation_binding"] is None or isinstance(package["activation_binding"], dict), "activation binding must be null or an object")
    require(package["phase"] in ("pre-attestation", "stable-window-start", "stable-window-end", "post-merge"), "evidence package phase invalid")
    if package["phase"] == "pre-attestation":
        expected_components = PRE_ATTESTATION_COMPONENTS
    elif package["phase"] == "post-merge":
        expected_components = POST_MERGE_COMPONENTS
    else:
        expected_components = STABLE_COMPONENTS

    _, pre_bundle_map, pre_digest_map = bundle_digest_map(
        package["pre_endpoint_bundles"], PRE_ATTESTATION_COMPONENTS, "pre-attestation",
    )

    validate_pre_attestation_v1(package["pre_attestation"])
    pre = package["pre_attestation"]
    target_type = derive_evidence_target_type(package, pre, authorized_target_type)
    if current_context is not None:
        require(
            (pre["base_sha"], pre["pr_number"], pre["candidate_head"], pre["candidate_tree"])
            == (current_context.base_sha, current_context.pr_number, current_context.candidate_head, current_context.candidate_tree),
            "pre-attestation identity differs from current CLI/event/local candidate context",
        )
    expected_pre_digests = [
        {"name": name, "endpoint_bundle_sha256": pre_digest_map[name]}
        for name in PRE_ATTESTATION_COMPONENTS
    ]
    require(pre["component_digests"] == expected_pre_digests, "pre-attestation component digests do not match embedded bundles")
    validate_package_request_bindings(pre_bundle_map, pre["pr_number"], pre["candidate_head"], pre["candidate_tree"], None)
    validate_package_response_semantics(pre_bundle_map, pre, pre["snapshot_cutoff_utc"], target_type)
    validate_finding_ledger(pre_bundle_map["finding"], pre_bundle_map["review"], pre["snapshot_cutoff_utc"], pre, None, target_type)

    if package["phase"] == "pre-attestation":
        require(package["snapshot_endpoint_bundles"] == [], "pre-attestation package snapshot bundles must be empty")
        require(package["attestation"] is None and package["publication_delta"] is None and package["manifest"] is None, "pre-attestation package cannot contain publication/manifest state")
        return

    _, snapshot_bundle_map, snapshot_digest_map = bundle_digest_map(
        package["snapshot_endpoint_bundles"], expected_components, "snapshot",
    )

    validate_attestation_v1(package["attestation"])
    attestation = package["attestation"]
    require(attestation["repository"] == pre["repository"], "attestation repository differs from pre-root")
    for field in ("pr_number", "base_sha", "candidate_head", "candidate_tree"):
        require(attestation[field] == pre[field], f"attestation {field} differs from pre-root")
    require(attestation["pre_attestation_sha256"] == hashlib.sha256(canonical_json_v1(pre)).hexdigest(), "attestation pre-root digest mismatch")
    require(attestation["changed_paths_sha256"] == pre_digest_map["paths"], "attestation paths digest mismatch")
    attested_pull = response_value(pre_bundle_map["pr"], "pull")
    require(
        attestation["pull_body_sha256"] == hashlib.sha256(attested_pull["body"].encode("utf-8")).hexdigest(),
        "attestation pull body digest mismatch",
    )

    owner = response_value(pre_bundle_map["identity"], "owner-identity")
    require(isinstance(owner, dict), "owner identity response must be an object")
    require(owner.get("login") == attestation["attestor_login"], "attestor does not match owner immutable identity")
    require_positive_int(owner.get("id"), "attestor owner id")
    require(owner["id"] == attestation["attestor_id"], "attestor does not match owner immutable identity")
    attestation_payload = response_value(snapshot_bundle_map["attestation"], "attestation-payload")
    require(attestation_payload == attestation, "attestation-payload artifact differs from package attestation")
    require(
        response_item(snapshot_bundle_map["attestation"], "attestation-payload")["request"]["body"] == attestation,
        "attestation-payload derived request input differs from package attestation",
    )
    comment = response_value(snapshot_bundle_map["attestation"], "attestation-comment")
    require(isinstance(comment, dict) and isinstance(comment.get("user"), dict), "attestation comment response shape invalid")
    require(comment["user"].get("login") == attestation["attestor_login"], "attestation comment author identity mismatch")
    require_positive_int(comment["user"].get("id"), "attestation comment author id")
    require(comment["user"]["id"] == attestation["attestor_id"], "attestation comment author identity mismatch")
    require(comment.get("body") == canonical_json_v1(attestation).decode("utf-8"), "attestation comment body differs from canonical payload")

    validate_manifest_v1(package["manifest"])
    manifest = package["manifest"]
    require(manifest["phase"] == package["phase"], "manifest/package phase mismatch")
    for field in ("repository", "pr_number", "base_sha", "candidate_head", "candidate_tree"):
        require(manifest[field] == pre[field], f"manifest {field} differs from pre-root")
    expected_manifest_digests = [
        {"name": name, "endpoint_bundle_sha256": snapshot_digest_map[name]}
        for name in expected_components
    ]
    require(manifest["component_digests"] == expected_manifest_digests, "manifest component digests do not match embedded bundles")
    validate_package_request_bindings(
        snapshot_bundle_map,
        pre["pr_number"],
        pre["candidate_head"],
        pre["candidate_tree"],
        manifest["effective_merge_sha"],
    )
    validate_package_response_semantics(snapshot_bundle_map, pre, manifest["snapshot_cutoff_utc"], target_type)
    if package["phase"] == "post-merge":
        validate_merge_response_semantics(
            snapshot_bundle_map["merge"],
            pre,
            manifest["effective_merge_sha"],
            attestation["attestor_id"],
            [item["filename"] for item in response_value(snapshot_bundle_map["paths"], "pull-files")],
            manifest["snapshot_cutoff_utc"],
        )
    require(
        datetime.strptime(manifest["snapshot_cutoff_utc"], "%Y-%m-%dT%H:%M:%SZ")
        > datetime.strptime(pre["snapshot_cutoff_utc"], "%Y-%m-%dT%H:%M:%SZ"),
        "stable/post-merge snapshot cutoff must be later than pre-attestation cutoff",
    )
    validate_finding_ledger(snapshot_bundle_map["finding"], snapshot_bundle_map["review"], manifest["snapshot_cutoff_utc"], pre, attestation, target_type)
    validate_publication_delta_v1(
        package["publication_delta"],
        pre_bundle_map,
        snapshot_bundle_map,
        attestation,
        pre["snapshot_cutoff_utc"],
        manifest["snapshot_cutoff_utc"],
    )


def validate_evidence_sequence(
    packages: list[dict[str, Any]],
    current_context: CurrentPRContext | None = None,
    require_merge_ready: bool = False,
    authorized_target_type: str | None = None,
) -> None:
    require(packages, "evidence sequence cannot be empty")
    for package in packages:
        validate_evidence_package_v2(package, current_context, authorized_target_type)
    require(
        all(canonical_json_v1(package["activation_binding"]) == canonical_json_v1(packages[0]["activation_binding"]) for package in packages),
        "activation binding changed across the evidence sequence",
    )
    phases = tuple(package["phase"] for package in packages)
    if require_merge_ready:
        require(current_context is not None, "--require-merge-ready requires complete current PR context")
        require(phases == ("stable-window-start", "stable-window-end"), "merge-ready evidence requires exactly stable-window-start/stable-window-end")
        merge_ready_target = derive_evidence_target_type(packages[0], packages[0]["pre_attestation"], authorized_target_type)
        require_merge_ready_freshness(merge_ready_target)
        require(
            all(package["attestation"] is not None and package["publication_delta"] is not None and package["manifest"] is not None for package in packages),
            "merge-ready evidence requires complete attestation/publication/manifest state",
        )
    if phases == ("pre-attestation",):
        return
    require(phases in (("stable-window-start", "stable-window-end"), ("stable-window-start", "stable-window-end", "post-merge")), f"invalid evidence phase sequence: {phases}")
    start, end = packages[:2]
    for field in ("pre_endpoint_bundles", "pre_attestation", "attestation", "publication_delta"):
        require(canonical_json_v1(start[field]) == canonical_json_v1(end[field]), f"stable window {field} changed")
    require(canonical_json_v1(start["snapshot_endpoint_bundles"]) == canonical_json_v1(end["snapshot_endpoint_bundles"]), "stable window component bundles changed")
    require(start["manifest"]["component_digests"] == end["manifest"]["component_digests"], "stable window manifest components changed")
    start_time = datetime.strptime(start["manifest"]["snapshot_cutoff_utc"], "%Y-%m-%dT%H:%M:%SZ")
    end_time = datetime.strptime(end["manifest"]["snapshot_cutoff_utc"], "%Y-%m-%dT%H:%M:%SZ")
    require((end_time - start_time).total_seconds() >= 600, "stable window must be at least 600 seconds")
    if len(packages) == 2:
        return
    post = packages[2]
    for field in ("pre_endpoint_bundles", "pre_attestation", "attestation", "publication_delta"):
        require(canonical_json_v1(end[field]) == canonical_json_v1(post[field]), f"post-merge {field} differs from stable-window-end")
    stable_count = len(STABLE_COMPONENTS)
    require(
        canonical_json_v1(post["snapshot_endpoint_bundles"][:stable_count])
        == canonical_json_v1(end["snapshot_endpoint_bundles"]),
        "post-merge common bundles differ from stable-window-end",
    )
    require(
        post["manifest"]["component_digests"][:stable_count] == end["manifest"]["component_digests"],
        "post-merge common manifest digests differ from stable-window-end",
    )
    post_time = datetime.strptime(post["manifest"]["snapshot_cutoff_utc"], "%Y-%m-%dT%H:%M:%SZ")
    require(post_time > end_time, "post-merge cutoff must be later than stable-window-end")
    merge_bundle = post["snapshot_endpoint_bundles"][-1]
    require(isinstance(merge_bundle, dict) and merge_bundle.get("component") == "merge", "post-merge sequence is missing its merge bundle")
    merged_pull = response_value(merge_bundle, "merged-pull")
    merged_at = datetime.strptime(merged_pull["merged_at"], "%Y-%m-%dT%H:%M:%SZ")
    require(end_time < merged_at <= post_time, "merge timestamp must be after the stable window and no later than the post snapshot")


def validate_activation_evidence_binding(
    packages: list[dict[str, Any]],
    governance_state: dict[str, str | int],
    current_pr_number: int,
    expected_governance_base: str,
) -> None:
    require(packages, "activation evidence sequence cannot be empty")
    binding = packages[0]["activation_binding"]
    is_activation = governance_state["status"] == "ACTIVE" and current_pr_number == governance_state["activation_pr"]
    if not is_activation:
        require(binding is None, "non-activation evidence must not carry an activation binding")
        return
    require(
        tuple(package.get("phase") for package in packages) == ("stable-window-start", "stable-window-end"),
        "activation evidence requires exactly stable-window-start/stable-window-end",
    )
    binding = require_exact_object(
        binding,
        ("schema", "activation_evidence_pr", "activation_candidate_head", "activation_candidate_tree", "governance_evidence_sequence"),
        "activation evidence binding",
    )
    require(binding["schema"] == "gvn-activation-binding-v1", "activation evidence binding schema mismatch")
    current_pre = packages[0]["pre_attestation"]
    require(binding["activation_evidence_pr"] == current_pr_number == current_pre["pr_number"], "activation evidence PR binding mismatch")
    require(binding["activation_candidate_head"] == current_pre["candidate_head"], "activation candidate head binding mismatch")
    require(binding["activation_candidate_tree"] == current_pre["candidate_tree"], "activation candidate tree binding mismatch")
    governance_packages = binding["governance_evidence_sequence"]
    require(isinstance(governance_packages, list) and len(governance_packages) == 3, "activation binding requires the complete governance start/end/post sequence")
    require(all(package.get("activation_binding") is None for package in governance_packages if isinstance(package, dict)), "nested governance evidence cannot recursively carry activation state")
    validate_evidence_sequence(governance_packages)
    require(tuple(package["phase"] for package in governance_packages) == ("stable-window-start", "stable-window-end", "post-merge"), "nested governance evidence phases mismatch")
    governance_pre = governance_packages[0]["pre_attestation"]
    governance_post = governance_packages[-1]
    governance_manifest = governance_post["manifest"]
    governance_attestation = governance_post["attestation"]
    require(governance_pre["pr_number"] == EXPECTED_GOVERNANCE_PR and governance_pre["base_sha"] == expected_governance_base, "nested governance evidence does not describe PR #19 from the frozen source base")
    require(governance_pre["candidate_head"] == governance_state["candidate_head"], "nested governance candidate head differs from ACTIVE DEC")
    require(governance_pre["candidate_tree"] == governance_state["merge_tree"], "nested governance candidate tree differs from ACTIVE DEC")
    require(governance_manifest["effective_merge_sha"] == governance_state["effective_commit"] == governance_state["merge_commit"], "nested governance merge SHA differs from ACTIVE DEC")
    merge_bundle = governance_post["snapshot_endpoint_bundles"][-1]
    merge_commit = response_value(merge_bundle, "merge-commit")
    require(merge_commit.get("parents") == [governance_state["merge_parent"]], "nested governance merge parent differs from ACTIVE DEC")
    require(hashlib.sha256(canonical_json_v1(governance_manifest)).hexdigest() == governance_state["governance_postmerge_manifest_sha"], "nested governance post-merge manifest digest differs from ACTIVE DEC")
    require(hashlib.sha256(canonical_json_v1(governance_attestation)).hexdigest() == governance_state["governance_attestation_sha"], "nested governance attestation digest differs from ACTIVE DEC")


def scan_secret_bytes(data: bytes) -> bool:
    """Return whether raw bytes contain any forbidden evidence-secret pattern."""

    require(isinstance(data, bytes), "evidence secret scan input must be bytes")
    return any(pattern.search(data) is not None for pattern in EVIDENCE_SECRET_PATTERNS)


def require_no_evidence_secret(data: bytes, label: str) -> None:
    require(not scan_secret_bytes(data), f"secret/privacy pattern detected in {label}")


def scan_python_literal_secrets(source_text: str, label: str) -> None:
    try:
        token_count = 0
        for _token in tokenize.generate_tokens(io.StringIO(source_text).readline):
            token_count += 1
            require(token_count <= MAX_VALIDATOR_SOURCE_TOKENS, f"validator source token count exceeds limit: {label}")
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        fail(f"validator source tokenization failed: {exc}")
    try:
        syntax_tree = ast.parse(source_text, filename=label)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        fail(f"validator source is not parseable Python: {exc}")
    for node_index, node in enumerate(ast.walk(syntax_tree)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            continue
        literal_bytes = node.value.encode("utf-8") if isinstance(node.value, str) else node.value
        require_no_evidence_secret(literal_bytes, f"{label} decoded literal[{node_index}]")
        if (
            20 <= len(literal_bytes) <= MAX_VALIDATOR_SOURCE_BYTES
            and len(literal_bytes) % 4 == 0
            and re.fullmatch(rb"[0-9A-Za-z+/_-]+={0,2}", literal_bytes) is not None
        ):
            try:
                decoded_literal = base64.b64decode(literal_bytes, altchars=b"-_", validate=True)
            except (binascii.Error, ValueError):
                continue
            require_no_evidence_secret(decoded_literal, f"{label} base64 literal[{node_index}]")


def preflight_zip_archive(data: bytes, label: str) -> None:
    """Bound ZIP central-directory parsing before constructing ZipFile objects.

    ZIP64 evidence is intentionally unsupported: the governance evidence format
    does not require it, and accepting it would require a separate bounded
    ZIP64 locator/EOCD parser before ZipFile can be safely constructed.
    """

    require(isinstance(data, bytes), f"evidence ZIP must be bytes: {label}")
    require(len(data) >= ZIP_EOCD_SIZE, f"evidence ZIP is shorter than EOCD: {label}")
    eocd_signature = b"PK\x05\x06"
    search_start = max(0, len(data) - MAX_ZIP_EOCD_SEARCH_BYTES)
    candidates: list[int] = []
    offset = data.find(eocd_signature, search_start)
    while offset != -1:
        if offset + ZIP_EOCD_SIZE <= len(data):
            comment_length = int.from_bytes(data[offset + 20 : offset + 22], "little")
            if offset + ZIP_EOCD_SIZE + comment_length == len(data):
                candidates.append(offset)
        offset = data.find(eocd_signature, offset + 1)
    require(len(candidates) == 1, f"evidence ZIP must have one EOF-terminated EOCD: {label}")
    eocd_offset = candidates[0]
    (
        _signature,
        disk_number,
        central_directory_disk,
        entries_on_disk,
        total_entries,
        central_directory_size,
        central_directory_offset,
        comment_length,
    ) = struct.unpack_from("<4s4H2LH", data, eocd_offset)
    require(
        eocd_offset + ZIP_EOCD_SIZE + comment_length == len(data),
        f"evidence ZIP EOCD comment does not end at EOF: {label}",
    )
    require(
        disk_number == 0 and central_directory_disk == 0 and entries_on_disk == total_entries,
        f"multi-disk evidence ZIP is forbidden: {label}",
    )
    if (
        entries_on_disk == 0xFFFF
        or total_entries == 0xFFFF
        or central_directory_size == 0xFFFFFFFF
        or central_directory_offset == 0xFFFFFFFF
    ):
        fail(f"ZIP64 evidence archives are forbidden: {label}")
    require(total_entries <= 1000, f"evidence ZIP has too many members: {label}")
    require(
        central_directory_offset + central_directory_size == eocd_offset,
        f"evidence ZIP central directory does not end at EOCD: {label}",
    )
    central_offset = central_directory_offset
    parsed_entries = 0
    while central_offset < eocd_offset:
        require(parsed_entries < 1000, f"evidence ZIP has too many actual central-directory members: {label}")
        require(
            central_offset + ZIP_CENTRAL_DIRECTORY_HEADER_SIZE <= eocd_offset
            and data[central_offset : central_offset + 4] == b"PK\x01\x02",
            f"invalid evidence ZIP central-directory header: {label}",
        )
        filename_length = int.from_bytes(data[central_offset + 28 : central_offset + 30], "little")
        extra_length = int.from_bytes(data[central_offset + 30 : central_offset + 32], "little")
        member_comment_length = int.from_bytes(data[central_offset + 32 : central_offset + 34], "little")
        central_offset += ZIP_CENTRAL_DIRECTORY_HEADER_SIZE + filename_length + extra_length + member_comment_length
        require(central_offset <= eocd_offset, f"evidence ZIP central-directory entry exceeds bounds: {label}")
        parsed_entries += 1
    require(
        central_offset == eocd_offset and parsed_entries == total_entries,
        f"evidence ZIP central-directory count/size mismatch: {label}",
    )


def scan_evidence_payload(
    decoded: bytes,
    media_type: Any,
    label: str,
    archive_depth: int = 0,
) -> None:
    require(isinstance(decoded, bytes), f"evidence payload must be bytes: {label}")
    require_no_evidence_secret(decoded, f"evidence response: {label}")
    if media_type == "application/json":
        response_text = validate_utf8_bytes(decoded, f"{label} JSON body")
        response_value_item = parse_json_strict(response_text)
        require_no_evidence_secret(
            canonical_json_v1(response_value_item),
            f"evidence response canonical JSON: {label}",
        )
        return
    if media_type != "application/zip":
        return

    require(archive_depth < MAX_EVIDENCE_ARCHIVE_DEPTH, f"evidence ZIP nesting exceeds limit: {label}")
    preflight_zip_archive(decoded, label)
    try:
        with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
            members = archive.infolist()
            require_no_evidence_secret(archive.comment, f"evidence ZIP comment: {label}")
            require(len(members) <= 1000, f"evidence ZIP has too many members: {label}")
            require(sum(member.file_size for member in members) <= MAX_EVIDENCE_BYTES, f"evidence ZIP expands beyond limit: {label}")
            expanded_bytes = 0
            for member in members:
                member_label = f"{label}/{member.filename}"
                require(member.flag_bits & 0x1 == 0, f"encrypted evidence ZIP member forbidden: {label}")
                metadata_bytes = member.filename.encode("utf-8", errors="strict") + b"\x00" + member.comment + b"\x00" + member.extra
                require_no_evidence_secret(metadata_bytes, f"evidence ZIP metadata: {label}")
                require(
                    unicodedata.normalize("NFC", member.filename) == member.filename and "\x00" not in member.filename,
                    f"invalid evidence ZIP member name: {label}",
                )
                if member.is_dir():
                    continue
                member_chunks: list[bytes] = []
                with archive.open(member) as member_stream:
                    while True:
                        chunk = member_stream.read(64 * 1024)
                        if not chunk:
                            break
                        expanded_bytes += len(chunk)
                        require(expanded_bytes <= MAX_EVIDENCE_BYTES, f"evidence ZIP actual expansion exceeds limit: {label}")
                        member_chunks.append(chunk)
                member_bytes = b"".join(member_chunks)
                require_no_evidence_secret(member_bytes, f"evidence ZIP member: {member_label}")
                nested_zip = zipfile.is_zipfile(io.BytesIO(member_bytes)) or member_bytes.startswith(
                    (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
                )
                if nested_zip:
                    scan_evidence_payload(member_bytes, "application/zip", member_label, archive_depth + 1)
    except (
        zipfile.BadZipFile,
        RuntimeError,
        OSError,
        NotImplementedError,
        UnicodeError,
        zlib.error,
        EOFError,
        ValueError,
    ) as exc:
        fail(f"invalid evidence ZIP response: {label}: {exc}")


def scan_evidence_secrets(package: dict[str, Any], package_depth: int = 0) -> None:
    require(isinstance(package, dict), "evidence package must be an object before evidence scan")
    require(package_depth < MAX_EVIDENCE_PACKAGE_DEPTH, "evidence package nesting exceeds limit")
    require_no_evidence_secret(canonical_json_v1(package), "evidence package metadata/request")
    for collection_name in ("pre_endpoint_bundles", "snapshot_endpoint_bundles"):
        bundles = package.get(collection_name)
        require(isinstance(bundles, list), f"{collection_name} must be an array before evidence scan")
        for bundle_index, bundle in enumerate(bundles):
            require(isinstance(bundle, dict) and isinstance(bundle.get("responses"), list), f"invalid evidence bundle before scan: {collection_name}[{bundle_index}]")
            for response_index, response in enumerate(bundle["responses"]):
                require(isinstance(response, dict) and isinstance(response.get("response_body_base64"), str), f"invalid response before evidence scan: {collection_name}[{bundle_index}][{response_index}]")
                try:
                    decoded = base64.b64decode(response["response_body_base64"], validate=True)
                except (binascii.Error, ValueError) as exc:
                    fail(f"invalid base64 before evidence scan: {collection_name}[{bundle_index}][{response_index}]: {exc}")
                scan_evidence_payload(
                    decoded,
                    response.get("response_media_type"),
                    f"{collection_name}[{bundle_index}][{response_index}]",
                )

    activation_binding = package.get("activation_binding")
    if activation_binding is None:
        return
    require(isinstance(activation_binding, dict), "activation binding must be an object before evidence scan")
    nested_packages = activation_binding.get("governance_evidence_sequence")
    if nested_packages is None:
        return
    require(isinstance(nested_packages, list), "nested governance evidence sequence must be an array before evidence scan")
    for nested_index, nested_package in enumerate(nested_packages):
        require(isinstance(nested_package, dict), f"invalid nested governance evidence package: {nested_index}")
        scan_evidence_secrets(nested_package, package_depth + 1)


def read_evidence_package_file(path: Path) -> dict[str, Any]:
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    evidence_directory = temp_root / EVIDENCE_DIRECTORY_NAME
    require(path.is_absolute(), f"evidence path must be absolute: {path}")
    require(path.parent == evidence_directory and path.name not in ("", ".", ".."), f"evidence file must be directly under {evidence_directory}: {path}")
    directory_descriptor = os.open(evidence_directory, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        directory_metadata = os.fstat(directory_descriptor)
        require(stat.S_ISDIR(directory_metadata.st_mode), f"evidence directory must be a directory: {evidence_directory}")
        require(stat.S_IMODE(directory_metadata.st_mode) == 0o700, f"evidence directory mode must be exactly 0700: {evidence_directory}")
        require(directory_metadata.st_uid == os.getuid(), f"evidence directory must be owned by the current user: {evidence_directory}")
        descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_descriptor)
    finally:
        os.close(directory_descriptor)
    try:
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), f"evidence path must be a regular file: {path}")
        require(stat.S_IMODE(metadata.st_mode) == 0o600, f"evidence file mode must be exactly 0600: {path}")
        require(metadata.st_uid == os.getuid(), f"evidence file must be owned by the current user: {path}")
        require(metadata.st_nlink == 1, f"evidence file must not be hard-linked: {path}")
        require(metadata.st_size <= MAX_EVIDENCE_BYTES, f"evidence file exceeds {MAX_EVIDENCE_BYTES} bytes: {path}")
        evidence_chunks: list[bytes] = []
        evidence_size = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            evidence_size += len(chunk)
            require(evidence_size <= MAX_EVIDENCE_BYTES, f"evidence file grew beyond {MAX_EVIDENCE_BYTES} bytes while reading: {path}")
            evidence_chunks.append(chunk)
        evidence_bytes = b"".join(evidence_chunks)
    finally:
        os.close(descriptor)
    evidence_text = validate_utf8_bytes(evidence_bytes, str(path))
    evidence_value = parse_json_strict(evidence_text)
    require(isinstance(evidence_value, dict) and evidence_value.get("schema") == "gvn-evidence-package-v2", "--evidence-json requires a unified gvn-evidence-package-v2")
    scan_evidence_secrets(evidence_value)
    return evidence_value


def validate_evidence_object(value: Any) -> None:
    canonical_json_v1(value)
    require(isinstance(value, dict), "evidence document must be an object")
    schema = value.get("schema")
    validators = {
        "gvn-request-v1": validate_request_v1,
        "gvn-endpoint-bundle-v3": validate_endpoint_bundle_v3,
        "gvn-pre-attestation-v1": validate_pre_attestation_v1,
        "gvn-attestation-v1": validate_attestation_v1,
        "gvn-manifest-v1": validate_manifest_v1,
        "gvn-evidence-package-v2": validate_evidence_package_v2,
    }
    require(schema in validators, f"unknown evidence schema: {schema!r}")
    validators[str(schema)](value)


def expect_failure(action: Any, label: str) -> None:
    try:
        action()
    except (GovernanceValidationError, UnicodeDecodeError, json.JSONDecodeError):
        return
    fail(f"self-test expected failure: {label}")


def expect_failure_message(action: Any, expected_message: str, label: str) -> None:
    try:
        action()
    except GovernanceValidationError as exc:
        require(expected_message in str(exc), f"self-test failure reason mismatch for {label}: {exc}")
        return
    fail(f"self-test expected failure: {label}")


def _run_self_tests(dec: str, plan: str, index: str, exercise_active_input: bool = True) -> None:
    initial_state = parse_triplet(dec, plan, index)
    if initial_state["status"] == "ACTIVE":
        original_label = str(initial_state["label"])
        dec = dec.replace("- 状态：`ACTIVE`", "- 状态：`PROPOSED`", 1)
        dec = dec.replace("- 生效状态：`ACTIVE`", "- 生效状态：`PENDING`", 1)
        dec = dec.replace(f"- `effective_commit`：`{initial_state['effective_commit']}`", "- `effective_commit`：`PENDING`", 1)
        dec = dec.replace(f"- `governance_candidate_head`：`{initial_state['candidate_head']}`", "- `governance_candidate_head`：`PENDING`", 1)
        dec = dec.replace(f"- `governance_merge_commit`：`{initial_state['merge_commit']}`", "- `governance_merge_commit`：`PENDING`", 1)
        dec = dec.replace(f"- `governance_merge_tree`：`{initial_state['merge_tree']}`", "- `governance_merge_tree`：`PENDING`", 1)
        dec = dec.replace(f"- `governance_merge_parent`：`{initial_state['merge_parent']}`", "- `governance_merge_parent`：`PENDING`", 1)
        dec = dec.replace(
            f"- `governance_postmerge_manifest_sha256`：`{initial_state['governance_postmerge_manifest_sha']}`",
            "- `governance_postmerge_manifest_sha256`：`PENDING`",
            1,
        )
        dec = dec.replace(
            f"- `governance_attestation_sha256`：`{initial_state['governance_attestation_sha']}`",
            "- `governance_attestation_sha256`：`PENDING`",
            1,
        )
        dec = dec.replace(f"- `activation_evidence_pr`：`#{initial_state['activation_pr']}`", "- `activation_evidence_pr`：`PENDING`", 1)
        plan = plan.replace(original_label, "PROPOSED / effective=PENDING", 1)
        index = index.replace(original_label, "PROPOSED / effective=PENDING", 1)
    draft_state = parse_triplet(dec, plan, index)
    numeric_order_fixture = [{"id": 2}, {"id": 10}]
    numeric_key = lambda item, item_index: (
        stable_integer_component(item.get("id") if isinstance(item, dict) else None, f"numeric-order[{item_index}].id"),
    )
    require_stable_array_order(numeric_order_fixture, "numeric-order", numeric_key)
    provider_order_fixture = list(reversed(numeric_order_fixture))
    provider_order_snapshot = json.loads(json.dumps(provider_order_fixture))
    require(
        derive_stable_array_view(provider_order_fixture, "provider-order", numeric_key) == numeric_order_fixture,
        "provider-order stable semantic view mismatch",
    )
    require(provider_order_fixture == provider_order_snapshot, "provider-order derivation mutated the raw array")
    expect_failure_message(
        lambda: require_stable_array_order(list(reversed(numeric_order_fixture)), "numeric-order", numeric_key),
        "numeric-order must be in stable canonical order",
        "numeric stable ordering is not lexical",
    )
    expect_failure_message(
        lambda: require_stable_array_order([{"id": 2}, {"id": 2, "extra": "different"}], "numeric-order", numeric_key),
        "numeric-order contains a duplicate stable unique key",
        "stable order duplicate immutable id",
    )
    expect_failure_message(
        lambda: require_stable_array_order([{"id": True}], "numeric-order", numeric_key),
        "numeric-order[0].id must be an integer",
        "stable order rejects boolean integer",
    )
    utf16_order_fixture = [{"id": "\U00010000"}, {"id": "\ue000"}]
    utf16_key = lambda item, item_index: (
        stable_string_component(item.get("id") if isinstance(item, dict) else None, f"utf16-order[{item_index}].id"),
    )
    require_stable_array_order(utf16_order_fixture, "utf16-order", utf16_key)
    expect_failure_message(
        lambda: require_stable_array_order(list(reversed(utf16_order_fixture)), "utf16-order", utf16_key),
        "utf16-order must be in stable canonical order",
        "UTF-16 ordering differs from Unicode code point order",
    )
    require_main_base("main", "self-test")
    expect_failure(lambda: require_main_base(None, "self-test"), "missing main base")
    expect_failure(lambda: require_main_base("release", "self-test"), "non-main base")
    expect_failure(
        lambda: parse_triplet(
            dec.replace("governance_postmerge_manifest_sha256", "activation_manifest_sha256"),
            plan,
            index,
        ),
        "legacy manifest pointer",
    )
    duplicate_status = dec.replace("- 状态：`PROPOSED`", "- 状态：`PROPOSED`\n- 状态：`PROPOSED`", 1)
    expect_failure(lambda: parse_triplet(duplicate_status, plan, index), "duplicate DEC header field")
    oversized_governance_dec = dec.replace(
        "- `governance_pr`：`#19`",
        f"- `governance_pr`：`#{SAFE_INTEGER_LIMIT + 1}`",
    )
    expect_failure_message(
        lambda: parse_triplet(oversized_governance_dec, plan, index),
        "governance_pr must be a positive safe integer",
        "oversized governance PR",
    )
    forged_expiry = dec.replace(
        "- `valid_until`：`2026-09-29T00:00:00Z`。",
        "- `valid_until`：`2099-01-01T00:00:00Z`。",
        1,
    ) + "\n- `valid_until`：`2026-09-29T00:00:00Z`。\n"
    expect_failure(lambda: validate_source_binding(forged_expiry), "forged residual expiry plus duplicate")
    validate_first_parent_lineage_untouched("HEAD", "HEAD")
    expect_failure(
        lambda: validate_first_parent_lineage_untouched(REAL_SOURCE_COMMIT, "HEAD"),
        "restorable governance-path history touch",
    )
    expect_failure(lambda: parse_triplet(dec, plan.replace("PROPOSED / effective=PENDING", "ACTIVE / effective=0"), index), "plan drift")
    expect_failure(lambda: parse_triplet(dec, plan, index.replace("PROPOSED / effective=PENDING", "ACTIVE / effective=0")), "index drift")
    expect_failure(lambda: validate_utf8_bytes(b"\xef\xbb\xbftext", "bom"), "BOM")
    expect_failure(lambda: validate_utf8_bytes(b"a\r\n", "crlf"), "CRLF")
    expect_failure(lambda: validate_utf8_bytes("e\u0301".encode(), "nfd"), "NFD")
    expect_failure(lambda: parse_json_strict('{"a":1,"a":2}'), "duplicate key")
    expect_failure(lambda: parse_json_strict('{"é":1,"e\\u0301":2}'), "NFC key collision")
    expect_failure(lambda: parse_json_strict('{"value":-0}'), "negative zero")
    require(
        parse_json_strict(f'{{"value":{SAFE_INTEGER_LIMIT}}}') == {"value": SAFE_INTEGER_LIMIT},
        "maximum safe JSON integer parse failed",
    )
    require(
        parse_json_strict(f'{{"value":{-SAFE_INTEGER_LIMIT}}}') == {"value": -SAFE_INTEGER_LIMIT},
        "minimum safe JSON integer parse failed",
    )
    for oversized_token, oversized_label in (
        (str(SAFE_INTEGER_LIMIT + 1), "JSON integer above safe limit"),
        (str(-(SAFE_INTEGER_LIMIT + 1)), "JSON integer below safe limit"),
        ("9" * 5000, "5000-digit positive JSON integer"),
        ("-" + "9" * 5000, "5000-digit negative JSON integer"),
    ):
        expect_failure_message(
            lambda token=oversized_token: parse_json_strict('{"value":' + token + "}"),
            "integer outside IEEE-754 safe range",
            oversized_label,
        )
    expect_failure_message(
        lambda: parse_json_strict('{"nested":[{"value":' + "9" * 5000 + "}]}"),
        "integer outside IEEE-754 safe range",
        "nested 5000-digit JSON integer",
    )
    expect_failure(lambda: canonical_json_v1({"value": 1.0}), "float")
    canonical = canonical_json_v1({"b": 1, "a": "é", "x": [True, None]})
    require(canonical == '{"a":"é","b":1,"x":[true,null]}'.encode(), f"unexpected canonical JSON: {canonical!r}")
    require_positive_int(1, "self-test positive integer")
    require_nonnegative_int(0, "self-test non-negative integer")
    require_positive_int(SAFE_INTEGER_LIMIT, "self-test safe positive integer")
    require_nonnegative_int(SAFE_INTEGER_LIMIT, "self-test safe non-negative integer")
    expect_failure_message(
        lambda: require_positive_int(True, "self-test positive integer"),
        "self-test positive integer must be an integer",
        "boolean positive integer",
    )
    expect_failure_message(
        lambda: require_positive_int(0, "self-test positive integer"),
        "self-test positive integer must be a positive safe integer",
        "zero positive integer",
    )
    expect_failure_message(
        lambda: require_positive_int(SAFE_INTEGER_LIMIT + 1, "self-test positive integer"),
        "self-test positive integer must be a positive safe integer",
        "oversized positive integer",
    )
    expect_failure_message(
        lambda: require_nonnegative_int(False, "self-test non-negative integer"),
        "self-test non-negative integer must be an integer",
        "boolean non-negative integer",
    )
    expect_failure_message(
        lambda: require_nonnegative_int(-1, "self-test non-negative integer"),
        "self-test non-negative integer must be a non-negative safe integer",
        "negative non-negative integer",
    )
    expect_failure_message(
        lambda: require_nonnegative_int(SAFE_INTEGER_LIMIT + 1, "self-test non-negative integer"),
        "self-test non-negative integer must be a non-negative safe integer",
        "oversized non-negative integer",
    )
    require(parse_positive_decimal(str(SAFE_INTEGER_LIMIT), "self-test decimal integer") == SAFE_INTEGER_LIMIT, "safe decimal integer parse failed")
    expect_failure_message(
        lambda: parse_positive_decimal(str(SAFE_INTEGER_LIMIT + 1), "self-test decimal integer"),
        "self-test decimal integer must be a positive safe integer",
        "oversized decimal integer",
    )
    expect_failure_message(
        lambda: parse_positive_decimal("9" * 5000, "self-test decimal integer"),
        "self-test decimal integer must be a positive safe integer",
        "unbounded decimal integer",
    )

    def sample_request(label: str) -> dict[str, Any]:
        source, method, _ = LABEL_REQUEST_RULES[label]
        authority = {
            "github-api": "api.github.com",
            "git": "ZhangIvan/QingYin",
            "agent": "codex-orchestrator",
            "derived": "local",
        }[source]
        if label in ("pull-metadata", "review-threads", "post-merge-metadata"):
            body: dict[str, Any] | None = {
                "query": PULL_METADATA_QUERY if label in ("pull-metadata", "post-merge-metadata") else REVIEW_THREADS_QUERY,
                "variables": {"name": "QingYin", "number": 19, "owner": "ZhangIvan"},
            }
        else:
            body = {"label": label} if method in ("POST", "PUT", "DERIVE") else None
        return {
            "schema": "gvn-request-v1",
            "source": source,
            "method": method,
            "authority": authority,
            "path": SAMPLE_REQUEST_PATHS[label],
            "query": (
                [["recursive", "1"]]
                if label == "candidate-tree"
                else [["event", "pull_request"], ["head_sha", "b" * 40], ["page", "1"], ["per_page", "100"]]
                if label == "workflow-runs"
                else [["page", "1"], ["per_page", "100"]]
                if label in (*PAGINATED_ARRAY_LABELS, *PAGINATED_OBJECT_LABELS)
                else []
            ),
            "body": body,
        }

    def sample_response(label: str, value: Any) -> dict[str, Any]:
        request = sample_request(label)
        request_sha = hashlib.sha256(canonical_json_v1(request)).hexdigest()
        response_body = canonical_json_v1(value).decode("utf-8")
        response_sha = hashlib.sha256(response_body.encode()).hexdigest()
        return {
            "label": label,
            "request": request,
            "request_canonical_sha256": request_sha,
            "response_status": 200,
            "response_media_type": "application/json",
            "response_body_base64": base64.b64encode(response_body.encode()).decode("ascii"),
            "response_body_sha256": response_sha,
            "response_canonical_sha256": response_sha,
            "human_body_hashes": derive_human_body_hashes(label, value),
        }

    def sample_bundle(component: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        overrides = values or {}
        def default_value(label: str) -> Any:
            if label == "pull":
                return {"id": 1, "body": None}
            if label in ("pull-metadata", "post-merge-metadata"):
                return {"data": {"repository": {"pullRequest": {"id": "PR_kwDODefault", "body": None}}}}
            if label == "review-threads":
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
            if label == "attestation-comment":
                return {"id": 1, "body": None}
            if label in PAGINATED_ARRAY_LABELS:
                return []
            if label in PAGINATED_OBJECT_LABELS:
                return {PAGINATED_OBJECT_LABELS[label]: [], "total_count": 0}
            return {"component": component, "label": label}
        return {
            "schema": "gvn-endpoint-bundle-v3",
            "component": component,
            "responses": [
                sample_response(label, overrides.get(label, default_value(label)))
                for label in COMPONENT_INVENTORY[component]
            ],
        }

    request_fixture = sample_request("pull")
    validate_evidence_object(request_fixture)
    request_sha = hashlib.sha256(canonical_json_v1(request_fixture)).hexdigest()
    require(
        request_sha == "eb0becc31bdc6eaa43025da619f5cf7bfd02a2c6bd8caba21606fb8b4ee39db7",
        f"request golden hash drifted: {request_sha}",
    )
    endpoint_fixture = sample_bundle("pr")
    validate_evidence_object(endpoint_fixture)
    endpoint_sha = hashlib.sha256(canonical_json_v1(endpoint_fixture)).hexdigest()
    require(
        endpoint_sha == "0ab458f39ecbd3c64a0a419c3abbb00e0c2094f682436cda3a2595351462897c",
        f"endpoint golden hash drifted: {endpoint_sha}",
    )
    for retired_endpoint_schema in ("gvn-endpoint-bundle-v1", "gvn-endpoint-bundle-v2"):
        expect_failure(
            lambda schema=retired_endpoint_schema: validate_evidence_object({**endpoint_fixture, "schema": schema}),
            f"retired endpoint bundle schema: {retired_endpoint_schema}",
        )
    expect_failure(lambda: validate_evidence_object({**endpoint_fixture, "unexpected": True}), "endpoint extra field")
    missing_body_hash_sidecar = json.loads(json.dumps(endpoint_fixture))
    del missing_body_hash_sidecar["responses"][0]["human_body_hashes"]
    expect_failure(lambda: validate_evidence_object(missing_body_hash_sidecar), "endpoint missing human body hash sidecar")
    forged_non_human_sidecar = sample_bundle("checks")
    response_item(forged_non_human_sidecar, "check-runs")["human_body_hashes"] = [
        {
            "kind": "github-review-rest",
            "immutable_id": "1",
            "field": "body",
            "state": "string",
            "sha256": hashlib.sha256(b"forged").hexdigest(),
        }
    ]
    expect_failure(lambda: validate_evidence_object(forged_non_human_sidecar), "non-human endpoint carrying body hash sidecar")
    for malformed_case, malformed_label, malformed_value in (
        ("empty-object", "pull", {}),
        ("null", "pull", None),
        ("array", "pull", []),
        ("empty-pull-request", "pull-metadata", {"data": {"repository": {"pullRequest": {}}}}),
        ("empty-pull-request", "post-merge-metadata", {"data": {"repository": {"pullRequest": {}}}}),
        ("empty-root", "review-threads", {}),
        ("empty-object", "attestation-comment", {}),
    ):
        malformed_component = {
            "pull": "pr",
            "pull-metadata": "metadata",
            "post-merge-metadata": "merge",
            "review-threads": "discussion",
            "attestation-comment": "attestation",
        }[malformed_label]
        malformed_bundle = sample_bundle(malformed_component)
        malformed_item = response_item(malformed_bundle, malformed_label)
        malformed_body = canonical_json_v1(malformed_value)
        malformed_digest = hashlib.sha256(malformed_body).hexdigest()
        malformed_item["response_body_base64"] = base64.b64encode(malformed_body).decode("ascii")
        malformed_item["response_body_sha256"] = malformed_digest
        malformed_item["response_canonical_sha256"] = malformed_digest
        malformed_item["human_body_hashes"] = []
        expect_failure(
            lambda bundle=malformed_bundle: validate_evidence_object(bundle),
            f"malformed {malformed_label} human body source: {malformed_case}",
        )
    text_pull_bundle = sample_bundle("pr")
    text_pull_item = response_item(text_pull_bundle, "pull")
    text_pull_body = b"not-json"
    text_pull_digest = hashlib.sha256(text_pull_body).hexdigest()
    text_pull_item["response_media_type"] = "text/plain; charset=utf-8"
    text_pull_item["response_body_base64"] = base64.b64encode(text_pull_body).decode("ascii")
    text_pull_item["response_body_sha256"] = text_pull_digest
    text_pull_item["response_canonical_sha256"] = text_pull_digest
    text_pull_item["human_body_hashes"] = []
    expect_failure(lambda: validate_evidence_object(text_pull_bundle), "human body source using text media type")
    for invalid_sidecar_id in (1, "001"):
        invalid_sidecar_bundle = json.loads(json.dumps(endpoint_fixture))
        response_item(invalid_sidecar_bundle, "pull")["human_body_hashes"][0]["immutable_id"] = invalid_sidecar_id
        expect_failure(
            lambda bundle=invalid_sidecar_bundle: validate_evidence_object(bundle),
            f"invalid sidecar immutable id {invalid_sidecar_id!r}",
        )
    missing_body_bundle = sample_bundle("pr", {"pull": {"id": 1}})
    require(
        response_item(missing_body_bundle, "pull")["human_body_hashes"][0]
        == {"kind": "pull-rest", "immutable_id": "1", "field": "body", "state": "missing", "sha256": None},
        "missing pull body state was not recorded exactly",
    )
    validate_evidence_object(missing_body_bundle)
    empty_body_bundle = sample_bundle("pr", {"pull": {"id": 1, "body": ""}})
    require(
        response_item(empty_body_bundle, "pull")["human_body_hashes"][0]["sha256"] == hashlib.sha256(b"").hexdigest(),
        "empty pull body hash mismatch",
    )
    validate_evidence_object(empty_body_bundle)
    expect_failure(
        lambda: validate_evidence_object({**endpoint_fixture, "responses": endpoint_fixture["responses"] * 2}),
        "endpoint duplicate response",
    )
    expect_failure(
        lambda: validate_evidence_object(
            {
                **endpoint_fixture,
                "responses": [{**endpoint_fixture["responses"][0], "response_body_sha256": "0" * 64}],
            }
        ),
        "endpoint raw body hash mismatch",
    )
    binary_bundle = sample_bundle("checks")
    binary_response = response_item(binary_bundle, "workflow-logs")
    binary_body = b"PK\x03\x04self-test"
    binary_sha = hashlib.sha256(binary_body).hexdigest()
    binary_response["response_media_type"] = "application/zip"
    binary_response["response_body_base64"] = base64.b64encode(binary_body).decode("ascii")
    binary_response["response_body_sha256"] = binary_sha
    binary_response["response_canonical_sha256"] = binary_sha
    validate_evidence_object(binary_bundle)
    invalid_binary_bundle = json.loads(json.dumps(binary_bundle))
    response_item(invalid_binary_bundle, "workflow-logs")["response_body_base64"] = "not-base64!"
    expect_failure(lambda: validate_evidence_object(invalid_binary_bundle), "endpoint invalid base64")
    oversized_job_log_buffer = io.BytesIO()
    with zipfile.ZipFile(oversized_job_log_buffer, "w", compression=zipfile.ZIP_DEFLATED) as oversized_job_log_archive:
        oversized_job_log_archive.writestr(f"{SAFE_INTEGER_LIMIT + 1}.log", "bounded self-test")
    oversized_job_log_bundle = sample_bundle("checks")
    oversized_job_log_response = response_item(oversized_job_log_bundle, "workflow-logs")
    oversized_job_log_bytes = oversized_job_log_buffer.getvalue()
    oversized_job_log_sha = hashlib.sha256(oversized_job_log_bytes).hexdigest()
    oversized_job_log_response["response_media_type"] = "application/zip"
    oversized_job_log_response["response_body_base64"] = base64.b64encode(oversized_job_log_bytes).decode("ascii")
    oversized_job_log_response["response_body_sha256"] = oversized_job_log_sha
    oversized_job_log_response["response_canonical_sha256"] = oversized_job_log_sha
    expect_failure_message(
        lambda: workflow_log_records(oversized_job_log_bundle),
        "workflow log job id must be a positive safe integer",
        "oversized workflow log job id",
    )

    empty_connection = {"nodes": [], "pageInfo": {"endCursor": None, "hasNextPage": False}}
    pull_title_fixture = "docs(governance): propose sole-maintainer merge protocol"
    pull_body_fixture = "Exact candidate governance proposal; no production authorization."
    pull_head_ref_fixture = "docs/g0-single-maintainer-governance"
    metadata_graphql = {
        "data": {
            "repository": {
                "pullRequest": {
                    "id": "PR_kwDOExample19",
                    "assignees": empty_connection,
                    "autoMergeRequest": None,
                    "baseRefName": "main",
                    "baseRefOid": "a" * 40,
                    "body": pull_body_fixture,
                    "headRefOid": "b" * 40,
                    "headRefName": pull_head_ref_fixture,
                    "isDraft": False,
                    "labels": empty_connection,
                    "mergeQueueEntry": None,
                    "mergeable": "MERGEABLE",
                    "number": 19,
                    "reviewRequests": empty_connection,
                    "title": pull_title_fixture,
                    "updatedAt": "2026-08-29T23:59:59Z",
                }
            }
        }
    }
    threads_graphql = {
        "data": {
            "repository": {
                "pullRequest": {
                    "id": "PR_kwDOExample19",
                    "baseRefOid": "a" * 40,
                    "headRefOid": "b" * 40,
                    "number": 19,
                    "reviewThreads": empty_connection,
                }
            }
        }
    }
    agent_review_reports = {
        "/root/agent-a": "ACCEPT; P0=0; P1=0; P2=0. 已验证：validator self-test、范围、候选 commit/tree、required contexts、workflow bytes、Finding 状态机和回滚说明均通过独立检查。推断：外部 API 原始来源仍依赖 owner attestation 与发布后回读。未验证：生产、部署、凭据与客户数据不在本次范围，也未发生外部写入。回滚：停止合并、废弃当前证据并从新候选重新审查。",
        "/root/agent-b": "ACCEPT; P0=0; P1=0; P2=0. 已验证：治理契约、CI provenance、文档一致性、秘密扫描、历史 allowlist 与 synthetic execution 关系均完成独立审计。推断：orchestrator transcript 的来源真实性由透明 residual、owner attestation 和两路回读覆盖。未验证：任何生产状态、真实发布或外部人工门均未触碰。回滚：使 attestation 失效并使用普通受保护修复 PR。",
    }
    agent_review_inputs = {
        reviewer_id: f"Independently review candidate {'b' * 40} / tree {'c' * 40}; inspect complete diff, validation evidence, security, compatibility, scope and rollback. Reviewer={reviewer_id}."
        for reviewer_id in ("/root/agent-a", "/root/agent-b")
    }
    agent_reviews_fixture = {
        "schema": "gvn-agent-reviews-v1",
        "reviews": [
            {
                "reviewer_id": reviewer_id,
                "task_name": reviewer_id,
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "source_authentication": "owner-attested-orchestrator-transcript",
                "implementation_participant": False,
                "started_at": "2026-08-29T23:40:00Z",
                "completed_at": "2026-08-29T23:45:00Z",
                "base_sha": "a" * 40,
                "candidate_head": "b" * 40,
                "candidate_tree": "c" * 40,
                "verdict": "ACCEPT",
                "p0": 0,
                "p1": 0,
                "p2": 0,
                "review_scope": list(AGENT_REVIEW_SCOPE),
                "verified": ["candidate-bound diff", "governance self-test"],
                "inferred": ["orchestrator transcript source is owner-attested"],
                "unverified": ["production state is outside scope", FRESHNESS_UNVERIFIED_MARKER],
                "verification": [
                    {
                        "command": "python3 scripts/validate_governance_state.py --self-test",
                        "result": "PASS",
                        "evidence": "exit=0; local structural validation passed",
                    }
                ],
                "findings": [],
                "review_input_body": agent_review_inputs[reviewer_id],
                "review_input_sha256": hashlib.sha256(agent_review_inputs[reviewer_id].encode("utf-8")).hexdigest(),
                "report_body": agent_review_reports[reviewer_id],
                "report_sha256": hashlib.sha256(agent_review_reports[reviewer_id].encode("utf-8")).hexdigest(),
            }
            for reviewer_id in ("/root/agent-a", "/root/agent-b")
        ],
    }
    check_runs_fixture = {
        "total_count": len(REQUIRED_CONTEXTS),
        "check_runs": [
            {
                "app": {"id": GITHUB_ACTIONS_APP_ID, "slug": "github-actions", "owner": {"login": "github"}},
                "check_suite": {"id": 300 + index},
                "conclusion": "success",
                "completed_at": "2026-08-30T00:00:00Z",
                "details_url": f"https://github.com/ZhangIvan/QingYin/actions/runs/{100 + index}/job/{200 + index}",
                "external_id": f"external-{index}",
                "head_sha": "b" * 40,
                "id": index,
                "name": context,
                "started_at": "2026-08-29T23:50:00Z",
                "status": "completed",
            }
            for index, context in enumerate(REQUIRED_CONTEXTS, start=1)
        ],
    }
    workflow_runs_fixture = {
        "total_count": len(REQUIRED_CONTEXTS),
        "workflow_runs": [
            {
                "check_suite": {"id": 300 + index},
                "conclusion": "success",
                "event": "pull_request",
                "head_sha": "b" * 40,
                "id": 100 + index,
                "path": CONTEXT_WORKFLOW_PATHS[context],
                "run_attempt": 1,
                "created_at": "2026-08-29T23:49:00Z",
                "run_started_at": "2026-08-29T23:50:00Z",
                "updated_at": "2026-08-30T00:00:00Z",
                "status": "completed",
            }
            for index, context in enumerate(REQUIRED_CONTEXTS, start=1)
        ],
    }
    workflow_jobs_fixture = {
        "jobs": [
            {
                "job_id": 200 + index,
                "run_id": 100 + index,
                "context": context,
                "check_run_id": index,
                "name": context,
                "workflow_path": CONTEXT_WORKFLOW_PATHS[context],
                "started_at": "2026-08-29T23:50:00Z",
                "completed_at": "2026-08-30T00:00:00Z",
                "status": "completed",
                "conclusion": "success",
            }
            for index, context in enumerate(REQUIRED_CONTEXTS, start=1)
        ]
    }
    workflow_log_contents = {
        200 + index: (
            f"GVN_EXECUTION context={context} sha={'9' * 40} tree={'c' * 40} "
            f"parents={'a' * 40} {'b' * 40}\n"
            f"GVN_RUNNER context={context} label={EXPECTED_RUNNER_LABEL} os=Linux arch=X64 "
            "image_os=ubuntu24 image_version=20260824.1.0 repository=ZhangIvan/QingYin event=pull_request shallow=false\n"
        ).encode()
        for index, context in enumerate(REQUIRED_CONTEXTS, start=1)
    }
    execution_objects_fixture = {
        "objects": [
            {
                "context": context,
                "object_type": "commit",
                "execution_sha": "9" * 40,
                "tree": "c" * 40,
                "ordered_parents": ["a" * 40, "b" * 40],
            }
            for context in REQUIRED_CONTEXTS
        ]
    }
    runner_provenance_fixture = {
        "schema": "gvn-runner-provenance-v1",
        "base_sha": "a" * 40,
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "executions": [
            {
                "context": context,
                "check_run_id": index,
                "check_suite_id": 300 + index,
                "external_id": f"external-{index}",
                "run_id": 100 + index,
                "job_id": 200 + index,
                "workflow_path": CONTEXT_WORKFLOW_PATHS[context],
                "event": "pull_request",
                "run_attempt": 1,
                "runner_label": EXPECTED_RUNNER_LABEL,
                "runner_os": "Linux",
                "runner_arch": "X64",
                "image_os": "ubuntu24",
                "image_version": "20260824.1.0",
                "repository": "ZhangIvan/QingYin",
                "shallow": False,
                "started_at": "2026-08-29T23:50:00Z",
                "completed_at": "2026-08-30T00:00:00Z",
                "log_sha256": hashlib.sha256(workflow_log_contents[200 + index]).hexdigest(),
                "execution_sha": "9" * 40,
                "execution_tree": "c" * 40,
                "ordered_parents": ["a" * 40, "b" * 40],
            }
            for index, context in enumerate(REQUIRED_CONTEXTS, start=1)
        ],
    }
    branch_protection_fixture = {
        "allow_deletions": {"enabled": False},
        "allow_force_pushes": {"enabled": False},
        "enforce_admins": {"enabled": True},
        "required_conversation_resolution": {"enabled": True},
        "required_linear_history": {"enabled": True},
        "required_status_checks": {
            "checks": [{"app_id": GITHUB_ACTIONS_APP_ID, "context": context} for context in REQUIRED_CONTEXTS],
            "contexts": list(REQUIRED_CONTEXTS),
            "strict": True,
        },
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "require_last_push_approval": False,
            "required_approving_review_count": 0,
        },
    }
    workflow_fixture_contents = {
        path: (ROOT / path).read_bytes()
        for path in (".github/workflows/design-contracts.yml", ".github/workflows/rust.yml")
    }
    workflow_blobs_fixture = {
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "workflows": [
            {
                "path": path,
                "blob": git_blob_sha1(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in workflow_fixture_contents.items()
        ],
    }
    action_occurrences_fixture: list[dict[str, Any]] = []
    for path, content in workflow_fixture_contents.items():
        document = yaml.load(content.decode("utf-8"), Loader=UniqueKeySafeLoader)
        for job_name, job in document["jobs"].items():
            for step_number, step in enumerate(job["steps"], start=1):
                if "uses" not in step:
                    continue
                action, sha = step["uses"].split("@", maxsplit=1)
                action_occurrences_fixture.append(
                    {"path": path, "job": job_name, "step": step_number, "action": action, "sha": sha}
                )
    action_occurrences_fixture.sort(key=lambda item: (utf16_sort_key(item["path"]), utf16_sort_key(item["job"]), item["step"], utf16_sort_key(item["action"]), utf16_sort_key(item["sha"])))
    action_pins_fixture = {
        "schema": "gvn-action-pins-v1",
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "occurrences": action_occurrences_fixture,
    }
    repository_settings_fixture = {
        "full_name": "ZhangIvan/QingYin",
        "default_branch": "main",
        "private": False,
        "fork": False,
        "archived": False,
        "disabled": False,
        "allow_squash_merge": True,
        "allow_merge_commit": True,
        "allow_rebase_merge": True,
        "allow_auto_merge": False,
        "delete_branch_on_merge": False,
        "owner": {"login": "ZhangIvan", "id": OWNER_GITHUB_ID},
    }
    security_settings_fixture = {
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
            "dependabot_security_updates": {"status": "enabled"},
        }
    }
    lockfile_fixture_files = []
    for path in ("Cargo.lock", "rust-toolchain.toml"):
        content = (ROOT / path).read_bytes()
        lockfile_fixture_files.append(
            {
                "path": path,
                "mode": "100644",
                "blob": git_blob_sha1(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    toolchain_lockfiles_fixture = {
        "schema": "gvn-toolchain-lockfiles-v1",
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "files": lockfile_fixture_files,
    }
    validator_source_fixture_bytes = b"#!/usr/bin/env python3\n\"\"\"Synthetic validator evidence fixture.\"\"\"\n"
    validator_source_fixture_blob = git_blob_sha1(validator_source_fixture_bytes)
    validator_source_fixture = {
        "schema": "gvn-validator-source-v1",
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "path": VALIDATOR_PATH.as_posix(),
        "mode": "100644",
        "type": "blob",
        "blob_sha1": validator_source_fixture_blob,
        "content_base64": base64.b64encode(validator_source_fixture_bytes).decode("ascii"),
        "content_sha256": hashlib.sha256(validator_source_fixture_bytes).hexdigest(),
    }
    candidate_tree_paths = sorted(
        {path.as_posix() for path in BOOTSTRAP_PATHS} | {"Cargo.lock", "rust-toolchain.toml"},
        key=utf16_sort_key,
    )
    candidate_tree_fixture = {
        "sha": "c" * 40,
        "truncated": False,
        "tree": [
            {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": validator_source_fixture_blob
                if path == VALIDATOR_PATH.as_posix()
                else git_blob_sha1((ROOT / path).read_bytes()),
            }
            for path in candidate_tree_paths
        ],
    }
    candidate_tree_blob_map = {item["path"]: item["sha"] for item in candidate_tree_fixture["tree"]}
    control_fixture_values = {
        "action-pins": action_pins_fixture,
        "branch-protection": branch_protection_fixture,
        "repository-settings": repository_settings_fixture,
        "rulesets": [],
        "validator-source": validator_source_fixture,
        "workflow-blobs": workflow_blobs_fixture,
    }
    verification_report_fixture = agent_review_references(
        sample_bundle("review", {"agent-reviews": agent_reviews_fixture, "github-reviews": []})
    )

    def acceptance_evidence_fixture(finding_id: str) -> dict[str, Any]:
        common = {
            "from_status": "Open",
            "transition": "Open->Accepted-Residual",
            "candidate_head": "b" * 40,
            "accepted_at": "2026-08-29T23:46:00Z",
            "accepted_by": "ZhangIvan",
            "accepted_by_id": OWNER_GITHUB_ID,
            "decision": "DEC-20260829-001",
            "section_sha256": RESIDUAL_SECTION_SHA256[finding_id],
            "verification_reports": verification_report_fixture,
            "owner_attestation_required": True,
        }
        if finding_id != "GVN-P1-005":
            return {"schema": "gvn-finding-acceptance-v1", **common}
        return {
            "schema": "gvn-finding-acceptance-v2",
            "from_status": common["from_status"],
            "transition": common["transition"],
            "finding_id": finding_id,
            "pr_number": 19,
            "base_sha": "a" * 40,
            "candidate_head": common["candidate_head"],
            "candidate_tree": "c" * 40,
            "target_type": "governance-bootstrap",
            "accepted_at": common["accepted_at"],
            "accepted_by": common["accepted_by"],
            "accepted_by_id": common["accepted_by_id"],
            "decision": common["decision"],
            "section_sha256": common["section_sha256"],
            "verification_reports": common["verification_reports"],
            "resolution_trigger": "trusted-signed-time-or-validator-direct-fetch-or-trusted-collector",
            "derived_status": {
                "stable_window_integrity": "VERIFIED",
                "stable_window_freshness": "UNVERIFIED",
                "activation_authorization": "CONDITIONAL_ACCEPTED_RESIDUAL",
            },
            "owner_attestation_required": common["owner_attestation_required"],
        }

    finding_ledger = {
        "findings": [
            {
                "id": finding_id,
                "severity": "P1",
                "status": "Accepted-Residual",
                "owner": "ZhangIvan",
                "scope": RESIDUAL_SCOPES[finding_id],
                "reason": "Platform limitation remains visible.",
                "mitigation": "Use exact evidence and fail closed.",
                "rollback": "Stop and use a protected recovery PR.",
                "evidence": acceptance_evidence_fixture(finding_id),
                "valid_until": RESIDUAL_VALID_UNTIL,
                "invalidators": ["candidate drift", "expiry"],
                "disposition": "Accepted only within the exact repository governance scope.",
            }
            for finding_id in RESIDUAL_IDS
        ]
    }
    pre_bundles = []
    for component in PRE_ATTESTATION_COMPONENTS:
        values: dict[str, Any] = {}
        if component == "pr":
            values = {
                "pull": {
                    "auto_merge": None,
                    "base": {"ref": "main", "sha": "a" * 40},
                    "body": pull_body_fixture,
                    "changed_files": len(BOOTSTRAP_STATUS),
                    "comments": 0,
                    "commits": 1,
                    "head": {"ref": pull_head_ref_fixture, "sha": "b" * 40},
                    "id": 19,
                    "locked": False,
                    "mergeable": True,
                    "mergeable_state": "clean",
                    "number": 19,
                    "node_id": "PR_kwDOExample19",
                    "draft": False,
                    "state": "open",
                    "title": pull_title_fixture,
                    "updated_at": "2026-08-29T23:59:59Z",
                }
            }
        if component == "paths":
            bootstrap_files = [
                {
                    "filename": path.as_posix(),
                    "status": "added" if status == "A" else "modified",
                    "sha": candidate_tree_blob_map[path.as_posix()],
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                }
                for index, (path, status) in enumerate(BOOTSTRAP_STATUS.items(), start=1)
            ]
            values = {
                "candidate-commit": {"object_type": "commit", "commit": "b" * 40, "tree": "c" * 40, "committed_at": "2026-08-29T23:30:00Z"},
                "candidate-tree": candidate_tree_fixture,
                "pull-files": bootstrap_files,
            }
        if component == "metadata":
            values = {"pull-metadata": metadata_graphql}
        if component == "review":
            values = {"agent-reviews": agent_reviews_fixture, "github-reviews": []}
        if component == "discussion":
            values = {
                "issue-comments": [],
                "review-threads": threads_graphql,
            }
        if component == "checks":
            values = {
                "check-runs": check_runs_fixture,
                "workflow-jobs": workflow_jobs_fixture,
                "workflow-runs": workflow_runs_fixture,
            }
        if component == "control":
            values = control_fixture_values
        if component == "identity":
            values = {
                "collaborators": [
                    {
                        "id": OWNER_GITHUB_ID,
                        "login": "ZhangIvan",
                        "role_name": "admin",
                        "permissions": {"admin": True, "maintain": True, "push": True, "triage": True, "pull": True},
                    }
                ],
                "owner-identity": {"id": OWNER_GITHUB_ID, "login": "ZhangIvan", "type": "User"},
            }
        if component == "security":
            values = {"security-settings": security_settings_fixture}
        if component == "runner":
            values = {
                "execution-objects": execution_objects_fixture,
                "runner-provenance": runner_provenance_fixture,
                "toolchain-lockfiles": toolchain_lockfiles_fixture,
            }
        if component == "finding":
            values = {"finding-ledger": finding_ledger}
        pre_bundles.append(sample_bundle(component, values))
    workflow_log_buffer = io.BytesIO()
    with zipfile.ZipFile(workflow_log_buffer, "w", compression=zipfile.ZIP_DEFLATED) as workflow_log_archive:
        for job_id, content in workflow_log_contents.items():
            workflow_log_archive.writestr(f"{job_id}.log", content)
    checks_bundle = next(bundle for bundle in pre_bundles if bundle["component"] == "checks")
    workflow_log_item = response_item(checks_bundle, "workflow-logs")
    workflow_log_bytes = workflow_log_buffer.getvalue()
    workflow_log_sha = hashlib.sha256(workflow_log_bytes).hexdigest()
    workflow_log_item["response_media_type"] = "application/zip"
    workflow_log_item["response_body_base64"] = base64.b64encode(workflow_log_bytes).decode("ascii")
    workflow_log_item["response_body_sha256"] = workflow_log_sha
    workflow_log_item["response_canonical_sha256"] = workflow_log_sha
    component_digests = [
        {"name": bundle["component"], "endpoint_bundle_sha256": hashlib.sha256(canonical_json_v1(bundle)).hexdigest()}
        for bundle in pre_bundles
    ]
    pre_bundle_map = {bundle["component"]: bundle for bundle in pre_bundles}
    semantic_root = {
        "pr_number": 19,
        "base_sha": "a" * 40,
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "snapshot_cutoff_utc": "2026-08-30T00:00:00Z",
    }

    def replace_json_response(bundle: dict[str, Any], label: str, value: Any, *, rederive_human_body_hashes: bool = True) -> None:
        item = response_item(bundle, label)
        body = canonical_json_v1(value)
        digest = hashlib.sha256(body).hexdigest()
        item["response_media_type"] = "application/json"
        item["response_body_base64"] = base64.b64encode(body).decode("ascii")
        item["response_body_sha256"] = digest
        item["response_canonical_sha256"] = digest
        if rederive_human_body_hashes:
            item["human_body_hashes"] = derive_human_body_hashes(label, value)

    def expect_reversed_response_array_acceptance(
        component: str,
        response_label: str,
        array_getter: Callable[[Any], list[Any]],
        test_label: str,
    ) -> None:
        candidate_map = json.loads(json.dumps(pre_bundle_map))
        response = response_value(candidate_map[component], response_label)
        array = array_getter(response)
        require(len(array) > 1, f"self-test requires at least two items: {test_label}")
        array.reverse()
        replace_json_response(candidate_map[component], response_label, response)
        envelope = response_item(candidate_map[component], response_label)
        frozen_transport = {
            field: envelope[field]
            for field in ("response_body_base64", "response_body_sha256", "response_canonical_sha256")
        }
        original_envelope = response_item(pre_bundle_map[component], response_label)
        require(
            all(frozen_transport[field] != original_envelope[field] for field in frozen_transport),
            f"raw-order change did not reset transport/canonical evidence: {test_label}",
        )
        validate_package_response_semantics(candidate_map, semantic_root)
        require(
            all(envelope[field] == value for field, value in frozen_transport.items()),
            f"semantic validation mutated raw response evidence: {test_label}",
        )

    def expect_reversed_response_array_failure(
        component: str,
        response_label: str,
        array_getter: Callable[[Any], list[Any]],
        expected_message: str,
        test_label: str,
    ) -> None:
        candidate_map = json.loads(json.dumps(pre_bundle_map))
        response = response_value(candidate_map[component], response_label)
        array = array_getter(response)
        require(len(array) > 1, f"self-test requires at least two items: {test_label}")
        array.reverse()
        replace_json_response(candidate_map[component], response_label, response)
        expect_failure_message(
            lambda: validate_package_response_semantics(candidate_map, semantic_root),
            expected_message,
            test_label,
        )

    def expect_duplicate_response_array_failure(
        component: str,
        response_label: str,
        array_getter: Callable[[Any], list[Any]],
        expected_message: str,
        test_label: str,
    ) -> None:
        candidate_map = json.loads(json.dumps(pre_bundle_map))
        response = response_value(candidate_map[component], response_label)
        array = array_getter(response)
        require(array, f"self-test requires a non-empty array: {test_label}")
        array.append(json.loads(json.dumps(array[0])))
        replace_json_response(candidate_map[component], response_label, response)
        expect_failure_message(
            lambda: validate_package_response_semantics(candidate_map, semantic_root),
            expected_message,
            test_label,
        )

    validate_package_response_semantics(pre_bundle_map, semantic_root)
    for derived_component, derived_label in (
        ("checks", "workflow-jobs"),
        ("checks", "workflow-logs"),
        ("runner", "runner-provenance"),
        ("finding", "finding-ledger"),
    ):
        require(
            response_item(pre_bundle_map[derived_component], derived_label)["request"]["body"]
            == {"label": derived_label},
            f"valid derived request operation descriptor mismatch: {derived_label}",
        )
    mismatched_derived_request_map = json.loads(json.dumps(pre_bundle_map))
    mismatched_derived_request = response_item(mismatched_derived_request_map["checks"], "workflow-jobs")
    mismatched_derived_request["request"]["body"] = {"label": "workflow-logs"}
    mismatched_derived_request["request_canonical_sha256"] = hashlib.sha256(
        canonical_json_v1(mismatched_derived_request["request"])
    ).hexdigest()
    expect_failure_message(
        lambda: validate_package_request_bindings(
            mismatched_derived_request_map,
            19,
            "b" * 40,
            "c" * 40,
            None,
        ),
        "derived request operation descriptor mismatch: workflow-jobs",
        "mismatched derived request operation descriptor",
    )
    reversed_endpoint_bundle = json.loads(json.dumps(pre_bundle_map["checks"]))
    reversed_endpoint_bundle["responses"].reverse()
    expect_failure_message(
        lambda: validate_evidence_object(reversed_endpoint_bundle),
        "endpoint bundle responses are not canonically sorted",
        "reversed multi-response endpoint bundle",
    )
    expect_reversed_response_array_acceptance(
        "paths",
        "candidate-tree",
        lambda response: response["tree"],
        "reversed candidate tree entries",
    )
    expect_reversed_response_array_acceptance(
        "paths",
        "pull-files",
        lambda response: response,
        "reversed pull files",
    )
    expect_reversed_response_array_acceptance(
        "checks",
        "check-runs",
        lambda response: response["check_runs"],
        "reversed check runs",
    )
    expect_reversed_response_array_acceptance(
        "checks",
        "workflow-runs",
        lambda response: response["workflow_runs"],
        "reversed workflow runs",
    )
    expect_reversed_response_array_failure(
        "checks",
        "workflow-jobs",
        lambda response: response["jobs"],
        "workflow-jobs.jobs must be in stable canonical order",
        "reversed workflow jobs",
    )
    expect_reversed_response_array_failure(
        "runner",
        "execution-objects",
        lambda response: response["objects"],
        "execution Git objects must follow the fixed required-context sequence",
        "reversed execution objects",
    )
    expect_reversed_response_array_acceptance(
        "control",
        "branch-protection",
        lambda response: response["required_status_checks"]["contexts"],
        "reversed branch-protection contexts",
    )
    expect_reversed_response_array_acceptance(
        "control",
        "branch-protection",
        lambda response: response["required_status_checks"]["checks"],
        "reversed branch-protection checks",
    )
    provider_order_protection_map = json.loads(json.dumps(pre_bundle_map))
    provider_order_protection = response_value(provider_order_protection_map["control"], "branch-protection")
    provider_context_order = ("contract-fixtures", "format-lint", "unit", "security", "msrv")
    provider_order_protection["required_status_checks"]["contexts"] = list(provider_context_order)
    checks_by_context = {
        item["context"]: item for item in provider_order_protection["required_status_checks"]["checks"]
    }
    provider_order_protection["required_status_checks"]["checks"] = [
        checks_by_context[context] for context in provider_context_order
    ]
    replace_json_response(
        provider_order_protection_map["control"],
        "branch-protection",
        provider_order_protection,
    )
    validate_package_response_semantics(provider_order_protection_map, semantic_root)
    expect_reversed_response_array_failure(
        "control",
        "workflow-blobs",
        lambda response: response["workflows"],
        "workflow blob paths must be unique and sorted",
        "reversed workflow blobs",
    )
    expect_reversed_response_array_failure(
        "control",
        "action-pins",
        lambda response: response["occurrences"],
        "action pin inventory differs from the complete workflow content",
        "reversed action pin occurrences",
    )
    reversed_finding_map = json.loads(json.dumps(pre_bundle_map))
    reversed_finding_ledger = response_value(reversed_finding_map["finding"], "finding-ledger")
    reversed_finding_ledger["findings"].reverse()
    replace_json_response(reversed_finding_map["finding"], "finding-ledger", reversed_finding_ledger)
    expect_failure_message(
        lambda: validate_finding_ledger(
            reversed_finding_map["finding"],
            reversed_finding_map["review"],
            semantic_root["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "finding ledger ids must be unique and sorted",
        "reversed finding ledger",
    )
    for component, response_label, array_getter, expected_message, test_label in (
        ("paths", "candidate-tree", lambda response: response["tree"], "candidate-tree.tree contains a duplicate stable unique key", "duplicate candidate-tree path key"),
        ("paths", "pull-files", lambda response: response, "pull-files contains a duplicate stable unique key", "duplicate pull-file name key"),
        ("checks", "check-runs", lambda response: response["check_runs"], "check-runs.check_runs contains a duplicate stable unique key", "duplicate check-run id key"),
        ("checks", "workflow-runs", lambda response: response["workflow_runs"], "workflow-runs.workflow_runs contains a duplicate stable unique key", "duplicate workflow-run id key"),
        ("control", "branch-protection", lambda response: response["required_status_checks"]["contexts"], "branch-protection.required_status_checks.contexts contains a duplicate stable unique key", "duplicate branch-protection context key"),
        ("control", "branch-protection", lambda response: response["required_status_checks"]["checks"], "branch-protection.required_status_checks.checks contains a duplicate stable unique key", "duplicate branch-protection check key"),
    ):
        expect_duplicate_response_array_failure(
            component,
            response_label,
            array_getter,
            expected_message,
            test_label,
        )
    duplicate_workflow_job_map = json.loads(json.dumps(pre_bundle_map))
    duplicate_workflow_jobs = response_value(duplicate_workflow_job_map["checks"], "workflow-jobs")
    duplicate_workflow_jobs["jobs"][1]["job_id"] = duplicate_workflow_jobs["jobs"][0]["job_id"]
    replace_json_response(duplicate_workflow_job_map["checks"], "workflow-jobs", duplicate_workflow_jobs)
    expect_failure_message(
        lambda: validate_package_response_semantics(duplicate_workflow_job_map, semantic_root),
        "workflow-jobs.jobs contains a duplicate stable unique key",
        "duplicate workflow-job id key",
    )
    ordered_metadata_map = json.loads(json.dumps(pre_bundle_map))
    ordered_metadata = response_value(ordered_metadata_map["metadata"], "pull-metadata")
    ordered_metadata_pr = ordered_metadata["data"]["repository"]["pullRequest"]
    ordered_metadata_pr["labels"]["nodes"] = [
        {"id": "LABEL_1", "name": "governance"},
        {"id": "LABEL_2", "name": "security"},
    ]
    ordered_metadata_pr["assignees"]["nodes"] = [
        {"id": "USER_1", "databaseId": 101, "login": "alpha"},
        {"id": "USER_2", "databaseId": 102, "login": "beta"},
    ]
    replace_json_response(ordered_metadata_map["metadata"], "pull-metadata", ordered_metadata)
    validate_package_response_semantics(ordered_metadata_map, semantic_root)
    reversed_labels_map = json.loads(json.dumps(ordered_metadata_map))
    reversed_labels = response_value(reversed_labels_map["metadata"], "pull-metadata")
    reversed_labels["data"]["repository"]["pullRequest"]["labels"]["nodes"].reverse()
    replace_json_response(reversed_labels_map["metadata"], "pull-metadata", reversed_labels)
    validate_package_response_semantics(reversed_labels_map, semantic_root)
    reversed_assignees_map = json.loads(json.dumps(ordered_metadata_map))
    reversed_assignees = response_value(reversed_assignees_map["metadata"], "pull-metadata")
    reversed_assignees["data"]["repository"]["pullRequest"]["assignees"]["nodes"].reverse()
    replace_json_response(reversed_assignees_map["metadata"], "pull-metadata", reversed_assignees)
    validate_package_response_semantics(reversed_assignees_map, semantic_root)
    duplicate_label_id_map = json.loads(json.dumps(ordered_metadata_map))
    duplicate_label_ids = response_value(duplicate_label_id_map["metadata"], "pull-metadata")
    duplicate_label_nodes = duplicate_label_ids["data"]["repository"]["pullRequest"]["labels"]["nodes"]
    duplicate_label_nodes[1]["id"] = duplicate_label_nodes[0]["id"]
    replace_json_response(duplicate_label_id_map["metadata"], "pull-metadata", duplicate_label_ids)
    expect_failure_message(
        lambda: validate_package_response_semantics(duplicate_label_id_map, semantic_root),
        "pull-metadata.labels.nodes contains a duplicate stable unique key",
        "duplicate GraphQL label immutable id with different name",
    )
    validate_evidence_object(pre_bundle_map["pr"])
    pull_sidecar = response_item(pre_bundle_map["pr"], "pull")["human_body_hashes"]
    require(
        pull_sidecar[0]["sha256"] == hashlib.sha256(pull_body_fixture.encode("utf-8")).hexdigest(),
        "REST pull body hash mismatch",
    )
    metadata_sidecar = response_item(pre_bundle_map["metadata"], "pull-metadata")["human_body_hashes"]
    require(
        metadata_sidecar
        == [
            {
                "kind": "pull-metadata-graphql",
                "immutable_id": "PR_kwDOExample19",
                "field": "body",
                "state": "string",
                "sha256": hashlib.sha256(pull_body_fixture.encode("utf-8")).hexdigest(),
            }
        ],
        "GraphQL pull metadata body hash sidecar mismatch",
    )
    tampered_metadata_bundle = json.loads(json.dumps(pre_bundle_map["metadata"]))
    tampered_metadata = response_value(tampered_metadata_bundle, "pull-metadata")
    tampered_metadata["data"]["repository"]["pullRequest"]["body"] += " tampered"
    replace_json_response(
        tampered_metadata_bundle,
        "pull-metadata",
        tampered_metadata,
        rederive_human_body_hashes=False,
    )
    expect_failure(
        lambda: validate_evidence_object(tampered_metadata_bundle),
        "pull-metadata body tamper with recomputed endpoint hashes",
    )
    tampered_pull_bundle = json.loads(json.dumps(pre_bundle_map["pr"]))
    tampered_pull = response_value(tampered_pull_bundle, "pull")
    tampered_pull["body"] += " tampered"
    replace_json_response(tampered_pull_bundle, "pull", tampered_pull, rederive_human_body_hashes=False)
    expect_failure(lambda: validate_evidence_object(tampered_pull_bundle), "pull body tamper with recomputed endpoint hashes")

    both_updated_at_late_map = json.loads(json.dumps(pre_bundle_map))
    both_updated_at_late_pull = response_value(both_updated_at_late_map["pr"], "pull")
    both_updated_at_late_pull["updated_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(both_updated_at_late_map["pr"], "pull", both_updated_at_late_pull)
    both_updated_at_late_metadata = response_value(both_updated_at_late_map["metadata"], "pull-metadata")
    both_updated_at_late_metadata["data"]["repository"]["pullRequest"]["updatedAt"] = "2026-08-30T00:00:01Z"
    replace_json_response(both_updated_at_late_map["metadata"], "pull-metadata", both_updated_at_late_metadata)
    expect_failure_message(
        lambda: validate_package_response_semantics(both_updated_at_late_map, semantic_root),
        "pull updated_at is newer than package response cutoff",
        "REST and GraphQL pull timestamps after cutoff",
    )
    rest_updated_at_late_map = json.loads(json.dumps(pre_bundle_map))
    rest_updated_at_late_pull = response_value(rest_updated_at_late_map["pr"], "pull")
    rest_updated_at_late_pull["updated_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(rest_updated_at_late_map["pr"], "pull", rest_updated_at_late_pull)
    expect_failure_message(
        lambda: validate_package_response_semantics(rest_updated_at_late_map, semantic_root),
        "pull updated_at is newer than package response cutoff",
        "REST pull timestamp after cutoff",
    )
    graphql_updated_at_late_map = json.loads(json.dumps(pre_bundle_map))
    graphql_updated_at_late_metadata = response_value(graphql_updated_at_late_map["metadata"], "pull-metadata")
    graphql_updated_at_late_metadata["data"]["repository"]["pullRequest"]["updatedAt"] = "2026-08-30T00:00:01Z"
    replace_json_response(graphql_updated_at_late_map["metadata"], "pull-metadata", graphql_updated_at_late_metadata)
    expect_failure_message(
        lambda: validate_package_response_semantics(graphql_updated_at_late_map, semantic_root),
        "pull metadata updatedAt is newer than package response cutoff",
        "GraphQL pull timestamp after cutoff",
    )
    equal_cutoff_updated_at_map = json.loads(json.dumps(pre_bundle_map))
    equal_cutoff_pull = response_value(equal_cutoff_updated_at_map["pr"], "pull")
    equal_cutoff_pull["updated_at"] = semantic_root["snapshot_cutoff_utc"]
    replace_json_response(equal_cutoff_updated_at_map["pr"], "pull", equal_cutoff_pull)
    equal_cutoff_metadata = response_value(equal_cutoff_updated_at_map["metadata"], "pull-metadata")
    equal_cutoff_metadata["data"]["repository"]["pullRequest"]["updatedAt"] = semantic_root["snapshot_cutoff_utc"]
    replace_json_response(equal_cutoff_updated_at_map["metadata"], "pull-metadata", equal_cutoff_metadata)
    validate_package_response_semantics(equal_cutoff_updated_at_map, semantic_root)
    expect_failure(
        lambda: validate_package_response_semantics(both_updated_at_late_map, semantic_root),
        "pre-attestation cutoff rejects late pull timestamps",
    )
    validate_package_response_semantics(both_updated_at_late_map, semantic_root, "2026-08-30T00:00:01Z")
    wrong_target_map = dict(pre_bundle_map)
    wrong_target_map["pr"] = sample_bundle(
        "pr",
        {"pull": {"id": 1, "body": None, "comments": 0, "updated_at": "2026-08-29T23:59:59Z"}},
    )
    response_item(wrong_target_map["pr"], "pull")["request"]["path"] = "/repos/ZhangIvan/QingYin/pulls/42"
    expect_failure(
        lambda: validate_package_request_bindings(wrong_target_map, 19, "b" * 40, "c" * 40, None),
        "package request identity mismatch",
    )
    truncated_map = dict(pre_bundle_map)
    truncated_map["discussion"] = sample_bundle(
        "discussion",
        {"issue-comments": [{"id": index} for index in range(1, 101)], "review-threads": threads_graphql},
    )
    expect_failure(
        lambda: validate_package_request_bindings(truncated_map, 19, "b" * 40, "c" * 40, None),
        "paginated response truncation",
    )
    truncated_candidate_tree_map = json.loads(json.dumps(pre_bundle_map))
    truncated_candidate_tree = response_value(truncated_candidate_tree_map["paths"], "candidate-tree")
    truncated_candidate_tree["truncated"] = True
    replace_json_response(truncated_candidate_tree_map["paths"], "candidate-tree", truncated_candidate_tree)
    expect_failure(
        lambda: validate_package_response_semantics(truncated_candidate_tree_map, semantic_root),
        "candidate tree truncated flag",
    )
    duplicate_candidate_tree_map = json.loads(json.dumps(pre_bundle_map))
    duplicate_candidate_tree = response_value(duplicate_candidate_tree_map["paths"], "candidate-tree")
    duplicate_candidate_tree["tree"].append(json.loads(json.dumps(duplicate_candidate_tree["tree"][0])))
    replace_json_response(duplicate_candidate_tree_map["paths"], "candidate-tree", duplicate_candidate_tree)
    expect_failure(
        lambda: validate_package_response_semantics(duplicate_candidate_tree_map, semantic_root),
        "candidate tree duplicate path",
    )
    forged_pull_map = dict(pre_bundle_map)
    forged_pull_map["pr"] = sample_bundle(
        "pr",
        {
            "pull": {
                "id": 42,
                "base": {"sha": "a" * 40},
                "body": "forged pull fixture",
                "comments": 0,
                "head": {"sha": "d" * 40},
                "number": 42,
                "draft": False,
                "state": "open",
                "updated_at": "2026-08-29T23:59:59Z",
            }
        },
    )
    expect_failure(lambda: validate_package_response_semantics(forged_pull_map, semantic_root), "forged pull response identity")
    forged_check_map = dict(pre_bundle_map)
    forged_check_response = json.loads(json.dumps(check_runs_fixture))
    forged_check_response["check_runs"][0]["head_sha"] = "f" * 40
    forged_check_map["checks"] = sample_bundle("checks", {"check-runs": forged_check_response})
    expect_failure(lambda: validate_package_response_semantics(forged_check_map, semantic_root), "forged check-run head")
    forged_graphql_map = dict(pre_bundle_map)
    forged_metadata = json.loads(json.dumps(metadata_graphql))
    forged_metadata["data"]["repository"]["pullRequest"]["number"] = 42
    forged_graphql_map["metadata"] = sample_bundle("metadata", {"pull-metadata": forged_metadata})
    expect_failure(lambda: validate_package_response_semantics(forged_graphql_map, semantic_root), "forged GraphQL PR identity")
    graphql_error_map = dict(pre_bundle_map)
    graphql_error_response = json.loads(json.dumps(metadata_graphql))
    graphql_error_response["errors"] = [{"message": "partial failure"}]
    graphql_error_map["metadata"] = sample_bundle("metadata", {"pull-metadata": graphql_error_response})
    expect_failure(lambda: validate_package_request_bindings(graphql_error_map, 19, "b" * 40, "c" * 40, None), "GraphQL data plus errors")
    pending_review_map = dict(pre_bundle_map)
    pending_metadata = json.loads(json.dumps(metadata_graphql))
    pending_metadata["data"]["repository"]["pullRequest"]["reviewRequests"]["nodes"] = [{"requestedReviewer": {"id": "x"}}]
    pending_review_map["metadata"] = sample_bundle("metadata", {"pull-metadata": pending_metadata})
    expect_failure(lambda: validate_package_response_semantics(pending_review_map, semantic_root), "pending review request")
    null_app_map = dict(pre_bundle_map)
    null_app_checks = json.loads(json.dumps(check_runs_fixture))
    for item in null_app_checks["check_runs"]:
        item["app"]["id"] = None
    null_app_protection = json.loads(json.dumps(branch_protection_fixture))
    for item in null_app_protection["required_status_checks"]["checks"]:
        item["app_id"] = None
    null_app_map["checks"] = sample_bundle("checks", {"check-runs": null_app_checks, "workflow-runs": workflow_runs_fixture})
    null_app_map["control"] = sample_bundle("control", {**control_fixture_values, "branch-protection": null_app_protection})
    expect_failure(lambda: validate_package_response_semantics(null_app_map, semantic_root), "null required app identity")
    owner_review_map = dict(pre_bundle_map)
    owner_reviews = json.loads(json.dumps(agent_reviews_fixture))
    owner_reviews["reviews"][1]["reviewer_id"] = "/root/ZhangIvan"
    owner_review_map["review"] = sample_bundle("review", {"agent-reviews": owner_reviews, "github-reviews": []})
    expect_failure(lambda: validate_package_response_semantics(owner_review_map, semantic_root), "owner counted as agent reviewer")
    future_review_map = dict(pre_bundle_map)
    future_reviews = json.loads(json.dumps(agent_reviews_fixture))
    future_reviews["reviews"][0]["completed_at"] = "2026-08-30T00:00:01Z"
    future_review_map["review"] = sample_bundle("review", {"agent-reviews": future_reviews, "github-reviews": []})
    expect_failure(lambda: validate_package_response_semantics(future_review_map, semantic_root), "agent review newer than evidence cutoff")
    forged_review_input_map = dict(pre_bundle_map)
    forged_review_input = json.loads(json.dumps(agent_reviews_fixture))
    forged_review_input["reviews"][0]["review_input_sha256"] = "0" * 64
    forged_review_input_map["review"] = sample_bundle("review", {"agent-reviews": forged_review_input, "github-reviews": []})
    expect_failure(lambda: validate_package_response_semantics(forged_review_input_map, semantic_root), "agent review input hash mismatch")
    github_review_fixture = {
        "id": 71,
        "node_id": "PRR_kwDOReview71",
        "user": {"id": 72, "login": "review-bot", "type": "Bot"},
        "state": "COMMENTED",
        "body": "Candidate-bound review metadata fixture.",
        "commit_id": "b" * 40,
        "submitted_at": "2026-08-29T23:48:00Z",
    }
    issue_comment_fixture = {
        "id": 74,
        "node_id": "IC_kwDOIssue74",
        "user": {"id": 75, "login": "reviewer-human"},
        "body": "Unicode é🙂 with CRLF\r\nand trailing space ",
        "created_at": "2026-08-29T23:47:00Z",
        "updated_at": "2026-08-29T23:49:00Z",
    }
    current_threads = json.loads(json.dumps(threads_graphql))
    current_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = [
        {
            "id": "PRRT_kwDOThread1",
            "isResolved": True,
            "isOutdated": False,
            "comments": {
                "nodes": [
                    {
                        "id": "PRRC_kwDOComment1",
                        "databaseId": 73,
                        "author": {"login": "review-bot", "id": "BOT_kwDOReviewer", "databaseId": 72},
                        "body": "Resolved candidate-bound comment.",
                        "createdAt": "2026-08-29T23:48:00Z",
                        "updatedAt": "2026-08-29T23:49:00Z",
                        "outdated": False,
                        "state": "SUBMITTED",
                        "commit": {"oid": "b" * 40},
                    }
                ],
                "pageInfo": {"endCursor": None, "hasNextPage": False},
            },
        }
    ]
    github_review_map = dict(pre_bundle_map)
    github_review_map["review"] = sample_bundle("review", {"agent-reviews": agent_reviews_fixture, "github-reviews": [github_review_fixture]})
    github_review_map["discussion"] = sample_bundle(
        "discussion",
        {"issue-comments": [issue_comment_fixture], "review-threads": current_threads},
    )
    validate_package_response_semantics(github_review_map, semantic_root)
    second_github_review = {
        **github_review_fixture,
        "id": 72,
        "node_id": "PRR_kwDOReview72",
        "user": {"id": 76, "login": "reviewer-human", "type": "User"},
        "state": "APPROVED",
        "body": "Second candidate-bound review fixture.",
        "submitted_at": "2026-08-29T23:49:00Z",
    }
    second_issue_comment = {
        **issue_comment_fixture,
        "id": 76,
        "node_id": "IC_kwDOIssue76",
        "user": {"id": 77, "login": "second-reviewer"},
        "body": "Second issue comment fixture.",
        "created_at": "2026-08-29T23:50:00Z",
        "updated_at": "2026-08-29T23:51:00Z",
    }
    ordered_threads = json.loads(json.dumps(current_threads))
    first_thread_comments = ordered_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]["nodes"]
    first_thread_comments.append(
        {
            **first_thread_comments[0],
            "id": "PRRC_kwDOComment2",
            "databaseId": 78,
            "body": "Second candidate-bound thread comment.",
            "createdAt": "2026-08-29T23:49:00Z",
            "updatedAt": "2026-08-29T23:50:00Z",
        }
    )
    ordered_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"].append(
        {
            "id": "PRRT_kwDOThread2",
            "isResolved": True,
            "isOutdated": False,
            "comments": {
                "nodes": [
                    {
                        **first_thread_comments[0],
                        "id": "PRRC_kwDOComment3",
                        "databaseId": 79,
                        "body": "Candidate-bound comment in the second thread.",
                        "createdAt": "2026-08-29T23:50:00Z",
                        "updatedAt": "2026-08-29T23:51:00Z",
                    }
                ],
                "pageInfo": {"endCursor": None, "hasNextPage": False},
            },
        }
    )
    ordered_human_map = json.loads(json.dumps(pre_bundle_map))
    ordered_human_map["review"] = sample_bundle(
        "review",
        {"agent-reviews": agent_reviews_fixture, "github-reviews": [github_review_fixture, second_github_review]},
    )
    ordered_human_map["discussion"] = sample_bundle(
        "discussion",
        {"issue-comments": [issue_comment_fixture, second_issue_comment], "review-threads": ordered_threads},
    )
    validate_package_response_semantics(ordered_human_map, semantic_root)
    for response_label in ("github-reviews", "issue-comments"):
        component = "review" if response_label == "github-reviews" else "discussion"
        reversed_human_map = json.loads(json.dumps(ordered_human_map))
        reversed_values = response_value(reversed_human_map[component], response_label)
        reversed_values.reverse()
        replace_json_response(reversed_human_map[component], response_label, reversed_values)
        validate_package_response_semantics(reversed_human_map, semantic_root)
    reversed_threads_map = json.loads(json.dumps(ordered_human_map))
    reversed_threads = response_value(reversed_threads_map["discussion"], "review-threads")
    reversed_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"].reverse()
    replace_json_response(reversed_threads_map["discussion"], "review-threads", reversed_threads)
    validate_package_response_semantics(reversed_threads_map, semantic_root)
    reversed_thread_comments_map = json.loads(json.dumps(ordered_human_map))
    reversed_thread_comments = response_value(reversed_thread_comments_map["discussion"], "review-threads")
    reversed_thread_comments["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]["nodes"].reverse()
    replace_json_response(reversed_thread_comments_map["discussion"], "review-threads", reversed_thread_comments)
    validate_package_response_semantics(reversed_thread_comments_map, semantic_root)
    validate_evidence_object(github_review_map["review"])
    validate_evidence_object(github_review_map["discussion"])
    github_review_sidecar = response_item(github_review_map["review"], "github-reviews")["human_body_hashes"]
    require(
        github_review_sidecar
        == [
            {
                "kind": "github-review-rest",
                "immutable_id": "71",
                "field": "body",
                "state": "string",
                "sha256": hashlib.sha256(github_review_fixture["body"].encode("utf-8")).hexdigest(),
            }
        ],
        "GitHub review body hash sidecar mismatch",
    )
    discussion_sidecars = {
        label: response_item(github_review_map["discussion"], label)["human_body_hashes"]
        for label in ("issue-comments", "review-threads")
    }
    require(
        discussion_sidecars["issue-comments"][0]["sha256"]
        == hashlib.sha256(issue_comment_fixture["body"].encode("utf-8")).hexdigest(),
        "issue comment body hash does not preserve exact decoded UTF-8 bytes",
    )
    require(
        discussion_sidecars["review-threads"][0]["sha256"]
        == hashlib.sha256("Resolved candidate-bound comment.".encode("utf-8")).hexdigest(),
        "review-thread comment body hash mismatch",
    )

    tampered_review_bundle = json.loads(json.dumps(github_review_map["review"]))
    tampered_reviews = response_value(tampered_review_bundle, "github-reviews")
    tampered_reviews[0]["body"] += " tampered"
    replace_json_response(
        tampered_review_bundle,
        "github-reviews",
        tampered_reviews,
        rederive_human_body_hashes=False,
    )
    expect_failure_message(
        lambda: validate_evidence_object(tampered_review_bundle),
        "human body hashes differ from decoded raw response",
        "review body tamper with recomputed endpoint hashes",
    )
    whitespace_review_bundle = json.loads(json.dumps(github_review_map["review"]))
    whitespace_review_item = response_item(whitespace_review_bundle, "github-reviews")
    whitespace_review_value = response_value(whitespace_review_bundle, "github-reviews")
    whitespace_body = json.dumps(whitespace_review_value, ensure_ascii=False, indent=2).encode("utf-8")
    whitespace_review_item["response_body_base64"] = base64.b64encode(whitespace_body).decode("ascii")
    whitespace_review_item["response_body_sha256"] = hashlib.sha256(whitespace_body).hexdigest()
    whitespace_review_item["response_canonical_sha256"] = hashlib.sha256(canonical_json_v1(whitespace_review_value)).hexdigest()
    validate_evidence_object(whitespace_review_bundle)
    require(
        whitespace_review_item["human_body_hashes"] == github_review_sidecar,
        "JSON transport whitespace changed the decoded field hash",
    )
    null_review_map = json.loads(json.dumps(github_review_map))
    null_reviews = response_value(null_review_map["review"], "github-reviews")
    null_reviews[0]["body"] = None
    replace_json_response(null_review_map["review"], "github-reviews", null_reviews)
    require(
        response_item(null_review_map["review"], "github-reviews")["human_body_hashes"][0]["state"] == "null",
        "null review body state was not recorded",
    )
    expect_failure(lambda: validate_package_response_semantics(null_review_map, semantic_root), "null GitHub review body")
    duplicate_review_fixture = {**github_review_fixture, "body": "same id, different body"}
    expect_failure(
        lambda: sample_bundle(
            "review",
            {"agent-reviews": agent_reviews_fixture, "github-reviews": [github_review_fixture, duplicate_review_fixture]},
        ),
        "duplicate GitHub review body hash identity",
    )
    expect_failure(
        lambda: sample_bundle(
            "review",
            {"agent-reviews": agent_reviews_fixture, "github-reviews": [{**github_review_fixture, "body": "e\u0301"}]},
        ),
        "non-NFC human body remains forbidden by canonical evidence",
    )
    tampered_thread_bundle = json.loads(json.dumps(github_review_map["discussion"]))
    tampered_threads = response_value(tampered_thread_bundle, "review-threads")
    tampered_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]["body"] += " tampered"
    replace_json_response(
        tampered_thread_bundle,
        "review-threads",
        tampered_threads,
        rederive_human_body_hashes=False,
    )
    expect_failure(lambda: validate_evidence_object(tampered_thread_bundle), "review-thread body tamper with recomputed endpoint hashes")
    tampered_issue_bundle = json.loads(json.dumps(github_review_map["discussion"]))
    tampered_issue_comments = response_value(tampered_issue_bundle, "issue-comments")
    tampered_issue_comments[0]["body"] += " tampered"
    replace_json_response(
        tampered_issue_bundle,
        "issue-comments",
        tampered_issue_comments,
        rederive_human_body_hashes=False,
    )
    expect_failure(lambda: validate_evidence_object(tampered_issue_bundle), "issue-comment body tamper with recomputed endpoint hashes")
    duplicate_issue_comment = {**issue_comment_fixture, "body": "duplicate immutable issue id"}
    expect_failure(
        lambda: sample_bundle(
            "discussion",
            {"issue-comments": [issue_comment_fixture, duplicate_issue_comment], "review-threads": current_threads},
        ),
        "duplicate issue comment body hash identity",
    )
    duplicate_thread_comment = json.loads(json.dumps(current_threads))
    duplicate_thread_nodes = duplicate_thread_comment["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]["nodes"]
    duplicate_thread_nodes.append({**duplicate_thread_nodes[0], "body": "duplicate immutable thread comment id"})
    expect_failure(
        lambda: sample_bundle(
            "discussion",
            {"issue-comments": [issue_comment_fixture], "review-threads": duplicate_thread_comment},
        ),
        "duplicate review-thread comment body hash identity",
    )
    late_issue_comment_map = json.loads(json.dumps(github_review_map))
    late_issue_comments = response_value(late_issue_comment_map["discussion"], "issue-comments")
    late_issue_comments[0]["updated_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(late_issue_comment_map["discussion"], "issue-comments", late_issue_comments)
    expect_failure_message(
        lambda: validate_package_response_semantics(late_issue_comment_map, semantic_root),
        "issue comment[0] timestamps invalid",
        "issue comment newer than cutoff",
    )
    missing_freshness_marker_map = json.loads(json.dumps(pre_bundle_map))
    missing_freshness_marker_reviews = response_value(missing_freshness_marker_map["review"], "agent-reviews")
    missing_freshness_marker_reviews["reviews"][0]["unverified"].remove(FRESHNESS_UNVERIFIED_MARKER)
    replace_json_response(missing_freshness_marker_map["review"], "agent-reviews", missing_freshness_marker_reviews)
    expect_failure_message(
        lambda: validate_package_response_semantics(missing_freshness_marker_map, semantic_root),
        "agent review[0] does not disclose GVN-P1-005 freshness as unverified",
        "missing GVN-P1-005 reviewer disclosure",
    )
    false_freshness_verification_map = json.loads(json.dumps(pre_bundle_map))
    false_freshness_reviews = response_value(false_freshness_verification_map["review"], "agent-reviews")
    false_freshness_reviews["reviews"][0]["verified"] = sorted(
        [*false_freshness_reviews["reviews"][0]["verified"], FRESHNESS_UNVERIFIED_MARKER],
        key=utf16_sort_key,
    )
    replace_json_response(false_freshness_verification_map["review"], "agent-reviews", false_freshness_reviews)
    expect_failure_message(
        lambda: validate_package_response_semantics(false_freshness_verification_map, semantic_root),
        "agent review[0] falsely verifies stable-window capture freshness",
        "false GVN-P1-005 reviewer verification",
    )
    future_candidate_map = json.loads(json.dumps(pre_bundle_map))
    future_candidate = response_value(future_candidate_map["paths"], "candidate-commit")
    future_candidate["committed_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(future_candidate_map["paths"], "candidate-commit", future_candidate)
    expect_failure_message(
        lambda: validate_package_response_semantics(future_candidate_map, semantic_root),
        "candidate commit is newer than the package response cutoff",
        "candidate commit after cutoff",
    )
    missing_candidate_time_map = json.loads(json.dumps(pre_bundle_map))
    missing_candidate_time = response_value(missing_candidate_time_map["paths"], "candidate-commit")
    del missing_candidate_time["committed_at"]
    replace_json_response(missing_candidate_time_map["paths"], "candidate-commit", missing_candidate_time)
    expect_failure(lambda: validate_package_response_semantics(missing_candidate_time_map, semantic_root), "candidate committed_at missing")
    early_github_review_map = json.loads(json.dumps(github_review_map))
    early_github_review = response_value(early_github_review_map["review"], "github-reviews")[0]
    early_github_review["submitted_at"] = "2026-08-29T23:29:59Z"
    replace_json_response(early_github_review_map["review"], "github-reviews", [early_github_review])
    expect_failure_message(
        lambda: validate_package_response_semantics(early_github_review_map, semantic_root),
        "GitHub review[0] is outside the candidate/cutoff interval",
        "GitHub review before candidate",
    )
    early_current_comment_map = json.loads(json.dumps(github_review_map))
    early_current_threads = response_value(early_current_comment_map["discussion"], "review-threads")
    early_current_comment = early_current_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]
    early_current_comment["createdAt"] = "2026-08-29T23:29:59Z"
    early_current_comment["updatedAt"] = "2026-08-29T23:29:59Z"
    replace_json_response(early_current_comment_map["discussion"], "review-threads", early_current_threads)
    expect_failure_message(
        lambda: validate_package_response_semantics(early_current_comment_map, semantic_root),
        "current review comment predates the candidate: 0:0",
        "current review comment before candidate",
    )
    outdated_comment_map = json.loads(json.dumps(github_review_map))
    outdated_threads = response_value(outdated_comment_map["discussion"], "review-threads")
    outdated_thread = outdated_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]
    outdated_thread["isOutdated"] = True
    outdated_comment = outdated_thread["comments"]["nodes"][0]
    outdated_comment["createdAt"] = "2026-08-29T23:00:00Z"
    outdated_comment["updatedAt"] = "2026-08-29T23:00:00Z"
    outdated_comment["outdated"] = True
    outdated_comment["commit"]["oid"] = "d" * 40
    replace_json_response(outdated_comment_map["discussion"], "review-threads", outdated_threads)
    validate_package_response_semantics(outdated_comment_map, semantic_root)
    equal_workflow_time_map = json.loads(json.dumps(pre_bundle_map))
    equal_workflow_runs = response_value(equal_workflow_time_map["checks"], "workflow-runs")
    for workflow_run in equal_workflow_runs["workflow_runs"]:
        workflow_run["created_at"] = "2026-08-29T23:50:00Z"
        workflow_run["run_started_at"] = "2026-08-29T23:50:00Z"
        workflow_run["updated_at"] = "2026-08-29T23:50:00Z"
    replace_json_response(equal_workflow_time_map["checks"], "workflow-runs", equal_workflow_runs)
    validate_package_response_semantics(equal_workflow_time_map, semantic_root)
    missing_workflow_time_map = json.loads(json.dumps(pre_bundle_map))
    missing_workflow_runs = response_value(missing_workflow_time_map["checks"], "workflow-runs")
    del missing_workflow_runs["workflow_runs"][0]["created_at"]
    replace_json_response(missing_workflow_time_map["checks"], "workflow-runs", missing_workflow_runs)
    expect_failure(lambda: validate_package_response_semantics(missing_workflow_time_map, semantic_root), "workflow run created_at missing")
    reversed_workflow_time_map = json.loads(json.dumps(pre_bundle_map))
    reversed_workflow_runs = response_value(reversed_workflow_time_map["checks"], "workflow-runs")
    reversed_workflow_runs["workflow_runs"][0]["created_at"] = "2026-08-29T23:51:00Z"
    replace_json_response(reversed_workflow_time_map["checks"], "workflow-runs", reversed_workflow_runs)
    expect_failure_message(
        lambda: validate_package_response_semantics(reversed_workflow_time_map, semantic_root),
        "workflow-run[0] timestamps are outside the candidate/cutoff interval",
        "workflow run timestamps reversed",
    )
    expect_failure(
        lambda: validate_package_response_semantics(pre_bundle_map, semantic_root, "2026-08-29T23:59:59Z"),
        "explicit package cutoff",
    )
    early_agent_map = json.loads(json.dumps(pre_bundle_map))
    early_agent_reviews = response_value(early_agent_map["review"], "agent-reviews")
    early_agent_reviews["reviews"][0]["started_at"] = "2026-08-29T23:29:59Z"
    replace_json_response(early_agent_map["review"], "agent-reviews", early_agent_reviews)
    expect_failure_message(
        lambda: validate_package_response_semantics(early_agent_map, semantic_root),
        "agent review[0] timestamps are outside the candidate/cutoff interval",
        "agent review before candidate",
    )
    late_check_map = json.loads(json.dumps(pre_bundle_map))
    late_checks = response_value(late_check_map["checks"], "check-runs")
    late_checks["check_runs"][0]["completed_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(late_check_map["checks"], "check-runs", late_checks)
    expect_failure_message(
        lambda: validate_package_response_semantics(late_check_map, semantic_root),
        "check-run[0] timestamps are outside the candidate/cutoff interval",
        "check run after cutoff",
    )
    late_runner_map = json.loads(json.dumps(pre_bundle_map))
    late_runner = response_value(late_runner_map["runner"], "runner-provenance")
    late_runner["executions"][0]["completed_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(late_runner_map["runner"], "runner-provenance", late_runner)
    expect_failure_message(
        lambda: validate_package_response_semantics(late_runner_map, semantic_root),
        "runner execution[0] timestamps are outside the candidate/cutoff interval",
        "runner execution after cutoff",
    )
    late_job_map = json.loads(json.dumps(pre_bundle_map))
    late_jobs = response_value(late_job_map["checks"], "workflow-jobs")
    late_jobs["jobs"][0]["completed_at"] = "2026-08-30T00:00:01Z"
    replace_json_response(late_job_map["checks"], "workflow-jobs", late_jobs)
    expect_failure_message(
        lambda: validate_package_response_semantics(late_job_map, semantic_root),
        "workflow job[0] timestamps are outside the candidate/cutoff interval",
        "workflow job after cutoff",
    )
    for count_field in ("p0", "p1", "p2"):
        boolean_agent_map = json.loads(json.dumps(pre_bundle_map))
        boolean_agent_reviews = response_value(boolean_agent_map["review"], "agent-reviews")
        boolean_agent_reviews["reviews"][0][count_field] = False
        replace_json_response(boolean_agent_map["review"], "agent-reviews", boolean_agent_reviews)
        expect_failure_message(
            lambda candidate_map=boolean_agent_map: validate_package_response_semantics(candidate_map, semantic_root),
            f"agent review[0].{count_field} must be an integer",
            f"boolean agent review {count_field}",
        )
    boolean_approval_map = json.loads(json.dumps(pre_bundle_map))
    boolean_approval_protection = response_value(boolean_approval_map["control"], "branch-protection")
    boolean_approval_protection["required_pull_request_reviews"]["required_approving_review_count"] = False
    replace_json_response(boolean_approval_map["control"], "branch-protection", boolean_approval_protection)
    expect_failure_message(
        lambda: validate_package_response_semantics(boolean_approval_map, semantic_root),
        "required approving review count must be an integer",
        "boolean required approval count",
    )
    boolean_pull_comments_map = json.loads(json.dumps(pre_bundle_map))
    boolean_pull = response_value(boolean_pull_comments_map["pr"], "pull")
    boolean_pull["comments"] = False
    replace_json_response(boolean_pull_comments_map["pr"], "pull", boolean_pull)
    expect_failure_message(
        lambda: validate_package_response_semantics(boolean_pull_comments_map, semantic_root),
        "pull comment count must be an integer",
        "boolean pull comment count",
    )
    boolean_review_user_map = json.loads(json.dumps(github_review_map))
    boolean_review_user = response_value(boolean_review_user_map["review"], "github-reviews")[0]
    boolean_review_user["user"]["id"] = True
    replace_json_response(boolean_review_user_map["review"], "github-reviews", [boolean_review_user])
    expect_failure_message(
        lambda: validate_package_response_semantics(boolean_review_user_map, semantic_root),
        "GitHub review[0] author id must be an integer",
        "boolean GitHub review author id",
    )
    boolean_comment_author_map = json.loads(json.dumps(github_review_map))
    boolean_comment_author_threads = response_value(boolean_comment_author_map["discussion"], "review-threads")
    boolean_comment_author_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]["author"]["databaseId"] = True
    replace_json_response(boolean_comment_author_map["discussion"], "review-threads", boolean_comment_author_threads)
    expect_failure_message(
        lambda: validate_package_response_semantics(boolean_comment_author_map, semantic_root),
        "review comment author database id: 0:0 must be an integer",
        "boolean review comment author database id",
    )
    boolean_workflow_run_map = json.loads(json.dumps(pre_bundle_map))
    boolean_workflow_runs = response_value(boolean_workflow_run_map["checks"], "workflow-runs")
    boolean_workflow_runs["workflow_runs"][0]["id"] = True
    replace_json_response(boolean_workflow_run_map["checks"], "workflow-runs", boolean_workflow_runs)
    expect_failure_message(
        lambda: validate_package_response_semantics(boolean_workflow_run_map, semantic_root),
        "workflow-runs.workflow_runs[0].id must be an integer",
        "boolean workflow run id",
    )
    boolean_workflow_job_map = json.loads(json.dumps(pre_bundle_map))
    boolean_workflow_jobs = response_value(boolean_workflow_job_map["checks"], "workflow-jobs")
    boolean_workflow_jobs["jobs"][0]["job_id"] = True
    replace_json_response(boolean_workflow_job_map["checks"], "workflow-jobs", boolean_workflow_jobs)
    expect_failure_message(
        lambda: validate_package_response_semantics(boolean_workflow_job_map, semantic_root),
        "workflow-jobs.jobs[0].job_id must be an integer",
        "boolean workflow job id",
    )
    stale_github_review_map = dict(github_review_map)
    stale_review = {**github_review_fixture, "commit_id": "a" * 40}
    stale_github_review_map["review"] = sample_bundle("review", {"agent-reviews": agent_reviews_fixture, "github-reviews": [stale_review]})
    expect_failure(lambda: validate_package_response_semantics(stale_github_review_map, semantic_root), "stale GitHub review candidate")
    unresolved_thread_map = dict(github_review_map)
    unresolved_threads = json.loads(json.dumps(current_threads))
    unresolved_threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["isResolved"] = False
    unresolved_thread_map["discussion"] = sample_bundle("discussion", {"issue-comments": [], "review-threads": unresolved_threads})
    expect_failure(lambda: validate_package_response_semantics(unresolved_thread_map, semantic_root), "unresolved review thread")
    second_collaborator_map = dict(pre_bundle_map)
    second_collaborator_map["identity"] = sample_bundle(
        "identity",
        {
            "collaborators": [
                {
                    "id": OWNER_GITHUB_ID,
                    "login": "ZhangIvan",
                    "role_name": "admin",
                    "permissions": {"admin": True, "maintain": True, "push": True, "triage": True, "pull": True},
                },
                {
                    "id": 999,
                    "login": "unexpected-maintainer",
                    "role_name": "admin",
                    "permissions": {"admin": True, "maintain": True, "push": True, "triage": True, "pull": True},
                },
            ],
            "owner-identity": {"id": OWNER_GITHUB_ID, "login": "ZhangIvan", "type": "User"},
        },
    )
    expect_failure(lambda: validate_package_response_semantics(second_collaborator_map, semantic_root), "unexpected second collaborator")
    auto_merge_map = dict(pre_bundle_map)
    auto_merge_settings = {**repository_settings_fixture, "allow_auto_merge": True}
    auto_merge_map["control"] = sample_bundle("control", {**control_fixture_values, "repository-settings": auto_merge_settings})
    expect_failure(lambda: validate_package_response_semantics(auto_merge_map, semantic_root), "repository auto-merge enabled")
    bypass_ruleset_map = dict(pre_bundle_map)
    bypass_ruleset = {
        "id": 1,
        "name": "unsafe-bypass",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [{"actor_type": "RepositoryRole", "actor_id": 5}],
        "conditions": {},
        "rules": [],
    }
    bypass_ruleset_map["control"] = sample_bundle("control", {**control_fixture_values, "rulesets": [bypass_ruleset]})
    expect_failure(lambda: validate_package_response_semantics(bypass_ruleset_map, semantic_root), "ruleset bypass actor")
    empty_policy_ruleset = {**bypass_ruleset, "name": "audited-empty-policy", "bypass_actors": []}
    empty_policy_ruleset_map = dict(pre_bundle_map)
    empty_policy_ruleset_map["control"] = sample_bundle(
        "control",
        {**control_fixture_values, "rulesets": [empty_policy_ruleset]},
    )
    validate_package_response_semantics(empty_policy_ruleset_map, semantic_root)
    second_empty_policy_ruleset = {**empty_policy_ruleset, "id": 2, "name": "second-audited-empty-policy"}
    ordered_rulesets_map = dict(pre_bundle_map)
    ordered_rulesets_map["control"] = sample_bundle(
        "control",
        {**control_fixture_values, "rulesets": [empty_policy_ruleset, second_empty_policy_ruleset]},
    )
    validate_package_response_semantics(ordered_rulesets_map, semantic_root)
    reversed_rulesets_map = json.loads(json.dumps(ordered_rulesets_map))
    reversed_rulesets = response_value(reversed_rulesets_map["control"], "rulesets")
    reversed_rulesets.reverse()
    replace_json_response(reversed_rulesets_map["control"], "rulesets", reversed_rulesets)
    validate_package_response_semantics(reversed_rulesets_map, semantic_root)
    duplicate_rulesets_map = json.loads(json.dumps(ordered_rulesets_map))
    duplicate_rulesets = response_value(duplicate_rulesets_map["control"], "rulesets")
    duplicate_rulesets[1]["id"] = duplicate_rulesets[0]["id"]
    replace_json_response(duplicate_rulesets_map["control"], "rulesets", duplicate_rulesets)
    expect_failure_message(
        lambda: validate_package_response_semantics(duplicate_rulesets_map, semantic_root),
        "rulesets contains a duplicate stable unique key",
        "duplicate ruleset id",
    )
    for policy_field, policy_value in (
        ("conditions", {"ref_name": {"include": ["refs/heads/main"], "exclude": []}}),
        ("rules", [{"type": "required_status_checks"}]),
    ):
        unsupported_ruleset_map = dict(pre_bundle_map)
        unsupported_ruleset = json.loads(json.dumps(empty_policy_ruleset))
        unsupported_ruleset[policy_field] = policy_value
        unsupported_ruleset_map["control"] = sample_bundle(
            "control",
            {**control_fixture_values, "rulesets": [unsupported_ruleset]},
        )
        expect_failure_message(
            lambda candidate_map=unsupported_ruleset_map: validate_package_response_semantics(candidate_map, semantic_root),
            "contains unsupported non-empty policy details",
            f"unsupported non-empty ruleset {policy_field}",
        )
    disabled_security_map = dict(pre_bundle_map)
    disabled_security = json.loads(json.dumps(security_settings_fixture))
    disabled_security["security_and_analysis"]["secret_scanning_push_protection"]["status"] = "disabled"
    disabled_security_map["security"] = sample_bundle("security", {"security-settings": disabled_security})
    expect_failure(lambda: validate_package_response_semantics(disabled_security_map, semantic_root), "disabled push protection")
    omitted_action_map = dict(pre_bundle_map)
    omitted_action_pins = {**action_pins_fixture, "occurrences": action_occurrences_fixture[:-1]}
    omitted_action_map["control"] = sample_bundle("control", {**control_fixture_values, "action-pins": omitted_action_pins})
    expect_failure(lambda: validate_package_response_semantics(omitted_action_map, semantic_root), "omitted action occurrence")

    for validator_field, invalid_value in (
        ("candidate_head", "e" * 40),
        ("candidate_tree", "e" * 40),
        ("path", "scripts/other.py"),
        ("mode", "100755"),
        ("type", "tree"),
        ("blob_sha1", "e" * 40),
        ("content_sha256", "e" * 64),
    ):
        invalid_validator_map = dict(pre_bundle_map)
        invalid_validator_source = {**validator_source_fixture, validator_field: invalid_value}
        invalid_validator_map["control"] = sample_bundle(
            "control",
            {**control_fixture_values, "validator-source": invalid_validator_source},
        )
        expect_failure(
            lambda candidate_map=invalid_validator_map: validate_package_response_semantics(candidate_map, semantic_root),
            f"validator source {validator_field} mismatch",
        )
    missing_validator_map = dict(pre_bundle_map)
    missing_validator_source = dict(validator_source_fixture)
    missing_validator_source.pop("content_sha256")
    missing_validator_map["control"] = sample_bundle(
        "control",
        {**control_fixture_values, "validator-source": missing_validator_source},
    )
    expect_failure(lambda: validate_package_response_semantics(missing_validator_map, semantic_root), "validator source missing field")
    escaped_literal_source = ('secret = "ghp_' + r'\u0041' + ("A" * 35) + '"\n').encode("ascii")
    encoded_secret_literal = base64.b64encode(("ghp_" + "A" * 36).encode("ascii")).decode("ascii")
    base64_literal_source = f'secret = "{encoded_secret_literal}"\n'.encode("ascii")
    for source_label, source_bytes in (
        ("invalid UTF-8", b"\xff"),
        ("embedded secret", ("ghp_" + "A" * 36).encode("ascii")),
        ("escaped literal secret", escaped_literal_source),
        ("base64 literal secret", base64_literal_source),
    ):
        invalid_source_map = dict(pre_bundle_map)
        invalid_source_fixture = {
            **validator_source_fixture,
            "blob_sha1": git_blob_sha1(source_bytes),
            "content_base64": base64.b64encode(source_bytes).decode("ascii"),
            "content_sha256": hashlib.sha256(source_bytes).hexdigest(),
        }
        invalid_source_map["control"] = sample_bundle(
            "control",
            {**control_fixture_values, "validator-source": invalid_source_fixture},
        )
        expect_failure(
            lambda candidate_map=invalid_source_map: validate_package_response_semantics(candidate_map, semantic_root),
            f"validator source {source_label}",
        )
    expect_failure(
        lambda: scan_python_literal_secrets("x = 1\n" * 30_000, "excessive-token validator source"),
        "validator source token resource limit",
    )
    validator_tree_mismatch_map = dict(pre_bundle_map)
    validator_tree_mismatch_paths = {
        "candidate-commit": {"object_type": "commit", "commit": "b" * 40, "tree": "c" * 40, "committed_at": "2026-08-29T23:30:00Z"},
        "candidate-tree": json.loads(json.dumps(candidate_tree_fixture)),
        "pull-files": json.loads(json.dumps(response_value(pre_bundle_map["paths"], "pull-files"))),
    }
    validator_tree_entry_fixture = next(
        item for item in validator_tree_mismatch_paths["candidate-tree"]["tree"]
        if item["path"] == VALIDATOR_PATH.as_posix()
    )
    validator_tree_entry_fixture["sha"] = "e" * 40
    validator_pull_file_fixture = next(
        item for item in validator_tree_mismatch_paths["pull-files"]
        if item["filename"] == VALIDATOR_PATH.as_posix()
    )
    validator_pull_file_fixture["sha"] = "e" * 40
    validator_tree_mismatch_map["paths"] = sample_bundle("paths", validator_tree_mismatch_paths)
    expect_failure(
        lambda: validate_package_response_semantics(validator_tree_mismatch_map, semantic_root),
        "validator source candidate-tree entry mismatch",
    )
    for workflow_path_probe in (
        ".github/workflows/hidden.yml",
        ".github/workflows/nested/hidden.yml",
        ".github/workflows/hidden.yaml",
        ".github/workflows/nested/hidden.yaml",
    ):
        extra_workflow_map = dict(pre_bundle_map)
        extra_workflow_paths = {
            "candidate-commit": {"object_type": "commit", "commit": "b" * 40, "tree": "c" * 40, "committed_at": "2026-08-29T23:30:00Z"},
            "candidate-tree": json.loads(json.dumps(candidate_tree_fixture)),
            "pull-files": json.loads(json.dumps(response_value(pre_bundle_map["paths"], "pull-files"))),
        }
        extra_workflow_paths["candidate-tree"]["tree"].append(
            {"path": workflow_path_probe, "mode": "100644", "type": "blob", "sha": "e" * 40}
        )
        extra_workflow_map["paths"] = sample_bundle("paths", extra_workflow_paths)
        expect_failure(
            lambda candidate_map=extra_workflow_map: validate_package_response_semantics(candidate_map, semantic_root),
            f"unreviewed candidate workflow {workflow_path_probe}",
        )
    for path_label, workflow_path_probe in (
        ("dot segment", ".github/workflows/./evil.yml"),
        ("dotdot segment", ".github/workflows/../evil.yml"),
        ("NUL", ".github/workflows/evil\x00.yml"),
        ("NFD", ".github/workflows/e\u0301.yml"),
    ):
        invalid_path_map = json.loads(json.dumps(pre_bundle_map))
        invalid_path_tree = response_value(invalid_path_map["paths"], "candidate-tree")
        invalid_path_tree["tree"].append(
            {"path": workflow_path_probe, "mode": "100644", "type": "blob", "sha": "e" * 40}
        )
        expect_failure(
            lambda candidate_map=invalid_path_map, candidate_tree=invalid_path_tree: (
                replace_json_response(candidate_map["paths"], "candidate-tree", candidate_tree),
                validate_package_response_semantics(candidate_map, semantic_root),
            ),
            f"candidate workflow path {path_label}",
        )
    for entry_label, workflow_entry in (
        ("tree type", {"path": ".github/workflows/tree.yml", "mode": "040000", "type": "tree", "sha": "e" * 40}),
        ("symlink mode", {"path": ".github/workflows/link.yml", "mode": "120000", "type": "blob", "sha": "e" * 40}),
        ("gitlink commit type", {"path": ".github/workflows/gitlink.yml", "mode": "160000", "type": "commit", "sha": "e" * 40}),
    ):
        invalid_entry_map = json.loads(json.dumps(pre_bundle_map))
        invalid_entry_tree = response_value(invalid_entry_map["paths"], "candidate-tree")
        invalid_entry_tree["tree"].append(workflow_entry)
        replace_json_response(invalid_entry_map["paths"], "candidate-tree", invalid_entry_tree)
        expect_failure(
            lambda candidate_map=invalid_entry_map: validate_package_response_semantics(candidate_map, semantic_root),
            f"candidate workflow entry {entry_label}",
        )
    ignored_workflow_map = json.loads(json.dumps(pre_bundle_map))
    ignored_workflow_tree = response_value(ignored_workflow_map["paths"], "candidate-tree")
    ignored_workflow_tree["tree"].extend(
        [
            {"path": ".github/workflows/evil.YML", "mode": "100644", "type": "blob", "sha": "e" * 40},
            {"path": ".github/workflows-evil/evil.yml", "mode": "100644", "type": "blob", "sha": "e" * 40},
        ]
    )
    ignored_workflow_tree["tree"].sort(key=lambda item: utf16_sort_key(item["path"]))
    replace_json_response(ignored_workflow_map["paths"], "candidate-tree", ignored_workflow_tree)
    validate_package_response_semantics(ignored_workflow_map, semantic_root)
    executable_workflow_map = dict(pre_bundle_map)
    executable_workflow_paths = {
        "candidate-commit": {"object_type": "commit", "commit": "b" * 40, "tree": "c" * 40, "committed_at": "2026-08-29T23:30:00Z"},
        "candidate-tree": json.loads(json.dumps(candidate_tree_fixture)),
        "pull-files": json.loads(json.dumps(response_value(pre_bundle_map["paths"], "pull-files"))),
    }
    next(
        item for item in executable_workflow_paths["candidate-tree"]["tree"]
        if item["path"] == ".github/workflows/rust.yml"
    )["mode"] = "100755"
    executable_workflow_map["paths"] = sample_bundle("paths", executable_workflow_paths)
    expect_failure(
        lambda: validate_package_response_semantics(executable_workflow_map, semantic_root),
        "executable candidate workflow",
    )
    for inventory_label, workflow_records in (
        ("missing", workflow_blobs_fixture["workflows"][:-1]),
        ("duplicate", [*workflow_blobs_fixture["workflows"], workflow_blobs_fixture["workflows"][0]]),
    ):
        invalid_inventory_map = dict(pre_bundle_map)
        invalid_inventory = {**workflow_blobs_fixture, "workflows": json.loads(json.dumps(workflow_records))}
        invalid_inventory_map["control"] = sample_bundle(
            "control",
            {**control_fixture_values, "workflow-blobs": invalid_inventory},
        )
        expect_failure(
            lambda candidate_map=invalid_inventory_map: validate_package_response_semantics(candidate_map, semantic_root),
            f"{inventory_label} workflow evidence inventory",
        )

    def semantic_map_with_design_workflow(design_content: bytes) -> dict[str, dict[str, Any]]:
        mutated_map = dict(pre_bundle_map)
        mutated_workflow_blobs = json.loads(json.dumps(workflow_blobs_fixture))
        mutated_workflow = next(item for item in mutated_workflow_blobs["workflows"] if item["path"] == ".github/workflows/design-contracts.yml")
        mutated_blob = git_blob_sha1(design_content)
        mutated_workflow["content_base64"] = base64.b64encode(design_content).decode("ascii")
        mutated_workflow["content_sha256"] = hashlib.sha256(design_content).hexdigest()
        mutated_workflow["blob"] = mutated_blob
        mutated_tree = json.loads(json.dumps(candidate_tree_fixture))
        next(item for item in mutated_tree["tree"] if item["path"] == ".github/workflows/design-contracts.yml")["sha"] = mutated_blob
        mutated_files = json.loads(json.dumps(bootstrap_files))
        next(item for item in mutated_files if item["filename"] == ".github/workflows/design-contracts.yml")["sha"] = mutated_blob
        mutated_map["paths"] = sample_bundle(
            "paths",
            {
                "candidate-commit": {"object_type": "commit", "commit": "b" * 40, "tree": "c" * 40, "committed_at": "2026-08-29T23:30:00Z"},
                "candidate-tree": mutated_tree,
                "pull-files": mutated_files,
            },
        )
        mutated_map["control"] = sample_bundle("control", {**control_fixture_values, "workflow-blobs": mutated_workflow_blobs})
        return mutated_map

    def semantic_map_with_rust_workflow(rust_content: bytes) -> dict[str, dict[str, Any]]:
        mutated_map = dict(pre_bundle_map)
        mutated_workflow_blobs = json.loads(json.dumps(workflow_blobs_fixture))
        mutated_workflow = next(item for item in mutated_workflow_blobs["workflows"] if item["path"] == ".github/workflows/rust.yml")
        mutated_blob = git_blob_sha1(rust_content)
        mutated_workflow["content_base64"] = base64.b64encode(rust_content).decode("ascii")
        mutated_workflow["content_sha256"] = hashlib.sha256(rust_content).hexdigest()
        mutated_workflow["blob"] = mutated_blob
        mutated_tree = json.loads(json.dumps(candidate_tree_fixture))
        next(item for item in mutated_tree["tree"] if item["path"] == ".github/workflows/rust.yml")["sha"] = mutated_blob
        mutated_files = json.loads(json.dumps(bootstrap_files))
        next(item for item in mutated_files if item["filename"] == ".github/workflows/rust.yml")["sha"] = mutated_blob
        mutated_map["paths"] = sample_bundle(
            "paths",
            {
                "candidate-commit": {"object_type": "commit", "commit": "b" * 40, "tree": "c" * 40, "committed_at": "2026-08-29T23:30:00Z"},
                "candidate-tree": mutated_tree,
                "pull-files": mutated_files,
            },
        )
        mutated_map["control"] = sample_bundle("control", {**control_fixture_values, "workflow-blobs": mutated_workflow_blobs})
        return mutated_map

    def validate_with_mutated_workflow_hash(
        design_content: bytes,
        run_hash_overrides: dict[str, str] | None = None,
    ) -> None:
        candidate_map = semantic_map_with_design_workflow(design_content)
        with patch.dict(
            EXPECTED_WORKFLOW_SHA256,
            {".github/workflows/design-contracts.yml": hashlib.sha256(design_content).hexdigest()},
        ):
            if run_hash_overrides is None:
                validate_package_response_semantics(candidate_map, semantic_root)
            else:
                with patch.dict(EXPECTED_RUN_SHA256, run_hash_overrides):
                    validate_package_response_semantics(candidate_map, semantic_root)

    def validate_with_mutated_rust_hash(rust_content: bytes, run_hash_overrides: dict[str, str]) -> None:
        candidate_map = semantic_map_with_rust_workflow(rust_content)
        with patch.dict(EXPECTED_WORKFLOW_SHA256, {".github/workflows/rust.yml": hashlib.sha256(rust_content).hexdigest()}):
            with patch.dict(EXPECTED_RUN_SHA256, run_hash_overrides):
                validate_package_response_semantics(candidate_map, semantic_root)

    original_design_content = workflow_fixture_contents[".github/workflows/design-contracts.yml"]
    unsafe_content = original_design_content.replace(
        b"permissions:\n  contents: read\n",
        b"permissions: write-all\n",
        1,
    )
    unsafe_permissions_map = semantic_map_with_design_workflow(unsafe_content)
    expect_failure(lambda: validate_package_response_semantics(unsafe_permissions_map, semantic_root), "write-all workflow permissions")
    duplicate_content = original_design_content.replace(
        b"permissions:\n  contents: read\n",
        b"permissions:\n  contents: read\npermissions:\n  contents: read\n",
        1,
    )
    duplicate_yaml_map = semantic_map_with_design_workflow(duplicate_content)
    expect_failure(lambda: validate_package_response_semantics(duplicate_yaml_map, semantic_root), "duplicate workflow YAML key")
    conditional_validator_content = original_design_content.replace(
        b"      - name: Validate governance state\n        run:",
        b"      - name: Validate governance state\n        if: false\n        run:",
        1,
    )
    conditional_validator_map = semantic_map_with_design_workflow(conditional_validator_content)
    expect_failure(lambda: validate_package_response_semantics(conditional_validator_map, semantic_root), "conditional governance validator step")
    no_pull_trigger_content = original_design_content.replace(b"  pull_request:\n", b"", 1)
    no_pull_trigger_map = semantic_map_with_design_workflow(no_pull_trigger_content)
    expect_failure(lambda: validate_package_response_semantics(no_pull_trigger_map, semantic_root), "missing pull_request workflow trigger")
    no_op_command_content = original_design_content.replace(
        b"        run: python scripts/validate_governance_state.py --self-test\n",
        b"        run: 'true'\n",
        1,
    )
    no_op_command_map = semantic_map_with_design_workflow(no_op_command_content)
    expect_failure(lambda: validate_package_response_semantics(no_op_command_map, semantic_root), "no-op governance validator command")
    uses_and_run_content = original_design_content.replace(
        b"      - uses: actions/checkout@",
        b"      - run: true\n        uses: actions/checkout@",
        1,
    )
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(uses_and_run_content),
        "exactly one of uses/run",
        "workflow action step with uses and run",
    )
    neither_uses_nor_run_content = original_design_content.replace(
        b"      - uses: actions/checkout@",
        b"      - ignored-reference: actions/checkout@",
        1,
    )
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(neither_uses_nor_run_content),
        "exactly one of uses/run",
        "workflow step with neither uses nor run",
    )
    null_uses_content = re.sub(
        rb"uses: actions/checkout@[0-9a-f]{40}[^\n]*",
        b"uses:",
        original_design_content,
        count=1,
    )
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(null_uses_content),
        "action reference must be a scalar string",
        "workflow action step with null uses",
    )
    bool_uses_content = re.sub(
        rb"uses: actions/checkout@[0-9a-f]{40}[^\n]*",
        b"uses: true",
        original_design_content,
        count=1,
    )
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(bool_uses_content),
        "action reference must be a scalar string",
        "workflow action step with boolean uses",
    )
    for typed_label, typed_scalar, expected_reason in (
        ("boolean", b"true", "non-empty string"),
        ("null", b"", "non-empty string"),
        ("list", b"[true]", "non-empty string"),
        ("empty multiline", b"|\n", "non-empty string"),
    ):
        typed_variant = original_design_content.replace(
            b"python scripts/validate_governance_state.py --self-test",
            typed_scalar,
            1,
        )
        expect_failure_message(
            lambda content=typed_variant: validate_with_mutated_workflow_hash(content),
            expected_reason,
            f"workflow validator {typed_label} value",
        )
    validator_run_key = ".github/workflows/design-contracts.yml|design-contracts|7|Validate governance state"
    for no_op_label, no_op_scalar in (
        ("comment-only", b"|\n          # no operation\n"),
        ("colon", b"':'"),
        ("quoted true", b"'true'"),
        ("exit zero", b"'exit 0'"),
        ("prefixed true", b"'true; python scripts/validate_governance_state.py --self-test'"),
    ):
        no_op_variant = original_design_content.replace(
            b"python scripts/validate_governance_state.py --self-test",
            no_op_scalar,
            1,
        )
        no_op_document = yaml.load(no_op_variant.decode("utf-8"), Loader=UniqueKeySafeLoader)
        no_op_run = no_op_document["jobs"]["design-contracts"]["steps"][6]["run"]
        expect_failure_message(
            lambda content=no_op_variant, run=no_op_run: validate_with_mutated_workflow_hash(
                content,
                {validator_run_key: hashlib.sha256(run.encode("utf-8")).hexdigest()},
            ),
            "governance validator command drifted",
            f"workflow validator {no_op_label} no-op",
        )
    wrong_marker_content = original_design_content.replace(b"context=contract-fixtures", b"context=wrong", 1)
    wrong_marker_document = yaml.load(wrong_marker_content.decode("utf-8"), Loader=UniqueKeySafeLoader)
    wrong_marker_run = wrong_marker_document["jobs"]["design-contracts"]["steps"][2]["run"]
    marker_run_key = ".github/workflows/design-contracts.yml|design-contracts|3|Record immutable execution evidence"
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(
            wrong_marker_content,
            {marker_run_key: hashlib.sha256(wrong_marker_run.encode("utf-8")).hexdigest()},
        ),
        "marker context mismatch",
        "workflow marker context drift",
    )
    for marker_label, marker_content, marker_reason in (
        ("duplicate", original_design_content.replace(b"GVN_EXECUTION", b"GVN_EXECUTION GVN_EXECUTION", 1), "marker count mismatch"),
        ("missing field", original_design_content.replace(b"parents=%s", b"parent=%s", 1), "marker field missing"),
    ):
        marker_document = yaml.load(marker_content.decode("utf-8"), Loader=UniqueKeySafeLoader)
        marker_run = marker_document["jobs"]["design-contracts"]["steps"][2]["run"]
        expect_failure_message(
            lambda content=marker_content, run=marker_run: validate_with_mutated_workflow_hash(
                content,
                {marker_run_key: hashlib.sha256(run.encode("utf-8")).hexdigest()},
            ),
            marker_reason,
            f"workflow marker {marker_label}",
        )
    shallow_checkout_content = original_design_content.replace(b"          fetch-depth: 0\n", b"          fetch-depth: 1\n", 1)
    shallow_checkout_map = semantic_map_with_design_workflow(shallow_checkout_content)
    expect_failure(lambda: validate_package_response_semantics(shallow_checkout_map, semantic_root), "shallow workflow checkout")
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(shallow_checkout_content),
        "checkout must fetch full history",
        "targeted shallow workflow checkout",
    )
    wrong_action_sha_content = re.sub(
        rb"actions/checkout@[0-9a-f]{40}",
        b"actions/checkout@" + b"e" * 40,
        original_design_content,
        count=1,
    )
    expect_failure_message(
        lambda: validate_with_mutated_workflow_hash(wrong_action_sha_content),
        "frozen action/SHA allowlist",
        "targeted wrong action SHA",
    )
    original_rust_content = workflow_fixture_contents[".github/workflows/rust.yml"]
    unlocked_rust_content = original_rust_content.replace(b"cargo check --locked", b"cargo check", 1)
    unlocked_rust_document = yaml.load(unlocked_rust_content.decode("utf-8"), Loader=UniqueKeySafeLoader)
    unlocked_run = unlocked_rust_document["jobs"]["format-lint"]["steps"][3]["run"]
    unlocked_run_key = ".github/workflows/rust.yml|format-lint|4|Check workspace"
    expect_failure_message(
        lambda: validate_with_mutated_rust_hash(
            unlocked_rust_content,
            {unlocked_run_key: hashlib.sha256(unlocked_run.encode("utf-8")).hexdigest()},
        ),
        "Cargo execution must use --locked",
        "targeted unlocked Cargo command",
    )
    with patch.dict(EXPECTED_RUN_SHA256, {"unexpected|job|1|run": "e" * 64}):
        expect_failure_message(
            lambda: validate_package_response_semantics(pre_bundle_map, semantic_root),
            "run occurrence inventory differs",
            "extra expected workflow run occurrence",
        )
    missing_run_hashes = dict(EXPECTED_RUN_SHA256)
    missing_run_hashes.pop(validator_run_key)
    with patch.dict(EXPECTED_RUN_SHA256, missing_run_hashes, clear=True):
        expect_failure_message(
            lambda: validate_package_response_semantics(pre_bundle_map, semantic_root),
            "run scalar differs",
            "missing expected workflow run occurrence",
        )
    wrong_lock_blob_map = dict(pre_bundle_map)
    wrong_lockfiles = json.loads(json.dumps(toolchain_lockfiles_fixture))
    wrong_lockfiles["files"][0]["blob"] = "0" * 40
    wrong_lock_blob_map["runner"] = sample_bundle(
        "runner",
        {
            "execution-objects": execution_objects_fixture,
            "runner-provenance": runner_provenance_fixture,
            "toolchain-lockfiles": wrong_lockfiles,
        },
    )
    expect_failure(lambda: validate_package_response_semantics(wrong_lock_blob_map, semantic_root), "lockfile Git blob mismatch")
    duplicate_external_map = json.loads(json.dumps(pre_bundle_map))
    duplicate_provenance = response_value(duplicate_external_map["runner"], "runner-provenance")
    duplicate_provenance["executions"][1]["external_id"] = duplicate_provenance["executions"][0]["external_id"]
    replace_json_response(duplicate_external_map["runner"], "runner-provenance", duplicate_provenance)
    expect_failure(lambda: validate_package_response_semantics(duplicate_external_map, semantic_root), "duplicate runner external id")
    shallow_runner_map = json.loads(json.dumps(pre_bundle_map))
    shallow_provenance = response_value(shallow_runner_map["runner"], "runner-provenance")
    shallow_provenance["executions"][0]["shallow"] = True
    replace_json_response(shallow_runner_map["runner"], "runner-provenance", shallow_provenance)
    expect_failure(lambda: validate_package_response_semantics(shallow_runner_map, semantic_root), "shallow runner evidence")
    extra_job_map = json.loads(json.dumps(pre_bundle_map))
    extra_jobs = response_value(extra_job_map["checks"], "workflow-jobs")
    extra_job = json.loads(json.dumps(extra_jobs["jobs"][0]))
    extra_job["job_id"] = 999
    extra_jobs["jobs"].append(extra_job)
    replace_json_response(extra_job_map["checks"], "workflow-jobs", extra_jobs)
    expect_failure(lambda: validate_package_response_semantics(extra_job_map, semantic_root), "unrelated workflow job")
    extra_execution_object_map = json.loads(json.dumps(pre_bundle_map))
    extra_objects = response_value(extra_execution_object_map["runner"], "execution-objects")
    extra_objects["objects"].append({**extra_objects["objects"][0], "context": "unrelated"})
    replace_json_response(extra_execution_object_map["runner"], "execution-objects", extra_objects)
    expect_failure(lambda: validate_package_response_semantics(extra_execution_object_map, semantic_root), "unrelated execution Git object")
    wrong_run_event_map = json.loads(json.dumps(pre_bundle_map))
    wrong_runs = response_value(wrong_run_event_map["checks"], "workflow-runs")
    wrong_runs["workflow_runs"][0]["event"] = "push"
    replace_json_response(wrong_run_event_map["checks"], "workflow-runs", wrong_runs)
    expect_failure(lambda: validate_package_response_semantics(wrong_run_event_map, semantic_root), "wrong workflow run event")
    pre_fixture = {
        "schema": "gvn-pre-attestation-v1",
        "repository": "ZhangIvan/QingYin",
        "pr_number": 19,
        "base_sha": "a" * 40,
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "snapshot_cutoff_utc": "2026-08-30T00:00:00Z",
        "component_digests": component_digests,
    }
    validate_evidence_object(pre_fixture)
    attestation_fixture = {
        "schema": "gvn-attestation-v1",
        "repository": "ZhangIvan/QingYin",
        "pr_number": 19,
        "base_sha": "a" * 40,
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "attestor_login": "ZhangIvan",
        "attestor_id": OWNER_GITHUB_ID,
        "changed_paths_sha256": component_digests[1]["endpoint_bundle_sha256"],
        "pull_body_sha256": hashlib.sha256(pull_body_fixture.encode("utf-8")).hexdigest(),
        "risk_class": "CR3",
        "pre_attestation_sha256": hashlib.sha256(canonical_json_v1(pre_fixture)).hexdigest(),
        "finding_ids": list(RESIDUAL_IDS),
        "accepted_residual_ids": list(RESIDUAL_IDS),
        "checks_status": "VERIFIED",
        "reviews_status": "VERIFIED",
        "trusted_control_status": "VERIFIED",
        "unknowns": [],
        "rollback": "Stop and use a protected recovery PR.",
        "no_production_authorization": True,
    }
    validate_evidence_object(attestation_fixture)
    expect_failure(
        lambda: validate_evidence_object({**attestation_fixture, "attestor_login": "not-owner"}),
        "attestor identity mismatch",
    )
    attestation_comment = {
        "body": canonical_json_v1(attestation_fixture).decode("utf-8"),
        "created_at": "2026-08-30T00:00:01Z",
        "id": 1,
        "node_id": "IC_kwDOAttestation1",
        "updated_at": "2026-08-30T00:00:01Z",
        "user": {"id": OWNER_GITHUB_ID, "login": "ZhangIvan"},
    }
    attestation_bundle = sample_bundle(
        "attestation",
        {
            "attestation-comment": attestation_comment,
            "attestation-payload": attestation_fixture,
        },
    )
    attestation_payload_item = response_item(attestation_bundle, "attestation-payload")
    attestation_payload_item["request"]["body"] = attestation_fixture
    attestation_payload_item["request_canonical_sha256"] = hashlib.sha256(
        canonical_json_v1(attestation_payload_item["request"])
    ).hexdigest()
    validate_evidence_object(attestation_bundle)
    attestation_comment_sidecar = response_item(attestation_bundle, "attestation-comment")["human_body_hashes"]
    require(
        attestation_comment_sidecar[0]["sha256"] == hashlib.sha256(attestation_comment["body"].encode("utf-8")).hexdigest(),
        "attestation comment body hash mismatch",
    )
    tampered_attestation_bundle = json.loads(json.dumps(attestation_bundle))
    tampered_attestation_comment = response_value(tampered_attestation_bundle, "attestation-comment")
    tampered_attestation_comment["body"] += " tampered"
    replace_json_response(
        tampered_attestation_bundle,
        "attestation-comment",
        tampered_attestation_comment,
        rederive_human_body_hashes=False,
    )
    expect_failure(
        lambda: validate_evidence_object(tampered_attestation_bundle),
        "attestation comment body tamper with recomputed endpoint hashes",
    )
    stable_bundles: list[dict[str, Any]] = []
    for component, pre_bundle in zip(PRE_ATTESTATION_COMPONENTS, pre_bundles, strict=True):
        if component == "pr":
            stable_bundles.append(
                sample_bundle(
                    "pr",
                    {
                        "pull": {
                            "auto_merge": None,
                            "base": {"ref": "main", "sha": "a" * 40},
                            "body": pull_body_fixture,
                            "changed_files": len(BOOTSTRAP_STATUS),
                            "comments": 1,
                            "commits": 1,
                            "head": {"ref": pull_head_ref_fixture, "sha": "b" * 40},
                            "id": 19,
                            "locked": False,
                            "mergeable": True,
                            "mergeable_state": "clean",
                            "number": 19,
                            "node_id": "PR_kwDOExample19",
                            "draft": False,
                            "state": "open",
                            "title": pull_title_fixture,
                            "updated_at": "2026-08-30T00:00:01Z",
                        }
                    },
                )
            )
        elif component == "metadata":
            stable_metadata_graphql = json.loads(json.dumps(metadata_graphql))
            stable_metadata_graphql["data"]["repository"]["pullRequest"]["updatedAt"] = "2026-08-30T00:00:01Z"
            stable_bundles.append(sample_bundle("metadata", {"pull-metadata": stable_metadata_graphql}))
        elif component == "discussion":
            stable_bundles.append(
                sample_bundle(
                    "discussion",
                    {
                        "issue-comments": [attestation_comment],
                        "review-threads": threads_graphql,
                    },
                )
            )
        else:
            stable_bundles.append(pre_bundle)
    stable_bundles.append(attestation_bundle)
    stable_digests = [
        {"name": bundle["component"], "endpoint_bundle_sha256": hashlib.sha256(canonical_json_v1(bundle)).hexdigest()}
        for bundle in stable_bundles
    ]
    stable_fixture = {
        "schema": "gvn-manifest-v1",
        "phase": "stable-window-start",
        "repository": "ZhangIvan/QingYin",
        "pr_number": 19,
        "base_sha": "a" * 40,
        "candidate_head": "b" * 40,
        "candidate_tree": "c" * 40,
        "snapshot_cutoff_utc": "2026-08-30T00:00:01Z",
        "component_digests": stable_digests,
        "effective_merge_sha": None,
    }
    validate_evidence_object(stable_fixture)
    expect_failure(
        lambda: validate_evidence_object({**stable_fixture, "component_digests": list(reversed(stable_digests))}),
        "manifest component order",
    )
    package_fixture = {
        "schema": "gvn-evidence-package-v2",
        "phase": "stable-window-start",
        "pre_endpoint_bundles": pre_bundles,
        "snapshot_endpoint_bundles": stable_bundles,
        "pre_attestation": pre_fixture,
        "attestation": attestation_fixture,
        "publication_delta": {
            "schema": "gvn-publication-delta-v1",
            "attestation_comment_id": 1,
            "attestation_comment_created_at": "2026-08-30T00:00:01Z",
            "attestation_comment_updated_at": "2026-08-30T00:00:01Z",
            "pull_updated_at_before": "2026-08-29T23:59:59Z",
            "pull_updated_at_after": "2026-08-30T00:00:01Z",
            "pull_comments_before": 0,
            "pull_comments_after": 1,
        },
        "manifest": stable_fixture,
        "activation_binding": None,
    }
    validate_evidence_object(package_fixture)
    reordered_publication_pre = {
        bundle["component"]: json.loads(json.dumps(bundle)) for bundle in pre_bundles
    }
    reordered_publication_snapshot = {
        bundle["component"]: json.loads(json.dumps(bundle)) for bundle in stable_bundles
    }
    preexisting_comment = json.loads(json.dumps(issue_comment_fixture))
    replace_json_response(
        reordered_publication_pre["discussion"],
        "issue-comments",
        [preexisting_comment],
    )
    replace_json_response(
        reordered_publication_snapshot["discussion"],
        "issue-comments",
        [attestation_comment, preexisting_comment],
    )
    reordered_pre_pull = response_value(reordered_publication_pre["pr"], "pull")
    reordered_pre_pull["comments"] = 1
    replace_json_response(reordered_publication_pre["pr"], "pull", reordered_pre_pull)
    reordered_snapshot_pull = response_value(reordered_publication_snapshot["pr"], "pull")
    reordered_snapshot_pull["comments"] = 2
    replace_json_response(reordered_publication_snapshot["pr"], "pull", reordered_snapshot_pull)
    reordered_delta = {**package_fixture["publication_delta"], "pull_comments_before": 1, "pull_comments_after": 2}
    expect_failure_message(
        lambda: validate_publication_delta_v1(
            reordered_delta,
            reordered_publication_pre,
            reordered_publication_snapshot,
            attestation_fixture,
            "2026-08-30T00:00:00Z",
            "2026-08-30T00:00:01Z",
        ),
        "publication must append exactly the attestation comment",
        "publication delta rejects reordered raw issue-comment sequence",
    )
    expect_failure(
        lambda: validate_evidence_object({**package_fixture, "schema": "gvn-evidence-package-v1"}),
        "retired evidence package v1",
    )
    scan_evidence_secrets(package_fixture)
    alternate_bootstrap_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    alternate_bootstrap_package["pre_attestation"]["base_sha"] = "d" * 40
    expect_failure_message(
        lambda: validate_evidence_package_v2(alternate_bootstrap_package),
        "governance bootstrap base must equal frozen source commit",
        "bootstrap package alternate source base",
    )
    boolean_attestation_id_bundles = json.loads(json.dumps(stable_bundles, ensure_ascii=False))
    boolean_attestation_bundle = next(bundle for bundle in boolean_attestation_id_bundles if bundle["component"] == "attestation")
    boolean_attestation_comment = response_value(boolean_attestation_bundle, "attestation-comment")
    boolean_attestation_comment["id"] = True
    replace_json_response(
        boolean_attestation_bundle,
        "attestation-comment",
        boolean_attestation_comment,
        rederive_human_body_hashes=False,
    )
    boolean_attestation_id_map = {bundle["component"]: bundle for bundle in boolean_attestation_id_bundles}
    expect_failure_message(
        lambda: validate_package_request_bindings(boolean_attestation_id_map, 19, "b" * 40, "c" * 40, None),
        "attestation comment id must be an integer",
        "boolean attestation comment id",
    )
    reordered_evidence_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    reordered_evidence_package["pre_endpoint_bundles"] = list(reversed(reordered_evidence_package["pre_endpoint_bundles"]))
    expect_failure(
        lambda: validate_evidence_object(reordered_evidence_package),
        "evidence component reorder",
    )
    extra_evidence_record_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    extra_evidence_record_package["pre_endpoint_bundles"].append(
        json.loads(json.dumps(extra_evidence_record_package["pre_endpoint_bundles"][0], ensure_ascii=False))
    )
    expect_failure(
        lambda: validate_evidence_object(extra_evidence_record_package),
        "evidence extra component record",
    )
    secret_request_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    secret_request_item = response_item(secret_request_package["pre_endpoint_bundles"][0], "pull")
    secret_request_item["request"]["query"] = [["token", "ghp_" + "A" * 36]]
    secret_request_item["request_canonical_sha256"] = hashlib.sha256(canonical_json_v1(secret_request_item["request"])).hexdigest()
    expect_failure(lambda: scan_evidence_secrets(secret_request_package), "secret in evidence request query")
    secret_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    secret_response = secret_package["snapshot_endpoint_bundles"][0]["responses"][0]
    secret_response["response_body_base64"] = base64.b64encode(("ghp_" + "A" * 36).encode()).decode("ascii")
    expect_failure(lambda: scan_evidence_secrets(secret_package), "secret in evidence response")
    for secret_index, secret_value in enumerate(
        (
            "github_pat_" + "A" * 48,
            "".join(("Authorization", ": ", "token-value-with-at-least-twenty-characters")),
            "".join(("Cookie", ": ", "session=abcdefghijklmnopqrstuvwxyz0123456789")),
            "".join(("xox", "b-", "1234567890-abcdefghijklmnopqrstuvwxyz")),
            "".join(("gl", "pat-", "abcdefghijklmnopqrstuvwxyz012345")),
            "AIza" + "A" * 35,
        )
    ):
        secret_variant = json.loads(json.dumps(package_fixture, ensure_ascii=False))
        secret_variant["activation_binding"] = {"probe": secret_value}
        expect_failure(lambda value=secret_variant: scan_evidence_secrets(value), f"expanded secret pattern[{secret_index}]")
    secret_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(secret_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as secret_zip:
        secret_zip.writestr("job.txt", "Bearer " + "a" * 20)
    secret_zip_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    secret_zip_response = response_item(secret_zip_package["snapshot_endpoint_bundles"][5], "workflow-logs")
    secret_zip_response["response_media_type"] = "application/zip"
    secret_zip_response["response_body_base64"] = base64.b64encode(secret_zip_buffer.getvalue()).decode("ascii")
    expect_failure(lambda: scan_evidence_secrets(secret_zip_package), "secret in evidence ZIP member")
    metadata_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(metadata_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as metadata_zip:
        metadata_zip.comment = ("ghp_" + "A" * 36).encode()
        metadata_zip.writestr("harmless.txt", "harmless")
    metadata_zip_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    metadata_zip_response = response_item(metadata_zip_package["snapshot_endpoint_bundles"][5], "workflow-logs")
    metadata_zip_response["response_media_type"] = "application/zip"
    metadata_zip_response["response_body_base64"] = base64.b64encode(metadata_zip_buffer.getvalue()).decode("ascii")
    expect_failure(lambda: scan_evidence_secrets(metadata_zip_package), "secret in evidence ZIP metadata")

    escaped_json_body = ('{"value":"ghp_' + r'\u0041' + ("A" * 35) + '"}').encode("ascii")
    require_no_evidence_secret(escaped_json_body, "self-test escaped JSON raw body")
    escaped_json_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    escaped_json_response = response_item(escaped_json_package["snapshot_endpoint_bundles"][0], "pull")
    escaped_json_response["response_body_base64"] = base64.b64encode(escaped_json_body).decode("ascii")
    expect_failure(lambda: scan_evidence_secrets(escaped_json_package), "secret in canonicalized escaped JSON response")

    nested_secret_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    nested_secret_response = response_item(nested_secret_package["pre_endpoint_bundles"][0], "pull")
    nested_secret_body = ('{"value":"' + ("ghp_" + "A" * 36) + '"}').encode("ascii")
    nested_secret_response["response_body_base64"] = base64.b64encode(nested_secret_body).decode("ascii")
    activation_nested_secret_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    activation_nested_secret_package["activation_binding"] = {
        "governance_evidence_sequence": [nested_secret_package],
    }
    expect_failure(
        lambda: scan_evidence_secrets(activation_nested_secret_package),
        "secret in activation nested evidence package",
    )

    nested_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(nested_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as nested_zip:
        nested_zip.writestr("nested-secret.txt", "ghp_" + "A" * 36)
    outer_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(outer_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as outer_zip:
        outer_zip.writestr("nested.zip", nested_zip_buffer.getvalue())
    nested_zip_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    nested_zip_response = response_item(nested_zip_package["snapshot_endpoint_bundles"][5], "workflow-logs")
    nested_zip_response["response_media_type"] = "application/zip"
    nested_zip_response["response_body_base64"] = base64.b64encode(outer_zip_buffer.getvalue()).decode("ascii")
    expect_failure(lambda: scan_evidence_secrets(nested_zip_package), "secret in nested evidence ZIP member")

    corrupt_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(corrupt_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as corrupt_zip:
        corrupt_zip.writestr("payload.txt", b"hello world")
    corrupt_zip_bytes = bytearray(corrupt_zip_buffer.getvalue())
    corrupt_name_length = int.from_bytes(corrupt_zip_bytes[26:28], "little")
    corrupt_extra_length = int.from_bytes(corrupt_zip_bytes[28:30], "little")
    corrupt_payload_offset = 30 + corrupt_name_length + corrupt_extra_length
    corrupt_zip_bytes[corrupt_payload_offset] ^= 0xFF
    expect_failure(
        lambda: scan_evidence_payload(bytes(corrupt_zip_bytes), "application/zip", "corrupt-deflate"),
        "corrupt deflate evidence ZIP",
    )
    many_entries_buffer = io.BytesIO()
    with zipfile.ZipFile(many_entries_buffer, "w", compression=zipfile.ZIP_STORED) as many_entries_zip:
        for entry_index in range(1001):
            many_entries_zip.writestr(f"empty-{entry_index}.txt", b"")
    expect_failure(
        lambda: preflight_zip_archive(many_entries_buffer.getvalue(), "self-test too many ZIP members"),
        "ZIP member limit preflight",
    )
    forged_count_zip = bytearray(many_entries_buffer.getvalue())
    forged_eocd_offset = forged_count_zip.rfind(b"PK\x05\x06")
    require(forged_eocd_offset >= 0, "self-test ZIP EOCD missing")
    forged_count_zip[forged_eocd_offset + 8 : forged_eocd_offset + 12] = b"\x01\x00\x01\x00"
    expect_failure(
        lambda: preflight_zip_archive(bytes(forged_count_zip), "self-test forged ZIP member count"),
        "ZIP actual member count preflight",
    )
    require(
        not scan_secret_bytes(Path(__file__).read_bytes()),
        "governance validator source contains a credential-like scanner fixture",
    )

    end_package_fixture = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    end_package_fixture["phase"] = "stable-window-end"
    end_package_fixture["manifest"]["phase"] = "stable-window-end"
    end_package_fixture["manifest"]["snapshot_cutoff_utc"] = "2026-08-30T00:10:01Z"
    validate_evidence_sequence([package_fixture, end_package_fixture])
    reordered_end_package = json.loads(json.dumps(end_package_fixture, ensure_ascii=False))
    reordered_end_checks = next(
        bundle for bundle in reordered_end_package["snapshot_endpoint_bundles"] if bundle["component"] == "checks"
    )
    reordered_end_check_response = response_value(reordered_end_checks, "check-runs")
    reordered_end_check_response["check_runs"].reverse()
    replace_json_response(reordered_end_checks, "check-runs", reordered_end_check_response)
    reordered_end_checks_digest = hashlib.sha256(canonical_json_v1(reordered_end_checks)).hexdigest()
    next(
        item for item in reordered_end_package["manifest"]["component_digests"] if item["name"] == "checks"
    )["endpoint_bundle_sha256"] = reordered_end_checks_digest
    expect_failure_message(
        lambda: validate_evidence_object(reordered_end_package),
        "publication changed forbidden component: checks",
        "stable-window package rejects raw provider-order drift",
    )
    expect_failure(
        lambda: validate_evidence_sequence([end_package_fixture, package_fixture]),
        "evidence phase reorder",
    )
    expect_failure(
        lambda: validate_evidence_sequence([package_fixture, end_package_fixture, end_package_fixture]),
        "evidence extra package record",
    )
    current_context_fixture = require_complete_current_context("a" * 40, "main", "b" * 40, "c" * 40, 19)
    expect_failure(
        lambda: require_complete_current_context(None, "main", "b" * 40, "c" * 40, 19),
        "evidence missing current base context",
    )
    expect_failure(
        lambda: require_complete_current_context("a" * 40, "main", "b" * 40, None, 19),
        "evidence missing local candidate tree",
    )
    expect_failure(
        lambda: require_complete_current_context("a" * 40, "main", "b" * 40, "c" * 40, True),
        "evidence boolean PR number",
    )
    expect_failure(
        lambda: require_complete_current_context("a" * 40, "release", "b" * 40, "c" * 40, 19),
        "evidence non-main complete context",
    )
    validate_evidence_sequence(
        [package_fixture, end_package_fixture],
        current_context=current_context_fixture,
        require_merge_ready=True,
    )
    for context_label, context_values in (
        ("base SHA", {"base_sha": "0" * 40}),
        ("PR number", {"pr_number": 20}),
        ("candidate head", {"candidate_head": "0" * 40}),
        ("candidate tree", {"candidate_tree": "0" * 40}),
    ):
        mismatched_context = CurrentPRContext(
            context_values.get("base_sha", current_context_fixture.base_sha),
            context_values.get("base_ref", current_context_fixture.base_ref),
            context_values.get("candidate_head", current_context_fixture.candidate_head),
            context_values.get("candidate_tree", current_context_fixture.candidate_tree),
            context_values.get("pr_number", current_context_fixture.pr_number),
        )
        expect_failure(
            lambda context=mismatched_context: validate_evidence_sequence(
                [package_fixture, end_package_fixture], current_context=context,
            ),
            f"evidence current-context {context_label} mismatch",
        )
    expect_failure(lambda: validate_evidence_sequence([package_fixture]), "standalone stable-window package")
    short_window = json.loads(json.dumps(end_package_fixture, ensure_ascii=False))
    short_window["manifest"]["snapshot_cutoff_utc"] = "2026-08-30T00:09:59Z"
    expect_failure(lambda: validate_evidence_sequence([package_fixture, short_window]), "short stable window")
    expect_failure(
        lambda: validate_evidence_sequence([package_fixture, end_package_fixture], require_merge_ready=True),
        "merge-ready missing current context",
    )

    merge_fixture_values = {
            "main-ref": {"ref": "refs/heads/main", "object": {"type": "commit", "sha": "d" * 40}},
            "merge-commit": {"object_type": "commit", "commit": "d" * 40, "parents": ["a" * 40], "tree": "c" * 40},
            "merge-response": {"merged": True, "sha": "d" * 40, "message": "Pull Request successfully merged"},
            "merged-pull": {
                "number": 19,
                "state": "closed",
                "merged": True,
                "merge_commit_sha": "d" * 40,
                "merged_at": "2026-08-30T00:10:02Z",
                "merged_by": {"id": OWNER_GITHUB_ID, "login": "ZhangIvan"},
                "auto_merge": None,
            },
            "post-merge-checks": {
                "total_count": len(REQUIRED_CONTEXTS),
                "check_runs": [
                    {
                        "app": {"id": GITHUB_ACTIONS_APP_ID, "slug": "github-actions", "owner": {"login": "github"}},
                        "check_suite": {"id": 900 + index},
                        "completed_at": "2026-08-30T00:10:02Z",
                        "details_url": f"https://github.com/ZhangIvan/QingYin/actions/runs/{700 + index}/job/{800 + index}",
                        "external_id": f"post-external-{index}",
                        "head_sha": "d" * 40,
                        "id": 600 + index,
                        "name": context,
                        "started_at": "2026-08-30T00:10:02Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                    for index, context in enumerate(REQUIRED_CONTEXTS, start=1)
                ],
            },
            "post-merge-metadata": metadata_graphql,
    }
    merge_bundle = sample_bundle("merge", merge_fixture_values)
    validate_merge_response_semantics(
        merge_bundle,
        semantic_root,
        "d" * 40,
        OWNER_GITHUB_ID,
        [path.as_posix() for path in BOOTSTRAP_PATHS],
        "2026-08-30T00:10:02Z",
    )
    reversed_post_checks_values = json.loads(json.dumps(merge_fixture_values))
    reversed_post_checks_values["post-merge-checks"]["check_runs"].reverse()
    validate_merge_response_semantics(
        sample_bundle("merge", reversed_post_checks_values),
        semantic_root,
        "d" * 40,
        OWNER_GITHUB_ID,
        [path.as_posix() for path in BOOTSTRAP_PATHS],
        "2026-08-30T00:10:02Z",
    )
    duplicate_post_checks_values = json.loads(json.dumps(merge_fixture_values))
    duplicate_post_checks_values["post-merge-checks"]["check_runs"][1]["id"] = (
        duplicate_post_checks_values["post-merge-checks"]["check_runs"][0]["id"]
    )
    expect_failure_message(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", duplicate_post_checks_values),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "post-merge-checks.check_runs contains a duplicate stable unique key",
        "duplicate post-merge check id key",
    )
    post_metadata_sidecar = response_item(merge_bundle, "post-merge-metadata")["human_body_hashes"]
    require(
        post_metadata_sidecar
        == [
            {
                "kind": "post-merge-metadata-graphql",
                "immutable_id": "PR_kwDOExample19",
                "field": "body",
                "state": "string",
                "sha256": hashlib.sha256(pull_body_fixture.encode("utf-8")).hexdigest(),
            }
        ],
        "post-merge GraphQL metadata body hash sidecar mismatch",
    )
    tampered_post_metadata_bundle = json.loads(json.dumps(merge_bundle))
    tampered_post_metadata = response_value(tampered_post_metadata_bundle, "post-merge-metadata")
    tampered_post_metadata["data"]["repository"]["pullRequest"]["body"] += " tampered"
    replace_json_response(
        tampered_post_metadata_bundle,
        "post-merge-metadata",
        tampered_post_metadata,
        rederive_human_body_hashes=False,
    )
    expect_failure(
        lambda: validate_evidence_object(tampered_post_metadata_bundle),
        "post-merge-metadata body tamper with recomputed endpoint hashes",
    )
    boolean_post_total_map = json.loads(json.dumps(merge_fixture_values))
    boolean_post_total_map["post-merge-checks"]["total_count"] = True
    expect_failure_message(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", boolean_post_total_map),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "post-merge checks.total_count must be an integer",
        "boolean post-merge checks total_count",
    )
    boolean_post_suite_map = json.loads(json.dumps(merge_fixture_values))
    boolean_post_suite_map["post-merge-checks"]["check_runs"][0]["check_suite"]["id"] = True
    expect_failure_message(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", boolean_post_suite_map),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "post-merge check[0] suite id must be an integer",
        "boolean post-merge check suite id",
    )
    merge_response_item = response_item(merge_bundle, "merge-response")
    merge_response_item["request"]["body"] = {"merge_method": "squash", "sha": "b" * 40}
    merge_response_item["request_canonical_sha256"] = hashlib.sha256(
        canonical_json_v1(merge_response_item["request"])
    ).hexdigest()
    post_bundles = [*stable_bundles, merge_bundle]
    post_digests = [
        {"name": bundle["component"], "endpoint_bundle_sha256": hashlib.sha256(canonical_json_v1(bundle)).hexdigest()}
        for bundle in post_bundles
    ]
    post_package_fixture = {
        **json.loads(json.dumps(end_package_fixture, ensure_ascii=False)),
        "phase": "post-merge",
        "snapshot_endpoint_bundles": post_bundles,
        "manifest": {
            **json.loads(json.dumps(end_package_fixture["manifest"], ensure_ascii=False)),
            "phase": "post-merge",
            "snapshot_cutoff_utc": "2026-08-30T00:10:02Z",
            "component_digests": post_digests,
            "effective_merge_sha": "d" * 40,
        },
    }
    validate_evidence_sequence([package_fixture, end_package_fixture, post_package_fixture])
    expect_failure(
        lambda: validate_evidence_sequence(
            [package_fixture, end_package_fixture, post_package_fixture],
            current_context=current_context_fixture,
            require_merge_ready=True,
        ),
        "merge-ready three-package sequence",
    )
    active_state_fixture: dict[str, str | int] = {
        "status": "ACTIVE",
        "activation_pr": 20,
        "candidate_head": "b" * 40,
        "merge_tree": "c" * 40,
        "effective_commit": "d" * 40,
        "merge_commit": "d" * 40,
        "merge_parent": "a" * 40,
        "governance_postmerge_manifest_sha": hashlib.sha256(canonical_json_v1(post_package_fixture["manifest"])).hexdigest(),
        "governance_attestation_sha": hashlib.sha256(canonical_json_v1(post_package_fixture["attestation"])).hexdigest(),
    }

    activation_pr_fixture = 20
    activation_head_fixture = "e" * 40
    activation_tree_fixture = "f" * 40

    def rebind_activation_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: rebind_activation_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebind_activation_value(item) for item in value]
        if isinstance(value, int) and not isinstance(value, bool) and value == EXPECTED_GOVERNANCE_PR:
            return activation_pr_fixture
        if isinstance(value, str):
            return (
                value.replace("b" * 40, activation_head_fixture)
                .replace("c" * 40, activation_tree_fixture)
                .replace("/pulls/19", "/pulls/20")
                .replace("/issues/19", "/issues/20")
                .replace("PR_kwDOExample19", "PR_kwDOActivation20")
                .replace("governance-bootstrap", "activation-evidence")
            )
        return value

    def write_rebound_json_response(item: dict[str, Any], value: Any) -> None:
        body = canonical_json_v1(value)
        digest = hashlib.sha256(body).hexdigest()
        item["response_media_type"] = "application/json"
        item["response_body_base64"] = base64.b64encode(body).decode("ascii")
        item["response_body_sha256"] = digest
        item["response_canonical_sha256"] = digest
        item["human_body_hashes"] = derive_human_body_hashes(item["label"], value)

    def rebind_activation_bundles(source_bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rebound = rebind_activation_value(json.loads(json.dumps(source_bundles, ensure_ascii=False)))
        rebound_log_hashes: dict[int, str] = {}
        for bundle in rebound:
            for item in bundle["responses"]:
                item["request"] = rebind_activation_value(item["request"])
                item["request_canonical_sha256"] = hashlib.sha256(canonical_json_v1(item["request"])).hexdigest()
                if item["response_media_type"] == "application/json":
                    original_value = response_value(bundle, item["label"])
                    write_rebound_json_response(item, rebind_activation_value(original_value))
                elif item["label"] == "workflow-logs":
                    original_archive = base64.b64decode(item["response_body_base64"], validate=True)
                    rebound_archive_buffer = io.BytesIO()
                    with zipfile.ZipFile(io.BytesIO(original_archive), "r") as source_archive, zipfile.ZipFile(
                        rebound_archive_buffer,
                        "w",
                        compression=zipfile.ZIP_DEFLATED,
                    ) as rebound_archive:
                        for member_name in sorted(source_archive.namelist(), key=utf16_sort_key):
                            member_body = source_archive.read(member_name)
                            rebound_body = rebind_activation_value(member_body.decode("utf-8")).encode("utf-8")
                            member = zipfile.ZipInfo(member_name, date_time=(1980, 1, 1, 0, 0, 0))
                            member.compress_type = zipfile.ZIP_DEFLATED
                            rebound_archive.writestr(member, rebound_body)
                            rebound_log_hashes[parse_positive_decimal(Path(member_name).stem, "rebound workflow job id")] = hashlib.sha256(rebound_body).hexdigest()
                    archive_body = rebound_archive_buffer.getvalue()
                    archive_digest = hashlib.sha256(archive_body).hexdigest()
                    item["response_body_base64"] = base64.b64encode(archive_body).decode("ascii")
                    item["response_body_sha256"] = archive_digest
                    item["response_canonical_sha256"] = archive_digest
                    item["human_body_hashes"] = []

        bundle_map = {bundle["component"]: bundle for bundle in rebound}
        review_artifact = response_value(bundle_map["review"], "agent-reviews")
        for review in review_artifact["reviews"]:
            review["review_input_sha256"] = hashlib.sha256(review["review_input_body"].encode("utf-8")).hexdigest()
            review["report_sha256"] = hashlib.sha256(review["report_body"].encode("utf-8")).hexdigest()
        write_rebound_json_response(response_item(bundle_map["review"], "agent-reviews"), review_artifact)
        verification_reports = [
            {"reviewer_id": review["reviewer_id"], "report_sha256": review["report_sha256"]}
            for review in review_artifact["reviews"]
        ]

        finding_ledger_value = response_value(bundle_map["finding"], "finding-ledger")
        for finding in finding_ledger_value["findings"]:
            evidence = finding["evidence"]
            if isinstance(evidence, dict) and "verification_reports" in evidence:
                evidence["verification_reports"] = verification_reports
            if finding["id"] == "GVN-P1-005":
                evidence["pr_number"] = activation_pr_fixture
                evidence["candidate_head"] = activation_head_fixture
                evidence["candidate_tree"] = activation_tree_fixture
                evidence["target_type"] = "activation-evidence"
        write_rebound_json_response(response_item(bundle_map["finding"], "finding-ledger"), finding_ledger_value)

        runner_provenance_value = response_value(bundle_map["runner"], "runner-provenance")
        for execution in runner_provenance_value["executions"]:
            execution["log_sha256"] = rebound_log_hashes[execution["job_id"]]
        write_rebound_json_response(response_item(bundle_map["runner"], "runner-provenance"), runner_provenance_value)
        return rebound

    outer_pre_bundles = rebind_activation_bundles(package_fixture["pre_endpoint_bundles"])
    outer_snapshot_bundles = rebind_activation_bundles(package_fixture["snapshot_endpoint_bundles"])
    outer_pre_digest_map = {
        bundle["component"]: hashlib.sha256(canonical_json_v1(bundle)).hexdigest()
        for bundle in outer_pre_bundles
    }
    outer_pre_attestation = rebind_activation_value(json.loads(json.dumps(package_fixture["pre_attestation"], ensure_ascii=False)))
    outer_pre_attestation["pr_number"] = activation_pr_fixture
    outer_pre_attestation["candidate_head"] = activation_head_fixture
    outer_pre_attestation["candidate_tree"] = activation_tree_fixture
    outer_pre_attestation["component_digests"] = [
        {"name": component, "endpoint_bundle_sha256": outer_pre_digest_map[component]}
        for component in PRE_ATTESTATION_COMPONENTS
    ]
    outer_attestation = rebind_activation_value(json.loads(json.dumps(package_fixture["attestation"], ensure_ascii=False)))
    outer_attestation["pr_number"] = activation_pr_fixture
    outer_attestation["candidate_head"] = activation_head_fixture
    outer_attestation["candidate_tree"] = activation_tree_fixture
    outer_attestation["pre_attestation_sha256"] = hashlib.sha256(canonical_json_v1(outer_pre_attestation)).hexdigest()
    outer_attestation["changed_paths_sha256"] = outer_pre_digest_map["paths"]

    outer_snapshot_map = {bundle["component"]: bundle for bundle in outer_snapshot_bundles}
    outer_attestation_payload_item = response_item(outer_snapshot_map["attestation"], "attestation-payload")
    outer_attestation_payload_item["request"]["body"] = outer_attestation
    outer_attestation_payload_item["request_canonical_sha256"] = hashlib.sha256(
        canonical_json_v1(outer_attestation_payload_item["request"])
    ).hexdigest()
    write_rebound_json_response(outer_attestation_payload_item, outer_attestation)
    outer_comment = response_value(outer_snapshot_map["attestation"], "attestation-comment")
    outer_comment["body"] = canonical_json_v1(outer_attestation).decode("utf-8")
    write_rebound_json_response(response_item(outer_snapshot_map["attestation"], "attestation-comment"), outer_comment)
    outer_issue_comments = response_value(outer_snapshot_map["discussion"], "issue-comments")
    require(len(outer_issue_comments) == 1, "outer activation fixture expects one publication comment")
    outer_issue_comments[0] = outer_comment
    write_rebound_json_response(response_item(outer_snapshot_map["discussion"], "issue-comments"), outer_issue_comments)

    outer_snapshot_digest_map = {
        bundle["component"]: hashlib.sha256(canonical_json_v1(bundle)).hexdigest()
        for bundle in outer_snapshot_bundles
    }
    outer_start_manifest = rebind_activation_value(json.loads(json.dumps(package_fixture["manifest"], ensure_ascii=False)))
    outer_start_manifest["pr_number"] = activation_pr_fixture
    outer_start_manifest["candidate_head"] = activation_head_fixture
    outer_start_manifest["candidate_tree"] = activation_tree_fixture
    outer_start_manifest["component_digests"] = [
        {"name": component, "endpoint_bundle_sha256": outer_snapshot_digest_map[component]}
        for component in STABLE_COMPONENTS
    ]
    outer_start_package = {
        "schema": "gvn-evidence-package-v2",
        "phase": "stable-window-start",
        "pre_endpoint_bundles": outer_pre_bundles,
        "snapshot_endpoint_bundles": outer_snapshot_bundles,
        "pre_attestation": outer_pre_attestation,
        "attestation": outer_attestation,
        "publication_delta": rebind_activation_value(json.loads(json.dumps(package_fixture["publication_delta"], ensure_ascii=False))),
        "manifest": outer_start_manifest,
        "activation_binding": None,
    }
    outer_end_package = json.loads(json.dumps(outer_start_package, ensure_ascii=False))
    outer_end_package["phase"] = "stable-window-end"
    outer_end_package["manifest"]["phase"] = "stable-window-end"
    outer_end_package["manifest"]["snapshot_cutoff_utc"] = end_package_fixture["manifest"]["snapshot_cutoff_utc"]
    activation_binding_fixture = {
        "schema": "gvn-activation-binding-v1",
        "activation_evidence_pr": activation_pr_fixture,
        "activation_candidate_head": activation_head_fixture,
        "activation_candidate_tree": activation_tree_fixture,
        "governance_evidence_sequence": [
            json.loads(json.dumps(package_fixture, ensure_ascii=False)),
            json.loads(json.dumps(end_package_fixture, ensure_ascii=False)),
            json.loads(json.dumps(post_package_fixture, ensure_ascii=False)),
        ],
    }
    outer_start_package["activation_binding"] = json.loads(json.dumps(activation_binding_fixture, ensure_ascii=False))
    outer_end_package["activation_binding"] = json.loads(json.dumps(activation_binding_fixture, ensure_ascii=False))
    outer_current_context = CurrentPRContext(
        "a" * 40,
        "main",
        activation_head_fixture,
        activation_tree_fixture,
        activation_pr_fixture,
    )
    validate_evidence_sequence(
        [outer_start_package, outer_end_package],
        current_context=outer_current_context,
        require_merge_ready=True,
        authorized_target_type="activation-evidence",
    )

    activation_main_state = {
        **active_state_fixture,
        "candidate_tree": activation_tree_fixture,
    }
    activation_evidence_paths = [
        Path("/tmp/qingyin-governance-evidence/activation-start.json"),
        Path("/tmp/qingyin-governance-evidence/activation-end.json"),
    ]

    def activation_main_argv(pr_number: int = activation_pr_fixture) -> list[str]:
        return [
            "validate_governance_state.py",
            "--base-sha",
            "a" * 40,
            "--base-ref",
            "main",
            "--head-sha",
            activation_head_fixture,
            "--pr-number",
            str(pr_number),
            "--evidence-json",
            str(activation_evidence_paths[0]),
            "--evidence-json",
            str(activation_evidence_paths[1]),
            "--require-merge-ready",
        ]

    def authoritative_activation_state(
        base_sha: str | None,
        base_ref: str | None,
        candidate_head: str | None,
        pr_number: int,
        self_test: bool,
    ) -> dict[str, str | int]:
        require(self_test is False, "main orchestration fixture must not recurse into self-test")
        require(
            (base_sha, base_ref, candidate_head, pr_number)
            == ("a" * 40, "main", activation_head_fixture, activation_pr_fixture),
            "main orchestration repository context mismatch",
        )
        return json.loads(json.dumps(activation_main_state))

    real_validate_evidence_sequence = validate_evidence_sequence
    real_validate_activation_evidence_binding = validate_activation_evidence_binding
    with (
        patch.object(sys, "argv", activation_main_argv()),
        patch(__name__ + ".event_context", return_value=("pull_request", "a" * 40, "main", activation_head_fixture, activation_pr_fixture)),
        patch(__name__ + ".validate_repository", side_effect=authoritative_activation_state) as main_repository_mock,
        patch(
            __name__ + ".read_evidence_package_file",
            side_effect=[json.loads(json.dumps(outer_start_package)), json.loads(json.dumps(outer_end_package))],
        ),
        patch(__name__ + ".validate_evidence_sequence", wraps=real_validate_evidence_sequence) as main_sequence_mock,
        patch(
            __name__ + ".validate_activation_evidence_binding",
            wraps=real_validate_activation_evidence_binding,
        ) as main_binding_mock,
        patch(__name__ + ".SOURCE_COMMIT", "a" * 40),
        patch.object(sys, "stdout", io.StringIO()),
        patch.object(sys, "stderr", io.StringIO()),
    ):
        require(main() == 0, "ACTIVE main orchestration rejected complete activation evidence")
    main_repository_mock.assert_called_once_with("a" * 40, "main", activation_head_fixture, activation_pr_fixture, False)
    require(main_sequence_mock.call_count == 2, "main orchestration must validate exactly one outer and one nested sequence")
    outer_sequence_call, nested_sequence_call = main_sequence_mock.call_args_list
    require(
        outer_sequence_call.kwargs.get("authorized_target_type") == "activation-evidence",
        "main did not derive activation authorization from authoritative state",
    )
    require(
        nested_sequence_call.kwargs.get("authorized_target_type") is None,
        "nested governance sequence recursively inherited activation authorization",
    )
    require(
        all(package["activation_binding"] is None for package in activation_binding_fixture["governance_evidence_sequence"]),
        "nested governance fixture unexpectedly carries activation state",
    )
    require(main_binding_mock.call_count == 1, "main did not execute activation binding validation exactly once")

    def run_negative_activation_main(
        state: dict[str, str | int],
        pr_number: int,
        packages: list[dict[str, Any]],
    ) -> tuple[int, str, int]:
        negative_stderr = io.StringIO()
        with (
            patch.object(sys, "argv", activation_main_argv(pr_number)),
            patch(__name__ + ".event_context", return_value=("pull_request", "a" * 40, "main", activation_head_fixture, pr_number)),
            patch(__name__ + ".validate_repository", return_value=json.loads(json.dumps(state))),
            patch(__name__ + ".read_evidence_package_file", side_effect=json.loads(json.dumps(packages))),
            patch(__name__ + ".validate_activation_evidence_binding", wraps=real_validate_activation_evidence_binding) as negative_binding_mock,
            patch(__name__ + ".SOURCE_COMMIT", "a" * 40),
            patch.object(sys, "stdout", io.StringIO()),
            patch.object(sys, "stderr", negative_stderr),
        ):
            result = main()
        return result, negative_stderr.getvalue(), negative_binding_mock.call_count

    for negative_label, negative_state, negative_pr in (
        ("proposed state", {**activation_main_state, "status": "PROPOSED"}, activation_pr_fixture),
        ("ordinary PR17", activation_main_state, 17),
        ("non-activation PR21", activation_main_state, 21),
        ("different activation pointer", {**activation_main_state, "activation_pr": 21}, activation_pr_fixture),
    ):
        negative_result, negative_error, negative_binding_calls = run_negative_activation_main(
            negative_state,
            negative_pr,
            [outer_start_package, outer_end_package],
        )
        require(negative_result == 1, f"{negative_label} unexpectedly received activation authorization")
        require(
            "non-authorized evidence must not carry an activation binding" in negative_error,
            f"{negative_label} failed for the wrong reason: {negative_error}",
        )
        require(negative_binding_calls == 0, f"{negative_label} reached activation binding validation after authorization failure")

    missing_outer_binding_packages = json.loads(json.dumps([outer_start_package, outer_end_package]))
    for package in missing_outer_binding_packages:
        package["activation_binding"] = None
    missing_result, missing_error, missing_binding_calls = run_negative_activation_main(
        activation_main_state,
        activation_pr_fixture,
        missing_outer_binding_packages,
    )
    require(missing_result == 1, "authorized activation without an outer binding unexpectedly passed")
    require("activation binding must be an object" in missing_error, f"missing outer binding failed for the wrong reason: {missing_error}")
    require(missing_binding_calls == 0, "missing outer binding reached activation binding validation")

    recursive_nested_packages = json.loads(json.dumps([outer_start_package, outer_end_package]))
    recursive_binding = recursive_nested_packages[0]["activation_binding"]
    recursive_binding["governance_evidence_sequence"][0]["activation_binding"] = {"recursive": True}
    recursive_nested_packages[1]["activation_binding"] = json.loads(json.dumps(recursive_binding))
    recursive_result, recursive_error, recursive_binding_calls = run_negative_activation_main(
        activation_main_state,
        activation_pr_fixture,
        recursive_nested_packages,
    )
    require(recursive_result == 1, "recursive nested activation binding unexpectedly passed")
    require("nested governance evidence cannot recursively carry activation state" in recursive_error, f"recursive binding failed for the wrong reason: {recursive_error}")
    require(recursive_binding_calls == 1, "recursive binding must fail inside the single activation binding validation")

    activation_binding_fixture = {
        "schema": "gvn-activation-binding-v1",
        "activation_evidence_pr": 20,
        "activation_candidate_head": "e" * 40,
        "activation_candidate_tree": "f" * 40,
        "governance_evidence_sequence": [package_fixture, end_package_fixture, post_package_fixture],
    }
    activation_package_stub = {
        "activation_binding": activation_binding_fixture,
        "pre_attestation": {"pr_number": 20, "candidate_head": "e" * 40, "candidate_tree": "f" * 40},
    }
    activation_start_stub = {**activation_package_stub, "phase": "stable-window-start"}
    activation_end_stub = {**activation_package_stub, "phase": "stable-window-end"}
    activation_outer_packages = [activation_start_stub, activation_end_stub]
    validate_activation_evidence_binding(activation_outer_packages, active_state_fixture, 20, "a" * 40)
    expect_failure(
        lambda: validate_activation_evidence_binding([activation_start_stub], active_state_fixture, 20, "a" * 40),
        "activation outer pre-only phase",
    )
    expect_failure(
        lambda: validate_activation_evidence_binding(
            [activation_start_stub, activation_end_stub, {**activation_end_stub, "phase": "post-merge"}],
            active_state_fixture,
            20,
            "a" * 40,
        ),
        "activation outer post-merge phase",
    )
    short_nested_binding = {**activation_binding_fixture, "governance_evidence_sequence": [package_fixture, end_package_fixture]}
    expect_failure(
        lambda: validate_activation_evidence_binding(
            [
                {**activation_start_stub, "activation_binding": short_nested_binding},
                {**activation_end_stub, "activation_binding": short_nested_binding},
            ],
            active_state_fixture,
            20,
            "a" * 40,
        ),
        "activation nested sequence missing post-merge",
    )
    wrong_activation_state = {**active_state_fixture, "governance_attestation_sha": "0" * 64}
    expect_failure(
        lambda: validate_activation_evidence_binding(activation_outer_packages, wrong_activation_state, 20, "a" * 40),
        "activation binding governance attestation digest",
    )
    expect_failure(
        lambda: validate_activation_evidence_binding(activation_outer_packages, {**active_state_fixture, "activation_pr": 21}, 20, "a" * 40),
        "activation binding on non-activation PR",
    )
    failed_post_checks = json.loads(json.dumps(merge_fixture_values["post-merge-checks"]))
    failed_post_checks["check_runs"][0]["conclusion"] = "failure"
    expect_failure(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "post-merge-checks": failed_post_checks}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "failed post-merge check",
    )
    premerge_post_checks = json.loads(json.dumps(merge_fixture_values["post-merge-checks"]))
    premerge_post_checks["check_runs"][0]["started_at"] = "2026-08-30T00:10:01Z"
    expect_failure_message(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "post-merge-checks": premerge_post_checks}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "post-merge check[0] timing is outside the merge/post-cutoff interval",
        "post-merge check before merge",
    )
    late_post_checks = json.loads(json.dumps(merge_fixture_values["post-merge-checks"]))
    late_post_checks["check_runs"][0]["completed_at"] = "2026-08-30T00:10:03Z"
    expect_failure_message(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "post-merge-checks": late_post_checks}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "post-merge check[0] timing is outside the merge/post-cutoff interval",
        "post-merge check after cutoff",
    )
    late_merged_pull = json.loads(json.dumps(merge_fixture_values["merged-pull"]))
    late_merged_pull["merged_at"] = "2026-08-30T00:10:03Z"
    expect_failure_message(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "merged-pull": late_merged_pull}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "merged pull is newer than the post-merge cutoff",
        "merge after post cutoff",
    )
    empty_post_checks = {"total_count": 0, "check_runs": []}
    expect_failure(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "post-merge-checks": empty_post_checks}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "empty post-merge checks",
    )
    wrong_actor_pull = json.loads(json.dumps(merge_fixture_values["merged-pull"]))
    wrong_actor_pull["merged_by"] = {"id": 999, "login": "not-owner"}
    expect_failure(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "merged-pull": wrong_actor_pull}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "wrong immutable merge actor",
    )
    queued_post_metadata = json.loads(json.dumps(metadata_graphql))
    queued_post_metadata["data"]["repository"]["pullRequest"]["mergeQueueEntry"] = {"id": "queue-entry", "position": 1}
    expect_failure(
        lambda: validate_merge_response_semantics(
            sample_bundle("merge", {**merge_fixture_values, "post-merge-metadata": queued_post_metadata}),
            semantic_root,
            "d" * 40,
            OWNER_GITHUB_ID,
            [path.as_posix() for path in BOOTSTRAP_PATHS],
            "2026-08-30T00:10:02Z",
        ),
        "post-merge queue state",
    )
    error_status_bundle = sample_bundle("merge", merge_fixture_values)
    response_item(error_status_bundle, "merge-response")["response_status"] = 409
    expect_failure(lambda: validate_evidence_object(error_status_bundle), "merge response HTTP conflict")
    expect_failure(lambda: validate_evidence_sequence([post_package_fixture]), "standalone post-merge package")
    pre_package_fixture = {
        "schema": "gvn-evidence-package-v2",
        "phase": "pre-attestation",
        "pre_endpoint_bundles": pre_bundles,
        "snapshot_endpoint_bundles": [],
        "pre_attestation": pre_fixture,
        "attestation": None,
        "publication_delta": None,
        "manifest": None,
        "activation_binding": None,
    }
    validate_evidence_sequence([pre_package_fixture])
    expect_failure(
        lambda: validate_evidence_sequence(
            [pre_package_fixture], current_context=current_context_fixture, require_merge_ready=True,
        ),
        "merge-ready pre-attestation-only sequence",
    )
    expect_failure(
        lambda: validate_evidence_sequence(
            [post_package_fixture], current_context=current_context_fixture, require_merge_ready=True,
        ),
        "merge-ready post-merge-only sequence",
    )
    bad_package = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    bad_package["pre_attestation"]["component_digests"][0]["endpoint_bundle_sha256"] = "0" * 64
    expect_failure(lambda: validate_evidence_object(bad_package), "package cross-component digest mismatch")
    forged_delta = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    forged_delta["snapshot_endpoint_bundles"][0] = pre_bundles[0]
    expect_failure(lambda: validate_evidence_object(forged_delta), "publication delta missing pull mutation")
    expired_residual = json.loads(json.dumps(package_fixture, ensure_ascii=False))
    expired_residual["manifest"]["snapshot_cutoff_utc"] = "2026-09-29T00:00:00Z"
    expect_failure(lambda: validate_evidence_object(expired_residual), "residual expiry at snapshot cutoff")
    missing_attested_finding = {**attestation_fixture, "finding_ids": ["GVN-P1-001"]}
    stable_bundle_map = {bundle["component"]: bundle for bundle in stable_bundles}
    expect_failure(
        lambda: validate_finding_ledger(
            stable_bundle_map["finding"],
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            missing_attested_finding,
            "governance-bootstrap",
        ),
        "attestation finding ledger mismatch",
    )
    missing_005_attestation = json.loads(json.dumps(attestation_fixture))
    missing_005_attestation["accepted_residual_ids"].remove("GVN-P1-005")
    expect_failure(
        lambda: validate_finding_ledger(
            stable_bundle_map["finding"],
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            missing_005_attestation,
            "governance-bootstrap",
        ),
        "attestation missing GVN-P1-005 acceptance",
    )
    missing_005_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    missing_005_ledger["findings"] = [item for item in missing_005_ledger["findings"] if item["id"] != "GVN-P1-005"]
    expect_failure_message(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": missing_005_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "accepted residual set does not match the evidence target",
        "governance bootstrap missing GVN-P1-005",
    )
    for binding_field, wrong_value in (
        ("pr_number", 20),
        ("base_sha", "d" * 40),
        ("candidate_head", "d" * 40),
        ("candidate_tree", "d" * 40),
        ("target_type", "activation-evidence"),
    ):
        wrong_005_binding_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
        wrong_005 = next(item for item in wrong_005_binding_ledger["findings"] if item["id"] == "GVN-P1-005")
        wrong_005["evidence"][binding_field] = wrong_value
        expect_failure_message(
            lambda ledger=wrong_005_binding_ledger: validate_finding_ledger(
                sample_bundle("finding", {"finding-ledger": ledger}),
                stable_bundle_map["review"],
                stable_fixture["snapshot_cutoff_utc"],
                semantic_root,
                None,
                "governance-bootstrap",
            ),
            "GVN-P1-005 acceptance target binding mismatch",
            f"GVN-P1-005 wrong {binding_field}",
        )
    wrong_005_scope_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    next(item for item in wrong_005_scope_ledger["findings"] if item["id"] == "GVN-P1-005")["scope"] = "repository-only: ordinary PR freshness"
    expect_failure_message(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": wrong_005_scope_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "Accepted-Residual scope mismatch: GVN-P1-005",
        "GVN-P1-005 scope expansion",
    )
    wrong_005_section_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    next(item for item in wrong_005_section_ledger["findings"] if item["id"] == "GVN-P1-005")["evidence"]["section_sha256"] = "0" * 64
    expect_failure_message(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": wrong_005_section_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "Accepted-Residual section digest mismatch: GVN-P1-005",
        "GVN-P1-005 section hash mismatch",
    )
    false_005_freshness_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    next(item for item in false_005_freshness_ledger["findings"] if item["id"] == "GVN-P1-005")["evidence"]["derived_status"]["stable_window_freshness"] = "VERIFIED"
    expect_failure_message(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": false_005_freshness_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "GVN-P1-005 derived status mismatch",
        "GVN-P1-005 false freshness verification",
    )
    ordinary_root = {**semantic_root, "pr_number": 17}
    forged_activation_target_package = {
        "activation_binding": {
            "activation_evidence_pr": ordinary_root["pr_number"],
            "activation_candidate_head": ordinary_root["candidate_head"],
            "activation_candidate_tree": ordinary_root["candidate_tree"],
        }
    }
    expect_failure_message(
        lambda: derive_evidence_target_type(forged_activation_target_package, ordinary_root),
        "non-authorized evidence must not carry an activation binding",
        "ordinary PR self-declared as activation evidence",
    )
    require(
        derive_evidence_target_type(forged_activation_target_package, ordinary_root, "activation-evidence") == "activation-evidence",
        "authorized activation evidence target derivation failed",
    )
    activation_non_source_root = {
        **semantic_root,
        "pr_number": 20,
        "base_sha": "d" * 40,
    }
    activation_non_source_package = {
        "activation_binding": {
            "activation_evidence_pr": activation_non_source_root["pr_number"],
            "activation_candidate_head": activation_non_source_root["candidate_head"],
            "activation_candidate_tree": activation_non_source_root["candidate_tree"],
        }
    }
    require(
        derive_evidence_target_type(activation_non_source_package, activation_non_source_root, "activation-evidence") == "activation-evidence",
        "activation evidence must allow a non-source base",
    )
    ordinary_resolved_005_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    ordinary_resolved_005 = next(item for item in ordinary_resolved_005_ledger["findings"] if item["id"] == "GVN-P1-005")
    ordinary_resolved_005["status"] = "Resolved"
    ordinary_resolved_005["valid_until"] = None
    ordinary_resolved_005["evidence"] = {
        "schema": "gvn-finding-resolution-v1",
        "from_status": "Open",
        "transition": "Open->Resolved",
        "candidate_head": ordinary_root["candidate_head"],
        "resolved_at": "2026-08-29T23:46:00Z",
        "patch_sha256": "0" * 64,
        "verification_reports": verification_report_fixture,
    }
    expect_failure_message(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": ordinary_resolved_005_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            ordinary_root,
            None,
            "ordinary",
        ),
        "ordinary evidence cannot carry one-time residual finding: GVN-P1-005",
        "ordinary PR carrying Resolved GVN-P1-005",
    )
    ordinary_deferred_005_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    next(item for item in ordinary_deferred_005_ledger["findings"] if item["id"] == "GVN-P1-005")["status"] = "Deferred-P2"
    expect_failure_message(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": ordinary_deferred_005_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            ordinary_root,
            None,
            "ordinary",
        ),
        "ordinary evidence cannot carry one-time residual finding: GVN-P1-005",
        "ordinary PR carrying Deferred GVN-P1-005",
    )
    expect_failure(
        lambda: validate_finding_ledger(
            stable_bundle_map["finding"],
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            ordinary_root,
            None,
            "ordinary",
        ),
        "ordinary PR carrying GVN-P1-005",
    )
    activation_root = {
        **semantic_root,
        "pr_number": 20,
        "candidate_head": "e" * 40,
        "candidate_tree": "f" * 40,
    }
    activation_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    for activation_finding in activation_ledger["findings"]:
        activation_finding["evidence"]["candidate_head"] = activation_root["candidate_head"]
    activation_005 = next(item for item in activation_ledger["findings"] if item["id"] == "GVN-P1-005")["evidence"]
    activation_005["pr_number"] = activation_root["pr_number"]
    activation_005["candidate_tree"] = activation_root["candidate_tree"]
    activation_005["target_type"] = "activation-evidence"
    validate_finding_ledger(
        sample_bundle("finding", {"finding-ledger": activation_ledger}),
        stable_bundle_map["review"],
        stable_fixture["snapshot_cutoff_utc"],
        activation_root,
        None,
        "activation-evidence",
    )
    expect_failure_message(
        lambda: require_merge_ready_freshness("ordinary"),
        "ordinary merge-ready evidence requires a trusted freshness receipt schema",
        "ordinary CR3 without trusted freshness receipt",
    )
    extended_expiry_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    extended_expiry_ledger["findings"][0]["valid_until"] = "2099-01-01T00:00:00Z"
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": extended_expiry_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "governance residual expiry extension",
    )
    arbitrary_acceptance_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    arbitrary_acceptance_ledger["findings"][0]["evidence"] = "not-a-proof"
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": arbitrary_acceptance_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "arbitrary Accepted-Residual evidence",
    )
    wrong_acceptance_report_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    wrong_acceptance_report_ledger["findings"][0]["evidence"]["verification_reports"][0]["report_sha256"] = "0" * 64
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": wrong_acceptance_report_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "Accepted-Residual verifier report mismatch",
    )
    early_acceptance_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    early_acceptance_ledger["findings"][0]["evidence"]["accepted_at"] = "2026-08-29T23:39:59Z"
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": early_acceptance_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "Accepted-Residual transition before fresh reviews",
    )
    production_residual_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    production_residual_ledger["findings"].append(
        {**production_residual_ledger["findings"][0], "id": "REV-P1-001", "scope": "production authorization"}
    )
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": production_residual_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "undeclared production residual",
    )
    production_resolved_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    production_resolved_ledger["findings"].append(
        {
            "id": "REV-P0-999",
            "severity": "P0",
            "status": "Resolved",
            "owner": "ZhangIvan",
            "scope": "repository-only: production authorization",
            "reason": "Attempted scope escalation.",
            "mitigation": "Do not authorize production.",
            "rollback": "Stop governance activation.",
            "evidence": "immutable-review-report-sha256",
            "valid_until": None,
            "invalidators": [],
            "disposition": "Resolved in repository governance only.",
        }
    )
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": production_resolved_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "production-scoped resolved finding",
    )
    severity_mismatch_ledger = json.loads(json.dumps(finding_ledger, ensure_ascii=False))
    severity_mismatch_ledger["findings"][0]["severity"] = "P2"
    expect_failure(
        lambda: validate_finding_ledger(
            sample_bundle("finding", {"finding-ledger": severity_mismatch_ledger}),
            stable_bundle_map["review"],
            stable_fixture["snapshot_cutoff_utc"],
            semantic_root,
            None,
            "governance-bootstrap",
        ),
        "finding id/severity mismatch",
    )
    github_environment_keys = (
        "GITHUB_ACTIONS",
        "GITHUB_EVENT_PATH",
        "GITHUB_EVENT_NAME",
        "GITHUB_REPOSITORY",
        "GITHUB_REF",
        "GITHUB_BASE_REF",
        "GITHUB_HEAD_REF",
    )
    saved_github_environment = {key: os.environ.get(key) for key in github_environment_keys}
    try:
        with tempfile.TemporaryDirectory(prefix="gvn-event-") as event_directory:
            event_file = Path(event_directory) / "event.json"
            event_payload = {
                "number": 19,
                "repository": {"full_name": "ZhangIvan/QingYin"},
                "pull_request": {
                    "base": {"sha": "a" * 40, "ref": "main", "repo": {"full_name": "ZhangIvan/QingYin"}},
                    "head": {"sha": "b" * 40, "ref": "docs/g0-single-maintainer-governance", "repo": {"full_name": "ZhangIvan/QingYin"}},
                },
            }
            event_file.write_text(json.dumps(event_payload), encoding="utf-8")
            os.environ.update(
                {
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_EVENT_PATH": str(event_file),
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_REPOSITORY": "ZhangIvan/QingYin",
                    "GITHUB_REF": "refs/pull/19/merge",
                    "GITHUB_BASE_REF": "main",
                    "GITHUB_HEAD_REF": "docs/g0-single-maintainer-governance",
                }
            )
            require(event_context() == ("pull_request", "a" * 40, "main", "b" * 40, 19), "pull-request event context fixture mismatch")
            event_file.write_text(
                '{"number":19,"repository":{"full_name":"ZhangIvan/QingYin"},'
                '"repository":{"full_name":"ZhangIvan/QingYin"},"pull_request":{}}',
                encoding="utf-8",
            )
            expect_failure(event_context, "strict event duplicate key")
            event_bool_payload = json.loads(json.dumps(event_payload))
            event_bool_payload["number"] = True
            event_file.write_text(json.dumps(event_bool_payload), encoding="utf-8")
            expect_failure(event_context, "event boolean PR number")
            event_file.write_text(json.dumps(event_payload), encoding="utf-8")
            os.environ["GITHUB_EVENT_NAME"] = "push"
            os.environ["GITHUB_REF"] = "refs/heads/main"
            push_payload = {"repository": {"full_name": "ZhangIvan/QingYin"}, "ref": "refs/heads/main"}
            event_file.write_text(json.dumps(push_payload), encoding="utf-8")
            require(event_context() == ("push", None, None, None, 0), "push event context fixture mismatch")
            with patch.object(
                sys,
                "argv",
                [
                    "validate_governance_state.py",
                    "--base-sha",
                    "a" * 40,
                    "--base-ref",
                    "main",
                    "--head-sha",
                    "b" * 40,
                    "--pr-number",
                    "19",
                ],
            ):
                require(main() == 1, "push event accepted complete CLI PR context")
            with patch.object(sys, "argv", ["validate_governance_state.py", "--evidence-json", "/tmp/missing-evidence.json"]):
                require(main() == 1, "push event accepted --evidence-json")
            with patch.object(sys, "argv", ["validate_governance_state.py", "--require-merge-ready"]):
                require(main() == 1, "push event accepted --require-merge-ready")
            event_file.write_text(json.dumps(event_payload), encoding="utf-8")
            os.environ["GITHUB_EVENT_NAME"] = "pull_request"
            os.environ["GITHUB_REF"] = "refs/pull/19/merge"
            os.environ["GITHUB_REPOSITORY"] = "attacker/fork"
            expect_failure(event_context, "event repository environment mismatch")
    finally:
        for key, original_value in saved_github_environment.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
    expect_failure(lambda: require_utc_timestamp("2026-02-31T00:00:00Z", "invalid-date"), "invalid UTC calendar date")
    expect_failure(
        lambda: validate_evidence_object({**attestation_fixture, "attestor_id": SAFE_INTEGER_LIMIT + 1}),
        "unsafe attestor integer",
    )
    expect_failure(
        lambda: validate_evidence_object({**attestation_fixture, "rollback": "e\u0301"}),
        "NFD attestation rollback",
    )

    active_sha = "a" * 40
    finalized_validator_blob = str(draft_state["governance_validator_blob"])
    if finalized_validator_blob == "PENDING":
        finalized_validator_blob = "d" * 40
        finalized_dec = dec.replace(
            "- `governance_validator_blob_git_sha1`：`PENDING`",
            f"- `governance_validator_blob_git_sha1`：`{finalized_validator_blob}`",
            1,
        )
    else:
        finalized_dec = dec
    finalized_state = parse_triplet(finalized_dec, plan, index)
    require(finalized_state["governance_validator_blob"] == finalized_validator_blob, "finalized validator blob self-test mismatch")
    finalized_validator_line = f"- `governance_validator_blob_git_sha1`：`{finalized_validator_blob}`"
    expect_failure(
        lambda: parse_triplet(finalized_dec.replace(finalized_validator_line, "", 1), plan, index),
        "missing DEC validator blob field",
    )
    expect_failure(
        lambda: parse_triplet(finalized_dec.replace(finalized_validator_line, f"{finalized_validator_line}\n{finalized_validator_line}", 1), plan, index),
        "duplicate DEC validator blob field",
    )
    expect_failure(
        lambda: parse_triplet(
            finalized_dec.replace(finalized_validator_line, "- `governance_validator_blob_git_sha1`：`" + "A" * 40 + "`", 1),
            plan,
            index,
        ),
        "uppercase DEC validator blob field",
    )
    expect_failure(
        lambda: parse_triplet(
            finalized_dec.replace(finalized_validator_line, "- `governance_validator_blob_git_sha1`：`" + "d" * 39 + "`", 1),
            plan,
            index,
        ),
        "short DEC validator blob field",
    )
    expect_failure(
        lambda: parse_triplet(
            finalized_dec.replace(finalized_validator_line, "- `governance_validator_blob_git_sha1`：`" + "g" * 40 + "`", 1),
            plan,
            index,
        ),
        "non-hex DEC validator blob field",
    )
    if draft_state["governance_validator_blob"] == "PENDING":
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, draft_state),
            "base-aware candidate with PENDING validator blob",
        )
    with patch(__name__ + ".git") as validator_tree_git:
        validator_tree_git.return_value = subprocess.CompletedProcess(
            ("git",),
            0,
            f"100644 blob {finalized_validator_blob}\t{VALIDATOR_PATH.as_posix()}\n".encode("utf-8"),
            b"",
        )
        validate_candidate_validator_blob(active_sha, finalized_state)
        validator_tree_git.return_value = subprocess.CompletedProcess(
            ("git",),
            0,
            f"100755 blob {finalized_validator_blob}\t{VALIDATOR_PATH.as_posix()}\n".encode("utf-8"),
            b"",
        )
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "executable candidate validator blob",
        )
        validator_tree_git.return_value = subprocess.CompletedProcess(
            ("git",),
            0,
            f"100644 blob {'e' * 40}\t{VALIDATOR_PATH.as_posix()}\n".encode("utf-8"),
            b"",
        )
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "candidate validator blob differs from DEC",
        )
        validator_tree_git.return_value = subprocess.CompletedProcess(
            ("git",),
            0,
            f"100644 blob {finalized_validator_blob}\tother/path\n".encode("utf-8"),
            b"",
        )
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "candidate validator blob has wrong path",
        )
        validator_tree_git.return_value = subprocess.CompletedProcess(
            ("git",),
            0,
            f"100644 tree {finalized_validator_blob}\t{VALIDATOR_PATH.as_posix()}\n".encode("utf-8"),
            b"",
        )
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "candidate validator blob has tree type",
        )
        validator_tree_git.return_value = subprocess.CompletedProcess(
            ("git",),
            0,
            (
                f"100644 blob {finalized_validator_blob}\t{VALIDATOR_PATH.as_posix()}\n"
                f"100644 blob {finalized_validator_blob}\t{VALIDATOR_PATH.as_posix()}\n"
            ).encode("utf-8"),
            b"",
        )
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "duplicate candidate validator tree entries",
        )
        validator_tree_git.return_value = subprocess.CompletedProcess(("git",), 0, b"", b"")
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "missing candidate validator tree entry",
        )
        validator_tree_git.return_value = subprocess.CompletedProcess(("git",), 0, b"\xff", b"")
        expect_failure(
            lambda: validate_candidate_validator_blob(active_sha, finalized_state),
            "invalid UTF-8 candidate validator tree entry",
        )
    active_dec = finalized_dec.replace("- 状态：`PROPOSED`", "- 状态：`ACTIVE`")
    active_dec = active_dec.replace("- 生效状态：`PENDING`", "- 生效状态：`ACTIVE`")
    active_dec = active_dec.replace("- `effective_commit`：`PENDING`", f"- `effective_commit`：`{active_sha}`")
    active_dec = active_dec.replace("- `governance_candidate_head`：`PENDING`", f"- `governance_candidate_head`：`{active_sha}`")
    active_dec = active_dec.replace("- `governance_merge_commit`：`PENDING`", f"- `governance_merge_commit`：`{active_sha}`")
    active_dec = active_dec.replace("- `governance_merge_tree`：`PENDING`", f"- `governance_merge_tree`：`{active_sha}`")
    active_dec = active_dec.replace("- `governance_merge_parent`：`PENDING`", f"- `governance_merge_parent`：`{active_sha}`")
    active_dec = active_dec.replace(
        "- `governance_postmerge_manifest_sha256`：`PENDING`",
        f"- `governance_postmerge_manifest_sha256`：`{'b' * 64}`",
    )
    active_dec = active_dec.replace(
        "- `governance_attestation_sha256`：`PENDING`",
        f"- `governance_attestation_sha256`：`{'c' * 64}`",
    )
    active_dec = active_dec.replace("- `activation_evidence_pr`：`PENDING`", "- `activation_evidence_pr`：`#20`")
    active_label = f"ACTIVE / effective={active_sha}"
    active_plan = plan.replace("PROPOSED / effective=PENDING", active_label, 1)
    active_index = index.replace("PROPOSED / effective=PENDING", active_label, 1)
    oversized_activation_dec = active_dec.replace(
        "- `activation_evidence_pr`：`#20`",
        f"- `activation_evidence_pr`：`#{SAFE_INTEGER_LIMIT + 1}`",
    )
    expect_failure_message(
        lambda: parse_triplet(oversized_activation_dec, active_plan, active_index),
        "activation_evidence_pr must be a positive safe integer",
        "oversized activation evidence PR",
    )
    active = parse_triplet(active_dec, active_plan, active_index)
    require(active["activation_pr"] == 20, "ACTIVE self-test PR mismatch")
    with patch(__name__ + ".git") as mocked_git, patch(__name__ + ".git_text_at", side_effect=(active_dec, active_plan, active_index)), patch(__name__ + ".cumulative_name_status", return_value={}), patch(__name__ + ".read_document", return_value=active_dec):
        mocked_git.return_value = subprocess.CompletedProcess(("git",), 0, b"", b"")
        expect_failure(
            lambda: validate_activation_diff("a" * 40, "release", 20, active),
            "ACTIVE governance PR non-main base",
        )
    require_active_dec_immutable("ACTIVE", active_dec, active_dec)
    expect_failure(
        lambda: require_active_dec_immutable("PROPOSED", active_dec, active_dec),
        "ACTIVE downgrade",
    )
    expect_failure(
        lambda: require_active_dec_immutable("ACTIVE", active_dec, active_dec + "tampered"),
        "ACTIVE mutation",
    )
    require(
        normalize_frozen(finalized_dec, DEC_MUTABLE_PREFIXES, "DEC self-test")
        == normalize_frozen(active_dec, DEC_MUTABLE_PREFIXES, "DEC self-test"),
        "allowed DEC activation lines did not normalize",
    )
    frozen_change = active_dec.replace("## 1. 背景与问题", "## 1. changed", 1)
    require(
        normalize_frozen(finalized_dec, DEC_MUTABLE_PREFIXES, "DEC self-test")
        != normalize_frozen(frozen_change, DEC_MUTABLE_PREFIXES, "DEC self-test"),
        "frozen DEC mutation escaped detection",
    )
    fabricated_evidence = active_dec.replace("| 当前保护快照 | `VERIFIED`", "| 当前保护快照 | `FABRICATED`", 1)
    require(
        normalize_frozen(active_dec, DEC_MUTABLE_PREFIXES, "DEC self-test")
        != normalize_frozen(fabricated_evidence, DEC_MUTABLE_PREFIXES, "DEC self-test"),
        "evidence-row mutation escaped frozen-byte detection",
    )
    if exercise_active_input:
        _run_self_tests(active_dec, active_plan, active_index, exercise_active_input=False)


def run_self_tests(dec: str, plan: str, index: str, exercise_active_input: bool = True) -> None:
    require(SOURCE_COMMIT == "27320e74f8cb920add83d6094fb81233dbb29636", "self-test source commit constant drifted")
    require_governance_bootstrap_base(REAL_SOURCE_COMMIT)
    expect_failure_message(
        lambda: require_governance_bootstrap_base("a" * 40),
        "governance bootstrap base must equal frozen source commit",
        "alternate governance bootstrap source base",
    )
    expect_failure_message(
        lambda: validate_activation_diff("a" * 40, "main", EXPECTED_GOVERNANCE_PR, {"status": "PROPOSED"}),
        "governance bootstrap base must equal frozen source commit",
        "alternate base before DEC branch selection",
    )
    expect_failure_message(
        lambda: validate_activation_diff(REAL_SOURCE_COMMIT, "release", EXPECTED_GOVERNANCE_PR, {"status": "PROPOSED"}),
        "governance bootstrap must target base.ref=main",
        "governance bootstrap non-main base ref",
    )
    synthetic_source_commit = "a" * 40
    dec = dec.replace(
        f"- 基线：`main@{REAL_SOURCE_COMMIT}`",
        f"- 基线：`main@{synthetic_source_commit}`",
        1,
    )
    with patch(__name__ + ".SOURCE_COMMIT", synthetic_source_commit):
        _run_self_tests(dec, plan, index, exercise_active_input)


def event_context() -> tuple[str, str | None, str | None, str | None, int]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        require(os.environ.get("GITHUB_ACTIONS") != "true", "GitHub Actions execution is missing GITHUB_EVENT_PATH")
        return "none", None, None, None, 0
    path = Path(event_path)
    if not path.is_file():
        fail(f"GITHUB_EVENT_PATH is not a file: {path}")
    payload = parse_json_strict(validate_utf8_bytes(path.read_bytes(), str(path)))
    require(isinstance(payload, dict), "GitHub event payload must be an object")
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    require(event_name in ("pull_request", "push"), "governance workflow event must be pull_request or push")
    require(os.environ.get("GITHUB_REPOSITORY") == "ZhangIvan/QingYin", "GITHUB_REPOSITORY mismatch")
    repository = payload.get("repository")
    require(isinstance(repository, dict) and repository.get("full_name") == "ZhangIvan/QingYin", "event repository identity mismatch")
    pull_request = payload.get("pull_request")
    if event_name == "push":
        require(not isinstance(pull_request, dict), "push event must not masquerade as a pull-request candidate")
        require(payload.get("ref") == "refs/heads/main" and os.environ.get("GITHUB_REF") == "refs/heads/main", "governance push event must target main")
        return "push", None, None, None, 0
    require(isinstance(pull_request, dict), "pull_request event payload is missing pull_request")
    base_object = pull_request.get("base", {})
    head_object = pull_request.get("head", {})
    require(isinstance(base_object, dict), "event base object missing or invalid")
    require(isinstance(head_object, dict), "event head object missing or invalid")
    base = base_object.get("sha")
    head = head_object.get("sha")
    base_ref = base_object.get("ref")
    head_ref = head_object.get("ref")
    number = payload.get("number")
    require(isinstance(base, str) and re.fullmatch(r"[0-9a-f]{40}", base) is not None, "event base SHA missing or invalid")
    require(isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head) is not None, "event head SHA missing or invalid")
    require(isinstance(base_ref, str) and base_ref, "event base ref missing or invalid")
    require(isinstance(head_ref, str) and head_ref, "event head ref missing or invalid")
    require_positive_int(number, "event PR number")
    require(isinstance(base_object.get("repo"), dict) and base_object["repo"].get("full_name") == "ZhangIvan/QingYin", "event base repository mismatch")
    require(isinstance(head_object.get("repo"), dict) and head_object["repo"].get("full_name") == "ZhangIvan/QingYin", "event head repository mismatch")
    require(os.environ.get("GITHUB_REF") == f"refs/pull/{number}/merge", "GITHUB_REF does not name the pull-request merge ref")
    require(os.environ.get("GITHUB_BASE_REF") == base_ref and os.environ.get("GITHUB_HEAD_REF") == head_ref, "GitHub base/head ref environment mismatch")
    return "pull_request", base, base_ref, head, number


def require_complete_current_context(
    base_sha: str | None,
    base_ref: str | None,
    candidate_head: str | None,
    candidate_tree: Any,
    pr_number: int,
) -> CurrentPRContext:
    require(
        isinstance(base_sha, str)
        and isinstance(base_ref, str)
        and base_ref == "main"
        and isinstance(candidate_head, str)
        and isinstance(candidate_tree, str),
        "--evidence-json requires complete current PR context",
    )
    require_positive_int(pr_number, "current PR number")
    require_sha1(base_sha, "current PR base SHA")
    require_sha1(candidate_head, "current PR candidate head")
    require_sha1(candidate_tree, "current PR candidate tree")
    return CurrentPRContext(base_sha, base_ref, candidate_head, candidate_tree, pr_number)


def validate_candidate_validator_blob(candidate_head: str, governance_state: dict[str, str | int]) -> None:
    expected_blob = governance_state["governance_validator_blob"]
    require(expected_blob != "PENDING", "base-aware validation requires a finalized governance validator Git blob")
    require(isinstance(expected_blob, str), "governance validator Git blob must be text")
    require_sha1(expected_blob, "governance validator Git blob")
    entry = git("ls-tree", candidate_head, "--", VALIDATOR_PATH.as_posix()).stdout.decode("utf-8")
    match = re.fullmatch(r"100644 blob ([0-9a-f]{40})\t" + re.escape(VALIDATOR_PATH.as_posix()) + r"\n", entry)
    require(match is not None, "candidate validator must be one non-executable regular Git blob")
    require(match.group(1) == expected_blob, "DEC validator Git blob differs from the exact candidate tree entry")


def validate_repository(
    base_sha: str | None,
    base_ref: str | None,
    candidate_head: str | None,
    pr_number: int,
    self_test: bool,
) -> dict[str, str | int]:
    dec = read_document(DEC_PATH)
    plan = read_document(PLAN_PATH)
    index = read_document(INDEX_PATH)
    state = parse_triplet(dec, plan, index)
    validate_index_modes()
    validate_source_binding(dec)
    candidate_tree: str | None = None
    if base_sha:
        require(candidate_head is not None, "base-aware validation requires the exact PR candidate head")
        require(not git("status", "--porcelain").stdout, "base-aware validation requires a clean worktree")
        resolved_checkout = git("rev-parse", "HEAD^{commit}").stdout.decode("ascii").strip()
        resolved_candidate = git("rev-parse", f"{candidate_head}^{{commit}}").stdout.decode("ascii").strip()
        require(resolved_candidate == candidate_head, "event/CLI candidate head did not resolve exactly")
        require(git("rev-parse", "--is-shallow-repository").stdout == b"false\n", "base-aware governance validation requires complete non-shallow history")
        candidate_tree = git("rev-parse", f"{candidate_head}^{{tree}}").stdout.decode("ascii").strip()
        checkout_tree = git("rev-parse", f"{resolved_checkout}^{{tree}}").stdout.decode("ascii").strip()
        require(checkout_tree == candidate_tree, "checked-out execution tree differs from the exact candidate tree")
        if resolved_checkout != candidate_head:
            checkout_parents = git("show", "-s", "--format=%P", resolved_checkout).stdout.decode("ascii").strip().split()
            require(checkout_parents == [base_sha, candidate_head], "checkout must be the exact candidate or a synthetic merge with ordered [base,candidate] parents")
        github_sha = os.environ.get("GITHUB_SHA")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            require(github_sha is not None, "GitHub Actions base-aware validation requires GITHUB_SHA")
        if github_sha is not None:
            require(re.fullmatch(r"[0-9a-f]{40}", github_sha) is not None and github_sha == resolved_checkout, "GITHUB_SHA differs from the checked-out commit")
        validate_candidate_validator_blob(candidate_head, state)
        validate_activation_diff(base_sha, base_ref, pr_number, state)
        state["candidate_tree"] = candidate_tree
    if self_test:
        run_self_tests(dec, plan, index)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", help="exact PR base SHA for activation-diff validation")
    parser.add_argument("--base-ref", help="exact PR base ref; required with bootstrap/activation --base-sha")
    parser.add_argument("--head-sha", help="exact PR candidate head SHA; required with explicit CLI PR context")
    parser.add_argument("--pr-number", type=int, default=0, help="current PR number")
    parser.add_argument("--evidence-json", type=Path, action="append", default=[], help="restricted 0600 /tmp gvn-evidence-package-v2 JSON; repeat for start/end/post sequence")
    parser.add_argument("--require-merge-ready", action="store_true", help="require exactly a complete stable-window start/end evidence sequence")
    parser.add_argument("--self-test", action="store_true", help="also execute deterministic negative tests")
    arguments = parser.parse_args()
    try:
        event_kind, event_base, event_base_ref, event_head, event_pr = event_context()
        if arguments.base_sha is not None:
            require(re.fullmatch(r"[0-9a-f]{40}", arguments.base_sha) is not None, "CLI base SHA must be exact lowercase 40-hex")
        if arguments.head_sha is not None:
            require(re.fullmatch(r"[0-9a-f]{40}", arguments.head_sha) is not None, "CLI head SHA must be exact lowercase 40-hex")
        cli_context_present = arguments.base_sha is not None or arguments.base_ref is not None or arguments.head_sha is not None or arguments.pr_number != 0
        if cli_context_present:
            require_positive_int(arguments.pr_number, "CLI PR number")
            require(arguments.base_sha is not None and arguments.base_ref is not None and arguments.head_sha is not None, "CLI PR context requires --base-sha, --base-ref, --head-sha and --pr-number together")
        if event_base is not None and cli_context_present:
            require(
                (arguments.base_sha, arguments.base_ref, arguments.head_sha, arguments.pr_number) == (event_base, event_base_ref, event_head, event_pr),
                "CLI PR context must exactly match GITHUB_EVENT_PATH",
            )
        if event_kind == "push":
            require(not cli_context_present, "push event forbids explicit CLI PR context")
            require(not arguments.evidence_json, "push event forbids --evidence-json")
            require(not arguments.require_merge_ready, "push event forbids --require-merge-ready")
        base_sha = arguments.base_sha or event_base
        base_ref = arguments.base_ref or event_base_ref
        candidate_head = arguments.head_sha or event_head
        pr_number = arguments.pr_number or event_pr
        require(not arguments.require_merge_ready or arguments.evidence_json, "--require-merge-ready requires --evidence-json")
        governance_state = validate_repository(base_sha, base_ref, candidate_head, pr_number, arguments.self_test)
        if arguments.evidence_json:
            current_context = require_complete_current_context(
                base_sha,
                base_ref,
                candidate_head,
                governance_state.get("candidate_tree"),
                pr_number,
            )
            evidence_packages = [read_evidence_package_file(path) for path in arguments.evidence_json]
            authorized_target_type = (
                "activation-evidence"
                if governance_state["status"] == "ACTIVE" and pr_number == governance_state["activation_pr"]
                else None
            )
            validate_evidence_sequence(
                evidence_packages,
                current_context=current_context,
                require_merge_ready=arguments.require_merge_ready,
                authorized_target_type=authorized_target_type,
            )
            validate_activation_evidence_binding(evidence_packages, governance_state, pr_number, SOURCE_COMMIT)
        elif governance_state["status"] == "ACTIVE" and pr_number == governance_state["activation_pr"]:
            fail("activation transition requires the complete candidate-bound evidence sequence")
    except (
        GovernanceValidationError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        yaml.YAMLError,
    ) as exc:
        print(f"governance state validation failed: {exc}", file=sys.stderr)
        return 1
    print("local governance structural validation passed; external GitHub evidence remains separately required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
