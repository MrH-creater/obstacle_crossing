from __future__ import annotations

from dataclasses import dataclass

import torch

from obstacle_crossing.terrain.terrain_path_tracking import StatefulPathTrackingTargets


_EPS = 1.0e-6


@dataclass(frozen=True)
class PathVelocitySolverCfg:
    """Path-frame velocity blend parameters shared by command and visualization."""

    target_direction_weight: float = 1.0
    tangent_direction_weight: float = 0.65
    lateral_correction_weight: float = 0.75
    max_lin_speed: float = 1.0
    lateral_deadband: float = 0.03
    lateral_error_reference: float = 0.35
    max_lateral_correction_scale: float = 1.0
    eps: float = _EPS

    def __post_init__(self) -> None:
        if self.target_direction_weight < 0.0:
            raise ValueError(
                f"target_direction_weight must be >= 0, got {self.target_direction_weight}."
            )
        if self.tangent_direction_weight < 0.0:
            raise ValueError(
                f"tangent_direction_weight must be >= 0, got {self.tangent_direction_weight}."
            )
        if self.lateral_correction_weight < 0.0:
            raise ValueError(
                f"lateral_correction_weight must be >= 0, got {self.lateral_correction_weight}."
            )
        if self.max_lin_speed < 0.0:
            raise ValueError(f"max_lin_speed must be >= 0, got {self.max_lin_speed}.")
        if self.lateral_deadband < 0.0:
            raise ValueError(f"lateral_deadband must be >= 0, got {self.lateral_deadband}.")
        if self.lateral_error_reference <= 0.0:
            raise ValueError(
                f"lateral_error_reference must be > 0, got {self.lateral_error_reference}."
            )
        if self.max_lateral_correction_scale < 0.0:
            raise ValueError(
                "max_lateral_correction_scale must be >= 0, "
                f"got {self.max_lateral_correction_scale}."
            )
        if self.eps <= 0.0:
            raise ValueError(f"eps must be > 0, got {self.eps}.")


@dataclass(frozen=True)
class PathFrameVelocityCommand:
    """Batched path-frame velocity command and solver debug terms."""

    valid_mask: torch.Tensor
    target_error_xy_path: torch.Tensor
    target_distance: torch.Tensor
    target_direction_xy_path: torch.Tensor
    tangent_direction_xy_path: torch.Tensor
    lateral_correction_direction_xy_path: torch.Tensor
    lateral_correction_scale: torch.Tensor
    blended_direction_xy_path: torch.Tensor
    desired_vel_xy_path: torch.Tensor


def compute_desired_velocity_path_frame(
    robot_xy_path: torch.Tensor,
    tracking_targets: StatefulPathTrackingTargets,
    cfg: PathVelocitySolverCfg | None = None,
) -> PathFrameVelocityCommand:
    """Blend lookahead target, path tangent, and lateral correction into path-frame XY velocity."""
    solver_cfg = cfg or PathVelocitySolverCfg()
    robot_xy = torch.as_tensor(robot_xy_path)
    if not torch.is_floating_point(robot_xy):
        robot_xy = robot_xy.to(dtype=torch.float32)
    _validate_xy_batch(robot_xy, "robot_xy_path")
    _validate_tracking_targets(tracking_targets, robot_xy)

    dtype = robot_xy.dtype
    device = robot_xy.device
    valid_mask = tracking_targets.valid_mask.to(device=device, dtype=torch.bool)
    target_xy = tracking_targets.target_xy_path.to(device=device, dtype=dtype)
    tangent_xy = tracking_targets.target_tangent_xy_path.to(device=device, dtype=dtype)
    nearest_xy = tracking_targets.nearest_xy_path.to(device=device, dtype=dtype)
    lateral_error = tracking_targets.lateral_error.to(device=device, dtype=dtype)
    finite_mask = _finite_rows(
        robot_xy,
        target_xy,
        tangent_xy,
        nearest_xy,
    ) & torch.isfinite(lateral_error)
    valid_mask = valid_mask & finite_mask

    target_error = target_xy - robot_xy
    target_direction, target_distance = _normalize_xy(target_error, eps=solver_cfg.eps)
    tangent_direction, _ = _normalize_xy(tangent_xy, eps=solver_cfg.eps)

    lateral_correction = nearest_xy - robot_xy
    lateral_correction_direction, _ = _normalize_xy(lateral_correction, eps=solver_cfg.eps)
    lateral_correction_scale = _lateral_correction_scale(lateral_error, solver_cfg)

    blended = (
        solver_cfg.target_direction_weight * target_direction
        + solver_cfg.tangent_direction_weight * tangent_direction
        + solver_cfg.lateral_correction_weight * lateral_correction_scale.unsqueeze(-1) * lateral_correction_direction
    )
    blended_direction, blended_norm = _normalize_xy(blended, eps=solver_cfg.eps)
    blended_direction = torch.where(
        (blended_norm > solver_cfg.eps).unsqueeze(-1),
        blended_direction,
        tangent_direction,
    )

    mask = valid_mask.unsqueeze(-1)
    zeros_xy = torch.zeros_like(robot_xy)
    target_direction = torch.where(mask, target_direction, zeros_xy)
    tangent_direction = torch.where(mask, tangent_direction, zeros_xy)
    lateral_correction_direction = torch.where(mask, lateral_correction_direction, zeros_xy)
    blended_direction = torch.where(mask, blended_direction, zeros_xy)
    target_error = torch.where(mask, target_error, zeros_xy)
    lateral_correction_scale = torch.where(
        valid_mask,
        lateral_correction_scale,
        torch.zeros_like(lateral_correction_scale),
    )
    target_distance = torch.where(valid_mask, target_distance, torch.zeros_like(target_distance))
    desired_vel = blended_direction * float(solver_cfg.max_lin_speed)

    return PathFrameVelocityCommand(
        valid_mask=valid_mask,
        target_error_xy_path=target_error,
        target_distance=target_distance,
        target_direction_xy_path=target_direction,
        tangent_direction_xy_path=tangent_direction,
        lateral_correction_direction_xy_path=lateral_correction_direction,
        lateral_correction_scale=lateral_correction_scale,
        blended_direction_xy_path=blended_direction,
        desired_vel_xy_path=desired_vel,
    )


def _validate_xy_batch(value: torch.Tensor, name: str) -> None:
    if value.ndim != 2 or value.shape[1] != 2:
        raise ValueError(f"{name} must have shape [N, 2], got {tuple(value.shape)}.")


def _validate_tracking_targets(targets: StatefulPathTrackingTargets, robot_xy: torch.Tensor) -> None:
    num_envs = robot_xy.shape[0]
    if targets.valid_mask.ndim != 1 or targets.valid_mask.shape[0] != num_envs:
        raise ValueError(
            f"tracking_targets.valid_mask must have shape [{num_envs}], got {tuple(targets.valid_mask.shape)}."
        )
    for name in ("target_xy_path", "target_tangent_xy_path", "nearest_xy_path"):
        value = getattr(targets, name)
        if value.ndim != 2 or value.shape != robot_xy.shape:
            raise ValueError(
                f"tracking_targets.{name} must have shape {tuple(robot_xy.shape)}, "
                f"got {tuple(value.shape)}."
            )
    for name in ("lateral_error",):
        value = getattr(targets, name)
        if value.ndim != 1 or value.shape[0] != num_envs:
            raise ValueError(f"tracking_targets.{name} must have shape [{num_envs}], got {tuple(value.shape)}.")


def _normalize_xy(value: torch.Tensor, *, eps: float) -> tuple[torch.Tensor, torch.Tensor]:
    norm = torch.linalg.norm(value, dim=-1)
    normalized = value / torch.clamp(norm.unsqueeze(-1), min=eps)
    return torch.where((norm > eps).unsqueeze(-1), normalized, torch.zeros_like(value)), norm


def _lateral_correction_scale(lateral_error: torch.Tensor, cfg: PathVelocitySolverCfg) -> torch.Tensor:
    active_error = torch.clamp(lateral_error - float(cfg.lateral_deadband), min=0.0)
    scale = active_error / float(cfg.lateral_error_reference)
    return torch.clamp(scale, min=0.0, max=float(cfg.max_lateral_correction_scale))


def _finite_rows(*values: torch.Tensor) -> torch.Tensor:
    if not values:
        raise ValueError("_finite_rows expects at least one tensor.")
    mask = torch.ones(values[0].shape[0], dtype=torch.bool, device=values[0].device)
    for value in values:
        row_mask = torch.isfinite(value).all(dim=1)
        mask = mask & row_mask.to(device=mask.device)
    return mask


__all__ = [
    "PathFrameVelocityCommand",
    "PathVelocitySolverCfg",
    "compute_desired_velocity_path_frame",
]
