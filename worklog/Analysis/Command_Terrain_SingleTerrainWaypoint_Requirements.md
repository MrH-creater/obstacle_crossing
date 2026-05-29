# Command / Terrain / SingleTerrainWaypoint / TargetPatch Requirements

## 1. 文档目的

本文档用于正式定义 obstacle_crossing 项目中：
- single terrain 侧的 `waypoint / centerline / target patch / target point` 数据应如何表达
- 如何与 `sequence_generator.py` 协同，生成 sequence 级 `waypoint / centerline / target patch`
- 如何服务 `TerrainAwareVelocityCommand`
- 为什么当前阶段不做自主路径规划，而采用 oracle 式路径引导

本文件重点解决：
1. single terrain 路径目标应该如何表达
2. sequence 路径如何由单地形路径拼接而来
3. command 最终应读什么数据
4. 与 instinct 项目中的 `flat_patches / pos_command_w` 思路如何衔接

---

## 2. 当前正式技术路线

### 2.1 当前 command 的角色
在 obstacle_crossing V1 中，command 的定位不是：
- 自主路径规划器
- 高层导航器
- 视觉路径搜索器

而是：

> **在已知目标路径 / waypoint / patch 的前提下，根据机器人当前位置与目标之间的误差，解算出三维速度命令：`lin_x`、`lin_y`、`ang_z`。**

也就是说：
- command 负责低/中层的“跟踪”
- 不负责高层的“找路”

---

### 2.2 当前为什么不做自主路径规划
当前 obstacle_crossing 的主线仍然是：
- 已知大致通过方向 / 路径
- 重点解决越障控制与连续通过能力

如果此时就引入自主路径规划，将会同时引入：
- 感知解释
- 可行路径搜索
- 路径决策
- 控制执行

这会显著扩大问题规模，不利于当前 V1 主线稳定推进。

因此当前正式采用：

> **oracle 式的路径目标输入**

也就是：
- 地形 / sequence 模板本身提供一条推荐路径
- command 只负责把这条推荐路径转成速度命令

---

## 3. 与 instinct 中 patch/target 逻辑的关系

在 instinct 的 parkour / terrain-aware command 思路里，常见做法是：
- terrain 提供一组有效 `flat_patches` / `target` 候选点
- command 从这些目标中取下一个目标点
- 再根据机器人当前位置与目标点误差，解算速度命令

典型参考包括：
- `source/instinctlab/instinctlab/tasks/parkour/mdp/commands/pose_velocity_command.py`

其中关键模式是：
- 环境或地形提供 **oracle target source**
- command 只负责把 target 转成 `pos_command_w / vel_command_b`

当前 obstacle_crossing 应继承的是这个思想：

> **路径目标由地形或 sequence 模板给出，command 只负责 tracking**

但 obstacle_crossing 不再局限于“孤立 patch 点”，而是更适合发展成：
- single terrain 的 local waypoint / centerline
- sequence template 的 global waypoint / centerline

---

## 4. 正式方案：single terrain target patch / waypoint 统一生成器

## 4.1 总设计结论
当前 single terrain 应为后续 command 提供：

> **一套推荐通过路径目标的统一表达**

这套表达在 V1 中建议包含两层：
1. **target patch / target point 层**：更适合作为 command 的局部目标
2. **waypoint / centerline 层**：更适合作为 sequence 生成时的整体路径骨架

因此当前正式推荐的不是“只做 waypoint”，而是：

> **single terrain target patch / waypoint 统一生成器**

也就是说：
- single terrain 先定义少量 anchor / key target
- 系统自动插值出 waypoints
- 同时从 waypoints 派生出一组可供 command 使用的 target patches / target points

这样既保留：
- sequence 侧易拼接的路径骨架

又保留：
- command 侧更稳健的 patch 目标语义

---

## 4.2 single terrain waypoint 的目标
每个 single terrain 都应该能提供：
- 从该地形起点到终点的一条推荐通过路径
- 路径沿当前统一前进方向大体单调推进
- 路径对当前地形的关键障碍穿越位置有足够表达能力

也就是说，它应该至少回答：
- 入口应从哪里进入
- 中间哪些关键位置需要通过
- 出口应从哪里离开

---

## 4.3 推荐实现：anchor points -> waypoint sequence

### 当前推荐方案
先不要求完全自动从 mesh 中提取最优路径，而是采用：

> **少量关键 anchor points + 自动插值生成更密集的 waypoint 序列**

### 原因
完全自动从 mesh 提取路径：
- 对 slalom / s_curve / future stairs / crawl / L-bend 太复杂

完全手工逐点写满：
- 太重，不利于维护

因此 V1 更稳的做法是：
- 每个地形只提供少量 anchor points
- 系统自动插值出完整 waypoint 序列

---

## 4.4 anchor points 的定义
每个地形建议至少配置：
- `entry anchor`
- `exit anchor`
- 中间若干关键通过点

例如：

### 对 `continuous_ramp`
- entry center
- ramp mid
- exit center

### 对 `continuous_hurdling`
- entry center
- hurdle approach
- crossing center
- exit center

### 对 `consecutive_slalom`
- 入口
- 每个绕桩空隙中心
- 出口

### 对 `s_curve`
- 入口
- 第一个转折关键点
- 中部关键点
- 第二个转折关键点
- 出口

---

## 4.5 single terrain target/waypoint 的建议数据结构
建议未来实现：

```python
@dataclass(frozen=True)
class SingleTerrainAnchorRecord:
    terrain_id: int
    terrain_key: str
    forward_axis: str
    anchors_xy: tuple[tuple[float, float], ...]
```

```python
@dataclass(frozen=True)
class SingleTerrainTargetPatchRecord:
    patch_id: str
    center_xy: tuple[float, float]
    half_size_x: float
    half_size_y: float
    heading_hint_rad: float | None = None
```

```python
@dataclass(frozen=True)
class SingleTerrainWaypointRecord:
    terrain_id: int
    terrain_key: str
    forward_axis: str
    anchors_xy: tuple[tuple[float, float], ...]
    waypoints_xy: tuple[tuple[float, float], ...]
    target_patches: tuple[SingleTerrainTargetPatchRecord, ...]
    entry_target_xy: tuple[float, float]
    exit_target_xy: tuple[float, float]
```

### 解释
- `anchors_xy`：人工或半人工给出的关键点
- `waypoints_xy`：系统插值后生成的更密路径骨架
- `target_patches`：供 command 直接消费的局部目标区域
- `entry_target_xy` / `exit_target_xy`：便于 generator 和 command 做段级拼接/切换

---

## 4.6 存储形式建议
### V1 推荐
优先使用：
- **Python 常量 / Python record**

原因：
- 6 个训练地形数量不多
- 最容易快速迭代与修改
- 后续稳定后再外置 YAML

例如可新增：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_waypoints.py`

其中定义：
- `DEFAULT_SINGLE_TERRAIN_ANCHORS`
- `build_default_single_terrain_waypoint_records()`

---

## 4.7 waypoint 插值规则
### V1 推荐
- 采用简单线性插值
- waypoint spacing 固定，例如：
  - `0.25m`

### 原因
- 足够支持 command V1
- 方便后续 sequence 拼接
- 不会过早引入曲线优化复杂度

### 当前不建议
- spline / Bezier / 高阶轨迹优化
- 从 mesh 自动生成最优 path

---

## 5. sequence template target patch / waypoint 的正式方案

## 5.1 总设计结论
每条 sequence template 不应只包含：
- terrain ids
- segment ranges
- command profiles

还应包含：

> **整条 sequence 的全局 waypoint / centerline 表达，以及由此派生的 command target patch / target point 表达**

也就是说，generator 在拼 sequence 几何时，也要同步拼接：
- sequence 路径骨架（waypoints / centerline）
- sequence command 目标（target patch / target point）

---

## 5.2 生成规则
### 规则 1：每个 single terrain 先有自己的 local waypoint
这些 waypoint 在 local 坐标系下表达该 single terrain 的推荐通过路径。

### 规则 2：generator 在拼接 single terrain 到长地形时，同步对其 local waypoint 做相同位姿变换
如果某个地形段在 sequence 中被：
- 平移到新的 `Y` 偏移位置
- 做统一朝向转换

那么它的 local waypoints 也必须做同样变换。

### 规则 3：buffer 区间要插入连接 waypoint
由于相邻障碍段之间存在 buffer 区间，sequence-level waypoint 不应在 segment 边界断开。

因此：
- 以前一段最后一个 waypoint
- 和后一段第一个 waypoint
为端点
- 在 buffer 区间内生成若干线性过渡 waypoint

### 规则 4：sequence 最终输出一条全局 waypoint 序列
这个全局序列可以记为：
- `sequence_waypoints_xy`

---

## 5.3 推荐输出字段
建议 `SequenceTemplateRecord` 后续增加：

```python
sequence_waypoints_xy: tuple[tuple[float, float], ...]
segment_waypoint_ranges: tuple[tuple[int, int], ...]
entry_target_xy: tuple[float, float]
exit_target_xy: tuple[float, float]
default_lookahead_distance: float
```

### 解释
- `sequence_waypoints_xy`：整条 sequence 的全局 waypoint 序列
- `segment_waypoint_ranges`：每个 segment 在全局 waypoint 序列中对应的 index 范围
- `entry_target_xy` / `exit_target_xy`：供 command / eval / debug 用的整体入口/出口目标
- `default_lookahead_distance`：供 command V1 作为默认前瞻参数

---

## 5.4 sequence waypoint 与基础地板方案的兼容性
当前 sequence 几何已经改为：
- 连续基础地板 + 障碍段排布

这实际上更有利于 waypoint 生成，因为：
- 路径不需要再考虑“buffer 是空气还是地板”
- 所有 segment 和 buffer 都在同一连续承载面上
- sequence waypoint 的连接可以更自然地沿 `+Y` 方向推进

所以当前 generator 的几何修订与 waypoint 方案是相互一致的。

---

## 6. TerrainAwareVelocityCommand 的正式职责

## 6.1 输入
`TerrainAwareVelocityCommand` 后续至少应读取：

### A. 机器人状态
- 当前 base pose / yaw
- 当前 base velocity（若 metrics 需要）

### B. assignment 提供的信息
- 当前 env 是 single 还是 sequence
- 当前 env 对应的 terrain 或 sequence template
- 当前 env 的 command profile
- 当前 env 的 waypoint / centerline 信息

### C. command 配置参数
- lookahead distance
- 位置误差容忍
- heading 误差容忍
- 最大线速度/角速度
- 速度与朝向增益

---

## 6.2 输出
输出必须是：
- `lin_x`
- `lin_y`
- `ang_z`

即：
- `vel_command_b`，形状 `(num_envs, 3)`

---

## 6.3 作用逻辑
其职责应明确为：

> **根据当前位置与下一个目标 waypoint 的误差，解算一个平面速度命令，而不是进行路径规划。**

一个合理的 V1 流程应为：
1. 通过 assignment 获取当前 env 的 active target source
2. 选取当前 lookahead waypoint
3. 计算机器人当前 pose 到该点的误差
4. 解算：
   - 前向速度 `lin_x`
   - 横向速度 `lin_y`
   - 航向角速度 `ang_z`

---

## 6.4 这层明确不做的内容
- 不做自主路径搜索
- 不做高层 navigation
- 不直接从视觉推断去哪走
- 不负责生成路径本身

这些都不属于当前 V1 范围。

---

## 7. 推荐的 command source 分层

为了后续可扩展性，建议将 command source 概念显式化：

### A. `SingleTerrainWaypointSource`
来源：single terrain 的 local waypoint record

### B. `SequenceTemplateWaypointSource`
来源：sequence template 的全局 waypoint record

### C. （未来）`ManualJoystickSource`
来源：遥控器输入

### D. （未来）`PlannerSource`
来源：感知/规划模块

当前 V1 只需实现：
- A
- B

---

## 8. 与现有模块的协同关系

## 8.1 与 `terrain_registry.py`
registry 提供：
- terrain identity
- command profile
- capability
- physics/collision profile

但 registry 不负责 waypoint 生成。

## 8.2 与 `sequence_generator.py`
generator 后续必须输出：
- sequence_waypoints_xy
- segment_waypoint_ranges
- entry/exit target

也就是说：
> generator 不仅要生成几何，还要生成 command 可消费的路径目标数据。

## 8.3 与 `terrain_assignment.py`
assignment 后续应成为 command 的直接查询入口。

command 不应自行读 template YAML，而应通过 assignment 查询：
- 当前 env 的 sequence_id
- 当前 env 的 target waypoint 信息
- 当前 env 的 command profiles

## 8.4 与 scheduler/orchestrator
command 不需要直接感知调度器，只需要通过 assignment 获取当前 active sample 的 target 数据。

---

## 9. 建议新增的 terrain 子模块

建议新增：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_waypoints.py`

负责：
- single terrain anchor 定义
- single terrain waypoint record 生成
- waypoint 插值
- 基础校验

建议至少包含：
- `SingleTerrainAnchorRecord`
- `SingleTerrainWaypointRecord`
- `DEFAULT_SINGLE_TERRAIN_ANCHORS`
- `interpolate_waypoints_from_anchors(...)`
- `build_single_terrain_waypoint_record(...)`
- `build_default_single_terrain_waypoint_records(...)`

---

## 10. 当前建议的实现顺序

### Step 1
实现 single terrain anchor / waypoint 数据结构与生成逻辑。

### Step 2
让 generator 在拼接 sequence 时，同时拼接 waypoints，并输出 sequence-level waypoint metadata。

### Step 3
让 assignment 能查询：
- single terrain waypoint
- sequence template waypoint
- segment waypoint ranges

### Step 4
实现 `TerrainAwareVelocityCommand`：
- 基于 assignment 读取 target
- 解算 `lin_x / lin_y / ang_z`

### Step 5
后续如需要，再加更细的 smoothing / lookahead / segment 切换逻辑。

---

## 11. 当前总设计师结论

当前 obstacle_crossing 的 command 正式路线应定义为：

> **采用 oracle 式 single terrain / sequence template target patch + waypoint 统一方案；由 single terrain 或 sequence template 提供推荐路径骨架与局部 target patch，再由 TerrainAwareVelocityCommand 将机器人当前位置到目标点的误差解算为 `lin_x`、`lin_y`、`ang_z`，而不是在 V1 中引入自主路径规划。**
