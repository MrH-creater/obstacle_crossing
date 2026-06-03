from __future__ import annotations

from types import SimpleNamespace
import unittest

import torch

from obstacle_crossing.terrain.terrain_runtime import (
    SceneRuntimePlacementProvider,
    TensorRuntimePlacementProvider,
)


class TerrainRuntimeTest(unittest.TestCase):
    def test_tensor_provider_round_trip_all_envs(self) -> None:
        provider = TensorRuntimePlacementProvider(
            torch.tensor(
                [
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [0.0, 10.0],
                ]
            )
        )
        local_xy = torch.tensor([[1.0, 2.0], [3.0, 4.0], [-1.0, 5.0]])

        world_xy = provider.local_to_world_xy(None, local_xy)
        recovered_local = provider.world_to_local_xy(None, world_xy)

        self.assertTrue(torch.allclose(world_xy, torch.tensor([[1.0, 2.0], [13.0, 4.0], [-1.0, 15.0]])))
        self.assertTrue(torch.allclose(recovered_local, local_xy))

    def test_tensor_provider_supports_env_id_subset(self) -> None:
        provider = TensorRuntimePlacementProvider(
            torch.tensor(
                [
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [0.0, 10.0],
                ]
            )
        )
        env_ids = torch.tensor([2, 0])
        local_xy = torch.tensor([[1.0, 1.0], [2.0, 2.0]])

        world_xy = provider.local_to_world_xy(env_ids, local_xy)

        self.assertTrue(torch.allclose(world_xy, torch.tensor([[1.0, 11.0], [2.0, 2.0]])))
        self.assertTrue(torch.allclose(provider.yaws_for_envs(env_ids), torch.zeros(2)))

    def test_scene_provider_prefers_terrain_origins_in_auto_mode(self) -> None:
        env = SimpleNamespace(
            scene=SimpleNamespace(
                env_origins=torch.tensor([[100.0, 100.0, 0.0], [200.0, 200.0, 0.0]]),
                terrain=SimpleNamespace(env_origins=torch.tensor([[0.0, 1.0, 0.0], [2.0, 3.0, 0.0]])),
            )
        )
        provider = SceneRuntimePlacementProvider(env, source="auto")

        self.assertTrue(torch.allclose(provider.origins_for_envs(), torch.tensor([[0.0, 1.0], [2.0, 3.0]])))

    def test_scene_provider_can_read_scene_origins(self) -> None:
        env = SimpleNamespace(
            scene=SimpleNamespace(
                env_origins=torch.tensor([[4.0, 5.0, 0.0], [6.0, 7.0, 0.0]]),
                terrain=SimpleNamespace(),
            )
        )
        provider = SceneRuntimePlacementProvider(env, source="scene")

        self.assertTrue(torch.allclose(provider.origins_for_envs(torch.tensor([1])), torch.tensor([[6.0, 7.0]])))

    def test_scene_provider_consistency_check_rejects_mismatch(self) -> None:
        env = SimpleNamespace(
            scene=SimpleNamespace(
                env_origins=torch.tensor([[0.0, 0.0, 0.0]]),
                terrain=SimpleNamespace(env_origins=torch.tensor([[1.0, 0.0, 0.0]])),
            )
        )
        provider = SceneRuntimePlacementProvider(env)

        with self.assertRaisesRegex(ValueError, "disagree"):
            provider.validate_origin_consistency()


if __name__ == "__main__":
    unittest.main()
