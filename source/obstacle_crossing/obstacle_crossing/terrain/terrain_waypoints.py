from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .terrain_registry import ObstacleTerrainRegistry, build_default_obstacle_crossing_registry
from .terrain_specs import ObstacleTerrainSpec


PathFrame = Literal["local_+Y", "sequence_global", "world"]
PatchRole = Literal["entry", "segment", "buffer", "exit"]
ProfileRangeSource = Literal["single", "segment", "buffer_next", "buffer_previous", "buffer_default", "exit"]

DEFAULT_FORWARD_AXIS = "+Y"
DEFAULT_WAYPOINT_SPACING = 0.25
DEFAULT_TARGET_PATCH_SPACING = 0.50
DEFAULT_TARGET_PATCH_HALF_SIZE_Y = 0.25
DEFAULT_CORRIDOR_HALF_WIDTH = 0.45
DEFAULT_LOOKAHEAD_DISTANCE = 0.80
DEFAULT_MAX_BACKWARD_STEP_Y = 0.50
_CONSECUTIVE_SLALOM_POST_Y = (-2.20, -1.10, 0.0, 1.10, 2.20)
_CONSECUTIVE_SLALOM_SIDE_SIGNS = (-1.0, 1.0, -1.0, 1.0, -1.0)
_CONSECUTIVE_SLALOM_LATERAL_OFFSET_X = 1.0
_CONSECUTIVE_SLALOM_ENTRY_Y = -2.35
_CONSECUTIVE_SLALOM_EXIT_Y = 2.35
_CONSECUTIVE_SLALOM_CURVE_SAMPLES_PER_GAP = 8
_S_CURVE_ENTRY_Y = -6.65
_S_CURVE_EXIT_Y = 6.65
_S_CURVE_RADIUS = 3.20
_S_CURVE_LOWER_CENTER_Y = -3.20
_S_CURVE_UPPER_CENTER_Y = 3.20
_S_CURVE_SAMPLES_PER_HALF = 32


@dataclass(frozen=True)
class TargetPatchRecord:
    """A target patch derived from a waypoint path.

    Patches are V1 tolerance/debug/corridor annotations. The command should use
    the path itself for lookahead tracking and may use patches for arrival or
    visualization semantics.
    """

    patch_id: str
    center_xy: tuple[float, float]
    half_size_x: float
    half_size_y: float
    heading_hint_rad: float | None
    source_arc_length: float
    source_waypoint_index: int | None
    segment_index: int | None
    role: PatchRole

    def __post_init__(self) -> None:
        if not self.patch_id:
            raise ValueError("patch_id must be non-empty.")
        _validate_xy(self.center_xy, "center_xy")
        if self.half_size_x <= 0.0:
            raise ValueError(f"half_size_x must be > 0, got {self.half_size_x}.")
        if self.half_size_y <= 0.0:
            raise ValueError(f"half_size_y must be > 0, got {self.half_size_y}.")
        if self.source_arc_length < 0.0:
            raise ValueError(f"source_arc_length must be >= 0, got {self.source_arc_length}.")


@dataclass(frozen=True)
class PathProfileRange:
    """Command profile to use over one arc-length interval of a path."""

    start_s: float
    end_s: float
    command_profile_key: str
    source: ProfileRangeSource
    segment_index: int | None = None

    def __post_init__(self) -> None:
        if self.start_s < 0.0:
            raise ValueError(f"start_s must be >= 0, got {self.start_s}.")
        if self.end_s < self.start_s:
            raise ValueError(f"end_s must be >= start_s, got {self.end_s} < {self.start_s}.")
        if not self.command_profile_key:
            raise ValueError("command_profile_key must be non-empty.")


@dataclass(frozen=True)
class WaypointPathRecord:
    """Shared path representation for single terrains and sequence templates."""

    path_id: str
    frame: PathFrame
    forward_axis: str
    waypoints_xy: tuple[tuple[float, float], ...]
    waypoint_arc_lengths: tuple[float, ...]
    target_patches: tuple[TargetPatchRecord, ...]
    profile_ranges: tuple[PathProfileRange, ...]
    entry_target_xy: tuple[float, float]
    exit_target_xy: tuple[float, float]
    default_lookahead_distance: float
    corridor_half_width: float

    def __post_init__(self) -> None:
        if not self.path_id:
            raise ValueError("path_id must be non-empty.")
        if self.forward_axis != DEFAULT_FORWARD_AXIS:
            raise NotImplementedError(f"Only forward_axis='{DEFAULT_FORWARD_AXIS}' is supported in V1.")
        if len(self.waypoints_xy) < 2:
            raise ValueError("waypoints_xy must contain at least two points.")
        _validate_xy_sequence(self.waypoints_xy, "waypoints_xy")
        if len(self.waypoint_arc_lengths) != len(self.waypoints_xy):
            raise ValueError(
                "waypoint_arc_lengths must match waypoints_xy length: "
                f"{len(self.waypoint_arc_lengths)} vs {len(self.waypoints_xy)}."
            )
        _validate_arc_lengths(self.waypoint_arc_lengths)
        _validate_xy(self.entry_target_xy, "entry_target_xy")
        _validate_xy(self.exit_target_xy, "exit_target_xy")
        if self.default_lookahead_distance <= 0.0:
            raise ValueError(
                f"default_lookahead_distance must be > 0, got {self.default_lookahead_distance}."
            )
        if self.corridor_half_width <= 0.0:
            raise ValueError(f"corridor_half_width must be > 0, got {self.corridor_half_width}.")
        total_length = self.total_length_s
        for profile_range in self.profile_ranges:
            if profile_range.end_s > total_length + 1.0e-6:
                raise ValueError(
                    f"profile range '{profile_range.command_profile_key}' ends at {profile_range.end_s}, "
                    f"but path total length is {total_length}."
                )

    @property
    def total_length_s(self) -> float:
        return float(self.waypoint_arc_lengths[-1])


@dataclass(frozen=True)
class SingleTerrainAnchorRecord:
    terrain_id: int
    terrain_key: str
    frame: PathFrame
    forward_axis: str
    anchors_xy: tuple[tuple[float, float], ...]
    heading_hints_rad: tuple[float | None, ...] = ()

    def __post_init__(self) -> None:
        if self.terrain_id < 0:
            raise ValueError(f"terrain_id must be >= 0, got {self.terrain_id}.")
        if not self.terrain_key:
            raise ValueError("terrain_key must be non-empty.")
        if self.frame != "local_+Y":
            raise ValueError(f"single terrain anchors must use frame='local_+Y', got '{self.frame}'.")
        if self.forward_axis != DEFAULT_FORWARD_AXIS:
            raise NotImplementedError(f"Only forward_axis='{DEFAULT_FORWARD_AXIS}' is supported in V1.")
        if len(self.anchors_xy) < 2:
            raise ValueError(f"Terrain '{self.terrain_key}' must define at least entry and exit anchors.")
        _validate_xy_sequence(self.anchors_xy, "anchors_xy")
        if self.heading_hints_rad and len(self.heading_hints_rad) != len(self.anchors_xy):
            raise ValueError(
                "heading_hints_rad must either be empty or match anchors_xy length: "
                f"{len(self.heading_hints_rad)} vs {len(self.anchors_xy)}."
            )
        _validate_forward_progress(self.anchors_xy, self.terrain_key)


@dataclass(frozen=True)
class SingleTerrainWaypointRecord:
    terrain_id: int
    terrain_key: str
    command_profile_key: str
    anchors_xy: tuple[tuple[float, float], ...]
    path: WaypointPathRecord

    def __post_init__(self) -> None:
        if self.terrain_id < 0:
            raise ValueError(f"terrain_id must be >= 0, got {self.terrain_id}.")
        if not self.terrain_key:
            raise ValueError("terrain_key must be non-empty.")
        if not self.command_profile_key:
            raise ValueError("command_profile_key must be non-empty.")
        if self.path.frame != "local_+Y":
            raise ValueError(f"single terrain path must use frame='local_+Y', got '{self.path.frame}'.")


@dataclass(frozen=True)
class SequenceWaypointPathRecord:
    """Path compose result for one sequence template."""

    path: WaypointPathRecord
    segment_waypoint_ranges: tuple[tuple[int, int], ...]
    segment_arc_ranges: tuple[tuple[float, float], ...]
    buffer_arc_ranges: tuple[tuple[float, float], ...]
    exit_arc_range: tuple[float, float] | None


def _smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def _build_consecutive_slalom_anchors() -> tuple[tuple[float, float], ...]:
    """Build a smooth left-right slalom centerline around the five posts."""

    post_y = _CONSECUTIVE_SLALOM_POST_Y
    side_signs = _CONSECUTIVE_SLALOM_SIDE_SIGNS
    offset_x = _CONSECUTIVE_SLALOM_LATERAL_OFFSET_X
    anchors: list[tuple[float, float]] = [
        (side_signs[0] * offset_x, _CONSECUTIVE_SLALOM_ENTRY_Y),
        (side_signs[0] * offset_x, post_y[0]),
    ]
    for index in range(len(post_y) - 1):
        start_x = side_signs[index] * offset_x
        end_x = side_signs[index + 1] * offset_x
        start_y = post_y[index]
        end_y = post_y[index + 1]
        for step in range(1, _CONSECUTIVE_SLALOM_CURVE_SAMPLES_PER_GAP + 1):
            ratio = step / _CONSECUTIVE_SLALOM_CURVE_SAMPLES_PER_GAP
            smooth_ratio = _smoothstep(ratio)
            anchors.append(
                (
                    start_x + (end_x - start_x) * smooth_ratio,
                    start_y + (end_y - start_y) * ratio,
                )
            )
    anchors.append((side_signs[-1] * offset_x, _CONSECUTIVE_SLALOM_EXIT_Y))
    return tuple(anchors)


def _build_s_curve_anchors() -> tuple[tuple[float, float], ...]:
    """Build the centerline for the S-Curve mesh as two sampled half-circles."""

    anchors: list[tuple[float, float]] = [(0.0, _S_CURVE_ENTRY_Y)]
    for step in range(_S_CURVE_SAMPLES_PER_HALF + 1):
        theta = -math.pi / 2.0 + math.pi * step / _S_CURVE_SAMPLES_PER_HALF
        anchors.append(
            (
                -_S_CURVE_RADIUS * math.cos(theta),
                _S_CURVE_LOWER_CENTER_Y + _S_CURVE_RADIUS * math.sin(theta),
            )
        )
    for step in range(1, _S_CURVE_SAMPLES_PER_HALF + 1):
        theta = -math.pi / 2.0 + math.pi * step / _S_CURVE_SAMPLES_PER_HALF
        anchors.append(
            (
                _S_CURVE_RADIUS * math.cos(theta),
                _S_CURVE_UPPER_CENTER_Y + _S_CURVE_RADIUS * math.sin(theta),
            )
        )
    anchors.append((0.0, _S_CURVE_EXIT_Y))
    return tuple(anchors)


DEFAULT_SINGLE_TERRAIN_ANCHORS: dict[str, tuple[tuple[float, float], ...]] = {
    "continuous_ramp": (
        (0.0, -3.70),
        (0.0, 0.0),
        (0.0, 3.70),
    ),
    "continuous_hurdling": (
        (0.0, -2.30),
        (0.0, -1.10),
        (0.0, 0.0),
        (0.0, 1.10),
        (0.0, 2.30),
    ),
    "cross_slope": (
        (0.0, -3.00),
        (0.0, 0.0),
        (0.0, 3.00),
    ),
    "consecutive_slalom": _build_consecutive_slalom_anchors(),
    "symmetrical_ramp": (
        (0.0, -1.75),
        (0.0, 0.0),
        (0.0, 1.75),
    ),
    "s_curve": _build_s_curve_anchors(),
}

DEFAULT_LOOKAHEAD_DISTANCE_BY_TERRAIN_KEY: dict[str, float] = {
    "continuous_hurdling": 0.60,
    "consecutive_slalom": 0.60,
    "s_curve": 0.70,
}

DEFAULT_CORRIDOR_HALF_WIDTH_BY_TERRAIN_KEY: dict[str, float] = {
    "continuous_hurdling": 0.35,
    "consecutive_slalom": 0.30,
    "s_curve": 0.22,
}


def build_single_terrain_anchor_record(
    spec: ObstacleTerrainSpec,
    *,
    anchors_xy: tuple[tuple[float, float], ...] | None = None,
) -> SingleTerrainAnchorRecord:
    anchors = anchors_xy if anchors_xy is not None else DEFAULT_SINGLE_TERRAIN_ANCHORS.get(spec.key)
    if anchors is None:
        raise KeyError(f"No default waypoint anchors are defined for terrain '{spec.key}'.")
    return SingleTerrainAnchorRecord(
        terrain_id=spec.terrain_id,
        terrain_key=spec.key,
        frame="local_+Y",
        forward_axis=DEFAULT_FORWARD_AXIS,
        anchors_xy=tuple(anchors),
    )


def build_single_terrain_waypoint_record(
    spec: ObstacleTerrainSpec,
    *,
    anchors_xy: tuple[tuple[float, float], ...] | None = None,
    waypoint_spacing: float = DEFAULT_WAYPOINT_SPACING,
    target_patch_spacing: float = DEFAULT_TARGET_PATCH_SPACING,
    target_patch_half_size_y: float = DEFAULT_TARGET_PATCH_HALF_SIZE_Y,
    default_lookahead_distance: float | None = None,
    corridor_half_width: float | None = None,
) -> SingleTerrainWaypointRecord:
    anchor_record = build_single_terrain_anchor_record(spec, anchors_xy=anchors_xy)
    waypoints_xy = interpolate_waypoints_from_anchors(anchor_record.anchors_xy, spacing=waypoint_spacing)
    waypoint_arc_lengths = compute_waypoint_arc_lengths(waypoints_xy)
    lookahead = default_lookahead_distance
    if lookahead is None:
        lookahead = DEFAULT_LOOKAHEAD_DISTANCE_BY_TERRAIN_KEY.get(spec.key, DEFAULT_LOOKAHEAD_DISTANCE)
    corridor_width = corridor_half_width
    if corridor_width is None:
        corridor_width = DEFAULT_CORRIDOR_HALF_WIDTH_BY_TERRAIN_KEY.get(spec.key, DEFAULT_CORRIDOR_HALF_WIDTH)
    target_patches = build_target_patches_from_waypoints(
        path_id=f"single_{spec.key}",
        waypoints_xy=waypoints_xy,
        waypoint_arc_lengths=waypoint_arc_lengths,
        patch_spacing=target_patch_spacing,
        half_size_x=corridor_width,
        half_size_y=target_patch_half_size_y,
    )
    profile_ranges = (
        PathProfileRange(
            start_s=0.0,
            end_s=waypoint_arc_lengths[-1],
            command_profile_key=spec.command_profile_key,
            source="single",
            segment_index=None,
        ),
    )
    path = WaypointPathRecord(
        path_id=f"single_{spec.key}",
        frame="local_+Y",
        forward_axis=DEFAULT_FORWARD_AXIS,
        waypoints_xy=waypoints_xy,
        waypoint_arc_lengths=waypoint_arc_lengths,
        target_patches=target_patches,
        profile_ranges=profile_ranges,
        entry_target_xy=waypoints_xy[0],
        exit_target_xy=waypoints_xy[-1],
        default_lookahead_distance=lookahead,
        corridor_half_width=corridor_width,
    )
    return SingleTerrainWaypointRecord(
        terrain_id=spec.terrain_id,
        terrain_key=spec.key,
        command_profile_key=spec.command_profile_key,
        anchors_xy=anchor_record.anchors_xy,
        path=path,
    )


def build_default_single_terrain_waypoint_records(
    registry: ObstacleTerrainRegistry | None = None,
    *,
    include_future_benchmark: bool = False,
    allow_missing: bool = False,
    waypoint_spacing: float = DEFAULT_WAYPOINT_SPACING,
    target_patch_spacing: float = DEFAULT_TARGET_PATCH_SPACING,
) -> tuple[SingleTerrainWaypointRecord, ...]:
    terrain_registry = registry if registry is not None else build_default_obstacle_crossing_registry()
    specs = terrain_registry.ordered_specs() if include_future_benchmark else terrain_registry.single_train_specs()
    records: list[SingleTerrainWaypointRecord] = []
    for spec in specs:
        try:
            records.append(
                build_single_terrain_waypoint_record(
                    spec,
                    waypoint_spacing=waypoint_spacing,
                    target_patch_spacing=target_patch_spacing,
                )
            )
        except KeyError:
            if not allow_missing:
                raise
    return tuple(records)


def build_default_single_terrain_waypoint_record_map(
    registry: ObstacleTerrainRegistry | None = None,
    *,
    include_future_benchmark: bool = False,
    allow_missing: bool = False,
    waypoint_spacing: float = DEFAULT_WAYPOINT_SPACING,
    target_patch_spacing: float = DEFAULT_TARGET_PATCH_SPACING,
) -> dict[str, SingleTerrainWaypointRecord]:
    records = build_default_single_terrain_waypoint_records(
        registry,
        include_future_benchmark=include_future_benchmark,
        allow_missing=allow_missing,
        waypoint_spacing=waypoint_spacing,
        target_patch_spacing=target_patch_spacing,
    )
    return {record.terrain_key: record for record in records}


def interpolate_waypoints_from_anchors(
    anchors_xy: Sequence[tuple[float, float]],
    *,
    spacing: float = DEFAULT_WAYPOINT_SPACING,
) -> tuple[tuple[float, float], ...]:
    if spacing <= 0.0:
        raise ValueError(f"spacing must be > 0, got {spacing}.")
    anchors = tuple((float(x), float(y)) for x, y in anchors_xy)
    if len(anchors) < 2:
        raise ValueError("anchors_xy must contain at least two points.")
    _validate_xy_sequence(anchors, "anchors_xy")

    waypoints: list[tuple[float, float]] = [anchors[0]]
    for start, end in zip(anchors[:-1], anchors[1:], strict=True):
        segment_length = _distance_xy(start, end)
        if segment_length <= 1.0e-9:
            continue
        steps = max(1, int(math.ceil(segment_length / spacing)))
        for step in range(1, steps + 1):
            t = step / steps
            waypoints.append(_lerp_xy(start, end, t))
    return tuple(waypoints)


def compute_waypoint_arc_lengths(
    waypoints_xy: Sequence[tuple[float, float]],
) -> tuple[float, ...]:
    waypoints = tuple((float(x), float(y)) for x, y in waypoints_xy)
    if len(waypoints) < 2:
        raise ValueError("waypoints_xy must contain at least two points.")
    _validate_xy_sequence(waypoints, "waypoints_xy")
    arc_lengths = [0.0]
    current_s = 0.0
    for start, end in zip(waypoints[:-1], waypoints[1:], strict=True):
        current_s += _distance_xy(start, end)
        arc_lengths.append(current_s)
    return tuple(arc_lengths)


def build_target_patches_from_waypoints(
    *,
    path_id: str,
    waypoints_xy: Sequence[tuple[float, float]],
    waypoint_arc_lengths: Sequence[float],
    patch_spacing: float = DEFAULT_TARGET_PATCH_SPACING,
    half_size_x: float = DEFAULT_CORRIDOR_HALF_WIDTH,
    half_size_y: float = DEFAULT_TARGET_PATCH_HALF_SIZE_Y,
    segment_index: int | None = None,
    default_role: PatchRole = "segment",
) -> tuple[TargetPatchRecord, ...]:
    if not path_id:
        raise ValueError("path_id must be non-empty.")
    if patch_spacing <= 0.0:
        raise ValueError(f"patch_spacing must be > 0, got {patch_spacing}.")
    if half_size_x <= 0.0:
        raise ValueError(f"half_size_x must be > 0, got {half_size_x}.")
    if half_size_y <= 0.0:
        raise ValueError(f"half_size_y must be > 0, got {half_size_y}.")
    waypoints = tuple((float(x), float(y)) for x, y in waypoints_xy)
    arc_lengths = tuple(float(v) for v in waypoint_arc_lengths)
    if len(waypoints) != len(arc_lengths):
        raise ValueError("waypoints_xy and waypoint_arc_lengths must have the same length.")
    _validate_xy_sequence(waypoints, "waypoints_xy")
    _validate_arc_lengths(arc_lengths)

    selected_indices = _select_patch_waypoint_indices(arc_lengths, patch_spacing)
    patches: list[TargetPatchRecord] = []
    for patch_number, waypoint_index in enumerate(selected_indices):
        role: PatchRole = default_role
        if waypoint_index == 0:
            role = "entry"
        elif waypoint_index == len(waypoints) - 1:
            role = "exit"
        heading_hint_rad = _heading_at_waypoint(waypoints, waypoint_index)
        patches.append(
            TargetPatchRecord(
                patch_id=f"{path_id}__patch_{patch_number:04d}",
                center_xy=waypoints[waypoint_index],
                half_size_x=half_size_x,
                half_size_y=half_size_y,
                heading_hint_rad=heading_hint_rad,
                source_arc_length=arc_lengths[waypoint_index],
                source_waypoint_index=waypoint_index,
                segment_index=segment_index,
                role=role,
            )
        )
    return tuple(patches)


def transform_waypoint_path(
    path: WaypointPathRecord,
    *,
    translate_xy: tuple[float, float] = (0.0, 0.0),
    frame: PathFrame,
    path_id: str | None = None,
) -> WaypointPathRecord:
    tx, ty = translate_xy
    waypoints_xy = tuple((x + tx, y + ty) for x, y in path.waypoints_xy)
    target_patches = tuple(
        TargetPatchRecord(
            patch_id=patch.patch_id if path_id is None else patch.patch_id.replace(path.path_id, path_id, 1),
            center_xy=(patch.center_xy[0] + tx, patch.center_xy[1] + ty),
            half_size_x=patch.half_size_x,
            half_size_y=patch.half_size_y,
            heading_hint_rad=patch.heading_hint_rad,
            source_arc_length=patch.source_arc_length,
            source_waypoint_index=patch.source_waypoint_index,
            segment_index=patch.segment_index,
            role=patch.role,
        )
        for patch in path.target_patches
    )
    return WaypointPathRecord(
        path_id=path.path_id if path_id is None else path_id,
        frame=frame,
        forward_axis=path.forward_axis,
        waypoints_xy=waypoints_xy,
        waypoint_arc_lengths=path.waypoint_arc_lengths,
        target_patches=target_patches,
        profile_ranges=path.profile_ranges,
        entry_target_xy=(path.entry_target_xy[0] + tx, path.entry_target_xy[1] + ty),
        exit_target_xy=(path.exit_target_xy[0] + tx, path.exit_target_xy[1] + ty),
        default_lookahead_distance=path.default_lookahead_distance,
        corridor_half_width=path.corridor_half_width,
    )


def target_patch_to_payload(patch: TargetPatchRecord) -> dict:
    return {
        "patch_id": patch.patch_id,
        "center_xy": [float(patch.center_xy[0]), float(patch.center_xy[1])],
        "half_size_x": float(patch.half_size_x),
        "half_size_y": float(patch.half_size_y),
        "heading_hint_rad": None if patch.heading_hint_rad is None else float(patch.heading_hint_rad),
        "source_arc_length": float(patch.source_arc_length),
        "source_waypoint_index": patch.source_waypoint_index,
        "segment_index": patch.segment_index,
        "role": patch.role,
    }


def target_patch_from_payload(payload: dict) -> TargetPatchRecord:
    center_xy = payload.get("center_xy", (0.0, 0.0))
    return TargetPatchRecord(
        patch_id=str(payload["patch_id"]),
        center_xy=_xy_tuple(center_xy),
        half_size_x=float(payload["half_size_x"]),
        half_size_y=float(payload["half_size_y"]),
        heading_hint_rad=_optional_float(payload.get("heading_hint_rad")),
        source_arc_length=float(payload.get("source_arc_length", 0.0)),
        source_waypoint_index=_optional_int(payload.get("source_waypoint_index")),
        segment_index=_optional_int(payload.get("segment_index")),
        role=str(payload.get("role", "segment")),
    )


def path_profile_range_to_payload(profile_range: PathProfileRange) -> dict:
    return {
        "start_s": float(profile_range.start_s),
        "end_s": float(profile_range.end_s),
        "command_profile_key": profile_range.command_profile_key,
        "source": profile_range.source,
        "segment_index": profile_range.segment_index,
    }


def path_profile_range_from_payload(payload: dict) -> PathProfileRange:
    return PathProfileRange(
        start_s=float(payload["start_s"]),
        end_s=float(payload["end_s"]),
        command_profile_key=str(payload["command_profile_key"]),
        source=str(payload.get("source", "segment")),
        segment_index=_optional_int(payload.get("segment_index")),
    )


def waypoint_path_to_payload(path: WaypointPathRecord) -> dict:
    return {
        "path_id": path.path_id,
        "frame": path.frame,
        "forward_axis": path.forward_axis,
        "waypoints_xy": [[float(x), float(y)] for x, y in path.waypoints_xy],
        "waypoint_arc_lengths": [float(value) for value in path.waypoint_arc_lengths],
        "target_patches": [target_patch_to_payload(patch) for patch in path.target_patches],
        "profile_ranges": [path_profile_range_to_payload(profile_range) for profile_range in path.profile_ranges],
        "entry_target_xy": [float(path.entry_target_xy[0]), float(path.entry_target_xy[1])],
        "exit_target_xy": [float(path.exit_target_xy[0]), float(path.exit_target_xy[1])],
        "default_lookahead_distance": float(path.default_lookahead_distance),
        "corridor_half_width": float(path.corridor_half_width),
        "total_length_s": float(path.total_length_s),
    }


def waypoint_path_from_payload(payload: dict | None) -> WaypointPathRecord | None:
    if not payload:
        return None
    return WaypointPathRecord(
        path_id=str(payload["path_id"]),
        frame=str(payload.get("frame", "sequence_global")),
        forward_axis=str(payload.get("forward_axis", DEFAULT_FORWARD_AXIS)),
        waypoints_xy=tuple(_xy_tuple(value) for value in payload.get("waypoints_xy", [])),
        waypoint_arc_lengths=tuple(float(value) for value in payload.get("waypoint_arc_lengths", [])),
        target_patches=tuple(target_patch_from_payload(value) for value in payload.get("target_patches", [])),
        profile_ranges=tuple(path_profile_range_from_payload(value) for value in payload.get("profile_ranges", [])),
        entry_target_xy=_xy_tuple(payload.get("entry_target_xy", (0.0, 0.0))),
        exit_target_xy=_xy_tuple(payload.get("exit_target_xy", (0.0, 0.0))),
        default_lookahead_distance=float(payload.get("default_lookahead_distance", DEFAULT_LOOKAHEAD_DISTANCE)),
        corridor_half_width=float(payload.get("corridor_half_width", DEFAULT_CORRIDOR_HALF_WIDTH)),
    )


def compose_sequence_waypoint_path(
    *,
    sequence_id: str,
    segment_paths: Sequence[WaypointPathRecord],
    segment_ranges_y: Sequence[tuple[float, float]],
    buffer_ranges_y: Sequence[tuple[float, float]],
    command_profile_keys: Sequence[str],
    sequence_total_length_y: float | None = None,
    waypoint_spacing: float = DEFAULT_WAYPOINT_SPACING,
    target_patch_spacing: float = DEFAULT_TARGET_PATCH_SPACING,
    buffer_profile_mode: Literal["next", "previous", "default"] = "next",
    default_buffer_profile_key: str = "default",
    exit_profile_mode: Literal["last", "default"] = "last",
    default_exit_profile_key: str = "default",
) -> SequenceWaypointPathRecord:
    """Compose a sequence-local path from segment-local paths.

    V1 profile semantics:
    - segment interior uses that segment's profile
    - buffer defaults to the next segment's profile
    - exit zone defaults to the last segment's profile
    """

    if not sequence_id:
        raise ValueError("sequence_id must be non-empty.")
    if not segment_paths:
        raise ValueError("Cannot compose a sequence path without segment paths.")
    if len(segment_paths) != len(segment_ranges_y):
        raise ValueError("segment_paths and segment_ranges_y must have the same length.")
    if len(command_profile_keys) != len(segment_paths):
        raise ValueError("command_profile_keys must match segment_paths length.")
    if len(buffer_ranges_y) != max(len(segment_paths) - 1, 0):
        raise ValueError("buffer_ranges_y length must be one less than segment_paths length.")
    if waypoint_spacing <= 0.0:
        raise ValueError(f"waypoint_spacing must be > 0, got {waypoint_spacing}.")

    all_waypoints: list[tuple[float, float]] = []
    segment_waypoint_ranges: list[tuple[int, int]] = []
    buffer_waypoint_ranges: list[tuple[int, int]] = []

    previous_exit_xy: tuple[float, float] | None = None
    for segment_index, (path, segment_range_y) in enumerate(zip(segment_paths, segment_ranges_y, strict=True)):
        if path.frame not in ("local_+Y", "sequence_global"):
            raise ValueError(
                f"segment path '{path.path_id}' must use frame 'local_+Y' or 'sequence_global', got '{path.frame}'."
            )
        segment_start_y = float(segment_range_y[0])
        translation_y = segment_start_y - path.entry_target_xy[1]
        translated_waypoints = tuple((x, y + translation_y) for x, y in path.waypoints_xy)

        if previous_exit_xy is not None:
            connector = interpolate_waypoints_from_anchors(
                (previous_exit_xy, translated_waypoints[0]),
                spacing=waypoint_spacing,
            )
            buffer_start_idx = len(all_waypoints)
            all_waypoints.extend(connector[1:-1])
            buffer_end_idx = len(all_waypoints)
            buffer_waypoint_ranges.append((buffer_start_idx, buffer_end_idx))

        segment_start_idx = len(all_waypoints)
        if all_waypoints and all_waypoints[-1] == translated_waypoints[0]:
            all_waypoints.extend(translated_waypoints[1:])
        else:
            all_waypoints.extend(translated_waypoints)
        segment_end_idx = len(all_waypoints)
        segment_waypoint_ranges.append((segment_start_idx, segment_end_idx))
        previous_exit_xy = translated_waypoints[-1]

    exit_waypoint_range: tuple[int, int] | None = None
    if sequence_total_length_y is not None:
        total_y = float(sequence_total_length_y)
        if total_y > all_waypoints[-1][1] + 1.0e-6:
            exit_target_xy = (all_waypoints[-1][0], total_y)
            connector = interpolate_waypoints_from_anchors(
                (all_waypoints[-1], exit_target_xy),
                spacing=waypoint_spacing,
            )
            exit_start_idx = len(all_waypoints)
            all_waypoints.extend(connector[1:])
            exit_waypoint_range = (exit_start_idx, len(all_waypoints))

    waypoints_xy = tuple(all_waypoints)
    waypoint_arc_lengths = compute_waypoint_arc_lengths(waypoints_xy)
    segment_arc_ranges = tuple(
        (waypoint_arc_lengths[start], waypoint_arc_lengths[end - 1])
        for start, end in segment_waypoint_ranges
    )

    buffer_arc_ranges: list[tuple[float, float]] = []
    for index in range(len(segment_arc_ranges) - 1):
        buffer_arc_ranges.append((segment_arc_ranges[index][1], segment_arc_ranges[index + 1][0]))

    exit_arc_range: tuple[float, float] | None = None
    if exit_waypoint_range is not None:
        exit_arc_range = (
            waypoint_arc_lengths[exit_waypoint_range[0] - 1],
            waypoint_arc_lengths[exit_waypoint_range[1] - 1],
        )

    profile_ranges = _build_sequence_profile_ranges(
        segment_arc_ranges=segment_arc_ranges,
        buffer_arc_ranges=tuple(buffer_arc_ranges),
        exit_arc_range=exit_arc_range,
        command_profile_keys=tuple(command_profile_keys),
        buffer_profile_mode=buffer_profile_mode,
        default_buffer_profile_key=default_buffer_profile_key,
        exit_profile_mode=exit_profile_mode,
        default_exit_profile_key=default_exit_profile_key,
    )
    corridor_half_width = min(path.corridor_half_width for path in segment_paths)
    lookahead = min(path.default_lookahead_distance for path in segment_paths)
    target_patches = build_target_patches_from_waypoints(
        path_id=f"sequence_{sequence_id}",
        waypoints_xy=waypoints_xy,
        waypoint_arc_lengths=waypoint_arc_lengths,
        patch_spacing=target_patch_spacing,
        half_size_x=corridor_half_width,
        half_size_y=DEFAULT_TARGET_PATCH_HALF_SIZE_Y,
    )
    path = WaypointPathRecord(
        path_id=f"sequence_{sequence_id}",
        frame="sequence_global",
        forward_axis=DEFAULT_FORWARD_AXIS,
        waypoints_xy=waypoints_xy,
        waypoint_arc_lengths=waypoint_arc_lengths,
        target_patches=target_patches,
        profile_ranges=profile_ranges,
        entry_target_xy=waypoints_xy[0],
        exit_target_xy=waypoints_xy[-1],
        default_lookahead_distance=lookahead,
        corridor_half_width=corridor_half_width,
    )
    return SequenceWaypointPathRecord(
        path=path,
        segment_waypoint_ranges=tuple(segment_waypoint_ranges),
        segment_arc_ranges=segment_arc_ranges,
        buffer_arc_ranges=tuple(buffer_arc_ranges),
        exit_arc_range=exit_arc_range,
    )


def _build_sequence_profile_ranges(
    *,
    segment_arc_ranges: tuple[tuple[float, float], ...],
    buffer_arc_ranges: tuple[tuple[float, float], ...],
    exit_arc_range: tuple[float, float] | None,
    command_profile_keys: tuple[str, ...],
    buffer_profile_mode: Literal["next", "previous", "default"],
    default_buffer_profile_key: str,
    exit_profile_mode: Literal["last", "default"],
    default_exit_profile_key: str,
) -> tuple[PathProfileRange, ...]:
    profile_ranges: list[PathProfileRange] = []
    for segment_index, (start_s, end_s) in enumerate(segment_arc_ranges):
        profile_ranges.append(
            PathProfileRange(
                start_s=start_s,
                end_s=end_s,
                command_profile_key=command_profile_keys[segment_index],
                source="segment",
                segment_index=segment_index,
            )
        )
        if segment_index < len(buffer_arc_ranges):
            buffer_start_s, buffer_end_s = buffer_arc_ranges[segment_index]
            if buffer_profile_mode == "next":
                profile_key = command_profile_keys[segment_index + 1]
                source: ProfileRangeSource = "buffer_next"
            elif buffer_profile_mode == "previous":
                profile_key = command_profile_keys[segment_index]
                source = "buffer_previous"
            else:
                profile_key = default_buffer_profile_key
                source = "buffer_default"
            profile_ranges.append(
                PathProfileRange(
                    start_s=buffer_start_s,
                    end_s=buffer_end_s,
                    command_profile_key=profile_key,
                    source=source,
                    segment_index=segment_index,
                )
            )

    if exit_arc_range is not None:
        exit_profile_key = command_profile_keys[-1] if exit_profile_mode == "last" else default_exit_profile_key
        profile_ranges.append(
            PathProfileRange(
                start_s=exit_arc_range[0],
                end_s=exit_arc_range[1],
                command_profile_key=exit_profile_key,
                source="exit",
                segment_index=len(command_profile_keys) - 1,
            )
        )
    return tuple(profile_ranges)


def _select_patch_waypoint_indices(arc_lengths: tuple[float, ...], patch_spacing: float) -> tuple[int, ...]:
    selected = [0]
    next_s = patch_spacing
    for idx, arc_length in enumerate(arc_lengths[1:-1], start=1):
        if arc_length + 1.0e-9 >= next_s:
            selected.append(idx)
            next_s = arc_length + patch_spacing
    if selected[-1] != len(arc_lengths) - 1:
        selected.append(len(arc_lengths) - 1)
    return tuple(selected)


def _heading_at_waypoint(waypoints: tuple[tuple[float, float], ...], index: int) -> float:
    if index <= 0:
        start, end = waypoints[0], waypoints[1]
    elif index >= len(waypoints) - 1:
        start, end = waypoints[-2], waypoints[-1]
    else:
        start, end = waypoints[index - 1], waypoints[index + 1]
    return math.atan2(end[1] - start[1], end[0] - start[0])


def _validate_xy(value: tuple[float, float], name: str) -> None:
    if len(value) != 2:
        raise ValueError(f"{name} must contain exactly 2 values, got {value}.")
    for item in value:
        if not math.isfinite(float(item)):
            raise ValueError(f"{name} contains a non-finite value: {value}.")


def _validate_xy_sequence(values: Sequence[tuple[float, float]], name: str) -> None:
    for index, value in enumerate(values):
        _validate_xy(value, f"{name}[{index}]")


def _xy_tuple(value: Sequence[float]) -> tuple[float, float]:
    first, second = value
    return (float(first), float(second))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _validate_arc_lengths(values: Sequence[float]) -> None:
    if not values:
        raise ValueError("waypoint_arc_lengths must not be empty.")
    if abs(float(values[0])) > 1.0e-9:
        raise ValueError(f"waypoint_arc_lengths must start at 0.0, got {values[0]}.")
    previous = float(values[0])
    for value in values[1:]:
        current = float(value)
        if current + 1.0e-9 < previous:
            raise ValueError("waypoint_arc_lengths must be sorted in non-decreasing order.")
        previous = current


def _validate_forward_progress(
    anchors_xy: Sequence[tuple[float, float]],
    terrain_key: str,
    *,
    max_backward_step_y: float = DEFAULT_MAX_BACKWARD_STEP_Y,
) -> None:
    if anchors_xy[-1][1] <= anchors_xy[0][1]:
        raise ValueError(
            f"Terrain '{terrain_key}' anchors must make net progress along +Y: "
            f"{anchors_xy[0][1]} -> {anchors_xy[-1][1]}."
        )
    for start, end in zip(anchors_xy[:-1], anchors_xy[1:], strict=True):
        if end[1] + max_backward_step_y < start[1]:
            raise ValueError(
                f"Terrain '{terrain_key}' has excessive backward +Y anchor step: {start} -> {end}."
            )


def _distance_xy(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def _lerp_xy(start: tuple[float, float], end: tuple[float, float], t: float) -> tuple[float, float]:
    return (float(start[0] + (end[0] - start[0]) * t), float(start[1] + (end[1] - start[1]) * t))


__all__ = [
    "DEFAULT_CORRIDOR_HALF_WIDTH",
    "DEFAULT_FORWARD_AXIS",
    "DEFAULT_LOOKAHEAD_DISTANCE",
    "DEFAULT_SINGLE_TERRAIN_ANCHORS",
    "DEFAULT_TARGET_PATCH_HALF_SIZE_Y",
    "DEFAULT_TARGET_PATCH_SPACING",
    "DEFAULT_WAYPOINT_SPACING",
    "PathFrame",
    "PathProfileRange",
    "PatchRole",
    "ProfileRangeSource",
    "SequenceWaypointPathRecord",
    "SingleTerrainAnchorRecord",
    "SingleTerrainWaypointRecord",
    "TargetPatchRecord",
    "WaypointPathRecord",
    "build_default_single_terrain_waypoint_record_map",
    "build_default_single_terrain_waypoint_records",
    "build_single_terrain_anchor_record",
    "build_single_terrain_waypoint_record",
    "build_target_patches_from_waypoints",
    "compute_waypoint_arc_lengths",
    "compose_sequence_waypoint_path",
    "interpolate_waypoints_from_anchors",
    "path_profile_range_from_payload",
    "target_patch_from_payload",
    "waypoint_path_from_payload",
    "waypoint_path_to_payload",
    "transform_waypoint_path",
]
