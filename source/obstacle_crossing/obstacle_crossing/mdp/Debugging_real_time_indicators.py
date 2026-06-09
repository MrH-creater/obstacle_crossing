from __future__ import annotations

from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def role_per_env(env: ManagerBasedRLEnv) -> torch.Tensor:
    """Placeholder for per-env runtime role ids.

    Intended behavior:
        Read the current terrain assignment attached by events and encode each
        env role as a numeric id. The first planned encoding is:
        unknown=0, single_train=1, sequence_train=2.

    Input source:
        env.terrain_assignment_view, or the assignment view carried by
        env.terrain_runtime_context.

    Output:
        A float32 tensor with shape [num_envs, 1].

    Dependencies:
        Requires the events layer to attach an EnvTerrainAssignmentView. It does
        not depend on command progress or cross-episode state.
    """
    raise NotImplementedError("TODO: implement stateless per-env role ids from terrain assignment runtime state.")


def role_distribution_summary(env: ManagerBasedRLEnv) -> dict[str, int]:
    """Placeholder for current env-count summary by role.

    Intended behavior:
        Aggregate assignment_view.group_env_ids_by_role() into a dictionary such
        as {"single_train": count, "sequence_train": count}. This is meant for
        startup/reset checks of the actual single/sequence split.

    Input source:
        env.terrain_assignment_view.group_env_ids_by_role().

    Output:
        A dictionary mapping role name to env count.

    Dependencies:
        Requires only the assignment view attached by events.
    """
    raise NotImplementedError("TODO: implement role-count summary from assignment_view.group_env_ids_by_role().")


def terrain_distribution_summary(env: ManagerBasedRLEnv) -> dict[str, int]:
    """Placeholder for current env-count summary by terrain.

    Intended behavior:
        Aggregate assignment_view.group_env_ids_by_terrain() into a dictionary
        mapping terrain key to env count. This is intended for seed/distribution
        checks and quick diagnosis of terrain sampling imbalance.

    Input source:
        env.terrain_assignment_view.group_env_ids_by_terrain().

    Output:
        A dictionary mapping terrain key to env count.

    Dependencies:
        Requires only the assignment view attached by events.
    """
    raise NotImplementedError("TODO: implement terrain-count summary from assignment_view.group_env_ids_by_terrain().")


def env_ids_on_terrain(env: ManagerBasedRLEnv, terrain_key: str) -> torch.Tensor:
    """Placeholder for locating env ids assigned to a terrain.

    Intended behavior:
        Return the env ids currently assigned to the requested terrain key. This
        supports debugging cases such as low reward or repeated termination on a
        specific terrain.

    Input source:
        env.terrain_assignment_view.group_env_ids_by_terrain().

    Output:
        A long tensor with shape [k], where k is the number of matched envs.

    Dependencies:
        Requires only the assignment view attached by events.
    """
    raise NotImplementedError("TODO: implement terrain-key to env-id lookup from assignment_view groups.")


def progress_fraction_per_env(env: ManagerBasedRLEnv) -> torch.Tensor:
    """Placeholder for per-env normalized path progress.

    Intended behavior:
        Compute progress_fraction = progress_s / path_total_length for each env,
        clamped or otherwise guarded into a useful [0, 1] diagnostic range.

    Input source:
        Future env fields written by TerrainAwareVelocityCommand, for example
        env.path_progress_s and env.path_total_length.

    Output:
        A float32 tensor with shape [num_envs, 1].

    Dependencies:
        Requires a future command-side change that exposes progress_s and
        path_total_length on env before this indicator can be implemented.
    """
    raise NotImplementedError("TODO: requires command-side progress_s/path_total_length exposure on env.")


def current_terrain_per_env(env: ManagerBasedRLEnv) -> torch.Tensor:
    """Placeholder for the terrain currently occupied by each env.

    Intended behavior:
        Determine the terrain segment currently occupied by each robot, instead
        of using only the first terrain in a sequence assignment. The planned
        implementation should compare command/path progress against assignment
        segment ranges.

    Input source:
        Future command-exposed progress state plus assignment segment_ranges_y.

    Output:
        A tensor with shape [num_envs, 1] carrying the current terrain id or a
        paired lookup key representation.

    Dependencies:
        Requires command-side progress exposure and the existing assignment view
        segment range metadata.
    """
    raise NotImplementedError("TODO: requires command progress exposure and segment-range mapping.")
