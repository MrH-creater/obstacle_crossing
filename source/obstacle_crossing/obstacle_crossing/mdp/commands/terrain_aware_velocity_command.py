from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch
from isaaclab.assets import Articulation
from isaaclab.managers import CommandTerm

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv

    from .commands_cfg import TerrainAwareVelocityCommandCfg


class TerrainAwareVelocityCommand(CommandTerm):
    """Velocity command generator conditioned on registry / assignment metadata.

    The implementation is intentionally left open for the next phase. This class
    is responsible for serving both single-terrain envs and continuous-sequence
    env pools after the configured iteration threshold.
    """

    cfg: TerrainAwareVelocityCommandCfg

    def __init__(self, cfg: TerrainAwareVelocityCommandCfg, env: ManagerBasedEnv):
        super().__init__(cfg, env)
        self.robot: Articulation = env.scene[cfg.asset_name]
        self.vel_command_b = torch.zeros(self.num_envs, 3, device=self.device)

    def __str__(self) -> str:
        return "TerrainAwareVelocityCommand(command_shape=(num_envs, 3))"

    @property
    def command(self) -> torch.Tensor:
        return self.vel_command_b

    def terrain_key_for_envs(self, env_ids: Sequence[int]) -> list[str]:
        raise NotImplementedError("TODO: fetch terrain keys from the assignment view.")

    def command_profile_for_envs(self, env_ids: Sequence[int]):
        raise NotImplementedError("TODO: fetch command profiles from terrain assignments.")

    def _resample_command(self, env_ids: Sequence[int]) -> None:
        raise NotImplementedError("TODO: sample commands conditioned on terrain role/profile.")

    def _update_command(self) -> None:
        raise NotImplementedError("TODO: update the command tensor each step.")

    def _update_metrics(self) -> None:
        raise NotImplementedError("TODO: track terrain-aware command metrics.")
