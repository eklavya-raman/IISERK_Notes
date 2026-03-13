#!/usr/bin/env python3
"""
Build or refresh an HTML index page for generated documents and add backlinks.

Features:
- Scans an output HTML directory for *.html files (excluding index.html)
- Extracts a human-readable title from each file
- Supports custom per-file title and section metadata
- Rewrites index.html grouped by sections (Course Notes, Assignments, Personal Study)
- Inserts/updates a backlink in each converted HTML file
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


BODY_OPEN_RE = re.compile(r"(<body[^>]*>)", flags=re.IGNORECASE)
SITE_INDEX_LINK_RE = re.compile(
  r"\s*<nav\s+class=\"site-index-link\"[^>]*>[\s\S]*?</nav>\s*",
  flags=re.IGNORECASE,
)
TITLE_H1_RE = re.compile(
  r"<h1[^>]*class=\"[^\"]*\btitle\b[^\"]*\"[^>]*>([\s\S]*?)</h1>",
  flags=re.IGNORECASE,
)
TITLE_TAG_RE = re.compile(r"<title[^>]*>([\s\S]*?)</title>", flags=re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")

SECTION_ORDER = ["course_notes", "assignments", "personal_study", "other"]
SECTION_LABELS = {
  "course_notes": "Course Notes",
  "assignments": "Assignments",
  "personal_study": "Personal Study",
  "other": "Other",
}
SECTION_ALIASES = {
  "course": "course_notes",
  "course_note": "course_notes",
  "course_notes": "course_notes",
  "notes": "course_notes",
  "assignment": "assignments",
  "assignments": "assignments",
  "asgn": "assignments",
  "pset": "assignments",
  "problem_set": "assignments",
  "personal": "personal_study",
  "personal_study": "personal_study",
  "study": "personal_study",
}


def _read_text(path: Path) -> str:
  try:
    return path.read_text(encoding="utf-8")
  except UnicodeDecodeError:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_html(value: str) -> str:
  text = TAG_RE.sub(" ", value)
  text = html.unescape(text)
  text = re.sub(r"\s+", " ", text).strip()
  return text


def _extract_title(page_html: str, fallback: str) -> str:
  h1 = TITLE_H1_RE.search(page_html)
  if h1 is not None:
    title = _strip_html(h1.group(1))
    if title:
      return title

  title_tag = TITLE_TAG_RE.search(page_html)
  if title_tag is not None:
    title = _strip_html(title_tag.group(1))
    if title:
      return title

  return fallback


def _upsert_backlink(page_html: str) -> str:
  clean = SITE_INDEX_LINK_RE.sub("\n", page_html)
  body_match = BODY_OPEN_RE.search(clean)
  if body_match is None:
    return page_html

  insert_at = body_match.end()
  backlink = (
    '\n<nav class="site-index-link">'
    '<a href="index.html" aria-label="Open notes index">&#8592; All Notes Index</a>'
    "</nav>\n"
  )
  return clean[:insert_at] + backlink + clean[insert_at:]


def _normalize_section(value: str | None) -> str:
  if not value:
    return "course_notes"

  key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
  if not key:
    return "course_notes"

  if key in SECTION_LABELS:
    return key
  if key in SECTION_ALIASES:
    return SECTION_ALIASES[key]
  return "other"


def _guess_section_from_filename(file_name: str) -> str:
  lowered = file_name.lower()
  if re.search(r"assign|asgn|assignment|pset|problem_set", lowered):
    return "assignments"
  if re.search(r"lab|experiment|resume|cv|article|personal|bio", lowered):
    return "personal_study"
  return "course_notes"


def _metadata_path(html_dir: Path) -> Path:
  return html_dir / "index_metadata.json"


def _load_metadata(path: Path) -> dict[str, dict[str, dict[str, str]]]:
  if not path.exists():
    return {"files": {}}

  try:
    raw = json.loads(_read_text(path))
  except json.JSONDecodeError:
    return {"files": {}}

  files = raw.get("files") if isinstance(raw, dict) else None
  if not isinstance(files, dict):
    return {"files": {}}

  normalized: dict[str, dict[str, str]] = {}
  for file_name, entry in files.items():
    if not isinstance(file_name, str) or not isinstance(entry, dict):
      continue
    clean_entry: dict[str, str] = {}
    title_value = entry.get("title")
    section_value = entry.get("section")
    if isinstance(title_value, str) and title_value.strip():
      clean_entry["title"] = title_value.strip()
    if isinstance(section_value, str) and section_value.strip():
      clean_entry["section"] = _normalize_section(section_value)
    if clean_entry:
      normalized[file_name] = clean_entry

  return {"files": normalized}


def _save_metadata(path: Path, metadata: dict[str, dict[str, dict[str, str]]]) -> None:
  path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")


def _apply_metadata_override(
  metadata: dict[str, dict[str, dict[str, str]]],
  target_file: str | None,
  title: str | None,
  section: str | None,
) -> None:
  if not target_file:
    return

  file_name = Path(target_file).name
  if not file_name.lower().endswith(".html"):
    file_name = f"{file_name}.html"

  if not title and not section:
    return

  files = metadata.setdefault("files", {})
  entry = files.setdefault(file_name, {})

  if title is not None and title.strip():
    entry["title"] = title.strip()

  if section is not None and section.strip():
    entry["section"] = _normalize_section(section)


def _build_section_html(grouped_items: dict[str, list[tuple[str, str]]]) -> str:
  sections: list[str] = []

  for section_key in SECTION_ORDER:
    items = grouped_items.get(section_key, [])
    if not items:
      continue

    items.sort(key=lambda pair: pair[1].lower())
    list_items = "\n".join(
      f'        <li><a href="{html.escape(file_name, quote=True)}">{html.escape(title)}</a></li>'
      for file_name, title in items
    )

    section_id = f"section-{section_key}"
    sections.append(
      "\n".join(
        [
          f'    <section id="{section_id}" class="panel">',
          f"      <h2>{html.escape(SECTION_LABELS[section_key])}</h2>",
          "      <ul>",
          list_items,
          "      </ul>",
          "    </section>",
        ]
      )
    )

  if not sections:
    return (
      '    <section class="panel">\n'
      "      <h2>Course Notes</h2>\n"
      "      <ul><li>No converted files found yet.</li></ul>\n"
      "    </section>"
    )

  return "\n\n".join(sections)


def _write_index(index_path: Path, grouped_items: dict[str, list[tuple[str, str]]], total_files: int) -> None:
  now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
  section_links = " ".join(
    f'<a href="#section-{key}">{html.escape(SECTION_LABELS[key])}</a>' for key in SECTION_ORDER if grouped_items.get(key)
  )
  section_html = _build_section_html(grouped_items)

  page = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Notes Index</title>
  <style>
  :root {{
    color-scheme: light dark;
    --bg: #f6f8fb;
    --panel: #ffffff;
    --text: #1d2638;
    --muted: #63708a;
    --link: #2e62c6;
    --border: #d5dced;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
    --bg: #0f1420;
    --panel: #161f2f;
    --text: #deebff;
    --muted: #9eb0d1;
    --link: #8ab7ff;
    --border: #2d3d59;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: Inter, Segoe UI, Roboto, Arial, sans-serif;
    line-height: 1.55;
  }}
  main {{
    max-width: 72rem;
    margin: 2rem auto;
    padding: 0 1rem;
    display: grid;
    gap: .9rem;
  }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem 1.1rem;
  }}
  h1, h2 {{ margin: 0 0 .45rem; }}
  p {{ margin: .25rem 0 .75rem; color: var(--muted); }}
  ul {{ margin: 0; padding-left: 1.2rem; }}
  li + li {{ margin-top: .35rem; }}
  a {{ color: var(--link); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .meta {{ margin-top: .9rem; font-size: .9rem; color: var(--muted); }}
  .section-links {{ display: flex; flex-wrap: wrap; gap: .75rem; margin: .45rem 0 0; }}
  </style>
</head>
<body>
  <main>
  <section class=\"panel\">
    <h1>Notes Index</h1>
    <p>Open converted pages by section.</p>
    <div class=\"section-links\">{section_links}</div>
    <div class=\"meta\">Updated: {html.escape(now_utc)} · Files: {total_files}</div>
  </section>

{section_html}
  </main>
</body>
</html>
"""
  index_path.write_text(page, encoding="utf-8")


def update_index(
  html_dir: Path,
  target_file: str | None = None,
  custom_title: str | None = None,
  custom_section: str | None = None,
) -> tuple[int, int]:
  metadata_file = _metadata_path(html_dir)
  metadata = _load_metadata(metadata_file)
  _apply_metadata_override(metadata, target_file, custom_title, custom_section)

  html_files = sorted(path for path in html_dir.glob("*.html") if path.name.lower() != "index.html")
  grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
  updated_pages = 0

  existing_names = {page.name for page in html_files}
  files_meta = metadata.setdefault("files", {})
  for key in list(files_meta.keys()):
    if key not in existing_names:
      files_meta.pop(key, None)

  for page in html_files:
    source = _read_text(page)
    meta = files_meta.get(page.name, {})

    title = meta.get("title") if isinstance(meta, dict) else None
    if not title:
      title = _extract_title(source, fallback=page.stem.replace("_", " ").strip())

    section = meta.get("section") if isinstance(meta, dict) else None
    section = _normalize_section(section) if section else _guess_section_from_filename(page.name)

    grouped[section].append((page.name, title))

    updated = _upsert_backlink(source)
    if updated != source:
      page.write_text(updated, encoding="utf-8")
      updated_pages += 1

    clean_entry: dict[str, str] = {}
    if isinstance(meta, dict) and meta.get("title"):
      clean_entry["title"] = meta["title"]
    clean_entry["section"] = section
    files_meta[page.name] = clean_entry

  _save_metadata(metadata_file, metadata)
  _write_index(html_dir / "index.html", grouped, total_files=len(html_files))
  return len(html_files), updated_pages


def main() -> int:
  parser = argparse.ArgumentParser(description="Update index.html and backlinks for converted HTML files.")
  parser.add_argument("--html-dir", required=True, help="Directory containing generated HTML files.")
  parser.add_argument("--target-file", help="HTML file name or path whose metadata should be updated.")
  parser.add_argument("--title", help="Custom title for --target-file.")
  parser.add_argument("--section", help="Section for --target-file (course notes / assignments / personal study).")
  args = parser.parse_args()

  html_dir = Path(args.html_dir).expanduser().resolve()
  if not html_dir.exists() or not html_dir.is_dir():
    print(f"[error] HTML directory not found: {html_dir}")
    return 1

  file_count, updated_pages = update_index(
    html_dir=html_dir,
    target_file=args.target_file,
    custom_title=args.title,
    custom_section=args.section,
  )
  print(f"[ok] Updated index: {html_dir / 'index.html'}")
  print(f"[ok] Linked files: {file_count}, backlinks refreshed: {updated_pages}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
