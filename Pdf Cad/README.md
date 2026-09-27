# pdfscriptV2.sh

A Bash utility that batch-converts DXF/DWG CAD drawings to PDF using QCAD's `dwg2pdf` tool, with an optional step to merge all resulting PDFs into a single file. The script uses Zenity dialogs for a simple graphical workflow — no terminal interaction required.

## Features

- Graphical folder picker to choose the drawing directory
- Batch conversion of all `.dxf`, `.dwg`, `.DXF`, and `.DWG` files in that directory
- Live progress bar showing the current file and percentage complete
- Converted PDFs saved into a `PDF/` subfolder of the source directory
- Summary dialog listing every file that was processed
- Optional merge of all converted PDFs into one file via `pdfunite`

## Requirements

- **Linux** with a graphical desktop session
- [**Zenity**](https://help.gnome.org/users/zenity/) — for all dialog boxes
- **QCAD Professional 3.32.2** installed at:
  ```
  /opt/qcad-3.32.2-pro-linux-qt5.14-x86_64/dwg2pdf
  ```
  (Edit the `QCAD_BIN` variable in the script if your installation path differs.)
- **poppler-utils** — provides `pdfunite`, only required if you use the merge feature
  ```bash
  sudo apt install poppler-utils
  ```

## Usage

1. Make the script executable (one-time step):
   ```bash
   chmod +x pdfscriptV2.sh
   ```
2. Run it:
   ```bash
   ./pdfscriptV2.sh
   ```
3. A folder-selection dialog appears. Choose the directory containing your `.dxf`/`.dwg` files.
4. The script scans for drawing files and shows a progress bar while converting each one.
5. When finished, a summary dialog lists all converted files and confirms where the PDFs were saved (`<your-folder>/PDF`).
6. You'll then be asked whether to merge all converted PDFs into a single file:
   - If **yes**, enter a filename for the merged PDF (the `.pdf` extension is added automatically).
   - The merged file is saved alongside the individual PDFs in the `PDF/` subfolder.

## How It Works

1. **Folder selection** — `zenity --file-selection --directory` lets the user pick the working directory; the script exits cleanly if cancelled.
2. **File discovery** — counts matching drawing files using a brace-expansion glob (`*.{dxf,dwg,DXF,DWG}`), guarding against "no files found" with `[ -e "$f" ]` checks.
3. **Conversion loop** — for each file, calls:
   ```bash
   dwg2pdf -a -margin=5 -l -c -p Tabloid -f -o "PDF/<name>.pdf" "<name>.<ext>"
   ```
   Output is piped into `zenity --progress` for a live progress bar, and each processed filename is recorded in a temporary file so the list survives the subshell created by the pipe.
4. **Cancellation check** — `PIPESTATUS` is checked after the pipeline to detect if the user closed the progress dialog early.
5. **Completion summary** — reads back the temporary file list and displays it in a `zenity --info` dialog, then removes the temp file.
6. **Optional merge** — if confirmed, prompts for an output name, verifies `pdfunite` is installed, rebuilds the list of expected PDF paths in conversion order, filters to files that actually exist, and runs `pdfunite` on them.

## Output Structure

```
<Selected Directory>/
├── drawing1.dwg
├── drawing2.dxf
└── PDF/
    ├── drawing1.pdf
    ├── drawing2.pdf
    └── merged.pdf        (only if you chose to merge)
```

## Notes & Caveats

- **Duplicate matches on case-insensitive filesystems:** If your filesystem doesn't distinguish case (or a directory contains e.g. both `A.dxf` and `A.DXF`-style duplicates), the glob `*.{dxf,dwg,DXF,DWG}` could process the same file more than once. On standard case-sensitive Linux filesystems this isn't an issue.
- **Path dependency:** The QCAD binary path is hardcoded. If QCAD is installed elsewhere or a different version is used, update `QCAD_BIN` near the top of the script.
- **Non-recursive:** Only files directly inside the selected folder are processed; subdirectories are not scanned.
- **Overwrite behavior:** Re-running the script on the same folder will overwrite existing PDFs of the same name in `PDF/` without warning.
- **Merge order:** PDFs are merged in the same order the files were originally converted (i.e., the shell's glob expansion order), not alphabetically re-sorted.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success, or user cancelled at any dialog prompt |
| 1 | Directory change failed, QCAD binary missing, `pdfunite` missing, or merge failed |
