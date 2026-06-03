from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from obstacle_crossing.terrain.terrain_path_tracking import StatefulPathTrackingTargets


def _load_path_velocity_math():
    module_path = PACKAGE_ROOT / "obstacle_crossing" / "mdp" / "commands" / "path_velocity_math.py"
    spec = importlib.util.spec_from_file_location("_obstacle_crossing_path_velocity_math_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load path velocity math module from {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_path_velocity_math = _load_path_velocity_math()
PathVelocitySolverCfg = _path_velocity_math.PathVelocitySolverCfg
compute_desired_velocity_path_frame = _path_velocity_math.compute_desired_velocity_path_frame


def _targets(
    *,
    valid_mask: torch.Tensor | None = None,
    nearest_xy_path: torch.Tensor | None = None,
    lateral_error: torch.Tensor | None = None,
    target_xy_path: torch.Tensor | None = None,
    target_tangent_xy_path: torch.Tensor | None = None,
) -> StatefulPathTrackingTargets:
    valid = torch.tensor([True]) if valid_mask is None else valid_mask
    count = valid.shape[0]
    zeros = torch.zeros(count)
    zeros_xy = torch.zeros(count, 2)
    return StatefulPathTrackingTargets(
        valid_mask=valid,
        progress_s=zeros,
        nearest_xy_path=zeros_xy if nearest_xy_path is None else nearest_xy_path,
        lateral_error=zeros if lateral_error is None else lateral_error,
        signed_lateral_error=zeros,
        segment_index=torch.full((count,), -1, dtype=torch.long),
        lookahead_distance=zeros,
        target_s=zeros,
        target_xy_path=zeros_xy if target_xy_path is None else target_xy_path,
        target_tangent_xy_path=zeros_xy if target_tangent_xy_path is None else target_tangent_xy_path,
    )


class PathVelocityMathTest(unittest.TestCase):
    def test_target_direction_can_drive_velocity(self) -> None:
        robot_xy = torch.tensor([[1.0, 2.0]])
        targets = _targets(
            nearest_xy_path=torch.tensor([[0.0, 2.0]]),
            lateral_error=torch.tensor([1.0]),
            target_xy_path=torch.tensor([[0.0, 3.0]]),
            target_tangent_xy_path=torch.tensor([[0.0, 1.0]]),
        )
        cfg = PathVelocitySolverCfg(
            target_direction_weight=1.0,
            tangent_direction_weight=0.0,
            lateral_correction_weight=0.0,
            max_lin_speed=2.0,
        )

        result = compute_desired_velocity_path_frame(robot_xy, targets, cfg)

        expected_direction = torch.tensor([[-0.70710677, 0.70710677]])
        self.assertTrue(torch.allclose(result.target_direction_xy_path, expected_direction, atol=1.0e-6))
        self.assertTrue(torch.allclose(result.desired_vel_xy_path, expected_direction * 2.0, atol=1.0e-6))

    def test_tangent_and_lateral_correction_blend(self) -> None:
        robot_xy = torch.tensor([[1.0, 2.0]])
        targets = _targets(
            nearest_xy_path=torch.tensor([[0.0, 2.0]]),
            lateral_error=torch.tensor([1.0]),
            target_xy_path=torch.tensor([[0.0, 3.0]]),
            target_tangent_xy_path=torch.tensor([[0.0, 1.0]]),
        )
        cfg = PathVelocitySolverCfg(
            target_direction_weight=0.0,
            tangent_direction_weight=1.0,
            lateral_correction_weight=1.0,
            lateral_deadband=0.0,
            lateral_error_reference=1.0,
            max_lin_speed=1.0,
        )

        result = compute_desired_velocity_path_frame(robot_xy, targets, cfg)

        expected_direction = torch.tensor([[-0.70710677, 0.70710677]])
        self.assertTrue(torch.allclose(result.lateral_correction_direction_xy_path, torch.tensor([[-1.0, 0.0]])))
        self.assertTrue(torch.allclose(result.lateral_correction_scale, torch.tensor([1.0])))
        self.assertTrue(torch.allclose(result.blended_direction_xy_path, expected_direction, atol=1.0e-6))

    def test_invalid_target_masks_outputs_to_zero(self) -> None:
        robot_xy = torch.tensor([[1.0, 2.0]])
        targets = _targets(
            valid_mask=torch.tensor([False]),
            nearest_xy_path=torch.tensor([[0.0, 2.0]]),
            lateral_error=torch.tensor([1.0]),
            target_xy_path=torch.tensor([[0.0, 3.0]]),
            target_tangent_xy_path=torch.tensor([[0.0, 1.0]]),
        )

        result = compute_desired_velocity_path_frame(robot_xy, targets)

        self.assertFalse(bool(result.valid_mask[0].item()))
        self.assertTrue(torch.allclose(result.desired_vel_xy_path, torch.zeros(1, 2)))
        self.assertTrue(torch.allclose(result.blended_direction_xy_path, torch.zeros(1, 2)))

    def test_zero_target_error_falls_back_to_tangent(self) -> None:
        robot_xy = torch.tensor([[0.0, 2.0]])
        targets = _targets(
            nearest_xy_path=torch.tensor([[0.0, 2.0]]),
            lateral_error=torch.tensor([0.0]),
            target_xy_path=torch.tensor([[0.0, 2.0]]),
            target_tangent_xy_path=torch.tensor([[0.0, 1.0]]),
        )
        cfg = PathVelocitySolverCfg(
            target_direction_weight=1.0,
            tangent_direction_weight=0.0,
            lateral_correction_weight=0.0,
            max_lin_speed=0.8,
        )

        result = compute_desired_velocity_path_frame(robot_xy, targets, cfg)

        self.assertTrue(torch.allclose(result.target_direction_xy_path, torch.zeros(1, 2)))
        self.assertTrue(torch.allclose(result.blended_direction_xy_path, torch.tensor([[0.0, 1.0]])))
        self.assertTrue(torch.allclose(result.desired_vel_xy_path, torch.tensor([[0.0, 0.8]])))

    def test_validates_batch_shapes(self) -> None:
        targets = _targets()

        with self.assertRaisesRegex(ValueError, "robot_xy_path must have shape"):
            compute_desired_velocity_path_frame(torch.tensor([0.0, 1.0]), targets)

    def test_promotes_integer_robot_input_to_float(self) -> None:
        robot_xy = torch.tensor([[0, 2]])
        targets = _targets(
            nearest_xy_path=torch.tensor([[0.0, 2.0]]),
            lateral_error=torch.tensor([0.0]),
            target_xy_path=torch.tensor([[0.0, 3.0]]),
            target_tangent_xy_path=torch.tensor([[0.0, 1.0]]),
        )

        result = compute_desired_velocity_path_frame(robot_xy, targets)

        self.assertTrue(torch.is_floating_point(result.desired_vel_xy_path))
        self.assertTrue(torch.allclose(result.desired_vel_xy_path, torch.tensor([[0.0, 1.0]])))

    def test_rejects_negative_weights(self) -> None:
        with self.assertRaisesRegex(ValueError, "target_direction_weight"):
            PathVelocitySolverCfg(target_direction_weight=-1.0)


if __name__ == "__main__":
    unittest.main()
