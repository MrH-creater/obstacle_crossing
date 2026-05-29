# implementation Details of `sequence_generator.py`

## 1. 文档目的

本文档记录当前 `sequence_generator.py` 的实现细节，重点说明：

- 当前文件已经实现了什么功能
- 它依赖了哪些上游文件、类、方法和模块
- 当前保留了哪些扩展点
- 对外暴露了哪些接口
- 与当前 `obstacle_crossing` 项目整体架构的关系

目标文件：

- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/sequence_generator.py`

本次文档对应的工作日志位置：

- `G:/Projects/obstacle_crossing/worklog/2026-5-26/implementation_Details_of_sequence_generator.md`

---

## 2. 当前项目上下文

当前项目 `obstacle_crossing` 的 terrain 相关职责边界如下：

### 2.1 `terrain_registry.py`
位置：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_registry.py`

职责：
- 定义障碍地形全集
- 定义 `terrain_id / key / terrain_file / motion_file`
- 定义 `command profile / capability / physics profile / collision profile`
- 定义哪些地形属于 `single_train / sequence_train / future_benchmark`

### 2.2 `terrain_layout.py`
位置：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_layout.py`

职责：
- 定义训练时不同 role 的比例和布局
- 定义 sequence train 启动和刷新节奏
- 不负责真实 sequence 内容本身的几何拼接和 metadata 生成

### 2.3 `terrain_assignment.py`
位置：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_assignment.py`

职责：
- 将 env 绑定到 terrain 或 sequence template
- 需要消费 sequence 的：
  - terrain ids / keys
  - command profile keys
  - required capabilities
  - physics / collision profile keys
  - sequence length

### 2.4 `sequence_generator.py`
位置：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/sequence_generator.py`

职责：
- 成为真实 sequence 内容的唯一生成源
- 生成真实长地形 mesh
- 生成完整 sequence metadata
- 负责训练模板池和评估模板池的构建与导出

---

## 3. 当前 `sequence_generator.py` 已实现的功能

### 3.1 数据结构定义

当前文件定义了以下核心数据结构：

#### `SequenceAlignmentReport`
位置：
- `sequence_generator.py:27`

用途：
- 保存单段地形在标准化后的检查结果
- 包括：
  - `terrain_id`
  - `terrain_key`
  - `source_path`
  - `forward_axis`
  - `bounds_min / bounds_max`
  - `extent_xyz`
  - `segment_length_y`
  - `z_min / z_max / z_span`
  - `z_start_edge_mean / z_end_edge_mean`
  - `warnings`

#### `NormalizedSegmentGeometry`
位置：
- `sequence_generator.py:45`

用途：
- 表示经过标准化的单段地形几何
- 包含：
  - 原始 `ObstacleTerrainSpec`
  - 归一后的 `trimesh.Trimesh`
  - 输入 backend
  - 前进方向
  - 边界、长度、entry/exit 信息
  - `SequenceAlignmentReport`

#### `SequenceSegmentRecord`
位置：
- `sequence_generator.py:60`

用途：
- 表示某一段地形在 sequence 中的逻辑记录
- 包含：
  - `terrain_id / terrain_key`
  - `command_profile_key`
  - `physics_profile_key`
  - `collision_profile_key`
  - `required_capabilities`
  - `segment_length_y`
  - `start_y / end_y`

#### `SequenceTemplateRecord`
位置：
- `sequence_generator.py:73`

用途：
- 表示一整条 sequence 模板
- 包含：
  - terrain identity 信息
  - sequence 长度信息
  - segment / buffer 边界信息
  - total length
  - profile / capability 信息
  - alignment report
  - 输入输出 backend 信息
  - 导出路径
  - 当前生成出的 `sequence_mesh`

#### `SequenceTemplatePool`
位置：
- `sequence_generator.py:100`

用途：
- 表示一批 sequence 模板池
- 包含：
  - `iteration`
  - `seed`
  - `template_records`
  - `active_sequence_length_range`
  - `refresh_reason`
  - `input_backend / output_backend`

---

### 3.2 训练阶段与课程逻辑

当前文件实现了 sequence 的课程与刷新 helper：

#### `should_enable_sequence_train(...)`
位置：
- `sequence_generator.py:143`

功能：
- 根据 `ContinuousSequenceSamplingCfg.sequence_train_start_iteration` 判断当前 iteration 是否允许 sequence train 启动

#### `get_active_sequence_length_range(...)`
位置：
- `sequence_generator.py:150`

功能：
- 根据 iteration 和 `ContinuousSequenceSamplingCfg` 计算当前允许的 sequence 长度范围
- 当前规则是：
  - 阶段 1：`(2, 2)`
  - 阶段 2：`(2, 4)`
  - 阶段 3：`(2, 6)`

#### `should_refresh_training_templates(...)`
位置：
- `sequence_generator.py:159`

功能：
- 根据 `template_refresh_interval_iterations` 判断当前 iteration 是否应刷新模板池
- 当前语义：
  - 启动前不刷新
  - 在 `sequence_train_start_iteration` 当次刷新
  - 后续按固定间隔刷新

实现说明：
- 这些逻辑由 generator 自己持有
- 没有依赖 `terrain_layout.py` 的私有方法

---

### 3.3 sequence 抽样逻辑

#### `sample_sequence_specs(...)`
位置：
- `sequence_generator.py:171`

功能：
- 从候选池中为一条 sequence 抽样若干地形段

当前实现规则：
- 候选池来自 `registry.single_train_specs()`
- sequence 长度来自当前课程阶段
- 默认 `allow_duplicate_terrains=False`
- 默认无放回抽样
- 抽样结果按 `terrain_id` 升序排序

这部分内部复用的 helper：
- `_validate_candidate_pool(...)` `sequence_generator.py:693`
- `_sample_specs_from_pool(...)` `sequence_generator.py:716`
- `_sorted_specs(...)` `sequence_generator.py:740`

---

### 3.4 缓冲段采样

#### `sample_buffer_lengths(...)`
位置：
- `sequence_generator.py:191`

功能：
- 对长度为 `N` 的 sequence 生成 `N-1` 个 buffer length

当前规则：
- 每个 buffer 从 `[1.0, 3.0]` 区间内采样
- 长度为 1 的 sequence 返回空 tuple

---

### 3.5 单段几何读取与标准化

#### `load_segment_geometry(...)`
位置：
- `sequence_generator.py:209`

功能：
- 根据 `ObstacleTerrainSpec.terrain_file` 和 terrain root 加载单段几何
- 当前 V1 已实现 STL 读取

#### `inspect_segment_alignment(...)`
位置：
- `sequence_generator.py:220`

功能：
- 检查单段地形是否满足统一坐标规范
- 输出：
  - bbox
  - extent
  - segment Y 长度
  - Z 边界统计
  - warning 信息

检查内容包括：
- `z_min` 是否接近 0
- 标准化后长轴是否已对齐到 `+Y`
- 起点边带和终点边带的平均高度是否可以被提取

#### `normalize_segment_geometry(...)`
位置：
- `sequence_generator.py:263`

功能：
- 对地形段做标准化，使其前进方向统一为 `+Y`
- 当前做法：
  - 根据 XY 方向 extent 判断是否需要绕 Z 轴旋转 90°
  - 若 X 长度显著大于 Y 长度，则旋转到以 Y 为主轴

当前实现原则：
- 只做平面朝向统一
- 不主动平移 Z
- 通过 `inspect_segment_alignment(...)` 生成显式检查结果

当前内部辅助逻辑包括：
- `_should_rotate_to_positive_y(...)` `sequence_generator.py:801`
- `_bounds_as_tuples(...)` `sequence_generator.py:806`
- `_extent_from_bounds(...)` `sequence_generator.py:811`
- `_edge_height_mean(...)` `sequence_generator.py:818`

---

### 3.6 长地形拼接与 metadata 构建

#### `compose_sequence_geometry(...)`
位置：
- `sequence_generator.py:300`

功能：
- 把多个 `NormalizedSegmentGeometry` 与 buffer 拼接成一条真实 sequence
- 同步生成 `SequenceTemplateRecord`

当前实现流程：
1. 校验 spec 数量与 geometry 数量一致
2. 校验 buffer 数量等于 `N-1`
3. 通过 registry 取 canonical spec
4. 按顺序沿 `+Y` 平移各段几何
5. 在相邻段之间插入 buffer 区间
6. 用 `trimesh.util.concatenate(...)` 合并为一条长 mesh
7. 生成 metadata：
   - `segment_offsets_y`
   - `segment_lengths_y`
   - `buffer_lengths_y`
   - `segment_ranges_y`
   - `buffer_ranges_y`
   - `sequence_total_length_y`
   - profile keys
   - capabilities
   - warnings

当前 buffer 的实现语义：
- buffer 目前是 **间距与区间记录**
- 不生成独立 buffer 实体 mesh

当前 Z 检查语义：
- 比较上一段末端和下一段起点的边带平均高度
- 若偏差超过阈值，加入 warning

---

### 3.7 模板池构建

#### `build_training_template_pool(...)`
位置：
- `sequence_generator.py:419`

功能：
- 根据当前 iteration 和训练配置构建训练共享的 sequence 模板池

当前实现流程：
1. 计算 active length range
2. 若 sequence train 尚未启用，则返回空 pool
3. 使用固定 seed 构造 `random.Random`
4. 循环生成 `template_count` 条 sequence
5. 每条 sequence：
   - 抽样 specs
   - 读取并标准化单段几何
   - 采样 buffer
   - 拼接长地形
   - 生成 `SequenceTemplateRecord`
6. 汇总为 `SequenceTemplatePool`

实现细节：
- 使用 segment cache，避免同一轮模板池中重复读取同一 STL
- `refresh_reason` 区分：
  - `sequence_train_disabled`
  - `scheduled_refresh`
  - `manual_build`

#### `build_fixed_eval_template_pool(...)`
位置：
- `sequence_generator.py:496`

功能：
- 根据调用方显式给出的 sequence 列表构建固定评估模板池

#### `build_random_eval_template_pool(...)`
位置：
- `sequence_generator.py:561`

功能：
- 基于 `SequenceEvalCfg` 生成随机评估模板池
- 默认优先从 `future_benchmark_specs()` 取候选池

---

### 3.8 模板导出

#### `export_sequence_template(...)`
位置：
- `sequence_generator.py:633`

功能：
- 导出单条 sequence 模板

当前 V1 导出内容：
- `sequence_<id>.stl`
- `sequence_<id>.yaml`

导出行为：
- 从 `SequenceTemplateRecord.sequence_mesh` 导出几何
- 同时把 metadata 序列化成 YAML
- 返回带有输出路径的更新版 `SequenceTemplateRecord`

#### `export_template_pool_manifest(...)`
位置：
- `sequence_generator.py:663`

功能：
- 导出整个模板池的 manifest 文件

当前导出内容：
- `sequence_pool_manifest.yaml`

内部序列化 helper：
- `_template_to_yaml_payload(...)` `sequence_generator.py:892`
- `_pool_manifest_payload(...)` `sequence_generator.py:951`

---

## 4. 上游依赖：调用了哪些文件、类、方法和模块

## 4.1 直接 import 的上游文件与类

### 来自 `terrain_registry.py`
位置：
- `sequence_generator.py:13`

导入：
- `ObstacleTerrainRegistry`

主要使用的方法：
- `single_train_specs()`
  - 在 `sample_sequence_specs(...)` 中作为训练候选池来源
- `get(...)`
  - 在 `_canonical_specs(...)` 与 `_resolve_spec_item(...)` 中使用
- `command_profile_for_terrain(...)`
  - 在 `_canonical_specs(...)` 中显式调用，确保 profile 来源经过 registry
- `physics_profile_for_terrain(...)`
  - 在 `_canonical_specs(...)` 中显式调用
- `collision_profile_for_terrain(...)`
  - 在 `_canonical_specs(...)` 中显式调用
- `future_benchmark_specs()`
  - 在 `build_random_eval_template_pool(...)` 中作为随机评估候选池

### 来自 `terrain_specs.py`
位置：
- `sequence_generator.py:14`

导入：
- `ContinuousSequenceSamplingCfg`
- `ObstacleTerrainSpec`
- `SequenceEvalCfg`

用途：
- `ContinuousSequenceSamplingCfg`
  - 训练 sequence 的课程、刷新、长度范围配置源
- `ObstacleTerrainSpec`
  - 单段地形的事实记录
- `SequenceEvalCfg`
  - 随机评估模板池构建的配置源

---

## 4.2 间接对齐的上游模块语义

### 对齐 `terrain_assignment.py`
位置：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_assignment.py`

对齐点：
- `required_capabilities` 的合并顺序

当前 `sequence_generator.py` 中：
- `_merge_capabilities(...)` `sequence_generator.py:841`

该逻辑与 `ObstacleTileAssignmentTable._merge_capabilities(...)` 的行为对齐：
- 保持 first-seen 稳定顺序
- 去重但不打乱语义顺序

### 避免依赖 `terrain_layout.py` 私有方法
位置：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_layout.py`

说明：
- 当前 `sequence_generator.py` 没有调用 `terrain_layout.py` 的私有 helper
- 课程逻辑由自己实现，不把 sequence 抽样逻辑再塞回 layout

---

## 4.3 外部第三方与项目内基础模块依赖

### `trimesh`
使用位置：
- `sequence_generator.py:10`
- `sequence_generator.py:124`
- `sequence_generator.py:129`
- `sequence_generator.py:277`
- `sequence_generator.py:390`

用途：
- 读取 STL
- 导出 STL
- 进行旋转和平移变换
- 合并多个 mesh

对齐参考：
- `G:/Projects/obstacle_crossing/source/instinctlab/instinctlab/terrains/trimesh/mesh_terrains.py:45`
  - 使用 `trimesh.load(..., force="mesh")`

### `yaml`
使用位置：
- `sequence_generator.py:11`
- `sequence_generator.py:654`
- `sequence_generator.py:674`

用途：
- 导出 sequence metadata YAML
- 导出 sequence pool manifest YAML

对齐参考：
- `G:/Projects/obstacle_crossing/scripts/generate_obstacle_crossing_metadata.py:13`
  - 使用 `yaml.safe_dump(..., sort_keys=False, allow_unicode=True)`

### `numpy`
使用位置：
- `sequence_generator.py:9`

用途：
- 构造平移向量
- 提取顶点数组
- 计算边带高度均值
- 读取 bounds

---

## 5. 当前实现中补充和扩展出来的功能

相较于原本项目缺失的部分，`sequence_generator.py` 当前新增了以下能力：

### 5.1 将 sequence 从“逻辑想法”变成“真实模板对象”
之前已有：
- registry
- layout
- assignment

现在新增：
- `SequenceTemplateRecord`
- `SequenceTemplatePool`
- 可实际拼出来的 `sequence_mesh`
- 可导出的 sequence metadata

### 5.2 实现了训练模板池的独立构建能力
- 支持按 iteration 构建 sequence 模板池
- 支持不同长度阶段
- 支持模板刷新节奏判断

### 5.3 增加了 sequence 几何标准化与显式检查
- 统一前进方向到 `+Y`
- 增加 `z_min` 检查
- 增加 segment 边界高度检查
- warning 进入 metadata，而不是静默吞掉

### 5.4 增加了评估模板池入口
虽然还没接训练/eval runtime，但已经有：
- `build_fixed_eval_template_pool(...)`
- `build_random_eval_template_pool(...)`

这意味着未来 sequence eval 可以直接复用现有 generator，而不是重新写一套抽样逻辑。

---

## 6. 当前暴露出来的接口

文件末尾通过 `__all__` 暴露了以下公共接口：

位置：
- `sequence_generator.py:982`

### 6.1 数据结构
- `NormalizedSegmentGeometry`
- `SequenceAlignmentReport`
- `SequenceSegmentRecord`
- `SequenceTemplatePool`
- `SequenceTemplateRecord`

### 6.2 构建和导出接口
- `build_fixed_eval_template_pool`
- `build_random_eval_template_pool`
- `build_training_template_pool`
- `compose_sequence_geometry`
- `export_sequence_template`
- `export_template_pool_manifest`

### 6.3 抽样和检查接口
- `get_active_sequence_length_range`
- `inspect_segment_alignment`
- `load_segment_geometry`
- `normalize_segment_geometry`
- `sample_buffer_lengths`
- `sample_sequence_specs`
- `should_enable_sequence_train`
- `should_refresh_training_templates`

---

## 7. 当前输入/输出格式

### 7.1 当前输入
已实现：
- `STL`

入口：
- `load_segment_geometry(...)` `sequence_generator.py:209`

路径语义：
- 默认 terrain root 为仓库下 `terrains/combined`
- `ObstacleTerrainSpec.terrain_file` 使用相对路径，例如：`../centered/1.Continuous Ramp.stl`
- 解析逻辑在 `_resolve_terrain_path(...)` `sequence_generator.py:792`

### 7.2 当前输出
已实现：
- `STL + YAML`

导出接口：
- `export_sequence_template(...)` `sequence_generator.py:633`
- `export_template_pool_manifest(...)` `sequence_generator.py:663`

输出内容：
- 单条 sequence mesh：`.stl`
- 单条 sequence metadata：`.yaml`
- 模板池 manifest：`.yaml`

---

## 8. 当前保留的扩展点

### 8.1 USD backend 预留
当前文件定义了：
- `SequenceGeometryIOBackend` `sequence_generator.py:110`
- `StlSequenceGeometryBackend` `sequence_generator.py:120`
- `UsdSequenceGeometryBackend` `sequence_generator.py:133`

状态：
- `STL` 已实现
- `USD` 仍是 `NotImplementedError`

这意味着结构上已经预留未来切换到 USD 的入口，但 V1 没有真的落 USD。

### 8.2 重复 terrain 开关预留
当前接口里已经有：
- `allow_duplicate_terrains`

涉及位置：
- `sample_sequence_specs(...)` `sequence_generator.py:171`
- `build_training_template_pool(...)` `sequence_generator.py:419`
- `build_fixed_eval_template_pool(...)` `sequence_generator.py:496`
- `build_random_eval_template_pool(...)` `sequence_generator.py:561`

当前默认行为：
- 仍然默认不允许重复 terrain

### 8.3 buffer 几何可以后续扩展为实体地形
当前 buffer 只是：
- 间距
- 元数据区间

未来可以扩展：
- 在 `compose_sequence_geometry(...)` 里插入实体平地 connector mesh
- 不需要改变当前 `SequenceTemplateRecord` 的字段设计

### 8.4 更严格的 Z 检查和朝向覆盖规则
当前行为是：
- 发现问题写 warning
- 不强制自动修复

未来可扩展：
- strict mode
- orientation override table
- per-terrain normalization rules

---

## 9. 当前实现的局限与未接入部分

以下内容当前没有实现或没有接入：

### 9.1 未接入训练主循环
当前 generator 只是模块能力，尚未接入：
- train loop
- PPO / runner
- env 刷新流程

### 9.2 未接 PhysX material apply
虽然 metadata 已记录：
- `physics_profile_keys`
- `collision_profile_keys`

但当前没有：
- 真实 apply 到 PhysX material
- collider 参数更新

### 9.3 未实现 runtime assignment 消费 sequence 边界
当前已经产出：
- `segment_ranges_y`
- `sequence_total_length_y`

但 `terrain_assignment.py` 还没有直接消费这些 sequence metadata 文件。

### 9.4 未实现 sequence_eval 调度脚本
已有模板池 API，但没有：
- 单独 eval 脚本
- 自动 benchmark 调度

---

## 10. 与当前项目文件的协同关系总结

### 10.1 上游事实源
- `terrain_registry.py` 提供地形事实、profile、capability、terrain file 路径
- `terrain_specs.py` 提供 sequence 配置结构

### 10.2 本模块职责
- `sequence_generator.py` 根据 registry 和 config 产生真实 sequence 模板
- 输出 mesh 和 metadata

### 10.3 下游潜在消费者
未来可以消费本模块产物的包括：
- `terrain_assignment.py`
- command 模块
- reward 模块
- eval 模块
- physics apply 模块

当前 sequence generator 的定位可以概括为：

> 它是当前 obstacle_crossing 项目里，真实 sequence 内容、真实长地形 mesh、完整 sequence metadata 的唯一生成源。

---

## 11. 最小调用方式示意

下面是当前模块的最小使用路径：

1. 创建 registry：
   - `build_default_obstacle_crossing_registry()`
2. 创建训练 cfg：
   - `ContinuousSequenceSamplingCfg(...)`
3. 构建训练模板池：
   - `build_training_template_pool(...)`
4. 导出单条模板：
   - `export_sequence_template(...)`
5. 导出模板池 manifest：
   - `export_template_pool_manifest(...)`

对应公共入口位置：
- `build_training_template_pool` `sequence_generator.py:419`
- `export_sequence_template` `sequence_generator.py:633`
- `export_template_pool_manifest` `sequence_generator.py:663`

---

## 12. 本次实现产物总结

本次新增文件：
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/sequence_generator.py`

本次没有修改：
- `terrain_registry.py`
- `terrain_layout.py`
- `terrain_assignment.py`
- `terrain_physics.py`

当前已经具备的能力：
- 训练 sequence 模板池构建
- 训练阶段长度课程
- 单段 STL 读取
- 单段朝向标准化到 `+Y`
- Z 对齐检查和 warning 记录
- 长 sequence mesh 拼接
- 完整 metadata 生成
- STL + YAML 导出
- 固定/随机 eval 模板池的结构化入口

当前保留但未完成的能力：
- USD backend
- runtime 接线
- PhysX apply
- eval 调度
- 更复杂的邻接/能力约束

---

## 13. 参考文件

- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/sequence_generator.py`
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_registry.py`
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_specs.py`
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_assignment.py`
- `G:/Projects/obstacle_crossing/source/obstacle_crossing/obstacle_crossing/terrain/terrain_layout.py`
- `G:/Projects/obstacle_crossing/source/instinctlab/instinctlab/terrains/trimesh/mesh_terrains.py`
- `G:/Projects/obstacle_crossing/scripts/generate_obstacle_crossing_metadata.py`
- `G:/Projects/obstacle_crossing/terrains/combined/metadata.yaml`
