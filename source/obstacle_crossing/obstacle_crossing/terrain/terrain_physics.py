from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CombineMode = Literal["average", "min", "multiply", "max"]


@dataclass(frozen=True)
class TerrainPhysicsProfile:
    """Declarative surface/material parameters for one terrain profile.

    This does not apply the material to Isaac Lab / PhysX yet; it only stores
    profile values so registry / events can reference a stable configuration.
    """

    static_friction: float
    dynamic_friction: float
    restitution: float = 0.0
    friction_combine_mode: CombineMode = "multiply"
    restitution_combine_mode: CombineMode = "multiply"

    def __post_init__(self) -> None:
        if self.static_friction < 0.0:
            raise ValueError("static_friction must be >= 0.")
        if self.dynamic_friction < 0.0:
            raise ValueError("dynamic_friction must be >= 0.")
        if self.restitution < 0.0:
            raise ValueError("restitution must be >= 0.")


@dataclass(frozen=True)
class TerrainCollisionProfile:
    """Declarative collision/contact parameters for one terrain profile."""

    collision_group: int = -1
    collision_enabled: bool = True
    contact_offset: float | None = None
    rest_offset: float | None = None

    def __post_init__(self) -> None:
        if self.contact_offset is not None and self.contact_offset < 0.0:
            raise ValueError("contact_offset must be >= 0 when provided.")
        if self.rest_offset is not None and self.rest_offset < 0.0:
            raise ValueError("rest_offset must be >= 0 when provided.")


DEFAULT_TERRAIN_PHYSICS_PROFILES: dict[str, TerrainPhysicsProfile] = {
    "default_walk_surface": TerrainPhysicsProfile(
        static_friction=1.0,
        dynamic_friction=1.0,
        restitution=0.0,
    ),
    "clearance_surface": TerrainPhysicsProfile(
        static_friction=1.0,
        dynamic_friction=0.95,
        restitution=0.0,
    ),
    "stairs_surface": TerrainPhysicsProfile(
        static_friction=1.05,
        dynamic_friction=1.0,
        restitution=0.0,
    ),
    "crawl_surface": TerrainPhysicsProfile(
        static_friction=0.95,
        dynamic_friction=0.9,
        restitution=0.0,
    ),
    "platform_surface": TerrainPhysicsProfile(
        static_friction=1.0,
        dynamic_friction=0.95,
        restitution=0.0,
    ),
    "narrow_turn_surface": TerrainPhysicsProfile(
        static_friction=1.0,
        dynamic_friction=1.0,
        restitution=0.0,
    ),
}


DEFAULT_TERRAIN_COLLISION_PROFILES: dict[str, TerrainCollisionProfile] = {
    "default": TerrainCollisionProfile(
        collision_group=-1,
        collision_enabled=True,
    ),
    "narrow_passage": TerrainCollisionProfile(
        collision_group=-1,
        collision_enabled=True,
        contact_offset=0.01,
        rest_offset=0.0,
    ),
    "crawl_channel": TerrainCollisionProfile(
        collision_group=-1,
        collision_enabled=True,
        contact_offset=0.01,
        rest_offset=0.0,
    ),
}
