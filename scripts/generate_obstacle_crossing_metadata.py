import yaml

from obstacle_crossing.terrain import build_default_obstacle_crossing_registry


def main() -> None:
    registry = build_default_obstacle_crossing_registry()
    terrains, motion_files = registry.build_metadata_rows()
    payload = {
        "terrains": terrains,
        "motion_files": motion_files,
    }
    print(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
