# Obstacle Crossing Terrain 子系统详细分析

## 0. 分析范围与方法

本分析主要覆盖目录：

- `G:\Projects\obstacle_crossing\source\obstacle_crossing\obstacle_crossing\terrain`

重点查看内容包括：

- 地形注册（registry / specs）
- 地形摆放与布局（layout）
- 物理参数与碰撞参数（physics / collision）
- env 分配与查询（assignment）
- sequence 生成与调度（sequence generator / scheduler / orchestrator）

为了保证“内容详实、可靠”，本次不是只读单个文件，而是同时做了三类核验：

1. **静态代码阅读**：逐个审阅 `terrain` 目录核心文件。  
2. **跨模块接线核对**：继续查看 `config`、`mdp`、`terrains` 目录，确认这些 terrain 抽象是否真的被训练入口使用。  
3. **最小化运行验证**：直接构造 registry / layout / sequence pool，并验证若干关键怀疑点是否可复现。

---

## 1. 总体结论（先说结论）

### 1.1 结论一句话版

`terrain` 目录内部的**抽象分层思路是对的**，尤其是 `terrain_specs.py`、`terrain_registry.py`、`sequence_generator.py`、`sequence_pool_scheduler.py` 这几个文件，已经搭出了比较完整的“新 terrain 子系统”骨架；但它目前更像是一个**半接线、半落地、仍与旧六地形导入链路并存的中间态**，距离“真正可靠地驱动训练与评估”还有明显差距。

### 1.2 我对当前状态的判断

如果只看 `terrain` 目录本身：

- **注册层 / 元数据层**：相对完整
- **sequence 生成层**：功能较多，但有几个关键设计缺口
- **layout / assignment 层**：能表达逻辑分配，但还没有真正打通 runtime
- **physics / collision 层**：目前主要是声明式数据，还没有真正 apply 到仿真
- **与训练主链路的整合度**：明显不足

### 1.3 最大的问题不是“某一个函数写错”

最大的问题其实是：

> **新的 registry/layout/sequence 体系已经写出来了，但训练入口仍主要挂在旧的 six-terrain metadata 导入链路上；两套口径没有真正统一。**

这会导致：

- terrain id 口径漂移
- command profile / capability / physics profile 可能对错地形
- sequence pipeline 虽然存在，但在训练主链路中并未真正闭环

这是当前最需要警惕的点。

---

## 2. terrain 目录结构与职责划分

目录中的核心文件如下：

| 文件 | 作用 | 当前状态判断 |
|---|---|---|
| `terrain/__init__.py:1` | 对外导出 registry / layout / physics / assignment / scheduler / specs | 正常 |
| `terrain/terrain_specs.py:16` | 定义 `ObstacleTerrainSpec`、`ContinuousSequenceSamplingCfg`、`SequenceEvalCfg` | 基础扎实 |
| `terrain/terrain_registry.py:176` | 统一注册 terrain、command profile、physics profile、collision profile | 比较完整 |
| `terrain/terrain_physics.py:10` | 定义地形物理与碰撞 profile 数据结构 | 只定义，未真正生效 |
| `terrain/terrain_layout.py:13` | 构造 single / sequence 的 layout 与 role count | 更像逻辑配额器，不是真正几何摆放器 |
| `terrain/terrain_assignment.py:21` | env / tile -> terrain / sequence 的映射查询 | 逻辑层有了，runtime 接线未完成 |
| `terrain/sequence_generator.py:26` | 真实 sequence 模板生成、几何加载、归一化、拼接、导出 | 功能最重，但存在关键缺口 |
| `terrain/sequence_pool_scheduler.py:25` | sequence pool 的启用、刷新、current/archive 生命周期管理 | 方向对，但 archive 有实质 bug |
| `terrain/sequence_generator_requirements.md:1` | 需求说明 | 对实现意图有帮助 |
| `terrain/sequence_pipeline_requirements.md:1` | pipeline 需求说明 | 对整体设计有帮助 |

整体上，**设计已经明显从“单一 metadata 驱动的旧方案”转向“registry + sequence template pool 驱动的新方案”**。这本身是进步。

---

## 3. 先说优点：哪些地方其实做得不错

### 3.1 terrain spec / registry 的分层是清晰的

`terrain/terrain_specs.py:41` 的 `ObstacleTerrainSpec` 与 `terrain/terrain_registry.py:176` 的 `ObstacleTerrainRegistry` 配合得比较合理：

- 事实数据（terrain_id / key / terrain_file / motion_file / tags / capabilities）在 spec 中定义
- profile 映射与 role 过滤在 registry 中集中管理
- `validate()` 会检查训练池、benchmark 池、motion_file、rank 唯一性等约束，见 `terrain/terrain_registry.py:418`

这比把 terrain 相关信息散落在 config、脚本、metadata 里强很多。

### 3.2 物理 profile / collision profile 的“声明式建模”方向是对的

`terrain/terrain_physics.py:10` 和 `terrain/terrain_physics.py:33` 把物理参数与碰撞参数从“散落在仿真代码里”提炼成了稳定 profile：

- `TerrainPhysicsProfile`
- `TerrainCollisionProfile`

这有利于后续把 terrain-specific material / collision 设置集中管理。

### 3.3 sequence metadata 的字段设计比较完整

`terrain/sequence_generator.py:72` 定义的 `SequenceTemplateRecord` 字段很全：

- terrain ids / keys
- command / physics / collision profile keys
- capabilities
- segment ranges
- buffer ranges
- warnings
- geometry / metadata output paths

这说明作者已经意识到：

> 后续 command、reward、physics apply、eval，不能再靠“猜”sequence 内部结构，而应该直接消费模板元数据。

这点是对的，而且是必要的。

### 3.4 sequence pool scheduler / orchestrator 的抽象方向正确

`terrain/sequence_pool_scheduler.py:25`、`terrain/sequence_pool_scheduler.py:38`、`terrain/sequence_pool_scheduler.py:107` 分出了：

- `SequencePoolDecision`
- `SequencePoolScheduler`
- `SequencePoolOrchestrator`

也就是把“课程策略解释”和“目录生命周期管理”分开了。这比把所有逻辑糊在 generator 里要清晰得多。

---

## 4. 详细分析：地形注册（registry / specs）

## 4.1 terrain 注册内容本身

默认 terrain 注册表定义在 `terrain/terrain_registry.py:28` 的 `DEFAULT_G1_TERRAIN_SPECS` 中，共 10 个地形：

- 当前 single_train / sequence_train 使用 6 个
- future benchmark 保留 4 个

其中：

- 训练地形：`continuous_ramp`、`continuous_hurdling`、`cross_slope`、`consecutive_slalom`、`symmetrical_ramp`、`s_curve`
- future benchmark：`spiral_staircase`、`one_meter_platform`、`crawl_channel`、`width_restricted_l_shaped_bend`

profile 也在同文件与 `terrain/terrain_physics.py:49`、`terrain/terrain_physics.py:83` 中统一声明。

这部分结构是合理的。

## 4.2 registry 的验证逻辑是加分项

`terrain/terrain_registry.py:418` 的 `validate()` 会做这些检查：

- registry 非空
- single_train / sequence_train 非空
- sequence_train 必须是 single_train 的子集
- future benchmark 不能与 single_train 重叠
- `curriculum_rank` 唯一
- 训练用 terrain 必须有 `motion_file`

这让 registry 比很多“只管存数据、不管数据对不对”的实现更可靠。

## 4.3 但 registry 与实际训练导入链路 **没有统一** —— 这是最大问题之一

虽然 registry 定义了 10 个 terrain 和稳定 id，但当前 G1 配置仍在使用旧的 six-terrain metadata 方案：

- `config/g1/g1_obstacle_crossing_cfg.py:36` 使用 `MotionMatchedTerrainCfg(path=_TERRAIN_DATA_DIR, metadata_yaml=_METADATA_YAML)`
- `_METADATA_YAML` 指向 `terrains/combined/metadata.yaml`，见 `config/g1/g1_obstacle_crossing_cfg.py:27-30`
- 同时又在 `config/g1/g1_obstacle_crossing_cfg.py:124` 设置 `self.terrain_registry = build_default_obstacle_crossing_registry()`

更关键的是，这个旧 metadata 的 id 映射**与新 registry 不一致**。

### 证据

旧 six-terrain metadata：`terrains/combined/metadata.yaml:23-35`

- id 0 -> continuous_ramp
- id 1 -> symmetrical_ramp
- id 2 -> cross_slope
- id 3 -> s_curve
- id 4 -> continuous_hurdling
- id 5 -> consecutive_slalom

而新 registry：`terrain/terrain_registry.py:28-173`

- id 0 -> continuous_ramp
- id 1 -> continuous_hurdling
- id 2 -> cross_slope
- id 3 -> consecutive_slalom
- id 4 -> symmetrical_ramp
- id 5 -> spiral_staircase（future benchmark）
- id 6 -> s_curve

这意味着：

- 旧 metadata 的 terrain id 1 代表 **symmetrical_ramp**
- 新 registry 的 terrain id 1 代表 **continuous_hurdling**

以及：

- 旧 metadata 的 terrain id 3 代表 **s_curve**
- 新 registry 的 terrain id 3 代表 **consecutive_slalom**

### 影响

一旦训练运行时：

- 地形几何来自旧 metadata / terrain importer
- 但 command profile / capability / physics profile / assignment 又尝试按新 registry 查

那么就会出现**“几何是 A，元数据却按 B 解释”**的问题。

这不是小瑕疵，而是**系统性口径错位**。

### 我的判断

这是当前最严重的问题之一，优先级应视为 **P0**。

## 4.4 `sequence_eval` / `holdout_eval` 命名不够统一

`terrain/terrain_specs.py:8` 的 `ObstacleEnvRole` 包含：

- `single_train`
- `sequence_train`
- `sequence_eval`
- `holdout_eval`

`terrain/terrain_registry.py:273` 又定义了 `sequence_eval_specs()`，而 `terrain/terrain_layout.py:130` 的 sequence layout 只支持：

- `sequence_train`
- `holdout_eval`

这说明当前代码里同时存在：

- `sequence_eval`
- `holdout_eval`

两套近义角色名。

这未必立刻报错，但**会显著增加后续接线和维护时的歧义**。如果保留两套名词，至少要明确：

- `sequence_eval` 是什么
- `holdout_eval` 又是什么
- 二者是否等价
- 谁用于手动 eval，谁用于训练期验证

现在这件事并不清晰。

## 4.5 `maximum_number_of_terrains` 目前几乎是“名义配置”

`terrain/terrain_specs.py:104` 和 `terrain/terrain_specs.py:167` 都有 `maximum_number_of_terrains`。

但在代码搜索中，这个字段基本只在 dataclass 校验中使用，用来保证：

- `maximum_number_of_terrains >= max_sequence_length`

除此之外几乎没有实际功能含义。

这会误导配置使用者，以为它真能控制候选池大小或采样上限；实际上并没有。

建议：

- 要么删掉
- 要么真的让 generator / layout 消费它

否则属于**伪配置项**。

---

## 5. 详细分析：地形物理参数（physics / collision）

## 5.1 物理 profile 定义本身没有明显硬伤

`terrain/terrain_physics.py:49-80` 给出了：

- `default_walk_surface`
- `clearance_surface`
- `stairs_surface`
- `crawl_surface`
- `platform_surface`
- `narrow_turn_surface`

`terrain/terrain_physics.py:83-100` 给出了 collision profile：

- `default`
- `narrow_passage`
- `crawl_channel`

数据结构和校验都比较正常，至少不会一眼看出明显错误。

## 5.2 但这些 profile 目前**基本还是元数据**，没有真正作用到仿真

虽然配置中有：

- `config/obstacle_crossing_env_cfg.py:266` `initialize_terrain_physics_profiles`
- `config/obstacle_crossing_env_cfg.py:267` `apply_terrain_physics_profiles`

但实际实现里：

- `mdp/events.py:17` `initialize_terrain_physics_profiles()` -> `NotImplementedError`
- `mdp/events.py:21` `apply_terrain_physics_profiles()` -> `NotImplementedError`

所以当前 physics/collision profile 的实际状态是：

> **数据定义存在，但还没有真正 apply 到场景/地形 prim 上。**

这意味着当前 terrain 物理参数还处于“纸面生效、运行时未生效”的阶段。

### 结论

这部分不算“写错”，但如果有人以为已经是完整 feature，那就会高估当前系统成熟度。

---

## 6. 详细分析：地形摆放 / 布局（layout）

## 6.1 `terrain_layout.py` 更像“配额/抽样器”，不是几何摆放器

文件 `terrain/terrain_layout.py:71` 的 `ObstacleTerrainLayoutBuilder` 名字叫 layout builder，但它当前主要做的是：

- single_train layout 抽样
- sequence_train layout 抽样
- role ratio / role count 计算

它并不负责真实 mesh 摆放，也不负责 scene 中 terrain tile 的几何拼接或定位。

换句话说，现在的“layout”更接近：

> **逻辑上的 tile 内容分配表**

而不是仿真意义上的空间布局器。

这个命名有一定误导性。

## 6.2 `build_mixed_layout()` 会丢失原始网格形状信息

`terrain/terrain_layout.py:184` 的 `build_mixed_layout()` 接受：

- `num_rows`
- `num_cols`

但后续其实先把它们折成 `total_tiles = num_rows * num_cols`，再按 role 计算 count，最后通过 `terrain/terrain_layout.py:399` 的 `_shape_for_tile_count()` 把每个 role 的布局都变成：

- `(1, tile_count)`

也就是说：

- 原始的二维网格形状并没有保留下来
- 产物不是一个统一大网格，而是多个 role bucket

这和 `ObstacleTerrainLayout` 注释中“assigned to a terrain grid”的表述（`terrain/terrain_layout.py:15`）有一定偏差。

### 影响

如果后续某个模块以为自己拿到的是“真实 rows x cols 地形网格”，就可能产生语义错配。

## 6.3 `holdout_eval` 当前实际上是死代码路径

`terrain/terrain_layout.py:300` 的 `_role_ratios()` 返回：

- `single_train`
- `sequence_train`
- `holdout_eval`

但无论 sequence 是否启用，`holdout_eval` 都被写死为 `0.0`：

- `terrain/terrain_layout.py:309`
- `terrain/terrain_layout.py:331`

因此：

- `build_mixed_layout()` 虽然会试图构造 `holdout_eval` layout（`terrain/terrain_layout.py:224-235`）
- 但 role count 永远是 0
- `_apply_minimum_validation_tiles()`（`terrain/terrain_layout.py:387`）也永远起不来，因为它只有在 role ratio > 0 时才补 1 个 tile

### 结论

`holdout_eval` 在当前实现里属于**名义存在、实际上不会被分配到任何 tile**。

如果这只是为了未来预留，那可以接受；但如果读代码的人以为当前已经有 holdout 验证池，那就是误导。

## 6.4 `sequence_train` 在启用起点会出现“调度已激活，但 layout 里仍是 0 env”的不一致

- `terrain/sequence_pool_scheduler.py:67-74` 在 `iteration == sequence_train_start_iteration` 且当前 manifest 不存在时，会把 refresh reason 标成 `initial_activation`
- `terrain/sequence_pool_scheduler.py:61` 也会在此时触发 `should_refresh`

但 layout 侧的 ratio 计算在起点迭代上仍是：

- progress = 0
- `sequence_train_ratio = sequence_train_env_ratio_initial`

而当前 config 中初始 ratio 就是 0：

- `config/obstacle_crossing_env_cfg.py:312-316`
- `config/g1/g1_obstacle_crossing_cfg.py:125-130`

因此在 `iteration = 10000` 时会出现：

- scheduler 认为 sequence 已进入激活阶段，会生成 current pool
- 但 layout 里 sequence_train env 数仍是 0

我实际跑出来的 role count 也是：

- `iteration = 0` -> `single_train=144, sequence_train=0`
- `iteration = 10000` -> `single_train=144, sequence_train=0`
- `iteration = 30000` -> `single_train=101, sequence_train=43`

### 这是不是 bug？

严格说不一定是 bug，但这是**策略层不一致**：

- 如果 10000 时没有 sequence env
- 那此时就生成 sequence pool，通常只是浪费 I/O 与生成成本

建议至少把这件事写明，或者把首次生成时机和首次分配 env 的时机对齐。

## 6.5 sequence 候选池口径与 generator 不一致

layout 侧 sequence 候选池来自：

- `terrain/terrain_layout.py:255-257` -> `registry.sequence_train_specs()`

而 generator 侧 sequence 候选池来自：

- `terrain/sequence_generator.py:179` -> `registry.single_train_specs()`

当前默认 registry 里这两者恰好一致，所以暂时不炸；但这属于**潜在语义分叉**。

一旦将来：

- 某些 terrain 允许 single_train
- 但不允许 sequence_train

那么 layout 和 generator 会各自基于不同候选池工作，最终产出的“sequence”就会不一致。

### 结论

这是一个**潜伏性设计问题**，优先级中等，但应该尽早统一口径。

---

## 7. 详细分析：sequence 生成（sequence_generator.py）

这是当前 terrain 子系统里最核心、也最值得挑刺的文件。

## 7.1 优点：它已经不只是“逻辑 sequence”，而是在生成真实模板

`terrain/sequence_generator.py:419` 的 `build_training_template_pool()` 会：

- 按 iteration 和 sampling cfg 决定长度范围
- 从候选池采样 terrain
- 读取 segment mesh
- 做归一化
- 拼接 sequence
- 产出 `SequenceTemplateRecord`

从工程结构上看，这是很大的进步。

## 7.2 但当前的“buffer”只有元数据，没有真实几何 —— 这是 **P0 级问题**

`terrain/sequence_generator.py:382-388` 在相邻段之间只做了两件事：

- 记录 `buffer_ranges_y`
- 把 `current_y` 向后推进一段 buffer length

但并没有：

- 生成任何 buffer mesh
- 插入任何连接面 / 过渡面 / 平台 / 地板

真正被拼起来的 mesh 只有：

- `translated_meshes`
- 最后 `trimesh.util.concatenate(translated_meshes)`，见 `terrain/sequence_generator.py:390`

也就是说，sequence 中的 buffer 区间只是**坐标上的空白带**，不是可走的连接几何。

### 我做的最小化验证

针对一个实际生成的 sequence：

- `buffer_ranges_y = ((7.3999, 9.9378),)`
- 在这个 buffer 区间内部统计 sequence mesh 顶点数
- 结果：`buffer_0_interior_vertex_count = 0`

这说明 buffer 区间**没有实际 mesh**。

### 为什么这很严重

需求文档 `terrain/sequence_generator_requirements.md:315` 写的是“真实长地形拼接”；`terrain/sequence_pipeline_requirements.md:27-29` 也明确强调：

- `sequence_train` 必须是真实长地形

但当前实现实际上更接近：

> **把多个障碍段按 Y 轴错开摆放，中间留空气间隙，并在 metadata 里记下 gap 的范围。**

如果后续没有下游系统自动给 gap 补底板，那么这就不是“真实连续地形”，而是“中间断开的多段 mesh 集合”。

### 结论

这是当前实现中最需要优先修的缺口之一。

## 7.3 朝向标准化启发式比较脆弱

`terrain/sequence_generator.py:801-804` 用这个条件判断是否要旋转到 `+Y`：

- 如果 `x_extent >= y_extent * 1.25`，则旋转 90 度

这个启发式比较粗糙，因为它默认：

- 主前进方向一定能靠 bbox 的长边判断
- 而且能被简单二选一地归到 X 或 Y

但复杂地形（尤其 L 形、旋转、弯折、螺旋类）并不总满足这个假设。

### 已验证现象

我直接加载并标准化了默认 registry 里的所有段，结果至少有：

- `symmetrical_ramp`
- `width_restricted_l_shaped_bend`

仍然得到 warning：

- `Segment 'symmetrical_ramp' is not aligned to +Y after normalization.`
- `Segment 'width_restricted_l_shaped_bend' is not aligned to +Y after normalization.`

对应逻辑来自 `terrain/sequence_generator.py:239-244`。

其中 `symmetrical_ramp` 还是当前训练集内地形，不是未来才会用到的边缘地形。

### 结论

当前“统一到 +Y”的能力并不稳健。对于训练集中的某些地形，它只能**发 warning，而不能保证纠正成功**。

## 7.4 Z 对齐只做告警，不做修正，也不阻断

`terrain/sequence_generator.py:374-380` 会检查相邻段边界高度差：

- 若 `z_delta > _Z_CONNECTION_TOLERANCE`（0.05m）就追加 warning

但当前行为仅仅是：

- warning
- 继续生成 sequence

我实际生成的样本里就出现了：

- `continuous_ramp` 和 `cross_slope` 之间 `Z boundary mismatch ... 0.2106 m`

这远大于 0.05m。

### 风险

如果一个 sequence 本意是“连续行进”，那 0.21m 的段间边界落差已经不小了。当前实现只报 warning，不做：

- 硬阻断
- 自动调平
- 连接面补偿

因此 sequence 的几何连续性并没有被保证。

## 7.5 X / Z 不做统一平移，当前依赖资产“碰巧够整齐”

`terrain/sequence_generator.py:347` 只沿 Y 做平移：

- `segment_mesh.apply_translation([0, translation_y, 0])`

不会自动对齐：

- X 方向中心
- Z 方向基线

好消息是：我检查了默认资产的标准化 bbox，当前这批资产的 `x_center` 都是 0，说明目前 X 方向至少还比较整齐。

但这是一种**资产前提**，不是代码保证。

对于 Z，问题就没有这么乐观了，上面已经验证过段间存在明显 mismatch。

## 7.6 generator 的候选池选择与 layout 存在分叉风险

这点前面已经提过，但 generator 里尤其明显：

- `terrain/sequence_generator.py:179` 直接使用 `registry.single_train_specs()`

这意味着 generator 并不遵守“仅 sequence_train enabled terrain 才能进入 sequence”的语义边界，而是信任当前 single_train 和 sequence_train 刚好相同。

这在当前数据下可以工作，但扩展时很危险。

## 7.7 “支持 USD”目前只是接口占位，不是真支持

`terrain/sequence_generator.py:133-140` 的 `UsdSequenceGeometryBackend` 仍是 `NotImplementedError`。

这件事本身不算 bug，因为代码里没有伪装成已经可用；但如果后续文档或使用者把它当成“已支持 USD”，那会误判成熟度。

准确说法应该是：

> **当前仅 STL 路线可用，USD 只是预留接口。**

## 7.8 还有一些小问题

### 7.8.1 `_default_output_dir()` 未被使用

`terrain/sequence_generator.py:784` 定义了 `_default_output_dir()`，但当前没看到实际调用。

这不是大问题，但说明文件里已经开始出现轻微的“预留接口多于实际使用”的迹象。

### 7.8.2 sequence order 被 terrain_id 排序固定化

`terrain/sequence_generator.py:740-741` 的 `_sorted_specs()` 会按 `terrain_id` 排序。

这符合当前需求文档，但它的副作用是：

- sequence 的相邻关系并不是“抽样顺序”
- 而是“按 id 排好的顺序”

这会让 sequence 的语义更像“ID 有序组合”，而不是“随机课程序列”。

这不是 bug，但会限制 sequence 的表达力。

---

## 8. 详细分析：sequence pool 调度与生命周期管理

## 8.1 设计方向没错

`terrain/sequence_pool_scheduler.py:50-86` 的 `build_decision()` 会根据：

- 当前 iteration
- sampling cfg
- 当前 manifest 是否存在

算出：

- sequence 是否启用
- 当前 ratio
- 当前 active length range
- 是否刷新
- refresh reason
- 是否复用 cached pool

这个拆分是合理的。

## 8.2 但 archive manifest 路径会失效 —— 这是 **P0 级实锤 bug**

当前 orchestrator 的主要流程是：

1. 先把新的 pool 导出到 staging 目录：`terrain/sequence_pool_scheduler.py:168-169`
2. 再把旧 `current/` 移到 archive：`terrain/sequence_pool_scheduler.py:192-205`
3. 再把 staging 提升为新的 `current/`：`terrain/sequence_pool_scheduler.py:207-214`
4. 提升后重写 current manifest 内的路径：`terrain/sequence_pool_scheduler.py:242-263`

问题在于：

- `archive_current_pool()` 是直接把旧 `current/` 整个搬走
- 被搬走的旧 manifest 里，`geometry_output_path` / `metadata_output_path` 仍然写着原来的 `current/...` 绝对路径
- 这些路径在新一轮 promote 后就会失效

### 我做的最小化复现

我实际跑了两次刷新：

- 第一次生成 `current`
- 第二次刷新时把旧 current 归档到 `archive/iter_00010000/`

归档后的 manifest 内容中，模板路径仍是：

- `.../current/sequence_000-004__0000.stl`
- `.../current/sequence_000-004__0000.yaml`

然后我直接调用 `_load_pool_manifest()` 读取这个 archive manifest，得到：

- `FileNotFoundError: ... current\sequence_000-004__0000.yaml`

### 结论

当前 archive 目录**表面上存在，实际上不能可靠回读**。

这会直接破坏：

- 回滚
- 复现实验
- 复用历史模板池
- 用 archive 做对比评估

这不是小瑕疵，而是实打实的生命周期管理 bug。

## 8.3 manifest 使用绝对路径，也降低了可移植性

当前导出的 `geometry_output_path` / `metadata_output_path` 都是绝对路径，见：

- `terrain/sequence_pool_scheduler.py:249-258`
- `terrain/sequence_generator.py:647-652`

这会带来两个问题：

1. repo 搬目录、复制到别的机器、换工作区时，manifest 直接失效
2. current/archive 切换时更容易出现路径悬挂

更稳妥的做法通常是：

- manifest 内保存相对路径
- 读取时相对于 manifest 所在目录解析

## 8.4 current/archive 切换缺乏失败恢复策略

当前流程里：

- 新 pool 已经导出到 staging
- 旧 current 已经被移动到 archive
- 如果此时 `promote_new_pool_to_current()` 失败

那么系统就会出现：

- 旧 current 不在了
- 新 current 也没建好

也就是训练侧可能一度没有合法 current pool。

当前代码中没有看到：

- 回滚
- 事务性替换
- 临时软链接方案
- 原子 rename 保护

如果确定运行环境永远单进程、无中断，这个风险可以接受；但从工程稳健性上看，还是偏弱。

---

## 9. 详细分析：env 分配与查询（assignment）

## 9.1 `terrain_assignment.py` 的核心价值：它试图把 layout 层和 runtime 查询层分开

`terrain/terrain_assignment.py:62` 的 `ObstacleTileAssignmentTable` 与 `terrain/terrain_assignment.py:223` 的 `EnvTerrainAssignmentView`，试图解决的问题是：

- tile 层如何表示 terrain/sequence 分配
- env 层如何查询自己的 terrain ids / keys / command profiles / sequence length / segment ranges

这个方向是对的。

## 9.2 但当前它更像“静态视图”，还不是 runtime 真绑定

最关键的证据是：

- `terrain/terrain_assignment.py:454-463` 的 `sync_from_env_terrain_indices()` 仍是 `NotImplementedError`

也就是说，它还没有真正接上 Isaac Lab / terrain importer 的 runtime terrain indices。

当前 assignment view 主要依赖的是：

- `from_layouts_round_robin()`，见 `terrain/terrain_assignment.py:254`
- `from_single_layout_and_sequence_pool()`，见 `terrain/terrain_assignment.py:268`

这两条路都只是：

- 构造逻辑 tile table
- 用 `torch.arange(num_envs) % len(tile_table)` 做 round-robin 分配

并不代表真实仿真场景里 env 当前到底站在哪个 tile 上。

### 结论

当前 assignment 模块更准确的描述应该是：

> **一个离 runtime 只差最后接线的逻辑分配视图。**

不是完整 runtime feature。

## 9.3 如果 assignment 只来自 layout，它拿不到真实 sequence 元数据

`ObstacleTileAssignmentTable._build_tile_records()` 在 layout-only 路径下构造 sequence tile 时，会把：

- `sequence_id=None`
- `segment_ranges_y=()`
- `buffer_ranges_y=()`
- `sequence_total_length_y=None`
- `template_geometry_path=None`
- `template_metadata_path=None`

见 `terrain/terrain_assignment.py:127-144`。

这意味着：

- 如果 sequence assignment 只是从 `ObstacleTerrainLayout` 来
- 那它其实并没有消费 generator 产出的真实 sequence template

换言之，**layout path 和 template path 的信息完备度不一致**。

## 9.4 sequence tile 分配策略过于简单：纯 round-robin 复用模板

`terrain/terrain_assignment.py:176-198` 中，sequence tile 的构造是：

- `template = sequence_pool.template_records[offset % len(sequence_pool.template_records)]`

这意味着：

- template 选择是固定轮转
- 没有随机性
- 没有按重置重采样
- 没有课程难度、capability、成功率反馈

作为最小版是够的，但如果以后要训练更复杂的连续能力，这个分配策略会偏死。

## 9.5 `group_env_ids_by_terrain()` 对 sequence env 的分组语义不纯

`terrain/terrain_assignment.py:400-406` 会对每个 env 的 `record.terrain_keys` 逐个加入 group。

对于 single env 没问题；但对 sequence env 来说，一个 env 会同时出现在多个 terrain key 组里。

### 这会导致什么

如果上层调用者把这个函数理解成“互斥分组”，那就错了。它其实是：

- **按 sequence 中包含哪些 terrain 做多重归类**

而不是：

- “每个 env 属于一个唯一 terrain 组”

这个 API 名字容易让人误解。

---

## 10. 从“摆放/分配”看，新旧系统目前仍未真正闭环

这部分虽然不完全在 `terrain` 目录内，但它直接决定前面那些抽象是不是“真的接上了”。因此必须单独说。

## 10.1 配置层自己就承认：显式 registry-driven multi-sequence layout 还是未来工作

`config/g1/g1_obstacle_crossing_cfg.py:106-110` 的注释已经写得很直白：

> Current terrain importer still uses the six-terrain metadata contract. The explicit registry-driven multi-sequence layout remains a future wiring step.

这基本等于官方自认：

- 当前主链路仍旧是旧 terrain importer
- registry / multi-sequence layout 还没真正接进来

所以如果有人把 `terrain` 目录的当前代码当成“已经 fully integrated 的训练管线”，那是不准确的。

## 10.2 训练配置直接引用了大量 TODO 函数

`config/obstacle_crossing_env_cfg.py` 里已经把很多 terrain 相关能力接进 env 配置：

- 事件：`config/obstacle_crossing_env_cfg.py:263-270`
- 观测：`config/obstacle_crossing_env_cfg.py:164-165`, `192-193`
- command：`config/obstacle_crossing_env_cfg.py:222-233`
- reward：`config/obstacle_crossing_env_cfg.py:237-249`
- termination：`config/obstacle_crossing_env_cfg.py:253-259`
- curriculum：`config/obstacle_crossing_env_cfg.py:273-278`

但这些函数在 `mdp` 侧大量还是 `NotImplementedError`：

- `mdp/events.py:9-36`
- `mdp/observations.py:23-28`
- `mdp/rewards.py:12-41`
- `mdp/terminations.py:16-37`
- `mdp/curriculums.py:14-51`
- `mdp/utils.py:11-36`
- `mdp/commands/terrain_aware_velocity_command.py:38-51`

### 这意味着什么

即使 `terrain` 目录内部抽象越来越完整，当前整体系统仍存在一个很现实的问题：

> **下游消费层并没有实现完。**

也就是说：

- terrain registry 有了
- layout 有了
- assignment 有了
- sequence pool 有了
- 但 command / reward / observation / termination / curriculum / runtime sync 还没真正接上

### 结论

这说明当前 terrain 子系统的成熟度不能只按 `terrain` 目录代码量来评估，必须按**端到端闭环程度**来评估。按这个标准看，目前成熟度明显还不高。

---

## 11. 资产与 metadata 口径还存在额外漂移

## 11.1 `terrains/centered/metadata.yaml` 的 schema 也和 `combined/metadata.yaml` 不同

`terrains/combined/metadata.yaml:23-55` 使用：

- `terrain_id` 为整数
- `motion_files` 也按整数 id 对应

而 `terrains/centered/metadata.yaml:3-22` 中：

- `terrain_id` 是字符串 key（如 `continuous_ramp`）
- 没有 motion_files
- 最后一个 key 还是 `width_restricted_l_shaped`，与 registry 中的 `width_restricted_l_shaped_bend`（`terrain/terrain_registry.py:159`）也不一致

### 含义

这再次说明当前资产侧至少存在两套 metadata 语义：

- 旧 combined 训练链路的一套
- centered 资产目录的一套
- registry / specs 又是一套 Python 内部语义

如果后续不统一成单一事实源（single source of truth），维护成本会越来越高。

---

## 12. 测试覆盖情况：几乎没有看到这条新链路的测试

我在仓库里按 `**/*test*.py` 搜索，没有发现直接覆盖以下对象的测试：

- `ObstacleTerrainRegistry`
- `ObstacleTerrainLayoutBuilder`
- `EnvTerrainAssignmentView`
- `SequencePoolOrchestrator`
- `build_training_template_pool`

这意味着当前关于 terrain 新链路的可靠性，主要还依赖：

- 人工阅读
- 手动验证
- 运行时碰运气

对于这种跨资产、跨 metadata、跨训练入口的功能来说，测试缺失会非常痛。

至少应该补的测试包括：

1. registry id / key / profile 一致性测试  
2. `combined/metadata.yaml` 与 registry 的映射一致性测试  
3. sequence generator 输出 metadata 自洽性测试  
4. buffer 是否真的有几何的测试（当前一定会暴露问题）  
5. current/archive manifest 可回读测试  
6. layout / generator 候选池口径一致性测试  

---

## 13. 重点问题清单（按优先级排序）

## P0：必须优先处理

### P0-1 旧 six-terrain metadata 与新 registry 的 terrain id 口径冲突

- 证据：`config/g1/g1_obstacle_crossing_cfg.py:36-53`, `config/g1/g1_obstacle_crossing_cfg.py:124-140`, `terrains/combined/metadata.yaml:23-35`, `terrain/terrain_registry.py:28-173`
- 影响：command / physics / capability / assignment 可能作用到错误地形
- 性质：系统性风险，不是局部小 bug

### P0-2 sequence buffer 只有范围，没有真实几何

- 证据：`terrain/sequence_generator.py:382-390`
- 运行验证：buffer 区间内部顶点数为 0
- 影响：sequence 并不是真正连续长地形，而是多段 mesh + 空隙

### P0-3 archive manifest 不可回读

- 证据：`terrain/sequence_pool_scheduler.py:192-205`, `terrain/sequence_pool_scheduler.py:242-263`, `terrain/sequence_pool_scheduler.py:266-287`
- 运行验证：从 archive manifest 读取模板时触发 `FileNotFoundError`
- 影响：归档池无法用于回滚、复现、历史评估

## P1：中高优先级

### P1-1 terrain 新体系与训练主链路尚未闭环

- 证据：`config/g1/g1_obstacle_crossing_cfg.py:106-110`, `mdp/events.py:9-36`, `mdp/commands/terrain_aware_velocity_command.py:38-51`, `mdp/observations.py:23-28`, `mdp/rewards.py:12-41`, `mdp/terminations.py:16-37`
- 影响：看起来已经有很多能力，实际多数下游仍不可用

### P1-2 layout 在 sequence 启动点与 scheduler 行为不一致

- 证据：`terrain/sequence_pool_scheduler.py:61-75`, `terrain/terrain_layout.py:312-332`, `config/obstacle_crossing_env_cfg.py:312-324`
- 现象：10000 iteration 时会生成 sequence pool，但 sequence env 仍为 0

### P1-3 `holdout_eval` 是死路径，`sequence_eval` / `holdout_eval` 命名混乱

- 证据：`terrain/terrain_layout.py:224-235`, `terrain/terrain_layout.py:300-332`, `terrain/terrain_registry.py:273-294`
- 影响：容易误判“当前已经存在验证池”

### P1-4 layout 丢失原始网格形状，更像 bucket 而不是真 layout

- 证据：`terrain/terrain_layout.py:193-236`, `terrain/terrain_layout.py:399-403`
- 影响：后续若把它当真正 terrain grid 可能出错

### P1-5 朝向归一化与 Z 连续性保证不足

- 证据：`terrain/sequence_generator.py:263-297`, `terrain/sequence_generator.py:374-380`, `terrain/sequence_generator.py:801-804`
- 已验证现象：`symmetrical_ramp` 仍提示未对齐到 `+Y`

### P1-6 generator / layout 的 sequence 候选池口径不一致

- 证据：`terrain/terrain_layout.py:255-257`, `terrain/sequence_generator.py:179`
- 影响：未来只要 single_train 与 sequence_train 不再完全相同，就会埋雷

## P2：次级问题 / 技术债

### P2-1 physics/collision profiles 目前只是声明，没有真正 apply

- 证据：`terrain/terrain_physics.py:49-100`, `mdp/events.py:17-24`

### P2-2 `maximum_number_of_terrains` 基本是伪配置项

- 证据：`terrain/terrain_specs.py:104`, `terrain/terrain_specs.py:122-125`, `terrain/terrain_specs.py:167`, `terrain/terrain_specs.py:182-185`

### P2-3 `group_env_ids_by_terrain()` 的返回不是互斥分组

- 证据：`terrain/terrain_assignment.py:400-406`

### P2-4 缺少自动化测试

- 影响：后续稍改 registry / metadata / asset 路径就可能静默坏掉

---

## 14. 我认为最值得立即做的修正方向

### 建议 1：先统一“唯一事实源”

二选一，但必须统一：

- 要么以 registry 为唯一事实源，自动生成训练 metadata
- 要么以训练 metadata 为唯一事实源，再回灌 registry

**不要继续同时维护：**

- `terrains/combined/metadata.yaml`
- `terrains/centered/metadata.yaml`
- `terrain_registry.py`

三套近似但不完全一致的口径。

### 建议 2：如果 sequence 要叫“真实长地形”，buffer 必须有真实连接几何

当前最少也要做到：

- 在 buffer 区间补一段可走平面 / 连接面
- 或明确下游 importer 会自动补地板，并把这个契约写死

否则现在的实现不应该宣称“真实连续地形”。

### 建议 3：修复 archive manifest 的路径策略

建议：

- manifest 内改存相对路径
- 路径相对 manifest 所在目录解析
- archive 后不需要重写路径
- 并补一个回读测试

### 建议 4：尽快打通 runtime assignment 与 command / reward / termination 消费链

至少应该优先实现：

- `terrain/terrain_assignment.py:454` `sync_from_env_terrain_indices()`
- `mdp/utils.py:11-36`
- `mdp/commands/terrain_aware_velocity_command.py:38-51`
- `mdp/events.py:9-36`

不然 terrain 新体系再完整，也只是“库代码准备好了，训练其实还没接上”。

### 建议 5：删掉或明确标注当前无效路径

如果短期不会用到：

- `holdout_eval`
- `sequence_eval` 双命名
- `maximum_number_of_terrains`
- 未使用 helper

那就应该：

- 删除
- 或在文档/命名里明确“预留但当前未生效”

这样可显著降低误读成本。

---

## 15. 最终评价

如果只评价 `terrain` 目录本身，我会给出这样的判断：

### 好的一面

- 设计方向是对的
- 分层比旧方案清晰很多
- registry / sequence template / scheduler 这套骨架已经搭起来了
- 很多地方明显是在朝“可维护、可扩展”的方向演进

### 不足的一面

- 目前仍是**过渡态系统**，不是稳定闭环系统
- 新旧 terrain 口径并存且未统一
- sequence 的“连续性”还停留在 metadata 层，不完全是几何层
- runtime 消费层大量未完成
- 缺少自动化测试兜底

### 我的总体结论

> **这套 terrain 子系统现在最像“下一代实现的框架与中间产物”，而不是“已经可完全依赖的最终训练管线”。**

如果你现在要继续推进，我会建议优先顺序是：

1. **先统一 registry 与旧 metadata 的口径**  
2. **再修 sequence buffer / archive manifest 这两个硬问题**  
3. **最后打通 assignment -> command/reward/termination/runtime 的闭环**

在这三步完成前，这个 terrain 子系统可以用于继续开发，但还不适合被视为“已经可靠落地”。

---

## 16. 附：本次最小化验证得到的几个关键现象

### 16.1 role count 验证

在默认配置下，实际得到：

- `iteration=0` -> `single_train=144, sequence_train=0, holdout_eval=0`
- `iteration=10000` -> `single_train=144, sequence_train=0, holdout_eval=0`
- `iteration=30000` -> `single_train=101, sequence_train=43, holdout_eval=0`

这说明：

- `holdout_eval` 当前确实不会被分配
- `10000` 时 scheduler 激活但 layout 仍没有 sequence env 的不一致是可复现的

### 16.2 sequence Z mismatch 警告可复现

实际样本中出现：

- `Z boundary mismatch between 'continuous_ramp' and 'cross_slope': 0.2106 m.`

说明 sequence 连续性问题不是纸面推测。

### 16.3 buffer 无几何可复现

对一个实际生成模板统计 buffer 区间内部顶点数，结果为 0，说明当前 buffer 只是区间，不是连接 mesh。

### 16.4 archive manifest 失效可复现

二次刷新后，从 `archive/iter_xxx/sequence_pool_manifest.yaml` 回读模板会直接触发 `FileNotFoundError`，说明 archive 目前不具备可靠复用价值。
