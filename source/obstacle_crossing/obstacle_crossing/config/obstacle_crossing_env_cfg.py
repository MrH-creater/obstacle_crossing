from __future__ import annotations

import math
from dataclasses import MISSING

import isaaclab.sim as sim_utils
from isaaclab.assets import ArticulationCfg, AssetBaseCfg
from isaaclab.envs import ManagerBasedRLEnvCfg
from isaaclab.managers import CurriculumTermCfg as CurrTerm
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import RewardTermCfg as RewTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.managers import TerminationTermCfg as DoneTerm
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import ContactSensorCfg, RayCasterCfg, patterns
from isaaclab.sensors.ray_caster.patterns import PinholeCameraPatternCfg
from isaaclab.utils import configclass
from isaaclab.utils.assets import ISAAC_NUCLEUS_DIR, ISAACLAB_NUCLEUS_DIR
from isaaclab.utils.noise import AdditiveUniformNoiseCfg as Unoise

import obstacle_crossing.mdp as mdp
from instinctlab.assets.unitree_g1 import beyondmimic_action_scale
from instinctlab.managers import MultiRewardCfg
from instinctlab.motion_reference import MotionReferenceManagerCfg
from instinctlab.sensors import Grid3dPointsGeneratorCfg, NoisyGroupedRayCasterCameraCfg, VolumePointsCfg
from instinctlab.terrains import GreedyconcatEdgeCylinderCfg, TerrainImporterCfg
from instinctlab.utils.noise import CropAndResizeCfg, DepthNormalizationCfg, GaussianBlurNoiseCfg

from ..terrain import (
    DEFAULT_G1_COMMAND_PROFILES,
    DEFAULT_TERRAIN_COLLISION_PROFILES,
    DEFAULT_TERRAIN_PHYSICS_PROFILES,
    build_default_obstacle_crossing_registry,
)
from ..terrain.terrain_specs import ContinuousSequenceSamplingCfg, SequenceEvalCfg
from ..terrain.terrain_registry import DEFAULT_G1_TERRAIN_SPECS
from ..terrain.terrain_specs import ObstacleTerrainSpec

_DEFAULT_REGISTRY = build_default_obstacle_crossing_registry()
_PROFILE_BY_TERRAIN_KEY = {spec.key: spec.command_profile_key for spec in _DEFAULT_REGISTRY.ordered_specs()}


@configclass
class ObstacleCrossingSceneCfg(InteractiveSceneCfg):
    """Scene definition for obstacle crossing.

    The exact terrain generator / importer strategy is supplied by robot-specific
    configs. This base class only fixes the shared sensor surface and terrain
    importer contract.
    """

    terrain = TerrainImporterCfg(
        prim_path="/World/ground",
        terrain_type="generator",
        terrain_generator=MISSING,
        max_init_terrain_level=5,
        collision_group=-1,
        physics_material=sim_utils.RigidBodyMaterialCfg(
            friction_combine_mode="multiply",
            restitution_combine_mode="multiply",
            static_friction=1.0,
            dynamic_friction=1.0,
        ),
        visual_material=sim_utils.MdlFileCfg(
            mdl_path=f"{ISAACLAB_NUCLEUS_DIR}/Materials/TilesMarbleSpiderWhiteBrickBondHoned/TilesMarbleSpiderWhiteBrickBondHoned.mdl",
            project_uvw=True,
            texture_scale=(0.25, 0.25),
        ),
        debug_vis=False,
        virtual_obstacles={
            "edges": GreedyconcatEdgeCylinderCfg(cylinder_radius=0.05, min_points=2),
        },
    )
    robot: ArticulationCfg = MISSING
    left_height_scanner = RayCasterCfg(
        prim_path="{ENV_REGEX_NS}/Robot/left_ankle_roll_link",
        offset=RayCasterCfg.OffsetCfg(pos=(0.04, 0.0, 20.0)),
        ray_alignment="yaw",
        pattern_cfg=patterns.GridPatternCfg(resolution=0.12, size=[0.12, 0.0]),
        debug_vis=False,
        mesh_prim_paths=["/World/ground"],
        update_period=0.02,
    )
    right_height_scanner = RayCasterCfg(
        prim_path="{ENV_REGEX_NS}/Robot/right_ankle_roll_link",
        offset=RayCasterCfg.OffsetCfg(pos=(0.04, 0.0, 20.0)),
        ray_alignment="yaw",
        pattern_cfg=patterns.GridPatternCfg(resolution=0.12, size=[0.12, 0.0]),
        debug_vis=False,
        mesh_prim_paths=["/World/ground"],
        update_period=0.02,
    )
    contact_forces = ContactSensorCfg(prim_path="{ENV_REGEX_NS}/Robot/.*", history_length=3, track_air_time=True)
    leg_volume_points = VolumePointsCfg(
        prim_path="{ENV_REGEX_NS}/Robot/.*_ankle_roll_link",
        points_generator=Grid3dPointsGeneratorCfg(
            x_min=-0.025,
            x_max=0.12,
            x_num=10,
            y_min=-0.03,
            y_max=0.03,
            y_num=5,
            z_min=-0.04,
            z_max=0.0,
            z_num=2,
        ),
        debug_vis=False,
    )
    camera = NoisyGroupedRayCasterCameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot/torso_link",
        mesh_prim_paths=["/World/ground"],
        ray_alignment="yaw",
        pattern_cfg=PinholeCameraPatternCfg(
            focal_length=1.0,
            horizontal_aperture=2 * math.tan(math.radians(89.51) / 2),
            vertical_aperture=2 * math.tan(math.radians(58.29) / 2),
            width=64,
            height=36,
        ),
        debug_vis=False,
        data_types=["distance_to_image_plane"],
        update_period=0.02,
        depth_clipping_behavior="max",
        offset=NoisyGroupedRayCasterCameraCfg.OffsetCfg(
            pos=(0.0487988662332928, 0.01, 0.4378029937970051),
            rot=(0.9135367613482678, 0.004363309284746571, 0.4067366430758002, 0.0),
            convention="world",
        ),
        min_distance=0.1,
        noise_pipeline={
            "crop_and_resize": CropAndResizeCfg(crop_region=(18, 0, 16, 16)),
            "gaussian_blur": GaussianBlurNoiseCfg(kernel_size=3, sigma=1),
            "depth_normalization": DepthNormalizationCfg(depth_range=(0.0, 2.5), normalize=True, output_range=(0.0, 1.0)),
        },
        data_histories={"distance_to_image_plane_noised": 37},
    )
    sky_light = AssetBaseCfg(
        prim_path="/World/skyLight",
        spawn=sim_utils.DomeLightCfg(
            intensity=750.0,
            texture_file=f"{ISAAC_NUCLEUS_DIR}/Materials/Textures/Skies/PolyHaven/kloofendal_43d_clear_puresky_4k.hdr",
        ),
    )
    motion_reference: MotionReferenceManagerCfg = MISSING


@configclass
class ObstacleCrossingObservationsCfg:
    """Observation configuration for obstacle crossing.

    Policy remains sim2real-safe; critic may use privileged terms.
    """

    @configclass
    class PolicyCfg(ObsGroup):
        base_ang_vel = ObsTerm(func=mdp.base_ang_vel, noise=Unoise(n_min=-0.2, n_max=0.2), history_length=8, flatten_history_dim=True, scale=0.25)
        projected_gravity = ObsTerm(func=mdp.projected_gravity, noise=Unoise(n_min=-0.05, n_max=0.05), history_length=8, flatten_history_dim=True)
        velocity_commands = ObsTerm(func=mdp.generated_commands, history_length=8, flatten_history_dim=True, params={"command_name": "base_velocity"}, noise=None)
        joint_pos = ObsTerm(func=mdp.joint_pos_rel, noise=Unoise(n_min=-0.01, n_max=0.01), history_length=8, flatten_history_dim=True)
        joint_vel = ObsTerm(func=mdp.joint_vel_rel, noise=Unoise(n_min=-0.5, n_max=0.5), scale=0.05, history_length=8, flatten_history_dim=True)
        actions = ObsTerm(func=mdp.last_action, history_length=8, flatten_history_dim=True)
        terrain_assignment = ObsTerm(func=mdp.terrain_assignment_debug, noise=None)
        env_role = ObsTerm(func=mdp.env_role_debug, noise=None)
        depth_image = ObsTerm(
            func=mdp.delayed_visualizable_image,
            params={
                "data_type": "distance_to_image_plane_noised_history",
                "sensor_cfg": SceneEntityCfg("camera"),
                "history_skip_frames": 5,
                "num_output_frames": 8,
                "delayed_frame_ranges": (0, 1),
                "debug_vis": False,
            },
            noise=None,
        )

        def __post_init__(self):
            self.enable_corruption = True
            self.concatenate_terms = False

    @configclass
    class CriticCfg(ObsGroup):
        base_lin_vel = ObsTerm(func=mdp.base_lin_vel, history_length=8, flatten_history_dim=True)
        base_ang_vel = ObsTerm(func=mdp.base_ang_vel, history_length=8, flatten_history_dim=True, scale=0.25)
        projected_gravity = ObsTerm(func=mdp.projected_gravity, history_length=8, flatten_history_dim=True)
        velocity_commands = ObsTerm(func=mdp.generated_commands, history_length=8, flatten_history_dim=True, params={"command_name": "base_velocity"}, noise=None)
        joint_pos = ObsTerm(func=mdp.joint_pos_rel, history_length=8, flatten_history_dim=True)
        joint_vel = ObsTerm(func=mdp.joint_vel_rel, scale=0.05, history_length=8, flatten_history_dim=True)
        actions = ObsTerm(func=mdp.last_action, history_length=8, flatten_history_dim=True)
        terrain_assignment = ObsTerm(func=mdp.terrain_assignment_debug, noise=None)
        env_role = ObsTerm(func=mdp.env_role_debug, noise=None)
        depth_image = ObsTerm(
            func=mdp.delayed_visualizable_image,
            params={
                "data_type": "distance_to_image_plane_noised_history",
                "sensor_cfg": SceneEntityCfg("camera"),
                "history_skip_frames": 5,
                "num_output_frames": 8,
                "delayed_frame_ranges": (0, 1),
                "debug_vis": False,
            },
            noise=None,
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = False

    policy: PolicyCfg = PolicyCfg()
    critic: CriticCfg = CriticCfg()


@configclass
class ObstacleCrossingActionsCfg:
    joint_pos = mdp.JointPositionActionCfg(asset_name="robot", joint_names=[".*"], scale=beyondmimic_action_scale, use_default_offset=True)


@configclass
class ObstacleCrossingCommandsCfg:
    base_velocity = mdp.TerrainAwareVelocityCommandCfg(
        asset_name="robot",
        resampling_time_range=(8.0, 12.0),
        debug_vis=False,
        profile_by_terrain_key=_PROFILE_BY_TERRAIN_KEY,
        profiles=DEFAULT_G1_COMMAND_PROFILES,
        target_dis_threshold=0.2,
        only_positive_lin_vel_x=True,
        lin_vel_threshold=0.0,
        ang_vel_threshold=0.0,
        rel_standing_envs=0.05,
    )


@configclass
class ObstacleCrossingRewardTerms:
    track_lin_vel_xy_exp = RewTerm(func=mdp.track_lin_vel_xy_exp, weight=2.0, params={"command_name": "base_velocity", "std": 0.5})
    track_ang_vel_z_exp = RewTerm(func=mdp.track_ang_vel_z_exp, weight=2.0, params={"command_name": "base_velocity", "std": 0.5})
    obstacle_progress = RewTerm(func=mdp.obstacle_progress, weight=1.0)
    volume_points_penetration = RewTerm(func=mdp.volume_points_penetration, weight=-4.0, params={"sensor_cfg": SceneEntityCfg("leg_volume_points")})
    feet_air_time = RewTerm(func=mdp.feet_air_time, weight=0.5, params={"command_name": "base_velocity", "sensor_cfg": SceneEntityCfg("contact_forces", body_names=".*_ankle_roll_link")})
    terrain_profile_bonus = RewTerm(func=mdp.terrain_profile_bonus, weight=0.5)
    sequence_completion_bonus = RewTerm(func=mdp.sequence_completion_bonus, weight=1.0)


@configclass
class ObstacleCrossingRewardsCfg(MultiRewardCfg):
    rewards: ObstacleCrossingRewardTerms = ObstacleCrossingRewardTerms()


@configclass
class ObstacleCrossingTerminationsCfg:
    time_out = DoneTerm(func=mdp.time_out, time_out=True)
    terrain_out_bound = DoneTerm(func=mdp.terrain_out_of_bounds, time_out=True, params={"distance_buffer": 2.0})
    base_contact = DoneTerm(func=mdp.base_contact, params={"sensor_cfg": SceneEntityCfg("contact_forces", body_names="torso_link"), "threshold": 1.0})
    bad_orientation = DoneTerm(func=mdp.bad_orientation, params={"limit_angle": 1.0})
    root_height = DoneTerm(func=mdp.root_height_below_env_origin_minimum, params={"minimum_height": 0.5})
    sequence_exhausted = DoneTerm(func=mdp.sequence_exhausted, time_out=True)


@configclass
class ObstacleCrossingEventCfg:
    initialize_registry = EventTerm(func=mdp.initialize_terrain_registry, mode="startup")
    initialize_layout = EventTerm(func=mdp.initialize_terrain_layout, mode="startup")
    initialize_terrain_physics = EventTerm(func=mdp.initialize_terrain_physics_profiles, mode="startup")
    apply_terrain_physics = EventTerm(func=mdp.apply_terrain_physics_profiles, mode="startup")
    register_virtual_obstacles = EventTerm(func=mdp.register_virtual_obstacles_to_sensors, mode="startup")
    reset_assignments = EventTerm(func=mdp.reset_env_terrain_assignments, mode="reset")
    update_curriculum_stage = EventTerm(func=mdp.update_curriculum_stage, mode="reset")


@configclass
class ObstacleCrossingCurriculumCfg:
    terrain_levels = CurrTerm(func=mdp.terrain_level_curriculum)
    terrain_mix = CurrTerm(func=mdp.terrain_mix_curriculum)
    command_profiles = CurrTerm(func=mdp.command_profile_curriculum)


@configclass
class ObstacleCrossingMonitorCfg:
    pass


@configclass
class ObstacleCrossingEnvCfg(ManagerBasedRLEnvCfg):
    scene: ObstacleCrossingSceneCfg = ObstacleCrossingSceneCfg(num_envs=4096, env_spacing=2.5)
    observations: ObstacleCrossingObservationsCfg = ObstacleCrossingObservationsCfg()
    actions: ObstacleCrossingActionsCfg = ObstacleCrossingActionsCfg()
    commands: ObstacleCrossingCommandsCfg = ObstacleCrossingCommandsCfg()
    rewards: ObstacleCrossingRewardsCfg = ObstacleCrossingRewardsCfg()
    terminations: ObstacleCrossingTerminationsCfg = ObstacleCrossingTerminationsCfg()
    events: ObstacleCrossingEventCfg = ObstacleCrossingEventCfg()
    curriculum: ObstacleCrossingCurriculumCfg = ObstacleCrossingCurriculumCfg()
    monitors: ObstacleCrossingMonitorCfg = ObstacleCrossingMonitorCfg()

    def __post_init__(self):
        self.decimation = 4
        self.episode_length_s = 20.0
        self.sim.dt = 0.005
        self.sim.render_interval = self.decimation
        self.sim.physics_material = self.scene.terrain.physics_material
        self.sim.physx.gpu_max_rigid_patch_count = 10 * 2**15
        self.sim.physx.gpu_collision_stack_size = 2**29
        if self.scene.contact_forces is not None:
            self.scene.contact_forces.update_period = self.sim.dt

        self.terrain_registry = build_default_obstacle_crossing_registry()
        self.terrain_physics_profiles = DEFAULT_TERRAIN_PHYSICS_PROFILES
        self.terrain_collision_profiles = DEFAULT_TERRAIN_COLLISION_PROFILES
        self.sequence_sampling_cfg = ContinuousSequenceSamplingCfg(
            sequence_train_start_iteration=10000,
            sequence_train_ratio_ramp_iterations=20000,
            sequence_train_env_ratio_initial=0.0,
            sequence_train_env_ratio_final=0.30,
            min_sequence_length=2,
            max_sequence_length=6,
            maximum_number_of_terrains=len(DEFAULT_G1_TERRAIN_SPECS),
            sequence_sampling_mode="sorted_subset",
            single_train_env_ratio=1.0,
            sequence_length_stage_iterations=5000,
            sequence_length_stage_targets=(2, 4, 6),
            template_refresh_interval_iterations=1000,
            enforce_minimum_one_tile_for_validation_roles=True,
            minimum_tile_rule_max_total_tiles=64,
        )
        self.sequence_eval_cfg = SequenceEvalCfg(
            enabled=True,
            eval_interval_iterations=1000,
            fixed_benchmark_count=32,
            random_benchmark_count=32,
            min_sequence_length=2,
            max_sequence_length=6,
            maximum_number_of_terrains=len(DEFAULT_G1_TERRAIN_SPECS),
            sequence_sampling_mode="sorted_subset",
            refresh_random_benchmarks_each_eval=True,
        )
