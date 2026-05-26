from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from isaaclab.managers import SceneEntityCfg

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def compute_rewards(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: aggregate obstacle-crossing reward terms for debugging / analysis.")


def track_lin_vel_xy_exp(env: ManagerBasedRLEnv, command_name: str, std: float) -> torch.Tensor:
    raise NotImplementedError("TODO: obstacle-crossing specific linear velocity tracking reward.")


def track_ang_vel_z_exp(env: ManagerBasedRLEnv, command_name: str, std: float) -> torch.Tensor:
    raise NotImplementedError("TODO: obstacle-crossing specific angular velocity tracking reward.")


def obstacle_progress(env: ManagerBasedRLEnv) -> torch.Tensor:
    raise NotImplementedError("TODO: reward forward progress over the active obstacle or sequence.")


def volume_points_penetration(env: ManagerBasedRLEnv, sensor_cfg: SceneEntityCfg) -> torch.Tensor:
    raise NotImplementedError("TODO: terrain-specific penetration penalty wrapper.")


def feet_air_time(env: ManagerBasedRLEnv, command_name: str, sensor_cfg: SceneEntityCfg) -> torch.Tensor:
    raise NotImplementedError("TODO: obstacle-specific feet airtime reward wrapper.")


def terrain_profile_bonus(env: ManagerBasedRLEnv) -> torch.Tensor:
    raise NotImplementedError("TODO: terrain-profile-conditioned shaping term.")


def sequence_completion_bonus(env: ManagerBasedRLEnv) -> torch.Tensor:
    raise NotImplementedError("TODO: bonus for completing multi-terrain continuous validation/training sequences.")
