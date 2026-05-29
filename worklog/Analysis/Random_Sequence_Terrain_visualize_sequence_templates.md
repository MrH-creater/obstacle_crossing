# Random Sequence Terrain `visualize_sequence_templates.py` Requirements

## 1. 文档目的

本文档用于正式定义 `visualize_sequence_templates.py` 的需求与实现边界。

该脚本的目标不是训练，也不是评估策略性能，而是：

> **作为 sequence generator 的几何/元数据可视化验证工具，帮助开发者在服务器或本地快速检查随机生成的 long sequence 地形是否符合预期。**

其主要用途包括：
- 可视化检查 sequence generator 当前输出的长地形几何
- 检查基础地板、障碍段排布、buffer 区间、起始区、结束区
- 检查 sequence 的朝向是否统一到 `+Y`
- 检查 sequence metadata 与几何是否一致
- 帮助在训练闭环接通之前快速做 generator 几何验证

---

## 2. 当前技术背景

当前 obstacle_crossing 的主线已经确定：
- single terrain 为稳定基础样本库
- `sequence_generator.py` 负责动态生成少量真实 long sequence 模板池
- sequence geometry 当前采用：
  - **连续基础地板 + 障碍段排布**
- sequence 输出格式当前优先为：
  - `STL + YAML`
- command、assignment、训练场景、eval 还在继续接线中

因此当前最需要的不是先把训练全部跑通，而是：

> **先验证 generator 输出出来的 sequence 长地形在几何上是不是正确的。**

这正是本脚本存在的意义。

---

## 3. 脚本定位

`visualize_sequence_templates.py` 应定位为：

> **generator 几何与 metadata 的可视化验证工具**

它不应承担：
- 训练逻辑
- eval 调度逻辑
- command 解算逻辑
- assignment runtime 逻辑

它的职责是：
- 调 generator 生成 sequence 模板
- 导出 STL / YAML
- 使用可视化方式展示结果
- 输出必要的调试信息

---

## 4. 正式功能需求

## 4.1 生成少量 sequence 模板
脚本必须支持：
- 调用 `build_training_template_pool(...)`
- 根据输入参数生成少量随机 sequence 模板
- 模板数量可以由命令行参数指定

### 最低要求
应支持参数：
- `iteration`
- `template_count`
- `seed`
- `terrain_root`
- `output_dir`
- `input_backend`
- `output_backend`

---

## 4.2 导出模板
脚本必须支持：
- 导出当前生成的 sequence 模板到指定目录
- 导出：
  - `sequence_<id>.stl`
  - `sequence_<id>.yaml`
  - `sequence_pool_manifest.yaml`

如果 output_dir 已存在，应支持：
- 复用
- 覆盖
- 或写入子目录（由实现端自行选择，但要行为清晰）

---

## 4.3 可视化方式
当前建议至少支持两种模式中的一种，优先推荐 B。

### 方案 A：离线 mesh 可视化（基础版）
- 使用 `trimesh` / `matplotlib`
- 直接显示 sequence mesh
- 可选叠加 waypoint / anchor / segment 边界

### 方案 B：复用现有 Isaac Sim / terrain visualization 入口（推荐）
- 使用现有 terrain 可视化工作流
- 将 sequence STL 作为 terrain 载入场景
- 在真实仿真渲染环境下观察结果

### 当前建议
V1 优先支持：
- **方案 B（推荐）**

如果实现复杂度太高，也允许先实现：
- **方案 A**
作为第一版。

---

## 4.4 必须支持的可视化检查项
脚本至少应能帮助开发者确认：

### A. 基础地板是否存在
- 是否生成了一整块基础地板
- 宽度是否为 `3m`
- 厚度是否为 `0.20m`
- 总长度是否符合：
  - `1m + Y + 1m`

### B. 障碍段是否正确排布在地板上
- 各障碍段是否位于地板上
- 是否沿 `+Y` 方向顺序排布
- 起点区和结束区是否保留

### C. buffer 区间是否正确
- 相邻障碍之间是否保留了 buffer
- buffer 长度是否在 `1m~3m`
- buffer 是间隔而不是几何断层

### D. 朝向是否统一
- 所有段的推荐通过方向是否大体与 `+Y` 平行
- 是否出现明显朝向错误的段

### E. metadata 是否匹配几何
- `segment_ranges_y` 与几何摆放是否一致
- `sequence_total_length_y` 是否与实际长度一致
- `terrain_ids / terrain_keys` 是否符合当前 sequence 结构

---

## 4.5 可视化辅助标记（建议）
为了方便 debug，建议脚本支持输出或叠加以下信息：

### A. segment 边界线
在可视化中标记：
- 每个 segment 的 `start_y`
- 每个 segment 的 `end_y`

### B. buffer 区间标记
标出：
- buffer 起点
- buffer 终点

### C. 起始区 / 结束区标记
标出：
- 地板起始区 1m
- 地板结束区 1m

### D. 文字输出
打印：
- `sequence_id`
- `terrain_ids`
- `terrain_keys`
- `buffer_lengths_y`
- `sequence_total_length_y`
- `warnings`

---

## 4.6 支持查看单条模板与模板池
脚本应支持两种使用方式：

### 模式 1：查看整个模板池
- 生成 `N` 条模板
- 导出全部
- 选择逐个查看或打印摘要

### 模式 2：查看某一条模板
- 指定 `template_index`
- 只可视化/打印该模板

---

## 5. 建议命令行参数

建议至少支持以下 CLI 参数：

```text
--iteration
--template-count
--seed
--terrain-root
--output-dir
--input-backend
--output-backend
--template-index
--export-only
--visualize-only
--show-metadata
--show-segment-ranges
--show-buffer-ranges
```

### 参数建议解释
- `--iteration`
  - 决定当前 sequence 长度课程阶段
- `--template-count`
  - 生成多少条 sequence 模板
- `--seed`
  - 控制随机采样复现性
- `--terrain-root`
  - single terrain STL 根目录
- `--output-dir`
  - sequence 导出目录
- `--template-index`
  - 只查看某条模板
- `--export-only`
  - 只导出，不显示
- `--visualize-only`
  - 已有模板目录中只做可视化
- `--show-metadata`
  - 打印 metadata 摘要
- `--show-segment-ranges`
  - 打印或绘制 segment ranges
- `--show-buffer-ranges`
  - 打印或绘制 buffer ranges

---

## 6. 输入来源与依赖模块

脚本应直接复用现有模块，而不是重新实现逻辑。

## 6.1 必须调用的模块
### `sequence_generator.py`
至少复用：
- `build_training_template_pool(...)`
- `export_sequence_template(...)`
- `export_template_pool_manifest(...)`

### `terrain_registry.py`
至少复用：
- `build_default_obstacle_crossing_registry()`

### `terrain_specs.py`
至少复用：
- `ContinuousSequenceSamplingCfg`

---

## 6.2 可选复用模块
### `visualize_terrain.py`
如果当前项目已有：
- `scripts/visualize_terrain.py`

则优先参考或复用其现有 terrain 加载/展示方式，避免重新造一套完全独立的可视化入口。

---

## 7. 建议输出内容

脚本运行后建议输出：

### 7.1 控制台摘要
例如：
- 当前 iteration
- 当前 active length range
- 生成模板数
- 每条模板的：
  - `sequence_id`
  - `terrain_ids`
  - `terrain_keys`
  - `buffer_lengths_y`
  - `sequence_total_length_y`
  - `warnings`

### 7.2 文件输出
- STL
- YAML
- manifest

### 7.3 可选图形输出
- mesh view
- segment/buffer range 边界线
- 起点/终点区域

---

## 8. 目标效果

这个脚本实现完成后，开发者应能：

1. 在不接训练闭环的情况下，独立检查 generator 生成的 random sequence 长地形
2. 快速发现：
   - 朝向是否正确
   - 基础地板是否存在
   - buffer 是否合理
   - metadata 是否自洽
3. 在服务器或本地快速做 sequence 几何 smoke test
4. 在 generator 修复迭代中作为标准验证工具使用

---

## 9. 推荐实现顺序

### Step 1
实现 CLI 参数解析

### Step 2
构建 registry 和 `ContinuousSequenceSamplingCfg`

### Step 3
调用 `build_training_template_pool(...)` 生成模板池

### Step 4
导出模板和 manifest

### Step 5
输出控制台摘要

### Step 6
加入 mesh 可视化功能
- 优先尝试复用现有 terrain 可视化脚本逻辑
- 如难度太大，先实现离线 mesh 可视化版本

---

## 10. 当前总设计师结论

`visualize_sequence_templates.py` 当前阶段是非常值得做的工具，因为：

> 在训练闭环尚未完全接通之前，它可以先帮我们验证 sequence generator 的几何与 metadata 是否正确，从而避免在训练中才发现基础 terrain 资产层的问题。

它的定位应明确为：
- **sequence generator 的可视化验证工具**
- 而不是训练脚本的一部分
- 也不是 eval 脚本本身
