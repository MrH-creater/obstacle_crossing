from __future__ import annotations

from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def compute_observations(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: assemble the full observation dictionary for obstacle crossing.")


def compute_policy_observations(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: assemble sim2real-safe policy observations.")


def compute_critic_observations(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    raise NotImplementedError("TODO: assemble critic observations, including privileged terms if needed.")


def terrain_assignment_debug(env: ManagerBasedRLEnv) -> torch.Tensor:
    raise NotImplementedError("TODO: expose terrain assignment / role debug signals for observation inspection.")


def env_role_debug(env: ManagerBasedRLEnv) -> torch.Tensor:
    raise NotImplementedError("TODO: expose env role ids for single-train / sequence-train / eval pools.")
