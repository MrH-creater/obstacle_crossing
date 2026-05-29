from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
import random

import torch

from .sequence_generator import SequenceTemplatePool
from .terrain_layout import ObstacleTerrainLayout
from .terrain_registry import ObstacleTerrainRegistry

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


AssignmentKind = Literal["single", "sequence"]


@dataclass(frozen=True)
class RoleAssignmentResult:
    single_train_env_ids: torch.Tensor
    sequence_train_env_ids: torch.Tensor


@dataclass(frozen=True)
class SampleAssignmentResult:
    single_tile_indices: torch.Tensor
    sequence_tile_indices: torch.Tensor


@dataclass(frozen=True)
class ObstacleEnvAssignmentRecord:
    env_id: int
    role: str
    assignment_kind: AssignmentKind
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    sequence_length: int
    sequence_id: str | None
    segment_ranges_y: tuple[tuple[float, float], ...]
    buffer_ranges_y: tuple[tuple[float, float], ...]
    sequence_total_length_y: float | None
    tile_index: int
    template_geometry_path: str | None
    template_metadata_path: str | None


@dataclass(frozen=True)
class ObstacleTileAssignmentRecord:
    tile_index: int
    role: str
    assignment_kind: AssignmentKind
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    sequence_length: int
    sequence_id: str | None
    segment_ranges_y: tuple[tuple[float, float], ...]
    buffer_ranges_y: tuple[tuple[float, float], ...]
    sequence_total_length_y: float | None
    template_geometry_path: str | None
    template_metadata_path: str | None


class ObstacleTileAssignmentTable:
    """Flattened tile-level assignment table built from role layouts.

    This class is intentionally independent from Isaac Lab env internals so it can
    be unit-tested before being bound to a runtime environment.
    """

    def __init__(
        self,
        registry: ObstacleTerrainRegistry,
        layouts: dict[str, ObstacleTerrainLayout] | None = None,
        *,
        tile_records: Sequence[ObstacleTileAssignmentRecord] | None = None,
    ):
        self.registry = registry
        self.layouts = dict(layouts or {})
        if tile_records is not None:
            self._tile_records = list(tile_records)
        else:
            self._tile_records = self._build_tile_records()

    @classmethod
    def from_single_layout_and_sequence_pool(
        cls,
        registry: ObstacleTerrainRegistry,
        single_layout: ObstacleTerrainLayout | None,
        sequence_pool: SequenceTemplatePool,
        sequence_tile_count: int,
        *,
        sequence_role: str = "sequence_train",
    ) -> ObstacleTileAssignmentTable:
        if sequence_tile_count < 0:
            raise ValueError(f"sequence_tile_count must be >= 0, got {sequence_tile_count}.")

        single_records = cls._build_single_layout_tile_records(registry, single_layout, starting_tile_index=0)
        sequence_records = cls._build_sequence_tile_records(
            sequence_pool,
            sequence_tile_count,
            starting_tile_index=len(single_records),
            role=sequence_role,
        )
        layouts: dict[str, ObstacleTerrainLayout] = {}
        if single_layout is not None:
            layouts[single_layout.role] = single_layout
        return cls(registry=registry, layouts=layouts, tile_records=[*single_records, *sequence_records])

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
                    assignment_kind: AssignmentKind = "single" if seq_len == 1 else "sequence"
                    records.append(
                        ObstacleTileAssignmentRecord(
                            tile_index=tile_index,
                            role=role,
                            assignment_kind=assignment_kind,
                            terrain_ids=terrain_ids,
                            terrain_keys=terrain_keys,
                            command_profile_keys=command_profile_keys,
                            required_capabilities=required_capabilities,
                            physics_profile_keys=physics_profile_keys,
                            collision_profile_keys=collision_profile_keys,
                            sequence_length=seq_len,
                            sequence_id=None,
                            segment_ranges_y=(),
                            buffer_ranges_y=(),
                            sequence_total_length_y=None,
                            template_geometry_path=None,
                            template_metadata_path=None,
                        )
                    )
                    tile_index += 1
        return records

    @classmethod
    def _build_single_layout_tile_records(
        cls,
        registry: ObstacleTerrainRegistry,
        single_layout: ObstacleTerrainLayout | None,
        *,
        starting_tile_index: int,
    ) -> list[ObstacleTileAssignmentRecord]:
        if single_layout is None:
            return []
        table = cls(registry=registry, layouts={single_layout.role: single_layout})
        return [replace_tile_index(record, starting_tile_index + offset) for offset, record in enumerate(table.records())]

    @staticmethod
    def _build_sequence_tile_records(
        sequence_pool: SequenceTemplatePool,
        sequence_tile_count: int,
        *,
        starting_tile_index: int,
        role: str,
    ) -> list[ObstacleTileAssignmentRecord]:
        if sequence_tile_count == 0:
            return []
        if not sequence_pool.template_records:
            raise ValueError("sequence_pool must contain template_records when sequence_tile_count > 0.")

        records: list[ObstacleTileAssignmentRecord] = []
        for offset in range(sequence_tile_count):
            template = sequence_pool.template_records[offset % len(sequence_pool.template_records)]
            records.append(
                ObstacleTileAssignmentRecord(
                    tile_index=starting_tile_index + offset,
                    role=role,
                    assignment_kind="sequence",
                    terrain_ids=template.terrain_ids,
                    terrain_keys=template.terrain_keys,
                    command_profile_keys=template.command_profile_keys,
                    required_capabilities=template.required_capabilities,
                    physics_profile_keys=template.physics_profile_keys,
                    collision_profile_keys=template.collision_profile_keys,
                    sequence_length=template.sequence_length,
                    sequence_id=template.sequence_id,
                    segment_ranges_y=template.segment_ranges_y,
                    buffer_ranges_y=template.buffer_ranges_y,
                    sequence_total_length_y=template.sequence_total_length_y,
                    template_geometry_path=template.geometry_output_path,
                    template_metadata_path=template.metadata_output_path,
                )
            )
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

    @classmethod
    def from_single_layout_and_sequence_pool(
        cls,
        registry: ObstacleTerrainRegistry,
        single_layout: ObstacleTerrainLayout | None,
        sequence_pool: SequenceTemplatePool,
        sequence_tile_count: int,
        num_envs: int,
        *,
        sequence_role: str = "sequence_train",
    ) -> EnvTerrainAssignmentView:
        tile_table = ObstacleTileAssignmentTable.from_single_layout_and_sequence_pool(
            registry=registry,
            single_layout=single_layout,
            sequence_pool=sequence_pool,
            sequence_tile_count=sequence_tile_count,
            sequence_role=sequence_role,
        )
        if len(tile_table) == 0:
            raise ValueError("Cannot build env assignment view from empty single layout and empty sequence pool.")
        env_to_tile = torch.arange(num_envs, dtype=torch.long) % len(tile_table)
        return cls(registry=registry, tile_table=tile_table, env_to_tile_index=env_to_tile)

    @classmethod
    def from_role_counts_and_active_pool(
        cls,
        registry: ObstacleTerrainRegistry,
        single_layout: ObstacleTerrainLayout | None,
        sequence_pool: SequenceTemplatePool,
        role_counts: dict[str, int],
        num_envs: int,
        *,
        seed: int = 0,
        sequence_role: str = "sequence_train",
    ) -> EnvTerrainAssignmentView:
        sequence_tile_count = int(role_counts.get(sequence_role, 0))
        tile_table = ObstacleTileAssignmentTable.from_single_layout_and_sequence_pool(
            registry=registry,
            single_layout=single_layout,
            sequence_pool=sequence_pool,
            sequence_tile_count=sequence_tile_count,
            sequence_role=sequence_role,
        )
        if len(tile_table) == 0:
            raise ValueError("Cannot build env assignment view from empty training sample pools.")

        role_assignment = cls._sample_role_assignment(
            num_envs=num_envs,
            single_env_count=max(num_envs - sequence_tile_count, 0),
            sequence_env_count=sequence_tile_count,
            seed=seed,
        )
        sample_assignment = cls._sample_sample_assignment(
            tile_table=tile_table,
            role_assignment=role_assignment,
            rng=random.Random(seed),
            sequence_role=sequence_role,
        )
        env_to_tile = cls._compose_env_to_tile_index(num_envs, role_assignment, sample_assignment)
        return cls(registry=registry, tile_table=tile_table, env_to_tile_index=env_to_tile)

    @staticmethod
    def _sample_role_assignment(
        *,
        num_envs: int,
        single_env_count: int,
        sequence_env_count: int,
        seed: int,
    ) -> RoleAssignmentResult:
        if num_envs < 0:
            raise ValueError(f"num_envs must be >= 0, got {num_envs}.")
        if single_env_count < 0 or sequence_env_count < 0:
            raise ValueError("single_env_count and sequence_env_count must be >= 0.")
        if single_env_count + sequence_env_count > num_envs:
            raise ValueError(
                f"Requested single+sequence env count exceeds num_envs: {single_env_count}+{sequence_env_count}>{num_envs}."
            )
        rng = random.Random(seed)
        env_ids = list(range(num_envs))
        rng.shuffle(env_ids)
        sequence_ids = sorted(env_ids[:sequence_env_count])
        single_ids = sorted(env_ids[sequence_env_count:sequence_env_count + single_env_count])
        return RoleAssignmentResult(
            single_train_env_ids=torch.tensor(single_ids, dtype=torch.long),
            sequence_train_env_ids=torch.tensor(sequence_ids, dtype=torch.long),
        )

    @staticmethod
    def _sample_sample_assignment(
        *,
        tile_table: ObstacleTileAssignmentTable,
        role_assignment: RoleAssignmentResult,
        rng: random.Random,
        sequence_role: str,
    ) -> SampleAssignmentResult:
        single_tile_indices = [
            record.tile_index for record in tile_table.records_for_role("single_train") if record.assignment_kind == "single"
        ]
        sequence_tile_indices = [
            record.tile_index for record in tile_table.records_for_role(sequence_role) if record.assignment_kind == "sequence"
        ]
        if role_assignment.single_train_env_ids.numel() > 0 and not single_tile_indices:
            raise ValueError("No single_train tile records are available for single env assignment.")
        if role_assignment.sequence_train_env_ids.numel() > 0 and not sequence_tile_indices:
            raise ValueError("No sequence tile records are available for sequence env assignment.")

        assigned_single_tiles = torch.tensor(
            [rng.choice(single_tile_indices) for _ in range(role_assignment.single_train_env_ids.numel())],
            dtype=torch.long,
        ) if role_assignment.single_train_env_ids.numel() > 0 else torch.empty(0, dtype=torch.long)

        assigned_sequence_tiles = torch.tensor(
            [sequence_tile_indices[idx % len(sequence_tile_indices)] for idx in range(role_assignment.sequence_train_env_ids.numel())],
            dtype=torch.long,
        ) if role_assignment.sequence_train_env_ids.numel() > 0 else torch.empty(0, dtype=torch.long)

        return SampleAssignmentResult(
            single_tile_indices=assigned_single_tiles,
            sequence_tile_indices=assigned_sequence_tiles,
        )

    @staticmethod
    def _compose_env_to_tile_index(
        num_envs: int,
        role_assignment: RoleAssignmentResult,
        sample_assignment: SampleAssignmentResult,
    ) -> torch.Tensor:
        env_to_tile_index = torch.full((num_envs,), -1, dtype=torch.long)
        if role_assignment.single_train_env_ids.numel() > 0:
            env_to_tile_index[role_assignment.single_train_env_ids] = sample_assignment.single_tile_indices
        if role_assignment.sequence_train_env_ids.numel() > 0:
            env_to_tile_index[role_assignment.sequence_train_env_ids] = sample_assignment.sequence_tile_indices
        if torch.any(env_to_tile_index < 0):
            raise ValueError("Some env ids were not assigned to any terrain/sample tile.")
        return env_to_tile_index

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

    def assignment_kinds_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[str]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).assignment_kind for tile_idx in tile_indices]

    def sequence_ids_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[str | None]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).sequence_id for tile_idx in tile_indices]

    def segment_ranges_y_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[tuple[float, float], ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).segment_ranges_y for tile_idx in tile_indices]

    def buffer_ranges_y_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[tuple[tuple[float, float], ...]]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).buffer_ranges_y for tile_idx in tile_indices]

    def sequence_total_lengths_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[float | None]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).sequence_total_length_y for tile_idx in tile_indices]

    def template_geometry_paths_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[str | None]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).template_geometry_path for tile_idx in tile_indices]

    def template_metadata_paths_for_envs(
        self,
        env: ManagerBasedRLEnv | None = None,
        env_ids: torch.Tensor | None = None,
    ) -> list[str | None]:
        tile_indices = self.tile_indices_for_envs(env_ids)
        return [self.tile_table.get(int(tile_idx.item())).template_metadata_path for tile_idx in tile_indices]

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
                    assignment_kind=tile_record.assignment_kind,
                    terrain_ids=tile_record.terrain_ids,
                    terrain_keys=tile_record.terrain_keys,
                    command_profile_keys=tile_record.command_profile_keys,
                    required_capabilities=tile_record.required_capabilities,
                    physics_profile_keys=tile_record.physics_profile_keys,
                    collision_profile_keys=tile_record.collision_profile_keys,
                    sequence_length=tile_record.sequence_length,
                    sequence_id=tile_record.sequence_id,
                    segment_ranges_y=tile_record.segment_ranges_y,
                    buffer_ranges_y=tile_record.buffer_ranges_y,
                    sequence_total_length_y=tile_record.sequence_total_length_y,
                    tile_index=tile_record.tile_index,
                    template_geometry_path=tile_record.template_geometry_path,
                    template_metadata_path=tile_record.template_metadata_path,
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



def replace_tile_index(record: ObstacleTileAssignmentRecord, tile_index: int) -> ObstacleTileAssignmentRecord:
    return ObstacleTileAssignmentRecord(
        tile_index=tile_index,
        role=record.role,
        assignment_kind=record.assignment_kind,
        terrain_ids=record.terrain_ids,
        terrain_keys=record.terrain_keys,
        command_profile_keys=record.command_profile_keys,
        required_capabilities=record.required_capabilities,
        physics_profile_keys=record.physics_profile_keys,
        collision_profile_keys=record.collision_profile_keys,
        sequence_length=record.sequence_length,
        sequence_id=record.sequence_id,
        segment_ranges_y=record.segment_ranges_y,
        buffer_ranges_y=record.buffer_ranges_y,
        sequence_total_length_y=record.sequence_total_length_y,
        template_geometry_path=record.template_geometry_path,
        template_metadata_path=record.template_metadata_path,
    )
