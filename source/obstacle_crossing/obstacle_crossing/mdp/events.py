from __future__ import annotations

"""Runtime event hooks for obstacle_crossing.

This module is the lifecycle bridge between:

- static configuration (`env.cfg`)
- terrain semantic infrastructure (registry / layout / sequence pool / assignment)
- scene-backed runtime placement state (`env.scene.*`)
- downstream MDP consumers (command / observations / rewards / terminations / curriculums)

V1 scope
--------
This implementation intentionally operates in **logical bootstrap** mode:

- It builds and attaches registry-driven terrain assignment/runtime state.
- It does **not** yet bind assignments back to authoritative physical terrain
  tile/type/template state exposed by the terrain importer.
- Weak hooks are kept for terrain-physics application and virtual-obstacle
  sensor registration so future extensions have stable integration points.

Design rules
------------
1. Startup events attach long-lived objects.
2. Reset events refresh lightweight state and assignment/runtime bindings.
3. Events expose state; they do not implement downstream business logic such as
   observations, rewards, terminations, path tracking, or velocity solving.
4. Command-line arguments are not parsed here. This module only consumes the
   already-resolved runtime/config state on ``env`` / ``env.cfg``.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any
import warnings

import torch

from ..terrain.sequence_pool_scheduler import SequencePoolOrchestrator
from ..terrain.terrain_assignment import EnvTerrainAssignmentView
from ..terrain.terrain_layout import ObstacleTerrainLayoutBuilder
from ..terrain.terrain_registry import ObstacleTerrainRegistry, build_default_obstacle_crossing_registry
from ..terrain.terrain_runtime import TerrainRuntimeContext, build_scene_runtime_context

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def initialize_terrain_registry(env: ManagerBasedRLEnv) -> None:
    """Attach the obstacle terrain registry and baseline profile dictionaries.

    Inputs / sources
    ----------------
    - ``env.terrain_registry`` / ``env.obstacle_terrain_registry`` if already attached
    - ``env.cfg.terrain_registry`` if provided by the config
    - fallback: ``build_default_obstacle_crossing_registry()``
    - ``env.cfg.terrain_physics_profiles`` / ``env.cfg.terrain_collision_profiles``
      if present; otherwise generated from the registry

    Responsibilities
    ----------------
    - Resolve the registry object that acts as the authoritative terrain
      semantic dictionary.
    - Attach terrain physics/collision profile dictionaries so later startup
      hooks and downstream modules can query stable mappings.
    - Mark the current binding mode as ``logical_bootstrap`` to make it explicit
      that V1 assignment/runtime state is semantic rather than physical-authoritative.

    Side effects on ``env``
    -----------------------
    - ``env.terrain_registry``
    - ``env.obstacle_terrain_registry`` (compatibility alias)
    - ``env.terrain_physics_profiles``
    - ``env.terrain_collision_profiles``
    - ``env.terrain_binding_mode = 'logical_bootstrap'``
    - ``env.terrain_scene_binding_available = False``
    """
    registry = _resolve_or_build_registry(env)
    env.terrain_registry = registry
    env.obstacle_terrain_registry = registry

    env.terrain_physics_profiles = getattr(env, "terrain_physics_profiles", None) or _first_existing_attr(
        getattr(env, "cfg", None),
        "terrain_physics_profiles",
    ) or registry.build_physics_profiles()
    env.terrain_collision_profiles = getattr(env, "terrain_collision_profiles", None) or _first_existing_attr(
        getattr(env, "cfg", None),
        "terrain_collision_profiles",
    ) or registry.build_collision_profiles()

    env.terrain_binding_mode = "logical_bootstrap"
    env.terrain_scene_binding_available = False


def initialize_terrain_layout(env: ManagerBasedRLEnv) -> None:
    """Build and attach the startup terrain layout / assignment / runtime bundle.

    Inputs / sources
    ----------------
    - Registry: resolved via :func:`_resolve_or_build_registry`
    - Physics/collision dictionaries: ensured via
      :func:`initialize_terrain_physics_profiles`
    - Sequence sampling config: ``env.cfg.sequence_sampling_cfg``
    - Seed: resolved via :func:`_resolve_seed`
    - Env count: resolved via :func:`_resolve_num_envs`
    - Terrain grid shape: resolved via :func:`_resolve_grid_shape`

    Responsibilities
    ----------------
    - Create/attach the long-lived layout builder.
    - Create/attach the long-lived sequence pool orchestrator.
    - Build the startup sequence pool using ``iteration=0`` semantics.
    - Build startup role counts for single-train / sequence-train allocation.
    - Build the single-train layout used by the V1 bootstrap assignment flow.
    - Create the initial ``EnvTerrainAssignmentView``.
    - Create or attach the initial ``TerrainRuntimeContext``.
    - Store initial curriculum state derived from the sequence scheduler decision.

    Notes
    -----
    This function performs **logical bootstrap assignment**, not physical terrain
    authoritative binding. A future version can sync assignment back from
    ``env.scene.terrain`` authoritative terrain identifiers.

    Side effects on ``env``
    -----------------------
    - ``env.current_iteration``
    - ``env.terrain_layout_builder``
    - ``env.sequence_pool_orchestrator``
    - ``env.sequence_template_pool``
    - ``env.terrain_role_counts``
    - ``env.terrain_layouts``
    - ``env.sequence_pool_version``
    - curriculum state fields via :func:`_store_curriculum_state`
    - runtime/assignment fields via :func:`_attach_or_update_runtime_context`
    - ``env.terrain_assignment_binding_mode = 'logical_bootstrap'``
    - ``env.terrain_scene_binding_available = False``
    """
    registry = _resolve_or_build_registry(env)
    initialize_terrain_physics_profiles(env)

    sampling_cfg = _require_attr(getattr(env, "cfg", None), "sequence_sampling_cfg")
    seed = _resolve_seed(env)
    num_envs = _resolve_num_envs(env)
    grid_rows, grid_cols = _resolve_grid_shape(env)
    layout_builder = _resolve_or_create_layout_builder(env)
    orchestrator = _resolve_or_create_sequence_pool_orchestrator(env)

    # Startup uses iteration=0 semantics. Runtime iterations are handled later
    # by ``update_curriculum_stage`` during reset.
    env.current_iteration = 0
    decision = orchestrator.scheduler.build_decision(
        iteration=0,
        sampling_cfg=sampling_cfg,
        current_manifest_exists=orchestrator.current_pool_manifest_path().exists(),
    )
    sequence_pool = orchestrator.ensure_active_training_pool(
        registry=registry,
        iteration=0,
        sampling_cfg=sampling_cfg,
        seed=seed,
    )
    role_counts = layout_builder.build_training_role_counts(
        total_tiles=num_envs,
        iteration=0,
        sampling_cfg=sampling_cfg,
    )
    single_layout = layout_builder.build_single_terrain_layout(
        registry=registry,
        num_rows=grid_rows,
        num_cols=grid_cols,
        seed=seed,
    )
    assignment_view = EnvTerrainAssignmentView.from_role_counts_and_active_pool(
        registry=registry,
        single_layout=single_layout,
        sequence_pool=sequence_pool,
        role_counts=role_counts,
        num_envs=num_envs,
        seed=seed,
        sequence_role="sequence_train",
    )

    env.terrain_layout_builder = layout_builder
    env.sequence_pool_orchestrator = orchestrator
    env.sequence_template_pool = sequence_pool
    env.terrain_role_counts = role_counts
    env.terrain_layouts = {"single_train": single_layout}
    env.sequence_pool_version = 1
    _store_curriculum_state(env, decision, refresh_reason=sequence_pool.refresh_reason)
    _attach_or_update_runtime_context(env, assignment_view)
    env.terrain_assignment_binding_mode = "logical_bootstrap"
    env.terrain_scene_binding_available = False


def initialize_terrain_physics_profiles(env: ManagerBasedRLEnv) -> None:
    """Attach terrain physics/collision profile lookup maps.

    Inputs / sources
    ----------------
    - Registry: resolved via :func:`_resolve_or_build_registry`
    - Existing env-attached profile dictionaries, if present
    - ``env.cfg.terrain_physics_profiles`` / ``env.cfg.terrain_collision_profiles``
    - fallback: registry-generated dictionaries

    Responsibilities
    ----------------
    - Ensure the physics/collision dictionaries exist on ``env``.
    - Derive terrain-key -> physics-profile-key and terrain-key ->
      collision-profile-key lookup tables.
    - Record initialization status so later hooks know that mappings are ready,
      even though V1 does not yet apply them to scene terrain prims.

    Side effects on ``env``
    -----------------------
    - ``env.terrain_physics_profiles``
    - ``env.terrain_collision_profiles``
    - ``env.terrain_physics_profile_by_key``
    - ``env.terrain_collision_profile_by_key``
    - ``env.terrain_physics_profiles_initialized = True``
    - ``env.terrain_physics_profiles_apply_status``
    """
    registry = _resolve_or_build_registry(env)
    physics_profiles = getattr(env, "terrain_physics_profiles", None) or _first_existing_attr(
        getattr(env, "cfg", None),
        "terrain_physics_profiles",
    ) or registry.build_physics_profiles()
    collision_profiles = getattr(env, "terrain_collision_profiles", None) or _first_existing_attr(
        getattr(env, "cfg", None),
        "terrain_collision_profiles",
    ) or registry.build_collision_profiles()

    env.terrain_physics_profiles = physics_profiles
    env.terrain_collision_profiles = collision_profiles
    env.terrain_physics_profile_by_key = registry.build_physics_profile_by_terrain_key()
    env.terrain_collision_profile_by_key = registry.build_collision_profile_by_terrain_key()
    env.terrain_physics_profiles_initialized = True
    env.terrain_physics_profiles_apply_status = getattr(env, "terrain_physics_profiles_apply_status", "initialized_not_applied")


def apply_terrain_physics_profiles(env: ManagerBasedRLEnv) -> None:
    """Weak V1 hook for terrain-physics application.

    Inputs / sources
    ----------------
    - Depends on :func:`initialize_terrain_physics_profiles` to ensure profile
      dictionaries and lookup maps are attached.

    Responsibilities
    ----------------
    - In V1, **do not** attempt to mutate terrain prims or PhysX materials.
    - Instead, clearly mark that physics/collision profiles are available but
      not yet applied to the scene terrain objects.
    - Emit a one-time warning to make the limitation explicit during bring-up.

    Side effects on ``env``
    -----------------------
    - ``env.terrain_physics_profiles_apply_status = 'skipped_v1'``
    - one-time warning flag ``env._terrain_physics_apply_warned``
    """
    initialize_terrain_physics_profiles(env)
    env.terrain_physics_profiles_apply_status = "skipped_v1"
    _warn_once(
        env,
        "_terrain_physics_apply_warned",
        "apply_terrain_physics_profiles is a V1 no-op; terrain physics/collision profiles are initialized but not applied to scene terrain prims yet.",
    )


def register_virtual_obstacles_to_sensors(env: ManagerBasedRLEnv) -> None:
    """Weak V1 hook for future sensor registration.

    Inputs / sources
    ----------------
    - ``env.scene.terrain`` for terrain-owned virtual obstacle handles
    - ``env.scene.leg_volume_points`` as the first candidate sensor consumer
    - optional sensor methods:
      - ``register_virtual_obstacles``
      - ``register_virtual_obstacle``

    Responsibilities
    ----------------
    - Detect whether scene terrain and the expected sensor are available.
    - If a compatible registration API exists, attempt to register virtual
      obstacles.
    - Otherwise, record a status code and emit a one-time warning.

    V1 intentionally keeps this weak / extensible:
    - no hard failure when the API is absent
    - no assumption that volume points is the only future sensor consumer

    Side effects on ``env``
    -----------------------
    - ``env.virtual_obstacle_sensor_registration_status`` with one of:
      - ``registered``
      - ``missing_scene_terrain``
      - ``missing_leg_volume_points_sensor``
      - ``no_supported_sensor_api``
      - ``api_detected_not_implemented``
    - one-time warning flag ``env._virtual_obstacle_registration_warned``
    """
    scene = getattr(env, "scene", None)
    terrain = getattr(scene, "terrain", None)
    sensor = getattr(scene, "leg_volume_points", None)

    status = "skipped_v1"
    if terrain is None:
        status = "missing_scene_terrain"
    elif sensor is None:
        status = "missing_leg_volume_points_sensor"
    else:
        virtual_obstacles = getattr(terrain, "virtual_obstacles", None)
        register_fn = _first_callable_attr(sensor, "register_virtual_obstacles", "register_virtual_obstacle")
        if virtual_obstacles and register_fn is not None:
            try:
                register_fn(virtual_obstacles)
                status = "registered"
            except Exception:
                status = "api_detected_not_implemented"
        elif register_fn is None:
            status = "no_supported_sensor_api"

    env.virtual_obstacle_sensor_registration_status = status
    if status != "registered":
        _warn_once(
            env,
            "_virtual_obstacle_registration_warned",
            f"register_virtual_obstacles_to_sensors is operating in V1 weak mode; status='{status}'.",
        )


def reset_env_terrain_assignments(
    env: ManagerBasedRLEnv,
    env_ids: torch.Tensor | None = None,
) -> None:
    """Refresh logical terrain assignment/runtime state during reset.

    Parameters
    ----------
    env:
        The runtime RL environment instance.
    env_ids:
        Reserved for future partial-reset support. V1 accepts the parameter to
        keep the public API shape stable, but currently ignores it and rebuilds
        the logical assignment for the whole env set.

    Inputs / sources
    ----------------
    - ``env.terrain_role_counts`` and ``env.sequence_template_pool`` prepared by
      :func:`update_curriculum_stage`
    - registry / seed / num_envs / grid shape helper resolution
    - the existing layout builder attached at startup

    Responsibilities
    ----------------
    - Rebuild the current logical single-train layout.
    - Rebuild the registry-driven ``EnvTerrainAssignmentView`` using the latest
      role counts and sequence template pool.
    - Update the runtime context **in place** so downstream modules keep a stable
      object reference while assignment content/version changes.
    - Re-assert that binding mode is still ``logical_bootstrap``.

    Future extension point
    ----------------------
    This function is the natural place to add authoritative physical terrain
    binding later, e.g. by calling a future
    ``assignment_view.sync_from_env_terrain_indices(...)`` once scene terrain
    tile/type/template identifiers are finalized.

    Side effects on ``env``
    -----------------------
    - ``env.terrain_layouts``
    - ``env.terrain_assignment_view``
    - ``env.terrain_runtime_context`` (created or updated)
    - ``env.terrain_assignment_version``
    - ``env.terrain_runtime_context_version``
    - ``env.terrain_assignment_binding_mode``
    - ``env.terrain_scene_binding_available``
    """
    del env_ids

    # V1 reset assumes curriculum has already run first. If required runtime
    # state is missing, recover by computing curriculum state eagerly.
    if not hasattr(env, "terrain_role_counts") or not hasattr(env, "sequence_template_pool"):
        update_curriculum_stage(env)

    registry = _resolve_or_build_registry(env)
    seed = _resolve_seed(env)
    num_envs = _resolve_num_envs(env)
    grid_rows, grid_cols = _resolve_grid_shape(env)
    layout_builder = _resolve_or_create_layout_builder(env)
    role_counts = _require_attr(env, "terrain_role_counts")
    sequence_pool = _require_attr(env, "sequence_template_pool")

    single_layout = layout_builder.build_single_terrain_layout(
        registry=registry,
        num_rows=grid_rows,
        num_cols=grid_cols,
        seed=seed,
    )
    assignment_view = EnvTerrainAssignmentView.from_role_counts_and_active_pool(
        registry=registry,
        single_layout=single_layout,
        sequence_pool=sequence_pool,
        role_counts=role_counts,
        num_envs=num_envs,
        seed=seed,
        sequence_role="sequence_train",
    )
    env.terrain_layouts = {"single_train": single_layout}
    _attach_or_update_runtime_context(env, assignment_view)
    env.terrain_assignment_binding_mode = "logical_bootstrap"
    env.terrain_scene_binding_available = False


def update_curriculum_stage(
    env: ManagerBasedRLEnv,
    env_ids: torch.Tensor | None = None,
) -> None:
    """Update sequence curriculum state before reset-time assignment refresh.

    Parameters
    ----------
    env:
        The runtime RL environment instance.
    env_ids:
        Reserved for future partial-reset support. V1 accepts the parameter to
        keep the public API stable but does not yet perform partial updates.

    Inputs / sources
    ----------------
    - registry resolved from env / env.cfg
    - ``env.cfg.sequence_sampling_cfg``
    - runtime env count, seed, and training iteration
    - the startup-attached layout builder and sequence pool orchestrator

    Responsibilities
    ----------------
    - Resolve the current training iteration using runtime-first semantics.
    - Query the sequence scheduler for the current decision
      (enabled / ratio / active length range / refresh requirement).
    - Ensure the current sequence pool is available and refresh it if needed.
    - Recompute terrain role counts for the current stage.
    - Store curriculum state fields on ``env`` for downstream consumers.
    - Maintain ``sequence_pool_version`` so later caches can detect refreshes.

    Side effects on ``env``
    -----------------------
    - ``env.current_iteration``
    - ``env.sequence_template_pool``
    - ``env.terrain_role_counts``
    - ``env.sequence_pool_version``
    - all fields written by :func:`_store_curriculum_state`
    """
    del env_ids

    registry = _resolve_or_build_registry(env)
    sampling_cfg = _require_attr(getattr(env, "cfg", None), "sequence_sampling_cfg")
    num_envs = _resolve_num_envs(env)
    seed = _resolve_seed(env)
    layout_builder = _resolve_or_create_layout_builder(env)
    orchestrator = _resolve_or_create_sequence_pool_orchestrator(env)

    # ``iteration`` is treated as runtime-authoritative state. This function does
    # not read command-line arguments directly; it only consumes already-resolved
    # runtime/cfg state.
    iteration = _resolve_training_iteration(env)
    env.current_iteration = iteration

    decision = orchestrator.scheduler.build_decision(
        iteration=iteration,
        sampling_cfg=sampling_cfg,
        current_manifest_exists=orchestrator.current_pool_manifest_path().exists(),
    )
    previous_pool_signature = _pool_signature(getattr(env, "sequence_template_pool", None))
    sequence_pool = orchestrator.ensure_active_training_pool(
        registry=registry,
        iteration=iteration,
        sampling_cfg=sampling_cfg,
        seed=seed,
    )
    current_pool_signature = _pool_signature(sequence_pool)
    if previous_pool_signature != current_pool_signature:
        env.sequence_pool_version = int(getattr(env, "sequence_pool_version", 0)) + 1
    else:
        env.sequence_pool_version = int(getattr(env, "sequence_pool_version", 0))

    role_counts = layout_builder.build_training_role_counts(
        total_tiles=num_envs,
        iteration=iteration,
        sampling_cfg=sampling_cfg,
    )

    env.sequence_template_pool = sequence_pool
    env.terrain_role_counts = role_counts
    _store_curriculum_state(env, decision, refresh_reason=sequence_pool.refresh_reason)


def _resolve_or_build_registry(env: Any) -> ObstacleTerrainRegistry:
    """Resolve the authoritative terrain registry from env / cfg or build a default.

    Resolution order
    ----------------
    1. ``env.terrain_registry`` / ``env.obstacle_terrain_registry``
    2. ``env.cfg.terrain_registry``
    3. fallback ``build_default_obstacle_crossing_registry()``

    Why this helper exists
    ----------------------
    - Keeps public event functions small and consistent.
    - Centralizes V1 bootstrap behavior.
    - Ensures a registry always exists before later event hooks run.
    """
    registry = _first_existing_attr(
        env,
        "terrain_registry",
        "obstacle_terrain_registry",
    )
    if isinstance(registry, ObstacleTerrainRegistry):
        return registry

    cfg = getattr(env, "cfg", None)
    registry = _first_existing_attr(cfg, "terrain_registry")
    if isinstance(registry, ObstacleTerrainRegistry):
        return registry

    registry = build_default_obstacle_crossing_registry()
    setattr(env, "terrain_registry", registry)
    setattr(env, "obstacle_terrain_registry", registry)
    return registry


def _resolve_seed(env: Any) -> int:
    """Resolve the effective random seed from already-applied env/cfg state.

    Important
    ---------
    This helper does **not** parse command-line arguments directly. If a CLI has
    overridden the seed, that override should already have been written into the
    final ``env`` / ``env.cfg`` object before events run.

    Resolution order
    ----------------
    1. ``env.seed`` / ``env.random_seed``
    2. ``env.unwrapped.seed`` / ``env.unwrapped.random_seed``
    3. ``env.cfg.seed`` / ``env.cfg.random_seed``
    4. fallback ``0``
    """
    for owner in (env, getattr(env, "unwrapped", None), getattr(env, "cfg", None)):
        if owner is None:
            continue
        for name in ("seed", "random_seed"):
            value = getattr(owner, name, None)
            if value is not None:
                return int(value)
    return 0


def _resolve_num_envs(env: Any) -> int:
    """Resolve the authoritative number of env instances.

    Resolution principle
    --------------------
    ``num_envs`` should prefer *runtime-realized state* over config literals.
    In other words, if the scene already exposes env origins, that runtime count
    is more authoritative than the original user/CLI request.

    Resolution order
    ----------------
    1. ``env.scene.env_origins`` row count
    2. ``env.scene.terrain.env_origins`` row count
    3. ``env.num_envs``
    4. ``env.cfg.scene.num_envs``

    Raises
    ------
    RuntimeError
        If no reasonable source of env count can be found.
    """
    scene = getattr(env, "scene", None)
    scene_env_origins = getattr(scene, "env_origins", None)
    if scene_env_origins is not None:
        return int(torch.as_tensor(scene_env_origins).shape[0])

    terrain = getattr(scene, "terrain", None)
    terrain_env_origins = getattr(terrain, "env_origins", None)
    if terrain_env_origins is not None:
        return int(torch.as_tensor(terrain_env_origins).shape[0])

    num_envs = getattr(env, "num_envs", None)
    if num_envs is not None:
        return int(num_envs)

    cfg = getattr(env, "cfg", None)
    scene_cfg = getattr(cfg, "scene", None)
    num_envs = getattr(scene_cfg, "num_envs", None)
    if num_envs is not None:
        return int(num_envs)

    raise RuntimeError("Unable to resolve num_envs from runtime env or cfg.")


def _resolve_grid_shape(env: Any) -> tuple[int, int]:
    """Resolve terrain grid shape from the terrain generator config.

    Required config path
    --------------------
    ``env.cfg.scene.terrain.terrain_generator.num_rows``
    ``env.cfg.scene.terrain.terrain_generator.num_cols``

    Why this helper exists
    ----------------------
    The startup/reset assignment flow rebuilds the single-train logical layout.
    That requires a stable notion of terrain grid shape even in fake-env tests.
    """
    cfg = getattr(env, "cfg", None)
    scene_cfg = _require_attr(cfg, "scene")
    terrain_cfg = _require_attr(scene_cfg, "terrain")
    generator_cfg = _require_attr(terrain_cfg, "terrain_generator")
    num_rows = int(_require_attr(generator_cfg, "num_rows"))
    num_cols = int(_require_attr(generator_cfg, "num_cols"))
    if num_rows <= 0 or num_cols <= 0:
        raise ValueError(f"terrain_generator num_rows/num_cols must be > 0, got ({num_rows}, {num_cols}).")
    return num_rows, num_cols


def _resolve_training_iteration(env: Any) -> int:
    """Resolve the current training iteration using runtime-first semantics.

    Formal rule
    -----------
    Command-line arguments are *not* read here. If the launcher uses CLI flags to
    override the training iteration, that override should already be reflected in
    ``env`` / ``env.cfg``.

    Priority order
    --------------
    1. explicit runtime training iteration fields:
       - ``current_training_iteration``
       - ``training_iteration``
       - ``global_iteration``
    2. runtime step counter:
       - ``common_step_counter``
    3. general fallback iteration field:
       - ``current_iteration``
    4. fallback ``0``

    Rationale
    ---------
    ``iteration`` is a runtime state variable used by curriculum logic. It should
    prefer the environment's authoritative runtime counters rather than static
    configuration values.
    """
    for owner in (env, getattr(env, "unwrapped", None), getattr(env, "cfg", None)):
        if owner is None:
            continue
        for name in (
            "current_training_iteration",
            "training_iteration",
            "global_iteration",
        ):
            value = getattr(owner, name, None)
            if value is not None:
                return int(value)

    step_counter = getattr(env, "common_step_counter", None)
    if step_counter is not None:
        return int(step_counter)

    for owner in (env, getattr(env, "unwrapped", None), getattr(env, "cfg", None)):
        if owner is None:
            continue
        value = getattr(owner, "current_iteration", None)
        if value is not None:
            return int(value)

    return 0


def _resolve_or_create_layout_builder(env: Any) -> ObstacleTerrainLayoutBuilder:
    """Resolve or create the long-lived layout builder attached to ``env``.

    The layout builder is treated as a startup-owned helper object that can be
    reused across resets. It is intentionally lightweight and deterministic.
    """
    layout_builder = getattr(env, "terrain_layout_builder", None)
    if isinstance(layout_builder, ObstacleTerrainLayoutBuilder):
        return layout_builder
    layout_builder = ObstacleTerrainLayoutBuilder()
    env.terrain_layout_builder = layout_builder
    return layout_builder


def _resolve_or_create_sequence_pool_orchestrator(env: Any) -> SequencePoolOrchestrator:
    """Resolve or create the long-lived sequence pool orchestrator.

    Inputs / sources
    ----------------
    Reads optional runtime/config overrides from:
    - ``sequence_pool_train_root``
    - ``sequence_pool_template_count``
    - ``terrain_data_root``
    - ``sequence_pool_input_backend``
    - ``sequence_pool_output_backend``

    Responsibilities
    ----------------
    - Centralize sequence pool IO/refresh policy.
    - Avoid rebuilding scheduler/orchestrator objects every reset.
    - Keep future pool refresh behavior encapsulated outside the public event
      hooks.
    """
    orchestrator = getattr(env, "sequence_pool_orchestrator", None)
    if isinstance(orchestrator, SequencePoolOrchestrator):
        return orchestrator

    cfg = getattr(env, "cfg", None)
    train_pool_root = _first_existing_attr(env, "sequence_pool_train_root") or _first_existing_attr(
        cfg,
        "sequence_pool_train_root",
    )
    template_count = _first_existing_attr(env, "sequence_pool_template_count") or _first_existing_attr(
        cfg,
        "sequence_pool_template_count",
    ) or 16
    terrain_root = _first_existing_attr(env, "terrain_data_root") or _first_existing_attr(
        cfg,
        "terrain_data_root",
    )
    input_backend = _first_existing_attr(env, "sequence_pool_input_backend") or _first_existing_attr(
        cfg,
        "sequence_pool_input_backend",
    ) or "stl"
    output_backend = _first_existing_attr(env, "sequence_pool_output_backend") or _first_existing_attr(
        cfg,
        "sequence_pool_output_backend",
    ) or "stl"

    if terrain_root is not None:
        terrain_root = Path(terrain_root)

    orchestrator = SequencePoolOrchestrator(
        train_pool_root=train_pool_root,
        template_count=int(template_count),
        terrain_root=terrain_root,
        input_backend=str(input_backend),
        output_backend=str(output_backend),
    )
    env.sequence_pool_orchestrator = orchestrator
    return orchestrator


def _attach_or_update_runtime_context(env: Any, assignment_view: EnvTerrainAssignmentView) -> TerrainRuntimeContext:
    """Create or in-place update ``TerrainRuntimeContext``.

    Why in-place update matters
    ---------------------------
    Downstream modules (especially command and future caches) may keep references
    to ``env.terrain_runtime_context``. Replacing the whole object every reset can
    lead to stale references. Therefore:

    - first call: create the context
    - later calls: update ``assignment_view`` and version fields in place

    Inputs / sources
    ----------------
    - ``assignment_view`` built by startup/reset logical assignment code
    - scene origins read indirectly by ``build_scene_runtime_context``

    Side effects on ``env``
    -----------------------
    - ``env.terrain_runtime_context``
    - ``env.terrain_assignment_view``
    - ``env.terrain_assignment_version``
    - ``env.terrain_runtime_context_version``
    """
    context = getattr(env, "terrain_runtime_context", None)
    if not isinstance(context, TerrainRuntimeContext):
        context = build_scene_runtime_context(
            env=env,
            assignment_view=assignment_view,
            origin_source="auto",
            validate_origin_consistency=True,
        )
        context.assignment_version = 1
        context.origin_version = 1
        context.source_iteration = getattr(env, "current_iteration", None)
        env.terrain_runtime_context = context
    else:
        context.assignment_view = assignment_view
        context.assignment_version += 1
        context.source_iteration = getattr(env, "current_iteration", None)

    env.terrain_assignment_view = assignment_view
    env.terrain_assignment_version = int(context.assignment_version)
    env.terrain_runtime_context_version = int(context.assignment_version)
    return context


def _store_curriculum_state(env: Any, decision: Any, *, refresh_reason: str) -> None:
    """Normalize and attach curriculum state fields onto ``env``.

    Inputs
    ------
    - ``decision`` is expected to come from
      ``SequencePoolOrchestrator.scheduler.build_decision(...)``
    - ``refresh_reason`` is taken from the actual resulting pool, so the stored
      state reflects what really happened rather than only the scheduler's prior
      intent.

    Side effects
    ------------
    Writes:
    - ``sequence_train_enabled``
    - ``sequence_train_ratio``
    - ``sequence_active_length_range``
    - ``sequence_pool_refresh_required``
    - ``sequence_curriculum_state``
    """
    env.sequence_train_enabled = bool(decision.sequence_enabled)
    env.sequence_train_ratio = float(decision.sequence_ratio)
    env.sequence_active_length_range = tuple(decision.active_length_range)
    env.sequence_pool_refresh_required = bool(decision.should_refresh)
    env.sequence_curriculum_state = {
        "iteration": int(decision.iteration),
        "sequence_enabled": bool(decision.sequence_enabled),
        "sequence_ratio": float(decision.sequence_ratio),
        "active_length_range": tuple(decision.active_length_range),
        "refresh_required": bool(decision.should_refresh),
        "refresh_reason": str(refresh_reason),
    }


def _pool_signature(pool: Any) -> tuple[Any, ...] | None:
    """Build a lightweight signature for the current sequence pool.

    This helper is used only to detect whether the active sequence pool has
    materially changed across resets so we can increment ``sequence_pool_version``.
    It is intentionally lightweight rather than a full structural hash.
    """
    if pool is None:
        return None
    template_records = getattr(pool, "template_records", ())
    sequence_ids = tuple(getattr(template, "sequence_id", None) for template in template_records)
    return (
        int(getattr(pool, "iteration", 0)),
        int(getattr(pool, "seed", 0)),
        tuple(getattr(pool, "active_sequence_length_range", ())),
        sequence_ids,
    )


def _first_existing_attr(owner: Any, *names: str) -> Any | None:
    """Return the first non-``None`` attribute found on ``owner``.

    Parameters
    ----------
    owner:
        Any object that may or may not expose the requested names.
    *names:
        Candidate attribute names in priority order.

    Returns
    -------
    Any | None
        The first existing, non-``None`` attribute value; otherwise ``None``.

    Why this helper exists
    ----------------------
    Many event inputs can come from either ``env`` or ``env.cfg``. This helper
    keeps the resolution style compact and explicit without hard-coding too many
    repeated ``hasattr/getattr`` chains.
    """
    if owner is None:
        return None
    for name in names:
        if hasattr(owner, name):
            value = getattr(owner, name)
            if value is not None:
                return value
    return None


def _first_callable_attr(owner: Any, *names: str):
    """Return the first resolved attribute that is callable.

    This is mainly used by weak integration hooks such as sensor registration,
    where V1 wants to probe for optional APIs without hard-coding a single
    method name or assuming the API always exists.
    """
    value = _first_existing_attr(owner, *names)
    return value if callable(value) else None


def _require_attr(owner: Any, name: str) -> Any:
    """Fetch a required attribute or raise a descriptive error.

    This helper is used when a later event step depends on a startup-created
    object or required cfg field. It keeps failure modes explicit and easier to
    debug than bare ``AttributeError`` from nested attribute access.
    """
    if owner is None or not hasattr(owner, name):
        raise AttributeError(f"Required attribute '{name}' is unavailable on {type(owner)!r}.")
    value = getattr(owner, name)
    if value is None:
        raise AttributeError(f"Required attribute '{name}' is None on {type(owner)!r}.")
    return value


def _warn_once(env: Any, flag_name: str, message: str) -> None:
    """Emit a warning only once per env instance.

    Weak hooks in V1 intentionally warn when they are operating in degraded or
    placeholder mode. To avoid noisy logs during repeated resets, warnings are
    memoized through an attribute flag stored on ``env``.
    """
    if getattr(env, flag_name, False):
        return
    warnings.warn(message, stacklevel=2)
    setattr(env, flag_name, True)


__all__ = [
    "initialize_terrain_registry",
    "initialize_terrain_layout",
    "initialize_terrain_physics_profiles",
    "apply_terrain_physics_profiles",
    "register_virtual_obstacles_to_sensors",
    "reset_env_terrain_assignments",
    "update_curriculum_stage",
]
