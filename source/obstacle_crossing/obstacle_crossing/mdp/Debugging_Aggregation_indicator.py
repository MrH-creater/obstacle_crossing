from __future__ import annotations

from typing import Any


class TerrainIndicatorAccumulator:
    """Placeholder for cross-episode terrain diagnostic aggregation.

    Intended behavior:
        Maintain stateful terrain-grouped statistics across episodes, including
        success/failure counts, termination-type counts, sequence progress
        samples for histograms, and later AMP score summaries.

    Input source:
        Future termination-frame snapshots carrying env id, current terrain, and
        termination type. Progress-dependent fields require real-time indicators
        backed by command-exposed progress state.

    Output/state:
        Planned state includes per_terrain_success, per_terrain_fail,
        per_terrain_termination_counts, sequence_progress_samples, and stretch
        per_terrain_amp_scores.

    Dependencies:
        Requires a termination-frame snapshot hook before reset mutates
        assignment/progress state. Real progress histograms also require command
        progress exposure through the real-time indicator layer.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("TODO: implement cross-episode terrain indicator accumulation state.")


def record_episode_terminations(env: Any, accumulator: TerrainIndicatorAccumulator, termination_snapshot: Any) -> None:
    """Placeholder for recording termination-frame diagnostic snapshots.

    Intended behavior:
        Consume a snapshot captured on the same frame as termination and update
        the accumulator with success/failure and termination-type counts grouped
        by current terrain.

    Input source:
        termination_snapshot should eventually contain env ids, current terrain
        ids/keys, termination types, and any success/time-out semantics needed by
        training diagnostics.

    Output:
        Mutates accumulator state in place and returns None.

    Dependencies:
        Requires a termination-frame snapshot hook and current-terrain
        resolution before env reset changes assignment/progress state.
    """
    raise NotImplementedError("TODO: requires termination-frame snapshot hook and accumulator implementation.")


def per_terrain_success_rate(
    accumulator: TerrainIndicatorAccumulator,
    recent_n: int | None = None,
) -> dict[str, float]:
    """Placeholder for terrain-grouped success rates.

    Intended behavior:
        Report success rate per terrain, optionally over a recent episode window.

    Input source:
        TerrainIndicatorAccumulator success/failure counters or windowed samples.

    Output:
        A dictionary mapping terrain key to success rate.

    Dependencies:
        Requires TerrainIndicatorAccumulator state and an agreed success/failure
        definition.
    """
    raise NotImplementedError("TODO: implement success-rate query after accumulator state is defined.")


def per_terrain_termination_breakdown(accumulator: TerrainIndicatorAccumulator) -> dict[str, dict[str, int]]:
    """Placeholder for terrain-grouped termination-type counts.

    Intended behavior:
        Report counts such as time_out, bad_orientation, base_contact, and other
        termination terms per terrain.

    Input source:
        TerrainIndicatorAccumulator per_terrain_termination_counts state.

    Output:
        A nested dictionary {terrain_key: {termination_type: count}}.

    Dependencies:
        Requires termination-frame snapshots and accumulator state.
    """
    raise NotImplementedError("TODO: implement termination breakdown query after accumulator state is defined.")


def sequence_progress_histogram(accumulator: TerrainIndicatorAccumulator, num_bins: int = 20) -> tuple:
    """Placeholder for sequence progress histogram diagnostics.

    Intended behavior:
        Build a histogram over sequence progress samples to reveal whether many
        envs stall at a particular progression phase.

    Input source:
        TerrainIndicatorAccumulator sequence_progress_samples state.

    Output:
        A tuple such as (bins, counts).

    Dependencies:
        Requires command progress exposure, real-time progress indicators, and
        accumulator storage of progress samples.
    """
    raise NotImplementedError("TODO: implement progress histogram after progress samples are recorded.")


def per_terrain_amp_score_stats(accumulator: TerrainIndicatorAccumulator) -> dict[str, dict[str, float]]:
    """Placeholder for stretch AMP score statistics by terrain.

    Intended behavior:
        Report per-terrain AMP score mean/variance or similar moments to locate
        terrain-specific style-learning imbalance.

    Input source:
        Future TerrainIndicatorAccumulator per_terrain_amp_scores state.

    Output:
        A dictionary such as {terrain_key: {"mean": value, "var": value}}.

    Dependencies:
        Stretch goal. Requires an agreed AMP score source and accumulator support.
    """
    raise NotImplementedError("TODO: stretch indicator requiring AMP score source and accumulator support.")
