from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from isaaclab.managers import SceneEntityCfg

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def compute_terminations(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: aggregate obstacle-crossing termination signals.")


def terrain_out_of_bounds(env: ManagerBasedRLEnv, distance_buffer: float = 2.0) -> torch.Tensor:
    raise NotImplementedError("TODO: terminate envs that leave the active terrain or terrain sequence bounds.")


def base_contact(env: ManagerBasedRLEnv, sensor_cfg: SceneEntityCfg, threshold: float = 1.0) -> torch.Tensor:
    raise NotImplementedError("TODO: terminate on invalid base/torso contacts.")


def bad_orientation(env: ManagerBasedRLEnv, limit_angle: float = 1.0) -> torch.Tensor:
    raise NotImplementedError("TODO: terminate on excessive body orientation error.")


def root_height_below_env_origin_minimum(
    env: ManagerBasedRLEnv,
    minimum_height: float,
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    raise NotImplementedError("TODO: terminate when root height falls below the minimum threshold.")


def sequence_exhausted(env: ManagerBasedRLEnv) -> torch.Tensor:
    raise NotImplementedError("TODO: terminate after the current continuous terrain sequence is exhausted.")
