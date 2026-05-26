"""Obstacle crossing task package.

This package hosts the long-term task-specific framework for registry-driven
single-terrain training and mixed continuous-terrain validation/training.

Important: this top-level package intentionally does NOT auto-import Isaac Lab /
InstinctLab registration modules. That keeps lightweight utilities such as the
terrain registry and metadata scripts usable without triggering simulator-side
imports. Import `obstacle_crossing.register_envs` explicitly when gym env
registration is needed.
"""
