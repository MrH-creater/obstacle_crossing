"""Stable package entrypoint for project-local Unitree robot configs.

The canonical robot resources currently live in the repository-level
``assets/`` directory because motion files, URDFs, and meshes are shared with
terrain metadata. This module gives installed obstacle_crossing code a stable
``obstacle_crossing.assets.unitree`` import path without depending on the
process working directory.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_UNITREE_SOURCE = _REPO_ROOT / "assets" / "unitree.py"

if not _UNITREE_SOURCE.exists():
    raise FileNotFoundError(f"Unable to locate project-local Unitree config: {_UNITREE_SOURCE}")

__file__ = str(_UNITREE_SOURCE)
exec(compile(_UNITREE_SOURCE.read_text(encoding="utf-8"), str(_UNITREE_SOURCE), "exec"), globals())

