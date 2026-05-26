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
