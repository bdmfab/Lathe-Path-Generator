import math

from gcode_engine import ensure_headers

# ---------------------------------------------------------------------------
# G76 multipass threading (LinuxCNC flavour), metric ISO 60-degree threads.
#
# LinuxCNC G76 recap (this is NOT the Fanuc/Haas format):
#   G76 P- Z- I- J- K- R- Q- H- E- L-
#   Drive line : line parallel to Z through the X position the tool is at
#                when G76 is called.
#   P  pitch (mm/rev)            Z  final Z of the thread
#   I  thread PEAK offset from the drive line. NEGATIVE = external thread,
#      POSITIVE = internal thread.
#   J  first cut depth, measured from the peak
#   K  full thread depth, measured from the peak
#   R  depth degression (1.0 = constant depth, 2.0 = constant area)
#   Q  compound slide angle (29.5 for a 60 degree thread)
#   H  spring (no-infeed) passes
#   E  taper distance along the drive line
#   L  which ends get the taper: 0 none, 1 entry, 2 exit, 3 both
#
# I, J and K are radial values. To keep that unambiguous regardless of the
# diameter-mode handling, the program switches to G8 (radius mode) just for
# the G76 block - the same trick LinuxCNC's own g76base.ngc wrapper uses -
# and goes back to G7 afterwards.
# ---------------------------------------------------------------------------

# (label, nominal major dia, coarse pitch) - ISO metric coarse
ISO_COARSE_PRESETS = [
    ("M3 x 0.5", 3.0, 0.5),
    ("M4 x 0.7", 4.0, 0.7),
    ("M5 x 0.8", 5.0, 0.8),
    ("M6 x 1.0", 6.0, 1.0),
    ("M8 x 1.25", 8.0, 1.25),
    ("M10 x 1.5", 10.0, 1.5),
    ("M12 x 1.75", 12.0, 1.75),
    ("M14 x 2.0", 14.0, 2.0),
    ("M16 x 2.0", 16.0, 2.0),
    ("M20 x 2.5", 20.0, 2.5),
    ("M24 x 3.0", 24.0, 3.0),
    ("M30 x 3.5", 30.0, 3.5),
]

# ISO 68-1 basic profile factors (x pitch)
EXTERNAL_DEPTH_FACTOR = 0.6134    # external thread height h3 = 17/24 * H
INTERNAL_DEPTH_FACTOR = 0.5413    # internal thread height H1 = 5/8 * H
INTERNAL_MINOR_FACTOR = 1.0825    # internal minor dia D1 = D - 1.0825 * P


def thread_geometry(external, major_dia, pitch, clearance=2.0, depth_override=0.0):
    """Work out the radial layout of the thread. All radii in mm.

    External: peak is the major radius, root is `depth` below it, and the
    drive line sits `clearance` above the peak (so I = -clearance).
    Internal: peak is the bore (minor) radius, root is `depth` outside it,
    and the drive line sits `clearance` inside the bore (so I = +clearance).
    """
    if major_dia <= 0:
        raise ValueError("Major diameter must be greater than zero.")
    if pitch <= 0:
        raise ValueError("Pitch must be greater than zero.")
    if clearance <= 0:
        raise ValueError("Radial clearance must be greater than zero.")
    if depth_override < 0:
        raise ValueError("Depth K can't be negative (use 0 for automatic).")

    if external:
        depth = depth_override if depth_override > 0 else EXTERNAL_DEPTH_FACTOR * pitch
        peak_r = major_dia / 2.0
        root_r = peak_r - depth
        drive_r = peak_r + clearance
        i_val = -clearance
        if root_r <= 0:
            raise ValueError("Thread depth is larger than the thread radius.")
    else:
        depth = depth_override if depth_override > 0 else INTERNAL_DEPTH_FACTOR * pitch
        peak_r = (major_dia - INTERNAL_MINOR_FACTOR * pitch) / 2.0
        root_r = peak_r + depth
        drive_r = peak_r - clearance
        i_val = clearance
        if peak_r <= 0:
            raise ValueError("Pitch is too coarse for this diameter.")
        if drive_r <= 0:
            raise ValueError("Radial clearance is larger than the bore radius - "
                             "reduce it so the drive line stays inside the bore.")

    return {
        "k": depth,
        "i": i_val,
        "peak_dia": peak_r * 2.0,
        "root_dia": root_r * 2.0,
        "drive_dia": drive_r * 2.0,
        "drive_r": drive_r,
    }


def estimate_pass_count(first_cut, depth, degression):
    """Approximate number of cutting passes. LinuxCNC takes pass n to a
    depth of J * n^(1/R), so passes ~= (K / J)^R."""
    if first_cut <= 0 or degression <= 0:
        return 1
    return max(1, int(math.ceil((depth / first_cut) ** degression - 1e-9)))


def _validate(length, z_start, first_cut, depth, degression, compound_angle,
              spring_passes, taper_dist, taper_ends, rpm):
    if length <= 0:
        raise ValueError("Thread length must be greater than zero.")
    if z_start <= -length:
        raise ValueError("Start Z must be on the lead-in side of the thread end.")
    if first_cut <= 0:
        raise ValueError("First cut J must be greater than zero.")
    if first_cut > depth:
        raise ValueError(f"First cut J ({first_cut:.3f}) can't exceed the thread depth K ({depth:.3f}).")
    if degression < 1.0:
        raise ValueError("Degression R must be 1.0 or greater.")
    if not 0 <= compound_angle < 90:
        raise ValueError("Compound angle Q must be between 0 and 90 degrees.")
    if spring_passes < 0:
        raise ValueError("Spring passes H can't be negative.")
    if taper_dist < 0:
        raise ValueError("Taper distance E can't be negative.")
    if taper_ends not in (0, 1, 2, 3):
        raise ValueError("Taper ends L must be 0, 1, 2 or 3.")
    if taper_ends and taper_dist <= 0:
        raise ValueError("Set a taper distance E greater than zero, or set taper ends to None.")
    if rpm <= 0:
        raise ValueError("Thread RPM must be greater than zero.")


def build_thread_program(external, major_dia, pitch, length, z_start=5.0,
                         clearance=2.0, depth_override=0.0, first_cut=0.15,
                         degression=1.5, compound_angle=29.5, spring_passes=2,
                         taper_dist=0.0, taper_ends=0, rpm=400):
    """Return the complete LinuxCNC program text for one G76 thread."""
    geo = thread_geometry(external, major_dia, pitch, clearance, depth_override)
    _validate(length, z_start, first_cut, geo["k"], degression, compound_angle,
              spring_passes, taper_dist, taper_ends, rpm)

    ensure_headers()
    z_end = -length
    kind = "External" if external else "Internal"

    g76 = (f"G76 P{pitch:.3f} Z{z_end:.3f} I{geo['i']:.3f} J{first_cut:.3f} "
           f"K{geo['k']:.3f} R{degression:.2f} Q{compound_angle:.1f} H{int(spring_passes)}")
    if taper_ends:
        g76 += f" E{taper_dist:.3f} L{int(taper_ends)}"

    lines = []
    with open("header.txt", "r") as f:
        lines.append(f.read().strip())
    lines.append(f"; --- G76 {kind} Thread: M{major_dia:g} x {pitch:g} ---")
    lines.append(f"; Thread Length - {length:.3f} mm")
    if external:
        lines.append(f"; Pre-turn OD to {geo['peak_dia']:.3f} mm before threading")
        lines.append(f"; Root (minor) diameter - {geo['root_dia']:.3f} mm")
    else:
        lines.append(f"; Pre-bore to {geo['peak_dia']:.3f} mm before threading")
        lines.append(f"; Root (major) diameter - {geo['root_dia']:.3f} mm")
    lines.append(f"; Thread Depth K - {geo['k']:.3f} mm")
    lines.append(f"; Thread RPM - {rpm:.0f} (constant RPM - G76 needs G97, not CSS)")
    lines.append("; %")
    lines.append(f"M03 S{rpm:.0f}")
    lines.append(f"G00 X{geo['drive_dia']:.3f} Z{z_start:.3f} M8 ; Drive line")
    lines.append("")
    lines.append("; --- Threading cycle (G8: I/J/K are radial) ---")
    lines.append("G8 ; Radius mode")
    lines.append(g76)
    lines.append("G7 ; Back to diameter mode")
    lines.append(f"G00 Z{z_start:.3f}")
    lines.append("")
    with open("footer.txt", "r") as f:
        lines.append(f.read().strip())
    return "\n".join(lines)


def export_thread_file(out_path, **params):
    """Build the thread program and write it to out_path. Returns the text."""
    text = build_thread_program(**params)
    with open(out_path, "w") as out:
        out.write(text)
    return text
