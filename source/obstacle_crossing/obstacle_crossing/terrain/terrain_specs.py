from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SequenceSamplingMode = Literal["sorted_subset"]
ObstacleEnvRole = Literal[
    "single_train",
    "sequence_train",
    "sequence_eval",
    "holdout_eval",
]


@dataclass(frozen=True)
class VelocityCommandProfile:
    """Terrain-conditioned command range definition."""

    lin_vel_x: tuple[float, float]
    lin_vel_y: tuple[float, float]
    ang_vel_z: tuple[float, float]
    rel_standing_envs: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("lin_vel_x", self.lin_vel_x),
            ("lin_vel_y", self.lin_vel_y),
            ("ang_vel_z", self.ang_vel_z),
        ):
            if len(value) != 2:
                raise ValueError(f"{name} must have exactly 2 elements, got {value}.")
            if value[0] > value[1]:
                raise ValueError(f"{name} must satisfy min <= max, got {value}.")
        if not 0.0 <= self.rel_standing_envs <= 1.0:
            raise ValueError(
                f"rel_standing_envs must be within [0, 1], got {self.rel_standing_envs}."
            )


@dataclass(frozen=True)
class ObstacleTerrainSpec:
    """Registry record for one obstacle terrain.

    `terrain_id` is the stable global identity used across training/validation.
    Keep it stable even when a terrain is temporarily excluded from training.
    """

    key: str
    terrain_id: int
    terrain_file: str
    motion_file: str | None = None
    weight: float = 1.0
    curriculum_rank: int = 0
    command_profile_key: str = "default"
    enabled_for_single_training: bool = True
    enabled_for_sequence_training: bool = True
    enabled_for_future_benchmark: bool = False
    tags: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    physics_profile_key: str = "default_walk_surface"
    collision_profile_key: str = "default"

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("key must be a non-empty string.")
        if self.terrain_id < 0:
            raise ValueError(f"terrain_id must be >= 0, got {self.terrain_id}.")
        if not self.terrain_file:
            raise ValueError(f"terrain_file must be set for terrain '{self.key}'.")
        if self.weight <= 0.0:
            raise ValueError(f"weight must be > 0 for terrain '{self.key}', got {self.weight}.")
        if self.curriculum_rank < 0:
            raise ValueError(
                f"curriculum_rank must be >= 0 for terrain '{self.key}', got {self.curriculum_rank}."
            )
        if any(not capability for capability in self.required_capabilities):
            raise ValueError(
                f"required_capabilities must not contain empty strings for terrain '{self.key}'."
            )
        if not self.physics_profile_key:
            raise ValueError(f"physics_profile_key must be set for terrain '{self.key}'.")
        if not self.collision_profile_key:
            raise ValueError(f"collision_profile_key must be set for terrain '{self.key}'.")


@dataclass(frozen=True)
class ContinuousSequenceSamplingCfg:
    """Configuration for sequence-train env generation.

    Confirmed strategy:
    - sequence_train is part of training and ramps from 0% to a target ratio
    - sequence lengths follow a 2 -> 4 -> 6 curriculum
    - sequence templates refresh periodically during training
    - sequence_eval is not part of this training pool; it belongs to a separate eval pipeline
    """

    sequence_train_start_iteration: int = 0
    sequence_train_ratio_ramp_iterations: int = 0
    sequence_train_env_ratio_initial: float = 0.0
    sequence_train_env_ratio_final: float = 0.0
    min_sequence_length: int = 2
    max_sequence_length: int = 6
    maximum_number_of_terrains: int = 10
    sequence_sampling_mode: SequenceSamplingMode = "sorted_subset"
    single_train_env_ratio: float = 1.0
    sequence_length_stage_iterations: int = 5000
    sequence_length_stage_targets: tuple[int, ...] = (2, 4, 6)
    template_refresh_interval_iterations: int = 1000
    enforce_minimum_one_tile_for_validation_roles: bool = True
    minimum_tile_rule_max_total_tiles: int = 64

    def __post_init__(self) -> None:
        if self.sequence_train_start_iteration < 0:
            raise ValueError("sequence_train_start_iteration must be >= 0.")
        if self.sequence_train_ratio_ramp_iterations < 0:
            raise ValueError("sequence_train_ratio_ramp_iterations must be >= 0.")
        if self.min_sequence_length < 1:
            raise ValueError("min_sequence_length must be >= 1.")
        if self.max_sequence_length < self.min_sequence_length:
            raise ValueError("max_sequence_length must be >= min_sequence_length.")
        if self.maximum_number_of_terrains < self.max_sequence_length:
            raise ValueError(
                "maximum_number_of_terrains must be >= max_sequence_length."
            )
        if self.sequence_length_stage_iterations <= 0:
            raise ValueError("sequence_length_stage_iterations must be > 0.")
        if self.template_refresh_interval_iterations <= 0:
            raise ValueError("template_refresh_interval_iterations must be > 0.")
        if not self.sequence_length_stage_targets:
            raise ValueError("sequence_length_stage_targets must not be empty.")
        if tuple(sorted(self.sequence_length_stage_targets)) != self.sequence_length_stage_targets:
            raise ValueError("sequence_length_stage_targets must be sorted in non-decreasing order.")
        if self.sequence_length_stage_targets[0] < self.min_sequence_length:
            raise ValueError(
                "The first sequence_length_stage_target must be >= min_sequence_length."
            )
        if self.sequence_length_stage_targets[-1] > self.max_sequence_length:
            raise ValueError(
                "The last sequence_length_stage_target must be <= max_sequence_length."
            )
        for name, value in (
            ("single_train_env_ratio", self.single_train_env_ratio),
            ("sequence_train_env_ratio_initial", self.sequence_train_env_ratio_initial),
            ("sequence_train_env_ratio_final", self.sequence_train_env_ratio_final),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {value}.")
        if self.minimum_tile_rule_max_total_tiles < 0:
            raise ValueError("minimum_tile_rule_max_total_tiles must be >= 0.")


@dataclass(frozen=True)
class SequenceEvalCfg:
    """Configuration for independent periodic sequence evaluation.

    This eval config is intentionally separate from training-time sequence sampling.
    The eval pipeline should not participate in parameter updates.
    """

    enabled: bool = True
    eval_interval_iterations: int = 1000
    fixed_benchmark_count: int = 32
    random_benchmark_count: int = 32
    min_sequence_length: int = 2
    max_sequence_length: int = 6
    maximum_number_of_terrains: int = 10
    sequence_sampling_mode: SequenceSamplingMode = "sorted_subset"
    refresh_random_benchmarks_each_eval: bool = True

    def __post_init__(self) -> None:
        if self.eval_interval_iterations <= 0:
            raise ValueError("eval_interval_iterations must be > 0.")
        if self.fixed_benchmark_count < 0:
            raise ValueError("fixed_benchmark_count must be >= 0.")
        if self.random_benchmark_count < 0:
            raise ValueError("random_benchmark_count must be >= 0.")
        if self.min_sequence_length < 1:
            raise ValueError("min_sequence_length must be >= 1.")
        if self.max_sequence_length < self.min_sequence_length:
            raise ValueError("max_sequence_length must be >= min_sequence_length.")
        if self.maximum_number_of_terrains < self.max_sequence_length:
            raise ValueError(
                "maximum_number_of_terrains must be >= max_sequence_length."
            )
