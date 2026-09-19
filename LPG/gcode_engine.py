import os
import math


# ---------------------------------------------------------------------------
# Geometry: profile segments (line or arc) in (Z, radius) space.
#
# A "segment" is a dict:
#   line: {"kind": "line", "p1": (z, r), "p2": (z, r)}
#   arc:  {"kind": "arc", "p1": (z, r), "p2": (z, r), "center": (z, r),
#          "radius": r, "sign": +1/-1, "ccw": bool}
# "sign" says whether offsetting the arc outward increases (+1, convex - the
# material bulges away from the arc's own center) or decreases (-1, concave)
# its radius. "ccw" is whether the arc sweeps counterclockwise from p1 to p2
# in this (Z, radius) plane, used to choose G03 vs G02.
# ---------------------------------------------------------------------------

def _unit_normal(z1, r1, z2, r2):
    """Outward unit normal (away from the axis/solid) for a straight segment
    running from (z1,r1) to (z2,r2). Rotates the segment direction -90 deg."""
    dz, dr = z2 - z1, r2 - r1
    length = math.hypot(dz, dr)
    if length == 0:
        return (0.0, 1.0)
    return (dr / length, -dz / length)


def _line_intersect(p1, d1, p2, d2):
    """Intersection of line (p1 + t*d1) with line (p2 + s*d2); None if parallel."""
    x1, y1 = p1; dx1, dy1 = d1
    x2, y2 = p2; dx2, dy2 = d2
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-12:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / denom
    return (x1 + t * dx1, y1 + t * dy1)


def _line_circle_intersect(p, d, center, radius, near):
    """Intersection of line (p + t*d) with a circle, whichever solution is
    closest to `near` (used to disambiguate the two candidate points)."""
    px, py = p; dx, dy = d
    cx, cy = center
    fx, fy = px - cx, py - cy
    a = dx * dx + dy * dy
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = max(b * b - 4 * a * c, 0.0)  # clamp: true tangencies can read
    sq = math.sqrt(disc)                # slightly negative from rounding
    t1, t2 = (-b + sq) / (2 * a), (-b - sq) / (2 * a)
    cands = [(px + t1 * dx, py + t1 * dy), (px + t2 * dx, py + t2 * dy)]
    return min(cands, key=lambda q: math.hypot(q[0] - near[0], q[1] - near[1]))


def _circle_circle_intersect(c1, r1, c2, r2, near):
    """Intersection of two circles, whichever solution is closest to `near`.
    None if the circles don't meet."""
    x1, y1 = c1; x2, y2 = c2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d < 1e-9 or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return None
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    xm, ym = x1 + a * dx / d, y1 + a * dy / d
    cands = [(xm + h * dy / d, ym - h * dx / d), (xm - h * dy / d, ym + h * dx / d)]
    return min(cands, key=lambda q: math.hypot(q[0] - near[0], q[1] - near[1]))


def _point_on_circle_towards(center, radius, true_point):
    """Point on the given circle at the same angle as true_point relative to center."""
    ang = math.atan2(true_point[1] - center[1], true_point[0] - center[0])
    return (center[0] + radius * math.cos(ang), center[1] + radius * math.sin(ang))


def _arc_convex_sign(center, p1, p2):
    """+1 if the arc bulges away from its center (offsetting the boundary
    outward increases its radius) - the usual case for a fillet blending a
    step up to a larger diameter. -1 if it recedes toward its center
    (offsetting outward decreases its radius) - a groove/undercut. Compares
    the center's radial position to the chord midpoint; correct for the
    simple, sub-180-degree blends typical of a turned part profile."""
    mid_r = (p1[1] + p2[1]) / 2.0
    return 1.0 if center[1] < mid_r else -1.0


def _segments_from_points(points):
    """Convert profile points (each point after the first optionally
    carrying an 'arc' dict describing the segment leading to it, as
    produced by dxf_parser.extract_profile_from_dxf) into explicit
    (Z, radius) segments."""
    segs = []
    for i in range(len(points) - 1):
        p1 = (points[i]["z"], points[i]["dia"] / 2.0)
        p2 = (points[i + 1]["z"], points[i + 1]["dia"] / 2.0)
        arc = points[i + 1].get("arc")
        if arc:
            center = (arc["center_z"], arc["center_r"])
            radius = arc["radius"]
            segs.append({
                "kind": "arc", "p1": p1, "p2": p2, "center": center,
                "radius": radius, "sign": _arc_convex_sign(center, p1, p2),
                "ccw": arc.get("ccw", True),
            })
        else:
            segs.append({"kind": "line", "p1": p1, "p2": p2})
    return segs


def _offset_segment_curve(seg, offset):
    """The infinite line/circle underlying one segment's own perpendicular
    offset by `offset` (outward): a point+direction for a line, or the same
    center with an adjusted radius for an arc."""
    if seg["kind"] == "line":
        nz, nr = _unit_normal(*seg["p1"], *seg["p2"])
        p = (seg["p1"][0] + nz * offset, seg["p1"][1] + nr * offset)
        d = (seg["p2"][0] - seg["p1"][0], seg["p2"][1] - seg["p1"][1])
        return {"kind": "line", "p": p, "d": d}
    return {"kind": "arc", "center": seg["center"], "radius": seg["radius"] + seg["sign"] * offset}


def _curve_intersect(c1, c2, near):
    if c1["kind"] == "line" and c2["kind"] == "line":
        return _line_intersect(c1["p"], c1["d"], c2["p"], c2["d"])
    if c1["kind"] == "line" and c2["kind"] == "arc":
        return _line_circle_intersect(c1["p"], c1["d"], c2["center"], c2["radius"], near)
    if c1["kind"] == "arc" and c2["kind"] == "line":
        return _line_circle_intersect(c2["p"], c2["d"], c1["center"], c1["radius"], near)
    return _circle_circle_intersect(c1["center"], c1["radius"], c2["center"], c2["radius"], near)


def _offset_boundary(segments, offset):
    """Offset a chain of line/arc segments outward by `offset`, perpendicular
    to each one, joining consecutive pieces at their true intersection (or
    tangent point, for a smooth/G1-continuous join) so corners and blends
    stay geometrically consistent - not just a per-vertex shift. Returns a
    new list of segments, same order and kind, with updated p1/p2 (and
    radius, for arcs)."""
    if not segments:
        return []
    curves = [_offset_segment_curve(s, offset) for s in segments]
    out = [dict(s) for s in segments]
    for i, c in enumerate(curves):
        if c["kind"] == "arc":
            out[i]["radius"] = c["radius"]

    first = curves[0]
    out[0]["p1"] = first["p"] if first["kind"] == "line" else \
        _point_on_circle_towards(first["center"], first["radius"], segments[0]["p1"])

    for i in range(len(segments) - 1):
        corner = _curve_intersect(curves[i], curves[i + 1], segments[i]["p2"])
        if corner is None:
            corner = segments[i]["p2"]  # degenerate fallback: shouldn't happen in practice
        out[i]["p2"] = corner
        out[i + 1]["p1"] = corner

    last = curves[-1]
    if last["kind"] == "line":
        out[-1]["p2"] = (last["p"][0] + last["d"][0], last["p"][1] + last["d"][1])
    else:
        out[-1]["p2"] = _point_on_circle_towards(last["center"], last["radius"], segments[-1]["p2"])
    return out


def _seg_r_range(seg):
    return (min(seg["p1"][1], seg["p2"][1]), max(seg["p1"][1], seg["p2"][1]))


def _z_at_r(boundary, target_r):
    """First Z (walking from the shallow end) where the boundary's radius
    reaches target_r. Returns None if it never does."""
    for seg in boundary:
        lo, hi = _seg_r_range(seg)
        if hi < target_r - 1e-9:
            continue
        if seg["kind"] == "line":
            (z1, r1), (z2, r2) = seg["p1"], seg["p2"]
            if r2 == r1:
                return z1
            t = max(0.0, min(1.0, (target_r - r1) / (r2 - r1)))
            return z1 + t * (z2 - z1)
        cz, cr = seg["center"]
        val = max(seg["radius"] ** 2 - (target_r - cr) ** 2, 0.0)
        dz = math.sqrt(val)
        z1, z2 = seg["p1"][0], seg["p2"][0]
        lo_z, hi_z = min(z1, z2), max(z1, z2)
        candidates = [z for z in (cz - dz, cz + dz) if lo_z - 1e-6 <= z <= hi_z + 1e-6]
        if not candidates:
            candidates = [cz - dz, cz + dz]
        return min(candidates, key=lambda z: abs(z - seg["p1"][0]))
    return None


def _emit_cut(gcode, seg, feed_str=""):
    """Append the move that cuts along one segment to its p2 endpoint: G01
    for a line, G02/G03 (R format) for an arc."""
    tz, tr = seg["p2"]
    if seg["kind"] == "line":
        gcode.append(f"G01 X{tr * 2:.3f} Z{tz:.3f}{feed_str}")
    else:
        code = "G03" if seg.get("ccw", True) else "G02"
        gcode.append(f"{code} X{tr * 2:.3f} Z{tz:.3f} R{seg['radius']:.3f}{feed_str}")


def _arc_sample_points(seg, n=12):
    """Sample n+1 points along an arc segment from p1 to p2 (for the canvas
    preview only, which draws plain line segments)."""
    cz, cr = seg["center"]
    radius = seg["radius"]
    a1 = math.atan2(seg["p1"][1] - cr, seg["p1"][0] - cz)
    a2 = math.atan2(seg["p2"][1] - cr, seg["p2"][0] - cz)
    if seg.get("ccw", True):
        if a2 < a1:
            a2 += 2 * math.pi
    else:
        if a2 > a1:
            a2 -= 2 * math.pi
    return [(cz + radius * math.cos(a1 + (a2 - a1) * i / n),
             cr + radius * math.sin(a1 + (a2 - a1) * i / n)) for i in range(n + 1)]


def densify_profile(profile, arc_segments=12):
    """Expand any arc segments in a profile (as returned by
    extract_profile_from_dxf) into a series of plain (dia, z) points, for
    rendering a smooth curve on a canvas that only draws straight lines.
    Lines pass through unchanged."""
    if len(profile) < 2:
        return list(profile)
    segs = _segments_from_points(profile)
    out = [{"dia": profile[0]["dia"], "z": profile[0]["z"]}]
    for seg in segs:
        if seg["kind"] == "line":
            out.append({"dia": seg["p2"][1] * 2.0, "z": seg["p2"][0]})
        else:
            for (z, r) in _arc_sample_points(seg, arc_segments)[1:]:
                out.append({"dia": r * 2.0, "z": z})
    return out


# ---------------------------------------------------------------------------
# Canvas preview
# ---------------------------------------------------------------------------

def calculate_roughing_moves(profile, stock_dia, doc, allowance, nose_radius=0.2,
                              clr=2.0, approach_margin=1.0):
    """Generates coordinate packets for screen rendering, using the same
    contour-aware logic as export_linuxcnc_file (see there for the full
    explanation of the boundary math). Arcs are sampled into short line
    segments here since the canvas only draws straight lines."""
    x_approach = stock_dia + approach_margin
    x_relief = stock_dia + (2 * nose_radius)

    moves = []
    moves.append({"type": "G00", "x": x_approach, "z": clr})
    moves.append({"type": "G00", "x": x_approach, "z": 0.0})
    moves.append({"type": "G01", "x": -(2 * nose_radius), "z": 0.0})
    moves.append({"type": "G01", "x": x_approach, "z": 0.0})
    moves.append({"type": "G00", "x": x_approach, "z": clr})

    full_length_z = min(pt["z"] for pt in profile)
    od_segments = _segments_from_points(profile[1:-1])

    if od_segments:
        allowance_boundary = _offset_boundary(od_segments, allowance)
        combined_boundary = _offset_boundary(od_segments, allowance + nose_radius)
        floor_dia = combined_boundary[0]["p1"][1] * 2.0
    else:
        allowance_boundary, combined_boundary = [], []
        floor_dia = 0.0

    def seg_points(seg):
        return _arc_sample_points(seg) if seg["kind"] == "arc" else [seg["p1"], seg["p2"]]

    curr_dia = float(stock_dia)
    tail_traced = False
    prev_dia = stock_dia

    while curr_dia > floor_dia:
        curr_dia -= (2 * doc)
        if curr_dia <= floor_dia:
            break
        target_r = curr_dia / 2.0

        z_limit = _z_at_r(combined_boundary, target_r + nose_radius) if combined_boundary else None
        if z_limit is not None and z_limit >= -1e-9:
            break

        moves.append({"type": "G00", "x": curr_dia, "z": clr})

        if z_limit is None:
            moves.append({"type": "G01", "x": curr_dia, "z": full_length_z})
            moves.append({"type": "G01", "x": x_relief, "z": full_length_z})
        elif not tail_traced:
            moves.append({"type": "G01", "x": curr_dia, "z": z_limit})
            last_pos = (z_limit, target_r)
            for seg in allowance_boundary:
                if seg["p2"][0] < z_limit - 1e-9:
                    if math.hypot(last_pos[0] - seg["p1"][0], last_pos[1] - seg["p1"][1]) < 1e-6:
                        for (z, r) in seg_points(seg)[1:]:
                            moves.append({"type": "G01", "x": r * 2, "z": z})
                    else:
                        tz, tr = seg["p2"]
                        moves.append({"type": "G01", "x": tr * 2, "z": tz})
                    last_pos = seg["p2"]
            moves.append({"type": "G01", "x": x_relief, "z": last_pos[0]})
            tail_traced = True
        else:
            moves.append({"type": "G01", "x": curr_dia, "z": z_limit})
            moves.append({"type": "G01", "x": prev_dia, "z": z_limit})

        moves.append({"type": "G00", "x": x_relief, "z": clr})
        prev_dia = curr_dia
    return moves


def ensure_headers():
    h = ("; %\n; --- LinuxCNC 2-Axis Lathe G-Code ---\nG21; MM\nG18; XZ\nG7; Dia\n"
         "G90; Abs\nG97; Constant RPM\nG50 S2500\nT1 M6\nG94; Feed/Min")
    f = ("; %\n; --- Machine Teardown Codes ---\nG00 Z30.0 M5\nM9\nM30\n; %")
    if not os.path.exists("header.txt"):
        with open("header.txt", "w") as out: out.write(h)
    if not os.path.exists("footer.txt"):
        with open("footer.txt", "w") as out: out.write(f)


def export_linuxcnc_file(out_path, profile, stock_dia, doc, allowance,
                          nose_radius=0.2,
                          use_css=True, css_speed=250, rpm=1000,
                          use_fpr=True, fpr_feed=0.12, fpm_feed=100.0,
                          clr=2.0, approach_margin=1.0):
    ensure_headers()
    gcode = []

    # Two different X clearances:
    # - x_approach: flat safety margin used when moving INTO position (initial
    #   rapid, facing) - generous, not tied to the tool.
    # - x_relief: minimal clearance used when backing OFF a cut we just made
    #   (roughing retracts, finishing exit) - only needs to clear the nose radius.
    x_approach = stock_dia + approach_margin
    x_relief = stock_dia + (2 * nose_radius)
    face_cut = -(2 * nose_radius)

    # Active cutting feed mode, chosen by the "Use FPR" checkbox: feed per
    # revolution (G95, mm/rev) or feed per minute (G94, mm/min).
    feed_gcode = "G95" if use_fpr else "G94"
    feed_desc = "Feed per Rev" if use_fpr else "Feed per Min"
    feed = fpr_feed if use_fpr else fpm_feed

    with open("header.txt", "r") as f: gcode.append(f.read().strip())

    # Dynamic parameter block: documents the actual values this job was run with
    gcode.append(f"; Stock Size - {stock_dia:.0f}mm")
    gcode.append(f"; Max Doc - {doc:.1f} mm")
    gcode.append(f"; Finish Allowance - {allowance:.1f} mm")
    gcode.append(f"; Tool Nose Radius - {nose_radius:.1f} mm")
    if use_fpr:
        gcode.append(f"; Feed - {fpr_feed:.2f} mm/rev (FPR)")
    else:
        gcode.append(f"; Feed - {fpm_feed:.1f} mm/min (FPM)")
    if use_css:
        gcode.append(f"; CSS - {css_speed:.0f} mm/m")
    else:
        gcode.append(f"; RPM - {rpm:.0f} (constant RPM, no CSS)")
    gcode.append("; %")

    # Start the spindle at a constant RPM so it can get up to speed while X may
    # still be in a "bad" (large diameter) position; switch to CSS once
    # positioned, only if "Use CSS" is checked - otherwise stay constant RPM.
    gcode.append(f"M03 S{rpm:.0f}")
    gcode.append(f"G00 X{x_approach:.3f} Z{clr:.3f} M8\n")

    # 1. Facing Sequence
    gcode.append("; --- Step 1: Facing Operation at Z0.0 ---")
    gcode.append("G94 ; Feed per Min for positioning")
    gcode.append(f"G00 X{x_approach:.3f}")
    if use_css:
        gcode.append(f"G96 S{css_speed:.0f}    ; CSS")
    gcode.append("G00 Z0.0")
    gcode.append(f"{feed_gcode} ; {feed_desc} for plunge cut")
    gcode.append(f"G01 X{face_cut:.3f} F{feed:.3f} ; Cut past center for tool radius")
    gcode.append(f"{feed_gcode} ; {feed_desc}")
    gcode.append(f"G00 Z{clr:.3f}\n")

    # 2. Roughing passes loop - contour aware. od_segments excludes the front
    # face (profile[0]) and the dropped closing centerline point (profile[-1])
    # - it's the pure OD-vs-Z turning contour, lines and arcs alike.
    full_length_z = min(pt["z"] for pt in profile)
    od_segments = _segments_from_points(profile[1:-1])

    if od_segments:
        allowance_boundary = _offset_boundary(od_segments, allowance)
        combined_boundary = _offset_boundary(od_segments, allowance + nose_radius)
        # Floor is where the tool's physical nose - not just the programmed
        # allowance - stops leaving any real depth to cut near the face.
        floor_dia = combined_boundary[0]["p1"][1] * 2.0
    else:
        allowance_boundary, combined_boundary = [], []
        floor_dia = 0.0

    curr_dia = float(stock_dia)
    p_num = 1
    tail_traced = False
    prev_dia = stock_dia

    gcode.append("; --- Step 2: Main Roughing Sequences ---")
    while curr_dia > floor_dia:
        curr_dia -= (2 * doc)
        if curr_dia <= floor_dia:
            break  # No usable depth remains near the face corner - the
            # facing operation and finishing pass already own it.
        target_r = curr_dia / 2.0

        # Depth at which the tool's physical nose - not just the programmed
        # tip position - would first violate the finish allowance boundary.
        z_limit = _z_at_r(combined_boundary, target_r + nose_radius) if combined_boundary else None
        if z_limit is not None and z_limit >= -1e-9:
            break  # Same safety check as the floor above, belt-and-suspenders.

        gcode.append(f"(Pass {p_num} - X: {curr_dia:.3f})")
        gcode.append(f"G00 X{curr_dia:.3f}")

        if z_limit is None:
            # The boundary never gets in the way at this diameter.
            gcode.append(f"G01 Z{full_length_z:.3f} F{feed:.3f}")
            gcode.append(f"G01 X{x_relief:.3f} F{feed:.3f}")
        elif not tail_traced:
            # First pass to reach the boundary - it alone is responsible for
            # clearing everything deeper. Cut to the safe depth, then trace
            # the true finish-allowance boundary the rest of the way to the
            # end (no later, smaller pass will ever need to visit it again).
            gcode.append(f"G01 Z{z_limit:.3f} F{feed:.3f}")
            last_pos = (z_limit, target_r)
            for seg in allowance_boundary:
                if seg["p2"][0] < z_limit - 1e-9:
                    if math.hypot(last_pos[0] - seg["p1"][0], last_pos[1] - seg["p1"][1]) < 1e-6:
                        # Tool is actually on this segment's own curve -
                        # cut it properly (G02/G03 for an arc).
                        _emit_cut(gcode, seg, feed_str=f" F{feed:.3f}")
                    else:
                        # This is the entry segment straddling z_limit - the
                        # tool ISN'T at its true start point, so a fixed-
                        # radius arc here would pass through the wrong
                        # center. Approximate the transition with a
                        # straight line instead (same tolerance already
                        # accepted for a straddled line segment).
                        tz, tr = seg["p2"]
                        gcode.append(f"G01 X{tr * 2:.3f} Z{tz:.3f} F{feed:.3f}")
                    last_pos = seg["p2"]
            gcode.append(f"G01 X{x_relief:.3f} F{feed:.3f}")
            tail_traced = True
        else:
            # The tail was already cleared by an earlier pass - just take
            # this shallower slice and retract to what that pass left behind.
            gcode.append(f"G01 Z{z_limit:.3f} F{feed:.3f}")
            gcode.append(f"G01 X{prev_dia:.3f} F{feed:.3f}")

        gcode.append(f"G00 Z{clr:.3f}")
        prev_dia = curr_dia
        p_num += 1

    # 3. Finish profile contour pass - nose-radius compensated.
    # NOTE: the sorted profile's last point is the sketch closing back to the
    # centerline (the DXF's drawn face at the far end) - it's not OD material
    # to cut, so it's excluded up front (cut_points).
    #
    # Every segment junction in cut_points is a true corner (or a smooth,
    # tangent blend, e.g. a fillet arc) EXCEPT the very last point (nothing
    # follows it but a retract). A round-nosed tool can't trace a sharp
    # corner without adjustment: the imaginary tip position there is found
    # by offsetting each adjacent segment perpendicular by the nose radius
    # (an arc offsets to the same center with an adjusted radius),
    # intersecting the two offset curves for the nose CENTER's position at
    # that corner, then converting center -> tip by subtracting the nose
    # radius from both Z and R. An arc segment's own radius for cutting is
    # that same offset radius - only its center shifts, which the R-format
    # G02/G03 move (with its two compensated endpoints) already captures
    # without needing the center explicitly. The very first point is
    # replaced by the established "past center" facing standoff, and the
    # very last point is cut at its true (uncompensated) value.
    cut_points = profile[:-1] if len(profile) > 1 else profile
    true_segments = _segments_from_points(cut_points)

    compensated = []
    if true_segments:
        center_boundary = _offset_boundary(true_segments, nose_radius)
        for i, seg in enumerate(true_segments):
            new_seg = dict(seg)
            if i < len(true_segments) - 1:
                cz, cr = center_boundary[i]["p2"]
                new_seg["p2"] = (cz - nose_radius, cr - nose_radius)
            if new_seg["kind"] == "arc":
                new_seg["radius"] = center_boundary[i]["radius"]
            compensated.append(new_seg)

    gcode.append("\n; --- Step 3: Profile Contour Finishing Pass ---")
    gcode.append(f"G00 X{face_cut:.3f} Z{clr:.3f}")
    gcode.append(f"G01 X{face_cut:.3f} Z0.000 F{feed * 0.5:.3f}")
    for seg in compensated:
        _emit_cut(gcode, seg)

    last_z = compensated[-1]["p2"][0] if compensated else 0.0
    gcode.append(f"G01 X{x_relief:.3f} Z{last_z:.3f} F{feed:.3f}")

    gcode.append("")
    with open("footer.txt", "r") as f: gcode.append(f.read().strip())
    with open(out_path, "w") as out: out.write("\n".join(gcode))