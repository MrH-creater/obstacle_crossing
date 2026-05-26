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
from instinctlab.terrains import TerrainGeneratorCfg
from instinctlab.terrains.trimesh.mesh_terrains_cfg import MotionMatchedTerrainCfg

from obstacle_crossing.config.obstacle_crossing_env_cfg import ObstacleCrossingEnvCfg
from obstacle_crossing.terrain import ContinuousSequenceSamplingCfg, build_default_obstacle_crossing_registry

__file_dir__ = os.path.dirname(os.path.realpath(__file__))
_TERRAIN_DATA_DIR = os.path.abspath(
    os.path.join(__file_dir__, "..", "..", "..", "..", "..", "..", "..", "terrains", "combined")
)
_METADATA_YAML = os.path.join(_TERRAIN_DATA_DIR, "metadata.yaml")

G1_CFG = copy.deepcopy(G1_29DOF_TORSOBASE_POPSICLE_CFG)
G1_CFG.spawn.merge_fixed_joints = True
G1_CFG.init_state.pos = (0.0, 0.0, 0.9)

OBSTACLE_CROSSING_TERRAIN_GEN_CFG = TerrainGeneratorCfg(
    seed=0,
    size=(10.0, 10.0),
    border_width=2.0,
    num_rows=12,
    num_cols=12,
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

OBSTACLE_CROSSING_TERRAIN_GEN_CFG_PLAY = copy.deepcopy(OBSTACLE_CROSSING_TERRAIN_GEN_CFG)
OBSTACLE_CROSSING_TERRAIN_GEN_CFG_PLAY.num_rows = 6
OBSTACLE_CROSSING_TERRAIN_GEN_CFG_PLAY.num_cols = 6

obstacle_crossing_motion_cfg = TerrainMotionCfg(
    path=_TERRAIN_DATA_DIR,
    metadata_yaml=_METADATA_YAML,
    retargetting_func=None,
    motion_start_from_middle_range=[0.0, 0.0],
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
    motion_buffers={"obstacle_crossing": obstacle_crossing_motion_cfg},
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
class G1ObstacleCrossingEnvCfg(ObstacleCrossingEnvCfg):
    """G1-specific obstacle crossing env skeleton.

    Current terrain importer still uses the six-terrain metadata contract. The
    explicit registry-driven multi-sequence layout remains a future wiring step.
    """

    def __post_init__(self):
        super().__post_init__()
        self.scene.terrain.terrain_generator = OBSTACLE_CROSSING_TERRAIN_GEN_CFG
        self.scene.robot = G1_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
        self.scene.robot.actuators = beyondmimic_g1_29dof_delayed_actuators
        self.scene.camera.mesh_prim_paths.extend(get_link_prim_targets(G1_29DOF_LINKS))
        self.scene.motion_reference = motion_reference_cfg

        self.observations.policy.depth_image = None
        self.observations.critic.depth_image = None

        self.episode_length_s = 15.0
        self.terrain_registry = build_default_obstacle_crossing_registry()
        self.sequence_sampling_cfg = ContinuousSequenceSamplingCfg(
            sequence_train_start_iteration=10000,
            sequence_train_ratio_ramp_iterations=20000,
            sequence_train_env_ratio_initial=0.0,
            sequence_train_env_ratio_final=0.30,
            min_sequence_length=2,
            max_sequence_length=6,
            maximum_number_of_terrains=10,
            sequence_sampling_mode="sorted_subset",
            single_train_env_ratio=1.0,
            sequence_length_stage_iterations=5000,
            sequence_length_stage_targets=(2, 4, 6),
            template_refresh_interval_iterations=1000,
            enforce_minimum_one_tile_for_validation_roles=True,
            minimum_tile_rule_max_total_tiles=64,
        )


@configclass
class G1ObstacleCrossingEnvCfg_PLAY(G1ObstacleCrossingEnvCfg):
    def __post_init__(self):
        super().__post_init__()
        self.scene.terrain.terrain_generator = OBSTACLE_CROSSING_TERRAIN_GEN_CFG_PLAY
        self.scene.num_envs = 10
        self.scene.env_spacing = 2.5
        self.episode_length_s = 20.0
        self.viewer = ViewerCfg(
            eye=[4.0, 0.75, 1.0],
            lookat=[0.0, 0.75, 0.0],
            origin_type="asset_root",
            asset_name="robot",
        )
        self.terminations.root_height = None
        self.scene.leg_volume_points.debug_vis = True
        self.commands.base_velocity.debug_vis = True
