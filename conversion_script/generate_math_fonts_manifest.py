#!/usr/bin/env python3
"""Generate a math font manifest from the repository fonts folder."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {".otf", ".ttf", ".woff", ".woff2"}


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-+", "-", lowered).strip("-")
    return lowered or "math-font"


def prettify_label(stem: str) -> str:
    value = re.sub(r"[-_]+", " ", stem).strip()
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    value = re.sub(r"\bregular\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return stem

    tokens = []
    uppercase_words = {"gfs", "stix", "xits", "lm"}
    for token in value.split(" "):
        lower = token.lower()
        if lower in uppercase_words:
            tokens.append(lower.upper())
        elif token.isupper():
            tokens.append(token)
        else:
            tokens.append(token.capitalize())

    return " ".join(tokens)


def make_family_alias(stem: str) -> str:
    return f"Repo Math {prettify_label(stem)}"


def is_math_font_file(path: Path) -> bool:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    return "math" in path.stem.lower()


def collect_fonts(fonts_dir: Path) -> list[dict[str, str]]:
    if not fonts_dir.exists():
        return []

    files = [file for file in fonts_dir.rglob("*") if file.is_file() and is_math_font_file(file)]
    files.sort(key=lambda entry: str(entry.relative_to(fonts_dir)).lower())

    manifest: list[dict[str, str]] = []
    used_values: set[str] = set()

    for file in files:
        relative = file.relative_to(fonts_dir).as_posix()
        stem = file.stem
        value = slugify(stem)
        if value in used_values:
            suffix = 2
            while f"{value}-{suffix}" in used_values:
                suffix += 1
            value = f"{value}-{suffix}"
        used_values.add(value)

        manifest.append(
            {
                "value": value,
                "label": prettify_label(stem),
                "file": relative,
                "family": make_family_alias(stem),
            }
        )

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate repo math font manifest JSON")
    parser.add_argument("--fonts-dir", required=True, help="Directory containing static fonts")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    fonts_dir = Path(args.fonts_dir).resolve()
    output = Path(args.output).resolve()

    manifest = {
        "fonts": collect_fonts(fonts_dir),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[info] Math font manifest: '{output}' ({len(manifest['fonts'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
