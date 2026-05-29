# Detailed Rules for Demand Modification

## 1. 文档目的

本文档用于正式记录 2026-5-27 当前 obstacle_crossing 项目在 terrain / sequence / eval 主线上的需求修订细则。

该文档的作用是：
- 将今天讨论得到的技术路线正式固化
- 给其他终端提供统一可执行的修改口径
- 为后续需求追踪、代码修改与 review 提供基准

本文件重点解决：
1. sequence 几何构造方式的修订
2. sequence_eval 的定位与执行方式修订
3. registry / generator / scheduler / assignment 的协同修订
4. 当前已识别问题项的推荐解决方案

---

## 2. 当前正式技术路线（修订后）

## 2.1 训练角色
当前训练主循环中只保留两个角色：
- `single_train`
- `sequence_train`

### 解释
- `single_train`：使用单地形样本
- `sequence_train`：使用真实长地形 sequence 模板

### 不再作为训练角色保留的内容
- `sequence_eval` 不再作为训练主循环内 role 使用
- `holdout_eval` 不再作为当前训练链路中的活跃 role

---

## 2.2 评估方式（修订后正式方案）
`sequence_eval` 当前阶段采用：

> **独立手动 eval / play 脚本**

### 明确规定
- 不进入训练主循环
- 不参与参数更新
- 不作为训练 env role
- 在关键训练阶段手动运行
- 后续若确有需要，再升级为自动 periodic eval

### 推荐评估命名
后续建议统一使用：
- `manual_sequence_eval`
- `fixed_sequence_benchmark`
- `random_sequence_benchmark`

避免继续在训练 role 层混用：
- `sequence_eval`
- `holdout_eval`

---

## 3. sequence 几何构造方式正式修订

## 3.1 原先 V1 中的不理想点
当前第一版 generator 存在的问题是：
- 相邻障碍段之间只有 buffer 区间记录
- 但 buffer 区间内没有真实可走几何
- 从结果上看，sequence 更像“多个障碍 mesh 被错开摆放，中间留空隙”
- 这不满足“真实可走的连续长地形”的目标

因此，需要对 sequence 的几何构造方式进行正式修订。

---

## 3.2 修订后的正式方案
sequence 不再通过“只拼接障碍段本体”来形成长地形，而改为：

> **使用一整块连续基础地板作为承载面，再将多个 single 地形障碍段按 sequence 顺序排布在地板上。**

### 这意味着
1. sequence 的整体物理支撑面由一个连续地板提供
2. buffer 不再承担“补齐几何连续性”的责任
3. buffer 仅表示相邻障碍段在连续地板上的间隔距离
4. sequence 中所有地形段都坐落在同一块基础地板上

---

## 3.3 sequence 基础地板的正式参数
### 已锁定参数
- **宽度（X 方向）**：固定为 `3m`
- **厚度（Z 方向）**：固定为 `20cm`（`0.20m`）

### 长度（Y 方向）定义
若一条 sequence 中：
- 第一个 single 地形的起点位置记为 sequence 内起始障碍起点
- 最后一个 single 地形的终点位置记为 sequence 内终止障碍终点
- 这二者之间沿 `+Y` 的距离为 `Y`

则基础地板总长度定义为：

```text
1m + Y + 1m
```

其中：
- 前 `1m`：起始区域（初始化/开始区域）
- 后 `1m`：结束区域（终止/通过完成区域）
- 中间部分：承载全部障碍段与 buffer 间隔

---

## 3.4 缓冲段在新方案中的意义
### 修订后的定义
buffer 不再表示：
- “一个需要额外补几何的断开区间”

而是表示：
- **相邻两个障碍段在连续基础地板上的 Y 向间隔距离**

### 当前正式规则仍保持不变
- 每个 buffer 长度在 `1m ~ 3m` 之间随机采样
- 每个 buffer 可独立采样

---

## 3.5 Z 方向处理的正式修订
### 已确认思路
由于 single 地形本身的几何尺寸和高度关系已经足够准确，且这些障碍本意上都应“摆放在地板上”，因此 sequence 生成时不再以“段末端高度和下一段起点高度是否能直接几何接平”为主要原则。

### 修订后的核心语义
- sequence 的统一参考平面由基础地板提供
- 每个 single 地形段应被放置在这块地板上
- 这样各地形段相对于地板的真实高度关系就天然保留
- 不再依赖直接 segment-to-segment 的 Z 接平

### 仍然保留的检查要求
尽管如此，生成器仍必须保留：
- `Z` 检查逻辑
- 用于发现：
  - 某个障碍没有正确坐落在地板上
  - 某个障碍悬浮或嵌入地板异常

也就是说：
> 以后 `Z` 检查应从“检查相邻段是否能直接接平”转向“检查各障碍段相对于基础地板的放置关系是否合理”。

---

## 3.6 朝向规则
### 已锁定规则
- 所有 single 地形进入 sequence 前统一到同一坐标系规范
- 当前统一前进方向为：`+Y`
- 当前统一采用“起点在前、终点在后”的规范

### 修订要求
后续生成器逻辑中，朝向校验仍然必须保留。

但应逐步从：
- 简单 bbox extent 判断是否旋转

过渡到：
- 可扩展的 per-terrain orientation override 机制

当前阶段：
- 先保留现有启发式
- 但对 `symmetrical_ramp`、`L-bend` 等已暴露 warning 的地形，应纳入后续修正清单

---

## 4. 事实源与元数据口径修订

## 4.1 registry 作为唯一事实源
正式采纳：

> **`terrain_registry.py` 作为唯一事实源。**

### registry 应成为唯一维护位置的内容
- `terrain_id`
- `terrain_key`
- `terrain_file`
- `motion_file`
- `command_profile_key`
- `required_capabilities`
- `physics_profile_key`
- `collision_profile_key`
- train / benchmark pool 归属

### 这意味着
后续：
- `metadata.yaml`
- sequence manifest
- training pool manifest

都应由 registry 逻辑派生生成，而不应继续长期并行维护另一套独立事实源。

---

## 4.2 旧 `combined/metadata.yaml` 的地位
当前旧 six-terrain metadata 还在训练配置中使用，但它与新 registry 的 terrain_id 语义不一致。

### 修订方向
- 短期：承认它仍是旧链路的输入
- 中期：必须统一到 registry 派生体系
- 长期：不允许 old metadata 与 registry 双轨长期并存

### 结论
这是当前 terrain 子系统的 **P0 级问题**，后续必须解决。

---

## 5. sequence generator 的定位修订

## 5.1 正式定位
`sequence_generator.py` 现在的正式定位是：

> **根据当前训练阶段和训练池定义，动态生成少量真实 long sequence 模板池（mesh + metadata），供 sequence_train 使用。**

### 注意
它不是：
- 手工模板库
- per-env 即时拼接器
- assignment 层
- runtime terrain 刷新调度器

---

## 5.2 当前 generator 可以继续沿用的部分
目前 generator 的以下逻辑可以继续保留：
- sequence 内容采样
- 课程阶段长度范围解释
- buffer 长度采样
- STL 读取
- STL + YAML 导出
- metadata 数据结构
- fixed/random eval template pool 基础接口

### 但必须修订的部分
1. `sequence` 真实几何构造方式
   - 从“障碍段直接拼接+空白 buffer”
   - 改成“连续基础地板 + 障碍段排布”
2. `Z` 检查逻辑
   - 从“段间接缝检查”转向“障碍与地板关系检查”
3. 后续输出 metadata 中应明确：
   - base floor 参数
   - 起始/结束区域

---

## 6. assignment 的正式职责修订

## 6.1 assignment 的角色
`terrain_assignment.py` 负责：
- 将 env 绑定到 single terrain 或 sequence template
- 提供 env 级查询接口

### 正式定义
assignment 应该回答：
- env 当前是 `single_train` 还是 `sequence_train`
- env 当前绑定的是哪个 single terrain 或哪条 `sequence template`
- 若是 sequence：
  - `sequence_id`
  - `terrain_ids`
  - `terrain_keys`
  - `segment_ranges_y`
  - `buffer_ranges_y`
  - `command_profile_keys`
  - `required_capabilities`
  - `physics_profile_keys`
  - `collision_profile_keys`

---

## 6.2 assignment 必须消费 template
这条现在正式锁定：

> **assignment 不得只消费 layout 里的抽象 terrain tuple，而必须消费 generator 生成的真实 `SequenceTemplateRecord` / `SequenceTemplatePool`。**

### 原因
因为只有消费 template，assignment 才能拿到：
- 真实 sequence_id
- segment_ranges_y
- buffer_ranges_y
- template geometry / metadata 路径
- 完整 profile / capability 信息

否则 sequence 仍停留在逻辑层。

---

## 7. 调度器 / 编排器正式职责

## 7.1 正式定位
新增：
- `sequence_pool_scheduler.py`

它负责：
- 解释 iteration -> 当前 sequence 训练决策
- 判断是否刷新 active sequence pool
- 调用 generator 构建新的训练模板池
- 管理 `current / archive` 生命周期
- 对训练侧暴露当前 active pool

也就是说：

> **generator 负责生成，scheduler/orchestrator 负责“何时生成、生成后谁来用、如何切换 active pool”。**

---

## 7.2 current / archive 的正式角色
### `current/`
表示：
- 当前训练活跃 sequence pool
- assignment 与训练场景只应读取 `current/sequence_pool_manifest.yaml`

### `archive/`
表示：
- 历史 sequence pool 快照
- 用于：
  - 回溯
  - 复现实验
  - 历史对比评估

### 修订要求
archive manifest 必须可可靠回读。
因此推荐修订方案：
- manifest 中保存相对路径，而不是绝对路径
- 读取时相对于 manifest 所在目录解析

这是当前 P0 级修复项。

---

## 8. sequence_train 与 sequence_eval 的正式区分

## 8.1 训练角色
训练主循环中只保留：
- `single_train`
- `sequence_train`

## 8.2 评估方式
不再把 `sequence_eval` 当作训练角色，而改成：
- `manual_sequence_eval`
- `fixed_sequence_benchmark`
- `random_sequence_benchmark`

### 当前正式方案
- 先做独立手动 eval/play 脚本
- 不放入训练主循环
- 不参与参数更新
- 后续如有需要，再升级成自动 periodic eval

---

## 9. `iteration=10000` 时 sequence activated 但 env 数为 0 的问题

## 9.1 当前现象
当前配置中：
- `sequence_train_start_iteration = 10000`
- `sequence_train_env_ratio_initial = 0.0`

因此在 `iteration == 10000` 时：
- scheduler 会认为 sequence 已启用
- 并可能生成 active pool
- 但 layout 计算出的 `sequence_train env count` 仍然为 `0`

## 9.2 原因
这是因为：
- 启用时机和比例起点是分离的
- 启用表示“sequence 训练阶段开始允许存在”
- 但初始比例为 `0`，所以 env 数自然是 `0`

## 9.3 推荐解释方案
当前总设计师建议：

> 将 `iteration=10000` 解释为 **sequence pool 预热点 / 预热阶段的开始点**。

也就是说：
- 10000 时允许 current pool 开始建立
- 但 sequence_train env 数量仍可能为 0
- 真正非零的 sequence_train env 会在后续比例 > 0 时自然出现

### 当前不建议立刻改的地方
- 不建议为了“10000 必须立刻有 sequence env”而急着改整体策略
- 如果未来确实要求 10000 立刻出现 sequence env，再单独把 `sequence_train_env_ratio_initial` 设为非零

---

## 10. 对当前问题项的推荐修订方案（汇总）

### P0-1 registry / metadata 口径不一致
**推荐修订方案**：
- registry 成为唯一事实源
- future metadata/manifest 从 registry 派生
- 旧 combined metadata 只作为过渡输入，不再长期双轨维护

### P0-2 buffer 无真实几何
**推荐修订方案**：
- generator 改为生成“连续基础地板 + 障碍段”
- buffer 只表示相邻障碍段在基础地板上的间隔

### P0-3 archive manifest 不可回读
**推荐修订方案**：
- manifest 使用相对路径
- current / archive 下统一相对 manifest 目录解析
- 修复 archive 回读失败问题

### P1-1 runtime 未闭环
**推荐修订方案**：
- 优先打通：
  - active pool -> assignment
  - assignment -> command/reward/observation
  - assignment -> training scene

### P1-2 10000 时 activated 但 env=0
**推荐修订方案**：
- 当前按“预热点”解释保留
- 若未来必须 10000 立刻有 sequence env，再改 initial ratio

### P1-3 命名混乱
**推荐修订方案**：
- 训练角色只保留：
  - `single_train`
  - `sequence_train`
- 评估模式统一命名为：
  - `manual_sequence_eval`
  - `fixed_sequence_benchmark`
  - `random_sequence_benchmark`
- `future_benchmark_specs()` 继续只表示地形池概念

### P1-4 layout 更像 bucket 而非真实 grid
**推荐修订方案**：
- 当前阶段接受它作为“逻辑 role 配额器”
- 不再把它表述为真实几何 layout
- 后续若需要严格 grid 几何，再单独扩展

### P1-5 朝向统一策略不足
**推荐修订方案**：
- 当前保留启发式
- 中期增加 per-terrain orientation override
- 对已知 warning 地形优先处理

### P1-6 generator / layout 候选池口径不一致
**推荐修订方案**：
- 中期统一成：sequence generator 使用的 sequence_train 候选池必须和训练真实启用池语义完全一致
- 当前若 single_train 与 sequence_train 刚好相同，可以暂时不爆炸，但不能长期依赖巧合

### P2-1 physics/collision 尚未 apply
**推荐修订方案**：
- 当前保留 metadata/profile 接口
- 不抢主线
- 在 assignment / scene / events 闭环之后再接 PhysX apply

### P2-2 `maximum_number_of_terrains` 是伪配置项
**推荐修订方案**：
- 后续要么真正使用它
- 要么删掉，避免误导

### P2-3 group_env_ids_by_terrain 语义不纯
**推荐修订方案**：
- 明确文档说明“这是按 sequence 内 terrain 进行多重归类，不是互斥分组”
- 如后续需要互斥版本，再新增单独接口

---

## 11. 当前总设计师结论（一句话）

> 当前 obstacle_crossing terrain 主线正式转向：以 registry 为唯一事实源，以 generator 生成真实 sequence 模板池，以 scheduler/orchestrator 管理 active sequence cache，以 assignment 绑定 env 到 single terrain 或真实 sequence template；同时将 sequence 几何从“多段 mesh + 空隙”修订为“连续基础地板 + 障碍段排布”，并将 sequence_eval 保持为训练外的独立手动评估方式。
