#!/usr/bin/env python3
"""
Interactive converter launcher for Windows.

Features:
- Scans tex_files/white for .tex files
- Shows numbered list for selection
- Supports multi-selection (e.g. 1,3-5)
- Supports recompile-all via `all`
- Supports recompile-linked via `linked`
- Supports linking TeX files to existing HTML files via `link`
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

QUIT_INPUTS = {"q", "quit", "exit"}
BACK_INPUTS = {"b", "back"}
ALL_INPUTS = {"all", "a", "*"}
LINKED_INPUTS = {"linked", "mapped", "m"}
LINK_INPUTS = {"link", "l"}
YES_INPUTS = {"y", "yes"}

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

LINKS_FILE_NAME = "tex_html_links.map"


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


def _prompt_image_base_url(default_url: str) -> str:
    hint = "External image base URL (optional, e.g. https://cdn.example.com/images_folder)"
    if default_url:
        raw = input(f"{hint} [current: {default_url}]: ").strip()
        return raw or default_url
    return input(f"{hint}: ").strip()


def _display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(path)


def _to_abs_path(raw_path: str, workspace_root: Path) -> Path:
    candidate = Path(raw_path.strip().strip('"').strip("'"))
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    return candidate.expanduser().resolve()


def _links_file_path(workspace_root: Path) -> Path:
    return workspace_root / "conversion_script" / LINKS_FILE_NAME


def _read_links(links_file: Path) -> dict[str, tuple[Path, Path]]:
    if not links_file.exists():
        return {}

    try:
        content = links_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = links_file.read_text(encoding="utf-8", errors="replace")

    links: dict[str, tuple[Path, Path]] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue

        tex_raw, html_raw = line.split("|", 1)
        tex_value = tex_raw.strip()
        html_value = html_raw.strip()
        if not tex_value or not html_value:
            continue

        tex_path = Path(tex_value).expanduser().resolve()
        html_path = Path(html_value).expanduser().resolve()
        links[str(tex_path).lower()] = (tex_path, html_path)

    return links


def _write_links(links_file: Path, links: dict[str, tuple[Path, Path]]) -> None:
    ordered_pairs = sorted(links.values(), key=lambda pair: str(pair[0]).lower())
    payload = "\n".join(f"{tex_path}|{html_path}" for tex_path, html_path in ordered_pairs)
    if payload:
        payload = f"{payload}\n"
    links_file.write_text(payload, encoding="utf-8")


def _get_linked_html(workspace_root: Path, tex_file: Path) -> Path | None:
    links_file = _links_file_path(workspace_root)
    links = _read_links(links_file)
    key = str(tex_file.expanduser().resolve()).lower()
    entry = links.get(key)
    if entry is None:
        return None
    return entry[1]


def _set_linked_html(workspace_root: Path, tex_file: Path, html_file: Path) -> Path:
    links_file = _links_file_path(workspace_root)
    links = _read_links(links_file)
    tex_abs = tex_file.expanduser().resolve()
    html_abs = html_file.expanduser().resolve()
    links[str(tex_abs).lower()] = (tex_abs, html_abs)
    _write_links(links_file, links)
    return links_file


def _collect_linked_entries(
    workspace_root: Path,
    files: list[Path],
) -> list[tuple[int, Path, Path]]:
    entries: list[tuple[int, Path, Path]] = []
    for index, tex_file in enumerate(files, start=1):
        linked_html = _get_linked_html(workspace_root, tex_file)
        if linked_html is None:
            continue
        entries.append((index, tex_file, linked_html))
    return entries


def _list_html_files(html_dir: Path) -> list[Path]:
    if not html_dir.exists() or not html_dir.is_dir():
        return []
    return sorted(path for path in html_dir.glob("*.html") if path.is_file())


def _display_html_files(files: list[Path], html_dir: Path) -> None:
    print("\nAvailable HTML files in html/:\n")
    for idx, file_path in enumerate(files, start=1):
        rel = file_path.relative_to(html_dir)
        print(f"  {idx:>3}. {rel.as_posix()}")
    print()


def _prompt_existing_html_target(workspace_root: Path, html_files: list[Path]) -> Path | None:
    while True:
        raw = input("Pick HTML number or enter existing HTML path (b to back): ").strip()
        lowered = raw.lower()

        if not raw:
            print("[error] Please enter an HTML file number or path.")
            continue

        if lowered in BACK_INPUTS or lowered in QUIT_INPUTS:
            return None

        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(html_files):
                return html_files[index - 1]
            print(f"[error] Selection out of range: {index}")
            continue

        candidate = _to_abs_path(raw, workspace_root)
        if candidate.suffix.lower() != ".html":
            print("[error] Target must be an existing .html file.")
            continue
        if not candidate.exists() or not candidate.is_file():
            print(f"[error] HTML file not found: {candidate}")
            continue
        return candidate


def _run_link_mode(workspace_root: Path, white_dir: Path, files: list[Path]) -> None:
    html_dir = workspace_root / "html"

    while True:
        _display_files(files, white_dir)
        raw = input("Pick TeX file number to link (b to back): ").strip()
        lowered = raw.lower()

        if lowered in BACK_INPUTS or lowered in QUIT_INPUTS:
            return

        try:
            index = int(raw)
        except ValueError:
            print("[error] Please enter a valid file number.")
            continue

        if index < 1 or index > len(files):
            print(f"[error] Selection out of range: {index}")
            continue

        tex_file = files[index - 1]
        print(f"\nSelected TeX: {tex_file.relative_to(white_dir).as_posix()}")

        existing_link = _get_linked_html(workspace_root, tex_file)
        if existing_link is not None:
            print(f"Current linked HTML: {_display_path(existing_link, workspace_root)}")

        html_files = _list_html_files(html_dir)
        if html_files:
            _display_html_files(html_files, html_dir)
        else:
            print("\n[warn] No HTML files found in html/. Enter a full path to an existing HTML file.\n")

        html_target = _prompt_existing_html_target(workspace_root, html_files)
        if html_target is None:
            continue

        links_file = _set_linked_html(workspace_root, tex_file, html_target)
        print(f"[ok] Linked {_display_path(tex_file, workspace_root)} -> {_display_path(html_target, workspace_root)}")
        print(f"[ok] Saved mapping file: {_display_path(links_file, workspace_root)}")

        again = input("Link another file? [y/N]: ").strip().lower()
        if again not in YES_INPUTS:
            return


def _run_conversion(
    workspace_root: Path,
    tex_file: Path,
    custom_title: str,
    section: str | None,
    image_base_url: str,
) -> int:
    converter_bat = workspace_root / "conversion_script" / "convert_tex_to_html.bat"

    env = os.environ.copy()
    if custom_title:
        env["NOTES_CUSTOM_TITLE"] = custom_title
    else:
        env.pop("NOTES_CUSTOM_TITLE", None)
    if section:
        env["NOTES_SECTION"] = section
    else:
        env.pop("NOTES_SECTION", None)
    if image_base_url:
        env["NOTES_IMAGE_BASE_URL"] = image_base_url
    else:
        env.pop("NOTES_IMAGE_BASE_URL", None)

    print(f"\n[run] Converting: {tex_file}")
    if custom_title:
        print(f"      title  : {custom_title}")
    if section:
        print(f"      section: {section}")
    if image_base_url:
        print(f"      images : {image_base_url}")

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
        raw = input(
            "Pick file numbers (e.g. 1,3-5), 'all' for all files, 'linked' for mapped files, 'link' to map TeX->HTML, or q to quit: "
        ).strip()
        lowered = raw.lower()
        if lowered in QUIT_INPUTS:
            print("[done] Exiting converter launcher.")
            return 0

        if lowered in LINK_INPUTS:
            _run_link_mode(workspace_root, white_dir, files)
            continue

        bulk_mode: str | None = None

        if lowered in ALL_INPUTS:
            confirm = input(f"Recompile all {len(files)} TeX files? [y/N]: ").strip().lower()
            if confirm not in YES_INPUTS:
                print("[info] Recompile-all canceled.")
                continue
            selected_indices = list(range(1, len(files) + 1))
            bulk_mode = "all"
        elif lowered in LINKED_INPUTS:
            linked_entries = _collect_linked_entries(workspace_root, files)
            if not linked_entries:
                print("[warn] No linked TeX->HTML mappings found. Use 'link' first.")
                continue

            print(f"[info] Found {len(linked_entries)} mapped TeX files.")
            confirm = input(f"Recompile only these {len(linked_entries)} mapped files? [y/N]: ").strip().lower()
            if confirm not in YES_INPUTS:
                print("[info] Recompile-linked canceled.")
                continue

            selected_indices = [index for index, _, _ in linked_entries]
            bulk_mode = "linked"
        else:
            try:
                selected_indices = _parse_selection(raw, len(files))
            except ValueError as error:
                print(f"[error] {error}")
                continue

        image_base_url = _prompt_image_base_url(os.environ.get("NOTES_IMAGE_BASE_URL", "").strip())

        if bulk_mode is not None:
            mode_label = "mapped" if bulk_mode == "linked" else "all"
            print(f"\n[info] Recompiling {len(selected_indices)} {mode_label} files using linked/default HTML outputs...")
            for index in selected_indices:
                tex_file = files[index - 1]
                linked_output = _get_linked_html(workspace_root, tex_file)
                if linked_output is not None:
                    print(f"      output : {_display_path(linked_output, workspace_root)}")
                rc = _run_conversion(
                    workspace_root=workspace_root,
                    tex_file=tex_file,
                    custom_title="",
                    section=None,
                    image_base_url=image_base_url,
                )
                if rc != 0:
                    print(f"[error] Conversion failed for {tex_file.name} (exit code {rc})")
                else:
                    print(f"[ok] Conversion complete for {tex_file.name}")
        else:
            for index in selected_indices:
                tex_file = files[index - 1]
                suggested_title = tex_file.stem.replace("_", " ").strip()
                print(f"\nSelected: {tex_file.relative_to(white_dir).as_posix()}")
                linked_output = _get_linked_html(workspace_root, tex_file)
                if linked_output is not None:
                    print(f"Linked HTML: {_display_path(linked_output, workspace_root)}")
                title = input(f"Custom title (Enter for auto, suggested: '{suggested_title}'): ").strip()
                section = _prompt_section(_guess_section(tex_file.name))
                rc = _run_conversion(workspace_root, tex_file, title, section, image_base_url)
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
