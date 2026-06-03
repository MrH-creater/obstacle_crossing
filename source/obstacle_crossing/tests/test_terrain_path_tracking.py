from __future__ import annotations

import unittest

import torch

from obstacle_crossing.terrain.terrain_path_tracking import (
    PathTrackingCfg,
    build_tracking_path_cache,
    compute_path_tracking_targets,
    compute_stateful_path_tracking_targets,
    estimate_path_curvature,
    estimate_path_tangents,
    interpolate_path_xy,
    project_point_to_path,
    project_point_to_tracking_cache,
    sample_path_by_spacing,
)
from obstacle_crossing.terrain.terrain_waypoints import WaypointPathRecord


def _path(
    waypoints_xy: tuple[tuple[float, float], ...],
    arc_lengths: tuple[float, ...],
    *,
    lookahead: float = 2.0,
) -> WaypointPathRecord:
    return WaypointPathRecord(
        path_id="test_path",
        frame="local_+Y",
        forward_axis="+Y",
        waypoints_xy=waypoints_xy,
        waypoint_arc_lengths=arc_lengths,
        target_patches=(),
        profile_ranges=(),
        entry_target_xy=waypoints_xy[0],
        exit_target_xy=waypoints_xy[-1],
        default_lookahead_distance=lookahead,
        corridor_half_width=0.5,
    )


class TerrainPathTrackingTest(unittest.TestCase):
    def test_project_point_to_straight_path(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 10.0)), (0.0, 10.0))

        projection = project_point_to_path(torch.tensor([1.0, 2.0]), path)

        self.assertTrue(projection.valid)
        self.assertAlmostEqual(projection.progress_s, 2.0)
        self.assertAlmostEqual(projection.nearest_xy_path[0], 0.0)
        self.assertAlmostEqual(projection.nearest_xy_path[1], 2.0)
        self.assertAlmostEqual(projection.lateral_error, 1.0)
        self.assertEqual(projection.segment_index, 0)

    def test_interpolate_path_xy_clamps_to_end(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 10.0)), (0.0, 10.0))

        self.assertEqual(interpolate_path_xy(path, 99.0), (0.0, 10.0))

    def test_compute_path_tracking_targets_uses_default_lookahead(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 10.0)), (0.0, 10.0), lookahead=2.0)

        result = compute_path_tracking_targets(torch.tensor([[1.0, 2.0]]), [path])

        self.assertTrue(bool(result.valid_mask[0].item()))
        self.assertTrue(torch.allclose(result.progress_s, torch.tensor([2.0])))
        self.assertTrue(torch.allclose(result.target_s, torch.tensor([4.0])))
        self.assertTrue(torch.allclose(result.target_xy_path, torch.tensor([[0.0, 4.0]])))

    def test_compute_path_tracking_targets_clamps_target_at_path_end(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 10.0)), (0.0, 10.0), lookahead=2.0)

        result = compute_path_tracking_targets(torch.tensor([[0.0, 9.5]]), [path])

        self.assertTrue(torch.allclose(result.progress_s, torch.tensor([9.5])))
        self.assertTrue(torch.allclose(result.target_s, torch.tensor([10.0])))
        self.assertTrue(torch.allclose(result.target_xy_path, torch.tensor([[0.0, 10.0]])))

    def test_compute_path_tracking_targets_handles_l_shaped_path(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 5.0), (5.0, 5.0)), (0.0, 5.0, 10.0), lookahead=1.0)

        result = compute_path_tracking_targets(torch.tensor([[2.0, 4.5]]), [path])

        self.assertTrue(torch.allclose(result.progress_s, torch.tensor([7.0])))
        self.assertTrue(torch.allclose(result.nearest_xy_path, torch.tensor([[2.0, 5.0]])))
        self.assertTrue(torch.allclose(result.target_s, torch.tensor([8.0])))
        self.assertTrue(torch.allclose(result.target_xy_path, torch.tensor([[3.0, 5.0]])))
        self.assertEqual(int(result.segment_index[0].item()), 1)

    def test_compute_path_tracking_targets_marks_none_path_invalid(self) -> None:
        result = compute_path_tracking_targets(torch.tensor([[1.0, 2.0]]), [None])

        self.assertFalse(bool(result.valid_mask[0].item()))
        self.assertEqual(int(result.segment_index[0].item()), -1)
        self.assertTrue(torch.allclose(result.target_xy_path, torch.zeros(1, 2)))

    def test_compute_path_tracking_targets_accepts_custom_lookahead(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 10.0)), (0.0, 10.0), lookahead=2.0)

        result = compute_path_tracking_targets(
            torch.tensor([[1.0, 2.0]]),
            [path],
            lookahead_distances=torch.tensor([3.0]),
        )

        self.assertTrue(torch.allclose(result.target_s, torch.tensor([5.0])))
        self.assertTrue(torch.allclose(result.target_xy_path, torch.tensor([[0.0, 5.0]])))

    def test_sample_path_by_spacing_includes_endpoints(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 10.0)), (0.0, 10.0), lookahead=2.0)

        sample_s, sample_xy = sample_path_by_spacing(path, 2.5)

        self.assertEqual(sample_s.shape[0], 5)
        self.assertTrue(torch.allclose(sample_s, torch.tensor([0.0, 2.5, 5.0, 7.5, 10.0])))
        self.assertTrue(torch.allclose(sample_xy[0], torch.tensor([0.0, 0.0])))
        self.assertTrue(torch.allclose(sample_xy[-1], torch.tensor([0.0, 10.0])))

    def test_tracking_cache_tangent_and_curvature(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 5.0), (5.0, 5.0)), (0.0, 5.0, 10.0), lookahead=2.0)
        sample_s, sample_xy = sample_path_by_spacing(path, 1.0)

        tangents = estimate_path_tangents(sample_xy)
        curvature = estimate_path_curvature(tangents, sample_s)

        self.assertTrue(torch.allclose(tangents[0], torch.tensor([0.0, 1.0])))
        self.assertGreater(float(torch.max(curvature).item()), 0.0)

    def test_windowed_projection_prevents_jump_to_nearby_future_segment(self) -> None:
        path = _path(
            ((0.0, 0.0), (0.0, 5.0), (0.2, 5.0), (0.2, 0.0)),
            (0.0, 5.0, 5.2, 10.2),
            lookahead=1.0,
        )
        cfg = PathTrackingCfg(sample_spacing=0.1, backtrack_margin=0.5, forward_search_window=2.0)
        cache = build_tracking_path_cache(path, cfg)

        global_projection = project_point_to_tracking_cache(torch.tensor([0.18, 1.0]), cache)
        windowed_projection = project_point_to_tracking_cache(
            torch.tensor([0.18, 1.0]),
            cache,
            previous_progress_s=1.0,
            cfg=cfg,
        )

        self.assertGreater(global_projection.progress_s, 8.0)
        self.assertLess(windowed_projection.progress_s, 2.0)

    def test_stateful_targets_return_tangent_and_adaptive_lookahead(self) -> None:
        path = _path(((0.0, 0.0), (0.0, 5.0), (5.0, 5.0)), (0.0, 5.0, 10.0), lookahead=2.0)
        cfg = PathTrackingCfg(sample_spacing=0.5, min_lookahead=0.2, max_lookahead=2.0)
        cache = build_tracking_path_cache(path, cfg)

        result = compute_stateful_path_tracking_targets(
            torch.tensor([[0.1, 4.9]]),
            [cache],
            previous_progress_s=torch.tensor([4.8]),
            cfg=cfg,
        )

        self.assertTrue(bool(result.valid_mask[0].item()))
        self.assertEqual(result.target_tangent_xy_path.shape, (1, 2))
        self.assertGreater(float(result.target_s[0].item()), float(result.progress_s[0].item()))
        self.assertLessEqual(float(result.lookahead_distance[0].item()), 2.0)


if __name__ == "__main__":
    unittest.main()
