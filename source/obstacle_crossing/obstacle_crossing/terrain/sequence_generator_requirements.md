# sequence_generator.py 详细功能需求清单

## 1. 文档目的

本文档用于定义 `obstacle_crossing` 项目中 `sequence_generator.py` 的**正式实现规格**。

这份规格的目标不是讨论抽象方向，而是为其他终端提供一个可以直接落地实现的统一口径，避免在实现过程中出现：
- 模块职责重复
- layout / assignment / registry 之间语义冲突
- sequence 逻辑在多个文件中各写一套
- 输出格式和元数据口径不一致

---

## 2. 当前已锁定的总体架构

## 2.1 模块职责总览

### `terrain_registry.py`
负责：
- 定义地形全集
- 定义 terrain_id / key / terrain_file / motion_file
- 定义 command profile / capability / physics profile / collision profile
- 定义哪些地形属于 `single_train`、`sequence_train`、`future_benchmark`

### `terrain_layout.py`
负责：
- 定义训练时 `single_train` 与 `sequence_train` 的比例
- 定义 `sequence_train` 何时启用
- 定义比例爬升策略
- 定义模板刷新时机
- 定义训练时 role 计数（而不是 sequence 内容本身）

### `sequence_generator.py`
负责：
- 生成 `sequence_train` 使用的真实长地形模板池
- 生成每条 sequence 的真实长地形 mesh
- 生成每条 sequence 的完整 metadata
- 提供固定模板与随机模板的生成/导出能力

### `terrain_assignment.py`
负责：
- 将 env 绑定到 `single_terrain` 或 `sequence template`
- 基于 single terrain / sequence template 提供 env 级查询
- 查询：
  - role
  - terrain_ids
  - command profiles
  - capabilities
  - physics/collision profile keys
  - sequence length

---

## 2.2 核心原则

### 原则 1
`sequence_generator.py` 是 **真实 sequence 内容的唯一生成源**。

即：
- 不允许 `terrain_layout.py` 再自己维护 sequence 的具体 terrain 组合
- 不允许 `terrain_assignment.py` 再重新抽 sequence
- 不允许 eval 脚本再私自写另一套 sequence 采样逻辑

### 原则 2
`terrain_layout.py` 只负责：
- 比例
- role 计数
- 模板刷新时机

不再负责：
- 具体 sequence 内容采样
- sequence 长度课程实现细节
- sequence mesh 拼接

### 原则 3
`sequence_generator.py` 自己拥有 sequence 生成相关逻辑：
- sequence 长度课程
- sequence 抽样
- 缓冲段采样
- mesh 读取与标准化
- mesh 拼接
- 元数据输出

### 原则 4
sequence 训练与评估分离：
- `sequence_train` 属于训练主线
- `sequence_eval` 当前阶段不进入训练主循环
- `sequence_eval` 是独立手动 eval / play 脚本

---

## 3. 当前已锁定的 sequence_train 规则

以下规则已经确认，`sequence_generator.py` 的实现必须严格遵守。

## 3.1 候选池规则
- sequence 训练使用的候选地形池来自：`single_train_specs()`
- 当前未进入训练的 4 个困难地形（future benchmark）不进入当前 `sequence_train`

## 3.2 长度课程规则（V1 正式版）
- 阶段 1：仅长度 `2`
- 阶段 2：长度 `2~4`
- 阶段 3：长度 `2~6`
- 每阶段 `5k iterations`

## 3.3 启用与比例规则
- `sequence_train_start_iteration = 10000`
- `10k -> 30k iterations`：`sequence_train` 比例从 `0% -> 30%` 线性爬升
- 主训练仍以 `single_train` 为主

## 3.4 模板刷新规则
- 每 `1k iterations` 刷新一次 sequence 模板池
- 每次约生成 `16` 条 sequence 模板
- 训练 env 共享模板，不为每个 env 单独生成一条长地形

## 3.5 sequence 抽样规则
- 从训练池中**无放回抽样**
- 抽样后按 `terrain_id` 排序
- 当前默认 **不允许重复地形**
- 但代码必须预留一个允许重复地形的开关，例如：
  - `allow_duplicate_terrains: bool = False`

## 3.6 相邻性/能力约束规则
- V1 **不加相邻性约束**
- V1 **不加 capability 连续性约束**
- 当前允许自由组合
- 但实现时要保留 future extension 的空间

## 3.7 缓冲段规则
- 每两个相邻障碍段之间插入一个缓冲段
- 缓冲段长度从 `1m ~ 3m` 区间内随机采样
- 每个缓冲段可独立采样

## 3.8 坐标与朝向规则
- 所有输入地形段都要统一到相同坐标规范
- 当前统一前进方向：`+Y`
- 统一“起点在前、终点在后”的规范
- `Z` 坐标当前原则上不额外平移，但必须提供检查逻辑；若检查发现不一致，生成器必须能给出显式告警或报错

---

## 4. 输入/输出格式要求

## 4.1 当前优先输出格式
当前正式目标输出格式：
- **STL + YAML**

即：
- sequence 几何：`.stl`
- sequence 元数据：`.yaml`

## 4.2 必须预留的接口
虽然 V1 先用 `STL + YAML`，但生成器必须在设计上预留：
- 后续切换为 `USD + YAML`
- 或 `USD + JSON/YAML`

因此，不能把输出逻辑写死为 STL-only。

## 4.3 输入地形也必须兼容两种来源
后续源地形读取也要预留两种方案：
- `STL + YAML`
- `USD`

也就是说，sequence 生成器内部应抽象出：
- mesh/scene 读取接口
- mesh/scene 写出接口

推荐未来接口形态：
```python
class SequenceGeometryIOBackend:
    def load_segment_geometry(...):
        ...
    def export_sequence_geometry(...):
        ...
```

V1 可先落 STL backend，但结构上必须允许以后增加 USD backend。

---

## 5. sequence_generator.py 的具体职责

## 5.1 候选池与训练阶段解释
### 目标
根据：
- `ObstacleTerrainRegistry`
- `ContinuousSequenceSamplingCfg`
- 当前 iteration

确定：
- 当前 sequence_train 是否启用
- 当前允许的 sequence 长度范围
- 当前是否需要刷新模板
- 当前训练模板池大小

### 注意
这里的“sequence 长度课程逻辑”属于 generator 自己。
也就是说：
- 不允许通过调用 `terrain_layout.py` 的私有 `_current_stage_max_sequence_length()` 完成
- 如果未来需要复用，应抽到共享 helper，而不是让 generator 依赖 layout 私有逻辑

### 建议接口
```python
def get_active_sequence_length_range(
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> tuple[int, int]:
    ...
```

```python
def should_refresh_training_templates(
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
) -> bool:
    ...
```

---

## 5.2 sequence 内容抽样
### 目标
生成一条 sequence 的 terrain 组合。

### 必须遵守
- 候选池来自 `single_train_specs()`
- 无放回
- 排序
- 默认无重复
- 长度范围按当前阶段

### 建议接口
```python
def sample_sequence_specs(
    registry: ObstacleTerrainRegistry,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
    rng: random.Random,
    *,
    allow_duplicate_terrains: bool = False,
) -> tuple[ObstacleTerrainSpec, ...]:
    ...
```

---

## 5.3 缓冲段采样
### 目标
为 sequence 中每个相邻障碍对生成缓冲段长度。

### 规则
- 若 sequence 长度为 `N`
- 缓冲段数量为 `N-1`
- 每个缓冲段长度从 `[1, 3]` 米中采样

### 建议接口
```python
def sample_buffer_lengths(
    sequence_length: int,
    rng: random.Random,
    *,
    min_buffer_length: float = 1.0,
    max_buffer_length: float = 3.0,
) -> tuple[float, ...]:
    ...
```

---

## 5.4 单段地形读取与标准化
### 目标
把每个输入地形段转换成 sequence 拼接前的统一表示。

### 必须完成的工作
1. 根据 `terrain_file` 读取几何
2. 兼容当前 V1 的 STL 输入
3. 预留将来 USD 输入
4. 统一朝向到 `+Y`
5. 检查坐标系规范
6. 检查 `Z` 平面一致性
7. 记录每段几何长度与边界信息

### 建议接口
```python
def load_segment_geometry(
    spec: ObstacleTerrainSpec,
    terrain_root: Path,
    *,
    backend: str = "stl",
):
    ...
```

```python
def normalize_segment_geometry(
    geometry,
    spec: ObstacleTerrainSpec,
    *,
    forward_axis: str = "+Y",
):
    ...
```

```python
def inspect_segment_alignment(
    geometry,
    spec: ObstacleTerrainSpec,
) -> dict:
    ...
```

---

## 5.5 真实长地形拼接
### 目标
把多个已标准化的地形段 + 缓冲段拼成一条真实长地形。

### 必须完成的工作
1. 按已排序 sequence 顺序拼接
2. 在相邻段之间插入缓冲段
3. 保证统一前进方向
4. 记录每段在整条 sequence 中的起止范围
5. 记录每个缓冲段范围
6. 计算整条 sequence 的总长度

### 注意
当前假设 `Z` 不额外重对齐，但必须：
- 输出检查结果
- 若超阈值不一致，可报 warning 或 raise exception

### 建议接口
```python
def compose_sequence_geometry(
    specs: tuple[ObstacleTerrainSpec, ...],
    segment_geometries: tuple,
    buffer_lengths: tuple[float, ...],
    *,
    output_backend: str = "stl",
):
    ...
```

---

## 5.6 元数据生成
### 目标
为每条 sequence 生成完整 metadata，以供：
- assignment
- reward
- command
- eval script
- future physics apply
使用。

### 必需元数据字段
每条 sequence 至少要能表达：

```python
sequence_id: str
terrain_ids: tuple[int, ...]
terrain_keys: tuple[str, ...]
sequence_length: int
segment_offsets_y: tuple[float, ...]
segment_lengths_y: tuple[float, ...]
buffer_lengths_y: tuple[float, ...]
segment_ranges_y: tuple[tuple[float, float], ...]
sequence_total_length_y: float
command_profile_keys: tuple[str, ...]
required_capabilities: tuple[str, ...]
physics_profile_keys: tuple[str, ...]
collision_profile_keys: tuple[str, ...]
input_format: str
output_format: str
forward_axis: str
```

### 为什么必须这么完整
因为后续：
- `terrain_assignment.py` 不能自己推断 segment 边界
- `TerrainAwareVelocityCommand` 不能自己猜当前该用哪个 command profile
- physics apply 不能自己猜 sequence 里每段用哪个 profile

---

## 5.7 模板池构建
### 目标
按当前 iteration 生成一批训练可共享的 sequence 模板池。

### 规则
- 每次刷新约 `16` 条
- 训练 env 共享模板池
- 模板池内每条模板都必须有独立的：
  - 几何
  - metadata

### 建议接口
```python
def build_training_template_pool(
    registry: ObstacleTerrainRegistry,
    iteration: int,
    sampling_cfg: ContinuousSequenceSamplingCfg,
    *,
    template_count: int = 16,
    seed: int = 0,
    input_backend: str = "stl",
    output_backend: str = "stl",
):
    ...
```

---

## 5.8 固定与随机评估模板支持
虽然 `sequence_eval` 当前不在训练主循环里，但生成器从一开始就必须支持：

### 固定 benchmark 模板池
- 用于手动评估中的固定 benchmark 集

### 随机 benchmark 模板池
- 用于手动评估中的随机 benchmark 集

### 建议接口
```python
def build_fixed_eval_template_pool(...):
    ...
```

```python
def build_random_eval_template_pool(...):
    ...
```

---

## 5.9 模板导出
### 目标
将 sequence 模板持久化落盘，便于：
- 手动评估脚本
- benchmark 重复使用
- 录像与对比实验

### 当前 V1 推荐导出
- `sequence_<id>.stl`
- `sequence_<id>.yaml`
- `sequence_pool_manifest.yaml`

### 必须预留
- 导出到 `USD`

### 建议接口
```python
def export_sequence_template(
    template,
    output_dir: Path,
    *,
    geometry_backend: str = "stl",
    metadata_backend: str = "yaml",
):
    ...
```

```python
def export_template_pool_manifest(
    pool,
    output_dir: Path,
    *,
    metadata_backend: str = "yaml",
):
    ...
```

---

## 6. 与现有模块的协同关系

## 6.1 与 `terrain_registry.py`
### sequence_generator.py 必须调用
- `single_train_specs()`
- `get(...)`
- `command_profile_for_terrain(...)`
- `physics_profile_for_terrain(...)`
- `collision_profile_for_terrain(...)`

### 不允许
- 自己维护另一份训练池
- 手工写死 6 地形路径
- 绕过 registry 直接猜 profile

---

## 6.2 与 `terrain_layout.py`
### 新职责边界
`terrain_layout.py` 现在只保留：
- `single_train` / `sequence_train` 的比例
- 当前 role 计数
- 模板刷新时机

`sequence_generator.py` 负责：
- sequence 长度课程
- sequence 内容采样
- 模板池生成

### 要求
- generator 不能依赖 layout 私有方法
- 若需共享训练阶段逻辑，应提取成公共 helper
- layout 与 generator 的课程参数必须来自同一个 config 源

---

## 6.3 与 `terrain_assignment.py`
### 协同方向
`terrain_assignment.py` 应该消费 sequence generator 的输出，而不是自己重新构造 sequence 内容。

### generator 必须为 assignment 提供
- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `command_profile_keys`
- `required_capabilities`
- `physics_profile_keys`
- `collision_profile_keys`
- `segment_ranges_y`
- `sequence_total_length_y`

### assignment 之后负责
- env 绑定到 single terrain 或 sequence template
- env 查询

---

## 6.4 与 `terrain_physics.py`
### generator 需要做的事
- 记录 sequence 中每段对应的：
  - `physics_profile_key`
  - `collision_profile_key`

### generator 不需要做的事
- 不直接应用 PhysX material
- 不直接改 collider

这些应由未来：
- `mdp/events.py`
- `apply_terrain_physics_profiles(...)`

处理。

---

## 7. 数据结构建议

建议 `sequence_generator.py` 内至少定义：

### `SequenceSegmentRecord`
表示单个地形段在 sequence 中的信息。

建议字段：
- `terrain_id`
- `terrain_key`
- `command_profile_key`
- `physics_profile_key`
- `collision_profile_key`
- `required_capabilities`
- `segment_length_y`
- `start_y`
- `end_y`

### `SequenceTemplateRecord`
表示一整条 sequence 模板。

建议字段：
- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `command_profile_keys`
- `physics_profile_keys`
- `collision_profile_keys`
- `required_capabilities`
- `buffer_lengths_y`
- `segment_records`
- `total_length_y`
- `geometry_output_path`
- `metadata_output_path`
- `input_backend`
- `output_backend`

### `SequenceTemplatePool`
表示一批 sequence 模板池。

建议字段：
- `iteration`
- `seed`
- `template_records`
- `active_sequence_length_range`
- `refresh_reason`

---

## 8. 文件与输出目录建议

## 8.1 代码文件
建议新增：
- `terrain/sequence_generator.py`

如后续复杂度增加，再考虑拆分为：
- `terrain/sequence_types.py`
- `terrain/sequence_io.py`

但 V1 先不建议拆太散。

## 8.2 输出目录建议
推荐输出到：
- `terrains/generated_sequences/train/`
- `terrains/generated_sequences/eval_fixed/`
- `terrains/generated_sequences/eval_random/`

这样与训练/评估语义对应清晰。

---

## 9. V1 必须实现 / 可以后置

## 9.1 V1 必须实现
- 训练侧动态模板池生成
- 候选池来自 `single_train_specs()`
- 2 / 2~4 / 2~6 长度课程
- 无放回、排序、无重复
- 插入 `1~3m` 缓冲段
- 统一到 `+Y`
- 输出 STL + YAML
- 预留 USD 输入/输出 backend 接口
- 完整 metadata 输出

## 9.2 V1 可以后置
- 允许重复地形的真实实现（先留参数）
- capability 邻接约束
- physics/collision profile 真正 apply 到 scene
- 自动 sequence_eval 调度
- 与真实 `terrain_levels / terrain_types` 的最终 runtime 同步

---

## 10. 验收标准

实现完成后，至少需要验证：
1. 当前训练池为 6 地形时，生成的 sequence 只从这 6 个地形采样
2. sequence 长度随 iteration 按课程阶段变化
3. sequence 内 terrain_id 严格升序
4. 默认无重复地形
5. 缓冲段长度始终在 `1~3m`
6. 统一前进方向结果正确，且 `+Y` 校验通过
7. `Z` 检查逻辑可运行，并能输出显式结果
8. 输出 metadata 中的 segment_ranges 与几何长度一致
9. 输出的 capability / physics / collision 信息与 registry 一致
10. 输出 backend 当前能稳定生成 STL + YAML，并且代码结构允许后续切换到 USD

---

## 11. 当前总设计师结论

`sequence_generator.py` 是 obstacle_crossing V1 中把：
- `terrain_registry.py`（地形事实源）
- `terrain_layout.py`（训练比例与 role 计数）
- `terrain_assignment.py`（env 绑定）
- `terrain_physics.py`（profile 接口）

连接起来的关键模块。

它必须成为：
> **真实 sequence 内容、真实长地形 mesh、完整 sequence metadata 的唯一生成源。**

否则：
- `sequence_train` 会停留在逻辑层
- `terrain_assignment.py` 会失去真实 segment 边界来源
- 后续 command / reward / eval 的实现都会分叉并返工
