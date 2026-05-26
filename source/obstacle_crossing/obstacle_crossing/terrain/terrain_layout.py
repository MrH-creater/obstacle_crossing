from __future__ import annotations

import math
import random
from dataclasses import dataclass

import torch

from .terrain_registry import ObstacleTerrainRegistry
from .terrain_specs import ContinuousSequenceSamplingCfg, ObstacleEnvRole, ObstacleTerrainSpec


@dataclass
class ObstacleTerrainLayout:
    """Represents the terrain composition assigned to a terrain grid.

    `terrain_ids` is padded with `-1` and has shape:
        (num_rows, num_cols, max_sequence_length)

    For single-terrain layouts, every cell has `sequence_length == 1`.
    For sequence layouts, each cell stores the full sorted sequence of terrain ids.
    """

    role: ObstacleEnvRole
    terrain_ids: torch.Tensor
    terrain_keys: list[list[tuple[str, ...]]]
    command_profile_keys: list[list[tuple[str, ...]]]
    sequence_lengths: torch.Tensor

    def __post_init__(self) -> None:
        if self.terrain_ids.ndim != 3:
            raise ValueError(
                f"terrain_ids must have shape (rows, cols, max_sequence_length), got {tuple(self.terrain_ids.shape)}."
            )
        if self.sequence_lengths.ndim != 2:
            raise ValueError(
                f"sequence_lengths must have shape (rows, cols), got {tuple(self.sequence_lengths.shape)}."
            )
        if self.terrain_ids.shape[:2] != self.sequence_lengths.shape:
            raise ValueError(
                "terrain_ids and sequence_lengths must agree on (rows, cols): "
                f"{tuple(self.terrain_ids.shape[:2])} vs {tuple(self.sequence_lengths.shape)}."
            )
        if len(self.terrain_keys) != self.sequence_lengths.shape[0]:
            raise ValueError("terrain_keys row count must match sequence_lengths rows.")
        if len(self.command_profile_keys) != self.sequence_lengths.shape[0]:
            raise ValueError("command_profile_keys row count must match sequence_lengths rows.")
        for row_idx in range(self.sequence_lengths.shape[0]):
            if len(self.terrain_keys[row_idx]) != self.sequence_lengths.shape[1]:
                raise ValueError("terrain_keys column count must match sequence_lengths cols.")
            if len(self.command_profile_keys[row_idx]) != self.sequence_lengths.shape[1]:
                raise ValueError("command_profile_keys column count must match sequence_lengths cols.")

    @property
    def num_rows(self) -> int:
        return int(self.sequence_lengths.shape[0])

    @property
    def num_cols(self) -> int:
        return int(self.sequence_lengths.shape[1])

    @property
    def max_sequence_length(self) -> int:
        return int(self.terrain_ids.shape[2])

    @property
    def num_tiles(self) -> int:
        return self.num_rows * self.num_cols


class ObstacleTerrainLayoutBuilder:
    """Builds terrain-grid layouts from a registry.

    Implemented semantics:
    - single-terrain layouts sample with replacement from `single_train_specs()`
    - sequence-train layouts sample uniformly over lengths in the currently active stage target range
    - terrain sampling inside one sequence is without replacement
    - sampled terrains are sorted by terrain_id before emission
    - sequence_eval is intentionally NOT part of this training-time mixed layout
    """

    def build_single_terrain_layout(
        self,
        registry: ObstacleTerrainRegistry,
        num_rows: int,
        num_cols: int,
        seed: int = 0,
    ) -> ObstacleTerrainLayout:
        specs = registry.single_train_specs()
        if not specs:
            raise ValueError("No terrains available for single-train layout.")

        rng = random.Random(seed)
        weights = [spec.weight for spec in specs]
        terrain_ids = torch.full((num_rows, num_cols, 1), -1, dtype=torch.long)
        sequence_lengths = torch.ones((num_rows, num_cols), dtype=torch.long)
        terrain_keys: list[list[tuple[str, ...]]] = []
        command_profile_keys: list[list[tuple[str, ...]]] = []

        for row_idx in range(num_rows):
            terrain_key_row: list[tuple[str, ...]] = []
            command_profile_row: list[tuple[str, ...]] = []
            for col_idx in range(num_cols):
                spec = rng.choices(specs, weights=weights, k=1)[0]
                terrain_ids[row_idx, col_idx, 0] = spec.terrain_id
                terrain_key_row.append((spec.key,))
                command_profile_row.append((spec.command_profile_key,))
            terrain_keys.append(terrain_key_row)
            command_profile_keys.append(command_profile_row)

        return ObstacleTerrainLayout(
            role="single_train",
            terrain_ids=terrain_ids,
            terrain_keys=terrain_keys,
            command_profile_keys=command_profile_keys,
            sequence_lengths=sequence_lengths,
        )

    def build_sequence_layout(
        self,
        registry: ObstacleTerrainRegistry,
        num_rows: int,
        num_cols: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
        role: ObstacleEnvRole,
        iteration: int = 0,
        seed: int = 0,
        use_holdout_specs: bool = False,
    ) -> ObstacleTerrainLayout:
        if role not in ("sequence_train", "holdout_eval"):
            raise ValueError(
                f"build_sequence_layout only supports sequence_train / holdout_eval here, got '{role}'."
            )

        rng = random.Random(seed)
        specs = self._sequence_candidate_specs(registry, role, use_holdout_specs)
        self._validate_sequence_candidate_pool(specs, sampling_cfg, role)

        stage_max_sequence_length = self._current_stage_max_sequence_length(iteration, sampling_cfg)
        effective_max_sequence_length = min(stage_max_sequence_length, len(specs), sampling_cfg.max_sequence_length)
        terrain_ids = torch.full((num_rows, num_cols, effective_max_sequence_length), -1, dtype=torch.long)
        sequence_lengths = torch.zeros((num_rows, num_cols), dtype=torch.long)
        terrain_keys: list[list[tuple[str, ...]]] = []
        command_profile_keys: list[list[tuple[str, ...]]] = []

        for row_idx in range(num_rows):
            terrain_key_row: list[tuple[str, ...]] = []
            command_profile_row: list[tuple[str, ...]] = []
            for col_idx in range(num_cols):
                sequence_specs = self._sample_sequence_specs(rng, specs, sampling_cfg, effective_max_sequence_length)
                sequence_lengths[row_idx, col_idx] = len(sequence_specs)
                for seq_idx, spec in enumerate(sequence_specs):
                    terrain_ids[row_idx, col_idx, seq_idx] = spec.terrain_id
                terrain_key_row.append(tuple(spec.key for spec in sequence_specs))
                command_profile_row.append(tuple(spec.command_profile_key for spec in sequence_specs))
            terrain_keys.append(terrain_key_row)
            command_profile_keys.append(command_profile_row)

        return ObstacleTerrainLayout(
            role=role,
            terrain_ids=terrain_ids,
            terrain_keys=terrain_keys,
            command_profile_keys=command_profile_keys,
            sequence_lengths=sequence_lengths,
        )

    def sample_sequence_keys(
        self,
        registry: ObstacleTerrainRegistry,
        sampling_cfg: ContinuousSequenceSamplingCfg,
        iteration: int = 0,
        use_holdout_specs: bool = False,
        seed: int | None = None,
    ) -> tuple[str, ...]:
        rng = random.Random(seed)
        role: ObstacleEnvRole = "holdout_eval" if use_holdout_specs else "sequence_train"
        specs = self._sequence_candidate_specs(registry, role, use_holdout_specs)
        self._validate_sequence_candidate_pool(specs, sampling_cfg, role)
        stage_max_sequence_length = self._current_stage_max_sequence_length(iteration, sampling_cfg)
        effective_max_sequence_length = min(stage_max_sequence_length, len(specs), sampling_cfg.max_sequence_length)
        sequence_specs = self._sample_sequence_specs(rng, specs, sampling_cfg, effective_max_sequence_length)
        return tuple(spec.key for spec in sequence_specs)

    def build_mixed_layout(
        self,
        registry: ObstacleTerrainRegistry,
        num_rows: int,
        num_cols: int,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
        seed: int = 0,
    ) -> dict[str, ObstacleTerrainLayout]:
        total_tiles = num_rows * num_cols
        role_ratios = self._role_ratios(iteration, sampling_cfg)
        role_counts = self._role_counts(total_tiles, role_ratios, sampling_cfg)

        layouts: dict[str, ObstacleTerrainLayout] = {}
        role_seeds = {
            "single_train": seed + 11,
            "sequence_train": seed + 23,
            "holdout_eval": seed + 53,
        }

        single_count = role_counts["single_train"]
        single_shape = self._shape_for_tile_count(single_count)
        layouts["single_train"] = self.build_single_terrain_layout(
            registry=registry,
            num_rows=single_shape[0],
            num_cols=single_shape[1],
            seed=role_seeds["single_train"],
        )

        sequence_train_count = role_counts["sequence_train"]
        sequence_train_shape = self._shape_for_tile_count(sequence_train_count)
        layouts["sequence_train"] = self.build_sequence_layout(
            registry=registry,
            num_rows=sequence_train_shape[0],
            num_cols=sequence_train_shape[1],
            sampling_cfg=sampling_cfg,
            role="sequence_train",
            iteration=iteration,
            seed=role_seeds["sequence_train"],
        )

        holdout_count = role_counts["holdout_eval"]
        holdout_shape = self._shape_for_tile_count(holdout_count)
        layouts["holdout_eval"] = self.build_sequence_layout(
            registry=registry,
            num_rows=holdout_shape[0],
            num_cols=holdout_shape[1],
            sampling_cfg=sampling_cfg,
            role="holdout_eval",
            iteration=iteration,
            seed=role_seeds["holdout_eval"],
            use_holdout_specs=True,
        )
        return layouts

    def _sequence_candidate_specs(
        self,
        registry: ObstacleTerrainRegistry,
        role: ObstacleEnvRole,
        use_holdout_specs: bool,
    ) -> list[ObstacleTerrainSpec]:
        if role == "holdout_eval" or use_holdout_specs:
            return registry.future_benchmark_specs()
        if role == "sequence_train":
            return registry.sequence_train_specs()
        raise KeyError(f"Unsupported role '{role}' for sequence candidate selection.")

    def _validate_sequence_candidate_pool(
        self,
        specs: list[ObstacleTerrainSpec],
        sampling_cfg: ContinuousSequenceSamplingCfg,
        role: ObstacleEnvRole,
    ) -> None:
        if not specs:
            raise ValueError(f"No terrains available for role '{role}'.")
        effective_max_len = min(sampling_cfg.max_sequence_length, len(specs))
        if effective_max_len < sampling_cfg.min_sequence_length:
            raise ValueError(
                f"Role '{role}' has only {len(specs)} candidate terrains, which is smaller than "
                f"min_sequence_length={sampling_cfg.min_sequence_length}."
            )

    def _sample_sequence_specs(
        self,
        rng: random.Random,
        specs: list[ObstacleTerrainSpec],
        sampling_cfg: ContinuousSequenceSamplingCfg,
        effective_max_sequence_length: int,
    ) -> tuple[ObstacleTerrainSpec, ...]:
        seq_length = rng.randint(sampling_cfg.min_sequence_length, effective_max_sequence_length)
        sampled_specs = rng.sample(specs, k=seq_length)
        sampled_specs.sort(key=lambda spec: spec.terrain_id)
        return tuple(sampled_specs)

    def _current_stage_max_sequence_length(
        self,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
    ) -> int:
        if iteration < sampling_cfg.sequence_train_start_iteration:
            return sampling_cfg.sequence_length_stage_targets[0]
        progress_iteration = iteration - sampling_cfg.sequence_train_start_iteration
        stage_index = min(
            progress_iteration // sampling_cfg.sequence_length_stage_iterations,
            len(sampling_cfg.sequence_length_stage_targets) - 1,
        )
        return sampling_cfg.sequence_length_stage_targets[int(stage_index)]

    def _role_ratios(
        self,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
    ) -> dict[str, float]:
        if iteration < sampling_cfg.sequence_train_start_iteration:
            return {
                "single_train": 1.0,
                "sequence_train": 0.0,
                "holdout_eval": 0.0,
            }

        progress = self._ramp_progress(
            iteration=iteration,
            start_iteration=sampling_cfg.sequence_train_start_iteration,
            ramp_iterations=sampling_cfg.sequence_train_ratio_ramp_iterations,
        )
        sequence_train_ratio = self._lerp(
            sampling_cfg.sequence_train_env_ratio_initial,
            sampling_cfg.sequence_train_env_ratio_final,
            progress,
        )
        single_train_ratio = sampling_cfg.single_train_env_ratio - sequence_train_ratio
        if single_train_ratio < 0.0:
            raise ValueError(
                "Configured sequence_train ratio exceeds the available single_train_env_ratio budget."
            )

        return {
            "single_train": single_train_ratio,
            "sequence_train": sequence_train_ratio,
            "holdout_eval": 0.0,
        }

    def _role_counts(
        self,
        total_tiles: int,
        role_ratios: dict[str, float],
        sampling_cfg: ContinuousSequenceSamplingCfg,
    ) -> dict[str, int]:
        role_names = ["single_train", "sequence_train", "holdout_eval"]
        raw_counts = {role: total_tiles * role_ratios[role] for role in role_names}
        counts = {role: int(math.floor(raw_counts[role])) for role in role_names}

        if self._should_enforce_validation_minimums(total_tiles, sampling_cfg):
            counts = self._apply_minimum_validation_tiles(counts, role_ratios)

        remainder = total_tiles - sum(counts.values())
        if remainder > 0:
            sorted_roles = sorted(
                role_names,
                key=lambda role: (raw_counts[role] - counts[role]),
                reverse=True,
            )
            for role in sorted_roles:
                if remainder <= 0:
                    break
                counts[role] += 1
                remainder -= 1
        elif remainder < 0:
            sorted_roles = sorted(
                [role for role in role_names if role != "single_train"],
                key=lambda role: (counts[role] - raw_counts[role]),
                reverse=True,
            )
            for role in sorted_roles:
                while remainder < 0 and counts[role] > 0:
                    counts[role] -= 1
                    remainder += 1
            while remainder < 0 and counts["single_train"] > 0:
                counts["single_train"] -= 1
                remainder += 1
            if remainder < 0:
                raise ValueError("Failed to reconcile mixed-layout role counts.")
        return counts

    def _should_enforce_validation_minimums(
        self,
        total_tiles: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
    ) -> bool:
        return (
            sampling_cfg.enforce_minimum_one_tile_for_validation_roles
            and total_tiles > 0
            and total_tiles <= sampling_cfg.minimum_tile_rule_max_total_tiles
        )

    def _apply_minimum_validation_tiles(
        self,
        counts: dict[str, int],
        role_ratios: dict[str, float],
    ) -> dict[str, int]:
        adjusted = dict(counts)
        validation_roles = ("holdout_eval",)
        for role in validation_roles:
            if role_ratios.get(role, 0.0) > 0.0 and adjusted[role] == 0:
                adjusted[role] = 1
        return adjusted

    def _shape_for_tile_count(self, tile_count: int) -> tuple[int, int]:
        if tile_count <= 0:
            return (0, 0)
        return (1, tile_count)

    def _ramp_progress(self, iteration: int, start_iteration: int, ramp_iterations: int) -> float:
        if iteration <= start_iteration:
            return 0.0
        if ramp_iterations <= 0:
            return 1.0
        return min((iteration - start_iteration) / ramp_iterations, 1.0)

    def _lerp(self, start: float, end: float, alpha: float) -> float:
        return start + (end - start) * alpha
