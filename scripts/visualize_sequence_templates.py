from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import torch
import trimesh
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "source" / "obstacle_crossing"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from obstacle_crossing.terrain import ContinuousSequenceSamplingCfg, build_default_obstacle_crossing_registry
from obstacle_crossing.terrain.sequence_generator import (
    build_training_template_pool,
    export_sequence_template,
    export_template_pool_manifest,
)
from obstacle_crossing.terrain.terrain_path_tracking import (
    PathTrackingCfg,
    TrackingPathCache,
    build_tracking_path_cache,
    compute_stateful_path_tracking_targets,
)
from obstacle_crossing.terrain.terrain_waypoints import WaypointPathRecord, waypoint_path_from_payload


def _load_path_velocity_math():
    module_path = PACKAGE_ROOT / "obstacle_crossing" / "mdp" / "commands" / "path_velocity_math.py"
    spec = importlib.util.spec_from_file_location("_obstacle_crossing_path_velocity_math_viz", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load path velocity math module from {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_path_velocity_math = _load_path_velocity_math()
PathVelocitySolverCfg = _path_velocity_math.PathVelocitySolverCfg
compute_desired_velocity_path_frame = _path_velocity_math.compute_desired_velocity_path_frame

GEOMETRY_BACKENDS = ("stl", "usd")
METADATA_BACKEND = "yaml"
BASE_FLOOR_WIDTH_X = 3.0
BASE_FLOOR_THICKNESS_Z = 0.20
BASE_FLOOR_TOP_Z = 0.0
DEFAULT_SEQUENCE_START_ITERATION = 10000
DEFAULT_OUTPUT_DIR = REPO_ROOT / "terrains" / "generated_sequences" / "visualization"
DEFAULT_TERRAIN_ROOT = REPO_ROOT
DEFAULT_COMMAND_VECTOR_SCALE = 0.55
DEFAULT_PATH_VELOCITY_SOLVER_CFG = PathVelocitySolverCfg()


@dataclass(frozen=True)
class LoadedTemplateArtifact:
    metadata: dict[str, Any]
    mesh: trimesh.Trimesh
    geometry_path: Path
    metadata_path: Path


def build_default_sampling_cfg() -> ContinuousSequenceSamplingCfg:
    return ContinuousSequenceSamplingCfg(
        sequence_train_start_iteration=10000,
        sequence_train_ratio_ramp_iterations=20000,
        sequence_train_env_ratio_initial=0.0,
        sequence_train_env_ratio_final=0.30,
        min_sequence_length=2,
        max_sequence_length=6,
        maximum_number_of_terrains=10,
        sequence_sampling_mode="sorted_subset",
        single_train_env_ratio=1.0,
        sequence_length_stage_iterations=5000,
        sequence_length_stage_targets=(2, 4, 6),
        template_refresh_interval_iterations=1000,
        enforce_minimum_one_tile_for_validation_roles=True,
        minimum_tile_rule_max_total_tiles=64,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate, export, and offline-visualize obstacle_crossing sequence templates. "
            "This is a trimesh-based validation tool for sequence geometry and metadata."
        )
    )
    parser.add_argument("--iteration", type=int, default=DEFAULT_SEQUENCE_START_ITERATION)
    parser.add_argument("--template-count", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--terrain-root",
        type=Path,
        default=DEFAULT_TERRAIN_ROOT,
        help="Root used to resolve registry terrain_file paths. Defaults to the repository root.",
    )
    parser.add_argument("--input-backend", choices=GEOMETRY_BACKENDS, default="stl")
    parser.add_argument("--output-backend", choices=GEOMETRY_BACKENDS, default="stl")
    parser.add_argument("--template-index", type=int)
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--visualize-only", action="store_true")
    parser.add_argument("--show-metadata", action="store_true")
    parser.add_argument("--show-segment-ranges", action="store_true")
    parser.add_argument("--show-buffer-ranges", action="store_true")
    parser.add_argument(
        "--render-path-overlays",
        action="store_true",
        help="Save top-down PNG overlays for mesh footprint, waypoints, target patches, segments, and buffers.",
    )
    parser.add_argument(
        "--render-tracking-overlay",
        action="store_true",
        help=(
            "Also overlay sampled robot_xy_path points, nearest projections, and lookahead targets computed by "
            "terrain_path_tracking.py. Implies --render-path-overlays."
        ),
    )
    parser.add_argument(
        "--render-command-vector-overlay",
        action="store_true",
        help=(
            "Also overlay target, tangent, lateral correction, and blended desired velocity vectors computed by "
            "path_velocity_math.py. Implies --render-path-overlays."
        ),
    )
    parser.add_argument("--tracking-sample-count", type=int, default=8)
    parser.add_argument(
        "--tracking-sample-spacing",
        type=float,
        help=(
            "Arc-length spacing for runtime tracking cache samples. If omitted, spacing is derived from "
            "--tracking-sample-count for backward-compatible review density."
        ),
    )
    parser.add_argument("--tracking-lateral-offset", type=float, default=0.55)
    parser.add_argument(
        "--target-direction-weight",
        type=float,
        default=DEFAULT_PATH_VELOCITY_SOLVER_CFG.target_direction_weight,
    )
    parser.add_argument(
        "--tangent-direction-weight",
        type=float,
        default=DEFAULT_PATH_VELOCITY_SOLVER_CFG.tangent_direction_weight,
    )
    parser.add_argument(
        "--lateral-correction-weight",
        type=float,
        default=DEFAULT_PATH_VELOCITY_SOLVER_CFG.lateral_correction_weight,
    )
    parser.add_argument(
        "--command-vector-max-lin-speed",
        type=float,
        default=DEFAULT_PATH_VELOCITY_SOLVER_CFG.max_lin_speed,
    )
    parser.add_argument("--command-vector-scale", type=float, default=DEFAULT_COMMAND_VECTOR_SCALE)
    parser.add_argument(
        "--overlay-output-dir",
        type=Path,
        help="Directory for overlay PNGs. Defaults to <output-dir>/overlays.",
    )
    parser.add_argument("--overlay-dpi", type=int, default=180)
    return parser.parse_args()


def ensure_valid_mode(args: argparse.Namespace) -> str:
    if args.export_only and args.visualize_only:
        raise SystemExit("--export-only and --visualize-only cannot be used together.")
    if args.render_tracking_overlay or args.render_command_vector_overlay:
        args.render_path_overlays = True
    if args.tracking_sample_count <= 0:
        raise SystemExit("--tracking-sample-count must be > 0.")
    if args.tracking_sample_spacing is not None and args.tracking_sample_spacing <= 0.0:
        raise SystemExit("--tracking-sample-spacing must be > 0 when provided.")
    if args.tracking_lateral_offset < 0.0:
        raise SystemExit("--tracking-lateral-offset must be >= 0.")
    if args.target_direction_weight < 0.0:
        raise SystemExit("--target-direction-weight must be >= 0.")
    if args.tangent_direction_weight < 0.0:
        raise SystemExit("--tangent-direction-weight must be >= 0.")
    if args.lateral_correction_weight < 0.0:
        raise SystemExit("--lateral-correction-weight must be >= 0.")
    if args.command_vector_max_lin_speed < 0.0:
        raise SystemExit("--command-vector-max-lin-speed must be >= 0.")
    if args.command_vector_scale <= 0.0:
        raise SystemExit("--command-vector-scale must be > 0.")
    if args.visualize_only:
        return "visualize-only"
    if args.export_only:
        return "export-only"
    return "full"


def build_and_export_templates(args: argparse.Namespace):
    registry = build_default_obstacle_crossing_registry()
    sampling_cfg = build_default_sampling_cfg()
    pool = build_training_template_pool(
        registry,
        args.iteration,
        sampling_cfg,
        template_count=args.template_count,
        seed=args.seed,
        terrain_root=args.terrain_root,
        input_backend=args.input_backend,
        output_backend=args.output_backend,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    exported_templates = []
    for template in pool.template_records:
        exported_templates.append(
            export_sequence_template(
                template,
                args.output_dir,
                geometry_backend=args.output_backend,
                metadata_backend=METADATA_BACKEND,
            )
        )
    exported_pool = replace(pool, template_records=tuple(exported_templates))
    manifest_path = export_template_pool_manifest(exported_pool, args.output_dir, metadata_backend=METADATA_BACKEND)
    return registry, sampling_cfg, exported_pool, manifest_path


def load_artifacts_from_manifest(output_dir: Path) -> tuple[dict[str, Any], list[LoadedTemplateArtifact]]:
    manifest_path = output_dir / f"sequence_pool_manifest.{METADATA_BACKEND}"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream) or {}

    artifacts: list[LoadedTemplateArtifact] = []
    for entry in manifest.get("templates", []):
        metadata_rel = entry.get("metadata_output_path_rel")
        geometry_rel = entry.get("geometry_output_path_rel")
        metadata_path = output_dir / metadata_rel if metadata_rel else Path(entry["metadata_output_path"])
        geometry_path = output_dir / geometry_rel if geometry_rel else Path(entry["geometry_output_path"])
        with metadata_path.open("r", encoding="utf-8") as stream:
            metadata = yaml.safe_load(stream) or {}
        mesh = trimesh.load(geometry_path, force="mesh")
        if not isinstance(mesh, trimesh.Trimesh):
            raise TypeError(f"Expected Trimesh for '{geometry_path}', got {type(mesh)!r}.")
        artifacts.append(
            LoadedTemplateArtifact(
                metadata=metadata,
                mesh=mesh,
                geometry_path=geometry_path,
                metadata_path=metadata_path,
            )
        )
    return manifest, artifacts


def filter_artifacts(artifacts: list[LoadedTemplateArtifact], template_index: int | None) -> list[LoadedTemplateArtifact]:
    if template_index is None:
        return artifacts
    if template_index < 0 or template_index >= len(artifacts):
        raise IndexError(f"template-index {template_index} is out of range for {len(artifacts)} templates.")
    return [artifacts[template_index]]


def print_pool_header(manifest: dict[str, Any], output_dir: Path) -> None:
    print("=" * 80)
    print("Sequence template pool summary")
    print("=" * 80)
    print(f"active_length_range : {tuple(manifest.get('active_sequence_length_range', []))}")
    print(f"template_count      : {manifest.get('template_count', 0)}")
    print(f"output_dir          : {output_dir}")
    print(f"refresh_reason      : {manifest.get('refresh_reason', 'unknown')}")
    print(f"input_backend       : {manifest.get('input_backend', 'unknown')}")
    print(f"output_backend      : {manifest.get('output_backend', 'unknown')}")
    print()


def print_template_summary(index: int, artifact: LoadedTemplateArtifact) -> None:
    metadata = artifact.metadata
    warnings = metadata.get("warnings", [])
    print("-" * 80)
    print(f"template_index       : {index}")
    print(f"sequence_id          : {metadata.get('sequence_id')}")
    print(f"terrain_ids          : {tuple(metadata.get('terrain_ids', []))}")
    print(f"terrain_keys         : {tuple(metadata.get('terrain_keys', []))}")
    print(f"buffer_lengths_y     : {tuple(round(float(v), 4) for v in metadata.get('buffer_lengths_y', []))}")
    print(f"sequence_total_length_y : {float(metadata.get('sequence_total_length_y', 0.0)):.4f}")
    print(f"warnings             : {warnings if warnings else 'None'}")
    print(f"geometry_output_path : {artifact.geometry_path}")
    print(f"metadata_output_path : {artifact.metadata_path}")


def _component_info(component: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    bounds = np.asarray(component.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    return bounds, extents


def identify_base_floor(artifact: LoadedTemplateArtifact) -> tuple[trimesh.Trimesh | None, list[trimesh.Trimesh], dict[str, Any]]:
    metadata = artifact.metadata
    components = list(artifact.mesh.split(only_watertight=False))
    if not components:
        return None, [], {"found": False, "reason": "mesh has no connected components"}

    expected_width = float(metadata.get("base_floor_width_x", BASE_FLOOR_WIDTH_X))
    expected_thickness = float(metadata.get("base_floor_thickness_z", BASE_FLOOR_THICKNESS_Z))
    expected_top_z = float(metadata.get("base_floor_top_z", BASE_FLOOR_TOP_Z))
    expected_length = float(metadata.get("sequence_total_length_y", 0.0))

    best_index = None
    best_score = None
    best_bounds = None
    best_extents = None
    for index, component in enumerate(components):
        bounds, extents = _component_info(component)
        score = (
            abs(extents[0] - expected_width)
            + abs(extents[1] - expected_length)
            + abs(bounds[1][2] - expected_top_z)
            + abs(bounds[0][2] - (expected_top_z - expected_thickness))
        )
        if best_score is None or score < best_score:
            best_index = index
            best_score = score
            best_bounds = bounds
            best_extents = extents

    assert best_index is not None
    floor_component = components[best_index]
    remaining = [component for i, component in enumerate(components) if i != best_index]
    result = {
        "found": (
            abs(best_extents[0] - expected_width) <= 0.05
            and abs(best_extents[1] - expected_length) <= 0.05
            and abs(best_bounds[1][2] - expected_top_z) <= 0.01
            and abs(best_bounds[0][2] - (expected_top_z - expected_thickness)) <= 0.01
        ),
        "bounds": best_bounds,
        "extents": best_extents,
        "expected_width": expected_width,
        "expected_length": expected_length,
        "expected_thickness": expected_thickness,
        "expected_top_z": expected_top_z,
        "component_count": len(components),
    }
    return floor_component, remaining, result


def inspect_segment_and_buffer_ranges(metadata: dict[str, Any]) -> dict[str, Any]:
    segment_ranges = [(float(start), float(end)) for start, end in metadata.get("segment_ranges_y", [])]
    buffer_ranges = [(float(start), float(end)) for start, end in metadata.get("buffer_ranges_y", [])]
    buffer_lengths = [float(v) for v in metadata.get("buffer_lengths_y", [])]
    sequence_total = float(metadata.get("sequence_total_length_y", 0.0))
    end_margin = float(metadata.get("base_floor_end_margin_y", 1.0))

    segment_monotonic = all(
        segment_ranges[i][0] <= segment_ranges[i][1] and segment_ranges[i][1] <= segment_ranges[i + 1][0]
        for i in range(max(len(segment_ranges) - 1, 0))
    ) if segment_ranges else True
    buffer_monotonic = all(start <= end for start, end in buffer_ranges)
    buffer_lengths_in_range = all(1.0 <= value <= 3.0 for value in buffer_lengths)

    buffer_matches = True
    for index, ((start, end), value) in enumerate(zip(buffer_ranges, buffer_lengths, strict=True)):
        if abs((end - start) - value) > 1.0e-3:
            buffer_matches = False
            break
        prev_segment_end = segment_ranges[index][1]
        next_segment_start = segment_ranges[index + 1][0]
        if abs(start - prev_segment_end) > 1.0e-3 or abs(end - next_segment_start) > 1.0e-3:
            buffer_matches = False
            break

    total_matches = True
    if segment_ranges:
        total_matches = abs(sequence_total - (segment_ranges[-1][1] + end_margin)) <= 1.0e-3

    return {
        "segment_ranges": segment_ranges,
        "buffer_ranges": buffer_ranges,
        "buffer_lengths": buffer_lengths,
        "segment_monotonic": segment_monotonic,
        "buffer_monotonic": buffer_monotonic,
        "buffer_lengths_in_range": buffer_lengths_in_range,
        "buffer_matches": buffer_matches,
        "sequence_total_matches": total_matches,
    }


def inspect_obstacle_placement(metadata: dict[str, Any], obstacle_components: list[trimesh.Trimesh], floor_top_z: float) -> dict[str, Any]:
    segment_ranges = [(float(start), float(end)) for start, end in metadata.get("segment_ranges_y", [])]
    assigned_counts = [0 for _ in segment_ranges]
    off_segment_components: list[tuple[int, float, float]] = []
    off_floor_components: list[tuple[int, float]] = []

    for index, component in enumerate(obstacle_components):
        bounds, _ = _component_info(component)
        y_min = float(bounds[0][1])
        y_max = float(bounds[1][1])
        z_min = float(bounds[0][2])
        if abs(z_min - floor_top_z) > 0.02:
            off_floor_components.append((index, z_min))
        overlaps = [
            seg_index
            for seg_index, (start_y, end_y) in enumerate(segment_ranges)
            if min(y_max, end_y) - max(y_min, start_y) > 1.0e-3
        ]
        if overlaps:
            assigned_counts[overlaps[0]] += 1
        else:
            off_segment_components.append((index, y_min, y_max))

    return {
        "segment_component_counts": assigned_counts,
        "all_segments_have_geometry": all(count > 0 for count in assigned_counts) if assigned_counts else True,
        "off_segment_components": off_segment_components,
        "off_floor_components": off_floor_components,
    }


def _xy_tuple(value: Any) -> tuple[float, float]:
    return (float(value[0]), float(value[1]))


def _range_tuple_list(values: Any) -> list[tuple[float, float]]:
    return [(float(start), float(end)) for start, end in values or []]


def _count_path_samples_by_y_region(
    y_values: list[float],
    segment_ranges: list[tuple[float, float]],
    buffer_ranges: list[tuple[float, float]],
    sequence_total_length_y: float,
) -> dict[str, int]:
    counts = {"segment": 0, "buffer": 0, "exit": 0, "outside": 0}
    obstacle_end_y = segment_ranges[-1][1] if segment_ranges else sequence_total_length_y
    for y in y_values:
        if any(start - 1.0e-6 <= y <= end + 1.0e-6 for start, end in segment_ranges):
            counts["segment"] += 1
        elif any(start - 1.0e-6 <= y <= end + 1.0e-6 for start, end in buffer_ranges):
            counts["buffer"] += 1
        elif obstacle_end_y - 1.0e-6 <= y <= sequence_total_length_y + 1.0e-6:
            counts["exit"] += 1
        else:
            counts["outside"] += 1
    return counts


def inspect_path_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    path = metadata.get("sequence_path") or {}
    if not path:
        return {"present": False}

    waypoints = [_xy_tuple(value) for value in path.get("waypoints_xy", [])]
    patches = list(path.get("target_patches", []))
    profile_ranges = list(path.get("profile_ranges", []))
    arc_lengths = [float(value) for value in path.get("waypoint_arc_lengths", [])]
    total_length_s = float(path.get("total_length_s", arc_lengths[-1] if arc_lengths else 0.0))
    sequence_total_length_y = float(metadata.get("sequence_total_length_y", 0.0))
    segment_ranges = _range_tuple_list(metadata.get("segment_ranges_y", []))
    buffer_ranges = _range_tuple_list(metadata.get("buffer_ranges_y", []))

    patch_centers = [_xy_tuple(patch.get("center_xy", (0.0, 0.0))) for patch in patches]
    patch_y_values = [center[1] for center in patch_centers]
    waypoint_y_values = [point[1] for point in waypoints]
    role_counts: dict[str, int] = {}
    for patch in patches:
        role = str(patch.get("role", "unknown"))
        role_counts[role] = role_counts.get(role, 0) + 1

    path_length_matches_arcs = True
    if arc_lengths:
        path_length_matches_arcs = abs(total_length_s - arc_lengths[-1]) <= 1.0e-4

    patch_centers_within_sequence_y = all(
        -1.0e-6 <= center[1] <= sequence_total_length_y + 1.0e-6
        for center in patch_centers
    )
    waypoint_y_monotonic = all(
        waypoints[index][1] <= waypoints[index + 1][1] + 1.0e-6
        for index in range(max(len(waypoints) - 1, 0))
    )

    return {
        "present": True,
        "path_id": path.get("path_id", "unknown"),
        "frame": path.get("frame", "unknown"),
        "forward_axis": path.get("forward_axis", "unknown"),
        "waypoint_count": len(waypoints),
        "target_patch_count": len(patches),
        "profile_range_count": len(profile_ranges),
        "total_length_s": total_length_s,
        "default_lookahead_distance": float(path.get("default_lookahead_distance", 0.0)),
        "corridor_half_width": float(path.get("corridor_half_width", 0.0)),
        "path_length_matches_arcs": path_length_matches_arcs,
        "patch_centers_within_sequence_y": patch_centers_within_sequence_y,
        "waypoint_y_monotonic": waypoint_y_monotonic,
        "patch_role_counts": role_counts,
        "waypoint_region_counts": _count_path_samples_by_y_region(
            waypoint_y_values,
            segment_ranges,
            buffer_ranges,
            sequence_total_length_y,
        ),
        "patch_region_counts": _count_path_samples_by_y_region(
            patch_y_values,
            segment_ranges,
            buffer_ranges,
            sequence_total_length_y,
        ),
    }


def inspect_template_geometry(artifact: LoadedTemplateArtifact) -> dict[str, Any]:
    metadata = artifact.metadata
    floor_component, obstacle_components, floor_info = identify_base_floor(artifact)
    range_info = inspect_segment_and_buffer_ranges(metadata)
    floor_top_z = float(metadata.get("base_floor_top_z", BASE_FLOOR_TOP_Z))
    obstacle_info = inspect_obstacle_placement(metadata, obstacle_components, floor_top_z)
    path_info = inspect_path_metadata(metadata)

    mesh_bounds, mesh_extents = _component_info(artifact.mesh)
    return {
        "mesh_bounds": mesh_bounds,
        "mesh_extents": mesh_extents,
        "floor_info": floor_info,
        "range_info": range_info,
        "obstacle_info": obstacle_info,
        "path_info": path_info,
        "obstacle_component_count": len(obstacle_components),
        "floor_component_present": floor_component is not None,
    }


def print_inspection_report(artifact: LoadedTemplateArtifact, report: dict[str, Any], args: argparse.Namespace) -> None:
    floor_info = report["floor_info"]
    range_info = report["range_info"]
    obstacle_info = report["obstacle_info"]
    path_info = report["path_info"]
    mesh_bounds = report["mesh_bounds"]
    mesh_extents = report["mesh_extents"]

    print(f"mesh_bounds          : min={np.round(mesh_bounds[0], 4)} max={np.round(mesh_bounds[1], 4)}")
    print(f"mesh_extents         : {np.round(mesh_extents, 4)}")
    print("geometry_checks      :")
    print(f"  base_floor_found   : {floor_info['found']}")
    print(
        "  base_floor_dims    : "
        f"actual=({floor_info['extents'][0]:.4f}, {floor_info['extents'][1]:.4f}, {floor_info['extents'][2]:.4f}) "
        f"expected~({floor_info['expected_width']:.4f}, {floor_info['expected_length']:.4f}, {floor_info['expected_thickness']:.4f})"
    )
    print(f"  obstacle_components: {report['obstacle_component_count']}")
    print(f"  segment_order_ok   : {range_info['segment_monotonic']}")
    print(f"  buffer_order_ok    : {range_info['buffer_monotonic']}")
    print(f"  buffer_len_in_1_3m : {range_info['buffer_lengths_in_range']}")
    print(f"  buffer_matches_gap : {range_info['buffer_matches']}")
    print(f"  sequence_total_ok  : {range_info['sequence_total_matches']}")
    print(f"  all_segments_have_geometry : {obstacle_info['all_segments_have_geometry']}")
    print(f"  off_floor_components       : {obstacle_info['off_floor_components'] or 'None'}")
    print(f"  off_segment_components     : {obstacle_info['off_segment_components'] or 'None'}")
    print("path_checks          :")
    print(f"  path_present       : {path_info['present']}")
    if path_info["present"]:
        print(f"  path_id            : {path_info['path_id']}")
        print(f"  path_frame         : {path_info['frame']}")
        print(f"  waypoints          : {path_info['waypoint_count']}")
        print(f"  target_patches     : {path_info['target_patch_count']}")
        print(f"  profile_ranges     : {path_info['profile_range_count']}")
        print(f"  path_total_length_s: {path_info['total_length_s']:.4f}")
        print(f"  lookahead_distance : {path_info['default_lookahead_distance']:.4f}")
        print(f"  corridor_half_width: {path_info['corridor_half_width']:.4f}")
        print(f"  path_length_ok     : {path_info['path_length_matches_arcs']}")
        print(f"  waypoint_y_order_ok: {path_info['waypoint_y_monotonic']}")
        print(f"  patches_in_y_range : {path_info['patch_centers_within_sequence_y']}")
        print(f"  waypoint_regions   : {path_info['waypoint_region_counts']}")
        print(f"  patch_regions      : {path_info['patch_region_counts']}")
        print(f"  patch_roles        : {path_info['patch_role_counts']}")

    if args.show_segment_ranges:
        print(f"segment_ranges_y     : {range_info['segment_ranges']}")
        print(f"segment_component_counts : {obstacle_info['segment_component_counts']}")
    if args.show_buffer_ranges:
        print(f"buffer_ranges_y      : {range_info['buffer_ranges']}")
    if args.show_metadata:
        print("metadata_payload     :")
        print(yaml.safe_dump(artifact.metadata, sort_keys=False, allow_unicode=True).rstrip())


def print_export_summary(manifest_path: Path, manifest: dict[str, Any]) -> None:
    print("=" * 80)
    print("Export complete")
    print("=" * 80)
    print(f"manifest_path        : {manifest_path}")
    print(f"template_count       : {manifest.get('template_count', 0)}")
    print()


def _patch_polygon_xy(patch: dict[str, Any]) -> np.ndarray:
    center = np.asarray(_xy_tuple(patch.get("center_xy", (0.0, 0.0))), dtype=float)
    half_size_x = float(patch.get("half_size_x", 0.0))
    half_size_y = float(patch.get("half_size_y", 0.0))
    heading = patch.get("heading_hint_rad")
    heading_rad = math.pi / 2.0 if heading is None else float(heading)
    forward = np.array([math.cos(heading_rad), math.sin(heading_rad)], dtype=float)
    lateral = np.array([math.cos(heading_rad - math.pi / 2.0), math.sin(heading_rad - math.pi / 2.0)], dtype=float)
    return np.stack(
        [
            center - lateral * half_size_x - forward * half_size_y,
            center + lateral * half_size_x - forward * half_size_y,
            center + lateral * half_size_x + forward * half_size_y,
            center - lateral * half_size_x + forward * half_size_y,
        ],
        axis=0,
    )


def _classify_y_region(
    y: float,
    segment_ranges: list[tuple[float, float]],
    buffer_ranges: list[tuple[float, float]],
    sequence_total_length_y: float,
) -> str:
    obstacle_end_y = segment_ranges[-1][1] if segment_ranges else sequence_total_length_y
    if any(start - 1.0e-6 <= y <= end + 1.0e-6 for start, end in segment_ranges):
        return "segment"
    if any(start - 1.0e-6 <= y <= end + 1.0e-6 for start, end in buffer_ranges):
        return "buffer"
    if obstacle_end_y - 1.0e-6 <= y <= sequence_total_length_y + 1.0e-6:
        return "exit"
    return "outside"


def render_path_overlay_png(
    artifact: LoadedTemplateArtifact,
    *,
    output_dir: Path,
    template_index: int,
    dpi: int,
    render_tracking_overlay: bool = False,
    tracking_sample_count: int = 8,
    tracking_sample_spacing: float | None = None,
    tracking_lateral_offset: float = 0.55,
    render_command_vector_overlay: bool = False,
    target_direction_weight: float = DEFAULT_PATH_VELOCITY_SOLVER_CFG.target_direction_weight,
    tangent_direction_weight: float = DEFAULT_PATH_VELOCITY_SOLVER_CFG.tangent_direction_weight,
    lateral_correction_weight: float = DEFAULT_PATH_VELOCITY_SOLVER_CFG.lateral_correction_weight,
    command_vector_max_lin_speed: float = DEFAULT_PATH_VELOCITY_SOLVER_CFG.max_lin_speed,
    command_vector_scale: float = DEFAULT_COMMAND_VECTOR_SCALE,
) -> Path | None:
    path = artifact.metadata.get("sequence_path") or {}
    if not path:
        print("path_overlay_png     : skipped (sequence_path missing)")
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon, Rectangle
    except ImportError as exc:
        print(f"path_overlay_png     : skipped (matplotlib unavailable: {exc})")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    sequence_id = str(artifact.metadata.get("sequence_id", f"template_{template_index:04d}"))
    safe_sequence_id = sequence_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    output_path = output_dir / f"{template_index:04d}_{safe_sequence_id}_path_overlay.png"

    waypoints = np.asarray([_xy_tuple(value) for value in path.get("waypoints_xy", [])], dtype=float)
    patches = list(path.get("target_patches", []))
    path_record = waypoint_path_from_payload(path)
    segment_ranges = _range_tuple_list(artifact.metadata.get("segment_ranges_y", []))
    buffer_ranges = _range_tuple_list(artifact.metadata.get("buffer_ranges_y", []))
    sequence_total_length_y = float(artifact.metadata.get("sequence_total_length_y", 0.0))
    floor_width = float(artifact.metadata.get("base_floor_width_x", BASE_FLOOR_WIDTH_X))
    floor_half_width = floor_width / 2.0

    fig_height = min(18.0, max(7.0, sequence_total_length_y * 0.45))
    fig_width = 8.5
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    floor_rect = Rectangle(
        (-floor_half_width, 0.0),
        floor_width,
        sequence_total_length_y,
        facecolor="#f4f4f0",
        edgecolor="#9a9a9a",
        linewidth=1.0,
        zorder=0,
    )
    ax.add_patch(floor_rect)

    for index, (start_y, end_y) in enumerate(segment_ranges):
        ax.axhspan(start_y, end_y, facecolor="#d8efe4", alpha=0.45, zorder=0)
        ax.text(
            -floor_half_width,
            (start_y + end_y) / 2.0,
            f"S{index}",
            va="center",
            ha="right",
            fontsize=8,
            color="#2f6b59",
        )
    for index, (start_y, end_y) in enumerate(buffer_ranges):
        ax.axhspan(start_y, end_y, facecolor="#ffe2b8", alpha=0.45, zorder=0)
        ax.text(
            floor_half_width,
            (start_y + end_y) / 2.0,
            f"B{index}",
            va="center",
            ha="left",
            fontsize=8,
            color="#986016",
        )

    vertices = np.asarray(artifact.mesh.vertices, dtype=float)
    if vertices.size:
        ax.scatter(
            vertices[:, 0],
            vertices[:, 1],
            c=vertices[:, 2],
            cmap="Greys",
            s=1.5,
            alpha=0.22,
            linewidths=0,
            zorder=1,
        )

    region_styles = {
        "segment": ("#f59e0b", 0.18, "#b45309"),
        "buffer": ("#22c55e", 0.18, "#15803d"),
        "exit": ("#3b82f6", 0.16, "#1d4ed8"),
        "outside": ("#ef4444", 0.18, "#b91c1c"),
    }
    for patch in patches:
        center_xy = _xy_tuple(patch.get("center_xy", (0.0, 0.0)))
        region = _classify_y_region(center_xy[1], segment_ranges, buffer_ranges, sequence_total_length_y)
        facecolor, alpha, edgecolor = region_styles[region]
        polygon = Polygon(
            _patch_polygon_xy(patch),
            closed=True,
            facecolor=facecolor,
            edgecolor=edgecolor,
            alpha=alpha,
            linewidth=0.8,
            zorder=3,
        )
        ax.add_patch(polygon)

    if patches:
        patch_centers = np.asarray([_xy_tuple(patch.get("center_xy", (0.0, 0.0))) for patch in patches], dtype=float)
        ax.scatter(
            patch_centers[:, 0],
            patch_centers[:, 1],
            s=12,
            color="#c2410c",
            edgecolors="white",
            linewidths=0.35,
            zorder=4,
            label="target_patch center",
        )
        arrow_stride = max(1, len(patches) // 16)
        arrow_centers: list[tuple[float, float]] = []
        arrow_uv: list[tuple[float, float]] = []
        for patch in patches[::arrow_stride]:
            heading = patch.get("heading_hint_rad")
            heading_rad = math.pi / 2.0 if heading is None else float(heading)
            arrow_centers.append(_xy_tuple(patch.get("center_xy", (0.0, 0.0))))
            arrow_uv.append((math.cos(heading_rad), math.sin(heading_rad)))
        arrow_center_array = np.asarray(arrow_centers, dtype=float)
        arrow_uv_array = np.asarray(arrow_uv, dtype=float)
        ax.quiver(
            arrow_center_array[:, 0],
            arrow_center_array[:, 1],
            arrow_uv_array[:, 0],
            arrow_uv_array[:, 1],
            angles="xy",
            scale_units="xy",
            scale=3.0,
            color="#7c2d12",
            width=0.004,
            zorder=5,
        )

    if len(waypoints):
        ax.plot(
            waypoints[:, 0],
            waypoints[:, 1],
            color="#2563eb",
            linewidth=1.4,
            zorder=6,
            label="waypoint path",
        )
        ax.scatter(
            waypoints[:, 0],
            waypoints[:, 1],
            s=7,
            color="#1d4ed8",
            alpha=0.75,
            linewidths=0,
            zorder=7,
        )
        ax.scatter(waypoints[0, 0], waypoints[0, 1], s=42, marker="o", color="#16a34a", zorder=8, label="entry")
        ax.scatter(waypoints[-1, 0], waypoints[-1, 1], s=48, marker="X", color="#dc2626", zorder=8, label="exit")

    if (render_tracking_overlay or render_command_vector_overlay) and path_record is not None:
        velocity_solver_cfg = PathVelocitySolverCfg(
            target_direction_weight=target_direction_weight,
            tangent_direction_weight=tangent_direction_weight,
            lateral_correction_weight=lateral_correction_weight,
            max_lin_speed=command_vector_max_lin_speed,
        )
        _draw_tracking_overlay(
            ax,
            path_record,
            sample_count=tracking_sample_count,
            sample_spacing=tracking_sample_spacing,
            lateral_offset=tracking_lateral_offset,
            render_tracking_overlay=render_tracking_overlay,
            render_command_vector_overlay=render_command_vector_overlay,
            velocity_solver_cfg=velocity_solver_cfg,
            command_vector_scale=command_vector_scale,
        )

    title = (
        f"{sequence_id}\n"
        f"waypoints={len(waypoints)} patches={len(patches)} "
        f"frame={path.get('frame', 'unknown')}"
    )
    if render_tracking_overlay or render_command_vector_overlay:
        if tracking_sample_spacing is None:
            title += f" tracking_samples={tracking_sample_count}"
        else:
            title += f" tracking_spacing={tracking_sample_spacing:.3f}m"
    if render_command_vector_overlay:
        title += (
            f" cmd_weights=({target_direction_weight:.2f},"
            f"{tangent_direction_weight:.2f},{lateral_correction_weight:.2f})"
        )
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_aspect("equal", adjustable="box")
    x_margin = max(0.35, floor_width * 0.15)
    y_margin = max(0.35, sequence_total_length_y * 0.02)
    ax.set_xlim(-floor_half_width - x_margin, floor_half_width + x_margin)
    ax.set_ylim(-y_margin, sequence_total_length_y + y_margin)
    ax.grid(True, color="#d4d4d4", linewidth=0.45, alpha=0.55)
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0, fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=dpi)
    plt.close(fig)
    return output_path


def _draw_tracking_overlay(
    ax,
    path: WaypointPathRecord,
    *,
    sample_count: int,
    sample_spacing: float | None,
    lateral_offset: float,
    render_tracking_overlay: bool,
    render_command_vector_overlay: bool,
    velocity_solver_cfg,
    command_vector_scale: float,
) -> None:
    effective_spacing = _tracking_sample_spacing(path, sample_count=sample_count, sample_spacing=sample_spacing)
    tracking_cfg = PathTrackingCfg(sample_spacing=effective_spacing)
    cache = build_tracking_path_cache(path, tracking_cfg, dtype=torch.float32)
    robot_xy_path = _sample_robot_xy_for_tracking_overlay(
        cache,
        path,
        lateral_offset=lateral_offset,
    )
    targets = compute_stateful_path_tracking_targets(
        robot_xy_path,
        [cache] * robot_xy_path.shape[0],
        previous_progress_s=cache.sample_s,
        cfg=tracking_cfg,
    )

    robot_np = robot_xy_path.cpu().numpy()
    nearest_np = targets.nearest_xy_path.cpu().numpy()
    target_np = targets.target_xy_path.cpu().numpy()

    if render_tracking_overlay:
        ax.scatter(
            robot_np[:, 0],
            robot_np[:, 1],
            s=24,
            marker="o",
            color="#e11d48",
            edgecolors="white",
            linewidths=0.45,
            zorder=10,
            label="tracking robot sample",
        )
        ax.scatter(
            nearest_np[:, 0],
            nearest_np[:, 1],
            s=28,
            marker="x",
            color="#7c3aed",
            linewidths=1.3,
            zorder=11,
            label="tracking projection",
        )
        ax.scatter(
            target_np[:, 0],
            target_np[:, 1],
            s=44,
            marker="*",
            color="#facc15",
            edgecolors="#92400e",
            linewidths=0.45,
            zorder=12,
            label="tracking target",
        )

        label_stride = max(1, robot_xy_path.shape[0] // 6)
        for index in range(robot_np.shape[0]):
            ax.plot(
                [robot_np[index, 0], nearest_np[index, 0]],
                [robot_np[index, 1], nearest_np[index, 1]],
                color="#e11d48",
                linewidth=0.75,
                linestyle="--",
                alpha=0.72,
                zorder=9,
            )
            ax.annotate(
                "",
                xy=(float(target_np[index, 0]), float(target_np[index, 1])),
                xytext=(float(nearest_np[index, 0]), float(nearest_np[index, 1])),
                arrowprops={"arrowstyle": "->", "color": "#f59e0b", "lw": 0.8, "alpha": 0.78},
                zorder=10,
            )
            if index % label_stride == 0 or index == robot_np.shape[0] - 1:
                ax.text(
                    float(robot_np[index, 0]) + 0.04,
                    float(robot_np[index, 1]) + 0.04,
                    f"s={float(targets.progress_s[index]):.1f}\nt={float(targets.target_s[index]):.1f}",
                    fontsize=6,
                    color="#7f1d1d",
                    bbox={"facecolor": "white", "edgecolor": "#fecaca", "alpha": 0.82, "pad": 1.2},
                    zorder=13,
                )

    if render_command_vector_overlay:
        velocity_command = compute_desired_velocity_path_frame(
            robot_xy_path,
            targets,
            velocity_solver_cfg,
        )
        _draw_command_vector_overlay(
            ax,
            robot_xy_path,
            velocity_command,
            vector_scale=command_vector_scale,
        )


def _draw_command_vector_overlay(
    ax,
    robot_xy_path: torch.Tensor,
    velocity_command,
    *,
    vector_scale: float,
) -> None:
    valid_mask = velocity_command.valid_mask.cpu().numpy().astype(bool)
    if not np.any(valid_mask):
        return

    valid_indices = np.flatnonzero(valid_mask)
    stride = max(1, int(math.ceil(len(valid_indices) / 48.0)))
    plot_indices = valid_indices[::stride]
    robot_np = robot_xy_path.cpu().numpy()[plot_indices]

    target_vectors = velocity_command.target_direction_xy_path.cpu().numpy()[plot_indices] * vector_scale
    tangent_vectors = velocity_command.tangent_direction_xy_path.cpu().numpy()[plot_indices] * vector_scale
    lateral_vectors = (
        velocity_command.lateral_correction_direction_xy_path.cpu().numpy()[plot_indices]
        * velocity_command.lateral_correction_scale.cpu().numpy()[plot_indices, None]
        * vector_scale
    )
    desired_vectors = velocity_command.desired_vel_xy_path.cpu().numpy()[plot_indices] * vector_scale

    ax.scatter(
        robot_np[:, 0],
        robot_np[:, 1],
        s=18,
        marker="o",
        color="#111827",
        edgecolors="white",
        linewidths=0.35,
        zorder=14,
        label="command sample",
    )
    _quiver_xy(
        ax,
        robot_np,
        target_vectors,
        color="#0ea5e9",
        width=0.0025,
        alpha=0.72,
        zorder=15,
        label="target direction",
    )
    _quiver_xy(
        ax,
        robot_np,
        tangent_vectors,
        color="#16a34a",
        width=0.0025,
        alpha=0.72,
        zorder=16,
        label="path tangent",
    )
    _quiver_xy(
        ax,
        robot_np,
        lateral_vectors,
        color="#9333ea",
        width=0.0024,
        alpha=0.58,
        zorder=17,
        label="lateral correction",
    )
    _quiver_xy(
        ax,
        robot_np,
        desired_vectors,
        color="#ef4444",
        width=0.0042,
        alpha=0.88,
        zorder=18,
        label="desired velocity",
    )


def _quiver_xy(
    ax,
    origins: np.ndarray,
    vectors: np.ndarray,
    *,
    color: str,
    width: float,
    alpha: float,
    zorder: int,
    label: str,
) -> None:
    ax.quiver(
        origins[:, 0],
        origins[:, 1],
        vectors[:, 0],
        vectors[:, 1],
        angles="xy",
        scale_units="xy",
        scale=1.0,
        color=color,
        width=width,
        alpha=alpha,
        zorder=zorder,
        label=label,
    )


def _sample_robot_xy_for_tracking_overlay(
    cache: TrackingPathCache,
    path: WaypointPathRecord,
    *,
    lateral_offset: float,
) -> torch.Tensor:
    offset_limit = min(lateral_offset, path.corridor_half_width * 0.5)
    robot_points: list[tuple[float, float]] = []
    for index in range(cache.sample_xy_path.shape[0]):
        path_xy = (
            float(cache.sample_xy_path[index, 0].item()),
            float(cache.sample_xy_path[index, 1].item()),
        )
        tangent = (
            float(cache.tangent_xy_path[index, 0].item()),
            float(cache.tangent_xy_path[index, 1].item()),
        )
        normal = (-tangent[1], tangent[0])
        side = -1.0 if index % 2 == 0 else 1.0
        scale = 0.55 + 0.45 * ((index % 3) / 2.0)
        offset = side * offset_limit * scale
        robot_points.append((path_xy[0] + normal[0] * offset, path_xy[1] + normal[1] * offset))

    return torch.tensor(robot_points, dtype=torch.float32)


def _tracking_sample_spacing(
    path: WaypointPathRecord,
    *,
    sample_count: int,
    sample_spacing: float | None,
) -> float:
    if sample_spacing is not None:
        return sample_spacing
    if sample_count <= 1:
        return max(path.total_length_s, 1.0e-3)
    return max(path.total_length_s / float(sample_count - 1), 1.0e-3)


def main() -> None:
    args = parse_args()
    mode = ensure_valid_mode(args)

    if mode == "visualize-only":
        manifest, artifacts = load_artifacts_from_manifest(args.output_dir)
    else:
        _, _, exported_pool, manifest_path = build_and_export_templates(args)
        manifest, artifacts = load_artifacts_from_manifest(args.output_dir)
        print_export_summary(manifest_path, manifest)
        if mode == "export-only":
            print_pool_header(manifest, args.output_dir)
            for index, artifact in enumerate(filter_artifacts(artifacts, args.template_index)):
                actual_index = args.template_index if args.template_index is not None else index
                print_template_summary(actual_index, artifact)
            return

    selected_artifacts = filter_artifacts(artifacts, args.template_index)
    print_pool_header(manifest, args.output_dir)
    print("visualization_mode   : offline mesh inspection (trimesh-based, no Isaac Sim viewer)")
    print()
    for display_index, artifact in enumerate(selected_artifacts):
        actual_index = args.template_index if args.template_index is not None else display_index
        print_template_summary(actual_index, artifact)
        report = inspect_template_geometry(artifact)
        print_inspection_report(artifact, report, args)
        if args.render_path_overlays:
            overlay_dir = args.overlay_output_dir or (args.output_dir / "overlays")
            overlay_path = render_path_overlay_png(
                artifact,
                output_dir=overlay_dir,
                template_index=actual_index,
                dpi=args.overlay_dpi,
                render_tracking_overlay=args.render_tracking_overlay,
                tracking_sample_count=args.tracking_sample_count,
                tracking_sample_spacing=args.tracking_sample_spacing,
                tracking_lateral_offset=args.tracking_lateral_offset,
                render_command_vector_overlay=args.render_command_vector_overlay,
                target_direction_weight=args.target_direction_weight,
                tangent_direction_weight=args.tangent_direction_weight,
                lateral_correction_weight=args.lateral_correction_weight,
                command_vector_max_lin_speed=args.command_vector_max_lin_speed,
                command_vector_scale=args.command_vector_scale,
            )
            if overlay_path is not None:
                print(f"path_overlay_png     : {overlay_path}")
        print()


if __name__ == "__main__":
    main()
