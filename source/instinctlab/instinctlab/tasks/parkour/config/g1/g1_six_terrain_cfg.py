"""Six-terrain parkour env config for G1 29-DoF.

Derived from `g1_parkour_target_amp_cfg.py`. Key deviations:

- Replaces the ROUGH_TERRAINS (heightfield perlin / pyramid stairs) with a single
  MotionMatchedTerrainCfg sub-terrain that loads the six obstacle STLs via the
  metadata.yaml under `<repo>/terrains/combined/`.
- Replaces the AMASS motion buffer with a TerrainMotionCfg pointed at the same
  metadata.yaml — each of the six terrains gets its own motion file.
- Sim2real-compatible observations: the existing parkour `PolicyCfg` already
  omits GT base linear velocity (kept only in `CriticCfg`), so no further edits
  are needed here.
- Depth camera left enabled but commented out toggle below — keep off for the
  first training pass to fit 4096 envs on a 4090 (24 GB).

Validation entry point:
    python source/standalone/play.py \
        --task=Isaac-G1-SixTerrain-v0 --sample --no_resume

This file only declares the env cfg; gym registration is done in the parkour
config __init__.py (add an entry there separately).
"""
from __future__ import annotations

import copy
import os

from isaaclab.envs import ViewerCfg
from isaaclab.utils import configclass

from instinctlab.assets.unitree_g1 import (
    G1_29DOF_LINKS,
    G1_29DOF_TORSOBASE_POPSICLE_CFG,
    G1_29Dof_TorsoBase_symmetric_augmentation_joint_mapping,
    G1_29Dof_TorsoBase_symmetric_augmentation_joint_reverse_buf,
    beyondmimic_g1_29dof_delayed_actuators,
)
from instinctlab.motion_reference import MotionReferenceManagerCfg
from instinctlab.motion_reference.motion_files.terrain_motion_cfg import TerrainMotionCfg
from instinctlab.motion_reference.utils import motion_interpolate_bilinear
from instinctlab.sensors import get_link_prim_targets
from instinctlab.tasks.parkour.config.parkour_env_cfg import ParkourEnvCfg
from instinctlab.terrains import TerrainGeneratorCfg
from instinctlab.terrains.trimesh.mesh_terrains_cfg import MotionMatchedTerrainCfg

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Repo layout: <repo>/terrains/combined/metadata.yaml references STLs in
# ../centered/ and NPZs in motions/. So `path` is the combined dir itself.
__file_dir__ = os.path.dirname(os.path.realpath(__file__))
_TERRAIN_DATA_DIR = os.path.abspath(
    os.path.join(__file_dir__, "..", "..", "..", "..", "..", "..", "..", "terrains", "combined")
)
_METADATA_YAML = os.path.join(_TERRAIN_DATA_DIR, "metadata.yaml")

# ---------------------------------------------------------------------------
# Robot
# ---------------------------------------------------------------------------
G1_CFG = copy.deepcopy(G1_29DOF_TORSOBASE_POPSICLE_CFG)
G1_CFG.spawn.merge_fixed_joints = True
G1_CFG.init_state.pos = (0.0, 0.0, 0.9)

# ---------------------------------------------------------------------------
# Terrain — single MotionMatchedTerrainCfg sub-terrain. The motion-matched
# loader internally rotates through the 6 STLs based on `difficulty`. With
# `curriculum=True`, each row in the terrain grid gets a difficulty step,
# letting easy obstacles dominate early training.
# ---------------------------------------------------------------------------
SIX_TERRAIN_GEN_CFG = TerrainGeneratorCfg(
    seed=0,
    size=(10.0, 10.0),       # each sub-terrain tile size (m); STLs are <8m in either axis
    border_width=2.0,
    num_rows=12,             # difficulty levels — spreads the 6 terrains across rows
    num_cols=12,             # parallel envs per difficulty level
    horizontal_scale=0.05,
    vertical_scale=0.005,
    slope_threshold=1.0,
    use_cache=False,
    curriculum=True,
    sub_terrains={
        "motion_matched": MotionMatchedTerrainCfg(
            proportion=1.0,
            path=_TERRAIN_DATA_DIR,
            metadata_yaml=_METADATA_YAML,
        ),
    },
)

# Play-mode generator: fewer tiles, no walls. Used by the *_PLAY variant.
SIX_TERRAIN_GEN_CFG_PLAY = copy.deepcopy(SIX_TERRAIN_GEN_CFG)
SIX_TERRAIN_GEN_CFG_PLAY.num_rows = 6
SIX_TERRAIN_GEN_CFG_PLAY.num_cols = 6

# ---------------------------------------------------------------------------
# Motion reference — TerrainMotionCfg replaces the AMASS buffer. Each motion
# is bound to a terrain_id via metadata.yaml; the manager places envs on the
# matching sub-terrain origin.
# ---------------------------------------------------------------------------
six_terrain_motion_cfg = TerrainMotionCfg(
    path=_TERRAIN_DATA_DIR,
    metadata_yaml=_METADATA_YAML,
    retargetting_func=None,
    motion_start_from_middle_range=[0.0, 0.0],   # always start from first frame for stay_still
    motion_start_height_offset=0.0,
    ensure_link_below_zero_ground=False,
    buffer_device="output_device",
    motion_interpolate_func=motion_interpolate_bilinear,
    velocity_estimation_method="frontward",
    max_origins_per_motion=16,
)

motion_reference_cfg = MotionReferenceManagerCfg(
    prim_path="{ENV_REGEX_NS}/Robot/torso_link",
    robot_model_path=G1_CFG.spawn.asset_path,
    reference_prim_path="/World/envs/env_.*/RobotReference/torso_link",
    symmetric_augmentation_link_mapping=[0, 1, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10, 13, 12],
    symmetric_augmentation_joint_mapping=G1_29Dof_TorsoBase_symmetric_augmentation_joint_mapping,
    symmetric_augmentation_joint_reverse_buf=G1_29Dof_TorsoBase_symmetric_augmentation_joint_reverse_buf,
    frame_interval_s=0.02,
    update_period=0.02,
    num_frames=10,
    motion_buffers={
        "six_terrain": six_terrain_motion_cfg,
    },
    link_of_interests=[
        "pelvis",
        "torso_link",
        "left_shoulder_roll_link",
        "right_shoulder_roll_link",
        "left_elbow_link",
        "right_elbow_link",
        "left_wrist_yaw_link",
        "right_wrist_yaw_link",
        "left_hip_roll_link",
        "right_hip_roll_link",
        "left_knee_link",
        "right_knee_link",
        "left_ankle_roll_link",
        "right_ankle_roll_link",
    ],
    mp_split_method="Even",
)


@configclass
class G1SixTerrainEnvCfg(ParkourEnvCfg):
    """Training env: 4096 envs across 12×12 motion-matched terrain grid."""

    def __post_init__(self):
        super().__post_init__()

        # Scene
        self.scene.terrain.terrain_generator = SIX_TERRAIN_GEN_CFG
        self.scene.robot = G1_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
        # Use the delayed actuator model from day 1 — sim2real requires control
        # delay to be baked into training, not bolted on later.
        self.scene.robot.actuators = beyondmimic_g1_29dof_delayed_actuators
        self.scene.camera.mesh_prim_paths.extend(get_link_prim_targets(G1_29DOF_LINKS))
        self.scene.motion_reference = motion_reference_cfg

        # Disable depth camera observation for the first training pass to keep
        # 4096 envs viable on 24 GB. Re-enable by removing these two lines once
        # height-scan-only policy is verified.
        self.observations.policy.depth_image = None
        self.observations.critic.depth_image = None

        # Episode length: each tile is 10 m, the obstacle is <8 m. ~15 s gives
        # the policy time to enter, traverse, and recover before reset.
        self.episode_length_s = 15.0


@configclass
class G1SixTerrainEnvCfg_PLAY(G1SixTerrainEnvCfg):
    """Visualization / sanity-check env: 10 envs, no walls, debug vis on."""

    def __post_init__(self):
        super().__post_init__()
        self.scene.terrain.terrain_generator = SIX_TERRAIN_GEN_CFG_PLAY
        self.scene.num_envs = 10
        self.scene.env_spacing = 2.5
        self.episode_length_s = 20.0

        self.viewer = ViewerCfg(
            eye=[4.0, 0.75, 1.0],
            lookat=[0.0, 0.75, 0.0],
            origin_type="asset_root",
            asset_name="robot",
        )

        # Don't terminate on root height drop during inspection.
        self.terminations.root_height = None

        # Debug viz for sensors/commands.
        self.scene.leg_volume_points.debug_vis = True
        self.commands.base_velocity.debug_vis = True

        # Don't randomize physics or initial joint pose in play.
        self.events.physics_material = None
        self.events.reset_robot_joints.params = {
            "position_range": (0.0, 0.0),
            "velocity_range": (0.0, 0.0),
        }
