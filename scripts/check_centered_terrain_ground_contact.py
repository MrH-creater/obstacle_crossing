from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh

DEFAULT_TERRAIN_ROOT = Path(r"G:/Projects/obstacle_crossing/terrains/centered")
DEFAULT_Z_TOL_RATIO = 0.005
DEFAULT_Z_TOL_ABS = 1.0e-4
DEFAULT_FLAT_AREA_RATIO_THRESHOLD = 0.5
DEFAULT_FLAT_COVERAGE_THRESHOLD = 0.7


@dataclass(frozen=True)
class TerrainContactReport:
    file_name: str
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    extents: tuple[float, float, float]
    z_min: float
    z_max: float
    support_tol: float
    support_vertex_count: int
    support_unique_xy_count: int
    support_hull_area: float
    bbox_xy_area: float
    area_ratio: float
    support_extent_x: float
    support_extent_y: float
    coverage_x: float
    coverage_y: float
    contact_type: str
    tilt_axis_hint: str
    verdict: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose whether centered terrain STL files have flat-ground contact or edge/point contact."
    )
    parser.add_argument("--terrain-root", type=Path, default=DEFAULT_TERRAIN_ROOT)
    parser.add_argument("--z-tol-ratio", type=float, default=DEFAULT_Z_TOL_RATIO)
    parser.add_argument("--z-tol-abs", type=float, default=DEFAULT_Z_TOL_ABS)
    parser.add_argument("--flat-area-ratio-threshold", type=float, default=DEFAULT_FLAT_AREA_RATIO_THRESHOLD)
    parser.add_argument("--flat-coverage-threshold", type=float, default=DEFAULT_FLAT_COVERAGE_THRESHOLD)
    return parser.parse_args()


def _unique_rows(points: np.ndarray, decimals: int = 6) -> np.ndarray:
    if points.size == 0:
        return points
    rounded = np.round(points, decimals=decimals)
    return np.unique(rounded, axis=0)


def _cross(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def _convex_hull_2d(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if len(points) <= 1:
        return points
    pts = sorted({(float(x), float(y)) for x, y in points})
    if len(pts) <= 1:
        return np.asarray(pts, dtype=float)

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(np.asarray(lower[-2]), np.asarray(lower[-1]), np.asarray(p)) <= 0.0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(np.asarray(upper[-2]), np.asarray(upper[-1]), np.asarray(p)) <= 0.0:
            upper.pop()
        upper.append(p)

    hull = lower[:-1] + upper[:-1]
    return np.asarray(hull, dtype=float)


def _polygon_area(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Expected Trimesh for '{path}', got {type(mesh)!r}.")
    return mesh


def diagnose_mesh(mesh: trimesh.Trimesh, file_name: str, *, z_tol_ratio: float, z_tol_abs: float,
                  flat_area_ratio_threshold: float, flat_coverage_threshold: float) -> TerrainContactReport:
    bounds = np.asarray(mesh.bounds, dtype=float)
    bounds_min = tuple(float(v) for v in bounds[0])
    bounds_max = tuple(float(v) for v in bounds[1])
    extents = tuple(float(v) for v in bounds[1] - bounds[0])
    z_min = bounds_min[2]
    z_max = bounds_max[2]
    z_span = z_max - z_min
    support_tol = max(z_tol_abs, z_span * z_tol_ratio)

    vertices = np.asarray(mesh.vertices, dtype=float)
    support_mask = vertices[:, 2] <= z_min + support_tol
    support_vertices = vertices[support_mask]
    support_xy = support_vertices[:, :2] if len(support_vertices) else np.empty((0, 2), dtype=float)
    unique_support_xy = _unique_rows(support_xy, decimals=6)

    support_extent_x = float(unique_support_xy[:, 0].max() - unique_support_xy[:, 0].min()) if len(unique_support_xy) else 0.0
    support_extent_y = float(unique_support_xy[:, 1].max() - unique_support_xy[:, 1].min()) if len(unique_support_xy) else 0.0
    bbox_xy_area = max(extents[0] * extents[1], 0.0)

    hull = _convex_hull_2d(unique_support_xy)
    support_hull_area = _polygon_area(hull)
    area_ratio = support_hull_area / bbox_xy_area if bbox_xy_area > 0 else 0.0
    coverage_x = support_extent_x / extents[0] if extents[0] > 0 else 0.0
    coverage_y = support_extent_y / extents[1] if extents[1] > 0 else 0.0

    if len(unique_support_xy) == 0:
        contact_type = "unsupported"
        tilt_axis_hint = "n/a"
        verdict = "not_ground_contact"
        reason = "No vertices found in the support band at z_min."
    elif len(unique_support_xy) == 1:
        contact_type = "point_contact"
        tilt_axis_hint = "n/a"
        verdict = "not_flat_ground_contact"
        reason = "Only one unique support point exists at z_min."
    elif len(unique_support_xy) == 2 or support_hull_area <= 1.0e-8:
        contact_type = "edge_contact"
        if support_extent_x >= support_extent_y:
            tilt_axis_hint = "edge runs along X (tilt mainly along Y)"
        else:
            tilt_axis_hint = "edge runs along Y (tilt mainly along X)"
        verdict = "not_flat_ground_contact"
        reason = (
            f"Support points collapse to a line/edge at z_min (area_ratio={area_ratio:.6f}, "
            f"coverage_x={coverage_x:.3f}, coverage_y={coverage_y:.3f})."
        )
    elif area_ratio >= flat_area_ratio_threshold and coverage_x >= flat_coverage_threshold and coverage_y >= flat_coverage_threshold:
        contact_type = "flat_ground_contact"
        tilt_axis_hint = "n/a"
        verdict = "flat_ground_contact"
        reason = (
            f"Support footprint covers most of the XY footprint (area_ratio={area_ratio:.3f}, "
            f"coverage_x={coverage_x:.3f}, coverage_y={coverage_y:.3f})."
        )
    else:
        contact_type = "partial_ground_contact"
        tilt_axis_hint = "n/a"
        verdict = "not_flat_ground_contact"
        reason = (
            f"Support footprint exists but is too small/partial for a true flat base "
            f"(area_ratio={area_ratio:.3f}, coverage_x={coverage_x:.3f}, coverage_y={coverage_y:.3f})."
        )

    return TerrainContactReport(
        file_name=file_name,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        extents=extents,
        z_min=z_min,
        z_max=z_max,
        support_tol=support_tol,
        support_vertex_count=int(len(support_vertices)),
        support_unique_xy_count=int(len(unique_support_xy)),
        support_hull_area=support_hull_area,
        bbox_xy_area=bbox_xy_area,
        area_ratio=area_ratio,
        support_extent_x=support_extent_x,
        support_extent_y=support_extent_y,
        coverage_x=coverage_x,
        coverage_y=coverage_y,
        contact_type=contact_type,
        tilt_axis_hint=tilt_axis_hint,
        verdict=verdict,
        reason=reason,
    )


def format_report(report: TerrainContactReport) -> str:
    return (
        f"{report.file_name}\n"
        f"  verdict              : {report.verdict}\n"
        f"  contact_type         : {report.contact_type}\n"
        f"  reason               : {report.reason}\n"
        f"  tilt_axis_hint       : {report.tilt_axis_hint}\n"
        f"  bounds_min           : {np.round(report.bounds_min, 6)}\n"
        f"  bounds_max           : {np.round(report.bounds_max, 6)}\n"
        f"  extents              : {np.round(report.extents, 6)}\n"
        f"  z_min / z_max        : {report.z_min:.6f} / {report.z_max:.6f}\n"
        f"  support_tol          : {report.support_tol:.6f}\n"
        f"  support_vertex_count  : {report.support_vertex_count}\n"
        f"  support_unique_xy_cnt : {report.support_unique_xy_count}\n"
        f"  support_hull_area     : {report.support_hull_area:.6f}\n"
        f"  bbox_xy_area          : {report.bbox_xy_area:.6f}\n"
        f"  area_ratio            : {report.area_ratio:.6f}\n"
        f"  support_extent_x/y    : {report.support_extent_x:.6f} / {report.support_extent_y:.6f}\n"
        f"  coverage_x/y          : {report.coverage_x:.3f} / {report.coverage_y:.3f}\n"
    )


def main() -> None:
    args = parse_args()
    terrain_root = args.terrain_root
    stl_paths = sorted(terrain_root.glob("*.stl"))
    if not stl_paths:
        raise SystemExit(f"No STL files found in {terrain_root}")

    print("=" * 100)
    print("Centered terrain ground-contact diagnostic")
    print("=" * 100)
    print(f"terrain_root             : {terrain_root}")
    print(f"file_count               : {len(stl_paths)}")
    print(f"z_tol_ratio / z_tol_abs  : {args.z_tol_ratio} / {args.z_tol_abs}")
    print(f"flat_area_ratio_threshold: {args.flat_area_ratio_threshold}")
    print(f"flat_coverage_threshold  : {args.flat_coverage_threshold}")
    print()

    reports: list[TerrainContactReport] = []
    for path in stl_paths:
        mesh = _load_mesh(path)
        report = diagnose_mesh(
            mesh,
            path.name,
            z_tol_ratio=args.z_tol_ratio,
            z_tol_abs=args.z_tol_abs,
            flat_area_ratio_threshold=args.flat_area_ratio_threshold,
            flat_coverage_threshold=args.flat_coverage_threshold,
        )
        reports.append(report)
        print(format_report(report))

    flat_count = sum(1 for report in reports if report.verdict == "flat_ground_contact")
    print("=" * 100)
    print(f"summary_flat_ground_contact : {flat_count}/{len(reports)}")
    print("summary_non_flat            :", len(reports) - flat_count)
    print("=" * 100)


if __name__ == "__main__":
    main()
