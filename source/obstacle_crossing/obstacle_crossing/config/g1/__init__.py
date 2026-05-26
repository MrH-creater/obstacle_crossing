import gymnasium as gym

from . import agents


task_entry = "obstacle_crossing.config.g1"


gym.register(
    id="Instinct-Obstacle-Crossing-G1-v0",
    entry_point="instinctlab.envs:InstinctRlEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{task_entry}.g1_obstacle_crossing_cfg:G1ObstacleCrossingEnvCfg",
        "instinct_rl_cfg_entry_point": f"{agents.__name__}.instinct_rl_cfg:ObstacleCrossingPPORunnerCfg",
    },
)


gym.register(
    id="Instinct-Obstacle-Crossing-G1-Play-v0",
    entry_point="instinctlab.envs:InstinctRlEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{task_entry}.g1_obstacle_crossing_cfg:G1ObstacleCrossingEnvCfg_PLAY",
        "instinct_rl_cfg_entry_point": f"{agents.__name__}.instinct_rl_cfg:ObstacleCrossingPPORunnerCfg",
    },
)
