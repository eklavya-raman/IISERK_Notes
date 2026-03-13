#!/usr/bin/env python3
"""
Interactive converter launcher for Windows.

Features:
- Scans tex_files/white for .tex files
- Shows numbered list for selection
- Supports multi-selection (e.g. 1,3-5)
- Allows custom title + section per file
- Runs successive conversions via convert_tex_to_html.bat

This script is intended to be packaged as an EXE (PyInstaller).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SECTION_OPTIONS = [
    ("course_notes", "Course Notes"),
    ("assignments", "Assignments"),
    ("personal_study", "Personal Study"),
]

SECTION_ALIASES = {
    "1": "course_notes",
    "2": "assignments",
    "3": "personal_study",
    "course": "course_notes",
    "course_notes": "course_notes",
    "course notes": "course_notes",
    "assignment": "assignments",
    "assignments": "assignments",
    "personal": "personal_study",
    "personal_study": "personal_study",
    "personal study": "personal_study",
    "study": "personal_study",
}


def _find_workspace_root() -> Path:
    candidates: list[Path] = []

    cwd = Path.cwd().resolve()
    candidates.extend([cwd, cwd.parent])

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])
    else:
        script_dir = Path(__file__).resolve().parent
        candidates.extend([script_dir.parent, script_dir.parent.parent])

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(path)

    for root in unique_candidates:
        if (root / "conversion_script" / "convert_tex_to_html.bat").exists() and (root / "tex_files" / "white").exists():
            return root

    raise FileNotFoundError(
        "Could not locate workspace root containing conversion_script/convert_tex_to_html.bat and tex_files/white"
    )


def _list_tex_files(white_dir: Path) -> list[Path]:
    return sorted(path for path in white_dir.rglob("*.tex") if path.is_file())


def _display_files(files: list[Path], white_dir: Path) -> None:
    print("\nAvailable TeX files in tex_files/white:\n")
    for idx, file_path in enumerate(files, start=1):
        rel = file_path.relative_to(white_dir)
        print(f"  {idx:>3}. {rel.as_posix()}")
    print()


def _parse_selection(raw: str, total: int) -> list[int]:
    parts = [token for token in re.split(r"[\s,]+", raw.strip()) if token]
    selected: set[int] = set()

    for part in parts:
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start = int(start_s)
                end = int(end_s)
            except ValueError as exc:
                raise ValueError(f"Invalid range: {part}") from exc

            if start > end:
                start, end = end, start

            for value in range(start, end + 1):
                if value < 1 or value > total:
                    raise ValueError(f"Selection out of range: {value}")
                selected.add(value)
        else:
            try:
                value = int(part)
            except ValueError as exc:
                raise ValueError(f"Invalid number: {part}") from exc

            if value < 1 or value > total:
                raise ValueError(f"Selection out of range: {value}")
            selected.add(value)

    return sorted(selected)


def _guess_section(file_name: str) -> str:
    lowered = file_name.lower()
    if re.search(r"assign|asgn|assignment|pset|problem_set", lowered):
        return "assignments"
    if re.search(r"lab|experiment|resume|cv|article|personal|bio", lowered):
        return "personal_study"
    return "course_notes"


def _prompt_section(default_section: str) -> str:
    default_label = dict(SECTION_OPTIONS).get(default_section, "Course Notes")

    print("Section options:")
    print("  1) Course Notes")
    print("  2) Assignments")
    print("  3) Personal Study")
    raw = input(f"Choose section [{default_label}]: ").strip().lower()

    if not raw:
        return default_section

    chosen = SECTION_ALIASES.get(raw)
    if chosen is None:
        print("  [warn] Unknown section; using default.")
        return default_section
    return chosen


def _run_conversion(workspace_root: Path, tex_file: Path, custom_title: str, section: str) -> int:
    converter_bat = workspace_root / "conversion_script" / "convert_tex_to_html.bat"

    env = os.environ.copy()
    if custom_title:
        env["NOTES_CUSTOM_TITLE"] = custom_title
    else:
        env.pop("NOTES_CUSTOM_TITLE", None)
    env["NOTES_SECTION"] = section

    print(f"\n[run] Converting: {tex_file}")
    if custom_title:
        print(f"      title  : {custom_title}")
    print(f"      section: {section}")

    completed = subprocess.run(
        [str(converter_bat), str(tex_file)],
        cwd=workspace_root,
        env=env,
        check=False,
    )
    return completed.returncode


def main() -> int:
    try:
        workspace_root = _find_workspace_root()
    except FileNotFoundError as error:
        print(f"[error] {error}")
        return 1

    white_dir = workspace_root / "tex_files" / "white"

    while True:
        files = _list_tex_files(white_dir)
        if not files:
            print(f"[error] No .tex files found under: {white_dir}")
            return 1

        _display_files(files, white_dir)
        raw = input("Pick file numbers (e.g. 1,3-5) or q to quit: ").strip()
        if raw.lower() in {"q", "quit", "exit"}:
            print("[done] Exiting converter launcher.")
            return 0

        try:
            selected_indices = _parse_selection(raw, len(files))
        except ValueError as error:
            print(f"[error] {error}")
            continue

        for index in selected_indices:
            tex_file = files[index - 1]
            suggested_title = tex_file.stem.replace("_", " ").strip()
            print(f"\nSelected: {tex_file.relative_to(white_dir).as_posix()}")
            title = input(f"Custom title (Enter for auto, suggested: '{suggested_title}'): ").strip()
            section = _prompt_section(_guess_section(tex_file.name))
            rc = _run_conversion(workspace_root, tex_file, title, section)
            if rc != 0:
                print(f"[error] Conversion failed for {tex_file.name} (exit code {rc})")
            else:
                print(f"[ok] Conversion complete for {tex_file.name}")

        again = input("\nConvert more files? [Y/n]: ").strip().lower()
        if again in {"n", "no"}:
            print("[done] Exiting converter launcher.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
