import math
import ezdxf


def _arc_endpoints(center, radius, start_angle_deg, end_angle_deg):
    """DXF ARC entities are always defined counterclockwise from
    start_angle to end_angle. Returns (p1, p2) as (z, radius) tuples for
    those two angles, in that order."""
    a1 = math.radians(start_angle_deg)
    a2 = math.radians(end_angle_deg)
    p1 = (center[0] + radius * math.cos(a1), center[1] + radius * math.sin(a1))
    p2 = (center[0] + radius * math.cos(a2), center[1] + radius * math.sin(a2))
    return p1, p2


def _points_close(a, b, tol=1e-3):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def extract_profile_from_dxf(dxf_path, manual_scale=1.0, layer_name="0"):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    q_str = f'*[layer=="{layer_name}"]'

    # Every piece of geometry becomes a "segment": a straight line or an arc,
    # each carrying its own two (z, radius) endpoints. Arcs additionally
    # carry their center, radius and whether the DXF defines them
    # counterclockwise (from p1 to p2, before any chain-reversal below).
    segments = []

    for entity in msp.query(q_str):
        if entity.dxftype() == 'LINE':
            sz, srad = entity.dxf.start.x * manual_scale, entity.dxf.start.y * manual_scale
            ez, erad = entity.dxf.end.x * manual_scale, entity.dxf.end.y * manual_scale
            if srad >= 0 and erad >= 0:
                segments.append({"kind": "line", "p1": (sz, srad), "p2": (ez, erad)})

        elif entity.dxftype() == 'ARC':
            center = (entity.dxf.center.x * manual_scale, entity.dxf.center.y * manual_scale)
            radius = entity.dxf.radius * manual_scale
            p1, p2 = _arc_endpoints(center, radius, entity.dxf.start_angle, entity.dxf.end_angle)
            if p1[1] >= 0 and p2[1] >= 0:
                segments.append({"kind": "arc", "p1": p1, "p2": p2,
                                  "center": center, "radius": radius, "ccw": True})

        elif entity.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
            if entity.dxftype() == 'LWPOLYLINE':
                verts = [(float(v[0]) * manual_scale, float(v[1]) * manual_scale)
                         for v in entity.get_points('xy')]
            else:
                verts = [(v.dxf.location.x * manual_scale, v.dxf.location.y * manual_scale)
                         for v in entity.vertices]
            for a, b in zip(verts, verts[1:]):
                if a[1] >= 0 and b[1] >= 0:
                    segments.append({"kind": "line", "p1": a, "p2": b})

    if not segments:
        raise ValueError("No valid geometry found on layer '0'.")

    # Chain segments end-to-end by matching shared endpoints (robust to
    # drawing order, and necessary for arcs since nearest-neighbor-by-point
    # can't tell a line from an arc). Start from whichever endpoint sits
    # closest to the front face, matching the original heuristic.
    all_points = [s["p1"] for s in segments] + [s["p2"] for s in segments]
    start_point = min(all_points, key=lambda p: (abs(p[0]), p[1]))

    remaining = list(segments)
    ordered = []
    current = start_point
    while remaining:
        found_idx, flip = None, False
        for idx, seg in enumerate(remaining):
            if _points_close(seg["p1"], current):
                found_idx, flip = idx, False
                break
            if _points_close(seg["p2"], current):
                found_idx, flip = idx, True
                break
        if found_idx is None:
            break  # remaining geometry isn't connected to this chain
        seg = remaining.pop(found_idx)
        if flip:
            seg = dict(seg, p1=seg["p2"], p2=seg["p1"])
            if seg["kind"] == "arc":
                seg["ccw"] = not seg["ccw"]
        ordered.append(seg)
        current = seg["p2"]

    # Build the point list the rest of the program expects. Each point
    # (after the first) carries an optional 'arc' description of the
    # segment that led to it, so downstream code can tell a line from an
    # arc without re-deriving geometry.
    profile = [{"dia": start_point[1] * 2.0, "z": start_point[0], "arc": None}]
    for seg in ordered:
        entry = {"dia": seg["p2"][1] * 2.0, "z": seg["p2"][0], "arc": None}
        if seg["kind"] == "arc":
            entry["arc"] = {
                "center_z": seg["center"][0],
                "center_r": seg["center"][1],
                "radius": seg["radius"],
                "ccw": seg["ccw"],
            }
        profile.append(entry)

    return profile