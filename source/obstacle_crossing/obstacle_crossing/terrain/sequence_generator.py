from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

import numpy as np
import trimesh
import yaml

from .terrain_registry import ObstacleTerrainRegistry
from .terrain_specs import ContinuousSequenceSamplingCfg, ObstacleTerrainSpec, SequenceEvalCfg
from .terrain_waypoints import (
    SequenceWaypointPathRecord,
    WaypointPathRecord,
    build_single_terrain_waypoint_record,
    compose_sequence_waypoint_path,
    waypoint_path_to_payload,
)

_FORWARD_AXIS = "+Y"
_GEOMETRY_BACKENDS = ("stl", "usd")
_METADATA_BACKENDS = ("yaml",)
_ROTATION_RATIO_THRESHOLD = 1.25
_Z_MIN_TOLERANCE = 1.0e-3
_Z_CONNECTION_TOLERANCE = 5.0e-2
_MIN_EDGE_BAND_WIDTH = 5.0e-2
_MAX_EDGE_BAND_WIDTH = 2.5e-1
# The centered symmetrical ramp mesh is stored with its entry-exit axis along X.
# Sequence templates use +Y as the forward axis, so this segment needs an
# explicit quarter-turn instead of relying on extent-ratio inference.
_FORCE_ROTATE_TO_POSITIVE_Y_TERRAIN_KEYS = frozenset({"symmetrical_ramp"})
_BASE_FLOOR_START_MARGIN_Y = 1.0
_BASE_FLOOR_END_MARGIN_Y = 1.0
_BASE_FLOOR_WIDTH_X = 3.0
_BASE_FLOOR_THICKNESS_Z = 0.20
_BASE_FLOOR_TOP_Z = 0.0


@dataclass(frozen=True)
class SequenceAlignmentReport:
    terrain_id: int
    terrain_key: str
    source_path: str
    forward_axis: str
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    extent_xyz: tuple[float, float, float]
    segment_length_y: float
    z_min: float
    z_max: float
    z_span: float
    z_start_edge_mean: float | None
    z_end_edge_mean: float | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedSegmentGeometry:
    spec: ObstacleTerrainSpec
    mesh: trimesh.Trimesh = field(repr=False, compare=False)
    source_path: str
    input_backend: str
    forward_axis: str
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    segment_length_y: float
    entry_y: float
    exit_y: float
    alignment_report: SequenceAlignmentReport


@dataclass(frozen=True)
class SequenceSegmentRecord:
    terrain_id: int
    terrain_key: str
    command_profile_key: str
    physics_profile_key: str
    collision_profile_key: str
    required_capabilities: tuple[str, ...]
    segment_length_y: float
    start_y: float
    end_y: float


@dataclass(frozen=True)
class SequenceTemplateRecord:
    sequence_id: str
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    sequence_length: int
    segment_offsets_y: tuple[float, ...]
    segment_lengths_y: tuple[float, ...]
    buffer_lengths_y: tuple[float, ...]
    segment_ranges_y: tuple[tuple[float, float], ...]
    buffer_ranges_y: tuple[tuple[float, float], ...]
    sequence_total_length_y: float
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    segment_records: tuple[SequenceSegmentRecord, ...]
    alignment_reports: tuple[SequenceAlignmentReport, ...]
    input_format: str
    output_format: str
    forward_axis: str
    base_floor_width_x: float = _BASE_FLOOR_WIDTH_X
    base_floor_thickness_z: float = _BASE_FLOOR_THICKNESS_Z
    base_floor_start_margin_y: float = _BASE_FLOOR_START_MARGIN_Y
    base_floor_end_margin_y: float = _BASE_FLOOR_END_MARGIN_Y
    base_floor_top_z: float = _BASE_FLOOR_TOP_Z
    sequence_path: WaypointPathRecord | None = None
    segment_waypoint_ranges: tuple[tuple[int, int], ...] = ()
    segment_arc_ranges: tuple[tuple[float, float], ...] = ()
    buffer_arc_ranges: tuple[tuple[float, float], ...] = ()
    exit_arc_range: tuple[float, float] | None = None
    geometry_output_path: str | None = None
    metadata_output_path: str | None = None
    geometry_output_path_rel: str | None = None
    metadata_output_path_rel: str | None = None
    warnings: tuple[str, ...] = ()
    sequence_mesh: trimesh.Trimesh | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class SequenceTemplatePool:
    iteration: int
    seed: int
    template_records: tuple[SequenceTemplateRecord, ...]
    active_sequence_length_range: tuple[int, int]
    refresh_reason: str
    input_backend: str
    output_backend: str


class SequenceGeometryIOBackend(Protocol):
    name: str

    def load_segment_geometry(self, path: Path) -> trimesh.Trimesh:
        ...

    def export_sequence_geometry(self, mesh: trimesh.Trimesh, path: Path) -> None:
        ...


class StlSequenceGeometryBackend:
    name = "stl"

    def load_segment_geometry(self, path: Path) -> trimesh.Trimesh:
        mesh = trimesh.load(path, force="mesh")
        if not isinstance(mesh, trimesh.Trimesh):
            raise TypeError(f"Expected Trimesh when loading '{path}', got {type(mesh)!r}.")
        return mesh

    def export_sequence_geometry(self, mesh: trimesh.Trimesh, path: Path) -> None:
        mesh.export(path)


class UsdSequenceGeometryBackend:
    name = "usd"

    def load_segment_geometry(self, path: Path) -> trimesh.Trimesh:
        raise NotImplementedError("USD segment loading is reserved for a future version.")

    def export_sequence_geometry(self, mesh: trimesh.Trimesh, path: Path) -> None:
        raise NotImplementedError("USD sequence export is reserved for a future version.")


def should_enable_sequence_train(
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> bool:
    return iteration >= sampling_cfg.sequence_train_start_iteration


def get_active_sequence_length_range(
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> tuple[int, int]:
    stage_index = _stage_index_for_iteration(iteration, sampling_cfg)
    stage_max_length = sampling_cfg.sequence_length_stage_targets[stage_index]
    return (sampling_cfg.min_sequence_length, min(stage_max_length, sampling_cfg.max_sequence_length))


def should_refresh_training_templates(
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> bool:
    if not should_enable_sequence_train(iteration, sampling_cfg):
        return False
    if iteration == sampling_cfg.sequence_train_start_iteration:
        return True
    progress_iteration = iteration - sampling_cfg.sequence_train_start_iteration
    return progress_iteration % sampling_cfg.template_refresh_interval_iterations == 0


def sample_sequence_specs(
    registry: ObstacleTerrainRegistry,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
    rng: random.Random,
    *,
    allow_duplicate_terrains: bool = False,
) -> tuple[ObstacleTerrainSpec, ...]:
    candidate_specs = registry.single_train_specs()
    min_length, max_length = get_active_sequence_length_range(iteration, sampling_cfg)
    return _sample_specs_from_pool(
        candidate_specs,
        min_length=min_length,
        max_length=max_length,
        rng=rng,
        allow_duplicate_terrains=allow_duplicate_terrains,
        pool_name="sequence_train",
    )


def sample_buffer_lengths(
    sequence_length: int,
    rng: random.Random,
    *,
    min_buffer_length: float = 1.0,
    max_buffer_length: float = 3.0,
) -> tuple[float, ...]:
    if sequence_length < 1:
        raise ValueError(f"sequence_length must be >= 1, got {sequence_length}.")
    if min_buffer_length <= 0.0:
        raise ValueError(f"min_buffer_length must be > 0, got {min_buffer_length}.")
    if max_buffer_length < min_buffer_length:
        raise ValueError(
            f"max_buffer_length must be >= min_buffer_length, got {max_buffer_length} < {min_buffer_length}."
        )
    return tuple(rng.uniform(min_buffer_length, max_buffer_length) for _ in range(max(sequence_length - 1, 0)))


def load_segment_geometry(
    spec: ObstacleTerrainSpec,
    terrain_root: Path | str | None = None,
    *,
    backend: str = "stl",
) -> trimesh.Trimesh:
    terrain_root_path = Path(terrain_root) if terrain_root is not None else _default_terrain_root()
    terrain_path = _resolve_terrain_path(spec, terrain_root_path)
    return _get_geometry_backend(backend).load_segment_geometry(terrain_path)


def inspect_segment_alignment(
    geometry: trimesh.Trimesh,
    spec: ObstacleTerrainSpec,
    *,
    source_path: str | None = None,
    forward_axis: str = _FORWARD_AXIS,
) -> SequenceAlignmentReport:
    if forward_axis != _FORWARD_AXIS:
        raise NotImplementedError(f"Only forward_axis='{_FORWARD_AXIS}' is supported in V1.")
    bounds_min, bounds_max = _bounds_as_tuples(geometry)
    extent_xyz = _extent_from_bounds(bounds_min, bounds_max)
    segment_length_y = extent_xyz[1]
    z_start_edge_mean = _edge_height_mean(geometry, bounds_min[1], bounds_max[1], side="start")
    z_end_edge_mean = _edge_height_mean(geometry, bounds_min[1], bounds_max[1], side="end")
    warnings: list[str] = []
    if abs(bounds_min[2]) > _Z_MIN_TOLERANCE:
        warnings.append(
            f"Segment '{spec.key}' has z_min={bounds_min[2]:.4f}, which exceeds tolerance {_Z_MIN_TOLERANCE:.4f}."
        )
    if _should_warn_not_aligned_to_positive_y(spec, extent_xyz):
        warnings.append(f"Segment '{spec.key}' is not aligned to +Y after normalization.")
    if z_start_edge_mean is None:
        warnings.append(f"Segment '{spec.key}' has no detectable start-edge height sample.")
    if z_end_edge_mean is None:
        warnings.append(f"Segment '{spec.key}' has no detectable end-edge height sample.")
    return SequenceAlignmentReport(
        terrain_id=spec.terrain_id,
        terrain_key=spec.key,
        source_path=source_path or spec.terrain_file,
        forward_axis=forward_axis,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        extent_xyz=extent_xyz,
        segment_length_y=segment_length_y,
        z_min=bounds_min[2],
        z_max=bounds_max[2],
        z_span=bounds_max[2] - bounds_min[2],
        z_start_edge_mean=z_start_edge_mean,
        z_end_edge_mean=z_end_edge_mean,
        warnings=tuple(warnings),
    )


def normalize_segment_geometry(
    geometry: trimesh.Trimesh,
    spec: ObstacleTerrainSpec,
    *,
    source_path: str | None = None,
    input_backend: str = "stl",
    forward_axis: str = _FORWARD_AXIS,
) -> NormalizedSegmentGeometry:
    if forward_axis != _FORWARD_AXIS:
        raise NotImplementedError(f"Only forward_axis='{_FORWARD_AXIS}' is supported in V1.")
    normalized_mesh = geometry.copy()
    bounds_min, bounds_max = _bounds_as_tuples(normalized_mesh)
    extent_xyz = _extent_from_bounds(bounds_min, bounds_max)
    if _should_rotate_segment_to_positive_y(spec, extent_xyz):
        rotation = trimesh.transformations.rotation_matrix(math.pi / 2.0, (0.0, 0.0, 1.0))
        normalized_mesh.apply_transform(rotation)
    alignment_report = inspect_segment_alignment(
        normalized_mesh,
        spec,
        source_path=source_path or spec.terrain_file,
        forward_axis=forward_axis,
    )
    return NormalizedSegmentGeometry(
        spec=spec,
        mesh=normalized_mesh,
        source_path=source_path or spec.terrain_file,
        input_backend=input_backend,
        forward_axis=forward_axis,
        bounds_min=alignment_report.bounds_min,
        bounds_max=alignment_report.bounds_max,
        segment_length_y=alignment_report.segment_length_y,
        entry_y=alignment_report.bounds_min[1],
        exit_y=alignment_report.bounds_max[1],
        alignment_report=alignment_report,
    )


def compose_sequence_geometry(
    specs: tuple[ObstacleTerrainSpec, ...],
    segment_geometries: tuple[NormalizedSegmentGeometry, ...],
    buffer_lengths: tuple[float, ...],
    *,
    registry: ObstacleTerrainRegistry | None = None,
    output_backend: str = "stl",
    sequence_id: str | None = None,
) -> SequenceTemplateRecord:
    if not specs:
        raise ValueError("Cannot compose a sequence without any segment specs.")
    if len(specs) != len(segment_geometries):
        raise ValueError(
            f"spec count and segment geometry count must match, got {len(specs)} vs {len(segment_geometries)}."
        )
    if len(buffer_lengths) != max(len(specs) - 1, 0):
        raise ValueError(
            f"Expected {max(len(specs) - 1, 0)} buffer lengths, got {len(buffer_lengths)}."
        )
    _get_geometry_backend(output_backend)

    canonical_specs = _canonical_specs(specs, registry)
    terrain_ids = tuple(spec.terrain_id for spec in canonical_specs)
    terrain_keys = tuple(spec.key for spec in canonical_specs)
    command_profile_keys = tuple(spec.command_profile_key for spec in canonical_specs)
    physics_profile_keys = tuple(spec.physics_profile_key for spec in canonical_specs)
    collision_profile_keys = tuple(spec.collision_profile_key for spec in canonical_specs)
    required_capabilities = _merge_capabilities(canonical_specs)

    translated_meshes: list[trimesh.Trimesh] = []
    segment_offsets_y: list[float] = []
    segment_lengths_y: list[float] = []
    segment_ranges_y: list[tuple[float, float]] = []
    buffer_ranges_y: list[tuple[float, float]] = []
    segment_records: list[SequenceSegmentRecord] = []
    alignment_reports: list[SequenceAlignmentReport] = []
    warnings: list[str] = []

    current_y = _BASE_FLOOR_START_MARGIN_Y
    for index, (canonical_spec, normalized_segment) in enumerate(zip(canonical_specs, segment_geometries, strict=True)):
        if canonical_spec.terrain_id != normalized_segment.spec.terrain_id:
            raise ValueError(
                f"Spec terrain_id {canonical_spec.terrain_id} does not match segment terrain_id "
                f"{normalized_segment.spec.terrain_id}."
            )
        segment_mesh = normalized_segment.mesh.copy()
        translation_y = current_y - normalized_segment.entry_y
        translation_z = _BASE_FLOOR_TOP_Z - normalized_segment.alignment_report.z_min
        segment_mesh.apply_translation(np.array([0.0, translation_y, translation_z]))
        translated_meshes.append(segment_mesh)

        start_y = current_y
        end_y = current_y + normalized_segment.segment_length_y
        segment_offsets_y.append(start_y)
        segment_lengths_y.append(normalized_segment.segment_length_y)
        segment_ranges_y.append((start_y, end_y))
        alignment_reports.append(normalized_segment.alignment_report)
        warnings.extend(normalized_segment.alignment_report.warnings)
        segment_records.append(
            SequenceSegmentRecord(
                terrain_id=canonical_spec.terrain_id,
                terrain_key=canonical_spec.key,
                command_profile_key=canonical_spec.command_profile_key,
                physics_profile_key=canonical_spec.physics_profile_key,
                collision_profile_key=canonical_spec.collision_profile_key,
                required_capabilities=tuple(canonical_spec.required_capabilities),
                segment_length_y=normalized_segment.segment_length_y,
                start_y=start_y,
                end_y=end_y,
            )
        )

        if index > 0:
            previous_report = alignment_reports[index - 1]
            current_report = normalized_segment.alignment_report
            if previous_report.z_end_edge_mean is not None and current_report.z_start_edge_mean is not None:
                z_delta = abs(previous_report.z_end_edge_mean - current_report.z_start_edge_mean)
                if z_delta > _Z_CONNECTION_TOLERANCE:
                    warnings.append(
                        "Z boundary mismatch between "
                        f"'{canonical_specs[index - 1].key}' and '{canonical_spec.key}': {z_delta:.4f} m."
                    )

        if index < len(buffer_lengths):
            buffer_start = end_y
            buffer_end = end_y + buffer_lengths[index]
            buffer_ranges_y.append((buffer_start, buffer_end))
            current_y = buffer_end
        else:
            current_y = end_y

    base_floor_width_x = max(_BASE_FLOOR_WIDTH_X, *(report.extent_xyz[0] for report in alignment_reports))
    obstacle_span_end_y = segment_ranges_y[-1][1]
    sequence_total_length_y = obstacle_span_end_y + _BASE_FLOOR_END_MARGIN_Y
    base_floor_mesh = _build_sequence_base_floor(
        total_length_y=sequence_total_length_y,
        width_x=base_floor_width_x,
        thickness_z=_BASE_FLOOR_THICKNESS_Z,
        top_z=_BASE_FLOOR_TOP_Z,
    )
    combined_mesh = trimesh.util.concatenate([base_floor_mesh, *translated_meshes])
    sequence_id_value = sequence_id or _build_sequence_id(terrain_ids, buffer_lengths)
    sequence_waypoint_record = _compose_sequence_waypoint_record(
        sequence_id=sequence_id_value,
        canonical_specs=canonical_specs,
        segment_ranges_y=tuple(segment_ranges_y),
        buffer_ranges_y=tuple(buffer_ranges_y),
        command_profile_keys=command_profile_keys,
        sequence_total_length_y=sequence_total_length_y,
    )

    return SequenceTemplateRecord(
        sequence_id=sequence_id_value,
        terrain_ids=terrain_ids,
        terrain_keys=terrain_keys,
        sequence_length=len(canonical_specs),
        segment_offsets_y=tuple(segment_offsets_y),
        segment_lengths_y=tuple(segment_lengths_y),
        buffer_lengths_y=tuple(buffer_lengths),
        segment_ranges_y=tuple(segment_ranges_y),
        buffer_ranges_y=tuple(buffer_ranges_y),
        sequence_total_length_y=sequence_total_length_y,
        command_profile_keys=command_profile_keys,
        required_capabilities=required_capabilities,
        physics_profile_keys=physics_profile_keys,
        collision_profile_keys=collision_profile_keys,
        segment_records=tuple(segment_records),
        alignment_reports=tuple(alignment_reports),
        input_format=segment_geometries[0].input_backend,
        output_format=output_backend,
        forward_axis=_FORWARD_AXIS,
        base_floor_width_x=base_floor_width_x,
        sequence_path=sequence_waypoint_record.path,
        segment_waypoint_ranges=sequence_waypoint_record.segment_waypoint_ranges,
        segment_arc_ranges=sequence_waypoint_record.segment_arc_ranges,
        buffer_arc_ranges=sequence_waypoint_record.buffer_arc_ranges,
        exit_arc_range=sequence_waypoint_record.exit_arc_range,
        warnings=tuple(warnings),
        sequence_mesh=combined_mesh,
    )


def build_training_template_pool(
    registry: ObstacleTerrainRegistry,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
    *,
    template_count: int = 16,
    seed: int = 0,
    terrain_root: Path | str | None = None,
    input_backend: str = "stl",
    output_backend: str = "stl",
    allow_duplicate_terrains: bool = False,
) -> SequenceTemplatePool:
    active_length_range = get_active_sequence_length_range(iteration, sampling_cfg)
    if template_count < 0:
        raise ValueError(f"template_count must be >= 0, got {template_count}.")
    if not should_enable_sequence_train(iteration, sampling_cfg):
        return SequenceTemplatePool(
            iteration=iteration,
            seed=seed,
            template_records=(),
            active_sequence_length_range=active_length_range,
            refresh_reason="sequence_train_disabled",
            input_backend=input_backend,
            output_backend=output_backend,
        )

    rng = random.Random(seed)
    terrain_root_path = Path(terrain_root) if terrain_root is not None else _default_terrain_root()
    segment_cache: dict[tuple[str, str], NormalizedSegmentGeometry] = {}
    template_records: list[SequenceTemplateRecord] = []
    refresh_reason = "scheduled_refresh" if should_refresh_training_templates(iteration, sampling_cfg) else "manual_build"

    for template_index in range(template_count):
        specs = sample_sequence_specs(
            registry,
            iteration,
            sampling_cfg,
            rng,
            allow_duplicate_terrains=allow_duplicate_terrains,
        )
        normalized_segments = tuple(
            _load_normalized_segment(
                spec,
                terrain_root_path,
                input_backend=input_backend,
                segment_cache=segment_cache,
            )
            for spec in specs
        )
        buffer_lengths = sample_buffer_lengths(len(specs), rng)
        sequence_id = _build_sequence_id(
            tuple(spec.terrain_id for spec in specs),
            buffer_lengths,
            sequence_index=template_index,
        )
        template_records.append(
            compose_sequence_geometry(
                specs,
                normalized_segments,
                buffer_lengths,
                registry=registry,
                output_backend=output_backend,
                sequence_id=sequence_id,
            )
        )

    return SequenceTemplatePool(
        iteration=iteration,
        seed=seed,
        template_records=tuple(template_records),
        active_sequence_length_range=active_length_range,
        refresh_reason=refresh_reason,
        input_backend=input_backend,
        output_backend=output_backend,
    )


def build_fixed_eval_template_pool(
    registry: ObstacleTerrainRegistry,
    sequences: list[tuple[str | int | ObstacleTerrainSpec, ...]] | tuple[tuple[str | int | ObstacleTerrainSpec, ...], ...],
    *,
    seed: int = 0,
    terrain_root: Path | str | None = None,
    input_backend: str = "stl",
    output_backend: str = "stl",
    allow_duplicate_terrains: bool = False,
) -> SequenceTemplatePool:
    rng = random.Random(seed)
    terrain_root_path = Path(terrain_root) if terrain_root is not None else _default_terrain_root()
    segment_cache: dict[tuple[str, str], NormalizedSegmentGeometry] = {}
    template_records: list[SequenceTemplateRecord] = []

    for template_index, sequence_items in enumerate(sequences):
        resolved_specs = tuple(_resolve_spec_item(registry, item) for item in sequence_items)
        resolved_specs = _sorted_specs(resolved_specs)
        _validate_candidate_pool(
            list(resolved_specs),
            min_length=1,
            max_length=len(resolved_specs),
            allow_duplicate_terrains=allow_duplicate_terrains,
            pool_name="fixed_eval",
        )
        if not allow_duplicate_terrains and len({spec.terrain_id for spec in resolved_specs}) != len(resolved_specs):
            raise ValueError("Fixed eval sequences must not contain duplicate terrains unless allow_duplicate_terrains=True.")
        normalized_segments = tuple(
            _load_normalized_segment(
                spec,
                terrain_root_path,
                input_backend=input_backend,
                segment_cache=segment_cache,
            )
            for spec in resolved_specs
        )
        buffer_lengths = sample_buffer_lengths(len(resolved_specs), rng)
        sequence_id = _build_sequence_id(
            tuple(spec.terrain_id for spec in resolved_specs),
            buffer_lengths,
            sequence_index=template_index,
        )
        template_records.append(
            compose_sequence_geometry(
                resolved_specs,
                normalized_segments,
                buffer_lengths,
                registry=registry,
                output_backend=output_backend,
                sequence_id=sequence_id,
            )
        )

    active_length_range = _pool_length_range(template_records)
    return SequenceTemplatePool(
        iteration=0,
        seed=seed,
        template_records=tuple(template_records),
        active_sequence_length_range=active_length_range,
        refresh_reason="fixed_eval_templates",
        input_backend=input_backend,
        output_backend=output_backend,
    )


def build_random_eval_template_pool(
    registry: ObstacleTerrainRegistry,
    eval_cfg: SequenceEvalCfg,
    *,
    template_count: int | None = None,
    seed: int = 0,
    terrain_root: Path | str | None = None,
    input_backend: str = "stl",
    output_backend: str = "stl",
    allow_duplicate_terrains: bool = False,
    use_future_benchmark_specs: bool = True,
) -> SequenceTemplatePool:
    candidate_specs = registry.future_benchmark_specs() if use_future_benchmark_specs else registry.single_train_specs()
    effective_max_length = _validate_candidate_pool(
        candidate_specs,
        min_length=eval_cfg.min_sequence_length,
        max_length=eval_cfg.max_sequence_length,
        allow_duplicate_terrains=allow_duplicate_terrains,
        pool_name="random_eval",
    )
    rng = random.Random(seed)
    terrain_root_path = Path(terrain_root) if terrain_root is not None else _default_terrain_root()
    segment_cache: dict[tuple[str, str], NormalizedSegmentGeometry] = {}
    actual_template_count = eval_cfg.random_benchmark_count if template_count is None else template_count
    template_records: list[SequenceTemplateRecord] = []

    for template_index in range(actual_template_count):
        specs = _sample_specs_from_pool(
            candidate_specs,
            min_length=eval_cfg.min_sequence_length,
            max_length=effective_max_length,
            rng=rng,
            allow_duplicate_terrains=allow_duplicate_terrains,
            pool_name="random_eval",
        )
        normalized_segments = tuple(
            _load_normalized_segment(
                spec,
                terrain_root_path,
                input_backend=input_backend,
                segment_cache=segment_cache,
            )
            for spec in specs
        )
        buffer_lengths = sample_buffer_lengths(len(specs), rng)
        sequence_id = _build_sequence_id(
            tuple(spec.terrain_id for spec in specs),
            buffer_lengths,
            sequence_index=template_index,
        )
        template_records.append(
            compose_sequence_geometry(
                specs,
                normalized_segments,
                buffer_lengths,
                registry=registry,
                output_backend=output_backend,
                sequence_id=sequence_id,
            )
        )

    return SequenceTemplatePool(
        iteration=0,
        seed=seed,
        template_records=tuple(template_records),
        active_sequence_length_range=(eval_cfg.min_sequence_length, effective_max_length),
        refresh_reason="random_eval_templates",
        input_backend=input_backend,
        output_backend=output_backend,
    )


def export_sequence_template(
    template: SequenceTemplateRecord,
    output_dir: Path | str,
    *,
    geometry_backend: str = "stl",
    metadata_backend: str = "yaml",
) -> SequenceTemplateRecord:
    if template.sequence_mesh is None:
        raise ValueError(f"Template '{template.sequence_id}' does not carry a composed mesh to export.")
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    geometry_path = output_dir_path / f"sequence_{template.sequence_id}.{geometry_backend}"
    metadata_path = output_dir_path / f"sequence_{template.sequence_id}.{metadata_backend}"
    geometry_path_rel = geometry_path.name
    metadata_path_rel = metadata_path.name
    _get_geometry_backend(geometry_backend).export_sequence_geometry(template.sequence_mesh, geometry_path)
    exported_template = replace(
        template,
        geometry_output_path=str(geometry_path),
        metadata_output_path=str(metadata_path),
        geometry_output_path_rel=geometry_path_rel,
        metadata_output_path_rel=metadata_path_rel,
        output_format=geometry_backend,
    )
    with metadata_path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            _template_to_yaml_payload(exported_template),
            stream,
            sort_keys=False,
            allow_unicode=True,
        )
    return exported_template


def export_template_pool_manifest(
    pool: SequenceTemplatePool,
    output_dir: Path | str,
    *,
    metadata_backend: str = "yaml",
) -> Path:
    _validate_metadata_backend(metadata_backend)
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir_path / f"sequence_pool_manifest.{metadata_backend}"
    with manifest_path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            _pool_manifest_payload(pool),
            stream,
            sort_keys=False,
            allow_unicode=True,
        )
    return manifest_path


def _stage_index_for_iteration(iteration: int, sampling_cfg: ContinuousSequenceSamplingCfg) -> int:
    if iteration < sampling_cfg.sequence_train_start_iteration:
        return 0
    progress_iteration = iteration - sampling_cfg.sequence_train_start_iteration
    return min(
        progress_iteration // sampling_cfg.sequence_length_stage_iterations,
        len(sampling_cfg.sequence_length_stage_targets) - 1,
    )


def _validate_candidate_pool(
    specs: list[ObstacleTerrainSpec],
    *,
    min_length: int,
    max_length: int,
    allow_duplicate_terrains: bool,
    pool_name: str,
) -> int:
    if not specs:
        raise ValueError(f"No terrain specs are available for pool '{pool_name}'.")
    if min_length < 1:
        raise ValueError(f"min_length must be >= 1, got {min_length}.")
    if max_length < min_length:
        raise ValueError(f"max_length must be >= min_length, got {max_length} < {min_length}.")
    effective_max_length = max_length if allow_duplicate_terrains else min(max_length, len(specs))
    if effective_max_length < min_length:
        raise ValueError(
            f"Pool '{pool_name}' has only {len(specs)} candidate terrains, which cannot satisfy "
            f"the requested range [{min_length}, {max_length}] with allow_duplicate_terrains={allow_duplicate_terrains}."
        )
    return effective_max_length


def _sample_specs_from_pool(
    specs: list[ObstacleTerrainSpec],
    *,
    min_length: int,
    max_length: int,
    rng: random.Random,
    allow_duplicate_terrains: bool,
    pool_name: str,
) -> tuple[ObstacleTerrainSpec, ...]:
    effective_max_length = _validate_candidate_pool(
        specs,
        min_length=min_length,
        max_length=max_length,
        allow_duplicate_terrains=allow_duplicate_terrains,
        pool_name=pool_name,
    )
    sequence_length = rng.randint(min_length, effective_max_length)
    if allow_duplicate_terrains:
        sampled_specs = rng.choices(specs, k=sequence_length)
    else:
        sampled_specs = rng.sample(specs, k=sequence_length)
    return _sorted_specs(sampled_specs)


def _sorted_specs(specs: list[ObstacleTerrainSpec] | tuple[ObstacleTerrainSpec, ...]) -> tuple[ObstacleTerrainSpec, ...]:
    return tuple(sorted(specs, key=lambda spec: spec.terrain_id))


def _load_normalized_segment(
    spec: ObstacleTerrainSpec,
    terrain_root: Path,
    *,
    input_backend: str,
    segment_cache: dict[tuple[str, str], NormalizedSegmentGeometry],
) -> NormalizedSegmentGeometry:
    cache_key = (spec.key, input_backend)
    cached_segment = segment_cache.get(cache_key)
    if cached_segment is not None:
        return cached_segment
    terrain_path = _resolve_terrain_path(spec, terrain_root)
    raw_mesh = _get_geometry_backend(input_backend).load_segment_geometry(terrain_path)
    normalized_segment = normalize_segment_geometry(
        raw_mesh,
        spec,
        source_path=str(terrain_path),
        input_backend=input_backend,
    )
    segment_cache[cache_key] = normalized_segment
    return normalized_segment


def _get_geometry_backend(name: str) -> SequenceGeometryIOBackend:
    if name == "stl":
        return StlSequenceGeometryBackend()
    if name == "usd":
        return UsdSequenceGeometryBackend()
    raise ValueError(f"Unsupported geometry backend '{name}'. Expected one of {_GEOMETRY_BACKENDS}.")


def _validate_metadata_backend(name: str) -> None:
    if name not in _METADATA_BACKENDS:
        raise ValueError(f"Unsupported metadata backend '{name}'. Expected one of {_METADATA_BACKENDS}.")


def _default_terrain_root() -> Path:
    return _repository_root() / "terrains" / "combined"


def _default_output_dir(split: str) -> Path:
    return _repository_root() / "terrains" / "generated_sequences" / split


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_terrain_path(spec: ObstacleTerrainSpec, terrain_root: Path) -> Path:
    terrain_path = (terrain_root / spec.terrain_file).resolve()
    if not terrain_path.exists():
        raise FileNotFoundError(
            f"Terrain file for '{spec.key}' was not found: '{terrain_path}'."
        )
    return terrain_path


def _should_rotate_to_positive_y(extent_xyz: tuple[float, float, float]) -> bool:
    x_extent, y_extent, _ = extent_xyz
    return x_extent >= y_extent * _ROTATION_RATIO_THRESHOLD


def _should_rotate_segment_to_positive_y(
    spec: ObstacleTerrainSpec,
    extent_xyz: tuple[float, float, float],
) -> bool:
    return spec.key in _FORCE_ROTATE_TO_POSITIVE_Y_TERRAIN_KEYS or _should_rotate_to_positive_y(extent_xyz)


def _should_warn_not_aligned_to_positive_y(
    spec: ObstacleTerrainSpec,
    extent_xyz: tuple[float, float, float],
) -> bool:
    if spec.key in _FORCE_ROTATE_TO_POSITIVE_Y_TERRAIN_KEYS:
        return False
    return extent_xyz[1] + 1.0e-6 < extent_xyz[0]


def _bounds_as_tuples(mesh: trimesh.Trimesh) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    return tuple(float(v) for v in bounds[0]), tuple(float(v) for v in bounds[1])


def _extent_from_bounds(
    bounds_min: tuple[float, float, float],
    bounds_max: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(float(max_v - min_v) for min_v, max_v in zip(bounds_min, bounds_max, strict=True))


def _build_sequence_base_floor(
    total_length_y: float,
    *,
    width_x: float,
    thickness_z: float,
    top_z: float,
) -> trimesh.Trimesh:
    if total_length_y <= 0.0:
        raise ValueError(f"total_length_y must be > 0, got {total_length_y}.")
    if width_x <= 0.0:
        raise ValueError(f"width_x must be > 0, got {width_x}.")
    if thickness_z <= 0.0:
        raise ValueError(f"thickness_z must be > 0, got {thickness_z}.")
    floor_center = np.array([0.0, total_length_y / 2.0, top_z - thickness_z / 2.0], dtype=float)
    floor_extents = np.array([width_x, total_length_y, thickness_z], dtype=float)
    return trimesh.creation.box(extents=floor_extents, transform=trimesh.transformations.translation_matrix(floor_center))


def _compose_sequence_waypoint_record(
    *,
    sequence_id: str,
    canonical_specs: tuple[ObstacleTerrainSpec, ...],
    segment_ranges_y: tuple[tuple[float, float], ...],
    buffer_ranges_y: tuple[tuple[float, float], ...],
    command_profile_keys: tuple[str, ...],
    sequence_total_length_y: float,
) -> SequenceWaypointPathRecord:
    segment_paths = tuple(
        build_single_terrain_waypoint_record(spec).path
        for spec in canonical_specs
    )
    return compose_sequence_waypoint_path(
        sequence_id=sequence_id,
        segment_paths=segment_paths,
        segment_ranges_y=segment_ranges_y,
        buffer_ranges_y=buffer_ranges_y,
        command_profile_keys=command_profile_keys,
        sequence_total_length_y=sequence_total_length_y,
    )


def _edge_height_mean(
    mesh: trimesh.Trimesh,
    min_y: float,
    max_y: float,
    *,
    side: str,
) -> float | None:
    vertices = np.asarray(mesh.vertices, dtype=float)
    if vertices.size == 0:
        return None
    segment_length_y = max_y - min_y
    band_width = min(_MAX_EDGE_BAND_WIDTH, max(_MIN_EDGE_BAND_WIDTH, segment_length_y * 0.05))
    if side == "start":
        mask = vertices[:, 1] <= min_y + band_width
    elif side == "end":
        mask = vertices[:, 1] >= max_y - band_width
    else:
        raise ValueError(f"Unknown edge side '{side}'.")
    if not np.any(mask):
        return None
    return float(np.mean(vertices[mask, 2]))


def _merge_capabilities(specs: list[ObstacleTerrainSpec] | tuple[ObstacleTerrainSpec, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        for capability in spec.required_capabilities:
            if capability not in seen:
                seen.add(capability)
                merged.append(capability)
    return tuple(merged)


def _canonical_specs(
    specs: tuple[ObstacleTerrainSpec, ...],
    registry: ObstacleTerrainRegistry | None,
) -> tuple[ObstacleTerrainSpec, ...]:
    if registry is None:
        return specs
    canonical_specs: list[ObstacleTerrainSpec] = []
    for spec in specs:
        canonical_spec = registry.get(spec.terrain_id)
        registry.command_profile_for_terrain(spec.terrain_id)
        registry.physics_profile_for_terrain(spec.terrain_id)
        registry.collision_profile_for_terrain(spec.terrain_id)
        canonical_specs.append(canonical_spec)
    return tuple(canonical_specs)


def _resolve_spec_item(
    registry: ObstacleTerrainRegistry,
    item: str | int | ObstacleTerrainSpec,
) -> ObstacleTerrainSpec:
    if isinstance(item, ObstacleTerrainSpec):
        return registry.get(item.terrain_id)
    return registry.get(item)


def _build_sequence_id(
    terrain_ids: tuple[int, ...],
    buffer_lengths: tuple[float, ...],
    *,
    sequence_index: int | None = None,
) -> str:
    terrain_part = "-".join(f"{terrain_id:03d}" for terrain_id in terrain_ids)
    if sequence_index is not None:
        return f"{terrain_part}__{sequence_index:04d}"
    if not buffer_lengths:
        return terrain_part
    buffer_part = "-".join(f"{buffer_length:.2f}".replace(".", "p") for buffer_length in buffer_lengths)
    return f"{terrain_part}__{buffer_part}"


def _template_to_yaml_payload(template: SequenceTemplateRecord) -> dict:
    _validate_metadata_backend("yaml")
    return {
        "sequence_id": template.sequence_id,
        "terrain_ids": list(template.terrain_ids),
        "terrain_keys": list(template.terrain_keys),
        "sequence_length": template.sequence_length,
        "segment_offsets_y": [float(v) for v in template.segment_offsets_y],
        "segment_lengths_y": [float(v) for v in template.segment_lengths_y],
        "buffer_lengths_y": [float(v) for v in template.buffer_lengths_y],
        "segment_ranges_y": [[float(start), float(end)] for start, end in template.segment_ranges_y],
        "buffer_ranges_y": [[float(start), float(end)] for start, end in template.buffer_ranges_y],
        "sequence_total_length_y": float(template.sequence_total_length_y),
        "command_profile_keys": list(template.command_profile_keys),
        "required_capabilities": list(template.required_capabilities),
        "physics_profile_keys": list(template.physics_profile_keys),
        "collision_profile_keys": list(template.collision_profile_keys),
        "input_format": template.input_format,
        "output_format": template.output_format,
        "forward_axis": template.forward_axis,
        "base_floor_width_x": float(template.base_floor_width_x),
        "base_floor_thickness_z": float(template.base_floor_thickness_z),
        "base_floor_start_margin_y": float(template.base_floor_start_margin_y),
        "base_floor_end_margin_y": float(template.base_floor_end_margin_y),
        "base_floor_top_z": float(template.base_floor_top_z),
        "sequence_path": None if template.sequence_path is None else waypoint_path_to_payload(template.sequence_path),
        "segment_waypoint_ranges": [[int(start), int(end)] for start, end in template.segment_waypoint_ranges],
        "segment_arc_ranges": [[float(start), float(end)] for start, end in template.segment_arc_ranges],
        "buffer_arc_ranges": [[float(start), float(end)] for start, end in template.buffer_arc_ranges],
        "exit_arc_range": None if template.exit_arc_range is None else [
            float(template.exit_arc_range[0]),
            float(template.exit_arc_range[1]),
        ],
        "geometry_output_path": template.geometry_output_path,
        "metadata_output_path": template.metadata_output_path,
        "geometry_output_path_rel": template.geometry_output_path_rel,
        "metadata_output_path_rel": template.metadata_output_path_rel,
        "warnings": list(template.warnings),
        "segments": [
            {
                "terrain_id": record.terrain_id,
                "terrain_key": record.terrain_key,
                "command_profile_key": record.command_profile_key,
                "physics_profile_key": record.physics_profile_key,
                "collision_profile_key": record.collision_profile_key,
                "required_capabilities": list(record.required_capabilities),
                "segment_length_y": float(record.segment_length_y),
                "start_y": float(record.start_y),
                "end_y": float(record.end_y),
            }
            for record in template.segment_records
        ],
        "alignment_reports": [
            {
                "terrain_id": report.terrain_id,
                "terrain_key": report.terrain_key,
                "source_path": report.source_path,
                "forward_axis": report.forward_axis,
                "bounds_min": [float(v) for v in report.bounds_min],
                "bounds_max": [float(v) for v in report.bounds_max],
                "extent_xyz": [float(v) for v in report.extent_xyz],
                "segment_length_y": float(report.segment_length_y),
                "z_min": float(report.z_min),
                "z_max": float(report.z_max),
                "z_span": float(report.z_span),
                "z_start_edge_mean": None if report.z_start_edge_mean is None else float(report.z_start_edge_mean),
                "z_end_edge_mean": None if report.z_end_edge_mean is None else float(report.z_end_edge_mean),
                "warnings": list(report.warnings),
            }
            for report in template.alignment_reports
        ],
    }


def _pool_manifest_payload(pool: SequenceTemplatePool) -> dict:
    return {
        "iteration": pool.iteration,
        "seed": pool.seed,
        "template_count": len(pool.template_records),
        "active_sequence_length_range": list(pool.active_sequence_length_range),
        "refresh_reason": pool.refresh_reason,
        "input_backend": pool.input_backend,
        "output_backend": pool.output_backend,
        "templates": [
            {
                "sequence_id": template.sequence_id,
                "geometry_output_path": template.geometry_output_path,
                "metadata_output_path": template.metadata_output_path,
                "geometry_output_path_rel": template.geometry_output_path_rel,
                "metadata_output_path_rel": template.metadata_output_path_rel,
                "terrain_ids": list(template.terrain_ids),
                "terrain_keys": list(template.terrain_keys),
                "sequence_length": template.sequence_length,
                "sequence_total_length_y": float(template.sequence_total_length_y),
                "path_frame": None if template.sequence_path is None else template.sequence_path.frame,
                "path_total_length_s": None if template.sequence_path is None else float(template.sequence_path.total_length_s),
            }
            for template in pool.template_records
        ],
    }


def _pool_length_range(template_records: list[SequenceTemplateRecord]) -> tuple[int, int]:
    if not template_records:
        return (0, 0)
    lengths = [template.sequence_length for template in template_records]
    return (min(lengths), max(lengths))


__all__ = [
    "NormalizedSegmentGeometry",
    "SequenceAlignmentReport",
    "SequenceSegmentRecord",
    "SequenceTemplatePool",
    "SequenceTemplateRecord",
    "build_fixed_eval_template_pool",
    "build_random_eval_template_pool",
    "build_training_template_pool",
    "compose_sequence_geometry",
    "export_sequence_template",
    "export_template_pool_manifest",
    "get_active_sequence_length_range",
    "inspect_segment_alignment",
    "load_segment_geometry",
    "normalize_segment_geometry",
    "sample_buffer_lengths",
    "sample_sequence_specs",
    "should_enable_sequence_train",
    "should_refresh_training_templates",
]
