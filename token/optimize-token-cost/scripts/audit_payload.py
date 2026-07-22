#!/usr/bin/env python3
"""Audit a synthetic JSON payload without printing its text values."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SECRET_KEYS = {
    "authorization", "cookie", "password", "api_key", "secret",
    "access_token", "refresh_token", "email",
}


class InputError(ValueError):
    pass


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def walk(value: Any, path: str, strings: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SECRET_KEYS:
                raise InputError(f"sensitive field is not allowed: {path}.{key}")
            walk(child, f"{path}.{key}", strings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]", strings)
    elif isinstance(value, str):
        strings.append((path, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit only synthetic or fully sanitized JSON prompt payloads."
    )
    parser.add_argument("payload", type=Path)
    parser.add_argument(
        "--confirm-synthetic", action="store_true",
        help="Required confirmation that the input contains no real user data or credentials."
    )
    parser.add_argument("--min-duplicate-chars", type=int, default=20)
    parser.add_argument("--largest", type=int, default=10)
    parser.add_argument("--chars-per-token", type=float)
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_synthetic:
        print("error: --confirm-synthetic is required", file=sys.stderr)
        return 1
    if args.min_duplicate_chars < 1 or args.largest < 0:
        print("error: numeric limits must be non-negative", file=sys.stderr)
        return 1
    if args.chars_per_token is not None and args.chars_per_token <= 0:
        print("error: --chars-per-token must be greater than zero", file=sys.stderr)
        return 1

    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        strings: list[tuple[str, str]] = []
        walk(payload, "$", strings)
        total_chars = sum(len(value) for _, value in strings)

        by_hash: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for path, value in strings:
            normalized = normalize(value)
            if len(normalized) < args.min_duplicate_chars:
                continue
            fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
            by_hash[fingerprint].append((path, len(normalized)))

        duplicates = []
        avoidable_chars = 0
        for fingerprint, entries in sorted(by_hash.items()):
            if len(entries) < 2:
                continue
            chars = entries[0][1]
            avoidable_chars += (len(entries) - 1) * chars
            duplicates.append({
                "fingerprint": fingerprint,
                "occurrences": len(entries),
                "chars_each": chars,
                "paths": [path for path, _ in entries],
            })

        largest = sorted(
            ({"path": path, "chars": len(value)} for path, value in strings),
            key=lambda item: (-item["chars"], item["path"]),
        )[:args.largest]

        estimated_tokens = None
        if args.chars_per_token is not None:
            estimated_tokens = total_chars / args.chars_per_token

        within_budget = args.max_chars is None or total_chars <= args.max_chars
        output = {
            "schema_version": 1,
            "text_values": len(strings),
            "total_chars": total_chars,
            "estimated_tokens": estimated_tokens,
            "estimate_source": (
                None if args.chars_per_token is None
                else f"user_supplied_chars_per_token={args.chars_per_token}"
            ),
            "duplicate_groups": duplicates,
            "avoidable_duplicate_chars": avoidable_chars,
            "largest_values": largest,
            "budget": {
                "max_chars": args.max_chars,
                "passed": within_budget,
            },
        }
        rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0 if within_budget else 2
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
