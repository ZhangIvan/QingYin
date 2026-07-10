"""Verify repository-local Markdown links used by QingYin navigation indexes."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_FILES = (ROOT / "docs",)
ROOT_MARKDOWN_FILES = (ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md")


def is_external(target: str) -> bool:
    return target.startswith(("#", "http://", "https://", "mailto:"))


def markdown_files() -> list[Path]:
    files = list(ROOT_MARKDOWN_FILES)
    for directory in MARKDOWN_FILES:
        files.extend(directory.rglob("*.md"))
    return files


def main() -> int:
    missing: list[str] = []
    for source in markdown_files():
        if not source.is_file():
            missing.append(f"required Markdown file is missing: {source.relative_to(ROOT)}")
            continue

        for raw_target in MARKDOWN_LINK.findall(source.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            if is_external(target):
                continue

            path_text = target.split("#", maxsplit=1)[0]
            if not path_text:
                continue
            destination = (source.parent / path_text).resolve()
            if not destination.is_file():
                missing.append(
                    f"{source.relative_to(ROOT)} -> {raw_target} does not resolve to a file"
                )

    if missing:
        print("Markdown link validation failed:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in missing), file=sys.stderr)
        return 1

    print("Markdown link validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
