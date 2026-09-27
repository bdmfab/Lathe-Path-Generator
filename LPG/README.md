# QCAD Lathe Visualizer & CAM Engine

A small desktop tool that turns a 2-axis lathe part profile drawn in a DXF
file into LinuxCNC-ready G-code, with a live toolpath preview and a
syntax-highlighted review of the generated program before it ever reaches
a machine.

## Files

| File | Purpose |
|---|---|
| `DxfView.py` | The GUI (Tkinter). Run this. |
| `dxf_parser.py` | Reads a DXF file and turns its LINE/ARC entities into an ordered part profile. |
| `gcode_engine.py` | All of the CAM logic: contour-aware roughing, nose-radius compensation, G-code generation. |
| `header.txt` | Machine startup G-code, read fresh on every export. Edit freely. |
| `footer.txt` | Machine shutdown G-code, read fresh on every export. Edit freely. |
| `lathe_cam_settings.json` | Auto-generated. Remembers your last-used field values between runs. |

## Requirements

- Python 3
- [`ezdxf`](https://pypi.org/project/ezdxf/) (`pip install ezdxf`)
- Tkinter (usually included with Python; on Linux you may need `python3-tk`
  from your package manager)

## Running it

```
python3 DxfView.py
```

## Drawing the part

- Draw the part's **half-profile** (one side of the centerline) on **layer
  `0`**, using `LINE` and `ARC` entities.
- Axes: the DXF's X-axis is the lathe's **Z-axis** (length), and the DXF's
  Y-axis is **radius** (not diameter) - the tool doubles it internally.
- Draw the profile as one continuous, connected chain from the front face
  (at the centerline) to the back face (also closing at the centerline).
  The parser chains segments by matching shared endpoints, so gaps or
  disconnected pieces will cause an error rather than a guess.
- The chain's first and last segments (the front and back face, both
  running into the centerline) are handled specially - the front face
  becomes the facing operation and the start of the finishing pass; the
  closing segment at the far end is treated as a stock/relief boundary,
  not a real face to cut.

## Workflow

1. **Open DXF** - load the part.
2. Adjust the parameter fields (see below).
3. **Refresh** - redraws the live preview using the current parameters,
   without writing any file.
4. **Export G-Code** - writes a `.ngc` file next to the source DXF, and
   loads it into the G-Code Review panel on the right.

## Parameter fields

| Field | Meaning |
|---|---|
| Stock | Raw stock diameter (mm) |
| Doc | Depth of cut per roughing pass, on diameter (mm) |
| Allow | Finish allowance left for the finishing pass, on radius (mm) |
| Nose R | Tool tip nose radius (mm) - used for facing standoff, roughing clearance, and finishing-pass compensation |
| Max RPM | Spindle speed cap. Emitted as `G50 S{Max RPM}` in every export. |
| RPM | Constant spindle RPM. Always used for the initial `M03 S{RPM}` startup. |
| CSS (S) | Target constant surface speed, in **m/min** |
| Use CSS | If checked, the program switches to `G96 S{CSS}` once positioned and stays there. If unchecked, but CSS is non-zero, each roughing pass instead gets an explicit `S{calculated RPM}` computed for that pass's own diameter (a manual, per-pass equivalent of CSS without ever leaving `G97`). |
| FPM | Feed rate in mm/min, used when not in FPR mode |
| FPR | Feed rate in mm/rev, used when in FPR mode |
| Use FPR | If checked, cutting feed uses `G95` with the FPR value. If unchecked, but FPR is non-zero, each roughing pass instead gets its FPM-equivalent feed (`FPR x that pass's RPM`) computed automatically. |

The RPM/feed override behavior above currently only applies to the
roughing passes, not facing or finishing.

## What the engine actually does

- **Facing**: cuts the front face, running slightly past center
  (`2 x nose radius`) so a round-nosed tool doesn't leave a nub at the axis.
- **Roughing**: steps in by `Doc` each pass. Every pass cuts only as deep
  as it safely can before the tool's *physical nose* (not just its
  programmed tip) would violate the finish allowance boundary - the first
  pass to reach that boundary traces it (line or arc) the rest of the way
  to the end of the part; every pass after that just retracts to whatever
  the previous pass already cleared. This is what keeps roughing from
  gouging into shoulders or fillets instead of naively cutting full-length
  at every diameter.
- **Finishing**: cuts the true, exact profile with nose-radius
  compensation applied at every corner (including where a fillet arc
  meets a straight section) - offsetting each adjacent segment by the
  nose radius, intersecting them for the tool's true contact point, then
  converting that to the imaginary sharp-tip position the G-code actually
  programs.
- **Arcs**: fully supported as `G02`/`G03` moves, both in roughing
  (tracing the allowance boundary around a fillet) and finishing (the
  true, nose-compensated fillet).

## G-Code Review panel

The right-hand panel shows the exported `.ngc` file with basic syntax
highlighting: **G-words green**, **M-words blue**, **Z-words red**.
It's read-only and refreshes automatically after every export.

## Known limitations / things to verify before cutting

- **Arc direction (`G02` vs `G03`)**: chosen by a standard convention for
  the G18 (XZ) plane, but this is a well-known area where actual behavior
  depends on your specific tool/turret orientation. **Verify in
  simulation/backplot** any time a new arc shape shows up in a part,
  especially if it curves the opposite way (concave vs. convex) from
  ones you've already checked.
- **`header.txt` / `footer.txt` only regenerate when missing.** If you
  edit them (e.g. removing a line), that edit is permanent until you
  delete the file - the program will never silently overwrite your
  changes, but it also won't warn you if the file gets out of sync with
  what the rest of the program expects (for example, `G50` is now always
  emitted dynamically from the Max RPM field, so it no longer needs to
  live in `header.txt` at all).
- **RPM/feed overrides are roughing-only** (see table above) - facing and
  finishing always use the flat RPM/CSS and FPM/FPR values directly.
- This is a 2-axis (X/Z) turning post only - no live tooling, sub-spindle,
  or milling moves.

## Settings persistence

Every field and both checkboxes are saved to `lathe_cam_settings.json`
(in the same folder as the script) when you close the window or export
successfully, and reloaded automatically the next time you start the
program.
