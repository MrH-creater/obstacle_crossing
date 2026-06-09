from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch
    from isaaclab.envs import ManagerBasedRLEnv


# ============================================================
# Policy group observations
# (sim2real-safe terms fed directly to the policy network)
# ============================================================


# ============================================================
# Critic group observations
# (may include privileged terms not available at deployment)
# ============================================================


# ============================================================
# Privileged observations
# (privileged-only signals, critic/teacher use)
# ============================================================


# ============================================================
# AMP observations
# (amp_policy / amp_reference state terms)
# ============================================================
