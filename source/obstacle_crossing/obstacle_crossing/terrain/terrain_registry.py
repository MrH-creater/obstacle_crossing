from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .terrain_physics import (
    DEFAULT_TERRAIN_COLLISION_PROFILES,
    DEFAULT_TERRAIN_PHYSICS_PROFILES,
    TerrainCollisionProfile,
    TerrainPhysicsProfile,
)
from .terrain_specs import ObstacleTerrainSpec, VelocityCommandProfile


DEFAULT_G1_COMMAND_PROFILES: dict[str, VelocityCommandProfile] = {
    "straight": VelocityCommandProfile(lin_vel_x=(0.45, 1.00), lin_vel_y=(0.0, 0.0), ang_vel_z=(-0.4, 0.4)),
    "turning": VelocityCommandProfile(lin_vel_x=(0.35, 0.80), lin_vel_y=(0.0, 0.0), ang_vel_z=(-1.0, 1.0)),
    "clearance": VelocityCommandProfile(lin_vel_x=(0.25, 0.60), lin_vel_y=(0.0, 0.0), ang_vel_z=(-0.4, 0.4)),
    "slalom": VelocityCommandProfile(lin_vel_x=(0.25, 0.60), lin_vel_y=(-0.2, 0.2), ang_vel_z=(-1.2, 1.2)),
    "stairs": VelocityCommandProfile(lin_vel_x=(0.15, 0.45), lin_vel_y=(0.0, 0.0), ang_vel_z=(-0.3, 0.3)),
    "crawl": VelocityCommandProfile(lin_vel_x=(0.05, 0.25), lin_vel_y=(0.0, 0.0), ang_vel_z=(-0.2, 0.2)),
    "platform": VelocityCommandProfile(lin_vel_x=(0.10, 0.35), lin_vel_y=(0.0, 0.0), ang_vel_z=(-0.3, 0.3)),
    "l_bend": VelocityCommandProfile(lin_vel_x=(0.15, 0.35), lin_vel_y=(-0.15, 0.15), ang_vel_z=(-1.0, 1.0)),
    "default": VelocityCommandProfile(lin_vel_x=(0.20, 0.60), lin_vel_y=(0.0, 0.0), ang_vel_z=(-0.5, 0.5)),
}


DEFAULT_G1_TERRAIN_SPECS: tuple[ObstacleTerrainSpec, ...] = (
    ObstacleTerrainSpec(
        key="continuous_ramp",
        terrain_id=0,
        terrain_file="../centered/1.Continuous Ramp.stl",
        motion_file="motions/ramp_retargetted.npz",
        curriculum_rank=0,
        command_profile_key="straight",
        enabled_for_single_training=True,
        enabled_for_sequence_training=True,
        tags=("train", "sequence"),
        required_capabilities=("walk", "slope_up_down", "balance"),
        physics_profile_key="default_walk_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="continuous_hurdling",
        terrain_id=1,
        terrain_file="../centered/2.Continuous Hurdling.stl",
        motion_file="motions/hurdling_retargetted.npz",
        curriculum_rank=1,
        command_profile_key="clearance",
        enabled_for_single_training=True,
        enabled_for_sequence_training=True,
        tags=("train", "sequence"),
        required_capabilities=("walk", "step_clearance", "balance"),
        physics_profile_key="clearance_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="cross_slope",
        terrain_id=2,
        terrain_file="../centered/3.Cross Slope.stl",
        motion_file="motions/cross_slope_retargetted.npz",
        curriculum_rank=2,
        command_profile_key="straight",
        enabled_for_single_training=True,
        enabled_for_sequence_training=True,
        tags=("train", "sequence"),
        required_capabilities=("walk", "uneven_terrain", "balance"),
        physics_profile_key="default_walk_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="consecutive_slalom",
        terrain_id=3,
        terrain_file="../centered/4.Consecutive Slalom.stl",
        motion_file="motions/slalom_retargetted.npz",
        curriculum_rank=5,
        command_profile_key="slalom",
        enabled_for_single_training=True,
        enabled_for_sequence_training=True,
        tags=("train", "sequence"),
        required_capabilities=("walk", "lateral_control", "turning", "balance"),
        physics_profile_key="narrow_turn_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="symmetrical_ramp",
        terrain_id=4,
        terrain_file="../centered/5.Symmetrical Ramp.stl",
        motion_file="motions/symmetrical_ramp_retargetted.npz",
        curriculum_rank=3,
        command_profile_key="straight",
        enabled_for_single_training=True,
        enabled_for_sequence_training=True,
        tags=("train", "sequence"),
        required_capabilities=("walk", "slope_up_down", "balance"),
        physics_profile_key="default_walk_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="spiral_staircase",
        terrain_id=5,
        terrain_file="../centered/6.Spiral Staircase.stl",
        motion_file=None,
        curriculum_rank=6,
        command_profile_key="stairs",
        enabled_for_single_training=False,
        enabled_for_sequence_training=False,
        enabled_for_future_benchmark=True,
        tags=("future_benchmark",),
        required_capabilities=("stairs", "turning", "precise_foot_placement", "balance"),
        physics_profile_key="stairs_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="s_curve",
        terrain_id=6,
        terrain_file="../centered/7.S-Curve.stl",
        motion_file="motions/s_curve_retargetted.npz",
        curriculum_rank=4,
        command_profile_key="turning",
        enabled_for_single_training=True,
        enabled_for_sequence_training=True,
        tags=("train", "sequence"),
        required_capabilities=("walk", "turning", "balance"),
        physics_profile_key="default_walk_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="one_meter_platform",
        terrain_id=7,
        terrain_file="../centered/8.One-meter Platform.stl",
        motion_file=None,
        curriculum_rank=7,
        command_profile_key="platform",
        enabled_for_single_training=False,
        enabled_for_sequence_training=False,
        enabled_for_future_benchmark=True,
        tags=("future_benchmark",),
        required_capabilities=("step_up", "jump_like_clearance", "landing_balance"),
        physics_profile_key="platform_surface",
        collision_profile_key="default",
    ),
    ObstacleTerrainSpec(
        key="crawl_channel",
        terrain_id=8,
        terrain_file="../centered/9.Crawl Channel.stl",
        motion_file=None,
        curriculum_rank=8,
        command_profile_key="crawl",
        enabled_for_single_training=False,
        enabled_for_sequence_training=False,
        enabled_for_future_benchmark=True,
        tags=("future_benchmark",),
        required_capabilities=("crouch", "crawl", "body_clearance"),
        physics_profile_key="crawl_surface",
        collision_profile_key="crawl_channel",
    ),
    ObstacleTerrainSpec(
        key="width_restricted_l_shaped_bend",
        terrain_id=9,
        terrain_file="../centered/10.Width-restricted L-shaped Bend.stl",
        motion_file=None,
        curriculum_rank=9,
        command_profile_key="l_bend",
        enabled_for_single_training=False,
        enabled_for_sequence_training=False,
        enabled_for_future_benchmark=True,
        tags=("future_benchmark",),
        required_capabilities=("turning", "lateral_control", "narrow_passage", "balance"),
        physics_profile_key="narrow_turn_surface",
        collision_profile_key="narrow_passage",
    ),
)


class ObstacleTerrainRegistry:
    """Registry container for obstacle terrain specifications.

    Responsibilities:
    - validate uniqueness of terrain ids / keys
    - validate command profile / physics profile / collision profile references
    - expose filtered terrain views for current training/eval pools
    - keep future benchmark terrains registered without exposing them to current eval
    - expose capability-based queries so future difficult terrains can be enabled later
    - export metadata rows compatible with the motion-matched terrain pipeline
    """

    def __init__(
        self,
        specs: Iterable[ObstacleTerrainSpec] = (),
        command_profiles: dict[str, VelocityCommandProfile] | None = None,
        physics_profiles: dict[str, TerrainPhysicsProfile] | None = None,
        collision_profiles: dict[str, TerrainCollisionProfile] | None = None,
    ):
        self._specs_by_key: dict[str, ObstacleTerrainSpec] = {}
        self._specs_by_id: dict[int, ObstacleTerrainSpec] = {}
        self._command_profiles = dict(command_profiles or {})
        self._physics_profiles = dict(physics_profiles or {})
        self._collision_profiles = dict(collision_profiles or {})
        self._validate_profile_dicts()
        for spec in specs:
            self.register(spec)

    def _validate_profile_dicts(self) -> None:
        if self._command_profiles and "default" not in self._command_profiles:
            raise ValueError("command_profiles must include a 'default' profile.")
        if self._physics_profiles and "default_walk_surface" not in self._physics_profiles:
            raise ValueError(
                "physics_profiles must include a 'default_walk_surface' profile."
            )
        if self._collision_profiles and "default" not in self._collision_profiles:
            raise ValueError("collision_profiles must include a 'default' profile.")

    def _validate_spec(self, spec: ObstacleTerrainSpec) -> None:
        if spec.key in self._specs_by_key:
            raise ValueError(f"Duplicate terrain key '{spec.key}'.")
        if spec.terrain_id in self._specs_by_id:
            raise ValueError(f"Duplicate terrain_id '{spec.terrain_id}'.")
        if self._command_profiles and spec.command_profile_key not in self._command_profiles:
            raise ValueError(
                f"Terrain '{spec.key}' references unknown command profile "
                f"'{spec.command_profile_key}'."
            )
        if self._physics_profiles and spec.physics_profile_key not in self._physics_profiles:
            raise ValueError(
                f"Terrain '{spec.key}' references unknown physics profile "
                f"'{spec.physics_profile_key}'."
            )
        if self._collision_profiles and spec.collision_profile_key not in self._collision_profiles:
            raise ValueError(
                f"Terrain '{spec.key}' references unknown collision profile "
                f"'{spec.collision_profile_key}'."
            )

    def register(self, spec: ObstacleTerrainSpec) -> None:
        self._validate_spec(spec)
        self._specs_by_key[spec.key] = spec
        self._specs_by_id[spec.terrain_id] = spec

    def get(self, key_or_id: str | int) -> ObstacleTerrainSpec:
        if isinstance(key_or_id, str):
            return self._specs_by_key[key_or_id]
        return self._specs_by_id[key_or_id]

    def __contains__(self, key_or_id: object) -> bool:
        if isinstance(key_or_id, str):
            return key_or_id in self._specs_by_key
        if isinstance(key_or_id, int):
            return key_or_id in self._specs_by_id
        return False

    def __len__(self) -> int:
        return len(self._specs_by_id)

    def keys(self) -> list[str]:
        return [spec.key for spec in self.ordered_specs()]

    def ids(self) -> list[int]:
        return [spec.terrain_id for spec in self.ordered_specs()]

    def ordered_specs(self) -> list[ObstacleTerrainSpec]:
        return sorted(self._specs_by_id.values(), key=lambda spec: spec.terrain_id)

    def enabled_specs(self) -> list[ObstacleTerrainSpec]:
        return self.single_train_specs()

    def single_train_specs(self) -> list[ObstacleTerrainSpec]:
        return [spec for spec in self.ordered_specs() if spec.enabled_for_single_training]

    def sequence_train_specs(self) -> list[ObstacleTerrainSpec]:
        return [spec for spec in self.single_train_specs() if spec.enabled_for_sequence_training]

    def sequence_eval_specs(self) -> list[ObstacleTerrainSpec]:
        return self.sequence_train_specs()

    def future_benchmark_specs(self) -> list[ObstacleTerrainSpec]:
        return [spec for spec in self.ordered_specs() if spec.enabled_for_future_benchmark]

    def current_eval_specs(self) -> list[ObstacleTerrainSpec]:
        return self.single_train_specs()

    def non_training_specs(self) -> list[ObstacleTerrainSpec]:
        return [spec for spec in self.ordered_specs() if not spec.enabled_for_single_training]

    def specs_for_role(self, role: str) -> list[ObstacleTerrainSpec]:
        if role == "single_train":
            return self.single_train_specs()
        if role == "sequence_train":
            return self.sequence_train_specs()
        if role == "sequence_eval":
            return self.sequence_eval_specs()
        if role == "holdout_eval":
            return self.future_benchmark_specs()
        raise KeyError(f"Unknown obstacle env role '{role}'.")

    def command_profile(self, key: str) -> VelocityCommandProfile:
        return self._command_profiles[key]

    def command_profile_for_terrain(self, key_or_id: str | int) -> VelocityCommandProfile:
        spec = self.get(key_or_id)
        return self.command_profile(spec.command_profile_key)

    def physics_profile(self, key: str) -> TerrainPhysicsProfile:
        return self._physics_profiles[key]

    def physics_profile_for_terrain(self, key_or_id: str | int) -> TerrainPhysicsProfile:
        spec = self.get(key_or_id)
        return self.physics_profile(spec.physics_profile_key)

    def collision_profile(self, key: str) -> TerrainCollisionProfile:
        return self._collision_profiles[key]

    def collision_profile_for_terrain(self, key_or_id: str | int) -> TerrainCollisionProfile:
        spec = self.get(key_or_id)
        return self.collision_profile(spec.collision_profile_key)

    def build_command_profiles(self) -> dict[str, VelocityCommandProfile]:
        return dict(self._command_profiles)

    def build_physics_profiles(self) -> dict[str, TerrainPhysicsProfile]:
        return dict(self._physics_profiles)

    def build_collision_profiles(self) -> dict[str, TerrainCollisionProfile]:
        return dict(self._collision_profiles)

    def build_profile_by_terrain_key(self) -> dict[str, str]:
        return {spec.key: spec.command_profile_key for spec in self.ordered_specs()}

    def build_physics_profile_by_terrain_key(self) -> dict[str, str]:
        return {spec.key: spec.physics_profile_key for spec in self.ordered_specs()}

    def build_collision_profile_by_terrain_key(self) -> dict[str, str]:
        return {spec.key: spec.collision_profile_key for spec in self.ordered_specs()}

    def capability_index(self) -> dict[str, list[ObstacleTerrainSpec]]:
        index: dict[str, list[ObstacleTerrainSpec]] = defaultdict(list)
        for spec in self.ordered_specs():
            for capability in spec.required_capabilities:
                index[capability].append(spec)
        return dict(index)

    def specs_with_capability(
        self,
        capability: str,
        *,
        include_future_benchmark: bool = True,
    ) -> list[ObstacleTerrainSpec]:
        specs = [spec for spec in self.ordered_specs() if capability in spec.required_capabilities]
        if include_future_benchmark:
            return specs
        return [spec for spec in specs if not spec.enabled_for_future_benchmark]

    def terrains_requiring_any_capability(
        self,
        capabilities: Iterable[str],
        *,
        include_future_benchmark: bool = True,
    ) -> list[ObstacleTerrainSpec]:
        capability_set = set(capabilities)
        specs = [
            spec
            for spec in self.ordered_specs()
            if capability_set.intersection(spec.required_capabilities)
        ]
        if include_future_benchmark:
            return specs
        return [spec for spec in specs if not spec.enabled_for_future_benchmark]

    def terrains_requiring_all_capabilities(
        self,
        capabilities: Iterable[str],
        *,
        include_future_benchmark: bool = True,
    ) -> list[ObstacleTerrainSpec]:
        capability_tuple = tuple(capabilities)
        specs = [
            spec
            for spec in self.ordered_specs()
            if all(capability in spec.required_capabilities for capability in capability_tuple)
        ]
        if include_future_benchmark:
            return specs
        return [spec for spec in specs if not spec.enabled_for_future_benchmark]

    def build_metadata_rows(
        self,
        include_disabled_terrains: bool = False,
        include_motionless_terrains: bool = False,
    ) -> tuple[list[dict], list[dict]]:
        terrains: list[dict] = []
        motion_files: list[dict] = []
        specs = self.ordered_specs() if include_disabled_terrains else self.enabled_specs()
        for spec in specs:
            terrains.append(
                {
                    "terrain_id": spec.terrain_id,
                    "terrain_file": spec.terrain_file,
                }
            )
            if spec.motion_file is not None:
                motion_files.append(
                    {
                        "terrain_id": spec.terrain_id,
                        "motion_file": spec.motion_file,
                        "weight": spec.weight,
                    }
                )
            elif include_motionless_terrains:
                motion_files.append(
                    {
                        "terrain_id": spec.terrain_id,
                        "motion_file": None,
                        "weight": spec.weight,
                    }
                )
        return terrains, motion_files

    def validate(self) -> None:
        if not self._specs_by_id:
            raise ValueError("Terrain registry is empty.")

        single_specs = self.single_train_specs()
        seq_specs = self.sequence_train_specs()
        benchmark_specs = self.future_benchmark_specs()

        if not single_specs:
            raise ValueError("Terrain registry has no terrains enabled for single-terrain training.")
        if not seq_specs:
            raise ValueError("Terrain registry has no terrains enabled for sequence training/eval.")

        single_ids = {spec.terrain_id for spec in single_specs}
        seq_ids = {spec.terrain_id for spec in seq_specs}
        if not seq_ids.issubset(single_ids):
            raise ValueError("sequence_train/eval terrains must be a subset of single_train terrains.")

        benchmark_ids = {spec.terrain_id for spec in benchmark_specs}
        if benchmark_ids & single_ids:
            raise ValueError("future benchmark terrains must not overlap with current single-train terrains.")

        all_ranks = [spec.curriculum_rank for spec in self.ordered_specs()]
        if len(all_ranks) != len(set(all_ranks)):
            raise ValueError("curriculum_rank values must be unique across registered terrains.")

        for spec in self.ordered_specs():
            if spec.motion_file is None and (
                spec.enabled_for_single_training or spec.enabled_for_sequence_training
            ):
                raise ValueError(
                    f"Terrain '{spec.key}' is enabled for training but has no motion_file."
                )

    def summary(self) -> dict[str, list[str] | int | dict[str, list[str]]]:
        capability_summary = {
            capability: [spec.key for spec in specs]
            for capability, specs in self.capability_index().items()
        }
        return {
            "num_total": len(self),
            "single_train": [spec.key for spec in self.single_train_specs()],
            "sequence_train": [spec.key for spec in self.sequence_train_specs()],
            "sequence_eval": [spec.key for spec in self.sequence_eval_specs()],
            "future_benchmark": [spec.key for spec in self.future_benchmark_specs()],
            "capabilities": capability_summary,
        }


def build_default_obstacle_crossing_registry() -> ObstacleTerrainRegistry:
    registry = ObstacleTerrainRegistry(
        specs=DEFAULT_G1_TERRAIN_SPECS,
        command_profiles=DEFAULT_G1_COMMAND_PROFILES,
        physics_profiles=DEFAULT_TERRAIN_PHYSICS_PROFILES,
        collision_profiles=DEFAULT_TERRAIN_COLLISION_PROFILES,
    )
    registry.validate()
    return registry
