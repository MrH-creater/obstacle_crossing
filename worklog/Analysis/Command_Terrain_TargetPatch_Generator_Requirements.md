# Command Terrain Target Patch / Waypoint Generator Requirements

## 1. 文档目的

本文档用于正式定义 obstacle_crossing 项目中：
- single terrain 的 target patch / waypoint / centerline 生成需求
- sequence template 的全局 waypoint / target patch 生成需求
- `TerrainAwareVelocityCommand` 的目标来源与数据接口
- 与 `terrain_registry.py`、`terrain_assignment.py`、`sequence_generator.py` 的协同关系

本文档既是：
- 需求说明
- 又是可直接下发给其他终端 Claude 的实现提示基础

---

## 2. 当前技术路线

### 2.1 command 的定位
当前 obstacle_crossing 不做自主路径规划。command 的正式定位是：

> **在已知目标路径 / waypoint / target patch 的前提下，根据机器人当前位置与目标之间的误差，解算出三维速度命令：`lin_x`、`lin_y`、`ang_z`。**

它负责的是：
- 低/中层 tracking
- 不是高层 planning

### 2.2 当前为何不做自主路径规划
若引入自主规划，将会同时引入：
- 感知解释
- 可行路径搜索
- 路径决策
- 控制执行

这会把当前问题扩展成完整导航任务，不符合 V1 的主线。

因此当前正式采用：

> **oracle 式路径目标输入**

也就是：
- 地形 / sequence template 本身提供推荐路径
- command 只负责 tracking

---

## 3. 与 instinct 中 patch/target 机制的关系

在 instinct / parkour 中，常见做法是：
- terrain 提供 `flat_patches` / `target`
- command 从这些目标中取下一个目标点
- command 再根据机器人当前位置与目标点误差解算速度

当前 obstacle_crossing 应继承这一思想，但升级为：

> **single terrain 的 local target patch / waypoint + sequence template 的全局 target patch / waypoint 统一生成方案**

也就是说：
- command 既可以读 single terrain 的局部目标
- 也可以读 sequence template 的全局目标

---

## 4. 正式方案：target patch + waypoint 统一生成器

## 4.1 总设计结论
当前 single terrain 应为后续 command 提供：
- 一套推荐通过路径目标的统一表达

这套表达在 V1 中建议包含两层：
1. **target patch / target point 层**：适合作为 command 的局部目标
2. **waypoint / centerline 层**：适合作为 sequence 生成时的整体路径骨架

因此当前正式推荐的是：

> **single terrain target patch / waypoint 统一生成器**

### 实现思路
- single terrain 先定义少量 anchor / key target
- 系统自动插值出 waypoints
- 再从 waypoints 派生 target patches / target points

这样既保留：
- sequence 侧可拼接的路径骨架

又保留：
- command 侧更稳健的 patch 目标语义

---

## 5. single terrain target patch / waypoint 需求

## 5.1 目标
每个 single terrain 应该能提供：
- 从起点到终点的一条推荐通过路径
- 路径沿当前统一前进方向大体单调推进
- 路径对关键障碍穿越位置有足够表达能力

也就是说，它至少应回答：
- 入口应从哪里进入
- 中间哪些关键位置需要通过
- 出口应从哪里离开

---

## 5.2 推荐实现方式：anchor points -> waypoint sequence -> target patches

### 推荐方案
不要求完全自动从 mesh 中提取最优路径，而是采用：

> **少量关键 anchor points + 自动插值生成更密集的 waypoint 序列 + 由 waypoints 派生 target patches**

### 为什么这样做
#### 完全自动从 mesh 提取路径
- 对 slalom / s_curve / future stairs / crawl / L-bend 太复杂

#### 完全手工逐点写满
- 太重，不利于维护

因此 V1 更稳的做法是：
- 每个地形只提供少量 anchor points
- 系统自动插值出完整 waypoint 序列
- 再生成 target patch / target point 数据

---

## 5.3 single terrain 的建议数据结构
建议未来实现以下结构：

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

### 字段含义
- `anchors_xy`：人工或半人工给出的关键点
- `waypoints_xy`：系统插值后生成的更密路径骨架
- `target_patches`：供 command 直接消费的局部目标区域
- `entry_target_xy` / `exit_target_xy`：供 generator 和 command 做段级拼接/切换

---

## 5.4 single terrain waypoint 存储建议
### V1 推荐
优先使用：
- **Python 常量 / Python record**

### 原因
- 6 个训练地形数量不多
- 最容易快速迭代与修改
- 后续稳定后再外置 YAML

建议后续新增文件：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_waypoints.py`

其中定义：
- `DEFAULT_SINGLE_TERRAIN_ANCHORS`
- `build_default_single_terrain_waypoint_records()`

---

## 5.5 waypoint 插值规则
### V1 推荐
- 采用简单线性插值
- waypoint spacing 固定，例如：`0.25m`

### 原因
- 足够支持 command V1
- 方便后续 sequence 拼接
- 不会过早引入曲线优化复杂度

### 当前不建议
- spline / Bezier / 高阶轨迹优化
- 从 mesh 自动生成最优 path

---

## 6. sequence template target patch / waypoint 需求

## 6.1 总设计结论
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

## 6.2 生成规则
### 规则 1：每个 single terrain 先有自己的 local waypoint / target patch
这些 waypoint 在 local 坐标系下表达该 single terrain 的推荐通过路径。

### 规则 2：generator 在拼接 single terrain 到长地形时，同步对其 local waypoint 做相同位姿变换
如果某个地形段在 sequence 中被：
- 平移到新的 `Y` 偏移位置
- 做统一朝向转换

那么它的 local waypoints 也必须做同样变换。

### 规则 3：buffer 区间要插入连接 waypoint / target patch
由于相邻障碍段之间存在 buffer 区间，sequence-level waypoint 不应在 segment 边界断开。

因此：
- 以前一段最后一个 waypoint
- 和后一段第一个 waypoint
为端点
- 在 buffer 区间内生成若干线性过渡 waypoint

### 规则 4：sequence 最终输出一条全局 waypoint 序列
这个全局序列可以记为：
- `sequence_waypoints_xy`

### 规则 5：sequence 还应派生出可供 command 直接消费的 patch 目标
也就是：
- 由 waypoint 序列进一步得到 target patch / target point

---

## 6.3 推荐输出字段
建议 `SequenceTemplateRecord` 后续增加：

```python
sequence_waypoints_xy: tuple[tuple[float, float], ...]
sequence_target_patches: tuple[SingleTerrainTargetPatchRecord, ...]
segment_waypoint_ranges: tuple[tuple[int, int], ...]
entry_target_xy: tuple[float, float]
exit_target_xy: tuple[float, float]
default_lookahead_distance: float
```

### 字段解释
- `sequence_waypoints_xy`：整条 sequence 的全局 waypoint 序列
- `sequence_target_patches`：由 waypoint 派生出的 target patch 序列
- `segment_waypoint_ranges`：每个 segment 在全局 waypoint 序列中对应的 index 范围
- `entry_target_xy` / `exit_target_xy`：供 command / eval / debug 用的整体入口/出口目标
- `default_lookahead_distance`：供 command V1 作为默认前瞻参数

---

## 6.4 与基础地板方案的兼容性
当前 sequence 几何已经改为：
- 连续基础地板 + 障碍段排布

这对 waypoint 生成是有利的，因为：
- 路径不需要再考虑 buffer 是空气还是地板
- 所有 segment 和 buffer 都在同一连续承载面上
- sequence waypoint 的连接可以更自然地沿 `+Y` 方向推进

所以当前 generator 的几何修订与 waypoint / target patch 方案是相互一致的。

---

## 7. TerrainAwareVelocityCommand 的正式职责

## 7.1 输入
`TerrainAwareVelocityCommand` 后续至少应读取：

### A. 机器人状态
- 当前 base pose / yaw
- 当前 base velocity（若 metrics 需要）

### B. assignment 提供的信息
- 当前 env 是 single 还是 sequence
- 当前 env 对应的 terrain 或 sequence template
- 当前 env 的 command profile
- 当前 env 的 waypoint / centerline / target patches 信息

### C. command 配置参数
- lookahead distance
- 位置误差容忍
- heading 误差容忍
- 最大线速度/角速度
- 速度与朝向增益

---

## 7.2 输出
输出必须是：
- `lin_x`
- `lin_y`
- `ang_z`

即：
- `vel_command_b`，形状 `(num_envs, 3)`

---

## 7.3 作用逻辑
其职责应明确为：

> **根据当前位置与下一个目标 waypoint / target patch 的误差，解算一个平面速度命令，而不是进行路径规划。**

一个合理的 V1 流程应为：
1. 通过 assignment 获取当前 env 的 active target source
2. 选取当前 lookahead waypoint 或 target patch
3. 计算机器人当前 pose 到该点的误差
4. 解算：
   - 前向速度 `lin_x`
   - 横向速度 `lin_y`
   - 航向角速度 `ang_z`

---

## 7.4 这层明确不做的内容
- 不做自主路径搜索
- 不做高层 navigation
- 不直接从视觉推断去哪走
- 不负责生成路径本身

这些都不属于当前 V1 范围。

---

## 8. 推荐的 command source 分层

为了后续可扩展性，建议将 command source 概念显式化：

### A. `SingleTerrainWaypointSource`
来源：single terrain 的 local waypoint / target patch record

### B. `SequenceTemplateWaypointSource`
来源：sequence template 的全局 waypoint / target patch record

### C. （未来）`ManualJoystickSource`
来源：遥控器输入

### D. （未来）`PlannerSource`
来源：感知/规划模块

当前 V1 只需实现：
- A
- B

---

## 9. 与现有模块的协同关系

## 9.1 与 `terrain_registry.py`
registry 提供：
- terrain identity
- command profile
- capability
- physics/collision profile

但 registry 不负责 waypoint / patch 生成。

## 9.2 与 `sequence_generator.py`
generator 后续必须输出：
- sequence_waypoints_xy
- sequence_target_patches
- segment_waypoint_ranges
- entry/exit target

也就是说：
> generator 不仅要生成几何，还要生成 command 可消费的路径目标数据。

## 9.3 与 `terrain_assignment.py`
assignment 后续应成为 command 的直接查询入口。

command 不应自行读 template YAML，而应通过 assignment 查询：
- 当前 env 的 sequence_id
- 当前 env 的 target waypoint / patch 信息
- 当前 env 的 command profiles

## 9.4 与 scheduler/orchestrator
command 不需要直接感知调度器，只需要通过 assignment 获取当前 active sample 的 target 数据。

---

## 10. 建议新增的 terrain 子模块

建议新增：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_waypoints.py`

负责：
- single terrain anchor 定义
- single terrain waypoint record 生成
- waypoint 插值
- target patch 生成
- 基础校验

建议至少包含：
- `SingleTerrainAnchorRecord`
- `SingleTerrainTargetPatchRecord`
- `SingleTerrainWaypointRecord`
- `DEFAULT_SINGLE_TERRAIN_ANCHORS`
- `interpolate_waypoints_from_anchors(...)`
- `build_single_terrain_waypoint_record(...)`
- `build_default_single_terrain_waypoint_records(...)`

---

## 11. 当前建议的实现顺序

### Step 1
实现 single terrain anchor / waypoint / target patch 数据结构与生成逻辑。

### Step 2
让 generator 在拼接 sequence 时，同时拼接 waypoints，并输出 sequence-level waypoint / target patch metadata。

### Step 3
让 assignment 能查询：
- single terrain waypoint / target patch
- sequence template waypoint / target patch
- segment waypoint ranges

### Step 4
实现 `TerrainAwareVelocityCommand`：
- 基于 assignment 读取 target
- 解算 `lin_x / lin_y / ang_z`

### Step 5
后续如需要，再加更细的 smoothing / lookahead / segment 切换逻辑。

---

## 12. 当前总设计师结论

当前 obstacle_crossing 的 command 正式路线应定义为：

> **采用 oracle 式 single terrain / sequence template target patch + waypoint 统一方案；由 single terrain 或 sequence template 提供推荐路径骨架与局部 target patch，再由 TerrainAwareVelocityCommand 将机器人当前位置到目标点的误差解算为 `lin_x`、`lin_y`、`ang_z`，而不是在 V1 中引入自主路径规划。**

---

## 13. 给其他终端的任务提示词

下面内容可直接作为实现任务下发给另一个终端：

### 任务名称
实现 single terrain / sequence template target patch / waypoint 生成模块

### 任务目标
请在 `source/obstacle_crossing/obstacle_crossing/terrain/` 下实现一个新的 terrain 路径目标生成模块，建议命名为：
- `terrain_waypoints.py`

该模块需要实现：
1. single terrain 的 anchor / waypoint / target patch 数据结构
2. single terrain 的 waypoint 插值
3. target patch 生成
4. sequence template 的全局 waypoint / target patch 拼接支持
5. 与 `sequence_generator.py`、`terrain_assignment.py`、`TerrainAwareVelocityCommand` 的协同数据接口

### 必须遵守的约束
- 不做自主路径规划
- 采用 oracle 式路径目标输入
- 当前前进方向统一为 `+Y`
- V1 采用少量 anchor points + 自动插值
- 结果既要支持 single terrain，也要支持 sequence template
- 必须支持后续被 `TerrainAwareVelocityCommand` 直接消费

### 建议接口
- `SingleTerrainAnchorRecord`
- `SingleTerrainTargetPatchRecord`
- `SingleTerrainWaypointRecord`
- `DEFAULT_SINGLE_TERRAIN_ANCHORS`
- `interpolate_waypoints_from_anchors(...)`
- `build_single_terrain_waypoint_record(...)`
- `build_default_single_terrain_waypoint_records(...)`

### 输出要求
- 先实现 Python 常量 / dataclass 版本
- 先不要过度抽象
- 如需修改 `sequence_generator.py`、`terrain_assignment.py`，应只做最小范围的接口对接，不要重写已有主逻辑

### 交付要求
完成后请说明：
- 新增/修改了哪些文件
- 当前支持的是 waypoint 还是 target patch + waypoint 双层方案
- 如何与 sequence generator 对接
- 最小验证方式是什么

---

## 14. 当前总设计师建议

建议当前优先实现：
- single terrain 的 anchor / waypoint / target patch 生成
- sequence generator 对全局 waypoint / target patch 的拼接
- assignment 对新数据结构的读取能力
- TerrainAwareVelocityCommand 的目标消费逻辑

而不是一上来做自主路径规划或复杂优化。
