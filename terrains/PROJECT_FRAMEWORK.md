# 六地形越障策略 — 项目构建框架

## 一、项目概述

基于 instinct (Isaac Lab) 框架，训练 Unitree G1 29-DoF 人形机器人完成自适应连续越障，
目标交付 **sim demo + 真机 sim2real 部署**。

- **机器人平台**: Unitree G1 29-DoF（双足 12 + 腰 3 + 双臂 14 = 29 DoF；ankle 双自由度）
- **训练范式**: Motion-Matched Perceptive Shadowing + volume_points 防穿透
- **硬件**: RTX 4090 (24 GB)，num_envs = 4096
- **Deadline**: 约 2 个月（自 2026-05-21 起，~2026-07-21 前完成 sim2real）
- **范围**: 先完成 6 个地形（剩余 4 个: 螺旋楼梯/1m 平台/爬行通道/L 弯，留 v2）


## 二、关键架构决策（已锁定）

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 地形组织 | **多 sub-terrain 网格训练**（非长条 concat） | `terrain_motion.match_scene` 原生支持；课程学习友好；4096 envs 并行高效 |
| 连续越障 | **不作为训练目标**，作为评估目标 | 单 policy 直接学 90s episode 信用分配差；用 sub-terrain 训技能后再在长条评估 |
| 跨栏处理 | **stay_still 占位 + volume_points 罚穿透** | 复用 `tasks/parkour` 现成机制；不需要为跨栏专门准备动作数据 |
| 观测设计 | **sim2real-only**，policy 不含 GT base 线速度 | 真机 IMU 算不出 GT 速度；parkour PolicyCfg 已天然兼容 |
| 历史堆叠 | RMA-lite：堆 8~10 步观测，policy 自估线速度 | 比 teacher-student 蒸馏简单，2 个月内可控 |
| 控制延迟 | **W2 起就用 `beyondmimic_g1_29dof_delayed_actuators`** | 不能等训完再加，会重学 |
| Domain randomization | W4 起渐进引入 | 太早加难收敛 |
| 高层视觉 policy | **本周期不做**，遥控器作为唯一上层 command 源 | 时间预算不允许；高层留 v2 |
| 任务派生基线 | 从 `tasks/parkour/config/g1/g1_parkour_target_amp_cfg.py` 派生 | 已含 volume_points / step_safety / delayed actuator / sim2real-compatible obs |


## 三、8 周时间表

```
W1  环境搭建 + stay_still pipeline   ⬜
W2  单地形（连续斜坡）调通              ⬜
W3  6 sub-terrain 联合训练            ⬜
W4  DR + actuator model 加入，sim 调  ⬜
W5  sim2sim 验证 (Isaac → MuJoCo)    ⬜
W6  真机部署准备                      ⬜
W7  真机调试（平地 → 简单障碍）         ⬜
W8  真机扩展 + 评估 + 录视频           ⬜
```

Motion 数据准备并行进行（W2~W3），不占主线 week。


## 四、已完成工作

### 4.1 地形文件处理

| 步骤 | 内容 | 输出 |
|------|------|------|
| 原始 CAD 导出 | AutoCAD DWG → STL（世界坐标） | `G:\CAD\障碍建模\*.stl` (10 个) |
| 坐标归化 | Python trimesh 批量平移：XY 归零、Z 底归零 | `terrains/centered/*.stl` (10 个) |
| 位姿调整 | 连续斜坡绕 Z+90°、连续绕桩绕 Z+90° | 已整合到组合地形中 |
| 纵向组合 | 6 地形沿 Y 轴排列，间距 10m | `terrains/combined/longitudinal_6_terrains.stl`（评估用，非训练）|

### 4.2 地形几何参数

| # | 名称 | 原始 X×Y×Z (m) | 旋转 | 长条中 Y 范围 (m) | 训练 terrain_id |
|---|------|---------------|------|-----------------|-----------------|
| 1 | 连续斜坡 | 7.4 × 2.4 × 0.50 | Z+90° | -3.70 ~ 3.70 | 0 |
| 2 | 连续跨栏 | 2.4 × 4.6 × 0.30 | — | 13.70 ~ 18.30 | 4 |
| 3 | 交叉斜坡 | 3.0 × 6.0 × 0.82 | — | 28.30 ~ 34.30 | 2 |
| 4 | 连续绕桩 | 4.7 × 0.3 × 1.50 | Z+90° | 44.30 ~ 49.00 | 5 |
| 5 | 对称斜坡 | 3.5 × 3.0 × 0.62 | — | 59.00 ~ 62.00 | 1 |
| 6 | S 弯桥 | 6.9 × 13.3 × 0.10 | — | 72.00 ~ 85.30 | 3 |

训练 terrain_id 顺序按 **训练难度递增** 排（与长条物理顺序不同）：
ramp → symmetrical → cross_slope → s_curve → hurdling → slalom

- 长条 STL 总尺寸记录待核（文档曾出现 79.6m vs 89.0m 不一致，以实际 STL bbox 为准）
- 单位：米，Z+ 向上，通行方向 +Y

### 4.3 元数据文件

| 文件 | 路径 | 内容 |
|------|------|------|
| 10 地形索引 | `terrains/centered/metadata.yaml` | 10 个独立地形 terrain_id（字符串）→ terrain_file |
| 6 地形 + motion | `terrains/combined/metadata.yaml` | **整数 terrain_id** 0~5；6 个 motion_file 一一对应 |

### 4.4 辅助工具

| 脚本 | 路径 | 功能 |
|------|------|------|
| 地形可视化 | `scripts/visualize_terrain.py` | 加载单个 STL 到 Isaac Sim 查看 |
| stay_still NPZ 生成 | `scripts/make_stay_still_npz.py` | 生成 6 个占位 motion NPZ（schema 见 §五）|
| 长条 combine 脚本 | ⬜ 待写 | 参数化：6 STL → combined STL + 长条版 metadata |


## 五、Motion NPZ Schema（来自 `amass_motion._read_retargetted_motion_file`）

文件名约定：`*_retargetted.npz` 或 `*_retargeted.npz` —— **后缀必须匹配**，否则走错 loader。

```
framerate    : float scalar
joint_names  : 1-D array of str (长度 N_joints；需与 G1 29-DoF articulation 顺序一致)
joint_pos    : (N_frames, N_joints) float32, 弧度
base_pos_w   : (N_frames, 3) float32, world frame
base_quat_w  : (N_frames, 4) float32, world frame (w, x, y, z)
```

> 旧文档曾写 `poses (N, J, 7)` — **错的**，已废弃。


## 六、待完成框架（更新版）

### 阶段 W1：环境搭建 + pipeline 跑通 ⬜

**目标**: stay_still 占位下，6 sub-terrain 场景能在 play.py 加载渲染。

- [x] 写 `terrains/combined/metadata.yaml`（6 terrain_id 0~5）
- [x] 写 `scripts/make_stay_still_npz.py`
- [x] 写 `tasks/parkour/config/g1/g1_six_terrain_cfg.py`
- [ ] 在 `tasks/parkour/config/g1/__init__.py` 注册 gym id `Isaac-G1-SixTerrain-v0` / `-PLAY-v0`
- [ ] 跑 `scripts/make_stay_still_npz.py` 产出 6 个 NPZ
- [ ] `play.py --task=Isaac-G1-SixTerrain-PLAY-v0 --sample --no_resume` 验证场景

### 阶段 W2：单地形调通 ⬜

- 临时把 metadata.yaml 的 terrains 缩到 1 个（连续斜坡）
- `train.py` 跑通；reward 收敛，能走完斜坡
- 此阶段已含 actuator delay（不含 DR）

### 阶段 W3：6 sub-terrain 联合训练 ⬜

- 完整 metadata.yaml 6 terrains
- 12×12 grid, curriculum=True
- 替换部分 motion 为真实 retargetted（优先级见 §七）

### 阶段 W4：DR + sim 调参 ⬜

- 加 friction / mass / motor Kp/Kd / payload / CoM 偏移随机化
- 加 push 扰动
- 加 IMU/encoder 观测噪声
- 目标：sim 通过率 ≥ 80%

### 阶段 W5：sim2sim 验证 ⬜

- 导出 policy → MuJoCo（Unitree G1 MJCF）
- 通过率 ≥ 70% 视为合格；否则加大 DR 回 W4

### 阶段 W6-W8：真机部署 ⬜

- W6: 部署脚本、安全限位、遥控映射、PD 实测
- W7: 真机平地走 → 单一简单障碍（斜坡 / 对称斜坡）
- W8: 真机扩展到 3~4 个障碍 + 录 demo


## 七、Motion 数据来源策略

| 地形 | 优先级方案 | 来源 |
|------|----------|------|
| 连续斜坡 / 对称斜坡 / 交叉斜坡 | AMASS walking retarget | AMASS + soma/PHC retargeter |
| S 弯桥 | AMASS turning walk retarget | 同上，注意支持非零 wz |
| 连续跨栏 | **stay_still 占位永久保留** | volume_points 罚穿透自动学抬腿 |
| 连续绕桩 | Isaac Sim 关键帧手搓 或 自采手机视频 + 姿态估计 | AMASS slalom 数据稀缺 |

stay_still 占位走通 pipeline 之前**不要**着急做真实 motion。


## 八、观测设计（sim2real-only）

policy 网络看到的（真机可得）：

| 观测项 | 来源 |
|--------|------|
| base 角速度 (IMU gyro) | IMU |
| 重力投影到 base frame | IMU |
| velocity command (vx, vy, wz) | 遥控器 / 自动 command 生成器 |
| 关节位置 - default | 编码器 |
| 关节速度 | 编码器 |
| 上一时刻 action | 内部状态 |
| height_scan（双脚附近 ray cast） | 真机用前向深度/雷达等价物近似 |
| 上述观测的 8 步历史 | 用于自估 base 线速度 |

critic 可以多看（仅训练时用）：
- GT base 线速度（policy 不看）

**禁用**：GT base 位置/速度、完美地形 heightmap、完美 contact force。


## 九、文件清单

```
InstinctLab/
├── terrains/
│   ├── centered/                          # 10 个归化后的独立 STL
│   │   ├── 1.Continuous Ramp.stl
│   │   ├── ... (省略)
│   │   ├── 10.Width-restricted L-shaped Bend.stl
│   │   └── metadata.yaml                 # 10 地形索引（字符串 id，独立用）
│   ├── combined/
│   │   ├── longitudinal_6_terrains.stl    # 长条评估用 STL（非训练）
│   │   ├── metadata.yaml                 # ✓ 训练 6 terrain_id + 6 motion 索引
│   │   └── motions/                      # ⬜ 由 make_stay_still_npz.py 产出
│   │       ├── ramp_retargetted.npz
│   │       ├── symmetrical_ramp_retargetted.npz
│   │       ├── cross_slope_retargetted.npz
│   │       ├── s_curve_retargetted.npz
│   │       ├── hurdling_retargetted.npz
│   │       └── slalom_retargetted.npz
│   └── PROJECT_FRAMEWORK.md              # 本文档
├── scripts/
│   ├── visualize_terrain.py              # STL 可视化工具
│   ├── make_stay_still_npz.py            # ✓ 占位 motion 生成
│   └── combine_terrains.py               # ⬜ 待写（参数化长条 STL 生成）
├── source/instinctlab/instinctlab/
│   ├── terrains/                         # instinct 地形系统源码
│   ├── tasks/parkour/                    # 当前任务派生基线
│   │   └── config/g1/
│   │       ├── g1_parkour_target_amp_cfg.py
│   │       └── g1_six_terrain_cfg.py     # ✓ 新建：6 地形 env
│   └── motion_reference/                 # 动作参考管理系统
└── docker/                               # Docker 部署配置
```


## 十、当前状态

```
W1 环境搭建            ███░░░░░░░░░ 进行中 — metadata / NPZ 生成器 / env cfg 已写，待注册 gym id 并跑 play.py
W2 单地形调通          ░░░░░░░░░░░░ ⬜
W3 6 sub-terrain 训练 ░░░░░░░░░░░░ ⬜
W4 DR + sim 调参      ░░░░░░░░░░░░ ⬜
W5 sim2sim 验证        ░░░░░░░░░░░░ ⬜
W6 真机部署准备        ░░░░░░░░░░░░ ⬜
W7 真机调试            ░░░░░░░░░░░░ ⬜
W8 真机扩展 + demo     ░░░░░░░░░░░░ ⬜
```

**当前阻塞项**: 无 — W1 剩余只是注册 gym id + 运行验证。
