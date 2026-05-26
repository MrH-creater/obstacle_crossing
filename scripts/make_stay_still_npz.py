"""Generate stay-still placeholder NPZs for the six-terrain training scene.

These NPZs satisfy the schema expected by `AmassMotion._read_retargetted_motion_file`
(see `instinctlab/motion_reference/motion_files/amass_motion.py`):

    framerate   : float, scalar
    joint_names : 1-D array of joint name strings (must match isaac_joint_names)
    joint_pos   : (N_frames, N_joints) float32, radians
    base_pos_w  : (N_frames, 3) float32, world-frame base position
    base_quat_w : (N_frames, 4) float32, world-frame base quaternion in (w, x, y, z)

The placeholder is a static pose held for `--duration` seconds. Once the training
pipeline is validated end-to-end, replace each NPZ with a real retargetted motion
(AMASS retarget, Isaac Sim keyframe export, or mocap retarget). Keep the file names
fixed — they are referenced by `terrains/combined/metadata.yaml`.

Usage:
    python scripts/make_stay_still_npz.py
    python scripts/make_stay_still_npz.py --duration 4.0 --framerate 50
"""
from __future__ import annotations

import argparse
import os

import numpy as np

# G1 29-DoF joint names. MUST match the articulation order used in
# instinctlab.assets.unitree_g1 (see beyondmimic_g1_29dof_actuators).
G1_29DOF_JOINT_NAMES = [
    "left_hip_pitch_joint",
    "left_hip_roll_joint",
    "left_hip_yaw_joint",
    "left_knee_joint",
    "left_ankle_pitch_joint",
    "left_ankle_roll_joint",
    "right_hip_pitch_joint",
    "right_hip_roll_joint",
    "right_hip_yaw_joint",
    "right_knee_joint",
    "right_ankle_pitch_joint",
    "right_ankle_roll_joint",
    "waist_yaw_joint",
    "waist_roll_joint",
    "waist_pitch_joint",
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
]

# Output file names — fixed contract with terrains/combined/metadata.yaml.
TERRAIN_MOTION_NAMES = [
    "ramp",
    "symmetrical_ramp",
    "cross_slope",
    "s_curve",
    "hurdling",
    "slalom",
]

# Pose used for the stay-still placeholder. The base sits at the terrain origin
# (the terrain mesh origin is at the top surface, per MotionMatchedTerrainCfg
# docstring), with the robot standing upright facing +X (identity quaternion).
DEFAULT_BASE_HEIGHT_M = 0.78        # G1 pelvis height at default joint pose
DEFAULT_BASE_QUAT_WXYZ = (1.0, 0.0, 0.0, 0.0)

# Default joint angles in radians. Mostly zero; small bends in hip/knee/ankle
# match the URDF "default" pose used by the env's joint position action offset.
# Keep this conservative — the policy will learn around it, the placeholder
# just needs to be a feasible stance.
G1_DEFAULT_JOINT_POS_RAD = {
    # Slight crouch so the robot doesn't reset into a perfectly stiff pose.
    "left_hip_pitch_joint":  -0.20,
    "left_knee_joint":        0.40,
    "left_ankle_pitch_joint": -0.20,
    "right_hip_pitch_joint": -0.20,
    "right_knee_joint":       0.40,
    "right_ankle_pitch_joint": -0.20,
    # Arms in a neutral hanging pose.
    "left_shoulder_pitch_joint":  0.20,
    "right_shoulder_pitch_joint": 0.20,
    "left_elbow_joint":           0.30,
    "right_elbow_joint":          0.30,
}


def build_default_joint_pos(joint_names: list[str]) -> np.ndarray:
    pose = np.zeros(len(joint_names), dtype=np.float32)
    for i, name in enumerate(joint_names):
        pose[i] = G1_DEFAULT_JOINT_POS_RAD.get(name, 0.0)
    return pose


def make_stay_still_npz(
    out_path: str,
    joint_names: list[str],
    framerate: float,
    duration_s: float,
    base_height: float,
    base_quat_wxyz: tuple[float, float, float, float],
) -> None:
    n_frames = max(int(round(framerate * duration_s)), 2)
    n_joints = len(joint_names)

    default_pose = build_default_joint_pos(joint_names)  # (J,)
    joint_pos = np.broadcast_to(default_pose, (n_frames, n_joints)).copy()

    base_pos_w = np.zeros((n_frames, 3), dtype=np.float32)
    base_pos_w[:, 2] = base_height

    base_quat_w = np.tile(
        np.asarray(base_quat_wxyz, dtype=np.float32), (n_frames, 1)
    )

    np.savez(
        out_path,
        framerate=np.float32(framerate),
        joint_names=np.asarray(joint_names, dtype=object),
        joint_pos=joint_pos.astype(np.float32),
        base_pos_w=base_pos_w.astype(np.float32),
        base_quat_w=base_quat_w.astype(np.float32),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "terrains", "combined", "motions",
        ),
        help="Directory to write the placeholder NPZ files.",
    )
    parser.add_argument("--framerate", type=float, default=50.0, help="Frames per second.")
    parser.add_argument("--duration", type=float, default=2.0, help="Total seconds per file.")
    parser.add_argument(
        "--base-height", type=float, default=DEFAULT_BASE_HEIGHT_M,
        help="World-frame Z of the base in meters.",
    )
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    for name in TERRAIN_MOTION_NAMES:
        out_path = os.path.join(args.out_dir, f"{name}_retargetted.npz")
        make_stay_still_npz(
            out_path=out_path,
            joint_names=G1_29DOF_JOINT_NAMES,
            framerate=args.framerate,
            duration_s=args.duration,
            base_height=args.base_height,
            base_quat_wxyz=DEFAULT_BASE_QUAT_WXYZ,
        )
        n_frames = max(int(round(args.framerate * args.duration)), 2)
        print(f"wrote {out_path}  frames={n_frames}  joints={len(G1_29DOF_JOINT_NAMES)}")


if __name__ == "__main__":
    main()
