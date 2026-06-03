from __future__ import annotations

from dataclasses import MISSING

from isaaclab.managers import CommandTermCfg
from isaaclab.utils import configclass

from ...terrain.terrain_specs import VelocityCommandProfile
from .terrain_aware_velocity_command import TerrainAwareVelocityCommand


@configclass
class TerrainAwareVelocityCommandCfg(CommandTermCfg):
    """Registry-driven velocity command config.

    This keeps per-terrain command profiles separate from the terrain generator
    internals so that obstacle crossing can switch between single-terrain and
    continuous-sequence env pools.
    """

    class_type: type = TerrainAwareVelocityCommand

    asset_name: str = MISSING
    profile_by_terrain_key: dict[str, str] = MISSING
    profiles: dict[str, VelocityCommandProfile] = MISSING
    target_dis_threshold: float = 0.2
    only_positive_lin_vel_x: bool = True
    lin_vel_threshold: float = 0.15
    ang_vel_threshold: float = 0.15
    rel_standing_envs: float = 0.0
    runtime_origin_source: str = "auto"
    validate_origin_consistency: bool = True
    path_tracking_sample_spacing: float = 0.25
    path_tracking_backtrack_margin: float = 0.5
    path_tracking_forward_search_window: float = 2.0
    path_tracking_min_lookahead: float = 0.25
    path_tracking_max_lookahead: float = 1.0
    path_tracking_target_smoothing_alpha: float = 0.3
    path_tracking_curvature_lookahead_gain: float = 1.0
    target_direction_weight: float = 1.0
    tangent_direction_weight: float = 0.65
    lateral_correction_weight: float = 0.75
    path_velocity_max_lin_speed: float = 1.0
    path_velocity_lateral_deadband: float = 0.03
    path_velocity_lateral_error_reference: float = 0.35
    path_velocity_max_lateral_correction_scale: float = 1.0
