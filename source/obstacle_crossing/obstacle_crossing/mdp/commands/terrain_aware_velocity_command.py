from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch
from isaaclab.assets import Articulation
from isaaclab.managers import CommandTerm

from obstacle_crossing.terrain.terrain_path_tracking import (
    PathTrackingCfg,
    TrackingPathCache,
    build_tracking_path_cache,
    compute_stateful_path_tracking_targets,
)
from obstacle_crossing.terrain.terrain_runtime import TerrainRuntimeContext
from obstacle_crossing.terrain.terrain_waypoints import WaypointPathRecord

from ..utils import resolve_terrain_runtime_context
from .path_velocity_math import PathVelocitySolverCfg, compute_desired_velocity_path_frame

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv

    from .commands_cfg import TerrainAwareVelocityCommandCfg


class TerrainAwareVelocityCommand(CommandTerm):
    """Velocity command generator conditioned on registry / assignment metadata.

    This class follows the waypoint path attached to each terrain assignment.
    Placement remains scene-backed through TerrainRuntimeContext; command math is
    shared with offline sequence visualization.
    """

    cfg: TerrainAwareVelocityCommandCfg

    def __init__(self, cfg: TerrainAwareVelocityCommandCfg, env: ManagerBasedEnv):
        super().__init__(cfg, env)
        self._terrain_env = env
        self.robot: Articulation = env.scene[cfg.asset_name]
        self.vel_command_b = torch.zeros(self.num_envs, 3, device=self.device)
        self.path_tracking_cfg = self._build_path_tracking_cfg()
        self.path_velocity_solver_cfg = self._build_path_velocity_solver_cfg()
        self.runtime_context: TerrainRuntimeContext | None = None
        self._tracking_cache_by_key: dict[tuple[str, str, str, float], TrackingPathCache] = {}
        self._previous_progress_s = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self._previous_target_s = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self._last_valid_mask = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
        self._last_progress_s = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self._last_lateral_error = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self._last_target_distance = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self._initialize_metrics()

    def __str__(self) -> str:
        return "TerrainAwareVelocityCommand(command_shape=(num_envs, 3))"

    @property
    def command(self) -> torch.Tensor:
        return self.vel_command_b

    def terrain_key_for_envs(self, env_ids: Sequence[int]) -> list[tuple[str, ...]]:
        return self._runtime_context().assignment_view.terrain_keys_for_envs(
            env=self._terrain_env,
            env_ids=_env_ids_cpu(env_ids),
        )

    def command_profile_for_envs(self, env_ids: Sequence[int]):
        return self._runtime_context().assignment_view.command_profiles_for_envs(
            env=self._terrain_env,
            env_ids=_env_ids_cpu(env_ids),
        )

    def _resample_command(self, env_ids: Sequence[int]) -> None:
        ids = _env_ids_device(env_ids, device=self.device)
        self._previous_progress_s[ids] = 0.0
        self._previous_target_s[ids] = 0.0
        self.vel_command_b[ids] = 0.0

    def _update_command(self) -> None:
        context = self._runtime_context()
        env_ids = torch.arange(self.num_envs, dtype=torch.long, device=self.device)
        root_xy_w = self._root_xy_w()
        robot_xy_path = context.origin_provider.world_to_local_xy(env_ids, root_xy_w)
        paths = context.assignment_view.waypoint_paths_for_envs(env=self._terrain_env, env_ids=env_ids.detach().cpu())
        path_items = [self._tracking_cache_for_path(path) for path in paths]

        targets = compute_stateful_path_tracking_targets(
            robot_xy_path,
            path_items,
            previous_progress_s=self._previous_progress_s,
            previous_target_s=self._previous_target_s,
            cfg=self.path_tracking_cfg,
        )
        path_velocity = compute_desired_velocity_path_frame(
            robot_xy_path,
            targets,
            self.path_velocity_solver_cfg,
        )
        profile_speed = self._profile_speed_for_envs(paths, targets.progress_s, path_velocity.valid_mask)
        desired_vel_path = path_velocity.blended_direction_xy_path * profile_speed.unsqueeze(-1)
        desired_vel_w = self._path_vector_to_world_xy(context, env_ids, robot_xy_path, desired_vel_path)
        desired_vel_b = _world_xy_to_body_xy(desired_vel_w, self._root_yaw_w())
        if self.cfg.only_positive_lin_vel_x:
            desired_vel_b[:, 0] = torch.clamp(desired_vel_b[:, 0], min=0.0)

        self.vel_command_b.zero_()
        self.vel_command_b[:, :2] = desired_vel_b
        self.vel_command_b[~path_velocity.valid_mask] = 0.0

        self._previous_progress_s = torch.where(
            path_velocity.valid_mask,
            targets.progress_s,
            self._previous_progress_s,
        )
        self._previous_target_s = torch.where(
            path_velocity.valid_mask,
            targets.target_s,
            self._previous_target_s,
        )
        self._last_valid_mask = path_velocity.valid_mask
        self._last_progress_s = targets.progress_s
        self._last_lateral_error = targets.lateral_error
        self._last_target_distance = path_velocity.target_distance

    def _update_metrics(self) -> None:
        if not hasattr(self, "metrics"):
            return
        self.metrics["path_valid"][:] = self._last_valid_mask.to(dtype=torch.float32)
        self.metrics["path_progress_s"][:] = self._last_progress_s
        self.metrics["path_lateral_error"][:] = self._last_lateral_error
        self.metrics["path_target_distance"][:] = self._last_target_distance

    def _runtime_context(self) -> TerrainRuntimeContext:
        if self.runtime_context is None:
            self.runtime_context = resolve_terrain_runtime_context(
                self._terrain_env,
                origin_source=self.cfg.runtime_origin_source,
                validate_origin_consistency=self.cfg.validate_origin_consistency,
            )
        return self.runtime_context

    def _build_path_tracking_cfg(self) -> PathTrackingCfg:
        return PathTrackingCfg(
            sample_spacing=self.cfg.path_tracking_sample_spacing,
            backtrack_margin=self.cfg.path_tracking_backtrack_margin,
            forward_search_window=self.cfg.path_tracking_forward_search_window,
            min_lookahead=self.cfg.path_tracking_min_lookahead,
            max_lookahead=self.cfg.path_tracking_max_lookahead,
            target_smoothing_alpha=self.cfg.path_tracking_target_smoothing_alpha,
            curvature_lookahead_gain=self.cfg.path_tracking_curvature_lookahead_gain,
        )

    def _build_path_velocity_solver_cfg(self) -> PathVelocitySolverCfg:
        return PathVelocitySolverCfg(
            target_direction_weight=self.cfg.target_direction_weight,
            tangent_direction_weight=self.cfg.tangent_direction_weight,
            lateral_correction_weight=self.cfg.lateral_correction_weight,
            max_lin_speed=1.0,
            lateral_deadband=self.cfg.path_velocity_lateral_deadband,
            lateral_error_reference=self.cfg.path_velocity_lateral_error_reference,
            max_lateral_correction_scale=self.cfg.path_velocity_max_lateral_correction_scale,
        )

    def _tracking_cache_for_path(self, path: WaypointPathRecord | None) -> TrackingPathCache | None:
        if path is None:
            return None
        key = (
            path.path_id,
            str(self.device),
            str(self.vel_command_b.dtype),
            self.path_tracking_cfg.sample_spacing,
        )
        cache = self._tracking_cache_by_key.get(key)
        if cache is None:
            cache = build_tracking_path_cache(
                path,
                self.path_tracking_cfg,
                dtype=self.vel_command_b.dtype,
                device=self.device,
            )
            self._tracking_cache_by_key[key] = cache
        return cache

    def _root_xy_w(self) -> torch.Tensor:
        data = self.robot.data
        root_pos_w = _first_tensor_attr(data, "root_pos_w", "root_link_pos_w")
        if root_pos_w is None:
            raise AttributeError("Robot data must expose root_pos_w or root_link_pos_w.")
        return torch.as_tensor(root_pos_w, dtype=self.vel_command_b.dtype, device=self.device)[:, :2]

    def _root_yaw_w(self) -> torch.Tensor:
        data = self.robot.data
        root_quat_w = _first_tensor_attr(data, "root_quat_w", "root_link_quat_w")
        if root_quat_w is None:
            return torch.zeros(self.num_envs, dtype=self.vel_command_b.dtype, device=self.device)
        quat = torch.as_tensor(root_quat_w, dtype=self.vel_command_b.dtype, device=self.device)
        return _yaw_from_quat_wxyz(quat)

    def _path_vector_to_world_xy(
        self,
        context: TerrainRuntimeContext,
        env_ids: torch.Tensor,
        robot_xy_path: torch.Tensor,
        vector_xy_path: torch.Tensor,
    ) -> torch.Tensor:
        world_start = context.origin_provider.local_to_world_xy(env_ids, robot_xy_path)
        world_end = context.origin_provider.local_to_world_xy(env_ids, robot_xy_path + vector_xy_path)
        return world_end - world_start

    def _profile_speed_for_envs(
        self,
        paths: Sequence[WaypointPathRecord | None],
        progress_s: torch.Tensor,
        valid_mask: torch.Tensor,
    ) -> torch.Tensor:
        speeds = torch.zeros(self.num_envs, dtype=self.vel_command_b.dtype, device=self.device)
        max_speed = float(self.cfg.path_velocity_max_lin_speed)
        for env_index, path in enumerate(paths):
            if path is None or not bool(valid_mask[env_index].item()):
                continue
            profile_key = _profile_key_for_progress(path, float(progress_s[env_index].item()))
            profile = self.cfg.profiles.get(profile_key) or self.cfg.profiles.get("default")
            if profile is None:
                speeds[env_index] = max_speed
                continue
            profile_mid_speed = 0.5 * (float(profile.lin_vel_x[0]) + float(profile.lin_vel_x[1]))
            speeds[env_index] = min(max_speed, profile_mid_speed)
        return speeds

    def _initialize_metrics(self) -> None:
        if not hasattr(self, "metrics"):
            return
        self.metrics["path_valid"] = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self.metrics["path_progress_s"] = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self.metrics["path_lateral_error"] = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self.metrics["path_target_distance"] = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)


def _profile_key_for_progress(path: WaypointPathRecord, progress_s: float) -> str:
    for profile_range in path.profile_ranges:
        if profile_range.start_s - 1.0e-6 <= progress_s <= profile_range.end_s + 1.0e-6:
            return profile_range.command_profile_key
    if path.profile_ranges:
        return path.profile_ranges[-1].command_profile_key
    return "default"


def _world_xy_to_body_xy(world_xy: torch.Tensor, yaw_w: torch.Tensor) -> torch.Tensor:
    cos_yaw = torch.cos(yaw_w)
    sin_yaw = torch.sin(yaw_w)
    body_xy = torch.zeros_like(world_xy)
    body_xy[:, 0] = cos_yaw * world_xy[:, 0] + sin_yaw * world_xy[:, 1]
    body_xy[:, 1] = -sin_yaw * world_xy[:, 0] + cos_yaw * world_xy[:, 1]
    return body_xy


def _yaw_from_quat_wxyz(quat_wxyz: torch.Tensor) -> torch.Tensor:
    if quat_wxyz.ndim != 2 or quat_wxyz.shape[1] != 4:
        raise ValueError(f"Expected root quaternion shape [N, 4], got {tuple(quat_wxyz.shape)}.")
    w = quat_wxyz[:, 0]
    x = quat_wxyz[:, 1]
    y = quat_wxyz[:, 2]
    z = quat_wxyz[:, 3]
    return torch.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _first_tensor_attr(owner, *names: str):
    for name in names:
        value = getattr(owner, name, None)
        if value is not None:
            return value
    return None


def _env_ids_cpu(env_ids: Sequence[int] | torch.Tensor) -> torch.Tensor:
    if isinstance(env_ids, torch.Tensor):
        return env_ids.detach().cpu().to(dtype=torch.long)
    return torch.as_tensor(list(env_ids), dtype=torch.long)


def _env_ids_device(env_ids: Sequence[int] | torch.Tensor, *, device: torch.device) -> torch.Tensor:
    if isinstance(env_ids, torch.Tensor):
        return env_ids.detach().to(device=device, dtype=torch.long)
    return torch.as_tensor(list(env_ids), dtype=torch.long, device=device)
