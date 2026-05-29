# implementation_details_of_sequence_pool_scheduler

## 1. 文档目的

本文档记录 2026-05-27 这次围绕 sequence pool 调度层与 assignment 升级所完成的实现工作，重点说明：

- 本次新增/修改了什么
- 每个类、方法、参数的作用
- 上下游调用关系
- current / archive 的切换工作流
- assignment 如何从 layout 查询层升级为 template 消费层
- 为什么这样实现
- 最小验证方法与当前剩余缺口

本文档描述的代码位置均位于：

- `source/obstacle_crossing/obstacle_crossing/terrain/`

---

## 2. 本次工作总览

本次工作的核心目标是把已有的 `sequence_generator.py` 正式纳入训练数据流，形成第一版：

- `active sequence pool -> assignment -> env`

而不是继续让 generator 只作为一个孤立的导出工具。

本次实现完成了以下三部分：

1. **新增 sequence pool 调度/编排层**
   - 新增 `sequence_pool_scheduler.py`
   - 实现基于 iteration 的 sequence_train 决策
   - 实现 current/archive 生命周期管理
   - 实现从 YAML manifest / template metadata 回读成 typed objects

2. **升级 assignment 层**
   - `terrain_assignment.py` 不再只能表达 layout 中的抽象 terrain tuple
   - 现在可以直接绑定 active `SequenceTemplatePool`
   - 能查询 `sequence_id / segment_ranges_y / buffer_ranges_y / profiles / capabilities`

3. **给 layout 增加最小配合接口**
   - `terrain_layout.py` 新增 `build_training_role_counts(...)`
   - 让 sequence-aware 训练链路可以只复用 role 配额逻辑，而不继续依赖 layout 生成 sequence 内容

---

## 3. 本次新增/修改的文件

### 3.1 新增文件

#### `source/obstacle_crossing/obstacle_crossing/terrain/sequence_pool_scheduler.py`

新增内容：
- `SequencePoolDecision`
- `SequencePoolScheduler`
- `SequencePoolOrchestrator`
- YAML 回读 helper
- current/archive/staging 切换 helper

这是本次新增的核心控制层。

---

### 3.2 修改文件

#### `source/obstacle_crossing/obstacle_crossing/terrain/terrain_assignment.py`

升级内容：
- 扩展 tile/env assignment record
- 新增 sequence template 绑定字段
- 新增从 `single_layout + sequence_pool` 构建 assignment 的入口
- 新增 sequence 查询接口

#### `source/obstacle_crossing/obstacle_crossing/terrain/terrain_layout.py`

新增内容：
- `build_training_role_counts(...)`

作用：
- 对外暴露训练期 role counts 计算接口
- 让后续流程只拿比例/计数，不再必须依赖 layout 生成 sequence 内容

#### `source/obstacle_crossing/obstacle_crossing/terrain/__init__.py`

新增导出：
- `SequencePoolDecision`
- `SequencePoolScheduler`
- `SequencePoolOrchestrator`

---

## 4. 复用了哪些现有实现，没有重写什么

本次**没有重写** `sequence_generator.py`。

而是直接复用了以下现有实现：

### 4.1 来自 `sequence_generator.py` 的复用对象与函数

文件：`source/obstacle_crossing/obstacle_crossing/terrain/sequence_generator.py`

复用 dataclass：
- `SequenceAlignmentReport`
- `SequenceSegmentRecord`
- `SequenceTemplateRecord`
- `SequenceTemplatePool`

复用决策辅助函数：
- `should_enable_sequence_train(...)`
- `get_active_sequence_length_range(...)`
- `should_refresh_training_templates(...)`

复用生成与导出函数：
- `build_training_template_pool(...)`
- `export_sequence_template(...)`
- `export_template_pool_manifest(...)`

### 4.2 来自 `terrain_registry.py` 的复用对象与函数

文件：`source/obstacle_crossing/obstacle_crossing/terrain/terrain_registry.py`

复用内容：
- `ObstacleTerrainRegistry`
- `build_default_obstacle_crossing_registry()`
- `single_train_specs()`
- `sequence_train_specs()`
- `future_benchmark_specs()`
- `get(...)`

### 4.3 来自 `terrain_layout.py` 的复用逻辑

复用内容：
- `_role_ratios(...)`
- `_role_counts(...)`

新增了一个公开包装：
- `build_training_role_counts(...)`

这样可以复用 layout 现有的训练配额逻辑，但不复制 sequence 内容采样规则。

---

## 5. 需求约束是如何落到实现中的

本次实现遵守的训练规则来自 `ContinuousSequenceSamplingCfg` 与 generator 现有逻辑。

### 5.1 关键配置字段

定义文件：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_specs.py`

核心字段：
- `sequence_train_start_iteration`
- `sequence_train_ratio_ramp_iterations`
- `sequence_train_env_ratio_initial`
- `sequence_train_env_ratio_final`
- `min_sequence_length`
- `max_sequence_length`
- `sequence_length_stage_iterations`
- `sequence_length_stage_targets`
- `template_refresh_interval_iterations`

### 5.2 本次实现中这些规则的具体落点

- **是否启用 sequence_train**
  - 使用 `should_enable_sequence_train(iteration, sampling_cfg)`
- **当前 sequence 长度课程范围**
  - 使用 `get_active_sequence_length_range(iteration, sampling_cfg)`
- **当前是否到刷新点**
  - 使用 `should_refresh_training_templates(iteration, sampling_cfg)`
- **sequence env ratio 的线性爬升**
  - 在 `SequencePoolScheduler._sequence_ratio(...)` 内实现
- **模板条数默认约 16**
  - `SequencePoolScheduler.__init__(template_count=16)`
  - `SequencePoolOrchestrator.__init__(template_count=16)`
- **模板内容生成规则**
  - 不在 scheduler/assignment 中复制
  - 完全交给 `build_training_template_pool(...)`

这意味着：
- 训练策略由 scheduler 解释
- sequence 内容由 generator 生产
- env 绑定由 assignment 承担

三者职责分离。

---

## 6. 新增文件 `sequence_pool_scheduler.py` 详细说明

文件：
- `source/obstacle_crossing/obstacle_crossing/terrain/sequence_pool_scheduler.py`

---

### 6.1 `SequencePoolDecision`

位置：
- `sequence_pool_scheduler.py:25`

定义：
```python
@dataclass(frozen=True)
class SequencePoolDecision:
    iteration: int
    sequence_enabled: bool
    sequence_ratio: float
    active_length_range: tuple[int, int]
    template_count: int
    should_refresh: bool
    refresh_reason: str
    output_dir: str
    use_cached_pool: bool
```

#### 字段说明

- `iteration`
  - 当前训练 iteration
- `sequence_enabled`
  - 当前 iteration 下 sequence_train 是否启用
- `sequence_ratio`
  - 当前训练阶段 sequence_train 占比
- `active_length_range`
  - 当前允许的 sequence 长度范围，例如 `(2, 2)`、`(2, 4)`、`(2, 6)`
- `template_count`
  - 这次 active pool 计划生成多少条模板，当前默认 16
- `should_refresh`
  - 当前是否应该生成/刷新 pool
- `refresh_reason`
  - 当前决策原因
- `output_dir`
  - 当前 active pool 对应的输出目录，指向 `current/`
- `use_cached_pool`
  - 是否应直接复用已有 current pool

#### 这个类的职责

这是一个**纯决策结果对象**，不做任何 I/O，也不做模板生成。

---

### 6.2 `SequencePoolScheduler`

位置：
- `sequence_pool_scheduler.py:37`

职责：
- 解释 iteration 对应的训练期 sequence 决策
- 判断是否刷新
- 输出 current pool 的目标目录
- 不直接操作磁盘
- 不直接生成模板

#### 构造函数

```python
def __init__(
    self,
    *,
    train_pool_root: Path | str | None = None,
    template_count: int = 16,
) -> None:
```

#### 参数说明

- `train_pool_root`
  - sequence train pool 的根目录
  - 若未传，默认指向：
    - `repo_root/terrains/generated_sequences/train`
- `template_count`
  - 默认生成模板数
  - 当前默认值：`16`
  - 若小于 0，会抛 `ValueError`

#### 成员变量

- `self.train_pool_root`
- `self.template_count`

---

### 6.3 `SequencePoolScheduler.build_decision(...)`

位置：
- `sequence_pool_scheduler.py:49`

签名：
```python
def build_decision(
    self,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
    *,
    current_manifest_exists: bool = False,
) -> SequencePoolDecision:
```

#### 参数说明

- `iteration`
  - 当前训练 iteration
- `sampling_cfg`
  - sequence 训练配置对象
- `current_manifest_exists`
  - 当前 `current/sequence_pool_manifest.yaml` 是否已存在
  - 用于判断：
    - 是否缺 current pool
    - 是否复用 cached pool

#### 内部调用的上游函数

1. `should_enable_sequence_train(iteration, sampling_cfg)`
2. `should_refresh_training_templates(iteration, sampling_cfg)`
3. `get_active_sequence_length_range(iteration, sampling_cfg)`
4. `self._sequence_ratio(iteration, sampling_cfg)`

#### 核心逻辑

1. 判断当前是否启用 sequence_train
2. 判断当前是否在计划刷新点
3. 取当前有效长度范围
4. 若 sequence 已启用，则计算当前 ratio
5. 若 sequence 已启用，并且：
   - 到了刷新点，或者
   - 当前根本没有 manifest
   则 `should_refresh=True`
6. 若 sequence 已启用、manifest 存在、且当前不刷新
   - `use_cached_pool=True`
7. 根据状态生成 `refresh_reason`

#### `refresh_reason` 语义

当前实现使用以下值：
- `sequence_train_disabled`
- `initial_activation`
- `missing_current_pool`
- `scheduled_refresh`
- `reuse_current_pool`

#### 输出

返回 `SequencePoolDecision`。

这是 orchestrator 的直接输入。

---

### 6.4 `SequencePoolScheduler.current_output_dir()`

位置：
- `sequence_pool_scheduler.py:87`

作用：
- 返回当前 active pool 目录：
  - `train_pool_root / "current"`

---

### 6.5 `SequencePoolScheduler.current_manifest_path()`

位置：
- `sequence_pool_scheduler.py:90`

作用：
- 返回当前 active manifest 路径：
  - `current/sequence_pool_manifest.yaml`

---

### 6.6 `SequencePoolScheduler._sequence_ratio(...)`

位置：
- `sequence_pool_scheduler.py:93`

签名：
```python
def _sequence_ratio(self, iteration: int, sampling_cfg: ContinuousSequenceSamplingCfg) -> float:
```

#### 内部调用

- `_ramp_progress(...)`
- `_lerp(...)`

#### 逻辑

- 根据 `sequence_train_start_iteration` 和 `sequence_train_ratio_ramp_iterations` 计算 alpha
- 在：
  - `sequence_train_env_ratio_initial`
  - `sequence_train_env_ratio_final`
  之间线性插值

这和 `terrain_layout.py` 现有 ratio 语义保持一致。

---

## 7. `SequencePoolOrchestrator` 详细说明

位置：
- `sequence_pool_scheduler.py:106`

职责：
- 调 scheduler 获取决策
- 调 generator 生产 template pool
- 把 pool 导出到 staging
- 把旧 current 归档到 archive
- 提升 staging 为 current
- 从 current 回读 active `SequenceTemplatePool`

它是本次新增的**执行层**。

---

### 7.1 构造函数

```python
def __init__(
    self,
    *,
    train_pool_root: Path | str | None = None,
    template_count: int = 16,
    allow_duplicate_terrains: bool = False,
    terrain_root: Path | str | None = None,
    input_backend: str = "stl",
    output_backend: str = "stl",
) -> None:
```

#### 参数说明

- `train_pool_root`
  - train pool 根目录
- `template_count`
  - 每次生成模板条数
- `allow_duplicate_terrains`
  - 是否允许 sequence 中重复 terrain
  - 当前默认 `False`
- `terrain_root`
  - 单段 terrain mesh 的根目录
  - 传给 generator
- `input_backend`
  - generator 读 segment geometry 使用的格式
  - 当前默认 `stl`
- `output_backend`
  - generator 导出 sequence geometry 使用的格式
  - 当前默认 `stl`

#### 成员变量

- `self.scheduler`
- `self.allow_duplicate_terrains`
- `self.terrain_root`
- `self.input_backend`
- `self.output_backend`

---

### 7.2 `ensure_active_training_pool(...)`

位置：
- `sequence_pool_scheduler.py:123`

签名：
```python
def ensure_active_training_pool(
    self,
    registry: ObstacleTerrainRegistry,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
    *,
    seed: int,
) -> SequenceTemplatePool:
```

#### 参数说明

- `registry`
  - terrain registry
  - generator 采样 terrain spec 时的事实来源
- `iteration`
  - 当前训练 iteration
- `sampling_cfg`
  - sequence 训练配置
- `seed`
  - 本次模板生成随机种子

#### 上游调用

1. `self.scheduler.build_decision(...)`
2. `self.current_pool_manifest_path().exists()`
3. `self.load_current_pool()`
4. `build_training_template_pool(...)`
5. `replace(pool, refresh_reason=decision.refresh_reason)`
6. `self._staging_dir_for_iteration(iteration)`
7. `self._export_pool_to_dir(pool, staging_dir)`
8. `self.archive_current_pool()`
9. `self.promote_new_pool_to_current(staging_dir)`
10. 再次 `self.load_current_pool()`

#### 详细工作流

##### 情况 A：sequence 未启用

若 `decision.sequence_enabled == False`：
- 不做任何磁盘写入
- 返回一个空的 `SequenceTemplatePool`
  - `template_records=()`
  - `refresh_reason=decision.refresh_reason`

##### 情况 B：直接复用 current pool

若 `decision.use_cached_pool == True`：
- 调 `load_current_pool()`
- 从 `current/sequence_pool_manifest.yaml` 读取 active pool
- 返回回读结果

##### 情况 C：需要刷新

若要刷新：
1. 调 `build_training_template_pool(...)` 生成新的 in-memory `SequenceTemplatePool`
2. 用 `replace(...)` 把 `refresh_reason` 改成 scheduler 给出的原因
3. 创建 staging 目录
4. 导出模板与 manifest 到 staging
5. 若已有 current，则归档 current
6. 把 staging 提升为 current
7. 再从 current manifest 回读 active pool
8. 返回 active pool

#### 设计原因

最后返回时选择**从 current 回读**，而不是直接返回刚生成的 pool，有两个原因：
- 确认落盘后的 YAML schema 与读侧逻辑是一致的
- assignment 后续消费的就是这份 current pool

---

### 7.3 `current_pool_manifest_path()`

位置：
- `sequence_pool_scheduler.py:178`

作用：
- 返回当前 active manifest 路径
- 直接委托给 `self.scheduler.current_manifest_path()`

---

### 7.4 `current_template_records()`

位置：
- `sequence_pool_scheduler.py:181`

作用：
- 读取当前 active pool
- 返回 `tuple[SequenceTemplateRecord, ...]`
- 若 current pool 不存在，则返回空 tuple

这是下游 assignment / training scene 直接拿 active templates 的简便入口。

---

### 7.5 `load_current_pool()`

位置：
- `sequence_pool_scheduler.py:185`

作用：
- 若 current manifest 不存在，返回 `None`
- 否则调用 `_load_pool_manifest(manifest_path)`
- 将 current YAML 重新恢复成 `SequenceTemplatePool`

#### 为什么需要这个方法

generator 目前只负责**导出**，并没有现成的回读 API。

本次为了让 assignment 能真实消费 active pool，需要补上读侧。

---

### 7.6 `archive_current_pool()`

位置：
- `sequence_pool_scheduler.py:191`

作用：
- 把旧 `current/` 整体移动到 `archive/`

#### 逻辑

1. 若 `current/` 不存在，返回 `None`
2. 确保 `archive/` 根目录存在
3. 尝试 `load_current_pool()`
4. 若能读到当前 pool，则使用：
   - `iter_<current_pool.iteration:08d>`
   作为 archive 目录名前缀
5. 若目录重名，则通过 `_unique_dir(...)` 自动加后缀 `__1`, `__2`, ...
6. 用 `shutil.move(...)` 把整个 current 目录移动进去

#### 这个设计的意义

- archive 是**整套池子**的历史快照
- 不逐文件复制，不逐文件覆盖
- 切换更清晰，也更容易排查问题

---

### 7.7 `promote_new_pool_to_current(...)`

位置：
- `sequence_pool_scheduler.py:206`

签名：
```python
def promote_new_pool_to_current(self, staging_dir: Path) -> Path:
```

#### 参数说明

- `staging_dir`
  - 新池所在的 staging 目录

#### 逻辑

1. 定位 current 目录
2. 若 current 已存在，直接抛 `FileExistsError`
3. 将 staging 整体移动为 current
4. 调 `_rewrite_current_pool_paths(current_dir)`
5. 返回新的 current 目录

#### 为什么 promotion 后还要重写路径

因为模板导出时发生在 staging 下：
- `geometry_output_path`
- `metadata_output_path`

最初写入的是 staging 路径。

一旦目录被提升为 current，这些 YAML 内部路径就需要改成 current 路径，否则后续 manifest/template 回读会指向过期路径。

---

### 7.8 `_export_pool_to_dir(...)`

位置：
- `sequence_pool_scheduler.py:226`

签名：
```python
def _export_pool_to_dir(self, pool: SequenceTemplatePool, output_dir: Path) -> SequenceTemplatePool:
```

#### 上游调用

- `export_sequence_template(...)`
- `export_template_pool_manifest(...)`
- `replace(...)`

#### 逻辑

1. 逐个 template 调 `export_sequence_template(...)`
2. 得到带有输出路径的 exported template records
3. 用 `replace(pool, template_records=exported_templates)` 生成 exported pool
4. 对 exported pool 调 `export_template_pool_manifest(...)`
5. 返回 exported pool

#### 输入输出关系

输入：
- 纯内存中的 `SequenceTemplatePool`

输出：
- 已导出到磁盘、并带真实输出路径的 `SequenceTemplatePool`

---

### 7.9 `_rewrite_current_pool_paths(...)`

位置：
- `sequence_pool_scheduler.py:241`

作用：
- 把 `current/sequence_pool_manifest.yaml` 和各个 `sequence_*.yaml` 中的路径字段重写为 current 路径

#### 具体重写字段

在 manifest 中重写：
- `geometry_output_path`
- `metadata_output_path`

在每个 template YAML 中重写：
- `geometry_output_path`
- `metadata_output_path`

#### 为什么是必要步骤

因为当前工作流是：
- 先写到 `_staging/`
- 再移动成 `current/`

如果不重写，manifest 内部仍然保存 staging 路径，promotion 后就会失效。

---

## 8. YAML 回读 helper 详细说明

这部分实现的目的，是让 scheduler/orchestrator 能把 generator 输出的 YAML 再恢复成既有 dataclass。

---

### 8.1 `_load_pool_manifest(...)`

位置：
- `sequence_pool_scheduler.py:265`

签名：
```python
def _load_pool_manifest(manifest_path: Path) -> SequenceTemplatePool:
```

#### 输入

- `manifest_path`
  - `current/sequence_pool_manifest.yaml`

#### 逻辑

1. 读取 manifest YAML
2. 逐个遍历 `templates`
3. 取出每个模板的 `metadata_output_path`
4. 调 `_load_template_record(Path(metadata_output_path))`
5. 将所有模板恢复为 `tuple[SequenceTemplateRecord, ...]`
6. 再构造 `SequenceTemplatePool`

#### 为什么不只读 manifest

因为 manifest 只包含摘要字段，比如：
- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `sequence_length`
- `sequence_total_length_y`
- geometry/metadata 输出路径

assignment 需要的细节字段，如：
- `segment_ranges_y`
- `buffer_ranges_y`
- `command_profile_keys`
- `required_capabilities`
- `physics_profile_keys`
- `collision_profile_keys`

都在单模板 YAML 中。

所以必须：
- manifest -> 定位 template YAML
- template YAML -> 恢复完整 template record

---

### 8.2 `_load_template_record(...)`

位置：
- `sequence_pool_scheduler.py:290`

签名：
```python
def _load_template_record(metadata_path: Path) -> SequenceTemplateRecord:
```

#### 输入

- `metadata_path`
  - 某条 `sequence_<id>.yaml`

#### 逻辑

1. 读取 template YAML
2. 恢复 `segment_records`
   - 构造成 `tuple[SequenceSegmentRecord, ...]`
3. 恢复 `alignment_reports`
   - 构造成 `tuple[SequenceAlignmentReport, ...]`
4. 恢复 `SequenceTemplateRecord`
   - `sequence_mesh=None`
   - 因为这里做的是 metadata 回读，不是 mesh 再加载

#### 回读字段

- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `sequence_length`
- `segment_offsets_y`
- `segment_lengths_y`
- `buffer_lengths_y`
- `segment_ranges_y`
- `buffer_ranges_y`
- `sequence_total_length_y`
- `command_profile_keys`
- `required_capabilities`
- `physics_profile_keys`
- `collision_profile_keys`
- `segment_records`
- `alignment_reports`
- `input_format`
- `output_format`
- `forward_axis`
- `geometry_output_path`
- `metadata_output_path`
- `warnings`

#### 为什么 `sequence_mesh=None`

assignment 只需要元数据，不需要把所有 STL 再反序列化到内存。

因此：
- 读 metadata
- 保持 typed record 完整
- 不引入不必要的 mesh load 成本

---

### 8.3 类型转换辅助函数

位置：
- `sequence_pool_scheduler.py:356` 之后

包括：
- `_tuple_int_pair(...)`
- `_triple_float(...)`
- `_range_tuple(...)`
- `_optional_float(...)`
- `_optional_str(...)`

作用：
- 把 YAML 中的 list / None / 标量安全恢复成目标 dataclass 字段类型

---

### 8.4 路径辅助函数

包括：
- `_default_train_pool_root()`
- `_repository_root()`
- `_unique_dir(...)`

作用：
- 统一 train pool 根目录
- 与 generator 的 repo-root 语义保持一致
- 生成不冲突的 archive / staging 目录名

---

## 9. `terrain_assignment.py` 详细说明

文件：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_assignment.py`

本次这里的重点是：
- 从“layout 查询层”升级成“真实 template 绑定层”

---

### 9.1 新增 `AssignmentKind`

位置：
- `terrain_assignment.py:17`

定义：
```python
AssignmentKind = Literal["single", "sequence"]
```

作用：
- 明确一个 tile/env 当前绑定的是：
  - 单地形
  - 还是 sequence template

---

### 9.2 扩展 `ObstacleEnvAssignmentRecord`

位置：
- `terrain_assignment.py:20`

相比之前新增的字段：
- `assignment_kind`
- `sequence_id`
- `segment_ranges_y`
- `buffer_ranges_y`
- `sequence_total_length_y`
- `template_geometry_path`
- `template_metadata_path`

#### 作用

该对象现在可以完整表达：
- 一个 env 当前绑定的是 single 还是 sequence
- 若是 sequence，它绑定的是哪个 active template
- 该 sequence 的各 segment / buffer 边界是什么
- 该 sequence 的 geometry / metadata 文件在哪

---

### 9.3 扩展 `ObstacleTileAssignmentRecord`

位置：
- `terrain_assignment.py:41`

新增字段与 env record 对齐。

#### 作用

tile record 是 env record 的底层来源。

现在 tile record 可以直接承载：
- single tile 的 terrain metadata
- sequence tile 的 template metadata

从而让 `EnvTerrainAssignmentView` 不需要再推导 sequence 内容。

---

### 9.4 `ObstacleTileAssignmentTable` 的升级

位置：
- `terrain_assignment.py:61`

职责仍然是：
- 把输入 flatten 成 tile-level records

但是输入现在支持两种来源：
- 原有 `layouts`
- 新增 `tile_records`

#### 构造函数签名

```python
def __init__(
    self,
    registry: ObstacleTerrainRegistry,
    layouts: dict[str, ObstacleTerrainLayout] | None = None,
    *,
    tile_records: Sequence[ObstacleTileAssignmentRecord] | None = None,
)
```

#### 参数说明

- `registry`
  - terrain registry
- `layouts`
  - 兼容旧路径，从 layout 自动构建 tile records
- `tile_records`
  - 新路径，允许外部直接提供已经构建好的 tile records

这样就能支持：
- 原有 layout-only 逻辑
- 新的 single + sequence pool 混合逻辑

---

### 9.5 `ObstacleTileAssignmentTable.from_single_layout_and_sequence_pool(...)`

位置：
- `terrain_assignment.py:82`

签名：
```python
@classmethod
def from_single_layout_and_sequence_pool(
    cls,
    registry: ObstacleTerrainRegistry,
    single_layout: ObstacleTerrainLayout | None,
    sequence_pool: SequenceTemplatePool,
    sequence_tile_count: int,
    *,
    sequence_role: str = "sequence_train",
) -> ObstacleTileAssignmentTable:
```

#### 参数说明

- `registry`
  - 用于 single layout tile 的 spec/profile/capability 查询
- `single_layout`
  - single_train 部分的 layout
- `sequence_pool`
  - 当前 active sequence template pool
- `sequence_tile_count`
  - 需要为 sequence role 分配多少 tile
- `sequence_role`
  - sequence tile 的 role 名，默认 `sequence_train`

#### 内部调用

1. `_build_single_layout_tile_records(...)`
2. `_build_sequence_tile_records(...)`
3. 用合并后的 `tile_records` 调类构造器

#### 设计意义

这是新的关键桥接点：
- single tile 继续来自 layout
- sequence tile 直接来自 active template pool
- 二者合并为统一 tile table

---

### 9.6 `_build_tile_records()`

位置：
- `terrain_assignment.py:107`

这是旧路径保留的核心逻辑。

#### 输入来源

- `self.layouts`

#### 行为

1. 遍历 layout 的每个 cell
2. 读取：
   - `terrain_ids`
   - `terrain_keys`
   - `command_profile_keys`
   - `sequence_lengths`
3. 用 `registry.get(terrain_id)` 补齐：
   - `required_capabilities`
   - `physics_profile_keys`
   - `collision_profile_keys`
4. 生成 `ObstacleTileAssignmentRecord`

#### 本次调整点

新增：
- `assignment_kind`
  - `seq_len == 1` -> `single`
  - 否则 -> `sequence`
- 其余 template 专属字段在 layout-only 路径下填默认空值

这让旧路径与新 record 结构保持兼容。

---

### 9.7 `_build_single_layout_tile_records(...)`

位置：
- `terrain_assignment.py:148`

作用：
- 把 `single_layout` 独立转成 tile records
- 支持指定 `starting_tile_index`

#### 内部调用

1. 先用旧逻辑生成 table
2. 取其 `records()`
3. 用 `replace_tile_index(...)` 重排 tile 索引

#### 为什么单独拆出来

因为新路径中：
- single tile 和 sequence tile 需要先分别构建
- 然后再拼接为一个统一 tile table

---

### 9.8 `_build_sequence_tile_records(...)`

位置：
- `terrain_assignment.py:161`

签名：
```python
@staticmethod
def _build_sequence_tile_records(
    sequence_pool: SequenceTemplatePool,
    sequence_tile_count: int,
    *,
    starting_tile_index: int,
    role: str,
) -> list[ObstacleTileAssignmentRecord]:
```

#### 参数说明

- `sequence_pool`
  - 当前 active sequence template pool
- `sequence_tile_count`
  - 需要生成多少 sequence tile
- `starting_tile_index`
  - sequence 部分 tile 的起始编号
- `role`
  - tile role，一般为 `sequence_train`

#### 核心逻辑

1. 若 `sequence_tile_count == 0`，直接返回空
2. 若 `sequence_pool.template_records` 为空但 tile_count > 0，抛异常
3. 逐个构建 sequence tile record
4. 若 `sequence_tile_count > len(template_records)`：
   - 使用 `offset % len(template_records)` 循环复用模板

#### 为什么用循环复用

因为：
- role 配额可能大于当前 active template 数量
- 本次任务要求的是 active pool -> assignment -> env
- 不是要求每个 env 都拥有独立 sequence 几何

因此在 V1 中：
- active pool 是模板池
- env/tile 可以复用模板
- 这样最符合既定设计目标

#### template 字段如何映射到 tile record

直接拷贝：
- `terrain_ids`
- `terrain_keys`
- `command_profile_keys`
- `required_capabilities`
- `physics_profile_keys`
- `collision_profile_keys`
- `sequence_length`
- `sequence_id`
- `segment_ranges_y`
- `buffer_ranges_y`
- `sequence_total_length_y`
- `geometry_output_path`
- `metadata_output_path`

也就是说，assignment 不再自己重建 sequence metadata。

---

### 9.9 `_merge_capabilities(...)`

位置：
- `terrain_assignment.py:199`

作用：
- 在 layout-only 路径下合并多个 terrain spec 的 capability
- 保持去重并保留出现顺序

注意：
- 对 sequence template 路径，本次不再用它合并 capability
- 直接信任 `SequenceTemplateRecord.required_capabilities`

---

## 10. `EnvTerrainAssignmentView` 的升级

位置：
- `terrain_assignment.py:222`

职责依旧是：
- 提供 env -> tile -> metadata 的统一运行时查询视图

但现在它既能服务：
- 旧 layout-only 路径
- 新 single + active sequence pool 路径

---

### 10.1 构造函数 `__init__(...)`

位置：
- `terrain_assignment.py:230`

仍保持原有约束：
- `env_to_tile_index` 必须是一维 tensor
- 不能引用越界 tile
- 不能在空 tile_table 上给出非空 env 映射

这保证了新路径仍然是 simulator-agnostic 的纯数据视图。

---

### 10.2 `from_layouts_round_robin(...)`

位置：
- `terrain_assignment.py:253`

这是旧路径保留接口。

作用：
- 从 layout 构建 tile table
- 用 round-robin 将 env 映射到 tile

当前仍可正常使用，保证兼容性。

---

### 10.3 `from_single_layout_and_sequence_pool(...)`

位置：
- `terrain_assignment.py:266`

签名：
```python
@classmethod
def from_single_layout_and_sequence_pool(
    cls,
    registry: ObstacleTerrainRegistry,
    single_layout: ObstacleTerrainLayout | None,
    sequence_pool: SequenceTemplatePool,
    sequence_tile_count: int,
    num_envs: int,
    *,
    sequence_role: str = "sequence_train",
) -> EnvTerrainAssignmentView:
```

#### 参数说明

- `registry`
  - terrain registry
- `single_layout`
  - single terrain 布局
- `sequence_pool`
  - 当前 active sequence pool
- `sequence_tile_count`
  - sequence role 要分配多少 tile
- `num_envs`
  - env 总数
- `sequence_role`
  - sequence tile 的 role 名

#### 内部调用

1. `ObstacleTileAssignmentTable.from_single_layout_and_sequence_pool(...)`
2. `torch.arange(num_envs) % len(tile_table)`
3. 类构造器 `cls(...)`

#### 输出

返回一个新的 `EnvTerrainAssignmentView`

#### 设计意义

这就是新链路真正连起来的位置：
- single layout -> single tile
- active sequence pool -> sequence tile
- tile table -> env round-robin 映射

---

### 10.4 保留的查询接口

这些接口仍然保留：
- `tile_indices_for_envs(...)`
- `terrain_ids_for_envs(...)`
- `terrain_keys_for_envs(...)`
- `command_profiles_for_envs(...)`
- `capabilities_for_envs(...)`
- `physics_profile_keys_for_envs(...)`
- `collision_profile_keys_for_envs(...)`
- `roles_for_envs(...)`
- `sequence_lengths_for_envs(...)`
- `group_env_ids_by_terrain(...)`
- `group_env_ids_by_role(...)`
- `records_for_envs(...)`

区别在于：
- 当 env 对应的是 sequence tile 时，这些值现在来自真实 template record
- 不再只是 layout 里的抽象 tuple

---

### 10.5 新增查询接口

#### `assignment_kinds_for_envs(...)`

位置：
- `terrain_assignment.py:356`

作用：
- 返回每个 env 当前绑定的是 `single` 还是 `sequence`

#### `sequence_ids_for_envs(...)`

位置：
- `terrain_assignment.py:364`

作用：
- 返回每个 env 当前绑定的 `sequence_id`
- single env 对应 `None`

#### `segment_ranges_y_for_envs(...)`

位置：
- `terrain_assignment.py:372`

作用：
- 返回每个 env 的 segment Y 区间
- sequence env 上来自 template record
- single env 上为空 tuple

#### `buffer_ranges_y_for_envs(...)`

位置：
- `terrain_assignment.py:380`

作用：
- 返回每个 env 的 buffer Y 区间
- sequence env 上来自 template record

---

### 10.6 `records_for_envs(...)`

位置：
- `terrain_assignment.py:414`

作用：
- 返回 `list[ObstacleEnvAssignmentRecord]`

#### 本次新增写入到 env record 的字段

- `assignment_kind`
- `sequence_id`
- `segment_ranges_y`
- `buffer_ranges_y`
- `sequence_total_length_y`
- `template_geometry_path`
- `template_metadata_path`

这使得调用方可以一次性拿到完整 env 绑定信息。

---

### 10.7 `sync_from_env_terrain_indices(...)`

位置：
- `terrain_assignment.py:453`

状态：
- 仍未实现

原因：
- 本次目标是把 active pool -> assignment -> env 的元数据链路打通
- 不是实现 Isaac Lab scene 中的实际 terrain runtime 索引同步

因此本次仍保持 simulator-agnostic。

---

## 11. `terrain_layout.py` 的最小配合改动

文件：
- `source/obstacle_crossing/obstacle_crossing/terrain/terrain_layout.py`

---

### 11.1 `build_training_role_counts(...)`

位置：
- `terrain_layout.py:238`

签名：
```python
def build_training_role_counts(
    self,
    total_tiles: int,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> dict[str, int]:
```

#### 参数说明

- `total_tiles`
  - 总 tile 数
- `iteration`
  - 当前训练 iteration
- `sampling_cfg`
  - sequence 训练配置

#### 内部调用

1. `_role_ratios(iteration, sampling_cfg)`
2. `_role_counts(total_tiles, role_ratios, sampling_cfg)`

#### 输出

返回：
```python
{
    "single_train": ...,
    "sequence_train": ...,
    "holdout_eval": ...,
}
```

#### 作用

新链路可以：
- 只拿 role 配额
- 然后自己决定 single tile 与 active sequence template 的绑定

而不再必须让 layout 去生成 sequence 内容。

---

### 11.2 `build_mixed_layout(...)` 的小调整

位置：
- `terrain_layout.py:184`

调整点：
- 原本内部直接计算 `role_ratios` + `role_counts`
- 现在改为调用新公开的 `build_training_role_counts(...)`

#### 意义

- 保持逻辑单一出口
- 让新调用方和旧调用方使用一致的 role count 计算逻辑

---

## 12. `__init__.py` 的包导出调整

文件：
- `source/obstacle_crossing/obstacle_crossing/terrain/__init__.py`

新增导出：
- `SequencePoolDecision`
- `SequencePoolScheduler`
- `SequencePoolOrchestrator`

#### 作用

调用方现在可以直接这样导入：
```python
from obstacle_crossing.terrain import SequencePoolOrchestrator
```

不必深入到具体模块路径。

---

## 13. 上下游调用关系总图

下面给出这次新增链路的逻辑调用图。

### 13.1 调度与生成链路

```text
训练入口 / 外部调用方
    -> SequencePoolOrchestrator.ensure_active_training_pool(...)
        -> SequencePoolScheduler.build_decision(...)
            -> should_enable_sequence_train(...)
            -> should_refresh_training_templates(...)
            -> get_active_sequence_length_range(...)
            -> _sequence_ratio(...)
        -> [如果复用 current]
            -> load_current_pool()
                -> _load_pool_manifest(...)
                    -> _load_template_record(...)
        -> [如果刷新]
            -> build_training_template_pool(...)
            -> _export_pool_to_dir(...)
                -> export_sequence_template(...)
                -> export_template_pool_manifest(...)
            -> archive_current_pool()
            -> promote_new_pool_to_current(...)
                -> _rewrite_current_pool_paths(...)
            -> load_current_pool()
                -> _load_pool_manifest(...)
                    -> _load_template_record(...)
```

---

### 13.2 assignment 绑定链路

```text
训练入口 / 外部调用方
    -> ObstacleTerrainLayoutBuilder.build_training_role_counts(...)
    -> build_single_terrain_layout(...)
    -> SequencePoolOrchestrator.current_template_records() / ensure_active_training_pool(...)
    -> EnvTerrainAssignmentView.from_single_layout_and_sequence_pool(...)
        -> ObstacleTileAssignmentTable.from_single_layout_and_sequence_pool(...)
            -> _build_single_layout_tile_records(...)
            -> _build_sequence_tile_records(...)
        -> env_to_tile_index = arange(num_envs) % len(tile_table)
```

---

### 13.3 env 查询链路

```text
调用方
    -> EnvTerrainAssignmentView.sequence_ids_for_envs(...)
    -> EnvTerrainAssignmentView.segment_ranges_y_for_envs(...)
    -> EnvTerrainAssignmentView.terrain_ids_for_envs(...)
    -> EnvTerrainAssignmentView.command_profiles_for_envs(...)
    -> EnvTerrainAssignmentView.capabilities_for_envs(...)
    -> EnvTerrainAssignmentView.records_for_envs(...)
        -> tile_table.get(tile_index)
            -> ObstacleTileAssignmentRecord
```

---

## 14. current / archive / staging 工作流详解

本次实现采用三段目录生命周期：

```text
terrains/generated_sequences/train/
    current/
    archive/
    _staging/
```

### 14.1 为什么不是直接覆盖 current

如果直接在 `current/` 中边写边覆盖，会有两个问题：
- 刷新过程中 current 可能处于半写入状态
- manifest 与 template YAML 可能短暂不一致

### 14.2 当前实现的切换流程

#### 第一步：生成新池到 staging

路径示例：
- `_staging/iter_00010000/`

包含：
- `sequence_<id>.stl`
- `sequence_<id>.yaml`
- `sequence_pool_manifest.yaml`

#### 第二步：归档旧 current

若存在旧 current：
- 移动到 `archive/iter_<old_iteration>/`
- 若同名冲突，则自动追加 `__1`, `__2`...

#### 第三步：promote staging 为 current

- `shutil.move(staging_dir, current_dir)`

#### 第四步：重写 manifest/template 路径

将 YAML 内的路径从 staging 改为 current。

### 14.3 下游如何消费

下游统一读取：
- `current/sequence_pool_manifest.yaml`

这是 active pool 的唯一对外入口。

---

## 15. 参数与数据流细节

### 15.1 scheduler 相关参数流

#### 输入
- `iteration`
- `sampling_cfg`
- `current_manifest_exists`

#### 输出
- `SequencePoolDecision`

#### 决定的内容
- 当前是否启用 sequence
- 当前长度范围
- 当前 ratio
- 当前是否刷新
- 当前是否复用 cached pool
- active pool 所在目录

---

### 15.2 orchestrator 相关参数流

#### 输入
- `registry`
- `iteration`
- `sampling_cfg`
- `seed`
- 构造时配置的：
  - `train_pool_root`
  - `template_count`
  - `allow_duplicate_terrains`
  - `terrain_root`
  - `input_backend`
  - `output_backend`

#### 输出
- `SequenceTemplatePool`

#### 中间文件输出
- `current/sequence_pool_manifest.yaml`
- `current/sequence_<id>.yaml`
- `current/sequence_<id>.stl`

---

### 15.3 assignment 相关参数流

#### 输入
- `single_layout`
- `sequence_pool`
- `sequence_tile_count`
- `num_envs`
- `registry`

#### 输出
- `EnvTerrainAssignmentView`

#### 中间对象
- `ObstacleTileAssignmentTable`
- `ObstacleTileAssignmentRecord`
- `ObstacleEnvAssignmentRecord`

#### env 查询输出示例
- `assignment_kind`
- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `command_profile_keys`
- `required_capabilities`
- `physics_profile_keys`
- `collision_profile_keys`
- `segment_ranges_y`
- `buffer_ranges_y`
- `sequence_total_length_y`
- `template_geometry_path`
- `template_metadata_path`

---

## 16. 这次实现为什么这样设计

### 16.1 不重写 generator

原因：
- generator 已经被确认是 V1 可用实现
- 已经实现了：
  - terrain 采样
  - 无放回 / 排序
  - buffer 生成
  - +Y 方向标准化
  - Z 检查
  - STL + YAML 导出

因此最合理的做法是：
- scheduler 只负责“何时生成/是否复用/放到哪里”
- generator 继续负责“生成什么”

### 16.2 不把 sequence 内容抽样塞回 layout

原因：
- layout 的职责应收缩到 role 配额与 role 计数
- 如果继续让 layout 决定 sequence 内容，会形成：
  - generator 一套 sequence 逻辑
  - layout 又一套 sequence 逻辑
  - assignment 又可能再来一套 sequence 逻辑

这正是本次要避免的分叉。

### 16.3 assignment 直接消费 `SequenceTemplatePool`

原因：
- assignment 需要回答的不是抽象 sequence，而是真实模板绑定信息
- `SequenceTemplateRecord` 已经是最完整、最真实的 metadata 载体
- 直接消费模板记录比自己推导更稳妥

### 16.4 current / archive 做整目录切换

原因：
- 切换语义清晰
- 历史可追溯
- 避免 partial write
- 便于后续 debug 与回滚分析

---

## 17. 最小验证方法与已完成验证

### 17.1 已完成的验证

本次已完成以下最小 smoke verification：

#### A. Python 编译检查

命令：
- 对以下文件执行 `python -m py_compile`
  - `sequence_pool_scheduler.py`
  - `terrain_assignment.py`
  - `terrain_layout.py`
  - `__init__.py`

结果：
- 通过

#### B. scheduler decision smoke check

验证点：
- `iteration=0`
- `iteration=10000`
- `iteration=15000`
- `iteration=20000`
- `iteration=30000`

确认结果：
- `0`：sequence disabled
- `10000`：enabled，`initial_activation`
- `15000`：ratio `0.075`，长度范围 `(2, 4)`
- `20000`：ratio `0.15`，长度范围 `(2, 6)`
- `30000`：ratio `0.3`，长度范围 `(2, 6)`

#### C. assignment smoke check

使用：
- 一个 small single layout
- 一个手工构造的 `SequenceTemplatePool`
- `EnvTerrainAssignmentView.from_single_layout_and_sequence_pool(...)`

确认结果：
- `assignment_kinds_for_envs()` 正确区分 single/sequence
- `sequence_ids_for_envs()` 正确返回 `sequence_id`
- `segment_ranges_y_for_envs()` 正确返回模板 segment ranges
- `terrain_ids_for_envs()` 正确混合 single 与 sequence

#### D. orchestrator current/archive lifecycle check

在临时目录下验证：
- staging 导出
- promote 为 current
- archive 旧 current
- 再 promote 新池为 current
- 从 current manifest 回读 active pool

确认结果：
- `current_after_promote` 正确
- `archive_dir` 正确创建
- `current_after_refresh` 正确切换到新 iteration

---

## 18. 当前仍未打通的环节

本次实现的是“第一版调度层 + assignment 消费层”，不是整个训练系统的最终接入。

仍未完成的部分包括：

1. **训练主循环接线**
   - 还没有把 orchestrator 正式接到 `train.py` / PPO runner

2. **sequence_eval 独立脚本/调度**
   - 本次没有实现 sequence_eval automation

3. **runtime terrain 索引同步**
   - `sync_from_env_terrain_indices()` 仍未实现

4. **真实 scene 物理应用**
   - 还没有把 physics/collision profile key 应用到 scene
   - 目前仅保留 metadata / key 级查询能力

5. **archive retention 策略**
   - 暂未实现老历史池清理

---

## 19. 本次实现的结论

本次实现已经完成以下关键闭环：

- 用 scheduler 解释训练期 sequence 决策
- 用 orchestrator 驱动 generator 生成 active pool
- 用 current/archive 维护 active pool 生命周期
- 用 assignment 将 env 绑定到 single terrain 或 active sequence template
- 用 typed query 接口让下游可以拿到真实 sequence metadata

换句话说，这次实现完成的是：

> **把 generator 生成的真实 sequence 模板池正式纳入训练数据流的第一版实现。**

这也是当前技术路线下，最小侵入、职责最清晰、且最符合既定规则的一次接线方案。
