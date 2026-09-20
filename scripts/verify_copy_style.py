#!/usr/bin/env python3
"""Enforce durable punctuation rules for user-facing website copy."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOTS = (ROOT / "apps" / "client" / "app", ROOT / "apps" / "client" / "src")
SOURCE_SUFFIXES = {".css", ".html", ".js", ".jsx", ".ts", ".tsx"}
DISALLOWED_EM_DASH = chr(0x2014)


def main() -> int:
    violations: list[str] = []
    for source_root in CLIENT_ROOTS:
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if DISALLOWED_EM_DASH in line:
                    violations.append(f"{path.relative_to(ROOT)}:{line_number}")

    if violations:
        print("Website copy must not use em dashes. Replace them with clearer punctuation:")
        print("\n".join(violations))
        return 1

    print("Website copy style check passed: no em dashes found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
