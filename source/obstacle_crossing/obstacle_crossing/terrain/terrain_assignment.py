from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import torch

from .terrain_layout import ObstacleTerrainLayout
from .terrain_registry import ObstacleTerrainRegistry

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


@dataclass(frozen=True)
class ObstacleEnvAssignmentRecord:
    env_id: int
    role: str
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    sequence_length: int
    tile_index: int


@dataclass(frozen=True)
class ObstacleTileAssignmentRecord:
    tile_index: int
    role: str
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    sequence_length: int


class ObstacleTileAssignmentTable:
    """Flattened tile-level assignment table built from role layouts.

    This class is intentionally independent from Isaac Lab env internals so it can
    be unit-tested before being bound to a runtime environment.
    """

    def __init__(
        self,
        registry: ObstacleTerrainRegistry,
        layouts: dict[str, ObstacleTerrainLayout],
    ):
        self.registry = registry
        self.layouts = dict(layouts)
        self._tile_records: list[ObstacleTileAssignmentRecord] = self._build_tile_records()

    def _build_tile_records(self) -> list[ObstacleTileAssignmentRecord]:
        records: list[ObstacleTileAssignmentRecord] = []
        tile_index = 0
        for role, layout in self.layouts.items():
            for row_idx in range(layout.num_rows):
                for col_idx in range(layout.num_cols):
                    seq_len = int(layout.sequence_lengths[row_idx, col_idx].item())
                    if seq_len <= 0:
                        continue
                    terrain_id_list = layout.terrain_ids[row_idx, col_idx, :seq_len].tolist()
                    terrain_ids = tuple(int(v) for v in terrain_id_list)
                    terrain_keys = tuple(layout.terrain_keys[row_idx][col_idx])
                    command_profile_keys = tuple(layout.command_profile_keys[row_idx][col_idx])
                    specs = [self.registry.get(terrain_id) for terrain_id in terrain_ids]
                    required_capabilities = self._merge_capabilities(specs)
                    physics_profile_keys = tuple(spec.physics_profile_key for spec in specs)
                    collision_profile_keys = tuple(spec.collision_profile_key for spec in specs)
                    records.append(
                        ObstacleTileAssignmentRecord(
                            tile_index=tile_index,
                            role=role,
                            terrain_ids=terrain_ids,
                            terrain_keys=terrain_keys,
                            command_profile_keys=command_profile_keys,
                            required_capabilities=required_capabilities,
                            physics_profile_keys=physics_profile_keys,
                            collision_profile_keys=collision_profile_keys,
                            sequence_length=seq_len,
                        )
                    )
                    tile_index += 1
        return records

    def _merge_capabilities(self, specs) -> tuple[str, ...]:
        merged: list[str] = []
        seen: set[str] = set()
        for spec in specs:
            for capability in spec.required_capabilities:
                if capability not in seen:
                    seen.add(capability)
                    merged.append(capability)
        return tuple(merged)

    def __len__(self) -> int:
        return len(self._tile_records)

    def records(self) -> list[ObstacleTileAssignmentRecord]:
        return list(self._tile_records)

    def get(self, tile_index: int) -> ObstacleTileAssignmentRecord:
        return self._tile_records[tile_index]

    def records_for_role(self, role: str) -> list[ObstacleTileAssignmentRecord]:
        return [record for record in self._tile_records if record.role == role]


class EnvTerrainAssignmentView:
    """Runtime lookup façade for env-to-terrain assignment.

    This class supports two layers:
    1. A standalone explicit env->tile map for unit tests and early integration.
    2. A future runtime binding path through Isaac Lab's terrain indices.
    """

    def __init__(
        self,
        registry: ObstacleTerrainRegistry,
        tile_table: ObstacleTileAssignmentTable,
        env_to_tile_index: torch.Tensor,
    ):
        if env_to_tile_index.ndim != 1:
            raise ValueError("env_to_tile_index must be a 1-D tensor.")
        if len(tile_table) == 0 and env_to_tile_index.numel() > 0:
            raise ValueError("Cannot assign envs when tile_table is empty.")
        if env_to_tile_index.numel() > 0:
            min_tile = int(torch.min(env_to_tile_index).item())
            max_tile = int(torch.max(env_to_tile_index).item())
            if min_tile < 0:
                raise ValueError("env_to_tile_index must not contain negative tile ids.")
            if max_tile >= len(tile_table):
                raise ValueError(
                    f"env_to_tile_index references tile {max_tile}, but tile_table has only {len(tile_table)} tiles."
                )
        self.registry = registry
        self.tile_table = tile_table
        self.env_to_tile_index = env_to_tile_index.to(dtype=torch.long).clone()

    @classmethod
    def from_layouts_round_robin(
        cls,
        registry: ObstacleTerrainRegistry,
        layouts: dict[str, ObstacleTerrainLayout],
        num_envs: int,
    ) -> EnvTerrainAssignmentView:
        tile_table = ObstacleTileAssignmentTable(registry=registry, layouts=layouts)
        if len(tile_table) == 0:
            raise ValueError("Cannot build env assignment view from empty layouts.")
        env_to_tile = torch.arange(num_envs, dtype=torch.long) % len(tile_table)
        return cls(registry=registry, tile_table=tile_table, env_to_tile_index=env_to_tile)

    def tile_indices_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        if env_ids is None:
            return self.env_to_tile_index.clone()
        return self.env_to_tile_index[env_ids.to(dtype=torch.long)]

    def terrain_ids_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> torch.Tensor:
        tile_indices = self.tile_indices_for_envs(env_ids)
        records = [self.tile_table.get(int(tile_idx.item())) for tile_idx in tile_indices]
        max_len = max((record.sequence_length for record in records), default=0)
        terrain_ids = torch.full((len(records), max_len), -1, dtype=torch.long)
        for row_idx, record in enumerate(records):
            if record.sequence_length > 0:
                terrain_ids[row_idx, :record.sequence_length] = torch.tensor(record.terrain_ids, dtype=torch.long)
        return terrain_ids

    def terrain_keys_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[str, ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).terrain_keys for tile_idx in tile_indices]

    def command_profiles_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[str, ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).command_profile_keys for tile_idx in tile_indices]

    def capabilities_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[str, ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).required_capabilities for tile_idx in tile_indices]

    def physics_profile_keys_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[str, ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).physics_profile_keys for tile_idx in tile_indices]

    def collision_profile_keys_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[str, ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).collision_profile_keys for tile_idx in tile_indices]

    def roles_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[str]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).role for tile_idx in tile_indices]

    def sequence_lengths_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> torch.Tensor:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return torch.tensor(
            [self.tile_table.get(int(tile_idx.item())).sequence_length for tile_idx in tile_indices],
            dtype=torch.long,
        )

    def group_env_ids_by_terrain(self, env: ManagerBasedRLEnv | None = None) -> dict[str, torch.Tensor]:
        groups: dict[str, list[int]] = defaultdict(list)
        for env_id, tile_idx in enumerate(self.env_to_tile_index.tolist()):
            record = self.tile_table.get(int(tile_idx))
            for terrain_key in record.terrain_keys:
                groups[terrain_key].append(env_id)
        return {key: torch.tensor(env_ids, dtype=torch.long) for key, env_ids in groups.items()}

    def group_env_ids_by_role(self, env: ManagerBasedRLEnv | None = None) -> dict[str, torch.Tensor]:
        groups: dict[str, list[int]] = defaultdict(list)
        for env_id, tile_idx in enumerate(self.env_to_tile_index.tolist()):
            record = self.tile_table.get(int(tile_idx))
            groups[record.role].append(env_id)
        return {key: torch.tensor(env_ids, dtype=torch.long) for key, env_ids in groups.items()}

    def records_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: Sequence[int] | torch.Tensor | None = None,
    ) -> list[ObstacleEnvAssignmentRecord]:
        if env_ids is None:
            env_id_tensor = torch.arange(len(self.env_to_tile_index), dtype=torch.long)
        elif isinstance(env_ids, torch.Tensor):
            env_id_tensor = env_ids.to(dtype=torch.long)
        else:
            env_id_tensor = torch.tensor(list(env_ids), dtype=torch.long)

        records: list[ObstacleEnvAssignmentRecord] = []
        for env_id in env_id_tensor.tolist():
            tile_index = int(self.env_to_tile_index[env_id].item())
            tile_record = self.tile_table.get(tile_index)
            records.append(
                ObstacleEnvAssignmentRecord(
                    env_id=env_id,
                    role=tile_record.role,
                    terrain_ids=tile_record.terrain_ids,
                    terrain_keys=tile_record.terrain_keys,
                    command_profile_keys=tile_record.command_profile_keys,
                    required_capabilities=tile_record.required_capabilities,
                    physics_profile_keys=tile_record.physics_profile_keys,
                    collision_profile_keys=tile_record.collision_profile_keys,
                    sequence_length=tile_record.sequence_length,
                    tile_index=tile_record.tile_index,
                )
            )
        return records

    def sync_from_env_terrain_indices(self, env: ManagerBasedRLEnv) -> None:
        """Future integration hook.

        The current assignment view is intentionally simulator-agnostic. Later we
        can map `env.scene['terrain'].terrain_levels` / `terrain_types` to tile
        indices here once the physical sequence-env representation is finalized.
        """
        raise NotImplementedError(
            "TODO: bind env_to_tile_index to runtime terrain_levels/terrain_types once sequence env physics is finalized."
        )
