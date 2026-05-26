# obstacle_crossing

`obstacle_crossing` is a standalone task library built on top of Isaac Lab and InstinctLab for Unitree G1 humanoid obstacle-crossing research.

## Current scope

This repository currently contains:

- a standalone `obstacle_crossing` Python package under `source/obstacle_crossing/`
- a copied `source/instinctlab/` dependency snapshot used during development
- terrain/task organization based on registry, layout, and assignment abstractions
- single-terrain training plus curriculum-based sequence-train design
- independent periodic sequence evaluation design
- sim2real-oriented observation and control constraints

## Repository layout

- `source/obstacle_crossing/` — standalone obstacle_crossing library
- `source/instinctlab/` — copied InstinctLab dependency snapshot
- `scripts/` — helper scripts for registry, metadata, inspection, and training workflow
- `terrains/` — terrain assets and project framework notes
- `docker/` — container-related helper files copied from the working environment

## Notes

This repository was split out from a larger InstinctLab working tree. Inherited root-level repository documents from that source project were intentionally removed or replaced so this repository can serve as the dedicated home for `obstacle_crossing`.
