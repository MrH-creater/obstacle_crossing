from isaaclab.utils import configclass

from instinctlab.tasks.parkour.config.g1.agents.instinct_rl_amp_cfg import G1ParkourPPORunnerCfg


@configclass
class ObstacleCrossingPPORunnerCfg(G1ParkourPPORunnerCfg):
    """Placeholder runner config for obstacle crossing.

    The first skeleton phase intentionally reuses the parkour runner config
    surface. Later phases can replace this with a dedicated runner/policy setup.
    """

    experiment_name = "g1_obstacle_crossing"
