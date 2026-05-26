from obstacle_crossing.terrain import build_default_obstacle_crossing_registry


def main() -> None:
    registry = build_default_obstacle_crossing_registry()
    for spec in registry.ordered_specs():
        print(
            {
                "terrain_id": spec.terrain_id,
                "key": spec.key,
                "terrain_file": spec.terrain_file,
                "motion_file": spec.motion_file,
                "curriculum_rank": spec.curriculum_rank,
                "single_train": spec.enabled_for_single_training,
                "sequence_train": spec.enabled_for_sequence_training,
                "holdout_eval": spec.enabled_for_holdout_validation,
            }
        )


if __name__ == "__main__":
    main()
