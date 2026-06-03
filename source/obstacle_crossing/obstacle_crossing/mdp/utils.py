from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

import torch

from obstacle_crossing.terrain.terrain_assignment import EnvTerrainAssignmentView
from obstacle_crossing.terrain.terrain_runtime import (
    RuntimeOriginSource,
    TerrainRuntimeContext,
    build_scene_runtime_context,
)

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def resolve_assignment_view(env: ManagerBasedRLEnv) -> EnvTerrainAssignmentView:
    """Resolve the terrain assignment view attached to an env or runtime context."""
    runtime_context = _first_existing_attr(
        env,
        "terrain_runtime_context",
        "obstacle_terrain_runtime_context",
    )
    if isinstance(runtime_context, TerrainRuntimeContext):
        return runtime_context.assignment_view

    for owner in _env_lookup_chain(env):
        assignment_view = _first_existing_attr(
            owner,
            "terrain_assignment_view",
            "obstacle_terrain_assignment_view",
            "assignment_view",
        )
        if isinstance(assignment_view, EnvTerrainAssignmentView):
            return assignment_view

    raise AttributeError(
        "No EnvTerrainAssignmentView found. Attach one as env.terrain_assignment_view or "
        "env.terrain_runtime_context.assignment_view before using terrain-aware commands."
    )


def resolve_terrain_runtime_context(
    env: ManagerBasedRLEnv,
    *,
    origin_source: RuntimeOriginSource = "auto",
    validate_origin_consistency: bool = True,
) -> TerrainRuntimeContext:
    """Resolve or build the terrain runtime context used by terrain-aware command logic."""
    for owner in _env_lookup_chain(env):
        runtime_context = _first_existing_attr(
            owner,
            "terrain_runtime_context",
            "obstacle_terrain_runtime_context",
        )
        if isinstance(runtime_context, TerrainRuntimeContext):
            return runtime_context

    assignment_view = resolve_assignment_view(env)
    runtime_context = build_scene_runtime_context(
        env=env,
        assignment_view=assignment_view,
        origin_source=origin_source,
        validate_origin_consistency=validate_origin_consistency,
    )
    _attach_attr_if_possible(env, "terrain_runtime_context", runtime_context)
    return runtime_context


def get_env_terrain_ids(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> torch.Tensor:
    assignment_view = resolve_assignment_view(env)
    return assignment_view.terrain_ids_for_envs(env=env, env_ids=_optional_env_ids_cpu(env_ids))


def get_env_terrain_keys(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> list[tuple[str, ...]]:
    assignment_view = resolve_assignment_view(env)
    return assignment_view.terrain_keys_for_envs(env=env, env_ids=_optional_env_ids_cpu(env_ids))


def get_env_command_profile_keys(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> list[tuple[str, ...]]:
    assignment_view = resolve_assignment_view(env)
    return assignment_view.command_profiles_for_envs(env=env, env_ids=_optional_env_ids_cpu(env_ids))


def get_env_roles(env: ManagerBasedRLEnv, env_ids: torch.Tensor | None = None) -> list[str]:
    assignment_view = resolve_assignment_view(env)
    return assignment_view.roles_for_envs(env=env, env_ids=_optional_env_ids_cpu(env_ids))


def group_env_ids_by_terrain(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    return resolve_assignment_view(env).group_env_ids_by_terrain(env=env)


def group_env_ids_by_role(env: ManagerBasedRLEnv) -> dict[str, torch.Tensor]:
    return resolve_assignment_view(env).group_env_ids_by_role(env=env)


def _env_lookup_chain(env: Any) -> tuple[Any, ...]:
    candidates = [env]
    unwrapped = getattr(env, "unwrapped", None)
    if unwrapped is not None and unwrapped is not env:
        candidates.append(unwrapped)
    scene = getattr(env, "scene", None)
    if scene is not None:
        candidates.append(scene)
    return tuple(candidates)


def _first_existing_attr(owner: Any, *names: str) -> Any | None:
    if owner is None:
        return None
    for name in names:
        if hasattr(owner, name):
            value = getattr(owner, name)
            if value is not None:
                return value
    return None


def _attach_attr_if_possible(owner: Any, name: str, value: Any) -> None:
    try:
        setattr(owner, name, value)
    except Exception:
        return


def _optional_env_ids_cpu(env_ids: torch.Tensor | None) -> torch.Tensor | None:
    if env_ids is None:
        return None
    return env_ids.detach().cpu().to(dtype=torch.long)
