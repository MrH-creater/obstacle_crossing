"""Load a centered STL terrain into Isaac Sim for visual inspection.

This mimics how instinct's motion_matched_terrain loads STL files —
it applies the same convention: XOY ground plane, Z-up, bottom at Z=0.

Usage (run from InstinctLab/ directory in Isaac Sim Python environment):
    # 查看单个地形
    python scripts/visualize_terrain.py terrains/centered/6.Spiral\ Staircase.stl
    # 或查看任意地形
    python scripts/visualize_terrain.py terrains/centered/1.Continuous\ Ramp.stl

Controls in the Isaac Sim viewport:
    Left mouse drag  = rotate view
    Middle mouse drag = pan
    Scroll           = zoom
    Ctrl+C in terminal = exit
"""

import argparse
import os
import sys

parser = argparse.ArgumentParser()
parser.add_argument("stl_path", type=str, help="Path to the centered STL file")
parser.add_argument("--headless", action="store_true", default=False)
args_cli, unknown = parser.parse_known_args()

# Launch Isaac Sim first (before any other imports)
from isaaclab.app import AppLauncher

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# Now we can import the rest
import numpy as np
import trimesh
import omni.usd
from pxr import Usd, UsdGeom, UsdShade, UsdLux, Sdf, Vt, Gf


def create_material(stage: Usd.Stage, mtl_path: str, color: tuple, roughness: float = 0.7) -> UsdShade.Material:
    """Create a UsdPreviewSurface material with the given diffuse color."""
    mtl = UsdShade.Material.Define(stage, mtl_path)
    shader = UsdShade.Shader.Define(stage, f"{mtl_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    mtl.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mtl


def bind_material(prim: Usd.Prim, mtl: UsdShade.Material):
    """Bind a material to a mesh prim."""
    UsdShade.MaterialBindingAPI(prim).Bind(mtl)


def load_stl_as_usd_mesh(
    stage: Usd.Stage, stl_path: str, prim_path: str = "/World/terrain",
    color: tuple = (0.55, 0.55, 0.55),
):
    """Load an STL file and create a USD Mesh prim with material."""
    mesh = trimesh.load(stl_path, force="mesh")
    print(f"Loaded STL: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
    print(f"  BBox min: {mesh.bounds[0]}")
    print(f"  BBox max: {mesh.bounds[1]}")
    print(f"  Size:     {mesh.bounds[1] - mesh.bounds[0]}")
    print(f"  Z range:  [{mesh.bounds[0][2]:.3f}, {mesh.bounds[1][2]:.3f}]")

    # Check centering
    center_xy = ((mesh.bounds[0][0] + mesh.bounds[1][0]) / 2,
                 (mesh.bounds[0][1] + mesh.bounds[1][1]) / 2)
    z_min = mesh.bounds[0][2]
    if abs(center_xy[0]) > 0.1 or abs(center_xy[1]) > 0.1:
        print(f"  WARNING: XY center=({center_xy[0]:.2f}, {center_xy[1]:.2f}), not at origin!")
    if abs(z_min) > 0.01:
        print(f"  WARNING: Z_min={z_min:.3f}, not at zero! Terrain may float or sink.")

    # Create USD mesh
    usd_mesh = UsdGeom.Mesh.Define(stage, prim_path)

    # Vertices
    points = Vt.Vec3fArray([Gf.Vec3f(float(v[0]), float(v[1]), float(v[2])) for v in mesh.vertices])
    usd_mesh.CreatePointsAttr(points)

    # Faces
    face_vertex_counts = Vt.IntArray([3] * len(mesh.faces))
    face_vertex_indices = Vt.IntArray([int(x) for x in mesh.faces.flatten()])
    usd_mesh.CreateFaceVertexCountsAttr(face_vertex_counts)
    usd_mesh.CreateFaceVertexIndicesAttr(face_vertex_indices)

    # Let Hydra compute normals (subdivisionScheme=none + orientation=rightHanded is default)
    usd_mesh.CreateSubdivisionSchemeAttr("none")
    usd_mesh.CreateDoubleSidedAttr(True)

    # Create material and bind it
    mtl = create_material(stage, f"{prim_path}/material", color=color)
    bind_material(usd_mesh.GetPrim(), mtl)

    return mesh


def add_ground_grid(stage: Usd.Stage, size: float = 20.0):
    """Add a visual reference plane on the XOY plane."""
    ground_path = "/World/ground_plane"
    ground = UsdGeom.Mesh.Define(stage, ground_path)

    half = size / 2
    z = -0.005
    verts = Vt.Vec3fArray([
        Gf.Vec3f(-half, -half, z),
        Gf.Vec3f( half, -half, z),
        Gf.Vec3f( half,  half, z),
        Gf.Vec3f(-half,  half, z),
    ])
    ground.CreatePointsAttr(verts)
    ground.CreateFaceVertexCountsAttr(Vt.IntArray([4]))
    ground.CreateFaceVertexIndicesAttr(Vt.IntArray([0, 1, 2, 3]))
    ground.CreateSubdivisionSchemeAttr("none")
    ground.CreateDoubleSidedAttr(True)

    mtl = create_material(stage, f"{ground_path}/material", color=(0.22, 0.22, 0.22), roughness=1.0)
    bind_material(ground.GetPrim(), mtl)

    print(f"Added ground reference plane: {size}x{size}m at Z={z}")


def add_lighting(stage: Usd.Stage):
    """Add dome light for ambient illumination."""
    dome = UsdLux.DomeLight.Define(stage, "/World/dome_light")
    dome.CreateIntensityAttr(500.0)
    print("Added dome light (intensity=500)")


def main():
    stl_path = os.path.abspath(args_cli.stl_path)
    if not os.path.exists(stl_path):
        print(f"[ERROR] File not found: {stl_path}")
        return

    stl_name = os.path.splitext(os.path.basename(stl_path))[0]
    print("=" * 60)
    print(f"Visualizing: {stl_name}")
    print("=" * 60)

    # Get Isaac Sim's existing USD stage via omni.usd
    stage = omni.usd.get_context().get_stage()

    # Set stage metadata
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    # Ensure /World exists
    world_path = "/World"
    if not stage.GetPrimAtPath(world_path):
        UsdGeom.Xform.Define(stage, world_path)
        stage.SetDefaultPrim(stage.GetPrimAtPath(world_path))

    # Add lighting
    add_lighting(stage)

    # Load the STL mesh
    load_stl_as_usd_mesh(stage, stl_path, "/World/terrain")

    # Add a ground reference
    add_ground_grid(stage)

    # Print the scene structure
    print("\n--- USD Stage Structure ---")
    for prim in stage.Traverse():
        print(f"  {prim.GetPath()}  [{prim.GetTypeName()}]")

    print("\n" + "=" * 60)
    print("[READY] Terrain loaded. The Isaac Sim window should now be visible.")
    print("Look around with mouse controls:")
    print("  Left drag   = orbit")
    print("  Middle drag = pan")
    print("  Scroll      = zoom")
    print("  F key       = frame selection")
    print("Press Ctrl+C in this terminal to exit.")
    print("=" * 60)

    # Keep the simulation running
    try:
        while simulation_app.is_running():
            simulation_app.update()
    except KeyboardInterrupt:
        print("\n[EXIT] Shutting down...")

    simulation_app.close()


if __name__ == "__main__":
    main()
