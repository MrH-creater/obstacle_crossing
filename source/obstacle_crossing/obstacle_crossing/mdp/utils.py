from __future__ import annotations

from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def resolve_assignment_view(env: ManagerBasedRLEnv):
    raise NotImplementedError("TODO: resolve the EnvTerrainAssignmentView instance from the environment.")


def get_env_terrain_ids(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> torch.Tensor:
    raise NotImplementedError("TODO: map env ids to stable terrain ids.")


def get_env_terrain_keys(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> list[str]:
    raise NotImplementedError("TODO: map env ids to terrain registry keys.")


def get_env_command_profile_keys(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> list[str]:
    raise NotImplementedError("TODO: map env ids to command profile keys.")


def get_env_roles(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> list[str]:
    raise NotImplementedError("TODO: map env ids to single_train / sequence_train / eval roles.")


def group_env_ids_by_terrain(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: group env ids by terrain key.")


def group_env_ids_by_role(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: group env ids by role.")
