# TerrainAwareVelocityCommand Requirements

## 1. 文档目的

本文档用于正式定义 obstacle_crossing 项目中：

- `TerrainAwareVelocityCommand`
- single terrain waypoint / centerline 生成
- sequence template waypoint / centerline 生成
- command 的输入输出、参数和协同边界

的实现需求。

本文档基于当前已锁定的项目主线，目标是：

> **在不引入自主路径规划问题的前提下，采用 oracle 式的 sequence template centerline / waypoint 方案，为 low-level policy 提供基于地形的速度命令。**

---

## 2. 当前正式技术路线

## 2.1 command 的定位
当前 obstacle_crossing 中的 `TerrainAwareVelocityCommand` 不负责：
- 自主路径规划
- 视觉理解后的全局路径搜索
- 高层 navigation / route selection

它负责的是：

> **已知当前应该前往的路径 / patch / waypoint 时，根据机器人当前位置与目标之间的偏差，解算出三维速度命令：`lin_x`、`lin_y`、`ang_z`。**

也就是说，它是：
- 目标跟踪命令生成器（tracking command generator）
而不是：
- 自主规划器（planner）

---

## 2.2 当前项目对路径来源的选择
正式采纳：

> **采用 sequence template centerline / waypoint 方案（方案 B）**

而不是：
- 让 low-level policy 自己规划路径
- 也不是让 command 完成全局路径规划

### 结论
当前 command 的目标来源应为：
- single terrain 自身的 centerline / waypoint / segment target points
- sequence template 在 generator 阶段拼接后形成的全局 `sequence_terrain_waypoints_y`

---

## 2.3 当前地形摆放前提
已经确认：
- 多地形 sequence 最终是在一块连续基础地板上按 `+Y` 方向排布
- 每个 single 地形的起点 → 终点方向，与 sequence 总体方向保持一致
- 相邻 single 地形之间通过 buffer 区间沿 `+Y` 方向间隔开

这意味着：

> **只要每个 single terrain 自己的 `waypoints_y / centerline / segment target points` 足够准确，那么 sequence 的整体 waypoint 序列就可以通过“位移拼接 + 必要时的简单平滑”构建出来。**

---

## 3. 总设计结论

### 3.1 command 的正式方案
当前正式方案是：

> **以 oracle 式的 centerline / waypoint 作为路径目标源，由 `TerrainAwareVelocityCommand` 根据机器人当前姿态与目标 waypoint 的相对误差，解算 `lin_x` / `lin_y` / `ang_z`。**

### 3.2 single 与 sequence 共用同一 command 体系
- single terrain 使用 single terrain 自带的 centerline / waypoint
- sequence terrain 使用 generator 拼接后的 sequence-level centerline / waypoint

### 3.3 后续不做什么
V1 不做：
- 自主局部路径规划
- 基于视觉直接搜索路径
- global planner / learned high-level policy

---

## 4. single terrain 侧需要补充的内容

为了让 command 能工作，single terrain 必须提供自己的局部路径信息。

## 4.1 single terrain 需要的路径表达
对于每个 single terrain，后续至少要能提供其一：

### 方案 A：waypoints_y
也就是一组按前进方向排序的 waypoint 点：
- `(x, y)`
- 或 `(x, y, z)`

### 方案 B：centerline
以更连续的形式表达地形的推荐通过中线。

### 方案 C：segment target points
如果某个地形不适合全程 centerline，也至少要给出：
- 入口 target
- 中间 target
- 出口 target

### 推荐
V1 推荐优先使用：
- **离散 waypoint 序列**

因为：
- 更容易生成
- 更容易拼接
- 更容易做 lookahead

---

## 4.2 single terrain waypoint 的基本要求
每个 single terrain 的 waypoint/centerline 生成至少应满足：

1. 与该地形的**真实几何通过路径**一致
2. 起点与终点方向符合当前统一的 `+Y` 方向规范
3. waypoint 序列是**单调沿 Y 方向推进**的
4. waypoint 间距不要过大，避免 command 目标跳变过猛
5. 能正确覆盖：
   - 地形起点
   - 地形核心障碍区
   - 地形终点

---

## 4.3 single terrain waypoint 的输出建议
推荐每个 single terrain 最终能提供：

```python
terrain_id: int
terrain_key: str
waypoints_xy: tuple[tuple[float, float], ...]
entry_target_xy: tuple[float, float]
exit_target_xy: tuple[float, float]
forward_axis: str = "+Y"
```

如果需要保留 Z，可扩展为：

```python
waypoints_xyz: tuple[tuple[float, float, float], ...]
```

但 V1 中 command 主要关注的是平面速度：
- `lin_x`
- `lin_y`
- `ang_z`

所以平面 waypoint 足够作为第一版。

---

## 5. sequence template 侧需要生成的路径信息

## 5.1 核心思想
每条 sequence template 不应该只包含：
- terrain ids
- segment ranges
- buffer ranges

还应包含：
- **整条 sequence 的 centerline / waypoint 序列**

也就是说，sequence generator 后续必须把：
- single terrain 的 local waypoints
- 以及段间连接逻辑

一起转化成：
- `sequence_terrain_waypoints_y`

---

## 5.2 sequence waypoint 的生成规则
正式采纳以下思路：

### 规则 1：每个 single terrain 先有自己的 local waypoint / centerline
这部分属于 single terrain 的局部路径描述。

### 规则 2：sequence generator 在拼接 single terrain 到长地形时，同时拼接其 waypoint
也就是说：
- 如果某个 single terrain 在 sequence 中被沿 `+Y` 平移到某个位置
- 那么它自己的 local waypoint 也要做同样平移

### 规则 3：相邻地形之间的 buffer 区间，需要补齐 waypoint 连接
因为多地形之间存在 buffer 段，所以 sequence-level waypoint 不应该在 segment 边界直接断掉。

### 推荐做法
- 取前一段最后一个 waypoint
- 取后一段第一个 waypoint
- 在 buffer 区间内插值出若干过渡 waypoint

也就是说：

> sequence waypoint = 各 single terrain waypoint 的位移拼接 + buffer 区间的连接 waypoint

---

## 5.3 是否必须复杂平滑？
当前阶段我的建议是：

### V1
先做：
- 简单连接
- 或简单线性插值
- 必要时做轻量平滑

### 不建议当前阶段就做
- 复杂高阶轨迹优化
- 曲率优化器
- 高层 planner 输出

### 原因
你当前首先要的是：
- 能稳定提供合理 command 目标
- 而不是追求最优轨迹

---

## 5.4 sequence 级 metadata 建议新增字段
当前 generator 已经能输出很多 metadata，但为了支持 command，需要新增：

### single terrain 级
- `segment_waypoints_xy`
- 或 `segment_centerline_xy`

### sequence template 级
- `sequence_waypoints_xy`
- `segment_entry_targets_xy`
- `segment_exit_targets_xy`
- `default_lookahead_distance`

推荐最少新增：

```python
sequence_waypoints_xy: tuple[tuple[float, float], ...]
segment_waypoint_ranges: tuple[tuple[int, int], ...]
```

这样 command 可以知道：
- 整条 sequence 的 waypoint 序列
- 每个 segment 对应 waypoint 序列中的哪一段

---

## 6. TerrainAwareVelocityCommand 的正式职责

## 6.1 输入
它后续至少应读取：

### A. 机器人当前状态
- 当前 base pose / heading
- 当前 base velocity（若需要用于滤波或 metrics）

### B. assignment 提供的信息
- 当前 env 是 single 还是 sequence
- 当前 env 对应的 terrain 或 sequence template
- 当前 env 的 command profile
- 若是 sequence：
  - sequence waypoint / centerline
  - segment ranges / waypoint ranges

### C. 配置参数
- lookahead distance
- 最大线速度/角速度
- 距离阈值
- heading 控制增益
- velocity 控制增益

---

## 6.2 输出
它输出：
- `lin_x`
- `lin_y`
- `ang_z`

也就是：
- `vel_command_b`，形状 `(num_envs, 3)`

---

## 6.3 作用逻辑
command 层的作用不是规划，而是：

> **根据“当前位置”和“目标 waypoint / centerline 上的下一目标点”的误差，解算平面速度命令。**

可以概括为：

1. 获取当前 env 的 target source
   - single terrain 的 waypoint
   - 或 sequence template 的 waypoint
2. 从目标序列中选取下一个 lookahead point
3. 计算机器人当前位置到该点的误差
4. 将误差映射为：
   - 前向速度 `lin_x`
   - 横向速度 `lin_y`
   - 角速度 `ang_z`

---

## 6.4 这层不负责什么
### 不负责
- 自主路径搜索
- 绕障决策
- 复杂 planner
- 生成路径本身

这些都不是当前 V1 要做的事。

---

## 7. 推荐的 command source 分层

为了后续扩展性，我建议将 `TerrainAwareVelocityCommand` 的内部设计区分为两层：

## 7.1 Command Source
负责回答：
> 当前应该追哪个目标？

可选 source：
- `SingleTerrainWaypointSource`
- `SequenceTemplateWaypointSource`
- `ManualJoystickSource`（未来）
- `PlannerSource`（未来）

## 7.2 Velocity Command Generator
负责回答：
> 已知目标后，应该输出怎样的 `lin_x / lin_y / ang_z`？

也就是说：
- source 决定目标
- command generator 决定如何跟踪

当前 V1 可以先不拆文件，但设计思路建议按这两层来组织。

---

## 8. 推荐新增的数据结构 / metadata

## 8.1 single terrain 路径记录
建议未来支持：

```python
SingleTerrainWaypointRecord:
    terrain_id: int
    terrain_key: str
    waypoints_xy: tuple[tuple[float, float], ...]
    entry_target_xy: tuple[float, float]
    exit_target_xy: tuple[float, float]
```

## 8.2 sequence template 路径记录
建议在 `SequenceTemplateRecord` 或关联 metadata 中新增：

```python
sequence_waypoints_xy: tuple[tuple[float, float], ...]
segment_waypoint_ranges: tuple[tuple[int, int], ...]
default_lookahead_distance: float
```

---

## 9. TerrainAwareVelocityCommand 建议参数

后续建议在 `TerrainAwareVelocityCommandCfg` 中支持如下参数：

```python
lookahead_distance: float
position_tolerance: float
heading_tolerance: float
max_linear_speed_x: float
max_linear_speed_y: float
max_angular_speed_z: float
velocity_control_gain: float
heading_control_gain: float
use_sequence_waypoints: bool = True
```

### 解释
- `lookahead_distance`
  - 选取前方目标 waypoint 的距离
- `position_tolerance`
  - 接近 waypoint 时切换到下一个目标点
- `heading_tolerance`
  - heading 误差阈值
- `max_*`
  - 输出命令上限
- `*_gain`
  - 将位置/方向误差映射成命令的比例系数

---

## 10. 与现有模块的协同关系

## 10.1 与 `terrain_registry.py`
registry 继续提供：
- terrain id / key
- command profile
- capability
- physics / collision profile

但 registry 不负责生成 waypoint。

## 10.2 与 `sequence_generator.py`
sequence_generator 后续需要额外输出：
- sequence-level waypoint / centerline
- segment waypoint ranges

也就是说：
> generator 生成 geometry + metadata，也要生成 command 可消费的路径目标数据。

## 10.3 与 `terrain_assignment.py`
assignment 后续应成为 command 的直接查询入口。

command 不应该自己去磁盘读 template YAML，而应通过 assignment 查询：
- 当前 env 绑定的 sequence_id
- 对应的 waypoint / target 信息
- 对应的 command profile

## 10.4 与 scheduler/orchestrator
scheduler/orchestrator 负责 current active pool，command 不直接感知 scheduler，只感知 assignment 暴露出来的 active target 信息。

---

## 11. 当前建议的实现顺序

### Step 1
定义 single terrain waypoint / centerline 数据结构与生成方式。

### Step 2
让 sequence_generator 在拼接 sequence 时，同时生成 sequence-level waypoint。

### Step 3
扩展 assignment，使其可查询 sequence waypoint / segment waypoint ranges。

### Step 4
实现 `TerrainAwareVelocityCommand`：
- 读取 assignment
- 获取 target waypoint
- 解算 `lin_x / lin_y / ang_z`

### Step 5
再考虑更细的 smoothing / lookahead / segment 切换策略。

---

## 12. 当前总设计师结论

当前 obstacle_crossing 项目中的 command 路线正式定为：

> **不做自主路径规划，采用 oracle 式的 single terrain / sequence template centerline / waypoint 作为目标源，由 TerrainAwareVelocityCommand 将机器人当前位置到目标点的误差解算为 `lin_x`、`lin_y`、`ang_z`。**

这样可以保证：
- 不把“路径规划”问题提前引入当前 V1
- 与当前 registry / generator / assignment 体系完全兼容
- 使连续越障问题保持在“已知目标路径下的低层动作规划与控制”这一合理范围内
