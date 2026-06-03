from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

import torch

from .terrain_waypoints import WaypointPathRecord


_EPS = 1.0e-9


@dataclass(frozen=True)
class PathTrackingCfg:
    """Runtime path tracking parameters shared by command and visualization."""

    sample_spacing: float = 0.25
    tight_curve_sample_spacing: float = 0.12
    backtrack_margin: float = 0.5
    forward_search_window: float = 2.0
    min_lookahead: float = 0.25
    max_lookahead: float = 1.0
    target_smoothing_alpha: float = 0.3
    curvature_lookahead_gain: float = 1.0

    def __post_init__(self) -> None:
        if self.sample_spacing <= 0.0:
            raise ValueError(f"sample_spacing must be > 0, got {self.sample_spacing}.")
        if self.tight_curve_sample_spacing <= 0.0:
            raise ValueError(f"tight_curve_sample_spacing must be > 0, got {self.tight_curve_sample_spacing}.")
        if self.backtrack_margin < 0.0:
            raise ValueError(f"backtrack_margin must be >= 0, got {self.backtrack_margin}.")
        if self.forward_search_window <= 0.0:
            raise ValueError(f"forward_search_window must be > 0, got {self.forward_search_window}.")
        if self.min_lookahead <= 0.0:
            raise ValueError(f"min_lookahead must be > 0, got {self.min_lookahead}.")
        if self.max_lookahead < self.min_lookahead:
            raise ValueError(
                f"max_lookahead must be >= min_lookahead, got {self.max_lookahead} < {self.min_lookahead}."
            )
        if not 0.0 <= self.target_smoothing_alpha <= 1.0:
            raise ValueError(
                "target_smoothing_alpha must be in [0, 1], "
                f"got {self.target_smoothing_alpha}."
            )
        if self.curvature_lookahead_gain < 0.0:
            raise ValueError(
                f"curvature_lookahead_gain must be >= 0, got {self.curvature_lookahead_gain}."
            )


@dataclass(frozen=True)
class PathProjection:
    """Projection of one XY point onto one waypoint path."""

    valid: bool
    progress_s: float
    nearest_xy_path: tuple[float, float]
    lateral_error: float
    signed_lateral_error: float
    segment_index: int


@dataclass(frozen=True)
class PathTrackingTargets:
    """Batched path-frame tracking outputs consumed by command logic."""

    valid_mask: torch.Tensor
    progress_s: torch.Tensor
    nearest_xy_path: torch.Tensor
    lateral_error: torch.Tensor
    signed_lateral_error: torch.Tensor
    segment_index: torch.Tensor
    target_s: torch.Tensor
    target_xy_path: torch.Tensor


@dataclass(frozen=True)
class TrackingPathCache:
    """Dense arc-length samples derived from a waypoint path for runtime tracking."""

    path_id: str
    sample_s: torch.Tensor
    sample_xy_path: torch.Tensor
    tangent_xy_path: torch.Tensor
    curvature: torch.Tensor
    corridor_half_width: float
    default_lookahead_distance: float
    total_length_s: float


@dataclass(frozen=True)
class StatefulPathTrackingTargets:
    """Batched stateful path tracking outputs for command integration."""

    valid_mask: torch.Tensor
    progress_s: torch.Tensor
    nearest_xy_path: torch.Tensor
    lateral_error: torch.Tensor
    signed_lateral_error: torch.Tensor
    segment_index: torch.Tensor
    lookahead_distance: torch.Tensor
    target_s: torch.Tensor
    target_xy_path: torch.Tensor
    target_tangent_xy_path: torch.Tensor


def project_point_to_path(
    point_xy: torch.Tensor | Sequence[float],
    path: WaypointPathRecord | None,
) -> PathProjection:
    """Project one path-frame point onto a waypoint path polyline."""
    if path is None:
        return _invalid_projection()

    px, py = _xy_pair(point_xy, "point_xy")
    best_dist_sq = math.inf
    best_progress_s = 0.0
    best_nearest_xy = (0.0, 0.0)
    best_signed_lateral = 0.0
    best_segment_index = -1

    for segment_index, (start_xy, end_xy) in enumerate(zip(path.waypoints_xy[:-1], path.waypoints_xy[1:], strict=True)):
        sx, sy = start_xy
        ex, ey = end_xy
        dx = ex - sx
        dy = ey - sy
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq <= _EPS:
            continue

        rel_x = px - sx
        rel_y = py - sy
        t = max(0.0, min(1.0, (rel_x * dx + rel_y * dy) / seg_len_sq))
        nearest_x = sx + t * dx
        nearest_y = sy + t * dy
        err_x = px - nearest_x
        err_y = py - nearest_y
        dist_sq = err_x * err_x + err_y * err_y

        if dist_sq < best_dist_sq:
            start_s = float(path.waypoint_arc_lengths[segment_index])
            end_s = float(path.waypoint_arc_lengths[segment_index + 1])
            seg_len = math.sqrt(seg_len_sq)
            cross = dx * err_y - dy * err_x
            best_dist_sq = dist_sq
            best_progress_s = start_s + t * (end_s - start_s)
            best_nearest_xy = (nearest_x, nearest_y)
            best_signed_lateral = cross / seg_len
            best_segment_index = segment_index

    if best_segment_index < 0:
        return _invalid_projection()

    return PathProjection(
        valid=True,
        progress_s=best_progress_s,
        nearest_xy_path=best_nearest_xy,
        lateral_error=math.sqrt(best_dist_sq),
        signed_lateral_error=best_signed_lateral,
        segment_index=best_segment_index,
    )


def sample_path_by_spacing(
    path: WaypointPathRecord,
    spacing: float,
    *,
    dtype: torch.dtype = torch.float32,
    device: torch.device | str | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Resample a waypoint path by arc-length spacing, including both endpoints."""
    if spacing <= 0.0:
        raise ValueError(f"spacing must be > 0, got {spacing}.")
    total_length = path.total_length_s
    sample_count = max(2, int(math.ceil(total_length / spacing)) + 1)
    sample_s = torch.linspace(0.0, total_length, sample_count, dtype=dtype, device=device)
    sample_xy = torch.tensor(
        [interpolate_path_xy(path, float(value.item())) for value in sample_s],
        dtype=dtype,
        device=device,
    )
    return sample_s, sample_xy


def estimate_path_tangents(sample_xy_path: torch.Tensor) -> torch.Tensor:
    """Estimate normalized tangent vectors for dense path samples."""
    samples = torch.as_tensor(sample_xy_path)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise ValueError(f"sample_xy_path must have shape [N, 2], got {tuple(samples.shape)}.")
    if samples.shape[0] == 0:
        raise ValueError("sample_xy_path must contain at least one sample.")

    tangents = torch.zeros_like(samples)
    if samples.shape[0] == 1:
        tangents[0] = torch.tensor([0.0, 1.0], dtype=samples.dtype, device=samples.device)
        return tangents

    tangents[0] = samples[1] - samples[0]
    tangents[-1] = samples[-1] - samples[-2]
    if samples.shape[0] > 2:
        tangents[1:-1] = samples[2:] - samples[:-2]

    norms = torch.linalg.norm(tangents, dim=1, keepdim=True)
    fallback = torch.tensor([0.0, 1.0], dtype=samples.dtype, device=samples.device).expand_as(tangents)
    return torch.where(norms > _EPS, tangents / torch.clamp(norms, min=_EPS), fallback)


def estimate_path_curvature(tangent_xy_path: torch.Tensor, sample_s: torch.Tensor) -> torch.Tensor:
    """Estimate curvature magnitude from tangent changes over arc length."""
    tangents = torch.as_tensor(tangent_xy_path)
    arc_s = torch.as_tensor(sample_s, dtype=tangents.dtype, device=tangents.device)
    if tangents.ndim != 2 or tangents.shape[1] != 2:
        raise ValueError(f"tangent_xy_path must have shape [N, 2], got {tuple(tangents.shape)}.")
    if arc_s.ndim != 1 or arc_s.shape[0] != tangents.shape[0]:
        raise ValueError(
            "sample_s must be a 1-D tensor with the same length as tangent_xy_path: "
            f"{tuple(arc_s.shape)} vs {tuple(tangents.shape)}."
        )
    if tangents.shape[0] < 2:
        return torch.zeros(tangents.shape[0], dtype=tangents.dtype, device=tangents.device)

    curvature = torch.zeros(tangents.shape[0], dtype=tangents.dtype, device=tangents.device)
    for index in range(tangents.shape[0]):
        if index == 0:
            delta_tangent = tangents[1] - tangents[0]
            delta_s = arc_s[1] - arc_s[0]
        elif index == tangents.shape[0] - 1:
            delta_tangent = tangents[-1] - tangents[-2]
            delta_s = arc_s[-1] - arc_s[-2]
        else:
            delta_tangent = tangents[index + 1] - tangents[index - 1]
            delta_s = arc_s[index + 1] - arc_s[index - 1]
        if abs(float(delta_s.item())) > _EPS:
            curvature[index] = torch.linalg.norm(delta_tangent) / torch.clamp(torch.abs(delta_s), min=_EPS)
    return curvature


def build_tracking_path_cache(
    path: WaypointPathRecord,
    cfg: PathTrackingCfg | None = None,
    *,
    dtype: torch.dtype = torch.float32,
    device: torch.device | str | None = None,
) -> TrackingPathCache:
    """Build a dense tracking cache from a waypoint path."""
    tracking_cfg = cfg or PathTrackingCfg()
    sample_s, sample_xy_path = sample_path_by_spacing(
        path,
        tracking_cfg.sample_spacing,
        dtype=dtype,
        device=device,
    )
    tangent_xy_path = estimate_path_tangents(sample_xy_path)
    curvature = estimate_path_curvature(tangent_xy_path, sample_s)
    return TrackingPathCache(
        path_id=path.path_id,
        sample_s=sample_s,
        sample_xy_path=sample_xy_path,
        tangent_xy_path=tangent_xy_path,
        curvature=curvature,
        corridor_half_width=path.corridor_half_width,
        default_lookahead_distance=path.default_lookahead_distance,
        total_length_s=path.total_length_s,
    )


def interpolate_path_xy(path: WaypointPathRecord, arc_length_s: float) -> tuple[float, float]:
    """Interpolate one XY point on a path by arc length, clamped to path bounds."""
    target_s = max(0.0, min(float(arc_length_s), path.total_length_s))
    arc_lengths = path.waypoint_arc_lengths

    if target_s <= arc_lengths[0]:
        return path.waypoints_xy[0]
    if target_s >= arc_lengths[-1]:
        return path.waypoints_xy[-1]

    for segment_index in range(len(arc_lengths) - 1):
        start_s = float(arc_lengths[segment_index])
        end_s = float(arc_lengths[segment_index + 1])
        if target_s > end_s:
            continue

        start_xy = path.waypoints_xy[segment_index]
        end_xy = path.waypoints_xy[segment_index + 1]
        if end_s <= start_s + _EPS:
            return end_xy
        t = (target_s - start_s) / (end_s - start_s)
        return (
            start_xy[0] + t * (end_xy[0] - start_xy[0]),
            start_xy[1] + t * (end_xy[1] - start_xy[1]),
        )

    return path.waypoints_xy[-1]


def interpolate_cache_xy(cache: TrackingPathCache, arc_length_s: float) -> tuple[float, float]:
    """Interpolate XY from a tracking cache by arc length."""
    return _interpolate_cache_tensor(cache.sample_s, cache.sample_xy_path, arc_length_s)


def interpolate_cache_tangent(cache: TrackingPathCache, arc_length_s: float) -> tuple[float, float]:
    """Interpolate normalized tangent from a tracking cache by arc length."""
    tangent_xy = _interpolate_cache_tensor(cache.sample_s, cache.tangent_xy_path, arc_length_s)
    norm = math.hypot(tangent_xy[0], tangent_xy[1])
    if norm <= _EPS:
        return 0.0, 1.0
    return tangent_xy[0] / norm, tangent_xy[1] / norm


def interpolate_cache_curvature(cache: TrackingPathCache, arc_length_s: float) -> float:
    """Interpolate scalar curvature from a tracking cache by arc length."""
    values = _interpolate_cache_tensor(cache.sample_s, cache.curvature.unsqueeze(-1), arc_length_s)
    return values[0]


def project_point_to_tracking_cache(
    point_xy: torch.Tensor | Sequence[float],
    cache: TrackingPathCache | None,
    *,
    previous_progress_s: float | None = None,
    cfg: PathTrackingCfg | None = None,
) -> PathProjection:
    """Project one point onto a tracking cache, optionally limited by previous progress."""
    if cache is None:
        return _invalid_projection()

    tracking_cfg = cfg or PathTrackingCfg()
    search_min_s: float | None = None
    search_max_s: float | None = None
    if previous_progress_s is not None:
        previous_s = max(0.0, min(float(previous_progress_s), cache.total_length_s))
        search_min_s = max(0.0, previous_s - tracking_cfg.backtrack_margin)
        search_max_s = min(cache.total_length_s, previous_s + tracking_cfg.forward_search_window)

    return _project_point_to_sampled_polyline(
        point_xy,
        cache.sample_xy_path,
        cache.sample_s,
        search_min_s=search_min_s,
        search_max_s=search_max_s,
    )


def project_point_to_path_windowed(
    point_xy: torch.Tensor | Sequence[float],
    path: WaypointPathRecord | None,
    *,
    previous_progress_s: float | None,
    cfg: PathTrackingCfg | None = None,
) -> PathProjection:
    """Project one point to a path using a tracking cache and a local progress window."""
    if path is None:
        return _invalid_projection()
    tracking_cfg = cfg or PathTrackingCfg()
    cache = build_tracking_path_cache(path, tracking_cfg)
    return project_point_to_tracking_cache(
        point_xy,
        cache,
        previous_progress_s=previous_progress_s,
        cfg=tracking_cfg,
    )


def compute_path_tracking_targets(
    robot_xy_path: torch.Tensor,
    paths: Sequence[WaypointPathRecord | None],
    *,
    lookahead_distances: torch.Tensor | Sequence[float] | None = None,
) -> PathTrackingTargets:
    """Compute V1 Python-loop path tracking targets for a batch of envs."""
    robot_xy = torch.as_tensor(robot_xy_path)
    if robot_xy.ndim != 2 or robot_xy.shape[1] != 2:
        raise ValueError(f"robot_xy_path must have shape [N, 2], got {tuple(robot_xy.shape)}.")
    if len(paths) != robot_xy.shape[0]:
        raise ValueError(f"paths length must match robot_xy_path rows: {len(paths)} vs {robot_xy.shape[0]}.")

    device = robot_xy.device
    dtype = robot_xy.dtype
    num_envs = robot_xy.shape[0]

    lookahead = _lookahead_tensor(
        lookahead_distances,
        paths=paths,
        dtype=dtype,
        device=device,
        num_envs=num_envs,
    )

    valid_mask = torch.zeros(num_envs, dtype=torch.bool, device=device)
    progress_s = torch.zeros(num_envs, dtype=dtype, device=device)
    nearest_xy_path = torch.zeros(num_envs, 2, dtype=dtype, device=device)
    lateral_error = torch.zeros(num_envs, dtype=dtype, device=device)
    signed_lateral_error = torch.zeros(num_envs, dtype=dtype, device=device)
    segment_index = torch.full((num_envs,), -1, dtype=torch.long, device=device)
    target_s = torch.zeros(num_envs, dtype=dtype, device=device)
    target_xy_path = torch.zeros(num_envs, 2, dtype=dtype, device=device)

    for env_index, path in enumerate(paths):
        projection = project_point_to_path(robot_xy[env_index], path)
        if path is None or not projection.valid:
            continue

        path_target_s = min(projection.progress_s + float(lookahead[env_index].item()), path.total_length_s)
        path_target_xy = interpolate_path_xy(path, path_target_s)

        valid_mask[env_index] = True
        progress_s[env_index] = projection.progress_s
        nearest_xy_path[env_index] = torch.tensor(projection.nearest_xy_path, dtype=dtype, device=device)
        lateral_error[env_index] = projection.lateral_error
        signed_lateral_error[env_index] = projection.signed_lateral_error
        segment_index[env_index] = projection.segment_index
        target_s[env_index] = path_target_s
        target_xy_path[env_index] = torch.tensor(path_target_xy, dtype=dtype, device=device)

    return PathTrackingTargets(
        valid_mask=valid_mask,
        progress_s=progress_s,
        nearest_xy_path=nearest_xy_path,
        lateral_error=lateral_error,
        signed_lateral_error=signed_lateral_error,
        segment_index=segment_index,
        target_s=target_s,
        target_xy_path=target_xy_path,
    )


def compute_stateful_path_tracking_targets(
    robot_xy_path: torch.Tensor,
    paths_or_caches: Sequence[WaypointPathRecord | TrackingPathCache | None],
    *,
    previous_progress_s: torch.Tensor | Sequence[float] | None = None,
    previous_target_s: torch.Tensor | Sequence[float] | None = None,
    cfg: PathTrackingCfg | None = None,
) -> StatefulPathTrackingTargets:
    """Compute stateful path tracking targets with windowed projection and adaptive lookahead."""
    robot_xy = torch.as_tensor(robot_xy_path)
    if robot_xy.ndim != 2 or robot_xy.shape[1] != 2:
        raise ValueError(f"robot_xy_path must have shape [N, 2], got {tuple(robot_xy.shape)}.")
    if len(paths_or_caches) != robot_xy.shape[0]:
        raise ValueError(
            f"paths_or_caches length must match robot_xy_path rows: {len(paths_or_caches)} vs {robot_xy.shape[0]}."
        )

    tracking_cfg = cfg or PathTrackingCfg()
    device = robot_xy.device
    dtype = robot_xy.dtype
    num_envs = robot_xy.shape[0]
    previous_progress = _optional_1d_tensor(previous_progress_s, num_envs=num_envs, dtype=dtype, device=device)
    previous_target = _optional_1d_tensor(previous_target_s, num_envs=num_envs, dtype=dtype, device=device)

    valid_mask = torch.zeros(num_envs, dtype=torch.bool, device=device)
    progress_s = torch.zeros(num_envs, dtype=dtype, device=device)
    nearest_xy_path = torch.zeros(num_envs, 2, dtype=dtype, device=device)
    lateral_error = torch.zeros(num_envs, dtype=dtype, device=device)
    signed_lateral_error = torch.zeros(num_envs, dtype=dtype, device=device)
    segment_index = torch.full((num_envs,), -1, dtype=torch.long, device=device)
    lookahead_distance = torch.zeros(num_envs, dtype=dtype, device=device)
    target_s = torch.zeros(num_envs, dtype=dtype, device=device)
    target_xy_path = torch.zeros(num_envs, 2, dtype=dtype, device=device)
    target_tangent_xy_path = torch.zeros(num_envs, 2, dtype=dtype, device=device)

    for env_index, path_or_cache in enumerate(paths_or_caches):
        cache = _cache_for_tracking_item(path_or_cache, tracking_cfg, dtype=dtype, device=device)
        if cache is None:
            continue

        prev_progress_value = None if previous_progress is None else float(previous_progress[env_index].item())
        projection = project_point_to_tracking_cache(
            robot_xy[env_index],
            cache,
            previous_progress_s=prev_progress_value,
            cfg=tracking_cfg,
        )
        if not projection.valid:
            continue

        adaptive_lookahead = _adaptive_lookahead(cache, projection.progress_s, tracking_cfg)
        raw_target_s = min(projection.progress_s + adaptive_lookahead, cache.total_length_s)
        smoothed_target_s = raw_target_s
        if previous_target is not None:
            previous_target_value = float(previous_target[env_index].item())
            alpha = tracking_cfg.target_smoothing_alpha
            smoothed_target_s = alpha * raw_target_s + (1.0 - alpha) * previous_target_value
            smoothed_target_s = max(projection.progress_s, min(smoothed_target_s, cache.total_length_s))

        target_xy = interpolate_cache_xy(cache, smoothed_target_s)
        target_tangent = interpolate_cache_tangent(cache, smoothed_target_s)

        valid_mask[env_index] = True
        progress_s[env_index] = projection.progress_s
        nearest_xy_path[env_index] = torch.tensor(projection.nearest_xy_path, dtype=dtype, device=device)
        lateral_error[env_index] = projection.lateral_error
        signed_lateral_error[env_index] = projection.signed_lateral_error
        segment_index[env_index] = projection.segment_index
        lookahead_distance[env_index] = adaptive_lookahead
        target_s[env_index] = smoothed_target_s
        target_xy_path[env_index] = torch.tensor(target_xy, dtype=dtype, device=device)
        target_tangent_xy_path[env_index] = torch.tensor(target_tangent, dtype=dtype, device=device)

    return StatefulPathTrackingTargets(
        valid_mask=valid_mask,
        progress_s=progress_s,
        nearest_xy_path=nearest_xy_path,
        lateral_error=lateral_error,
        signed_lateral_error=signed_lateral_error,
        segment_index=segment_index,
        lookahead_distance=lookahead_distance,
        target_s=target_s,
        target_xy_path=target_xy_path,
        target_tangent_xy_path=target_tangent_xy_path,
    )


def _invalid_projection() -> PathProjection:
    return PathProjection(
        valid=False,
        progress_s=0.0,
        nearest_xy_path=(0.0, 0.0),
        lateral_error=0.0,
        signed_lateral_error=0.0,
        segment_index=-1,
    )


def _project_point_to_sampled_polyline(
    point_xy: torch.Tensor | Sequence[float],
    sample_xy_path: torch.Tensor,
    sample_s: torch.Tensor,
    *,
    search_min_s: float | None = None,
    search_max_s: float | None = None,
) -> PathProjection:
    px, py = _xy_pair(point_xy, "point_xy")
    samples = torch.as_tensor(sample_xy_path, dtype=torch.float64)
    arc_s = torch.as_tensor(sample_s, dtype=torch.float64)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise ValueError(f"sample_xy_path must have shape [N, 2], got {tuple(samples.shape)}.")
    if arc_s.ndim != 1 or arc_s.shape[0] != samples.shape[0]:
        raise ValueError("sample_s must be a 1-D tensor with the same length as sample_xy_path.")

    best_dist_sq = math.inf
    best_progress_s = 0.0
    best_nearest_xy = (0.0, 0.0)
    best_signed_lateral = 0.0
    best_segment_index = -1

    for segment_index in range(samples.shape[0] - 1):
        start_s = float(arc_s[segment_index].item())
        end_s = float(arc_s[segment_index + 1].item())
        if search_min_s is not None and end_s < search_min_s:
            continue
        if search_max_s is not None and start_s > search_max_s:
            continue

        sx = float(samples[segment_index, 0].item())
        sy = float(samples[segment_index, 1].item())
        ex = float(samples[segment_index + 1, 0].item())
        ey = float(samples[segment_index + 1, 1].item())
        dx = ex - sx
        dy = ey - sy
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq <= _EPS:
            continue

        rel_x = px - sx
        rel_y = py - sy
        t = max(0.0, min(1.0, (rel_x * dx + rel_y * dy) / seg_len_sq))
        nearest_x = sx + t * dx
        nearest_y = sy + t * dy
        err_x = px - nearest_x
        err_y = py - nearest_y
        dist_sq = err_x * err_x + err_y * err_y

        if dist_sq < best_dist_sq:
            seg_len = math.sqrt(seg_len_sq)
            cross = dx * err_y - dy * err_x
            best_dist_sq = dist_sq
            best_progress_s = start_s + t * (end_s - start_s)
            best_nearest_xy = (nearest_x, nearest_y)
            best_signed_lateral = cross / seg_len
            best_segment_index = segment_index

    if best_segment_index < 0:
        return _invalid_projection()
    return PathProjection(
        valid=True,
        progress_s=best_progress_s,
        nearest_xy_path=best_nearest_xy,
        lateral_error=math.sqrt(best_dist_sq),
        signed_lateral_error=best_signed_lateral,
        segment_index=best_segment_index,
    )


def _lookahead_tensor(
    lookahead_distances: torch.Tensor | Sequence[float] | None,
    *,
    paths: Sequence[WaypointPathRecord | None],
    dtype: torch.dtype,
    device: torch.device,
    num_envs: int,
) -> torch.Tensor:
    if lookahead_distances is not None:
        values = torch.as_tensor(lookahead_distances, dtype=dtype, device=device)
        if values.ndim != 1 or values.shape[0] != num_envs:
            raise ValueError(f"lookahead_distances must have shape [{num_envs}], got {tuple(values.shape)}.")
        return values

    return torch.tensor(
        [0.0 if path is None else float(path.default_lookahead_distance) for path in paths],
        dtype=dtype,
        device=device,
    )


def _adaptive_lookahead(cache: TrackingPathCache, progress_s: float, cfg: PathTrackingCfg) -> float:
    curvature = interpolate_cache_curvature(cache, progress_s)
    base = cache.default_lookahead_distance
    lookahead = base / (1.0 + cfg.curvature_lookahead_gain * max(curvature, 0.0))
    return max(cfg.min_lookahead, min(cfg.max_lookahead, lookahead, cache.total_length_s))


def _cache_for_tracking_item(
    item: WaypointPathRecord | TrackingPathCache | None,
    cfg: PathTrackingCfg,
    *,
    dtype: torch.dtype,
    device: torch.device,
) -> TrackingPathCache | None:
    if item is None:
        return None
    if isinstance(item, TrackingPathCache):
        return item
    return build_tracking_path_cache(item, cfg, dtype=dtype, device=device)


def _optional_1d_tensor(
    value: torch.Tensor | Sequence[float] | None,
    *,
    num_envs: int,
    dtype: torch.dtype,
    device: torch.device,
) -> torch.Tensor | None:
    if value is None:
        return None
    tensor = torch.as_tensor(value, dtype=dtype, device=device)
    if tensor.ndim != 1 or tensor.shape[0] != num_envs:
        raise ValueError(f"Expected shape [{num_envs}], got {tuple(tensor.shape)}.")
    return tensor


def _interpolate_cache_tensor(sample_s: torch.Tensor, values: torch.Tensor, arc_length_s: float) -> tuple[float, ...]:
    arc = torch.as_tensor(sample_s, dtype=torch.float64)
    data = torch.as_tensor(values, dtype=torch.float64)
    if arc.ndim != 1 or data.ndim != 2 or data.shape[0] != arc.shape[0]:
        raise ValueError("sample_s must be [N] and values must be [N, D].")
    target_s = max(0.0, min(float(arc_length_s), float(arc[-1].item())))
    if target_s <= float(arc[0].item()):
        return tuple(float(value.item()) for value in data[0])
    if target_s >= float(arc[-1].item()):
        return tuple(float(value.item()) for value in data[-1])

    for index in range(arc.shape[0] - 1):
        start_s = float(arc[index].item())
        end_s = float(arc[index + 1].item())
        if target_s > end_s:
            continue
        if end_s <= start_s + _EPS:
            return tuple(float(value.item()) for value in data[index + 1])
        ratio = (target_s - start_s) / (end_s - start_s)
        interpolated = data[index] + ratio * (data[index + 1] - data[index])
        return tuple(float(value.item()) for value in interpolated)

    return tuple(float(value.item()) for value in data[-1])


def _xy_pair(value: torch.Tensor | Sequence[float], name: str) -> tuple[float, float]:
    tensor = torch.as_tensor(value, dtype=torch.float64)
    if tensor.shape != (2,):
        raise ValueError(f"{name} must have shape [2], got {tuple(tensor.shape)}.")
    return float(tensor[0].item()), float(tensor[1].item())


__all__ = [
    "PathTrackingCfg",
    "PathProjection",
    "PathTrackingTargets",
    "StatefulPathTrackingTargets",
    "TrackingPathCache",
    "build_tracking_path_cache",
    "compute_path_tracking_targets",
    "compute_stateful_path_tracking_targets",
    "estimate_path_curvature",
    "estimate_path_tangents",
    "interpolate_cache_curvature",
    "interpolate_cache_tangent",
    "interpolate_cache_xy",
    "interpolate_path_xy",
    "project_point_to_path",
    "project_point_to_path_windowed",
    "project_point_to_tracking_cache",
    "sample_path_by_spacing",
]
