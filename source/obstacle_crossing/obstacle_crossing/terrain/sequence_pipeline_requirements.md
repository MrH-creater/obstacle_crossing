# sequence pipeline 详细实现需求文档

## 1. 文档目的

本文档用于定义当前 obstacle_crossing 项目中：
- `sequence_generator.py`
- `terrain_assignment.py`
- 新增的调度器 / 编排器（scheduler / orchestrator）

三者在当前技术路线下的**统一实现方案**。

该文档的目标是：
1. 承认并利用当前 `sequence_generator.py` 已有实现成果，而不是重新推翻重写
2. 在当前技术路线下重新定义 generator / assignment / 调度器 的协同关系
3. 为其他终端提供一份可直接执行的实现规范
4. 避免后续出现“generator 一套逻辑、assignment 一套逻辑、训练入口又一套逻辑”的分叉

---

## 2. 当前技术路线（已锁定）

## 2.1 训练主线
- 训练由：
  - `single_train`
  - `sequence_train`
 组成
- `sequence_train` 必须是真实长地形，而不是仅逻辑 sequence
- 主训练仍以 `single_train` 为主，`sequence_train` 作为连续能力注入路径

## 2.2 sequence_train 课程策略
- `sequence_train_start_iteration = 10000`
- `10k -> 30k`：`0% -> 30%`
- 长度课程：
  - 阶段 1：长度 `2`
  - 阶段 2：长度 `2~4`
  - 阶段 3：长度 `2~6`
  - 每阶段 `5k iteration`
- 每 `1k iteration` 刷新模板池
- 每次约 `16` 条训练模板
- 候选池来自 `single_train_specs()`
- 无放回采样
- 按 `terrain_id` 排序
- 默认不允许重复地形，但保留开关
- V1 不加相邻性/能力连续性约束
- 段间 buffer 长度从 `1m~3m` 随机采样
- 统一前进方向为 `+Y`
- `Z` 默认不重对齐，但必须检查

## 2.3 sequence_eval 策略
- 不进入训练主循环
- 不参与参数更新
- 先作为**独立手动 eval/play 脚本**
- 当前阶段不要求自动 periodic eval pipeline

## 2.4 工程实现方向
- single terrain 由用户维护，作为稳定的单地形缓存库
- long sequence 由 generator 自动生成，不由用户手工预先制作大量组合
- sequence 以**模板池**形式存在，不是每个 env 即时拼接独立长地形
- 训练时按比例混用：
  - single terrain 缓存库
  - sequence 模板缓存库
- sequence 缓存库按训练刷新节奏更新

---

## 3. 模块职责总览（正式定义）

## 3.1 `terrain_registry.py`
职责：
- 定义所有 terrain 的事实信息
- 定义 train / future benchmark pool 边界
- 定义 capability / command / physics / collision profile
- 作为地形事实的唯一来源

**不负责**：
- sequence 采样
- 长地形拼接
- env 分配
- 模板刷新

---

## 3.2 `terrain_layout.py`
职责：
- 只负责训练期 role 配额与 role 计数
- 只负责：
  - `single_train` 比例
  - `sequence_train` 比例
  - 当前是否启用 sequence_train
  - 当前 small-layout 下的保底策略
- 输出训练时的 role counts / role allocation 结果

**不负责**：
- sequence 具体 terrain 抽样
- sequence 长地形几何拼接
- sequence metadata 生成
- env 到 template 的最终绑定

### 当前要求
后续如需进一步精简，应逐步把 generator 相关的“具体 sequence 内容逻辑”从 layout 中退出，layout 只保留：
- role 比例
- role 计数
- 训练配额

---

## 3.3 `sequence_generator.py`
职责：
- 成为真实 sequence 内容的唯一生成源
- 根据训练阶段和 generator 请求，生成 sequence 模板池
- 负责：
  - sequence 内容采样
  - 单段读取与标准化
  - 长地形拼接
  - STL + YAML 导出
  - metadata 导出
- 支持：
  - train 模板池
  - fixed eval 模板池
  - random eval 模板池

**不负责**：
- 决定当前训练比例
- 决定当前哪些 env 是 single / sequence
- 决定 env 绑定哪条模板
- 真正把 physics/collision profile apply 到 scene

---

## 3.4 `terrain_assignment.py`
职责：
- 将 env 绑定到：
  - single terrain
  - 或 sequence template
- 提供统一运行时查询：
  - env -> role
  - env -> terrain ids / keys
  - env -> command profiles
  - env -> capabilities
  - env -> physics/collision profile keys
  - env -> sequence length
  - env -> 当前绑定的 template id
  - env -> segment 边界

### 当前要求
`terrain_assignment.py` 后续必须从“逻辑 layout 查询层”升级成“真实 template 消费层”。

也就是说，后续 assignment 的输入不能只来自：
- role
- terrain_ids
- layout

而必须来自：
- `SequenceTemplatePool`
- `SequenceTemplateRecord`
- active pool manifest

---

## 3.5 新增：调度器 / 编排器
建议新增：
- `sequence_pool_scheduler.py`

它负责：
- 解释 iteration -> 当前训练决策
- 判断是否应刷新 sequence pool
- 调用 generator 生成 active pool
- 管理 current / archive 模板池
- 把 active pool 暴露给 assignment 和训练场景

它是当前技术路线中缺失的关键控制层。

---

## 4. 为什么需要调度器 / 编排器

当前 generator 已经具备生成模板池的能力，但仍缺：
- 什么时候生成
- 当前阶段该生成多少条
- 生成到哪个目录
- 是否切换 current active pool
- assignment 和训练侧该读哪一版模板池

如果没有调度器，当前系统会出现：
- generator 能产出东西，但训练侧不知道什么时候用
- assignment 不知道应该绑定哪一批 active template
- 训练刷新节奏无法统一控制

因此，调度器存在的目的就是：

> **把“训练阶段策略”翻译成“sequence 缓存池生命周期管理”**

---

## 5. 调度器 / 编排器的职责定义

建议拆成两层：

## 5.1 轻量决策层：`SequencePoolDecision`
作用：
- 纯逻辑解释当前 iteration 下的 sequence 决策

建议字段：
```python
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

## 5.2 轻量决策器：`SequencePoolScheduler`
作用：
- 根据 iteration 和 `ContinuousSequenceSamplingCfg` 计算当前决策

建议接口：
```python
class SequencePoolScheduler:
    def build_decision(
        self,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
    ) -> SequencePoolDecision:
        ...
```

它负责：
- sequence 是否启用
- 当前比例是多少
- 当前 active length range 是什么
- 当前是不是要刷新
- 当前需要多少模板

## 5.3 执行层：`SequencePoolOrchestrator`
作用：
- 调 generator 生成模板池
- 维护 current / archive
- 提供 active pool 给 assignment / training scene

建议接口：
```python
class SequencePoolOrchestrator:
    def ensure_active_training_pool(
        self,
        registry: ObstacleTerrainRegistry,
        iteration: int,
        sampling_cfg: ContinuousSequenceSamplingCfg,
        *,
        seed: int,
    ) -> SequenceTemplatePool:
        ...
```

```python
def current_pool_manifest_path(self) -> Path:
    ...
```

```python
def current_template_records(self) -> list[SequenceTemplateRecord]:
    ...
```

---

## 6. 当前已存在的 `sequence_generator.py` 应如何处理

## 6.1 结论
**不要推倒重写。**

当前 generator 已经具备：
- 数据结构
- 课程逻辑
- STL 读取
- 统一朝向到 `+Y`
- 长地形拼接
- STL + YAML 导出
- 固定/随机 eval 模板池入口

这是当前技术路线下完全可用的基础实现。

## 6.2 在当前技术路线下它的定位
它应当继续作为：

> **sequence 模板内容、真实长地形 mesh、完整 metadata 的唯一生成源**

也就是说：
- 训练侧 sequence cache 仍由它生成
- 调度器调用它
- assignment 消费它的输出

## 6.3 后续对 generator 的改动原则
可以增强，但不宜返工重写。当前阶段建议：
- 保留现有抽样、拼接、导出逻辑
- 在调度器/assignment 接线中复用现有 API
- 后续再按需要增强：
  - buffer 实体 mesh
  - strict Z mode
  - orientation override
  - USD backend

---

## 7. 对 `terrain_assignment.py` 的正式要求

## 7.1 当前状态
当前 `terrain_assignment.py` 还主要基于：
- layout
- terrain_ids
- round-robin env->tile 绑定

它还没有真正消费 generator 产出的 template metadata。

## 7.2 目标状态
后续 assignment 需要升级成：

### single env
绑定到：
- single terrain record

### sequence env
绑定到：
- `SequenceTemplateRecord`

也就是说，assignment 必须能够回答：
- env 42 当前绑定的是哪条 `sequence_id`
- 这条 sequence 的 terrain_ids 是什么
- segment_ranges_y 是什么
- 当前 capability / physics / collision profile 是什么

## 7.3 建议新增/调整的查询能力
建议最终支持：
- `template_ids_for_envs(...)`
- `segment_ranges_for_envs(...)`
- `template_records_for_envs(...)`
- `current_pool_id(...)`

当前 assignment 里的：
- `roles_for_envs(...)`
- `terrain_ids_for_envs(...)`
- `command_profiles_for_envs(...)`
- `capabilities_for_envs(...)`
- `physics_profile_keys_for_envs(...)`
- `collision_profile_keys_for_envs(...)`

都应逐步改成建立在真实 template / active pool 基础上，而不是仅 layout 逻辑上。

---

## 8. 训练时 sequence cache 的工作流（正式方案）

## 8.1 两个缓存库
### A. single terrain cache
由用户维护：
- centered STL
- registry
- metadata

### B. sequence cache
由 generator 自动生成：
- 少量 sequence 模板
- mesh + metadata
- current / archive 管理

## 8.2 sequence cache 推荐目录结构
```text
terrains/
  generated_sequences/
    train/
      current/
        sequence_pool_manifest.yaml
        sequence_*.stl
        sequence_*.yaml
      archive/
        iter_010000/
        iter_011000/
        ...
    eval_fixed/
    eval_random/
```

## 8.3 工作流
1. 训练推进到某 iteration
2. `SequencePoolScheduler` 决定：
   - 是否启用 sequence_train
   - 当前比例是多少
   - 当前长度课程是什么
   - 是否应刷新
3. `SequencePoolOrchestrator` 若需要刷新，则调用 `sequence_generator.py`
4. generator 生成 `16` 条左右训练模板，输出到 `current/`，并归档旧版本
5. assignment / training scene 只读取当前 `current/sequence_pool_manifest.yaml`
6. `sequence_train` env 从当前 active pool 取样本；`single_train` env 从 single terrain cache 取样本

---

## 9. 输出格式与输入格式要求

## 9.1 当前优先
- 输出：`STL + YAML`
- 输入：优先 `STL`

## 9.2 必须预留
- 输出：`USD`
- 输入：`USD`

### 要求
不要把 IO backend 写死为 STL-only。应保留 backend 抽象层，允许未来切换：
- `stl`
- `usd`

---

## 10. 当前阶段推荐的实现顺序

### Step 1
实现：
- `sequence_pool_scheduler.py`
- `SequencePoolDecision`
- `SequencePoolScheduler`
- `SequencePoolOrchestrator`
- current/archive 目录切换
- active manifest 管理

### Step 2
让 `terrain_assignment.py` 从：
- 逻辑 layout / terrain_ids

升级到：
- 真实 template / active pool

### Step 3
让训练场景/训练入口能够加载 current active sequence pool

### Step 4
让 command / reward / observation 开始消费 sequence metadata

### Step 5
实现独立手动 `sequence_eval` 脚本

---

## 11. 当前不建议立刻做的事

- 不建议重写 `sequence_generator.py`
- 不建议现在把 periodic eval 自动化做满
- 不建议现在做每个 env 即时拼接长地形
- 不建议现在把 buffer 立即升级成实体 connector mesh
- 不建议现在为 capability 邻接约束引入复杂采样器

---

## 12. 最终总设计结论

当前 obstacle_crossing 的正式技术路线应为：

> **single terrain 作为稳定基础样本库；sequence_generator 作为外部模板生成器，按训练阶段动态生成少量真实长地形模板池；SequencePoolScheduler/Orchestrator 管理模板池刷新与 active pool 切换；terrain_assignment 将 env 绑定到 single terrain 或当前 active sequence template；sequence_eval 独立手动脚本运行，不进入训练主循环。**

该路线相比“训练中实时逐 env 拼接地形”更符合：
- 模块独立性
- 可维护性
- 可调试性
- 可复现性
- 后续加入 4 个困难地形时的可扩展性
