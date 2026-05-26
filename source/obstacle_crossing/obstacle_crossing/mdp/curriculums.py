from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch

from ..terrain.terrain_specs import ContinuousSequenceSamplingCfg

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def terrain_level_curriculum(env: ManagerBasedRLEnv, env_ids: Sequence[int]) -> torch.Tensor:
    raise NotImplementedError("TODO: curriculum over single-terrain difficulty / rank.")


def terrain_mix_curriculum(env: ManagerBasedRLEnv, env_ids: Sequence[int]) -> torch.Tensor:
    raise NotImplementedError("TODO: curriculum over the mixture of enabled training terrains.")


def command_profile_curriculum(env: ManagerBasedRLEnv, env_ids: Sequence[int]) -> torch.Tensor:
    raise NotImplementedError("TODO: curriculum over command profiles (straight / turning / clearance / slalom ...).")


def sequence_train_ratio_schedule(
    current_iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> dict[str, float]:
    raise NotImplementedError("TODO: compute the 10k->30k ramp that takes sequence_train from 0% to 30%.")


def sequence_length_stage(
    current_iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> int:
    raise NotImplementedError("TODO: compute the active 2->4->6 sequence-length curriculum stage.")


def should_enable_sequence_train(
    current_iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> bool:
    raise NotImplementedError("TODO: gate sequence_train after sequence_train_start_iteration.")


def should_refresh_sequence_templates(
    current_iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> bool:
    raise NotImplementedError("TODO: refresh sequence templates every configured interval (e.g. 1k iterations).")
