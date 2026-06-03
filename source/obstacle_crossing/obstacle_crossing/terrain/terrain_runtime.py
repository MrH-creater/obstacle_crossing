from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

import torch

from .terrain_assignment import EnvTerrainAssignmentView


RuntimeOriginSource = Literal["auto", "terrain", "scene"]


@runtime_checkable
class RuntimePlacementProvider(Protocol):
    """Runtime placement query interface consumed by terrain-aware command logic."""

    def origins_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        """Return world-frame XY origins for the requested env ids, shape ``[N, 2]``."""
        ...

    def yaws_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        """Return world-frame yaw values for the requested env ids, shape ``[N]``."""
        ...

    def local_to_world_xy(self, env_ids: torch.Tensor | None, local_xy: torch.Tensor) -> torch.Tensor:
        """Transform path-frame XY coordinates to world-frame XY coordinates."""
        ...

    def world_to_local_xy(self, env_ids: torch.Tensor | None, world_xy: torch.Tensor) -> torch.Tensor:
        """Transform world-frame XY coordinates to path-frame XY coordinates."""
        ...


@dataclass
class TerrainRuntimeContext:
    """Runtime bridge between assignment metadata and authoritative terrain placement."""

    assignment_view: EnvTerrainAssignmentView
    origin_provider: RuntimePlacementProvider
    path_tensor_cache: Any | None = None
    assignment_version: int = 0
    origin_version: int = 0
    path_cache_version: int = 0
    source_iteration: int | None = None


class TensorRuntimePlacementProvider:
    """Tensor-backed placement provider for tests, debug, and standalone bring-up."""

    def __init__(
        self,
        origins_w: torch.Tensor,
        *,
        yaws_w: torch.Tensor | None = None,
        clone: bool = True,
    ) -> None:
        origins_xy = _coerce_origins_xy(origins_w)
        self._origins_w = origins_xy.clone() if clone else origins_xy

        if yaws_w is None:
            self._yaws_w = torch.zeros(self._origins_w.shape[0], dtype=self._origins_w.dtype, device=self._origins_w.device)
        else:
            yaws = torch.as_tensor(yaws_w, dtype=self._origins_w.dtype, device=self._origins_w.device)
            if yaws.ndim != 1:
                raise ValueError(f"yaws_w must be a 1-D tensor, got shape {tuple(yaws.shape)}.")
            if yaws.shape[0] != self._origins_w.shape[0]:
                raise ValueError(
                    "yaws_w must have the same first dimension as origins_w: "
                    f"{yaws.shape[0]} vs {self._origins_w.shape[0]}."
                )
            self._yaws_w = yaws.clone() if clone else yaws

    @property
    def num_envs(self) -> int:
        return int(self._origins_w.shape[0])

    @property
    def device(self) -> torch.device:
        return self._origins_w.device

    def origins_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        indices = _normalize_env_ids(env_ids, num_envs=self.num_envs, device=self.device)
        return self._origins_w[indices]

    def yaws_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        indices = _normalize_env_ids(env_ids, num_envs=self.num_envs, device=self.device)
        return self._yaws_w[indices]

    def local_to_world_xy(self, env_ids: torch.Tensor | None, local_xy: torch.Tensor) -> torch.Tensor:
        origins = self.origins_for_envs(env_ids)
        xy = _coerce_xy_batch(local_xy, expected_count=origins.shape[0], dtype=origins.dtype, device=origins.device)
        return xy + origins

    def world_to_local_xy(self, env_ids: torch.Tensor | None, world_xy: torch.Tensor) -> torch.Tensor:
        origins = self.origins_for_envs(env_ids)
        xy = _coerce_xy_batch(world_xy, expected_count=origins.shape[0], dtype=origins.dtype, device=origins.device)
        return xy - origins


class SceneRuntimePlacementProvider:
    """Scene-backed provider that reads authoritative env origins from Isaac/Instinct runtime objects."""

    def __init__(
        self,
        env: Any,
        *,
        source: RuntimeOriginSource = "auto",
        consistency_atol: float = 1.0e-5,
    ) -> None:
        if source not in ("auto", "terrain", "scene"):
            raise ValueError(f"Unsupported origin source '{source}'.")
        self.env = env
        self.source = source
        self.consistency_atol = float(consistency_atol)

    @property
    def num_envs(self) -> int:
        return int(self._origin_tensor().shape[0])

    @property
    def device(self) -> torch.device:
        return self._origin_tensor().device

    def origins_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        origins_xy = _coerce_origins_xy(self._origin_tensor())
        indices = _normalize_env_ids(env_ids, num_envs=origins_xy.shape[0], device=origins_xy.device)
        return origins_xy[indices]

    def yaws_for_envs(self, env_ids: torch.Tensor | None = None) -> torch.Tensor:
        origins = self.origins_for_envs(env_ids)
        return torch.zeros(origins.shape[0], dtype=origins.dtype, device=origins.device)

    def local_to_world_xy(self, env_ids: torch.Tensor | None, local_xy: torch.Tensor) -> torch.Tensor:
        origins = self.origins_for_envs(env_ids)
        xy = _coerce_xy_batch(local_xy, expected_count=origins.shape[0], dtype=origins.dtype, device=origins.device)
        return xy + origins

    def world_to_local_xy(self, env_ids: torch.Tensor | None, world_xy: torch.Tensor) -> torch.Tensor:
        origins = self.origins_for_envs(env_ids)
        xy = _coerce_xy_batch(world_xy, expected_count=origins.shape[0], dtype=origins.dtype, device=origins.device)
        return xy - origins

    def validate_origin_consistency(self) -> None:
        """Raise if both scene and terrain origins exist but disagree in XY."""
        terrain_origins = self._terrain_env_origins()
        scene_origins = self._scene_env_origins()
        if terrain_origins is None or scene_origins is None:
            return

        terrain_xy = _coerce_origins_xy(terrain_origins)
        scene_xy = _coerce_origins_xy(scene_origins)
        if terrain_xy.shape != scene_xy.shape:
            raise ValueError(
                "scene.terrain.env_origins and scene.env_origins have different XY shapes: "
                f"{tuple(terrain_xy.shape)} vs {tuple(scene_xy.shape)}."
            )
        if not torch.allclose(terrain_xy, scene_xy.to(device=terrain_xy.device, dtype=terrain_xy.dtype), atol=self.consistency_atol):
            max_diff = torch.max(torch.abs(terrain_xy - scene_xy.to(device=terrain_xy.device, dtype=terrain_xy.dtype))).item()
            raise ValueError(
                "scene.terrain.env_origins and scene.env_origins disagree in XY; "
                f"max difference is {max_diff:.6g}."
            )

    def _origin_tensor(self) -> torch.Tensor:
        if self.source == "terrain":
            origins = self._terrain_env_origins()
            if origins is None:
                raise AttributeError("Requested source='terrain', but env.scene.terrain.env_origins is unavailable.")
            return torch.as_tensor(origins)

        if self.source == "scene":
            origins = self._scene_env_origins()
            if origins is None:
                raise AttributeError("Requested source='scene', but env.scene.env_origins is unavailable.")
            return torch.as_tensor(origins)

        terrain_origins = self._terrain_env_origins()
        if terrain_origins is not None:
            return torch.as_tensor(terrain_origins)

        scene_origins = self._scene_env_origins()
        if scene_origins is not None:
            return torch.as_tensor(scene_origins)

        raise AttributeError("No runtime env origins found on env.scene.terrain.env_origins or env.scene.env_origins.")

    def _terrain_env_origins(self) -> Any | None:
        scene = getattr(self.env, "scene", None)
        terrain = getattr(scene, "terrain", None)
        return getattr(terrain, "env_origins", None)

    def _scene_env_origins(self) -> Any | None:
        scene = getattr(self.env, "scene", None)
        return getattr(scene, "env_origins", None)


def build_scene_runtime_context(
    *,
    env: Any,
    assignment_view: EnvTerrainAssignmentView,
    origin_source: RuntimeOriginSource = "auto",
    validate_origin_consistency: bool = True,
) -> TerrainRuntimeContext:
    """Create a terrain runtime context backed by origins already owned by the scene."""
    origin_provider = SceneRuntimePlacementProvider(env, source=origin_source)
    if validate_origin_consistency:
        origin_provider.validate_origin_consistency()
    return TerrainRuntimeContext(assignment_view=assignment_view, origin_provider=origin_provider)


def _normalize_env_ids(env_ids: torch.Tensor | None, *, num_envs: int, device: torch.device) -> torch.Tensor:
    if env_ids is None:
        return torch.arange(num_envs, dtype=torch.long, device=device)
    indices = torch.as_tensor(env_ids, dtype=torch.long, device=device)
    if indices.ndim != 1:
        raise ValueError(f"env_ids must be a 1-D tensor, got shape {tuple(indices.shape)}.")
    if indices.numel() == 0:
        return indices
    min_id = int(torch.min(indices).item())
    max_id = int(torch.max(indices).item())
    if min_id < 0 or max_id >= num_envs:
        raise IndexError(f"env_ids must be in [0, {num_envs}), got min={min_id}, max={max_id}.")
    return indices


def _coerce_origins_xy(origins_w: Any) -> torch.Tensor:
    origins = torch.as_tensor(origins_w)
    if origins.ndim != 2:
        raise ValueError(f"origins_w must be a 2-D tensor, got shape {tuple(origins.shape)}.")
    if origins.shape[1] < 2:
        raise ValueError(f"origins_w must have at least 2 columns, got shape {tuple(origins.shape)}.")
    return origins[:, :2]


def _coerce_xy_batch(
    xy: torch.Tensor,
    *,
    expected_count: int,
    dtype: torch.dtype,
    device: torch.device,
) -> torch.Tensor:
    values = torch.as_tensor(xy, dtype=dtype, device=device)
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError(f"xy must have shape [N, 2], got {tuple(values.shape)}.")
    if values.shape[0] != expected_count:
        raise ValueError(f"xy must contain {expected_count} rows, got {values.shape[0]}.")
    return values


__all__ = [
    "RuntimeOriginSource",
    "RuntimePlacementProvider",
    "SceneRuntimePlacementProvider",
    "TensorRuntimePlacementProvider",
    "TerrainRuntimeContext",
    "build_scene_runtime_context",
]
