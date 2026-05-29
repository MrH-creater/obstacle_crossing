# Assignment Implementation Details

## 1. 文档目的

本文档用于给实现终端提供 `assignment` 层的具体实现细节、参数、类、方法和目标效果说明。

与 `Assignment_Requirement_Analysis.md` 不同，这份文档更偏向：
- 要写什么类
- 要暴露什么字段
- 需要调用哪些模块
- assignment 刷新逻辑应该如何组织
- 最低可接受的功能效果是什么

---

## 2. 当前实现目标

当前 assignment 层的实现目标不是“立刻接入全部训练细节”，而是先完成：

> **env -> single terrain / active sequence template 的正式绑定闭环**

也就是说：
- 从 role assignment
- 到 sample assignment
- 再到 env 查询接口

形成第一版可用链路。

---

## 3. 当前 assignment 层建议的正式结构

建议保留并完善两层结构：

### 3.1 tile/sample 层
负责表达：
- 当前可分配的 single terrain 样本
- 当前 active sequence template 样本

### 3.2 env view 层
负责表达：
- 某个 env 当前绑定哪个样本
- 该 env 的 metadata 查询

---

## 4. 必须保留的概念划分

## 4.1 role assignment
决定：
- 哪些 env 是 `single_train`
- 哪些 env 是 `sequence_train`

### 输入
- `iteration`
- `ContinuousSequenceSamplingCfg`
- `num_envs`
- 由 layout / scheduler 提供的当前 role 比例 / role counts

### 输出
例如：
```python
single_train_env_ids: torch.Tensor
sequence_train_env_ids: torch.Tensor
```

---

## 4.2 sample assignment
在 role 已知的前提下：
- `single_train` env 绑定到 single terrain cache 样本
- `sequence_train` env 绑定到 current active sequence template

### 输入
- single terrain 候选样本
- current active `SequenceTemplatePool`
- role-assigned env ids

### 输出
- 一份完整的 assignment table / view

---

## 5. 建议的数据结构

## 5.1 `AssignmentKind`
建议保留：
```python
AssignmentKind = Literal["single", "sequence"]
```

用于明确一个 assignment record 当前属于哪类样本。

---

## 5.2 `ObstacleTileAssignmentRecord`
这是样本级记录，建议至少包含：

```python
@dataclass(frozen=True)
class ObstacleTileAssignmentRecord:
    tile_index: int
    assignment_kind: AssignmentKind
    role: str
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    sequence_length: int
    sequence_id: str | None = None
    segment_ranges_y: tuple[tuple[float, float], ...] = ()
    buffer_ranges_y: tuple[tuple[float, float], ...] = ()
    sequence_total_length_y: float | None = None
    template_geometry_path: str | None = None
    template_metadata_path: str | None = None
```

### 语义
- 如果 `assignment_kind == "single"`
  - `terrain_ids` 长度为 1
  - `sequence_id = None`
  - `segment_ranges_y = ()`
- 如果 `assignment_kind == "sequence"`
  - `terrain_ids` 长度 >= 2
  - `sequence_id` 有值
  - `segment_ranges_y` / `buffer_ranges_y` / `sequence_total_length_y` 有值

---

## 5.3 `ObstacleEnvAssignmentRecord`
这是 env 级记录，建议字段与 tile record 对齐，但多一个 `env_id`：

```python
@dataclass(frozen=True)
class ObstacleEnvAssignmentRecord:
    env_id: int
    assignment_kind: AssignmentKind
    role: str
    terrain_ids: tuple[int, ...]
    terrain_keys: tuple[str, ...]
    command_profile_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    physics_profile_keys: tuple[str, ...]
    collision_profile_keys: tuple[str, ...]
    sequence_length: int
    sequence_id: str | None = None
    segment_ranges_y: tuple[tuple[float, float], ...] = ()
    buffer_ranges_y: tuple[tuple[float, float], ...] = ()
    sequence_total_length_y: float | None = None
    template_geometry_path: str | None = None
    template_metadata_path: str | None = None
    tile_index: int = -1
```

---

## 6. 建议保留的核心类

## 6.1 `ObstacleTileAssignmentTable`
职责：
- 存储 sample-level 绑定表
- 统一 single terrain 样本和 sequence template 样本

### 建议构造方式支持两条路径
#### 路径 A：旧 layout-only 路径（保兼容）
```python
ObstacleTileAssignmentTable(registry=..., layouts=...)
```

#### 路径 B：新 single + sequence pool 路径（主推）
```python
ObstacleTileAssignmentTable.from_single_layout_and_sequence_pool(
    registry=...,
    single_layout=...,
    sequence_pool=...,
    sequence_tile_count=...,
    sequence_role="sequence_train",
)
```

### 该类必须负责的事情
- 把 single terrain layout 转成 tile records
- 把 `SequenceTemplatePool.template_records` 转成 sequence tile records
- 统一两类 tile record 到一个表中

---

## 6.2 `EnvTerrainAssignmentView`
职责：
- 面向训练和评估时的 env 查询接口
- 从 env -> tile/sample 绑定中回答各种 metadata 查询

### 建议保留 / 增加的接口

#### 基础查询
- `tile_indices_for_envs(...)`
- `roles_for_envs(...)`
- `assignment_kinds_for_envs(...)`
- `terrain_ids_for_envs(...)`
- `terrain_keys_for_envs(...)`
- `sequence_lengths_for_envs(...)`

#### template 级查询
- `sequence_ids_for_envs(...)`
- `segment_ranges_y_for_envs(...)`
- `buffer_ranges_y_for_envs(...)`
- `sequence_total_lengths_for_envs(...)`
- `template_geometry_paths_for_envs(...)`
- `template_metadata_paths_for_envs(...)`

#### profile/capability 查询
- `command_profiles_for_envs(...)`
- `capabilities_for_envs(...)`
- `physics_profile_keys_for_envs(...)`
- `collision_profile_keys_for_envs(...)`

#### 分组/调试接口
- `group_env_ids_by_role(...)`
- `group_env_ids_by_terrain(...)`
- `records_for_envs(...)`

### 暂时保留但未实现的接口
- `sync_from_env_terrain_indices(...)`

这个接口当前仍可留为 future runtime integration hook。

---

## 7. role assignment 逻辑建议

## 7.1 输入来源
role assignment 的输入不应来自 assignment 自己拍脑袋，而应来自：
- `terrain_layout.py` 的 role count 结果
- 或 scheduler 解释后的 role 配额结果

### 当前建议
继续复用：
- `ObstacleTerrainLayoutBuilder.build_training_role_counts(...)`

它已经能根据：
- iteration
- sequence 课程策略

给出：
- `single_train`
- `sequence_train`
- `holdout_eval`

对应的 tile 数量。

### 注意
当前训练角色实际只使用：
- `single_train`
- `sequence_train`

`holdout_eval` 当前阶段可视为预留路径。

---

## 7.2 role assignment 的 env 选择方式
### 推荐方案
在刷新点：
- 随机抽取 `sequence_train` env ids
- 剩余 env ids 归为 `single_train`

### 原因
比“固定前 N 个 env 永远 sequence”更合理，能减少环境偏置。

### 约束
- role assignment 不应每个 step 变化
- 不应每个 env reset 都变化
- 应在：
  - 训练初始化
  - sequence pool 刷新时
  - 关键训练阶段切换时
 进行整体重采样

---

## 8. sample assignment 逻辑建议

## 8.1 single_train 样本分配
### 输入
- `single_layout`
- `registry`
- `single_train_env_ids`

### 推荐语义
- single env 从 single terrain cache 获取样本
- 允许多个 env 使用同一 single terrain
- 支持权重

## 8.2 sequence_train 样本分配
### 输入
- `current active SequenceTemplatePool`
- `sequence_train_env_ids`

### 推荐语义
- sequence env 绑定的是**template 实例**，不是抽象 terrain_ids tuple
- 允许多个 env 共享同一 template
- 当前 V1 建议使用：
  - **尽量均匀覆盖 current pool**
  - 必要时再随机打乱顺序

### 不建议
- 每个 env 一条独立 template
- 每次 query 时现场重新采样
- 只记录 terrain_ids 不记录 sequence_id

---

## 9. assignment 的刷新时机

## 正式建议
assignment 刷新只发生在：
1. 训练初始化
2. sequence pool 刷新点
3. 如有必要，训练阶段发生关键切换时

### 当前不建议
- 每 step 重采样
- 每 env reset 重采样
- 每次 query 现算

### 原因
这样可以保证：
- active pool 与 assignment 同步
- 训练分布在刷新窗口内稳定
- sequence_train 和 single_train 的比例行为可复现

---

## 10. 与当前 active pool 的协同要求

## 10.1 调度器提供什么
建议通过：
- `SequencePoolOrchestrator.ensure_active_training_pool(...)`

获得当前 active pool。

### orchestrator 输出
- `SequenceTemplatePool`
- current manifest 路径
- template records

## 10.2 assignment 如何消费
assignment 后续不应该自己扫磁盘找 `.stl/.yaml`，而应该：
- 直接消费 orchestrator 提供的 active `SequenceTemplatePool`
- 或读取 `current/sequence_pool_manifest.yaml` 所回读的 pool

### 原因
这样可以保证：
- current / archive 生命周期由调度器统一管理
- assignment 只关心“当前 active pool 是什么”
- 不会误读历史模板池

---

## 11. 与其它模块的接口关系

## 11.1 与 generator
- assignment 不生成 template
- assignment 不修改 template 内容
- assignment 只消费：
  - `SequenceTemplatePool`
  - `SequenceTemplateRecord`

## 11.2 与 layout
- assignment 不解释训练比例
- assignment 接收 role 配额/role counts
- assignment 不再参与 sequence 长度课程解释

## 11.3 与 command
后续 `TerrainAwareVelocityCommand` 应直接查询 assignment：
- 当前 env 是 single 还是 sequence
- sequence 的 command profiles
- 将来如需要，还可以基于 segment ranges 做更细的控制逻辑

## 11.4 与 reward/observation/eval
assignment 应成为这些模块的统一查询入口：
- 完整通过率
- 分段通过率
- capability
- physics/collision profile
- sequence_total_length

---

## 12. 目标效果

本次 assignment 修订完成后，应至少达到以下效果：

### 12.1 对训练主线
- `single_train` 和 `sequence_train` env 数量按当前课程策略正确分配
- `sequence_train` env 真正绑定到 active sequence template，而不是仅逻辑 tuple

### 12.2 对查询接口
- 调用方能够问出：
  - 当前 env 绑定的是哪条 `sequence_id`
  - `segment_ranges_y` 是什么
  - `buffer_ranges_y` 是什么
  - command/capability/profile 是什么

### 12.3 对后续主线
为后续这些事情提供稳定基础：
- command 消费 sequence metadata
- reward 统计完整通过率 / 分段通过率
- 手动 sequence_eval 脚本复用 assignment 查询

---

## 13. 与当前代码的具体差距（实现终端应重点关注）

当前 `terrain_assignment.py` 已经有：
- tile/env record 结构
- template 字段雏形
- `from_single_layout_and_sequence_pool(...)`
- `sequence_ids_for_envs(...)`
- `segment_ranges_y_for_envs(...)`
- 等一批接口

### 但仍需重点检查和增强的点
1. role assignment 与 env id 抽样是否真正明确
2. sequence template 分配是否只是简单 round-robin，是否需要更合理的覆盖策略
3. current active pool 与 assignment 刷新时机是否严格同步
4. single 与 sequence 在统一 assignment table 中的行为是否完全一致、无歧义
5. 下游是否能无痛消费 assignment record

---

## 14. 推荐实现步骤

### Step 1
整理并确认 `ObstacleTileAssignmentRecord` / `ObstacleEnvAssignmentRecord` 字段完整性。

### Step 2
明确 role assignment 输入输出：
- single_train env ids
- sequence_train env ids

### Step 3
实现/强化：
- single sample assignment
- sequence sample assignment

### Step 4
让 `EnvTerrainAssignmentView` 的查询接口全部建立在真实 template 绑定上。

### Step 5
增加最小验证：
- 检查 sequence env 是否真的带有 `sequence_id`
- 检查 `segment_ranges_y` 是否可查询
- 检查 current active pool 变更时 assignment 是否同步更新

---

## 15. 当前总设计师结论

当前 assignment 层最重要的任务，不是继续发明新的抽样规则，而是：

> **把训练中的 env 角色分配和 active sequence template 分配真正落到一张统一、稳定、可查询的 assignment table 上。**

做到这一点后，generator、scheduler、layout 这几层才算真正形成可被训练主线和手动 eval 复用的闭环。
