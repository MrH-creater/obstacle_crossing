from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from .sequence_generator import (
    SequenceAlignmentReport,
    SequenceSegmentRecord,
    SequenceTemplatePool,
    SequenceTemplateRecord,
    build_training_template_pool,
    export_sequence_template,
    export_template_pool_manifest,
    get_active_sequence_length_range,
    should_enable_sequence_train,
    should_refresh_training_templates,
)
from .terrain_registry import ObstacleTerrainRegistry
from .terrain_specs import ContinuousSequenceSamplingCfg
from .terrain_waypoints import waypoint_path_from_payload


@dataclass(frozen=True)
class SequencePoolDecision:
    iteration: int
    sequence_enabled: bool
    sequence_ratio: float
    active_length_range: tuple[int, int]
    template_count: int
    should_refresh: bool
    refresh_reason: str
    output_dir: str
    use_cached_pool: bool


class SequencePoolScheduler:
    def __init__(
        self,
        *,
        train_pool_root: Path | str | None = None,
        template_count: int = 16,
    ) -> None:
        if template_count < 0:
            raise ValueError(f"template_count must be >= 0, got {template_count}.")
        self.train_pool_root = Path(train_pool_root) if train_pool_root is not None else _default_train_pool_root()
        self.template_count = template_count

    def build_decision(
        self,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
        *,
        current_manifest_exists: bool = False,
    ) -> SequencePoolDecision:
        sequence_enabled = should_enable_sequence_train(iteration, sampling_cfg)
        scheduled_refresh = should_refresh_training_templates(iteration, sampling_cfg)
        active_length_range = get_active_sequence_length_range(iteration, sampling_cfg)
        sequence_ratio = self._sequence_ratio(iteration, sampling_cfg) if sequence_enabled else 0.0
        should_refresh = sequence_enabled and (scheduled_refresh or not current_manifest_exists)
        use_cached_pool = sequence_enabled and current_manifest_exists and not should_refresh

        if not sequence_enabled:
            refresh_reason = "sequence_train_disabled"
        elif not current_manifest_exists:
            if iteration == sampling_cfg.sequence_train_start_iteration:
                refresh_reason = "initial_activation"
            else:
                refresh_reason = "missing_current_pool"
        elif scheduled_refresh:
            refresh_reason = "scheduled_refresh"
        else:
            refresh_reason = "reuse_current_pool"

        return SequencePoolDecision(
            iteration=iteration,
            sequence_enabled=sequence_enabled,
            sequence_ratio=sequence_ratio,
            active_length_range=active_length_range,
            template_count=self.template_count,
            should_refresh=should_refresh,
            refresh_reason=refresh_reason,
            output_dir=str(self.current_output_dir()),
            use_cached_pool=use_cached_pool,
        )

    def current_output_dir(self) -> Path:
        return self.train_pool_root / "current"

    def current_manifest_path(self) -> Path:
        return self.current_output_dir() / "sequence_pool_manifest.yaml"

    def _sequence_ratio(self, iteration: int, sampling_cfg: ContinuousSequenceSamplingCfg) -> float:
        progress = _ramp_progress(
            iteration=iteration,
            start_iteration=sampling_cfg.sequence_train_start_iteration,
            ramp_iterations=sampling_cfg.sequence_train_ratio_ramp_iterations,
        )
        return _lerp(
            sampling_cfg.sequence_train_env_ratio_initial,
            sampling_cfg.sequence_train_env_ratio_final,
            progress,
        )


class SequencePoolOrchestrator:
    def __init__(
        self,
        *,
        train_pool_root: Path | str | None = None,
        template_count: int = 16,
        allow_duplicate_terrains: bool = False,
        terrain_root: Path | str | None = None,
        input_backend: str = "stl",
        output_backend: str = "stl",
    ) -> None:
        self.scheduler = SequencePoolScheduler(train_pool_root=train_pool_root, template_count=template_count)
        self.allow_duplicate_terrains = allow_duplicate_terrains
        self.terrain_root = Path(terrain_root) if terrain_root is not None else None
        self.input_backend = input_backend
        self.output_backend = output_backend

    def ensure_active_training_pool(
        self,
        registry: ObstacleTerrainRegistry,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
        *,
        seed: int,
    ) -> SequenceTemplatePool:
        decision = self.scheduler.build_decision(
            iteration,
            sampling_cfg,
            current_manifest_exists=self.current_pool_manifest_path().exists(),
        )
        if not decision.sequence_enabled:
            return SequenceTemplatePool(
                iteration=iteration,
                seed=seed,
                template_records=(),
                active_sequence_length_range=decision.active_length_range,
                refresh_reason=decision.refresh_reason,
                input_backend=self.input_backend,
                output_backend=self.output_backend,
            )

        if decision.use_cached_pool:
            current_pool = self.load_current_pool()
            if current_pool is None:
                raise FileNotFoundError(
                    f"Expected current pool manifest at '{self.current_pool_manifest_path()}', but it was not found."
                )
            return current_pool

        pool = build_training_template_pool(
            registry,
            iteration,
            sampling_cfg,
            template_count=decision.template_count,
            seed=seed,
            terrain_root=self.terrain_root,
            input_backend=self.input_backend,
            output_backend=self.output_backend,
            allow_duplicate_terrains=self.allow_duplicate_terrains,
        )
        pool = replace(pool, refresh_reason=decision.refresh_reason)
        staging_dir = self._staging_dir_for_iteration(iteration)
        self._export_pool_to_dir(pool, staging_dir)
        self.archive_current_pool()
        self.promote_new_pool_to_current(staging_dir)
        current_pool = self.load_current_pool()
        if current_pool is None:
            raise FileNotFoundError(
                f"Expected promoted current pool manifest at '{self.current_pool_manifest_path()}', but it was not found."
            )
        return current_pool

    def current_pool_manifest_path(self) -> Path:
        return self.scheduler.current_manifest_path()

    def current_template_records(self) -> tuple[SequenceTemplateRecord, ...]:
        current_pool = self.load_current_pool()
        return () if current_pool is None else current_pool.template_records

    def load_current_pool(self) -> SequenceTemplatePool | None:
        manifest_path = self.current_pool_manifest_path()
        if not manifest_path.exists():
            return None
        return _load_pool_manifest(manifest_path)

    def archive_current_pool(self) -> Path | None:
        current_dir = self.scheduler.current_output_dir()
        if not current_dir.exists():
            return None

        archive_root = self._archive_root()
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_iteration = "unknown"
        current_pool = self.load_current_pool()
        if current_pool is not None:
            archive_iteration = f"{current_pool.iteration:08d}"
        archive_dir = _unique_dir(archive_root / f"iter_{archive_iteration}")
        shutil.move(str(current_dir), str(archive_dir))
        return archive_dir

    def promote_new_pool_to_current(self, staging_dir: Path) -> Path:
        current_dir = self.scheduler.current_output_dir()
        current_dir.parent.mkdir(parents=True, exist_ok=True)
        if current_dir.exists():
            raise FileExistsError(f"Cannot promote staging pool because '{current_dir}' already exists.")
        shutil.move(str(staging_dir), str(current_dir))
        self._rewrite_current_pool_paths(current_dir)
        return current_dir

    def _archive_root(self) -> Path:
        return self.scheduler.train_pool_root / "archive"

    def _staging_root(self) -> Path:
        return self.scheduler.train_pool_root / "_staging"

    def _staging_dir_for_iteration(self, iteration: int) -> Path:
        staging_root = self._staging_root()
        staging_root.mkdir(parents=True, exist_ok=True)
        return _unique_dir(staging_root / f"iter_{iteration:08d}")

    def _export_pool_to_dir(self, pool: SequenceTemplatePool, output_dir: Path) -> SequenceTemplatePool:
        output_dir.mkdir(parents=True, exist_ok=True)
        exported_templates = tuple(
            export_sequence_template(
                template,
                output_dir,
                geometry_backend=self.output_backend,
                metadata_backend="yaml",
            )
            for template in pool.template_records
        )
        exported_pool = replace(pool, template_records=exported_templates)
        export_template_pool_manifest(exported_pool, output_dir, metadata_backend="yaml")
        return exported_pool

    def _rewrite_current_pool_paths(self, current_dir: Path) -> None:
        manifest_path = current_dir / "sequence_pool_manifest.yaml"
        with manifest_path.open("r", encoding="utf-8") as stream:
            manifest_payload = yaml.safe_load(stream) or {}

        for template_payload in manifest_payload.get("templates", []):
            sequence_id = str(template_payload["sequence_id"])
            geometry_path = str(current_dir / f"sequence_{sequence_id}.{self.output_backend}")
            metadata_path = str(current_dir / f"sequence_{sequence_id}.yaml")
            template_payload["geometry_output_path"] = geometry_path
            template_payload["metadata_output_path"] = metadata_path

            template_file = current_dir / f"sequence_{sequence_id}.yaml"
            with template_file.open("r", encoding="utf-8") as stream:
                template_record_payload = yaml.safe_load(stream) or {}
            template_record_payload["geometry_output_path"] = geometry_path
            template_record_payload["metadata_output_path"] = metadata_path
            with template_file.open("w", encoding="utf-8") as stream:
                yaml.safe_dump(template_record_payload, stream, sort_keys=False, allow_unicode=True)

        with manifest_path.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(manifest_payload, stream, sort_keys=False, allow_unicode=True)


def _load_pool_manifest(manifest_path: Path) -> SequenceTemplatePool:
    with manifest_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}

    template_records: list[SequenceTemplateRecord] = []
    for template_summary in payload.get("templates", []):
        metadata_output_path_rel = template_summary.get("metadata_output_path_rel")
        metadata_output_path = template_summary.get("metadata_output_path")
        if metadata_output_path_rel:
            template_path = manifest_path.parent / str(metadata_output_path_rel)
        elif metadata_output_path:
            template_path = Path(metadata_output_path)
        else:
            raise ValueError(
                f"Template '{template_summary.get('sequence_id')}' in '{manifest_path}' is missing metadata path information."
            )
        template_records.append(_load_template_record(template_path))

    return SequenceTemplatePool(
        iteration=int(payload.get("iteration", 0)),
        seed=int(payload.get("seed", 0)),
        template_records=tuple(template_records),
        active_sequence_length_range=_tuple_int_pair(payload.get("active_sequence_length_range", (0, 0))),
        refresh_reason=str(payload.get("refresh_reason", "loaded_from_manifest")),
        input_backend=str(payload.get("input_backend", "stl")),
        output_backend=str(payload.get("output_backend", "stl")),
    )



def _load_template_record(metadata_path: Path) -> SequenceTemplateRecord:
    with metadata_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}

    segment_records = tuple(
        SequenceSegmentRecord(
            terrain_id=int(segment_payload["terrain_id"]),
            terrain_key=str(segment_payload["terrain_key"]),
            command_profile_key=str(segment_payload["command_profile_key"]),
            physics_profile_key=str(segment_payload["physics_profile_key"]),
            collision_profile_key=str(segment_payload["collision_profile_key"]),
            required_capabilities=tuple(str(capability) for capability in segment_payload.get("required_capabilities", [])),
            segment_length_y=float(segment_payload["segment_length_y"]),
            start_y=float(segment_payload["start_y"]),
            end_y=float(segment_payload["end_y"]),
        )
        for segment_payload in payload.get("segments", [])
    )
    alignment_reports = tuple(
        SequenceAlignmentReport(
            terrain_id=int(report_payload["terrain_id"]),
            terrain_key=str(report_payload["terrain_key"]),
            source_path=str(report_payload["source_path"]),
            forward_axis=str(report_payload["forward_axis"]),
            bounds_min=_triple_float(report_payload["bounds_min"]),
            bounds_max=_triple_float(report_payload["bounds_max"]),
            extent_xyz=_triple_float(report_payload["extent_xyz"]),
            segment_length_y=float(report_payload["segment_length_y"]),
            z_min=float(report_payload["z_min"]),
            z_max=float(report_payload["z_max"]),
            z_span=float(report_payload["z_span"]),
            z_start_edge_mean=_optional_float(report_payload.get("z_start_edge_mean")),
            z_end_edge_mean=_optional_float(report_payload.get("z_end_edge_mean")),
            warnings=tuple(str(warning) for warning in report_payload.get("warnings", [])),
        )
        for report_payload in payload.get("alignment_reports", [])
    )

    return SequenceTemplateRecord(
        sequence_id=str(payload["sequence_id"]),
        terrain_ids=tuple(int(terrain_id) for terrain_id in payload.get("terrain_ids", [])),
        terrain_keys=tuple(str(terrain_key) for terrain_key in payload.get("terrain_keys", [])),
        sequence_length=int(payload.get("sequence_length", 0)),
        segment_offsets_y=tuple(float(value) for value in payload.get("segment_offsets_y", [])),
        segment_lengths_y=tuple(float(value) for value in payload.get("segment_lengths_y", [])),
        buffer_lengths_y=tuple(float(value) for value in payload.get("buffer_lengths_y", [])),
        segment_ranges_y=_range_tuple(payload.get("segment_ranges_y", [])),
        buffer_ranges_y=_range_tuple(payload.get("buffer_ranges_y", [])),
        sequence_total_length_y=float(payload.get("sequence_total_length_y", 0.0)),
        command_profile_keys=tuple(str(key) for key in payload.get("command_profile_keys", [])),
        required_capabilities=tuple(str(capability) for capability in payload.get("required_capabilities", [])),
        physics_profile_keys=tuple(str(key) for key in payload.get("physics_profile_keys", [])),
        collision_profile_keys=tuple(str(key) for key in payload.get("collision_profile_keys", [])),
        segment_records=segment_records,
        alignment_reports=alignment_reports,
        input_format=str(payload.get("input_format", "stl")),
        output_format=str(payload.get("output_format", "stl")),
        forward_axis=str(payload.get("forward_axis", "+Y")),
        base_floor_width_x=float(payload.get("base_floor_width_x", 3.0)),
        base_floor_thickness_z=float(payload.get("base_floor_thickness_z", 0.20)),
        base_floor_start_margin_y=float(payload.get("base_floor_start_margin_y", 1.0)),
        base_floor_end_margin_y=float(payload.get("base_floor_end_margin_y", 1.0)),
        base_floor_top_z=float(payload.get("base_floor_top_z", 0.0)),
        sequence_path=waypoint_path_from_payload(payload.get("sequence_path")),
        segment_waypoint_ranges=_int_range_tuple(payload.get("segment_waypoint_ranges", [])),
        segment_arc_ranges=_range_tuple(payload.get("segment_arc_ranges", [])),
        buffer_arc_ranges=_range_tuple(payload.get("buffer_arc_ranges", [])),
        exit_arc_range=_optional_range(payload.get("exit_arc_range")),
        geometry_output_path=_optional_str(payload.get("geometry_output_path")),
        metadata_output_path=_optional_str(payload.get("metadata_output_path")) or str(metadata_path),
        geometry_output_path_rel=_optional_str(payload.get("geometry_output_path_rel")),
        metadata_output_path_rel=_optional_str(payload.get("metadata_output_path_rel")),
        warnings=tuple(str(warning) for warning in payload.get("warnings", [])),
        sequence_mesh=None,
    )



def _tuple_int_pair(values: list[int] | tuple[int, int]) -> tuple[int, int]:
    first, second = values
    return (int(first), int(second))



def _triple_float(values: list[float] | tuple[float, float, float]) -> tuple[float, float, float]:
    first, second, third = values
    return (float(first), float(second), float(third))



def _range_tuple(values: list[list[float]] | tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    return tuple((float(start), float(end)) for start, end in values)


def _int_range_tuple(values: list[list[int]] | tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    return tuple((int(start), int(end)) for start, end in values)


def _optional_range(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    start, end = value
    return (float(start), float(end))



def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)



def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)



def _default_train_pool_root() -> Path:
    return _repository_root() / "terrains" / "generated_sequences" / "train"



def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]



def _ramp_progress(iteration: int, start_iteration: int, ramp_iterations: int) -> float:
    if iteration <= start_iteration:
        return 0.0
    if ramp_iterations <= 0:
        return 1.0
    return min((iteration - start_iteration) / ramp_iterations, 1.0)



def _lerp(start: float, end: float, alpha: float) -> float:
    return start + (end - start) * alpha



def _unique_dir(base_dir: Path) -> Path:
    if not base_dir.exists():
        return base_dir
    suffix = 1
    while True:
        candidate = base_dir.parent / f"{base_dir.name}__{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


__all__ = [
    "SequencePoolDecision",
    "SequencePoolOrchestrator",
    "SequencePoolScheduler",
]
