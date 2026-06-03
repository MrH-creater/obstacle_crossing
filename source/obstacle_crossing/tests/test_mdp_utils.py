from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from obstacle_crossing.terrain.terrain_assignment import (
    EnvTerrainAssignmentView,
    ObstacleTileAssignmentRecord,
    ObstacleTileAssignmentTable,
)
from obstacle_crossing.terrain.terrain_registry import build_default_obstacle_crossing_registry
from obstacle_crossing.terrain.terrain_waypoints import build_single_terrain_waypoint_record


def _load_mdp_utils():
    module_path = PACKAGE_ROOT / "obstacle_crossing" / "mdp" / "utils.py"
    spec = importlib.util.spec_from_file_location("_obstacle_crossing_mdp_utils_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load mdp utils module from {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_mdp_utils = _load_mdp_utils()


def _assignment_view(num_envs: int = 2) -> EnvTerrainAssignmentView:
    registry = build_default_obstacle_crossing_registry()
    spec = registry.get(0)
    path = build_single_terrain_waypoint_record(spec).path
    tile_record = ObstacleTileAssignmentRecord(
        tile_index=0,
        role="single_train",
        assignment_kind="single",
        terrain_ids=(spec.terrain_id,),
        terrain_keys=(spec.key,),
        command_profile_keys=(spec.command_profile_key,),
        required_capabilities=spec.required_capabilities,
        physics_profile_keys=(spec.physics_profile_key,),
        collision_profile_keys=(spec.collision_profile_key,),
        sequence_length=1,
        sequence_id=None,
        segment_ranges_y=(),
        buffer_ranges_y=(),
        sequence_total_length_y=None,
        template_geometry_path=None,
        template_metadata_path=None,
        waypoint_path=path,
    )
    tile_table = ObstacleTileAssignmentTable(registry=registry, tile_records=[tile_record])
    return EnvTerrainAssignmentView(
        registry=registry,
        tile_table=tile_table,
        env_to_tile_index=torch.zeros(num_envs, dtype=torch.long),
    )


class MdpUtilsTest(unittest.TestCase):
    def test_assignment_query_helpers_delegate_to_assignment_view(self) -> None:
        env = SimpleNamespace(terrain_assignment_view=_assignment_view())

        terrain_ids = _mdp_utils.get_env_terrain_ids(env)
        terrain_keys = _mdp_utils.get_env_terrain_keys(env, torch.tensor([1]))
        profile_keys = _mdp_utils.get_env_command_profile_keys(env, torch.tensor([0]))
        roles = _mdp_utils.get_env_roles(env)

        self.assertTrue(torch.equal(terrain_ids, torch.tensor([[0], [0]])))
        self.assertEqual(terrain_keys, [("continuous_ramp",)])
        self.assertEqual(profile_keys, [("straight",)])
        self.assertEqual(roles, ["single_train", "single_train"])

    def test_resolve_terrain_runtime_context_builds_scene_backed_context(self) -> None:
        assignment_view = _assignment_view()
        env = SimpleNamespace(
            terrain_assignment_view=assignment_view,
            scene=SimpleNamespace(
                terrain=SimpleNamespace(env_origins=torch.tensor([[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]])),
            ),
        )

        context = _mdp_utils.resolve_terrain_runtime_context(env, validate_origin_consistency=False)

        self.assertIs(context.assignment_view, assignment_view)
        self.assertIs(getattr(env, "terrain_runtime_context"), context)
        self.assertTrue(torch.allclose(context.origin_provider.origins_for_envs(), torch.tensor([[1.0, 2.0], [3.0, 4.0]])))


if __name__ == "__main__":
    unittest.main()
