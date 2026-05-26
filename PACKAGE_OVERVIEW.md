# obstacle_crossing 项目包说明

这个目录是从当前 `InstinctLab` 工作区整理出的**独立项目包**，用于后续单独编辑、归档和项目构建。

## 目录结构

```text
obstacle_crossing/
├── .git/                          # 来自当前 InstinctLab 仓库的 git 元数据
├── docker/                        # Docker 运行配置
├── scripts/                       # 项目脚本（含 make_stay_still_npz.py）
├── source/                        # InstinctLab 源码（含 g1_six_terrain_cfg.py）
├── terrains/                      # 地形、metadata、PROJECT_FRAMEWORK.md
├── worklog/                       # 工作日志（含 2026-05-21.md）
├── memory/                        # 项目记忆、决策、参考说明
├── raw_assets/
│   └── terrain_cad/               # 原始 CAD/STL 地形资产副本
└── PACKAGE_OVERVIEW.md            # 本说明文件
```

## 已包含内容

### 1. 完整 InstinctLab 工作区副本
直接从：
- `D:\Python\instinct\InstinctLab`

复制到：
- `G:\Projects\obstacle_crossing`

包含当前仓库中的：
- `source/instinctlab/...`
- `terrains/...`
- `scripts/...`
- `docker/...`
- `worklog/...`
- `.git/`、`.vscode/`、`.cursor/` 等隐藏目录/文件

### 2. 项目级 memory / 决策文档
从：
- `C:\Users\jqrxy\.claude\projects\D--Python-instinct-InstinctLab\memory`

复制到：
- `G:\Projects\obstacle_crossing\memory`

包括：
- `project_six_terrain.md`
- `project_architecture_decisions.md`
- `project_hardware.md`
- `reference_parkour_base.md`
- `reference_motion_npz_schema.md`
- `user_role.md`
- `MEMORY.md`

### 3. 原始地形资产
从：
- `G:\CAD\障碍建模`

复制到：
- `G:\Projects\obstacle_crossing\raw_assets\terrain_cad`

包括：
- 10 个原始 STL
- `Terrain obstacle modeling.zip`
- `teerain_OF_100.usd`
- 其他该目录下现有内容

## 当前项目关键文件

- 训练/项目路线文档：`terrains/PROJECT_FRAMEWORK.md`
- 六地形 env 配置：`source/instinctlab/instinctlab/tasks/parkour/config/g1/g1_six_terrain_cfg.py`
- stay_still 占位 motion 生成器：`scripts/make_stay_still_npz.py`
- 六地形 metadata：`terrains/combined/metadata.yaml`
- 工作日志：`worklog/2026-05-21.md`

## 关于 Isaac Lab 依赖

本项目训练框架是：
- **Isaac Lab + InstinctLab**

其中当前包内**已完整包含 InstinctLab 工作区副本**，但**未额外包含一份独立的 Isaac Lab 源码树副本**。原因是：
- 当前本机文件系统中没有直接可访问的独立 `isaaclab/` 源码目录
- 当前命令环境里 `docker` 不可用，无法直接从容器导出 Isaac Lab 安装目录

这意味着：
- 本目录足够用于整理项目内容、代码编辑、文档维护、决策沉淀、追加项目代码
- 如果后续需要把它变成**真正完全离线自足**的训练工程，还需要再补一份 Isaac Lab 源码/安装环境导出

## 建议的后续动作

1. 在这个新目录中继续补：
   - `tasks/parkour/config/g1/__init__.py` 里的 gym 注册
   - `combine_terrains.py`
   - 真实 motion retarget 数据

2. 后续从 Isaac Lab 运行环境中补充：
   - Isaac Lab 源码目录，或
   - 可复现的安装说明 / 容器导出

3. 如果后续确认这个目录将成为新的主工作区，建议再单独执行：
   - 清理与本项目无关的历史文件
   - 更新 README / 新建项目级启动说明
   - 视需要改造为独立 git 仓库
