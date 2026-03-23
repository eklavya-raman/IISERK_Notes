#!/usr/bin/env python3
"""
Post-process pandoc-generated HTML to add:
- theorem-like numbering and boxed rendering,
- list of theorems,
- tikz placeholder image insertion,
- responsive table wrappers.
"""

from __future__ import annotations

import argparse
import html
import os
import re
from collections import defaultdict
from pathlib import Path


BODY_RE = re.compile(r"(<body[^>]*>)([\s\S]*?)(</body>)", flags=re.IGNORECASE)
HEADING_RE = re.compile(r"<h([1-6])([^>]*)>([\s\S]*?)</h\1>", flags=re.IGNORECASE)
BOX_BOUNDARY_RE = re.compile(r"<h[1-6]\b|<div class=\"corollary\">", flags=re.IGNORECASE)
DIV_COROLLARY_RE = re.compile(r"<div class=\"corollary\">([\s\S]*?)</div>", flags=re.IGNORECASE)
DIV_PROOF_RE = re.compile(r"<div class=\"proof\">([\s\S]*?)</div>", flags=re.IGNORECASE)
THEOREM_BOX_OPEN_RE = re.compile(
    r'<div class="[^"]*\btheorem-box\b[^"]*"[^>]*data-number="([^"]+)"[^>]*>',
    flags=re.IGNORECASE,
)
TOC_FIRST_UL_RE = re.compile(r'(<nav[^>]*id="TOC"[^>]*>[\s\S]*?<ul[^>]*>)', flags=re.IGNORECASE)
TABLE_RE = re.compile(r"<table\b[\s\S]*?</table>", flags=re.IGNORECASE)
TIKZ_PLACEHOLDER_RE = re.compile(
    r"<p>\s*\[\[TIKZ_IMAGE\|([^\]]+)\]\]\s*</p>",
    flags=re.IGNORECASE,
)
GENERIC_TIKZ_CAPTION_RE = re.compile(r"^(?:tikzpicture|circuitikz)\s+\d+$", flags=re.IGNORECASE)

LABEL_RE = re.compile(
    r"^(Definition|Theorem|Identity|Axiom|Note|Exercise|Example|Solution|Solutions|Proof|Key Result|Highlight|Box)"
    r"\s*(?:\((.*)\))?[\.:]?$",
    flags=re.IGNORECASE,
)

LABEL_CLASS_MAP = {
    "definition": "definition-box",
    "theorem": "theorem-box",
    "identity": "identity-box",
    "axiom": "axiom-box",
    "note": "note-box",
    "exercise": "exercise-box",
    "example": "example-box",
    "solution": "solution-box",
    "proof": "proof-box",
    "key result": "keyresult-box",
    "highlight": "highlight-box",
    "box": "generic-box",
}

THEOREM_LIST_LABELS = {"Theorem", "Corollary"}
ABSOLUTE_URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", flags=re.IGNORECASE)


def _strip_tags(value: str) -> str:
    clean = re.sub(r"<[^>]+>", "", value)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _slugify(value: str) -> str:
    slug = value.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        return "block"
    return slug


def _parse_heading_label(inner_html: str) -> tuple[str, str | None] | None:
    plain = _strip_tags(inner_html)
    plain = re.sub(r"^\d+(?:\.\d+)*\s+", "", plain)
    match = LABEL_RE.match(plain)
    if match is None:
        return None

    label = match.group(1)
    if label.lower() == "solutions":
        label = "Solution"
    else:
        label = label[0].upper() + label[1:].lower()

    title = match.group(2)
    if title is not None:
        title = title.strip().rstrip(".")
        if not title:
            title = None

    return label, title


def _extract_heading_title_html(inner_html: str, label: str) -> str | None:
    title_html = re.sub(
        r'^\s*<span[^>]*class="header-section-number"[^>]*>[\s\S]*?</span>\s*',
        "",
        inner_html,
        flags=re.IGNORECASE,
    )
    title_html = re.sub(rf"^\s*{re.escape(label)}\s*", "", title_html, flags=re.IGNORECASE)
    title_html = title_html.strip()
    title_html = re.sub(r"^[\.:]\s*", "", title_html)
    title_html = re.sub(r"\s*[\.:]\s*$", "", title_html)

    if title_html.startswith("(") and title_html.endswith(")"):
        title_html = title_html[1:-1].strip()

    if not title_html:
        return None
    return title_html


def _context_key(section_counts: list[int]) -> tuple[int, ...]:
    parts = tuple(number for number in section_counts[1:4] if number > 0)
    if not parts:
        return (0,)
    return parts


def _parse_heading_data_number(heading_attrs: str) -> list[int] | None:
    match = re.search(r'data-number="([^"]+)"', heading_attrs)
    if match is None:
        return None

    numbers = [int(token) for token in re.findall(r"\d+", match.group(1))]
    if not numbers:
        return None
    return numbers


def _format_number(context: tuple[int, ...], value: int) -> str:
    if context == (0,):
        return str(value)
    prefix = ".".join(str(number) for number in context)
    return f"{prefix}.{value}"


def _wrap_heading_boxes(body: str) -> tuple[str, list[tuple[str, str]]]:
    theorem_entries: list[tuple[str, str]] = []
    result: list[str] = []
    section_counts = [0, 0, 0, 0, 0, 0, 0]
    counters: dict[str, dict[str, tuple[int, ...] | int | None]] = defaultdict(
        lambda: {"context": None, "value": 0}
    )

    cursor = 0
    while True:
        heading = HEADING_RE.search(body, cursor)
        if heading is None:
            result.append(body[cursor:])
            break

        heading_start, heading_end = heading.span()
        result.append(body[cursor:heading_start])

        level = int(heading.group(1))
        heading_attrs = heading.group(2)
        full_heading = heading.group(0)
        inner_html = heading.group(3)
        parsed = _parse_heading_label(inner_html)

        if parsed is None:
            heading_numbers = _parse_heading_data_number(heading_attrs)
            if heading_numbers is not None:
                for index in range(1, len(section_counts)):
                    section_counts[index] = 0
                for index, value in enumerate(heading_numbers, start=1):
                    if index < len(section_counts):
                        section_counts[index] = value
            result.append(full_heading)
            cursor = heading_end
            continue

        label, title = parsed
        context = _context_key(section_counts)

        counter_state = counters[label]
        if counter_state["context"] != context:
            counter_state["context"] = context
            counter_state["value"] = 0

        counter_state["value"] = int(counter_state["value"]) + 1
        number = _format_number(context, int(counter_state["value"]))

        boundary = BOX_BOUNDARY_RE.search(body, heading_end)
        content_end = boundary.start() if boundary else len(body)
        content = body[heading_end:content_end].strip()

        heading_text = f"{label} {number}"
        if title:
            heading_text = f"{heading_text} ({title})"

        title_html = _extract_heading_title_html(inner_html, label)
        heading_html = f"{html.escape(label)} {html.escape(number)}"
        if title_html:
            heading_html = f"{heading_html} ({title_html})"
        elif title:
            heading_html = f"{heading_html} ({html.escape(title)})"

        block_id = _slugify(f"{label}-{number}-{title or ''}")
        style_class = LABEL_CLASS_MAP.get(label.lower(), "generic-box")
        box_html = (
            f'<div class="latex-box {style_class}" id="{block_id}" '
            f'data-label="{html.escape(label)}" data-number="{html.escape(number)}">\n'
            f'  <div class="latex-box-title">{heading_html}</div>\n'
            f'  <div class="latex-box-body">\n{content}\n  </div>\n'
            f'</div>\n'
        )

        result.append(box_html)
        if label in THEOREM_LIST_LABELS:
            theorem_entries.append((heading_html, block_id))

        cursor = content_end

    return "".join(result), theorem_entries


def _wrap_corollary_div_boxes(body: str, theorem_entries: list[tuple[str, str]]) -> str:
    result: list[str] = []
    cursor = 0
    current_theorem_number: str | None = None
    per_theorem_corollaries: dict[str, int] = defaultdict(int)
    global_corollary_counter = 0

    while cursor < len(body):
        theorem_match = THEOREM_BOX_OPEN_RE.search(body, cursor)
        corollary_match = DIV_COROLLARY_RE.search(body, cursor)

        next_match: re.Match[str] | None = None
        next_kind: str | None = None

        if theorem_match is not None and corollary_match is not None:
            if theorem_match.start() <= corollary_match.start():
                next_match = theorem_match
                next_kind = "theorem"
            else:
                next_match = corollary_match
                next_kind = "corollary"
        elif theorem_match is not None:
            next_match = theorem_match
            next_kind = "theorem"
        elif corollary_match is not None:
            next_match = corollary_match
            next_kind = "corollary"

        if next_match is None or next_kind is None:
            result.append(body[cursor:])
            break

        result.append(body[cursor : next_match.start()])

        if next_kind == "theorem":
            current_theorem_number = html.unescape(next_match.group(1)).strip() or None
            result.append(next_match.group(0))
            cursor = next_match.end()
            continue

        content = next_match.group(1).strip()
        if current_theorem_number:
            per_theorem_corollaries[current_theorem_number] += 1
            number = f"{current_theorem_number}.{per_theorem_corollaries[current_theorem_number]}"
        else:
            global_corollary_counter += 1
            number = str(global_corollary_counter)

        heading_text = f"Corollary {number}"
        heading_html = html.escape(heading_text)
        block_id = _slugify(f"corollary-{number}")
        theorem_entries.append((heading_html, block_id))
        result.append(
            f'<div class="latex-box corollary-box" id="{block_id}" data-label="Corollary" data-number="{number}">\n'
            f'  <div class="latex-box-title">{heading_text}</div>\n'
            f'  <div class="latex-box-body">\n{content}\n  </div>\n'
            f'</div>'
        )
        cursor = next_match.end()

    return "".join(result)


def _inline_proof_divs(body: str) -> str:
    def proof_repl(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        content = re.sub(
            r"^\s*<p>\s*(?:<(?:em|strong)>\s*)?Proof\.?\s*(?:</(?:em|strong)>\s*)?",
            "<p>",
            content,
            flags=re.IGNORECASE,
        )
        return (
            '<div class="theorem-proof" data-label="Proof">\n'
            '  <div class="theorem-proof-title">Proof</div>\n'
            f'  <div class="theorem-proof-body">\n{content}\n  </div>\n'
            '</div>'
        )

    return DIV_PROOF_RE.sub(proof_repl, body)


def _add_theorem_link_to_toc(body: str) -> str:
    if 'href="#list-of-theorems"' in body:
        return body

    toc_match = TOC_FIRST_UL_RE.search(body)
    if toc_match is None:
        return body

    insert_at = toc_match.end()
    entry = '\n  <li><a href="#list-of-theorems">List of Theorems</a></li>'
    return body[:insert_at] + entry + body[insert_at:]


def _normalize_image_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    if not cleaned:
        return None
    return cleaned.rstrip("/")


def _resolve_image_src(src: str, image_base_url: str | None) -> str:
    normalized_src = src.replace("\\", "/").strip()
    if not normalized_src:
        return normalized_src

    if ABSOLUTE_URL_RE.match(normalized_src) is not None:
        return normalized_src

    base = _normalize_image_base_url(image_base_url)
    if base is None:
        return normalized_src

    relative_src = normalized_src.lstrip("./")
    if base.endswith("/images_folder") and relative_src.startswith("images_folder/"):
        relative_src = relative_src[len("images_folder/") :]

    return f"{base}/{relative_src.lstrip('/')}"


def _replace_tikz_placeholders(body: str, image_base_url: str | None = None) -> str:
    def parse_payload(payload: str) -> tuple[str, str, str]:
        parts = [part.strip() for part in payload.split("|")]
        if not parts:
            return "", "", ""

        light_src = parts[0]
        dark_src = light_src
        caption = ""

        if len(parts) == 2:
            second = parts[1]
            if re.search(r"\.(?:svg|png|jpe?g|gif|webp)$", second, flags=re.IGNORECASE):
                dark_src = second
            else:
                caption = second
        elif len(parts) >= 3:
            dark_src = parts[1] or light_src
            caption = "|".join(parts[2:]).strip()

        if not dark_src:
            dark_src = light_src

        return light_src, dark_src, caption

    def repl(match: re.Match[str]) -> str:
        payload = match.group(1).strip()
        light_src, dark_src, caption = parse_payload(payload)
        light_src = _resolve_image_src(light_src, image_base_url=image_base_url)
        dark_src = _resolve_image_src(dark_src, image_base_url=image_base_url)

        if GENERIC_TIKZ_CAPTION_RE.match(caption or ""):
            caption = ""

        alt = caption if caption else "Figure"
        safe_light_src = html.escape(light_src, quote=True)
        safe_dark_src = html.escape(dark_src, quote=True)
        safe_alt = html.escape(alt, quote=True)
        safe_caption = html.escape(caption)
        caption_html = f'<div class="tikz-caption">{safe_caption}</div>' if caption else ""

        return (
            '<div class="tikz-embed">'
            f'<img class="tikz-img tikz-img-light" src="{safe_light_src}" alt="{safe_alt}" loading="lazy" />'
            f'<img class="tikz-img tikz-img-dark" src="{safe_dark_src}" alt="{safe_alt}" loading="lazy" />'
            f"{caption_html}"
            "</div>"
        )

    return TIKZ_PLACEHOLDER_RE.sub(repl, body)


def _wrap_tables(body: str) -> str:
    def repl(match: re.Match[str]) -> str:
        table_html = match.group(0)
        return f'<div class="table-wrap">{table_html}</div>'

    return TABLE_RE.sub(repl, body)


def _insert_theorem_list(body: str, theorem_entries: list[tuple[str, str]]) -> str:
    if not theorem_entries:
        return body

    if 'id="list-of-theorems"' in body:
        return body

    items = "\n".join(
        f'  <li><a href="#{html.escape(block_id, quote=True)}">{label}</a></li>'
        for label, block_id in theorem_entries
    )
    theorem_list_html = (
        "<section id=\"list-of-theorems\" class=\"list-of-theorems\">\n"
        "  <h2>List of Theorems</h2>\n"
        "  <ol>\n"
        f"{items}\n"
        "  </ol>\n"
        "</section>\n"
    )

    toc_end = body.find("</nav>")
    if toc_end != -1:
        insert_at = toc_end + len("</nav>")
        with_list = body[:insert_at] + "\n" + theorem_list_html + body[insert_at:]
        return _add_theorem_link_to_toc(with_list)

    return _add_theorem_link_to_toc(theorem_list_html + body)


def postprocess_html_document(document: str, image_base_url: str | None = None) -> str:
    body_match = BODY_RE.search(document)
    if body_match is None:
        return document

    body_start, body_content, body_end = body_match.groups()

    body_content, theorem_entries = _wrap_heading_boxes(body_content)
    body_content = _wrap_corollary_div_boxes(body_content, theorem_entries)
    body_content = _inline_proof_divs(body_content)
    body_content = _replace_tikz_placeholders(body_content, image_base_url=image_base_url)
    body_content = _wrap_tables(body_content)
    body_content = _insert_theorem_list(body_content, theorem_entries)

    processed_body = f"{body_start}{body_content}{body_end}"
    return document[: body_match.start()] + processed_body + document[body_match.end() :]


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-process pandoc-generated HTML.")
    parser.add_argument("--input", "-i", required=True, help="Input HTML file.")
    parser.add_argument("--output", "-o", help="Output HTML file. Defaults to in-place update.")
    parser.add_argument(
        "--image-base-url",
        help="Optional absolute base URL for externally hosted tikz images (e.g. CDN/S3/R2 path).",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else input_path

    if not input_path.exists():
        print(f"[error] Input HTML not found: {input_path}")
        return 1

    source = input_path.read_text(encoding="utf-8", errors="replace")
    image_base_url = args.image_base_url or os.environ.get("NOTES_IMAGE_BASE_URL")
    processed = postprocess_html_document(source, image_base_url=image_base_url)
    output_path.write_text(processed, encoding="utf-8")
    print(f"[ok] Post-processed HTML: {output_path}")
    if _normalize_image_base_url(image_base_url):
        print(f"[ok] External image base URL applied: {_normalize_image_base_url(image_base_url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
