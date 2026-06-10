"""Stable package entrypoint for project-local Unitree actuator configs."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ACTUATOR_SOURCE = _REPO_ROOT / "assets" / "unitree_actuator.py"

if not _ACTUATOR_SOURCE.exists():
    raise FileNotFoundError(f"Unable to locate project-local Unitree actuator config: {_ACTUATOR_SOURCE}")

__file__ = str(_ACTUATOR_SOURCE)
exec(compile(_ACTUATOR_SOURCE.read_text(encoding="utf-8"), str(_ACTUATOR_SOURCE), "exec"), globals())

