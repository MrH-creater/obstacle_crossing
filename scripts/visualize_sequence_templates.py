from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
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

GEOMETRY_BACKENDS = ("stl", "usd")
METADATA_BACKEND = "yaml"
BASE_FLOOR_WIDTH_X = 3.0
BASE_FLOOR_THICKNESS_Z = 0.20
BASE_FLOOR_TOP_Z = 0.0
DEFAULT_SEQUENCE_START_ITERATION = 10000
DEFAULT_OUTPUT_DIR = REPO_ROOT / "terrains" / "generated_sequences" / "visualization"
DEFAULT_TERRAIN_ROOT = REPO_ROOT / "terrains" / "combined"


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
    parser.add_argument("--terrain-root", type=Path, default=DEFAULT_TERRAIN_ROOT)
    parser.add_argument("--input-backend", choices=GEOMETRY_BACKENDS, default="stl")
    parser.add_argument("--output-backend", choices=GEOMETRY_BACKENDS, default="stl")
    parser.add_argument("--template-index", type=int)
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--visualize-only", action="store_true")
    parser.add_argument("--show-metadata", action="store_true")
    parser.add_argument("--show-segment-ranges", action="store_true")
    parser.add_argument("--show-buffer-ranges", action="store_true")
    return parser.parse_args()


def ensure_valid_mode(args: argparse.Namespace) -> str:
    if args.export_only and args.visualize_only:
        raise SystemExit("--export-only and --visualize-only cannot be used together.")
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


def inspect_template_geometry(artifact: LoadedTemplateArtifact) -> dict[str, Any]:
    metadata = artifact.metadata
    floor_component, obstacle_components, floor_info = identify_base_floor(artifact)
    range_info = inspect_segment_and_buffer_ranges(metadata)
    floor_top_z = float(metadata.get("base_floor_top_z", BASE_FLOOR_TOP_Z))
    obstacle_info = inspect_obstacle_placement(metadata, obstacle_components, floor_top_z)

    mesh_bounds, mesh_extents = _component_info(artifact.mesh)
    return {
        "mesh_bounds": mesh_bounds,
        "mesh_extents": mesh_extents,
        "floor_info": floor_info,
        "range_info": range_info,
        "obstacle_info": obstacle_info,
        "obstacle_component_count": len(obstacle_components),
        "floor_component_present": floor_component is not None,
    }


def print_inspection_report(artifact: LoadedTemplateArtifact, report: dict[str, Any], args: argparse.Namespace) -> None:
    floor_info = report["floor_info"]
    range_info = report["range_info"]
    obstacle_info = report["obstacle_info"]
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
        print()


if __name__ == "__main__":
    main()
