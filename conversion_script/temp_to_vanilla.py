#!/usr/bin/env python3
"""
Convert notes based on the `notes_white` template into pandoc-friendly vanilla LaTeX.

Usage examples:
  python conversion_script/temp_to_vanilla.py \
	  --input tex_files/white/skolem.tex

  python conversion_script/temp_to_vanilla.py \
	  --input tex_files/white \
	  --output tex_files/white_vanilla
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable


STANDARD_PREAMBLE = r"""
% --- inserted by temp_to_vanilla.py ---
% Minimal, standard LaTeX setup suitable for pandoc HTML conversion.
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{geometry}
\usepackage{graphicx}
\usepackage{amsmath,amssymb,amsthm,mathtools}
\usepackage{hyperref}
\usepackage{enumitem}
\usepackage{array}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{xcolor}
\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue,citecolor=blue}
\numberwithin{equation}{section}
""".strip()


NOTES_TEMPLATE_INPUT_RE = re.compile(
	r"\\input\{(?:\./)?(?:notes_white|assignments_white)\}"
)

TIKZ_ENV_RE = re.compile(
	r"\\begin\{(tikzpicture|circuitikz)\}(?:\[[^\]]*\])?[\s\S]*?\\end\{\1\}",
	flags=re.MULTILINE,
)

THEOREM_LIKE_LABELS = {
	"mydefinition": "Definition",
	"mytheorem": "Theorem",
	"myidentity": "Identity",
	"myaxiom": "Axiom",
	"mynote": "Note",
	"myexercise": "Exercise",
	"example": "Example",
	"exercise": "Exercise",
	"solution": "Solution",
	"myproof": "Proof",
}


def _parse_delimited_group(
	text: str,
	start: int,
	open_char: str,
	close_char: str,
) -> tuple[str, int] | None:
	if start >= len(text) or text[start] != open_char:
		return None

	depth = 0
	i = start
	while i < len(text):
		ch = text[i]
		if ch == open_char:
			depth += 1
		elif ch == close_char:
			depth -= 1
			if depth == 0:
				return text[start + 1 : i], i + 1
		elif ch == "\\":
			i += 1
		i += 1
	return None


def _replace_macro_with_args(
	text: str,
	macro: str,
	arg_count: int,
	replacer: Callable[[list[str]], str],
) -> str:
	token = f"\\{macro}"
	i = 0
	out: list[str] = []

	while i < len(text):
		idx = text.find(token, i)
		if idx == -1:
			out.append(text[i:])
			break

		end_name = idx + len(token)

		if end_name < len(text) and (text[end_name].isalpha() or text[end_name] == "@"):  # command boundary
			out.append(text[i : end_name])
			i = end_name
			continue

		out.append(text[i:idx])

		j = end_name
		args: list[str] = []
		ok = True
		for _ in range(arg_count):
			while j < len(text) and text[j].isspace():
				j += 1
			parsed = _parse_delimited_group(text, j, "{", "}")
			if parsed is None:
				ok = False
				break
			arg, j = parsed
			args.append(arg)

		if not ok:
			out.append(text[idx:end_name])
			i = end_name
			continue

		out.append(replacer(args))
		i = j

	return "".join(out)


def _replace_token_macros(text: str, replacements: dict[str, str]) -> str:
	ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
	for token, value in ordered:
		pattern = re.compile(re.escape(token) + r"(?![A-Za-z@])")
		text = pattern.sub(lambda _m: value, text)
	return text


def _normalize_math_delimiters(text: str) -> str:
	text = text.replace(r"\(", "$")
	text = text.replace(r"\)", "$")
	text = text.replace(r"\[", "$$")
	text = text.replace(r"\]", "$$")
	text = re.sub(
		r"\{([^{}]+)\}\s*\\choose\s*\{([^{}]+)\}",
		r"\\binom{\1}{\2}",
		text,
	)
	return text


def _run_command(command: list[str], cwd: Path) -> bool:
	try:
		result = subprocess.run(
			command,
			cwd=cwd,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=180,
			check=False,
		)
		return result.returncode == 0
	except (FileNotFoundError, subprocess.SubprocessError, OSError):
		return False


def _retint_svg_for_dark_theme(svg_path: Path, light_color: str = "#e8ecff") -> None:
	try:
		source = svg_path.read_text(encoding="utf-8")
	except UnicodeDecodeError:
		source = svg_path.read_text(encoding="utf-8", errors="replace")
	except OSError:
		return

	updated = source
	if re.search(r"<svg[^>]*\bcolor=", updated, flags=re.IGNORECASE) is None:
		updated = re.sub(
			r"<svg\b",
			f"<svg color='{light_color}' fill='{light_color}'",
			updated,
			count=1,
			flags=re.IGNORECASE,
		)

	updated = re.sub(
		r"stroke=(['\"])(?:#000000|#000|black)\1",
		r"stroke=\1currentColor\1",
		updated,
		flags=re.IGNORECASE,
	)
	updated = re.sub(
		r"fill=(['\"])(?:#000000|#000|black)\1",
		r"fill=\1currentColor\1",
		updated,
		flags=re.IGNORECASE,
	)

	if updated != source:
		try:
			svg_path.write_text(updated, encoding="utf-8")
		except OSError:
			return


def _convert_pdf_to_image(pdf_path: Path, output_stem: Path) -> Path | None:
	if shutil.which("dvisvgm"):
		svg_output = output_stem.with_suffix(".svg")
		ok = _run_command(
			[
				"dvisvgm",
				"--pdf",
				"--page=1",
				"--bbox=min",
				"-o",
				str(svg_output),
				str(pdf_path),
			],
			cwd=pdf_path.parent,
		)
		if ok and svg_output.exists():
			return svg_output

	if shutil.which("pdftocairo"):
		svg_output = output_stem.with_suffix(".svg")
		ok = _run_command(
			[
				"pdftocairo",
				"-svg",
				str(pdf_path),
				str(svg_output),
			],
			cwd=pdf_path.parent,
		)
		if ok and svg_output.exists():
			return svg_output

		svg_without_ext = output_stem
		if ok and svg_without_ext.exists():
			try:
				svg_without_ext.replace(svg_output)
				return svg_output
			except OSError:
				return svg_without_ext

	if shutil.which("magick"):
		png_output = output_stem.with_suffix(".png")
		ok = _run_command(
			[
				"magick",
				"-density",
				"220",
				str(pdf_path),
				str(png_output),
			],
			cwd=pdf_path.parent,
		)
		if ok and png_output.exists():
			return png_output

	return None


def _create_dark_variant(light_image: Path) -> Path:
	if light_image.suffix.lower() != ".svg":
		return light_image

	dark_stem = light_image.stem
	if dark_stem.endswith("_light"):
		dark_stem = dark_stem[: -len("_light")]
	dark_image = light_image.with_name(f"{dark_stem}_dark{light_image.suffix}")

	try:
		shutil.copyfile(light_image, dark_image)
	except OSError:
		return light_image

	_retint_svg_for_dark_theme(dark_image)
	return dark_image


def _render_tikz_env_to_image(
	env_block: str,
	image_dir: Path,
	image_stem: str,
) -> Path | None:
	image_dir.mkdir(parents=True, exist_ok=True)

	tex_document = "\n".join([
		r"\documentclass[border=2pt]{standalone}",
		r"\usepackage{amsmath,amssymb,mathtools}",
		r"\usepackage{tikz}",
		r"\usepackage{pgfplots}",
		r"\pgfplotsset{compat=1.18}",
		r"\usepackage{circuitikz}",
		r"\begin{document}",
		env_block,
		r"\end{document}",
	])

	with tempfile.TemporaryDirectory(prefix="tikz_render_") as tmp_dir_name:
		tmp_dir = Path(tmp_dir_name)
		tex_file = tmp_dir / f"{image_stem}.tex"
		tex_file.write_text(tex_document, encoding="utf-8")

		compiled = False
		if shutil.which("latexmk"):
			compiled = _run_command(
				[
					"latexmk",
					"-pdf",
					"-interaction=nonstopmode",
					"-halt-on-error",
					tex_file.name,
				],
				cwd=tmp_dir,
			)
		elif shutil.which("pdflatex"):
			compiled = _run_command(
				[
					"pdflatex",
					"-interaction=nonstopmode",
					"-halt-on-error",
					tex_file.name,
				],
				cwd=tmp_dir,
			)

		if not compiled:
			return None

		pdf_file = tmp_dir / f"{image_stem}.pdf"
		if not pdf_file.exists():
			return None

		output_stem = image_dir / image_stem
		rendered = _convert_pdf_to_image(pdf_file, output_stem)
		return rendered


def _replace_tikz_with_image_placeholders(
	text: str,
	source_path: Path | None,
	images_dir: Path | None,
	image_path_prefix: str,
) -> str:
	counter = 0
	safe_prefix = image_path_prefix.strip().strip("/\\") or "images_folder"

	def repl(match: re.Match[str]) -> str:
		nonlocal counter
		counter += 1
		env_name = match.group(1)
		env_block = match.group(0)

		base_stem = source_path.stem if source_path is not None else "figure"
		image_stem = f"{base_stem}_{env_name}_{counter:03d}"

		if images_dir is not None:
			light_stem = f"{image_stem}_light"
			rendered = _render_tikz_env_to_image(env_block, images_dir, light_stem)
			if rendered is not None:
				dark_variant = _create_dark_variant(rendered)
				light_rel_path = f"{safe_prefix}/{rendered.name}".replace("\\", "/")
				dark_rel_path = f"{safe_prefix}/{dark_variant.name}".replace("\\", "/")
				caption = f"{env_name} {counter}"
				return f"\n\n[[TIKZ_IMAGE|{light_rel_path}|{dark_rel_path}|{caption}]]\n\n"

		return f"\n\n[TikZ figure {counter} omitted for HTML conversion]\n\n"

	return TIKZ_ENV_RE.sub(repl, text)


def _remove_listoftheorems_blocks(text: str) -> str:
	command = r"\listoftheorems"
	i = 0
	out: list[str] = []

	while i < len(text):
		idx = text.find(command, i)
		if idx == -1:
			out.append(text[i:])
			break

		out.append(text[i:idx])
		j = idx + len(command)

		while j < len(text) and text[j].isspace():
			j += 1

		if j < len(text) and text[j] == "[":
			parsed = _parse_delimited_group(text, j, "[", "]")
			if parsed is not None:
				_, j = parsed

		while j < len(text) and text[j] != "\n":
			j += 1
		if j < len(text):
			j += 1

		i = j

	return "".join(out)


def _replace_custom_preamble(text: str) -> str:
	docclass_match = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text)
	begin_match = re.search(r"\\begin\{document\}", text)
	if docclass_match is None or begin_match is None:
		return text
	if docclass_match.start() > begin_match.start():
		return text

	before_docclass = text[: docclass_match.start()]
	docclass = docclass_match.group(0)
	body = text[begin_match.start() :]

	rebuilt = (
		f"{before_docclass}{docclass}\n"
		f"{STANDARD_PREAMBLE}\n\n"
		f"{body}"
	)
	return rebuilt


def _replace_environment_blocks_with_placeholder(text: str, env_name: str, placeholder: str) -> str:
	pattern = re.compile(
		rf"\\begin\{{{env_name}\}}(?:\[[^\]]*\])?[\s\S]*?\\end\{{{env_name}\}}",
		flags=re.MULTILINE,
	)
	replacement = f"\\begin{{verbatim}}\n{placeholder}\n\\end{{verbatim}}"
	return pattern.sub(lambda _m: replacement, text)


def _heading_from_env(label: str, title: str | None) -> str:
	if title is not None:
		clean = title.strip()
		if clean:
			return f"\\paragraph{{{label} ({clean}).}}"
	return f"\\paragraph{{{label}.}}"


def _replace_env_with_heading(text: str, env_name: str, label: str) -> str:
	begin_pattern = re.compile(
		rf"\\begin\{{{env_name}\}}(?:\[(.*?)\]|\{{(.*?)\}})?",
		flags=re.DOTALL,
	)

	def repl_begin(match: re.Match[str]) -> str:
		title = match.group(1) if match.group(1) is not None else match.group(2)
		return _heading_from_env(label, title) + "\n"

	text = begin_pattern.sub(repl_begin, text)
	text = re.sub(rf"\\end\{{{env_name}\}}", r"\\par", text)
	return text


def _normalize_custom_environments(text: str) -> str:
	for env_name, label in [
		("mydefinition", "Definition"),
		("mytheorem", "Theorem"),
		("myidentity", "Identity"),
		("myaxiom", "Axiom"),
		("mynote", "Note"),
		("myexercise", "Exercise"),
		("example", "Example"),
		("exercise", "Exercise"),
		("solution", "Solution"),
		("myproof", "Proof"),
	]:
		text = _replace_env_with_heading(text, env_name, label)

	text = re.sub(r"\\begin\{introduction\}", r"\\chapter*{Introduction}", text)
	text = re.sub(r"\\end\{introduction\}", "", text)
	text = re.sub(r"\\begin\{acknowledgements\}", r"\\chapter*{Acknowledgements}", text)
	text = re.sub(r"\\end\{acknowledgements\}", "", text)
	text = re.sub(r"\\begin\{references\}", r"\\begin{thebibliography}{99}", text)
	text = re.sub(r"\\end\{references\}", r"\\end{thebibliography}", text)

	text = re.sub(r"\\begin\{longlisting\}", "", text)
	text = re.sub(r"\\end\{longlisting\}", "", text)

	text = re.sub(r"\\begin\{tcolorbox\}(?:\[[^\]]*\])?", r"\\paragraph{Box.}\n", text)
	text = re.sub(r"\\end\{tcolorbox\}", r"\\par", text)
	text = re.sub(r"\\begin\{keyresult\}(?:\[[^\]]*\])?", r"\\paragraph{Key Result.}\n", text)
	text = re.sub(r"\\end\{keyresult\}", r"\\par", text)
	text = re.sub(r"\\begin\{highlight\}(?:\[[^\]]*\])?", r"\\paragraph{Highlight.}\n", text)
	text = re.sub(r"\\end\{highlight\}", r"\\par", text)

	text = re.sub(r"\\begin\{mycodeblock\}(?:\[[^\]]*\])?", r"\\begin{verbatim}", text)
	text = re.sub(r"\\end\{mycodeblock\}", r"\\end{verbatim}", text)

	return text


def _expand_custom_macros(text: str) -> str:
	arg_replacements: list[tuple[str, int, Callable[[list[str]], str]]] = [
		("eqnarrayx", 1, lambda a: rf"\begin{{eqnarray}} {a[0]} \end{{eqnarray}}"),
		("eqn", 1, lambda a: rf"\begin{{equation}} {a[0]} \end{{equation}}"),
		("underemphasise", 1, lambda a: rf"\textbf{{{a[0]}}}"),
		("emphasise", 1, lambda a: rf"\textbf{{{a[0]}}}"),
		("intg", 3, lambda a: rf"\int_{{{a[0]}}}^{{{a[1]}}} {a[2]} \, dx"),
		("sumg", 3, lambda a: rf"\sum_{{{a[0]}}}^{{{a[1]}}} {a[2]}"),
		("diff", 2, lambda a: rf"\frac{{d {a[0]}}}{{d {a[1]}}}"),
		("pdiff", 2, lambda a: rf"\frac{{\partial {a[0]}}}{{\partial {a[1]}}}"),
		("limit", 3, lambda a: rf"\lim_{{{a[0]} \to {a[1]}}} {a[2]}"),
		("infseries", 2, lambda a: rf"\sum_{{{a[0]}}}^{{\infty}} {a[1]}"),
		("mat", 1, lambda a: rf"\begin{{matrix}} {a[0]} \end{{matrix}}"),
		("pmat", 1, lambda a: rf"\begin{{pmatrix}} {a[0]} \end{{pmatrix}}"),
		("bmat", 1, lambda a: rf"\begin{{bmatrix}} {a[0]} \end{{bmatrix}}"),
		("mycases", 1, lambda a: rf"\begin{{cases}} {a[0]} \end{{cases}}"),
		("floor", 1, lambda a: rf"\left\lfloor {a[0]} \right\rfloor"),
		("ceil", 1, lambda a: rf"\left\lceil {a[0]} \right\rceil"),
		("abs", 1, lambda a: rf"\left| {a[0]} \right|"),
		("norm", 1, lambda a: rf"\left\| {a[0]} \right\|"),
		("set", 1, lambda a: rf"\left\{{ {a[0]} \right\}}"),
		("angg", 1, lambda a: rf"\left\langle {a[0]} \right\rangle"),
		("iintd", 1, lambda a: rf"\iint {a[0]}\,dx\,dy"),
		("iiintd", 1, lambda a: rf"\iiint {a[0]}\,dx\,dy\,dz"),
		("nint", 3, lambda a: rf"\int_{{{a[0]}}}^{{{a[1]}}} {a[2]}\,dx"),
		("megaunion", 2, lambda a: rf"\bigcup_{{{a[0]}}}^{{{a[1]}}}"),
		("megaintersect", 2, lambda a: rf"\bigcap_{{{a[0]}}}^{{{a[1]}}}"),
		("settitle", 1, lambda _a: ""),
	]

	for macro, argc, repl in arg_replacements:
		text = _replace_macro_with_args(text, macro, argc, repl)

	token_replacements = {
		r"\forallx": r"\forall x \in \mathbb{R}",
		r"\existsx": r"\exists x \in \mathbb{R}",
		r"\megaunion": r"\bigcup",
		r"\megaintersect": r"\bigcap",
		r"\union": r"\cup",
		r"\intersect": r"\cap",
		r"\nd": r"\wedge",
		r"\orr": r"\vee",
		r"\R": r"\mathbb{R}",
		r"\Z": r"\mathbb{Z}",
		r"\N": r"\mathbb{N}",
		r"\Q": r"\mathbb{Q}",
		r"\C": r"\mathcal{C}",
	}
	text = _replace_token_macros(text, token_replacements)

	return text


def convert_tex_content(
	text: str,
	source_path: Path | None = None,
	images_dir: Path | None = None,
	image_path_prefix: str = "images_folder",
) -> str:
	line_ending = "\r\n" if "\r\n" in text else "\n"
	text = text.replace("\r\n", "\n").replace("\r", "\n")

	text = _remove_listoftheorems_blocks(text)
	text = NOTES_TEMPLATE_INPUT_RE.sub("", text)
	text = _replace_custom_preamble(text)
	text = _normalize_math_delimiters(text)
	text = _expand_custom_macros(text)

	text = _replace_tikz_with_image_placeholders(
		text,
		source_path=source_path,
		images_dir=images_dir,
		image_path_prefix=image_path_prefix,
	)

	text = _normalize_custom_environments(text)

	text = re.sub(r"\n{3,}", "\n\n", text)
	text = text.strip() + "\n"

	return text.replace("\n", line_ending)


def _read_text(path: Path) -> str:
	for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
		try:
			return path.read_text(encoding=encoding)
		except UnicodeDecodeError:
			continue
	return path.read_text(encoding="utf-8", errors="replace")


def _should_process(content: str, force: bool) -> bool:
	if force:
		return True
	return bool(NOTES_TEMPLATE_INPUT_RE.search(content))


def _iter_tex_files(root: Path, recursive: bool = True) -> list[Path]:
	if recursive:
		return sorted(root.rglob("*.tex"))
	return sorted(root.glob("*.tex"))


def _resolve_output_for_single_file(src: Path, output: Path | None, suffix: str) -> Path:
	if output is None:
		return src.with_name(f"{src.stem}{suffix}{src.suffix}")

	if output.exists() and output.is_file():
		return output
	if output.suffix.lower() == ".tex" and not output.exists():
		return output

	output.mkdir(parents=True, exist_ok=True)
	return output / f"{src.stem}{suffix}{src.suffix}"


def _convert_file(
	src: Path,
	dst: Path,
	force: bool,
	images_dir: Path | None,
	image_path_prefix: str,
) -> tuple[bool, str]:
	content = _read_text(src)
	if not _should_process(content, force):
		return False, "skip (no notes_white input found)"

	converted = convert_tex_content(
		content,
		source_path=src,
		images_dir=images_dir,
		image_path_prefix=image_path_prefix,
	)
	dst.parent.mkdir(parents=True, exist_ok=True)
	dst.write_text(converted, encoding="utf-8")
	return True, "converted"


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Convert notes_white-based LaTeX files to vanilla LaTeX for pandoc HTML conversion."
	)
	parser.add_argument(
		"--input",
		"-i",
		required=True,
		help="Input .tex file or directory.",
	)
	parser.add_argument(
		"--output",
		"-o",
		help="Output file (single input) or output directory (directory input).",
	)
	parser.add_argument(
		"--suffix",
		default="_vanilla",
		help="Suffix for output files when output file path is not explicitly given (default: _vanilla).",
	)
	parser.add_argument(
		"--non-recursive",
		action="store_true",
		help="When input is a directory, only process top-level .tex files.",
	)
	parser.add_argument(
		"--force",
		action="store_true",
		help="Process files even if they do not explicitly include notes_white.",
	)
	parser.add_argument(
		"--images-dir",
		help="Directory where rendered tikz/circuit images should be written.",
	)
	parser.add_argument(
		"--image-path-prefix",
		default="images_folder",
		help="Path prefix inserted into tikz image placeholders (default: images_folder).",
	)
	args = parser.parse_args()

	input_path = Path(args.input).expanduser().resolve()
	output_path = Path(args.output).expanduser().resolve() if args.output else None
	images_dir = Path(args.images_dir).expanduser().resolve() if args.images_dir else None
	if images_dir is not None:
		images_dir.mkdir(parents=True, exist_ok=True)

	if not input_path.exists():
		print(f"[error] Input path not found: {input_path}")
		return 1

	processed = 0
	skipped = 0

	if input_path.is_file():
		if input_path.suffix.lower() != ".tex":
			print(f"[error] Input file is not a .tex file: {input_path}")
			return 1
		dst = _resolve_output_for_single_file(input_path, output_path, args.suffix)
		ok, status = _convert_file(
			input_path,
			dst,
			args.force,
			images_dir,
			args.image_path_prefix,
		)
		if ok:
			processed += 1
			print(f"[ok] {input_path} -> {dst}")
		else:
			skipped += 1
			print(f"[skip] {input_path}: {status}")
	else:
		files = _iter_tex_files(input_path, recursive=not args.non_recursive)
		if output_path is None:
			output_dir = input_path.parent / f"{input_path.name}_vanilla"
		else:
			output_dir = output_path
		output_dir.mkdir(parents=True, exist_ok=True)

		files_to_process: list[Path] = []
		for src in files:
			if output_dir in src.parents:
				continue
			if src.stem.endswith(args.suffix):
				continue
			files_to_process.append(src)

		for src in files_to_process:
			rel = src.relative_to(input_path)
			dst = output_dir / rel
			ok, status = _convert_file(
				src,
				dst,
				args.force,
				images_dir,
				args.image_path_prefix,
			)
			if ok:
				processed += 1
				print(f"[ok] {rel}")
			else:
				skipped += 1
				print(f"[skip] {rel}: {status}")

		print(f"\nOutput directory: {output_dir}")

	print(f"Summary: converted={processed}, skipped={skipped}")
	return 0


if __name__ == "__main__":
	sys.exit(main())

