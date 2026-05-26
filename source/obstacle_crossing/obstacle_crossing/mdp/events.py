from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def initialize_terrain_registry(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError("TODO: create and attach the obstacle terrain registry to the env.")


def initialize_terrain_layout(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError("TODO: build and attach the terrain grid layout bundle for the current training stage.")


def initialize_terrain_physics_profiles(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError("TODO: create and attach terrain physics/collision profile mappings to the env.")


def apply_terrain_physics_profiles(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError(
        "TODO: apply terrain-specific physics/collision profiles to terrain prims or tiles when supported."
    )


def register_virtual_obstacles_to_sensors(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError("TODO: register virtual obstacles / terrain meshes with volume point sensors.")


def reset_env_terrain_assignments(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError("TODO: resample env roles and terrain assignments after resets or stage changes.")


def update_curriculum_stage(env: ManagerBasedRLEnv) -> None:
    raise NotImplementedError("TODO: update curriculum stage and validation pool ratios from iteration count.")
