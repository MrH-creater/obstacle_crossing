# Assignment Requirement Analysis

## 1. 文档目的

本文档用于从总设计师视角，明确当前 obstacle_crossing 项目中 `assignment` 这一层的需求、问题来源、目标职责以及推荐设计方向。

该文档重点回答：
1. 为什么现在必须推进 assignment 升级
2. `assignment` 在当前项目中的真实职责是什么
3. 它与 `registry / layout / sequence_generator / scheduler` 的边界关系是什么
4. 为什么 assignment 不能再只停留在“layout 查询层”
5. 当前推荐的 assignment 总体设计是什么

---

## 2. 当前背景

当前 terrain 主线已经进入新的阶段：
- `terrain_registry.py` 已经成为 terrain 事实源候选
- `terrain_layout.py` 已经承担训练期 role 比例与 role 计数
- `sequence_generator.py` 已经能生成真实 sequence template（至少在 V1 能力层）
- `sequence_pool_scheduler.py` 已经能管理 active sequence pool 的启用、刷新与 current/archive 生命周期

因此当前最关键的新问题不再是：
- “能否表达 sequence”

而是：

> **这些 sequence template 生成出来以后，训练 env 到底如何使用它们？**

这个问题的答案，就落在 `assignment` 层。

---

## 3. assignment 目前为什么还不够

## 3.1 旧状态
在早期骨架阶段，`terrain_assignment.py` 更像是：
- 基于 layout 的逻辑查询视图
- 通过 terrain ids / role / tile index 表达 env 映射

这种做法在只有 single terrain 或纯逻辑 sequence 阶段是够用的。

## 3.2 当前问题
现在 generator 已经能产生：
- `SequenceTemplateRecord`
- `SequenceTemplatePool`
- `sequence_<id>.stl`
- `sequence_<id>.yaml`
- `sequence_pool_manifest.yaml`

而 assignment 如果仍然只停留在：
- `terrain_ids = (0,2,4,6)`
- `role = sequence_train`

那就意味着：
- env 没有真正绑定到某个具体 template
- command/reward 也拿不到真实的 segment metadata
- `sequence_train` 仍然停留在“逻辑 sequence”的层面

因此，当前 assignment 的升级是必须的。

---

## 4. 当前 assignment 的目标职责

## 4.1 一句话定义
当前 assignment 的正式职责是：

> **将 env 绑定到 single terrain 或 active sequence template，并提供完整的运行时查询接口。**

它要做的，不是生成 sequence，也不是决定 sequence 训练比例，而是：
- 接收训练当前有效的样本池
- 决定每个 env 当前具体使用什么样本
- 把这一绑定关系结构化保存下来
- 供 command / reward / observation / eval 查询

---

## 4.2 assignment 的两层结构

我建议将 assignment 明确理解为两层：

### 第一层：role assignment
决定：
- 哪些 env 属于 `single_train`
- 哪些 env 属于 `sequence_train`

这一步的输入来自：
- 当前 iteration
- `ContinuousSequenceSamplingCfg`
- role 比例（来自 layout 或 scheduler 的解释）
- env 总数

### 第二层：sample assignment
在 role assignment 已确定后：
- `single_train` env 去 single terrain cache 中分配样本
- `sequence_train` env 去 current active sequence pool 中分配 template

这一步决定：
- 某个 env 绑定哪个 single terrain
- 或绑定哪个 `sequence_id`

---

## 4.3 为什么要做 role assignment + sample assignment 两层拆分

因为如果把 assignment 简单写成：
- “随机挑一些 env，再随机挑一些地形”

那很容易把：
- 角色分配逻辑
- 样本分配逻辑
- 后续 metadata 查询逻辑

混在一起。

拆成两层后：

### role assignment
解决的是：
> 当前训练阶段下，single 与 sequence 各占多少 env？

### sample assignment
解决的是：
> 已经属于 single 或 sequence 的 env，具体绑定到哪个样本？

这样实现更清晰，后续调试和替换策略也更容易。

---

## 5. 为什么 assignment 必须消费 active template，而不是只看 terrain_ids

## 5.1 terrain_ids 不足以唯一确定 sequence 样本
假设两条 sequence：
- `terrain_ids = (0,2,4,6)`
- `terrain_ids = (0,2,4,6)`

但它们可能：
- buffer 长度不同
- segment_ranges 不同
- 实际几何输出路径不同
- metadata 路径不同

也就是说：

> `terrain_ids tuple` 只能说明“逻辑组成”，不能唯一说明“真实 sequence 实例”。

因此 assignment 不能只绑定到 terrain_ids，而必须绑定到：
- `sequence_id`
- 或 `SequenceTemplateRecord`

---

## 5.2 后续模块需要 template 级信息
后续这些模块都会依赖 assignment：

### `TerrainAwareVelocityCommand`
它需要知道：
- 当前 env 是 single 还是 sequence
- sequence 当前属于哪条 template
- 当前 template 对应哪些 command profile
- 将来甚至可能需要知道当前 segment ranges

### reward / termination
它们需要知道：
- 当前 sequence 总长度
- 每个 segment 的边界
- 完整通过率 / 分段通过率统计边界

### observation / debug / eval
它们需要知道：
- 当前 env 绑定的是哪个 `sequence_id`
- geometry / metadata 路径是什么
- capability / physics profile / collision profile 是什么

因此 assignment 必须消费 template。

---

## 6. assignment 应该从哪些上游读取信息

## 6.1 registry
来自 `terrain_registry.py`：
- terrain 事实定义
- capability
- physics/collision profile key
- 单地形样本语义

## 6.2 layout
来自 `terrain_layout.py`：
- single_train / sequence_train 的配额或 role counts
- 当前训练阶段下的 role 比例

## 6.3 sequence generator / active sequence pool
来自：
- `SequenceTemplatePool`
- `SequenceTemplateRecord`
- current active pool manifest

这是 sequence 样本的真实来源。

## 6.4 调度器 / 编排器
来自：
- `SequencePoolScheduler`
- `SequencePoolOrchestrator`

用于确定：
- 当前 active pool 是什么
- 当前应不应该使用 sequence pool
- 当前有哪些 template 可分配

---

## 7. 推荐的 assignment 行为模式

## 7.1 训练时 role assignment
### 推荐规则
在每次 assignment 刷新点：
- 根据当前 iteration 和课程策略
- 得到 `single_train` 与 `sequence_train` 的比例
- 对 env id 进行角色划分

### 建议方式
- 随机抽样 env ids
- 而不是固定前 N 个 env 永远做 sequence

### 原因
这样更符合训练多样性，也避免某些 env 长期绑定某一角色造成偏差。

---

## 7.2 训练时 single sample assignment
对于被标记为 `single_train` 的 env：
- 从 single terrain cache 中按策略分配具体 terrain

### 推荐规则
- 支持权重
- 支持有放回抽样
- 多个 env 可以共享同一 single terrain 样本

---

## 7.3 训练时 sequence sample assignment
对于被标记为 `sequence_train` 的 env：
- 从 `current active sequence pool` 中分配具体 template

### 推荐规则
- 绑定的是 `SequenceTemplateRecord` / `sequence_id`
- 而不是只记录 terrain_ids tuple
- 多个 env 允许共享同一 template

### 为什么可以共享
因为当前主线已经明确：
- sequence 是少量真实模板池
- 不是为每个 env 即时单独生成一条 long-track

因此“多 env 共享少量 template”是设计目标之一。

---

## 7.4 assignment 的刷新时机
### 推荐规则
assignment 不应在每个 env reset 都重采样，而应在：
- 训练初始化时
- sequence pool 刷新时
- 训练阶段发生关键切换时

进行整体刷新。

### 原因
这样可以：
- 保持训练分布的阶段稳定性
- 让 generator 的 active pool 与 assignment 同步
- 避免过快抖动

---

## 8. assignment 最低必须记录的字段

我建议 assignment 的正式记录至少包括：

### env 级记录
- `env_id`
- `assignment_kind` (`single` / `sequence`)
- `train_role` (`single_train` / `sequence_train`)
- `single_terrain_id` / `single_terrain_key`（若 single）
- `sequence_id`（若 sequence）
- `sequence_template_index`（若 sequence）
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

这意味着 assignment 不是“轻量标签器”，而是：

> **后续训练与评估模块共享的运行时样本绑定表。**

---

## 9. 为什么当前最重要的不是继续改 generator，而是完善 assignment

### generator 当前已经能做的
- 采样 sequence
- 生成真实模板
- 导出 STL + YAML
- 组织成 template pool

### assignment 当前还缺的
- 正式 env -> active template 绑定
- 与 active pool 的正式消费闭环
- 与 command / reward / eval 的直接下游对接基础

所以当前 terrain 主线的下一个重点应是：

> **从“能生成 template”推进到“训练真正能使用 template”。**

而这一步的核心就在 assignment。

---

## 10. 与其它 terrain 模块的边界关系（最终总结）

### registry
回答：
- 世界上有哪些 terrain
- 它们各自的事实是什么

### layout
回答：
- 当前训练阶段中，single 和 sequence 各占多少

### generator
回答：
- 当前 active sequence pool 中有哪些真实 template

### assignment
回答：
- 当前每个 env 用的是哪个 single terrain 或哪个 sequence template

也就是说：

> registry 定义候选集合；layout 定义配额；generator 产出真实样本；assignment 完成 env 到样本的绑定。 

---

## 11. 当前总设计师结论

当前 assignment 的正式升级方向已经明确：

> **assignment 必须从“layout 上的逻辑 terrain 查询层”升级成“消费 active sequence template 的运行时绑定层”。**

这一步一旦做好，后续：
- command
- reward
- observation
- eval script

就有了统一且可靠的 runtime 绑定入口。
