# Copyright (c) 2022-2025, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

from dataclasses import MISSING

import torch
from isaaclab.actuators import DelayedPDActuator, DelayedPDActuatorCfg
from isaaclab.utils import configclass
from isaaclab.utils.types import ArticulationActions


class UnitreeActuator(DelayedPDActuator):
    """Delayed PD actuator with Unitree motor torque-speed limits and friction."""
    """Unitree actuator class that implements a torque-speed curve for the actuators.

    The torque-speed curve is defined as follows:

            Torque Limit, N·m
                ^
    Y2──────────|
                |──────────────Y1
                |              │\
                |              │ \
                |              │  \
                |              |   \
    ------------+--------------|------> velocity: rad/s
                              X1   X2

    - Y1: Peak Torque Test (Torque and Speed in the Same Direction)
    - Y2: Peak Torque Test (Torque and Speed in the Opposite Direction)
    - X1: Maximum Speed at Full Torque (T-N Curve Knee Point)
    - X2: No-Load Speed Test

    - Fs: Static friction coefficient
    - Fd: Dynamic friction coefficient
    - Va: Velocity at which the friction is fully activated
    """

    cfg: UnitreeActuatorCfg

    def __init__(self, cfg: UnitreeActuatorCfg, *args, **kwargs):
        super().__init__(cfg, *args, **kwargs)

        self._joint_vel = torch.zeros_like(self.computed_effort)
        self._effort_y1 = self._parse_joint_parameter(cfg.Y1, 1e9)
        self._effort_y2 = self._parse_joint_parameter(cfg.Y2, cfg.Y1)
        self._velocity_x1 = self._parse_joint_parameter(cfg.X1, 1e9)
        self._velocity_x2 = self._parse_joint_parameter(cfg.X2, 1e9)
        self._friction_static = self._parse_joint_parameter(cfg.Fs, 0.0)
        self._friction_dynamic = self._parse_joint_parameter(cfg.Fd, 0.0)
        self._activation_vel = self._parse_joint_parameter(cfg.Va, 0.01)

    def compute(
        self,
        control_action: ArticulationActions,
        joint_pos: torch.Tensor,
        joint_vel: torch.Tensor,
    ) -> ArticulationActions:
        self._joint_vel[:] = joint_vel
        control_action = super().compute(control_action, joint_pos, joint_vel)

        self.applied_effort -= (
            self._friction_static * torch.tanh(joint_vel / self._activation_vel)
            + self._friction_dynamic * joint_vel
        )

        control_action.joint_positions = None
        control_action.joint_velocities = None
        control_action.joint_efforts = self.applied_effort
        return control_action

    def _clip_effort(self, effort: torch.Tensor) -> torch.Tensor:
        same_direction = (self._joint_vel * effort) > 0
        max_effort = torch.where(same_direction, self._effort_y1, self._effort_y2)
        max_effort = torch.where(
            self._joint_vel.abs() < self._velocity_x1,
            max_effort,
            self._compute_effort_limit(max_effort),
        )
        return torch.clip(effort, -max_effort, max_effort)

    def _compute_effort_limit(self, max_effort: torch.Tensor) -> torch.Tensor:
        slope = -max_effort / (self._velocity_x2 - self._velocity_x1)
        limit = slope * (self._joint_vel.abs() - self._velocity_x1) + max_effort
        return limit.clip(min=0.0)


@configclass
class UnitreeActuatorCfg(DelayedPDActuatorCfg):
    """Configuration for Unitree actuators."""

    class_type: type = UnitreeActuator

    X1: float = 1e9
    """Maximum speed at full torque, in rad/s."""

    X2: float = 1e9
    """No-load speed, in rad/s."""

    Y1: float = MISSING
    """Peak torque when torque and speed are in the same direction, in Nm."""

    Y2: float | None = None
    """Peak torque when torque and speed are in opposite directions, in Nm."""

    Fs: float = 0.0
    """Static friction coefficient."""

    Fd: float = 0.0
    """Dynamic friction coefficient."""

    Va: float = 0.01
    """Velocity at which the friction term is fully activated."""


@configclass
class UnitreeActuatorCfg_N7520_14p3(UnitreeActuatorCfg):
    X1 = 22.63
    X2 = 35.52
    Y1 = 71.0
    Y2 = 83.3
    Fs = 1.6
    Fd = 0.16
    armature = 0.01017752


@configclass
class UnitreeActuatorCfg_N7520_22p5(UnitreeActuatorCfg):
    X1 = 14.5
    X2 = 22.7
    Y1 = 111.0
    Y2 = 131.0
    Fs = 2.4
    Fd = 0.24
    armature = 0.025101925


@configclass
class UnitreeActuatorCfg_N5020_16(UnitreeActuatorCfg):
    X1 = 30.86
    X2 = 40.13
    Y1 = 24.8
    Y2 = 31.9
    Fs = 0.6
    Fd = 0.06
    armature = 0.003609725


@configclass
class UnitreeActuatorCfg_W4010_25(UnitreeActuatorCfg):
    X1 = 15.3
    X2 = 24.76
    Y1 = 4.8
    Y2 = 8.6
    Fs = 0.6
    Fd = 0.06
    armature = 0.00425
