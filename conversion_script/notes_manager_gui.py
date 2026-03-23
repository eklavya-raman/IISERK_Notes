#!/usr/bin/env python3
"""
Local browser GUI launcher for Notes Converter + Publisher.

This app serves an HTML/CSS/JS frontend from conversion_script/gui and exposes
API endpoints that invoke the existing batch scripts:
- conversion_script/convert_tex_to_html.bat
- conversion_script/publish_html_repo.bat
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

PUBLISH_REMOTE_URL_DEFAULT = "https://github.com/eklavya-raman/IISERK_Notes.git"
PUBLISH_REMOTE_NAME_DEFAULT = "origin"
PUBLISH_TARGET_BRANCH_DEFAULT = "main"
PUBLISH_BRANCH_DEFAULT = "html-subtree"
LINKS_FILE_NAME = "tex_html_links.map"
GUI_HOST = "127.0.0.1"
GUI_PORT_DEFAULT = 8765
GUI_LOGS_RELATIVE_DIR = Path("conversion_script") / "logs"
GUI_LOG_FILE_NAME = "notes_manager_gui.log"

LOGGER = logging.getLogger("notes_manager_gui")


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
        if (
            (root / "conversion_script" / "convert_tex_to_html.bat").exists()
            and (root / "conversion_script" / "publish_html_repo.bat").exists()
            and (root / "tex_files" / "white").exists()
            and (root / "html").exists()
        ):
            return root

    raise FileNotFoundError(
        "Could not locate workspace root containing converter/publisher scripts, tex_files/white, and html"
    )


def _normalize_section(value: str) -> str:
    lowered = value.strip().lower()
    if not lowered:
        return ""

    normalized = SECTION_ALIASES.get(lowered)
    if normalized:
        return normalized

    if lowered in {option[0] for option in SECTION_OPTIONS}:
        return lowered

    return ""


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


def _list_tex_files(white_dir: Path) -> list[Path]:
    return sorted(path for path in white_dir.rglob("*.tex") if path.is_file())


def _list_html_files(html_dir: Path) -> list[Path]:
    return sorted(path for path in html_dir.glob("*.html") if path.is_file())


def _run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    parts = [part for part in [completed.stdout, completed.stderr] if part and part.strip()]
    output = "\n".join(parts).strip()
    return completed.returncode, output


class NotesManagerService:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.white_dir = workspace_root / "tex_files" / "white"
        self.default_html_dir = workspace_root / "html"
        self.converter_bat = workspace_root / "conversion_script" / "convert_tex_to_html.bat"
        self.publisher_bat = workspace_root / "conversion_script" / "publish_html_repo.bat"
        self.links_file = _links_file_path(workspace_root)

    def _display_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(path.resolve())

    def _to_abs_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path.strip().strip('"').strip("'"))
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        return candidate.expanduser().resolve()

    def _resolve_target_html(self, tex_path: Path, links: dict[str, tuple[Path, Path]]) -> tuple[Path, str]:
        key = str(tex_path.resolve()).lower()
        linked_entry = links.get(key)
        if linked_entry is not None:
            return linked_entry[1], "mapped"

        return self.default_html_dir / f"{tex_path.stem}.html", "default"

    def _result(self, ok: bool, summary: str, log: str = "", code: int = 0) -> dict[str, Any]:
        return {
            "ok": ok,
            "summary": summary,
            "log": log,
            "code": code,
        }

    def get_state(self) -> dict[str, Any]:
        try:
            links = _read_links(self.links_file)

            tex_files = _list_tex_files(self.white_dir)
            tex_entries: list[dict[str, str]] = []
            for tex_file in tex_files:
                key = str(tex_file.resolve()).lower()
                linked_html_entry = links.get(key)
                linked_html_display = ""
                linked_html_path = ""
                if linked_html_entry is not None:
                    linked_html_path = str(linked_html_entry[1])
                    linked_html_display = self._display_path(linked_html_entry[1])

                tex_entries.append(
                    {
                        "path": str(tex_file.resolve()),
                        "displayPath": self._display_path(tex_file),
                        "linkedHtmlPath": linked_html_path,
                        "linkedHtmlDisplayPath": linked_html_display,
                    }
                )

            html_files = _list_html_files(self.default_html_dir)
            html_entries = [
                {
                    "path": str(html_file.resolve()),
                    "displayPath": self._display_path(html_file),
                }
                for html_file in html_files
            ]

            mapped_count = sum(1 for entry in tex_entries if entry["linkedHtmlPath"])
            LOGGER.info(
                "State requested: tex=%d, mapped=%d, html=%d",
                len(tex_entries),
                mapped_count,
                len(html_entries),
            )

            section_entries = [{"value": value, "label": label} for value, label in SECTION_OPTIONS]

            return {
                "ok": True,
                "workspaceRoot": str(self.workspace_root),
                "texFiles": tex_entries,
                "htmlFiles": html_entries,
                "sectionOptions": section_entries,
                "publishDefaults": {
                    "remoteUrl": PUBLISH_REMOTE_URL_DEFAULT,
                    "remoteName": PUBLISH_REMOTE_NAME_DEFAULT,
                    "targetBranch": PUBLISH_TARGET_BRANCH_DEFAULT,
                    "publishBranch": PUBLISH_BRANCH_DEFAULT,
                    "htmlDir": str(self.default_html_dir),
                },
            }
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("State collection failed")
            return {
                "ok": False,
                "error": str(error),
            }

    def link_tex_to_html(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            tex_raw = str(payload.get("texPath", "")).strip()
            html_raw = str(payload.get("htmlPath", "")).strip()

            if not tex_raw:
                return self._result(False, "Missing TeX path.")
            if not html_raw:
                return self._result(False, "Missing HTML path.")

            tex_path = self._to_abs_path(tex_raw)
            html_path = self._to_abs_path(html_raw)

            if not tex_path.exists() or not tex_path.is_file() or tex_path.suffix.lower() != ".tex":
                return self._result(False, f"Invalid TeX file: {tex_path}")

            if not html_path.exists() or not html_path.is_file() or html_path.suffix.lower() != ".html":
                return self._result(False, f"Invalid HTML file: {html_path}")

            links = _read_links(self.links_file)
            links[str(tex_path).lower()] = (tex_path, html_path)
            _write_links(self.links_file, links)

            LOGGER.info(
                "Link updated: %s -> %s",
                self._display_path(tex_path),
                self._display_path(html_path),
            )

            return self._result(
                True,
                f"Linked {self._display_path(tex_path)} -> {self._display_path(html_path)}",
            )
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Link update failed")
            return self._result(False, f"Link update failed: {error}")

    def convert_files(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            mode = str(payload.get("mode", "selected")).strip().lower()
            custom_title = str(payload.get("customTitle", "")).strip()
            section = _normalize_section(str(payload.get("section", "")).strip())
            image_base_url = str(payload.get("imageBaseUrl", "")).strip()

            LOGGER.info(
                "Conversion request: mode=%s, custom_title=%s, section=%s, image_base_url=%s",
                mode,
                bool(custom_title),
                section or "(none)",
                image_base_url or "(none)",
            )

            links = _read_links(self.links_file)

            tex_files: list[Path]
            if mode == "all":
                tex_files = _list_tex_files(self.white_dir)
            elif mode == "linked":
                tex_files = [
                    tex_file
                    for tex_file in _list_tex_files(self.white_dir)
                    if str(tex_file.resolve()).lower() in links
                ]
            else:
                raw_paths = payload.get("texPaths", [])
                if not isinstance(raw_paths, list):
                    return self._result(False, "texPaths must be an array for selected mode.")

                selected: list[Path] = []
                for raw_path in raw_paths:
                    candidate = self._to_abs_path(str(raw_path))
                    if not candidate.exists() or not candidate.is_file() or candidate.suffix.lower() != ".tex":
                        return self._result(False, f"Invalid TeX file: {candidate}")
                    selected.append(candidate)
                tex_files = selected

            if not tex_files:
                if mode == "linked":
                    return self._result(False, "No mapped TeX files found. Use link mode first.")
                return self._result(False, "No TeX files selected.")

            logs: list[str] = []
            success_count = 0
            fail_count = 0
            total = len(tex_files)

            logs.append(
                f"Conversion mode: {mode} | Files queued: {total} | "
                f"Section override: {section or '(none)'} | "
                f"Custom title override: {'set' if custom_title else '(none)'}"
            )
            if image_base_url:
                logs.append(f"Image base URL override: {image_base_url}")

            LOGGER.info("Starting conversion for %d file(s)", total)

            for index, tex_file in enumerate(tex_files, start=1):
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

                target_html, target_mode = self._resolve_target_html(tex_file, links)
                display_tex = self._display_path(tex_file)
                display_target_html = self._display_path(target_html)

                logs.append(f"[{index}/{total}] START: {display_tex}")
                logs.append(f"[{index}/{total}] Target HTML ({target_mode}): {display_target_html}")
                LOGGER.info(
                    "[%d/%d] Converting %s -> %s (%s)",
                    index,
                    total,
                    display_tex,
                    display_target_html,
                    target_mode,
                )

                command = [str(self.converter_bat), str(tex_file)]
                started = time.perf_counter()
                return_code, output = _run_command(command, cwd=self.workspace_root, env=env)
                elapsed = time.perf_counter() - started

                if output:
                    logs.append(output)

                if return_code == 0:
                    logs.append(f"[{index}/{total}] DONE in {elapsed:.2f}s")
                    LOGGER.info("[%d/%d] Done in %.2fs", index, total, elapsed)
                    success_count += 1
                else:
                    logs.append(f"[{index}/{total}] FAILED in {elapsed:.2f}s (exit code: {return_code})")
                    LOGGER.warning(
                        "[%d/%d] Failed in %.2fs with exit code %d",
                        index,
                        total,
                        elapsed,
                        return_code,
                    )
                    fail_count += 1

            ok = fail_count == 0
            if ok:
                summary = f"Converted {success_count}/{total} file(s) successfully."
            else:
                summary = f"Converted {success_count}/{total} file(s); {fail_count} failed."

            LOGGER.info("Conversion finished: %s", summary)

            return self._result(ok, summary, "\n".join(logs), 0 if ok else 1)
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Conversion failed with exception")
            return self._result(False, f"Conversion failed: {error}")

    def publish_html(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            remote_url = str(payload.get("remoteUrl", "")).strip() or PUBLISH_REMOTE_URL_DEFAULT
            remote_name = str(payload.get("remoteName", "")).strip() or PUBLISH_REMOTE_NAME_DEFAULT
            target_branch = str(payload.get("targetBranch", "")).strip() or PUBLISH_TARGET_BRANCH_DEFAULT
            publish_branch = str(payload.get("publishBranch", "")).strip() or PUBLISH_BRANCH_DEFAULT
            html_dir_raw = str(payload.get("htmlDir", "")).strip()

            if html_dir_raw:
                html_dir = self._to_abs_path(html_dir_raw)
            else:
                html_dir = self.default_html_dir

            command = [
                str(self.publisher_bat),
                remote_url,
                remote_name,
                target_branch,
                publish_branch,
                str(html_dir),
            ]

            LOGGER.info(
                "Publish request: remote_url=%s, remote_name=%s, target_branch=%s, publish_branch=%s, html_dir=%s",
                remote_url,
                remote_name,
                target_branch,
                publish_branch,
                self._display_path(html_dir),
            )

            return_code, output = _run_command(command, cwd=self.workspace_root)
            ok = return_code == 0
            if ok:
                summary = "Publish completed successfully."
            else:
                summary = "Publish failed. Check output for details."

            LOGGER.info("Publish result: %s (code=%d)", summary, return_code)

            return self._result(ok, summary, output, return_code)
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Publish failed with exception")
            return self._result(False, f"Publish failed: {error}")


class NotesGuiRequestHandler(SimpleHTTPRequestHandler):
    service: NotesManagerService
    gui_dir: Path

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(self.gui_dir), **kwargs)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict[str, Any]:
        content_length_raw = self.headers.get("Content-Length", "0")
        try:
            content_length = int(content_length_raw)
        except ValueError:
            return {}

        if content_length <= 0:
            return {}

        data = self.rfile.read(content_length)
        if not data:
            return {}

        try:
            parsed = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

        if isinstance(parsed, dict):
            return parsed

        return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/state":
            LOGGER.info("GET /api/state")
            self._send_json(self.service.get_state())
            return

        if parsed.path in {"/", "/index.html"}:
            self.path = "/index.html"

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self._read_json_body()

        if parsed.path == "/api/link":
            LOGGER.info("POST /api/link")
            self._send_json(self.service.link_tex_to_html(payload))
            return

        if parsed.path == "/api/convert":
            LOGGER.info("POST /api/convert")
            self._send_json(self.service.convert_files(payload))
            return

        if parsed.path == "/api/publish":
            LOGGER.info("POST /api/publish")
            self._send_json(self.service.publish_html(payload))
            return

        if parsed.path == "/api/shutdown":
            LOGGER.info("POST /api/shutdown")
            self._send_json({"ok": True, "summary": "Shutdown requested."})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self._send_json({"ok": False, "error": "Unknown endpoint."}, status=HTTPStatus.NOT_FOUND)


def _resolve_gui_dir() -> Path:
    if getattr(sys, "frozen", False):
        base_path = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base_path = Path(__file__).resolve().parent

    return base_path / "gui"


def _resolve_preferred_port() -> int:
    raw_port = os.environ.get("NOTES_GUI_PORT", "").strip()
    if not raw_port:
        return GUI_PORT_DEFAULT

    try:
        parsed = int(raw_port)
    except ValueError:
        return GUI_PORT_DEFAULT

    if 0 <= parsed <= 65535:
        return parsed

    return GUI_PORT_DEFAULT


def _setup_app_logger(workspace_root: Path) -> Path:
    logs_dir = workspace_root / GUI_LOGS_RELATIVE_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / GUI_LOG_FILE_NAME

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)
    LOGGER.propagate = False

    LOGGER.info("Initialized GUI logger")
    LOGGER.info("Log file: %s", log_file)
    return log_file


def main() -> int:
    try:
        workspace_root = _find_workspace_root()
    except FileNotFoundError as error:
        print(f"[error] {error}")
        return 1

    log_file = _setup_app_logger(workspace_root)

    gui_dir = _resolve_gui_dir()
    index_file = gui_dir / "index.html"
    if not index_file.exists():
        LOGGER.error("GUI file not found: %s", index_file)
        print(f"[error] GUI file not found: {index_file}")
        return 1

    service = NotesManagerService(workspace_root)

    NotesGuiRequestHandler.service = service
    NotesGuiRequestHandler.gui_dir = gui_dir

    preferred_port = _resolve_preferred_port()

    try:
        server = ThreadingHTTPServer((GUI_HOST, preferred_port), NotesGuiRequestHandler)
    except OSError:
        server = ThreadingHTTPServer((GUI_HOST, 0), NotesGuiRequestHandler)

    host, port = server.server_address
    url = f"http://{host}:{port}/index.html"

    LOGGER.info("Workspace: %s", workspace_root)
    LOGGER.info("GUI URL: %s", url)
    LOGGER.info("Detailed logs: %s", log_file)

    print(f"[info] Workspace: {workspace_root}", flush=True)
    print(f"[info] GUI URL: {url}", flush=True)
    print(f"[info] Log file: {log_file}", flush=True)
    print("[info] Opening browser...", flush=True)

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received; shutting down GUI server")
        pass
    finally:
        server.server_close()

    LOGGER.info("GUI server stopped")
    print("[done] GUI server stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
