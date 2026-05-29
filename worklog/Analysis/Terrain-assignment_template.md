# assignment 与 template 分析

## 1. 文档目的

本文档用于明确 `obstacle_crossing` 项目中：
- `template` 是什么
- `assignment` 是什么
- 两者的区别与协同关系
- 为什么当前项目必须继续推进“assignment 消费 template”这条主线

该文档面向：
- 项目总设计师决策
- 其他终端实现端理解模块边界
- 后续需求追踪和术语统一

---

## 2. 什么是 template

在当前项目中，`template` 指的是：

> **一条已经生成好的、可被训练或评估复用的真实 sequence 长地形样板。**

这里的“样板”不是抽象的 terrain id 组合，而是一个真实的、可落地的 sequence 实例。

也就是说，一个 template 不只是：
- 逻辑上包含哪些 terrain

而是还要包含：
- 真正拼接好的长地形几何
- 完整 metadata
- 各段边界信息
- command / capability / physics / collision 的语义串联

---

## 3. template 具体包含什么

一条 sequence template 至少由两部分构成：

### 3.1 几何本体
例如：
- `sequence_000-002-004-006__0003.stl`

它表示：
- 一条真实长地形
- 包含多个按规则拼接好的障碍段
- 中间包含缓冲段

### 3.2 配套 metadata
例如：
- `sequence_000-002-004-006__0003.yaml`

metadata 至少需要记录：
- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `sequence_length`
- `segment_offsets_y`
- `segment_lengths_y`
- `buffer_lengths_y`
- `segment_ranges_y`
- `sequence_total_length_y`
- `command_profile_keys`
- `required_capabilities`
- `physics_profile_keys`
- `collision_profile_keys`

因此，`template` 的本质不是单一 STL 文件，而是：

> **一个“真实 sequence 内容 + 对应元数据”的组合体。**

---

## 4. 什么是 assignment

在当前项目中，`assignment` 指的是：

> **把每一个 env 绑定到某个具体的 single terrain 或某条具体的 sequence template 上的运行时映射层。**

它解决的问题不是“长地形长什么样”，而是：

- env 0 当前对应哪个地形？
- env 37 当前对应哪条 sequence？
- env 37 当前的 role 是什么？
- env 37 当前 sequence 包含哪些 terrain？
- env 37 当前 sequence 的长度是多少？
- env 37 当前有哪些 capability / physics profile / collision profile？

也就是说：

> template 定义“内容本身”，assignment 定义“谁用这个内容”。

---

## 5. assignment 具体包含什么

当前语义下，assignment 至少需要能提供：

### 5.1 env -> role
例如：
- `single_train`
- `sequence_train`
- `sequence_eval`
- `holdout_eval`

### 5.2 env -> terrain / sequence 绑定
对于 single terrain：
- env 0 -> `continuous_ramp`

对于 sequence：
- env 42 -> `sequence_000-002-004-006__0003`

### 5.3 env -> metadata 查询
例如返回：
- terrain ids
- terrain keys
- command profile keys
- required capabilities
- physics profile keys
- collision profile keys
- sequence length
- 当前所属 tile / template

所以 assignment 更准确地说是：

> **env 与真实 terrain/template 之间的查询接口层。**

---

## 6. template 和 assignment 的区别

### template 关注的问题
> 这条 sequence 本身是什么？

它负责回答：
- sequence 由哪些地形组成
- 顺序是什么
- 几何长什么样
- 每段边界在哪里
- buffer 在哪里
- profile/capability 是什么

### assignment 关注的问题
> 哪个 env 当前使用哪个 terrain 或 sequence？

它负责回答：
- env 绑定的是 single 还是 sequence
- env 对应哪条 sequence template
- env 当前可查询到哪些 metadata

---

## 7. 用一个直观比喻理解两者

可以把这两个概念理解成：

### template = 试卷
一张试卷里有什么题、题目顺序是什么，已经确定好了。

在当前项目里就是：
- 一条 sequence 里包含哪些 terrain
- 它们怎么拼接
- metadata 是什么

### assignment = 发卷系统
决定哪个学生拿哪一张试卷。

在当前项目里就是：
- 哪个 env 拿到哪条 sequence
- 哪个 env 当前属于 single_train 还是 sequence_train

---

## 8. 当前项目中两者分别落在哪些模块上

### 8.1 template
当前主要由：
- `sequence_generator.py`

负责生成。

当前核心数据结构为：
- `SequenceTemplateRecord`
- `SequenceTemplatePool`

它已经开始承担：
- sequence 抽样
- 长地形拼接
- 元数据生成
- STL + YAML 导出

### 8.2 assignment
当前主要由：
- `terrain_assignment.py`

负责。

当前核心数据结构为：
- `ObstacleTileAssignmentTable`
- `EnvTerrainAssignmentView`

它目前已经能表达：
- env -> role
- env -> terrain ids / keys
- env -> capability / profile

但还没有形成对真实 sequence template 的完整消费闭环。

---

## 9. 什么叫“assignment 消费 template”

这是当前项目主线中一个关键概念。

“assignment 消费 template”的意思是：

### 当前状态
assignment 更多还是在使用：
- role
- terrain_ids
- logical layout 结果

来做查询。

也就是说，虽然 generator 已经能产生真实 sequence 模板，assignment 还没有完全把这些模板作为自己的直接数据源。

### 目标状态
assignment 不再只知道：
- env 42 对应 terrain_ids = `(0,2,4,6)`

而是要知道：
- env 42 对应的是 **哪一条真实 sequence template**
- 这条 template 的 `sequence_id` 是什么
- 它的 STL 文件是什么
- 它的 metadata 文件是什么
- 它的 segment 边界在哪里
- 它对应哪些 capability / profile

也就是说：

> assignment 要从“抽象 sequence 组合的查询层”，升级为“绑定真实 template 实例的查询层”。

---

## 10. 为什么当前必须推进“assignment 消费 template”

这是目前 terrain 主线中最重要的原因说明。

### 10.1 否则 generator 只是生成了孤立产物
如果 generator 只是把：
- `sequence_xxx.stl`
- `sequence_xxx.yaml`

生成出来，但 assignment 不真正绑定它们，那么这些模板就只是“文件系统里的结果”，并没有进入训练和评估主线。

也就是说：
- generator 有了
- 但 env 还没真正“用上” generator 产物

### 10.2 command / reward / observation 无法获得真实 sequence 信息
后续这些模块都需要知道：
- 当前 env 对应哪条 sequence
- 当前 sequence 的 command profile 是什么
- 当前有哪些 capability
- 每段边界在哪里

如果 assignment 仍然只停留在：
- `terrain_ids = (0,2,4,6)`

那它们就拿不到：
- 真实 template 的 geometry / metadata
- segment_ranges
- 统一的 profile/capability 串联信息

### 10.3 sequence_train 的“真实长地形”目标就无法闭环
你已经明确：
- `sequence_train` 必须是真实长地形
- 不是仅逻辑 sequence

如果 assignment 不消费 template，那么训练主线仍然停留在“逻辑上有 sequence”的阶段，而没有真正闭环到：
- env 绑定真实 sequence
- scene 加载真实 sequence

### 10.4 独立 sequence_eval 也需要真实 template 实例
未来独立的 eval/play 脚本同样需要：
- 固定 benchmark template
- 随机 benchmark template

这些脚本如果不能复用 assignment 对 template 的绑定方式，就又会出现另一套平行逻辑，导致：
- 训练使用一套 template 管理逻辑
- 评估使用另一套 template 管理逻辑

这正是当前主线要避免的事情。

---

## 11. 当前项目中的正确协同关系

根据当前已确认的架构，正确关系应为：

### `terrain_registry.py`
负责：
- 定义有哪些地形
- 定义 capability / profile / file path 等事实

### `terrain_layout.py`
负责：
- 定义 `single_train` 与 `sequence_train` 的比例
- 定义 role 计数
- 定义刷新时机

### `sequence_generator.py`
负责：
- 根据 registry 和训练阶段，生成真实 sequence template
- 输出 mesh 和 metadata

### `terrain_assignment.py`
负责：
- 将 env 绑定到 single terrain 或 sequence template
- 提供运行时查询

也就是说，理想主线是：

> registry 提供事实源 → layout 提供配额与时机 → generator 产生真实模板 → assignment 绑定 env 到模板。

---

## 12. 当前的总设计师判断

### 当前可以认为：
- `template` 这条线已经通过 `sequence_generator.py` 初步建立完成
- `assignment` 这条线还停留在“逻辑映射层”，尚未完全升级为“template 消费层”

### 因此后续 terrain 主线重点应转向：
1. 让 assignment 绑定真实 template
2. 让训练场景能加载这些 template
3. 让 command / reward / eval 复用 assignment 查询结果

---

## 13. 一句话总结

### template 是什么？
> 一条已经生成好的真实 sequence 长地形样板（mesh + metadata）。

### assignment 是什么？
> 把某个 env 绑定到某个 single terrain 或某条 sequence template 的运行时映射层。

### 为什么要推进 assignment 消费 template？
> 因为只有这样，sequence_generator 生成的真实长地形模板才能真正进入训练与评估闭环，而不是只停留在文件层产物。
