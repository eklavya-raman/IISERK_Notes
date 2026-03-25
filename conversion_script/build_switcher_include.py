#!/usr/bin/env python3
"""Build include-after-body HTML by embedding math font manifest before switcher script."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {"fonts": []}

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {"fonts": []}

    if not isinstance(payload, dict):
        return {"fonts": []}

    fonts = payload.get("fonts", [])
    if not isinstance(fonts, list):
        fonts = []

    return {"fonts": fonts}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a switcher include file with embedded font manifest")
    parser.add_argument("--switcher", required=True, help="Path to base pandoc_theme_switcher.html")
    parser.add_argument("--manifest", required=True, help="Path to generated math font manifest JSON")
    parser.add_argument("--output", required=True, help="Output include HTML file")
    args = parser.parse_args()

    switcher_path = Path(args.switcher).resolve()
    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()

    switcher_html = switcher_path.read_text(encoding="utf-8")
    manifest_payload = load_manifest(manifest_path)
    manifest_json = json.dumps(manifest_payload, separators=(",", ":"), ensure_ascii=False)

    injected = (
        "<script>window.__PANDOC_MATH_FONTS_MANIFEST__="
        + manifest_json
        + ";</script>\n"
        + switcher_html
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(injected, encoding="utf-8")
    print(f"[info] Switcher include: '{output_path}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
