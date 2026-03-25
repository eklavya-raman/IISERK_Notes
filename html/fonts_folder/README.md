# Static fonts for HTML export

Place custom web font files here so generated HTML can serve them from `fonts_folder/` on Vercel.

## Math fonts (repo-driven options)

- Put math fonts here using any of: `.otf`, `.ttf`, `.woff`, `.woff2`.
- Math font options in the UI are generated from this folder automatically (no hardcoded list).
- A file is treated as a math font when its filename contains `Math` (case-insensitive).

On each conversion, the pipeline:
- copies this folder to `html/fonts_folder/`
- generates `html/fonts_folder/math_fonts_manifest.json`
- builds the math font dropdown from that manifest

## Optional custom text font family (all styles)

If you want body/headings to use your own full font family, add files with this base naming:

- `NotesCustom-Regular` (`.otf` / `.ttf` / `.woff` / `.woff2`)
- `NotesCustom-Italic`
- `NotesCustom-Bold`
- `NotesCustom-BoldItalic`

Then choose `Custom` in the Text Font dropdown.

## Notes

- You can override the source folder with:
  - `set NOTES_FONTS_SOURCE_DIR=path\to\your\fonts`
