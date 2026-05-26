from obstacle_crossing.terrain import (
    ContinuousSequenceSamplingCfg,
    ObstacleTerrainLayoutBuilder,
    build_default_obstacle_crossing_registry,
)


def main() -> None:
    registry = build_default_obstacle_crossing_registry()
    builder = ObstacleTerrainLayoutBuilder()
    sampling_cfg = ContinuousSequenceSamplingCfg(
        validation_env_start_iteration=10000,
        validation_ratio_ramp_iterations=20000,
        min_sequence_length=2,
        max_sequence_length=6,
        maximum_number_of_terrains=10,
        sequence_sampling_mode="sorted_subset",
    )
    print("Registry loaded with", len(registry.ordered_specs()), "terrains")
    print("Sampling cfg:", sampling_cfg)
    print("Layout builder ready:", builder.__class__.__name__)
    print("TODO: implement layout sampling and pretty-print the sampled terrain grid.")


if __name__ == "__main__":
    main()
