#!/usr/bin/env python3
"""Reject representative credential material before it enters the repository."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_SCANNED_FILE_BYTES = 2 * 1024 * 1024
EXCLUDED_DIRECTORIES = {
    ".agents",
    ".codegraph",
    ".codex",
    ".git",
    ".idea",
    ".venv",
    "node_modules",
    "target",
    "venv",
}

SECRET_PATTERNS = (
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    ),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Alibaba Cloud access key", re.compile(r"\bLTAI[0-9A-Za-z]{12,20}\b")),
    ("Tencent Cloud secret ID", re.compile(r"\bAKID[0-9A-Za-z]{13,40}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,255}\b")),
    ("GitLab token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_-]{20,}\b")),
    (
        "QingYin project credential",
        re.compile(r"\bqy_(?:live|test)_[0-9A-Za-z_-]{16,}\b"),
    ),
    (
        "Authorization bearer value",
        re.compile(r"(?i)\bBearer\s+[0-9A-Za-z._~+/-]{20,}={0,2}\b"),
    ),
    (
        "inline credential assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\b"
            r"\s*[:=]\s*[\"'][0-9A-Za-z_./+=-]{20,}[\"']"
        ),
    ),
)

REPRESENTATIVE_VALUES = {
    "private key": "-----BEGIN " + "PRIVATE KEY-----",
    "AWS access key": "AKIA" + "A" * 16,
    "Alibaba Cloud access key": "LTAI" + "a" * 16,
    "Tencent Cloud secret ID": "AKID" + "a" * 20,
    "Google API key": "AIza" + "A" * 35,
    "GitHub token": "ghp_" + "A" * 36,
    "GitLab token": "glpat-" + "a" * 20,
    "Slack token": "xoxb-" + "a" * 20,
    "OpenAI-style key": "sk-" + "a" * 20,
    "QingYin project credential": "qy_" + "live_" + "a" * 16,
    "Authorization bearer value": "Bearer " + "a" * 20,
    "inline credential assignment": "api_key = \"" + "a" * 20 + "\"",
}


def candidate_files() -> list[Path]:
    """Return bounded UTF-8 candidates while excluding tools and build output."""
    candidates: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
            continue
        candidates.append(path)
    return sorted(candidates)


def main() -> None:
    """Scan source text without echoing any matched credential material."""
    for label, pattern in SECRET_PATTERNS:
        representative = REPRESENTATIVE_VALUES[label]
        if pattern.search(representative) is None:
            raise SystemExit(f"secret regression self-test failed: {label}")

    findings: list[str] = []
    scanned = 0
    for path in candidate_files():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        relative = path.relative_to(ROOT)
        for line_number, line in enumerate(content.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{relative}:{line_number}: potential {label}")

    if findings:
        raise SystemExit("secret regression scan failed:\n" + "\n".join(findings))
    print(f"secret regression scan OK ({scanned} UTF-8 files)")


if __name__ == "__main__":
    main()
