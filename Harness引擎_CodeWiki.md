# Harness 引擎 Code Wiki

> **项目名称：** Harness — 本地可部署的 AI 角色扮演引擎  
> **开发者：** 独立开发  
> **数据与运行环境：** 单机本地（Windows），推理后端为 Ollama  
> **文档生成日期：** 2026-08-14

---

## 目录

1. [项目概述](#1-项目概述)
2. [项目文件清单（已排除无关目录）](#2-项目文件清单已排除无关目录)
3. [整体架构](#3-整体架构)
4. [模块详细说明](#4-模块详细说明)
5. [关键类与函数](#5-关键类与函数)
6. [依赖关系图](#6-依赖关系图)
7. [数据持久化结构](#7-数据持久化结构)
8. [项目运行方式](#8-项目运行方式)
9. [配置说明](#9-配置说明)
10. [部署方案](#10-部署方案)
11. [测试与质量保证](#11-测试与质量保证)

---

## 1. 项目概述

Harness 是一套**本地运行的 AI 角色扮演引擎**。用户选定一个虚拟角色后，可以与该角色进行多轮对话；系统在后台维护角色人设、对话历史、长期记忆，并在每轮对话结束后自动做质量评分。

### 1.1 设计理念

Harness 从第一天就按「可部署、可观测、可运营」来设计：
- **可部署：** 用户登录与数据隔离、REST API、管理后台、Docker 部署方案
- **可观测：** 四维度规则评分 + 质检流水表、长期记忆可视化（用户端 + 管理端）
- **可运营：** 管理后台可直接编辑角色 JSON，实现「人工纠偏」

### 1.2 五层架构概览

```
用户 → 交互层 → 控制层 → 认知层 → 执行层 → 持久层
```

| 层级 | 职责 | 对应文件 |
|------|------|----------|
| 交互层 | Flask Web UI + FastAPI REST API + 管理后台 | [web_ui.py](file:///c:/Users/guang/web_ui.py), [api/](file:///c:/Users/guang/api/), [app/](file:///c:/Users/guang/app/), [admin/](file:///c:/Users/guang/admin/) |
| 控制层 | 调度引擎（选角、拼 prompt、调模型、触发后处理） | [harness_core.py](file:///c:/Users/guang/harness_core.py) |
| 认知层 | 角色设定、情绪状态、长期记忆仓库、叙事弧光 | [soul/](file:///c:/Users/guang/soul/), [emotion/](file:///c:/Users/guang/emotion/), [character_memory.py](file:///c:/Users/guang/character_memory.py), [memory/](file:///c:/Users/guang/memory/), [arc/](file:///c:/Users/guang/arc/) |
| 执行层 | 调用本地 Ollama 生成回复 | [ollama_client.py](file:///c:/Users/guang/ollama_client.py), [embeddings.py](file:///c:/Users/guang/embeddings.py) |
| 持久层 | SQLite 数据库、JSON 文件、质检流水表 | [database/](file:///c:/Users/guang/database/), [harness.db](file:///c:/Users/guang/harness.db), users/{uid}/characters/{key}/ |

---

## 2. 项目文件清单（已排除无关目录）

### 2.1 排除的目录 / 文件

以下内容不属于 Harness 引擎项目，已在分析中排除：
- `d-agency-for-qwen` / `.d-agency-for-qwen`
- `WPS Cloud` / `WPS Cloud Files` / `WPSDrive`
- `联系人 (Contacts)` / `链接 (Links)` / `视频 (Videos)` / `搜索 (Searches)` / `下载 (Downloads)` / `音乐 (Music)` / `桌面 (Desktop)`
- `.trae-cn` / `.docker` / `.docker-build`（注意：这是旧构建缓存，非主项目） / `.ollama`
- `OneDrive` / `DevEcoStudioProject`
- `paperclip/`（独立 TypeScript 项目）
- `.hvigor` / `.ohpm` / `.pm2` / `.paperclip` / `.ai_completion` / `AppData/` / `NTUSER.*` 等系统目录

### 2.2 Harness 引擎相关文件一览

#### 根目录核心文件

| 文件 | 职责 |
|------|------|
| [harness_core.py](file:///c:/Users/guang/harness_core.py) | **调度引擎主文件**：HarnessEngine 类、多入口 API、用户引擎缓存 |
| [harness_config.py](file:///c:/Users/guang/harness_config.py) | 引擎外置配置（config.json）加载、深度合并、校验 |
| [Harness引擎进展与架构汇报.md](file:///c:/Users/guang/Harness%E5%BC%95%E6%93%8E%E8%BF%9B%E5%B1%95%E4%B8%8E%E6%9E%B6%E6%9E%84%E6%B1%87%E6%8A%A5.md) | 项目架构汇报文档 |
| [config.json](file:///c:/Users/guang/config.json) | 引擎运行时配置（模型、路径、间隔等） |
| [config.py](file:///c:/Users/guang/config.py) | Flask 应用配置（SECRET_KEY、数据库 URI、Session） |
| [requirements.txt](file:///c:/Users/guang/requirements.txt) | Python 依赖清单 |
| [web_ui.py](file:///c:/Users/guang/web_ui.py) | Flask Web UI 入口（启动服务、创建管理员） |
| [run_api.py](file:///c:/Users/guang/run_api.py) | FastAPI REST API 启动脚本（uvicorn） |
| [cli_demo.py](file:///c:/Users/guang/cli_demo.py) | 命令行对话演示 |
| [Dockerfile](file:///c:/Users/guang/Dockerfile) | 多阶段 Docker 构建（builder → runtime） |
| [docker-compose.yml](file:///c:/Users/guang/docker-compose.yml) | Docker Compose 三服务编排（web / api / nginx） |
| [DEPLOYMENT.md](file:///c:/Users/guang/DEPLOYMENT.md) | 部署操作文档 |
| [extensions.py](file:///c:/Users/guang/extensions.py) | Flask 扩展实例（db / login_manager / csrf） |
| [logger.py](file:///c:/Users/guang/logger.py) | 会话执行轨迹记录器（输入 / 回复 / 状态变更 / 错误） |
| [embeddings.py](file:///c:/Users/guang/embeddings.py) | Ollama 向量嵌入客户端 + 余弦相似度 |
| [ollama_client.py](file:///c:/Users/guang/ollama_client.py) | Ollama HTTP 客户端（流式 / 非流式 / 取消 / 重试） |
| [soul.py](file:///c:/Users/guang/soul.py) | 向后兼容重导出（soul.model.Soul） |
| [emotion.py](file:///c:/Users/guang/emotion.py) | 旧版简单情绪管理（关键词法，1–10 分） |
| [character_memory.py](file:///c:/Users/guang/character_memory.py) | 运行时记忆引擎（短期 FIFO + 长期向量/关键词检索） |
| [memory_extractor.py](file:///c:/Users/guang/memory_extractor.py) | LLM 从对话中提取长期记忆事实 |
| [arc_updater.py](file:///c:/Users/guang/arc_updater.py) | LLM 评估角色弧光与当前目标更新 |
| [unified_analyzer.py](file:///c:/Users/guang/unified_analyzer.py) | 合并：单次 LLM 调用同时做记忆提取 + 弧光评估 |
| [character_manager.py](file:///c:/Users/guang/character_manager.py) | 多角色注册表、目录、路径解析、切换与迁移 |
| [stress_test_manual.py](file:///c:/Users/guang/stress_test_manual.py) | 手动压测脚本 |
| [demo_memory_impact.py](file:///c:/Users/guang/demo_memory_impact.py) | 记忆影响演示 |
| [triggered_summary_pseudo.py](file:///c:/Users/guang/triggered_summary_pseudo.py) | 触发摘要伪代码 |
| [migrate_existing_data.py](file:///c:/Users/guang/migrate_existing_data.py) | 现有数据迁移 |
| [migrate_import_characters.py](file:///c:/Users/guang/migrate_import_characters.py) | 角色导入迁移 |
| [memory_extractor.py](file:///c:/Users/guang/memory_extractor.py) | 同上 |
| [install_docker.ps1](file:///c:/Users/guang/install_docker.ps1) | Docker 安装 PowerShell 脚本 |
| [.env.example](file:///c:/Users/guang/.env.example) | 环境变量模板 |
| [.dockerignore](file:///c:/Users/guang/.dockerignore) | Docker 忽略规则 |
| [characters.json](file:///c:/Users/guang/characters.json) | 全局角色注册表 |
| [soul_state.json](file:///c:/Users/guang/soul_state.json) | 旧版单文件 Soul 状态 |
| [memory_state.json](file:///c:/Users/guang/memory_state.json) | 旧版单文件记忆状态 |
| [emotion_state.json](file:///c:/Users/guang/emotion_state.json) | 旧版单文件情绪状态 |
| [harness.db](file:///c:/Users/guang/harness.db) | SQLite 数据库（用户、角色、评分流水等） |
| [harness-memory-flowchart.png](file:///c:/Users/guang/harness-memory-flowchart.png) | 记忆模块流程图 |
| [harness-memory-architecture.excalidraw](file:///c:/Users/guang/harness-memory-architecture.excalidraw) | 记忆架构图（Excalidraw） |
| [characters.json](file:///c:/Users/guang/characters.json) | 角色注册表（幽灵 / 老K / 喵小星） |

#### 包目录结构

| 目录 | 职责 |
|------|------|
| [admin/](file:///c:/Users/guang/admin/) | Flask 管理后台（角色 CRUD、评分统计、记忆可视化、安全审核） |
| [api/](file:///c:/Users/guang/api/) | FastAPI REST API（认证、角色、对话、弧光、记忆路由） |
| [app/](file:///c:/Users/guang/app/) | Flask 应用主体（create_app 工厂、用户登录、数据路由、记忆路由） |
| [arc/](file:///c:/Users/guang/arc/) | 角色弧光管理（配置、日志、模型、渲染、manager） |
| [characters/](file:///c:/Users/guang/characters/) | 角色数据目录（每个角色独立文件夹 + soul_core.json / soul_state.json） |
| [config_manager/](file:///c:/Users/guang/config_manager/) | 配置管理器（备份、加载、注册、校验、写入） |
| [database/](file:///c:/Users/guang/database/) | 数据库（SQLAlchemy 模型、Session、schema.sql 初始化） |
| [deploy/](file:///c:/Users/guang/deploy/) | 部署相关（entrypoint、healthcheck、nginx、supervisor、脚本） |
| [emotion/](file:///c:/Users/guang/emotion/) | PAD 三维情绪管理（分析器、规则、衰减、阶段、渲染、模型） |
| [memory/](file:///c:/Users/guang/memory/) | 长期记忆可视化（读取、解析、搜索、IO） |
| [performance/](file:///c:/Users/guang/performance/) | 性能保障（GPU 检测、请求队列、超时、监控、配置） |
| [safety/](file:///c:/Users/guang/safety/) | 内容安全网关（输入/输出过滤、审核、扫描、审计） |
| [scoring/](file:///c:/Users/guang/scoring/) | 对话质量评分（规则四维度 + 可选 LLM 评分 + 引擎入库） |
| [scripts/](file:///c:/Users/guang/scripts/) | 数据迁移脚本（migrate_characters.py） |
| [soul/](file:///c:/Users/guang/soul/) | Soul 核心/状态分层（模型、加载器、迁移、schema、校验、写入） |
| [static/](file:///c:/Users/guang/static/) | 静态资源（stream_chat.js 流式前端） |
| [streaming/](file:///c:/Users/guang/streaming/) | 流式响应（SSE、流适配器、取消管理器） |
| [tests/](file:///c:/Users/guang/tests/) | 测试套件（18 个测试文件，覆盖各模块） |
| [users/](file:///c:/Users/guang/users/) | 用户数据隔离目录（users/{uid}/characters.json 等） |
| [worlds/](file:///c:/Users/guang/worlds/) | 世界观配置（cyber_station.json、low_gravity.json） |

---

## 3. 整体架构

### 3.1 五层架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  交互层（Presentation）                                          │
│  Flask Web UI（web_ui.py / app/）  +  FastAPI REST API（api/）   │
│  管理后台（admin/，Bootstrap）  →  供前端调用的 /api/*            │
│  CLI 对话（cli_demo.py）                                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  控制层（Orchestration）                                         │
│  HarnessEngine 调度：选角、拼 prompt、调模型、触发后处理           │
│  用户登录与数据隔离（Flask-Login + is_admin，users/{uid}/ 目录）   │
│  性能排队 + 超时 + 监控（performance/）                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼────────┐  ┌────────▼────────┐  ┌───────▼────────┐
│ 认知层          │  │ 内容安全中间件  │  │  评分中间件     │
│ soul/          │  │ safety/         │  │  scoring/      │
│ emotion/       │  │ 输入/输出审核    │  │  四维度评估      │
│ character_     │  │                  │  │  规则+LLM双路   │
│ memory.py      │  │                  │  │                │
│ memory/ 可视化  │  │                  │  │                │
│ arc/ 弧光       │  │                  │  │                │
└───────┬────────┘  └────────┬────────┘  └───────┬────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  执行层（Inference）                                             │
│  ollama_client.py → 本地 Ollama（OpenAI-compatible 格式）        │
│  embeddings.py → /api/embeddings 向量检索                         │
│  规划：线上切换 DeepSeek API + Headroom Token 压缩中间件          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  持久层（Persistence）                                            │
│  SQLite（harness.db）：用户、角色、质检流水、弧光日志、会话         │
│  JSON 文件（characters/{key}/）：soul_core / soul_state /        │
│      memory_state / emotion_state                                 │
│  Docker 卷 harness-data（部署方案）                               │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 单轮对话调用链

#### 入口 A：Flask Web UI

```
用户 → web_ui.py (Flask)
     → app/routes/data_routes.py /api/chat
     → harness_core.py → process_message()
```

#### 入口 B：FastAPI REST API

```
用户 → api/routes/chat.py /api/chat/completions
     → harness_core.py → generate_response()
                → performance.run_inference() [排队+超时+监控]
                → _generate_response_core()
                    → DB 角色校验
                    → _get_engine_for_user() [引擎缓存]
                    → engine.process_message()
                    → scoring.engine.score_and_persist()
```

#### 入口 C：CLI 对话

```
用户 → harness_core.py chat_loop()
     → process_message() / process_message_stream()
```

#### process_message() 内部核心步骤（三入口汇合）

```
1. 热重载配置（reload_config）
2. 安全审核：safety.gateway.check_user_input()
3. logger.log_input() + memory.add_message("user", ...)
4. 情绪更新：emotion.process_user_turn()
5. build_prompt() 组装上下文（soul + emotion + 相关记忆 + 近期对话）
6. _generate_reply() → chat_ollama.generate[_stream]()
7. 输出审核：safety.gateway.sanitize_model_output()
8. logger.log_response() + memory.add_message("assistant", ...)
9. round_count++ + emotion 持久化
10. 后处理（按间隔触发）：
    ├─ 每 N 轮：MemoryExtractor 抽取事实 → 写入 long_term
    └─ 每 M 轮：ArcUpdater 评估弧光 → 更新 soul.arc_stage / current_goal
    或 UnifiedAnalyzer 一次 LLM 调用完成两者
11. 每 K 轮：_save_all_state() 自动持久化
12. 返回 TurnResult(response, new_facts, arc_changes, error)
```

---

## 4. 模块详细说明

### 4.1 控制层：调度引擎核心

#### [harness_core.py](file:///c:/Users/guang/harness_core.py)

Harness 引擎的大脑，负责：
- **初始化：** 加载配置、创建各子组件实例（Soul、Memory、Emotion、OllamaClient、MemoryExtractor、ArcUpdater、UnifiedAnalyzer、CharacterManager、EmbeddingClient）
- **角色切换：** `switch_character(name)` 保存当前状态、切换注册表、重新加载新角色的 soul/memory/emotion
- **Prompt 组装：** `build_prompt(user_message)` 将角色设定 + 情绪 + 相关长期记忆 + 近期对话历史拼成完整的单段 prompt 字符串
- **消息处理（非流式）：** `process_message(user_message)` — 同步处理，返回 TurnResult
- **消息处理（流式 Token）：** `process_message_stream(user_message)` — 生成器方式 yield `(token|done|cancelled|error, payload)`
- **消息处理（分步进度，Web UI 用）：** `iter_turn(user_message)` — yield StepProgress（step=1/2/3 对应 生成/记忆/弧光）
- **CLI 对话循环：** `chat_loop()` — 支持 `/exit` `/status` `/save` `/stream` 命令
- **用户级引擎缓存：** `_engine_cache: dict[int, HarnessEngine]` + `_get_engine_for_user(user_id)`
- **压测模式：** `HARNESS_STRESS_MODE=1` 环境变量禁用后处理，仅跑对话模型
- **数据库初始化：** `init_database(db_path)`

#### [harness_config.py](file:///c:/Users/guang/harness_config.py)

引擎外置配置管理：
- `DEFAULT_CONFIG`：内置默认配置（9 个 section：paths / ollama / engine / memory_extractor / arc_updater / emotion / unified_analyzer / web / embeddings / characters）
- `_deep_merge(base, override)`：递归深度合并配置
- `validate_config(config)`：数值范围校验
- `load_config(filepath, overrides, create_if_missing, validate)`：加载 config.json
- `save_config(config, filepath)`：保存 JSON
- `get_section(config, section)`：安全取 section

---

### 4.2 认知层：角色灵魂

#### [soul/model.py](file:///c:/Users/guang/soul/model.py) → `Soul` 类

定义 AI 角色的「灵魂」：**核心身份（不变）** 与 **叙事状态（可演化）**。

| 属性 | 类型 | 说明 |
|------|------|------|
| `name` | str | 角色名字 |
| `role` | str | 职业 / 身份 |
| `core_traits` | list[str] | 核心性格特质数组 |
| `core_drive` | str | 核心驱动力（角色行动的深层动机） |
| `fear` | str | 内心恐惧 |
| `catchphrases` | list[str] | 口头禅数组 |
| `vocabulary` | list[str] | 常用词汇数组 |
| `arc_stage` | str | 角色弧光阶段（起点 / 转折点 / 终点） |
| `current_goal` | str | 当前目标 |

核心方法：
- `apply_narrative_update(arc_stage, current_goal)`：验证并应用叙事更新（弧光只能保持或前进一阶），返回实际变更 dict
- `to_dict()` / `to_core_dict()` / `to_state_dict()`：序列化为不同层级的 dict
- `save(filepath)` / `load(filepath)`：持久化 / 加载

分层设计：
- **CORE_KEYS**（7 个）：角色静态身份，写入 `soul_core.json`（不可变或需人工审批变更）
- **STATE_KEYS**（2 个）：叙事动态状态，写入 `soul_state.json`（对话过程中自动演化）

#### [soul/loader.py](file:///c:/Users/guang/soul/loader.py)

Soul 的加载与保存：
- `load_soul_from_paths(path, template, auto_migrate)`：从分层目录或旧版单文件加载，返回 `(soul, core_dict, state_dict, warnings)`
- `save_soul_state(soul, filepath)`：仅写入 state 字段
- `apply_core_to_soul()` / `apply_state_to_soul()`：将 dict 应用到 Soul 对象

#### [soul/migration.py](file:///c:/Users/guang/soul/migration.py)

旧版单文件 `soul_state.json` → 新版分层 `soul_core.json + soul_state.json` 的迁移逻辑：
- `needs_migration(char_dir)`：检测是否需要迁移
- `migrate_legacy(char_dir, template)`：执行迁移
- `soul_paths(char_dir)`：返回 `{legacy, core, state}` 三个路径

#### [soul/validator.py](file:///c:/Users/guang/soul/validator.py) + [soul/writer.py](file:///c:/Users/guang/soul/writer.py) + [soul/core_schema.py](file:///c:/Users/guang/soul/core_schema.py) + [soul/state_schema.py](file:///c:/Users/guang/soul/state_schema.py)

- Core / State 的 JSON Schema 定义与校验
- 写入时自动备份（write_core_update 创建 _backup 副本）

---

### 4.3 认知层：情绪管理

#### [emotion/manager.py](file:///c:/Users/guang/emotion/manager.py) → `PADEmotionManager`

**PAD 三维情绪模型**（Pleasure-Arousal-Dominance），fail-open 异常安全。

处理流程：`process_user_turn(user_message)`
1. 规则加载：`load_rules()`
2. 文本分析：`analyzer.analyze_user_input()` → 行为类别 ID
3. 规则偏移：`rules.get_offset_for_behavior(behavior)` → PAD 增量
4. 基线衰减：`decay.apply_decay(pad, stage_baseline, rounds=1)` → 向阶段基线缓慢回归
5. 阶段切换：`stage.check_stage_transition(stage, stats)` → 基于统计判断是否切换阶段
6. 统计递增 + 日志回调

关键属性：
- `score`：兼容旧版 1–10 情绪分（供 unified_analyzer / arc_updater 消费）
- `pad`：三维情绪向量（Pleasure, Arousal, Dominance，范围 -1.0~+1.0）
- `stage`：情绪阶段标签（如 stranger / acquaintance / friend / trust / conflict）

#### [emotion/analyzer.py](file:///c:/Users/guang/emotion/analyzer.py)

分析用户输入文本，识别行为类别（感谢、威胁、背叛、信任请求等）。

#### [emotion/rules.py](file:///c:/Users/guang/emotion/rules.py) + [emotion/rules.json](file:///c:/Users/guang/emotion/rules.json)

每类行为对应的 PAD 偏移规则（可配置 JSON）。

#### [emotion/decay.py](file:///c:/Users/guang/emotion/decay.py)

情绪衰减：偏离基线的部分按回合数逐步回归。

#### [emotion/stage.py](file:///c:/Users/guang/emotion/stage.py)

阶段判定：基于累计正向/负向交互数，决定情绪阶段跃迁。

#### [emotion/models.py](file:///c:/Users/guang/emotion/models.py) + [emotion/renderer.py](file:///c:/Users/guang/emotion/renderer.py) + [emotion/config.py](file:///c:/Users/guang/emotion/config.py)

- `EmotionRuntimeState` dataclass（PAD、stage、stats）
- `render_emotion()`：将 PAD 向量转为自然语言描述，供 prompt 注入
- 常量配置：POSITIVE_BEHAVIORS、NEGATIVE_BEHAVIORS、CONFLICT_STAGE 等

#### [emotion.py](file:///c:/Users/guang/emotion.py) → `Emotion`（旧版）

旧版简单情绪：基于正负关键词加减 0.2，单一 1–10 分数。已被 `PADEmotionManager` 取代，但仍保留作兼容参考。

---

### 4.4 认知层：记忆系统

#### [character_memory.py](file:///c:/Users/guang/character_memory.py) → `Memory` 类

运行时记忆引擎，分两层：

| 记忆层 | 数据结构 | 容量 | 检索方式 | 持久化 |
|--------|----------|------|----------|--------|
| **短期记忆** `short_term` | `list[{role, content, timestamp}]` | `max_rounds * 2` 条 | FIFO 滑动窗口，直接拼入 prompt | `memory_state.json` |
| **长期记忆** `long_term` | `list[{fact, importance, timestamp, embedding?}]` | 不限 | 向量余弦相似度 × importance（优先级高），失败回退关键词匹配 | `memory_state.json` |

核心方法：
- `add_message(role, content)`：追加短期消息，超限 FIFO 弹出
- `add_fact(fact, importance, embedding?)`：追加长期事实，importance 强制 clamp 到 1–5；若有 embed_fn 则计算向量
- `get_relevant_facts(query, limit)`：优先向量检索，失败回退关键词匹配，返回 top-N 相关事实
- `_keyword_search()` / `_vector_search()`：两种检索实现
- `save()` / `load()`：JSON 持久化

#### [memory_extractor.py](file:///c:/Users/guang/memory_extractor.py) → `MemoryExtractor`

使用 LLM 从对话中提取值得长期保存的关键事实：
- Prompt 构造：告知规则（不编造、简洁、importance 分级）+ 已有长期记忆（防重复）+ 本轮对话
- 容错 JSON 解析：支持裸 `[]`、```json ``` 包裹、兜底正则
- `_validate_facts()`：规范化 fact 文本 + importance 范围
- `extract(user_msg, ai_resp, existing_facts)` → `(facts_list, raw_llm_output)`
- `filter_new_facts(candidates, existing_facts)`：去重（精确匹配 + 子串相似）

#### [memory/reader.py](file:///c:/Users/guang/memory/reader.py) + [memory/parser.py](file:///c:/Users/guang/memory/parser.py) + [memory/search.py](file:///c:/Users/guang/memory/search.py) + [memory/io.py](file:///c:/Users/guang/memory/io.py) + [memory/config.py](file:///c:/Users/guang/memory/config.py)

长期记忆可视化模块（只读 + 统计）：
- 分页读取 memory_state.json
- 统计 importance 分布、时间趋势（供 Chart.js 渲染）
- 供 `/memory` 用户端和 `/admin/memory/` 管理端展示

---

### 4.5 认知层：叙事弧光

#### [arc_updater.py](file:///c:/Users/guang/arc_updater.py) → `ArcUpdater`

使用 LLM 评估对话是否应推动角色弧光或更新当前目标：
- Prompt 构造：当前弧光状态 + 情绪分 + 对话 → 是否 should_update
- 约束：arc_stage 只能是起点/转折点/终点，且只能保持或前进一阶
- `evaluate(soul, user_msg, ai_resp, emotion_score)` → `(update_dict|None, raw)`
- `apply_to_soul(soul, update)`：调用 `soul.apply_narrative_update()`

#### [unified_analyzer.py](file:///c:/Users/guang/unified_analyzer.py) → `UnifiedAnalyzer`

**优化：一次 LLM 调用同时完成记忆提取 + 弧光评估**（比分开调用节省一次模型推理）。
- 可开关 `analyze_facts` / `analyze_arc`
- 返回 `{facts: [...], narrative: {should_update, arc_stage?, current_goal?, reason?}}`

#### [arc/manager.py](file:///c:/Users/guang/arc/manager.py) + [arc/models.py](file:///c:/Users/guang/arc/models.py) + [arc/renderer.py](file:///c:/Users/guang/arc/renderer.py) + [arc/config.py](file:///c:/Users/guang/arc/config.py) + [arc/logger.py](file:///c:/Users/guang/arc/logger.py)

数据库侧的弧光管理：
- `on_engine_arc_update()`：引擎弧光更新回调 → 写入 ArcLog 表
- Arc 模型：stages[] / goals[] / progress / auto_advance
- 供管理后台 `/admin/characters/<id>/arc` 查看和人工推进

---

### 4.6 认知层：角色管理

#### [character_manager.py](file:///c:/Users/guang/character_manager.py) → `CharacterManager`

多角色注册表、目录隔离、路径解析、切换、迁移。

核心职责：
1. **注册表加载**：读取 `characters.json`，与 DEFAULT_REGISTRY（幽灵 / 老K）合并
2. **目录创建**：`characters/{name}/` 下不存在 soul_core.json 时，从注册表模板写入
3. **路径解析**：`resolve_paths(name)` → `{soul, soul_core, soul_state, memory, emotion, log_session}`
4. **角色切换**：`set_active(name)` + 配合 HarnessEngine.switch_character() 做状态保存/重载
5. **旧文件迁移**：根目录的旧 `soul_state.json` / `memory_state.json` / `emotion_state.json` → `characters/{active}/` 下

#### [characters/](file:///c:/Users/guang/characters/) 目录

每个角色一个独立子目录：
- `{角色名}/soul_core.json`：静态身份（name、role、core_traits 等）
- `{角色名}/soul_state.json`：动态叙事（arc_stage、current_goal）
- （其他同目录：memory_state.json、emotion_state.json）

预置角色：**幽灵**（星际赏金猎人）、**老K**（空间站军火商）、**喵小星**

---

### 4.7 执行层：推理客户端

#### [ollama_client.py](file:///c:/Users/guang/ollama_client.py) → `OllamaClient`

封装与本地 Ollama API 的 HTTP 交互。

异常体系：
- `OllamaError`（基类）
  - `OllamaConnectionError`（无法连接）
  - `OllamaTimeoutError`（超时）
  - `OllamaResponseError`（响应格式异常）

核心方法：
| 方法 | 说明 |
|------|------|
| `generate(prompt, **kwargs)` | 非流式生成，返回完整文本；支持 `stream=True` 内部走流式 |
| `generate_stream(prompt, on_token, show_thinking=False)` | 流式生成 + 逐 token 回调，返回完整文本 |
| `iter_tokens(prompt, cancel_event=None, **kwargs)` | 低级别流式迭代器，yield `(field, token)`，field 为 response / thinking；支持 `cancel_event` 取消 |
| `_extract_text(data)` | 文本提取策略：优先 response 字段，空时回退 thinking（推理模型） |
| `_post(payload, stream)` | 请求发送 + 指数退避重试（默认 max_retries=2） |
| `get_last_call()` | 最近一次 request + response 原始 dict（供 Logger 记录） |
| `cancel_ollama_request()` / `abort_stream()` | 关闭活跃 HTTP 连接 + best-effort POST `/api/cancel` |

流式取消机制：
- `cancel_event`（threading.Event）在 iter_tokens 循环中每块检查
- 检测到 set 时关闭连接，并额外 best-effort 通知 Ollama `/api/cancel`

#### [embeddings.py](file:///c:/Users/guang/embeddings.py) → `EmbeddingClient`

调用 Ollama `/api/embeddings` 生成文本向量（默认 nomic-embed-text 模型）：
- `embed(text)` → `list[float]`，带超时重试
- `cosine_similarity(a, b)`：纯 Python 余弦相似度，供记忆向量检索

---

### 4.8 控制层辅助：性能保障

#### [performance/\_\_init\_\_.py](file:///c:/Users/guang/performance/__init__.py) → `run_inference(task, user_id, character_id)`

FastAPI 入口 `generate_response()` 不直接调引擎，而是走 `run_inference()`：
- 请求队列排队（避免并发推理打爆 Ollama）
- 超时控制
- GPU 检测与性能指标记录

子模块：
| 模块 | 职责 |
|------|------|
| [performance/queue_manager.py](file:///c:/Users/guang/performance/queue_manager.py) | FIFO 队列 + 容量上限 + 拒绝策略（QueueBusyError） |
| [performance/runtime.py](file:///c:/Users/guang/performance/runtime.py) | run_inference 主逻辑 |
| [performance/gpu_check.py](file:///c:/Users/guang/performance/gpu_check.py) | pynvml GPU 状态检测 |
| [performance/metrics.py](file:///c:/Users/guang/performance/metrics.py) | 延迟、吞吐、Token/s 等指标采集 |
| [performance/monitor.py](file:///c:/Users/guang/performance/monitor.py) | 后台监控线程 |
| [performance/config.py](file:///c:/Users/guang/performance/config.py) | 配置 + performance.env |

---

### 4.9 控制层辅助：内容安全

#### [safety/gateway.py](file:///c:/Users/guang/safety/gateway.py)

统一安全入口，供 harness_core 调用：
- `check_user_input(text, user_id, character_id)` → 拦截提示 str 或 None（放行）
- `sanitize_model_output(text, user_id, character_id)` → 过滤后的文本

流程：filter → auditor.log_audit_record → 命中 blocked 则替换统一提示

子模块：
| 模块 | 职责 |
|------|------|
| [safety/input_filter.py](file:///c:/Users/guang/safety/input_filter.py) | 用户输入黑名单匹配、等级判定（monitor / blocked） |
| [safety/output_filter.py](file:///c:/Users/guang/safety/output_filter.py) | 模型输出过滤，防敏感词 / AI 元认知泄漏 |
| [safety/loader.py](file:///c:/Users/guang/safety/loader.py) | 敏感词库加载 |
| [safety/scanner.py](file:///c:/Users/guang/safety/scanner.py) | 关键词扫描器 |
| [safety/auditor.py](file:///c:/Users/guang/safety/auditor.py) | 审核记录写入数据库 / 日志 |
| [safety/config.py](file:///c:/Users/guang/safety/config.py) | 阈值 / 词库路径配置 |

---

### 4.10 控制层辅助：质量评分

#### [scoring/engine.py](file:///c:/Users/guang/scoring/engine.py)

评分主引擎：`score_conversation()` + `score_and_persist()`。

四维度评估（config.DIMENSION_WEIGHTS 加权）：

| 维度 | 规则方式 | 说明 |
|------|----------|------|
| **相关性** relevance_score | 词元重叠度 | 回复是否回应了用户问题 |
| **角色一致性** consistency_score | 与 system_prompt 等元数据重叠度 | 回复是否符合人设 |
| **流畅度** fluency_score | 句长、n-gram 重复率 | 语句是否通顺无重复堆砌 |
| **安全性** safety_score | 黑名单命中（命中 0 分，否则满分） | 是否触碰敏感内容 |

双路评分策略：
- **默认：规则评分**（毫秒级，不阻塞主流程）
- **可选：LLM 评分**（scoring/llm_scorer.py），失败自动回退规则
- 结果写入 `score_logs` 表（Flask DB 优先，否则独立 SQLite）

子模块：
| 模块 | 职责 |
|------|------|
| [scoring/rules.py](file:///c:/Users/guang/scoring/rules.py) | 四维度规则实现 |
| [scoring/llm_scorer.py](file:///c:/Users/guang/scoring/llm_scorer.py) | LLM 评分（可选开启） |
| [scoring/config.py](file:///c:/Users/guang/scoring/config.py) | 维度权重、默认方法、LLM 开关 |

---

### 4.11 交互层：Flask Web UI

#### [web_ui.py](file:///c:/Users/guang/web_ui.py)

CLI 入口：
- `python web_ui.py run --host --port --debug`：启动 Flask 服务（默认 127.0.0.1:7860）
- `python web_ui.py create-admin --username --password`：创建/提升管理员账户
- `create_flask_app()`：供 `flask --app` / gunicorn 使用的应用工厂

#### [app/\_\_init\_\_.py](file:///c:/Users/guang/app/__init__.py) → `create_app()`

Flask 应用工厂：
1. 初始化配置（Config.from_object + 可选 overrides）
2. 绑定扩展：`db.init_app` / `csrf.init_app` / `login_manager.init_app`
3. `@login_manager.user_loader`：SQLAlchemy User 加载
4. 数据库建表 + SQLite schema 初始化 + admin schema 迁移
5. 注册 Blueprint：
   - `auth_bp`（登录/注册）
   - `data_bp`（对话 / 流式 SSE / 取消 / 状态）
   - `memory_bp`（记忆可视化 / 管理）
   - `character_wizard_bp`（角色创建向导）
   - `admin_bp`（管理后台，url_prefix=/admin）
6. CLI 命令注册（init_cli）
7. `/health` 健康检查、404/500 错误处理器

#### [app/routes/auth.py](file:///c:/Users/guang/app/routes/auth.py) + [app/routes/data_routes.py](file:///c:/Users/guang/app/routes/data_routes.py) + [app/routes/memory_routes.py](file:///c:/Users/guang/app/routes/memory_routes.py)

| 路由 | 说明 |
|------|------|
| `/auth/login` | Flask-Login 登录页 |
| `/auth/register` | 注册 |
| `/auth/logout` | 登出 |
| `/api/chat` (POST) | 对话请求 → harness_core.process_message() |
| `/stream/chat` (GET SSE) | 流式对话 → StepProgress SSE |
| `/cancel` (POST) | 取消正在生成的请求（streaming.cancel_manager） |
| `/api/status` | 引擎状态快照 |
| `/memory` | 用户角色记忆可视化页 |
| `/memory/manage/<id>` | 记忆管理（增删改长期记忆条目） |
| `/characters/create` | 角色创建向导 |
| `/character/<id>` | 角色弧光详情页 |

#### [app/models/user.py](file:///c:/Users/guang/app/models/user.py)

Flask SQLAlchemy 模型（User、CharacterRecord、ScoreLog 等，与 database.models 映射同表）。

#### [app/services/auth_service.py](file:///c:/Users/guang/app/services/auth_service.py) + [app/cli.py](file:///c:/Users/guang/app/cli.py)

认证服务（密码 hash、用户创建）+ CLI 命令（create-admin 等）。

#### [app/static/js/stream_chat.js](file:///c:/Users/guang/app/static/js/stream_chat.js)

前端 SSE 流式对话 JS：订阅 `/stream/chat`，逐 token 更新 UI，支持取消按钮。

#### [app/templates/](file:///c:/Users/guang/app/templates/)

`index.html`（主对话页）、`login.html`、`register.html`。

---

### 4.12 交互层：管理后台

#### [admin/blueprint.py](file:///c:/Users/guang/admin/blueprint.py) + [admin/views/](file:///c:/Users/guang/admin/views/)

Flask Blueprint：`admin_bp`，`url_prefix=/admin`，`@admin_required` 装饰器保护。

views 子模块：
| 视图 | 职责 |
|------|------|
| [dashboard.py](file:///c:/Users/guang/admin/views/dashboard.py) | 仪表盘（用户数、角色数、评分趋势、性能指标） |
| [characters.py](file:///c:/Users/guang/admin/views/characters.py) | 角色 CRUD、参数编辑、JSON 编辑表单 |
| [character_wizard.py](file:///c:/Users/guang/admin/character_wizard.py) | 角色创建向导（分步表单） |
| [users.py](file:///c:/Users/guang/admin/views/users.py) | 用户管理、提升/撤销管理员 |
| [memories.py](file:///c:/Users/guang/admin/views/memories.py) + [memory.py](file:///c:/Users/guang/admin/views/memory.py) | 全站角色记忆浏览 / 单角色记忆详情 + 图表 |
| [scores.py](file:///c:/Users/guang/admin/views/scores.py) | 质检流水表列表 + 低分对话筛选 |
| [performance.py](file:///c:/Users/guang/admin/views/performance.py) | 性能监控面板（延迟、吞吐、GPU 利用率） |
| [soul.py](file:///c:/Users/guang/admin/views/soul.py) + [forms/soul.py](file:///c:/Users/guang/admin/forms/soul.py) | Soul core/state 表单编辑 |
| [config.py](file:///c:/Users/guang/admin/views/config.py) | config.json 在线编辑（热重载） |
| [arc.py](file:///c:/Users/guang/admin/views/arc.py) | 角色弧光管理（人工推进/回退、目标编辑） |
| [safety.py](file:///c:/Users/guang/admin/views/safety.py) | 安全审核日志 + 词库管理 |

其他 admin 辅助：
- [admin/decorators.py](file:///c:/Users/guang/admin/decorators.py)：`@admin_required` 装饰器
- [admin/audit_log.py](file:///c:/Users/guang/admin/audit_log.py)：管理员操作审计
- [admin/character_sync.py](file:///c:/Users/guang/admin/character_sync.py)：DB 角色 ↔ 文件系统角色同步
- [admin/soul_paths.py](file:///c:/Users/guang/admin/soul_paths.py)：Soul 路径管理
- [admin/static/admin.css](file:///c:/Users/guang/admin/static/admin.css)：后台 Bootstrap 样式

---

### 4.13 交互层：FastAPI REST API

#### [api/main.py](file:///c:/Users/guang/api/main.py) → `app: FastAPI`

FastAPI 应用：
- 标题/版本/docs_url/openapi_url 设置
- CORS 中间件（来源 settings.cors_origins_list()）
- lifespan：启动时建表 + SQLite schema 初始化
- `/api/health` 健康检查

注册路由：
```
/api/* auth.router       → 认证（JWT）
/api/* characters.router → 角色 CRUD
/api/* chat.router       → 对话（含流式 SSE）
/api/* arc.router        → 弧光状态
/api/* memories.router   → 记忆查询/管理
```

#### [api/config.py](file:///c:/Users/guang/api/config.py) + [api/dependencies.py](file:///c:/Users/guang/api/dependencies.py)

- Pydantic Settings：CORS origins、JWT 密钥、DB URL
- 依赖注入：`get_db`（SQLAlchemy Session）、`get_current_user`（JWT 解码）

#### [api/routes/](file:///c:/Users/guang/api/routes/)

| 路由文件 | 主要端点 |
|----------|----------|
| [auth.py](file:///c:/Users/guang/api/routes/auth.py) | `POST /api/auth/register`、`POST /api/auth/login`（返回 JWT） |
| [characters.py](file:///c:/Users/guang/api/routes/characters.py) | `GET/POST /api/characters`、`GET/PUT/DELETE /api/characters/{id}` |
| [chat.py](file:///c:/Users/guang/api/routes/chat.py) | `POST /api/chat/completions`（同步）、`POST /api/chat/stream`（SSE） |
| [arc.py](file:///c:/Users/guang/api/routes/arc.py) | `GET /api/characters/{id}/arc`、`POST /api/characters/{id}/arc/progress` |
| [memories.py](file:///c:/Users/guang/api/routes/memories.py) | `GET /api/characters/{id}/memories`、`POST/DELETE` 条目 |

#### [api/schemas/](file:///c:/Users/guang/api/schemas/)

Pydantic 请求/响应模型：`user.py`、`character.py`、`chat.py`、`memory.py`、`arc.py`。

#### [api/services/auth_service.py](file:///c:/Users/guang/api/services/auth_service.py) + [api/utils/security.py](file:///c:/Users/guang/api/utils/security.py)

JWT 签发/验证、密码哈希（passlib.bcrypt）。

#### [run_api.py](file:///c:/Users/guang/run_api.py)

`uvicorn.run(api.main:app, host=127.0.0.1, port=8000, reload=True)`。

---

### 4.14 持久层：数据库

#### [database/models.py](file:///c:/Users/guang/database/models.py) → SQLAlchemy ORM

| 表名 | 模型 | 关键字段 | 说明 |
|------|------|----------|------|
| `users` | User | id, username, password_hash, is_admin, is_active, created_at | 用户账户 |
| `characters` | Character | id, user_id(FK), character_key, display_name, role, description, system_prompt, parameters_json, emotion_state, deleted, version | 角色元数据（DB 侧） |
| `arcs` | Arc | id, character_id(FK, UNIQUE), current_stage, stages(JSON), goals(JSON), progress, auto_advance | 角色弧光状态 |
| `arc_logs` | ArcLog | id, character_id, user_id, action, details, operator, created_at | 弧光变更审计日志 |
| `conversations` | Conversation | id, user_id, character_key, role, content, created_at | 对话历史存档 |
| `session_logs` | SessionLog | id, user_id, session_id, log_path, created_at | 会话日志路径索引 |
| `score_logs` | ScoreLog | id, user_id, character_id, user_message, bot_reply, relevance_score, consistency_score, fluency_score, safety_score, total_score, scoring_method, created_at | 质检流水表 |
| （Admin 侧补充） | | audit_logs, safety_logs | 管理后台操作审计 + 安全日志 |

#### [database/session.py](file:///c:/Users/guang/database/session.py)

- `engine`：SQLAlchemy Engine（SQLite 默认）
- `SessionLocal`：sessionmaker 工厂
- `get_database_url()`：从环境变量取
- `get_db()`：FastAPI Depends 用的生成器

#### [database/\_\_init\_\_.py](file:///c:/Users/guang/database/__init__.py)

`init_sqlite_schema(db_path)`：执行 `schema.sql` 初始化索引/触发器/视图。

#### [database/schema.sql](file:///c:/Users/guang/database/schema.sql)

原始 SQL（索引、唯一约束、触发器、可选 JSON 校验）。

---

### 4.15 流式与取消

#### [streaming/sse.py](file:///c:/Users/guang/streaming/sse.py)

Server-Sent Events 响应格式化：`event: token\ndata: {...}\n\n`。

#### [streaming/stream_adapter.py](file:///c:/Users/guang/streaming/stream_adapter.py)

HarnessEngine token generator → Flask/FastAPI Response 适配。

#### [streaming/cancel_manager.py](file:///c:/Users/guang/streaming/cancel_manager.py)

按 `(user_id, request_id)` 维护 threading.Event，供 `/cancel` 端点远程取消活跃生成。

---

### 4.16 配置管理

#### [config_manager/](file:///c:/Users/guang/config_manager/)

高级配置管理（比 harness_config.py 更完整的 CRUD）：
- [loader.py](file:///c:/Users/guang/config_manager/loader.py)：多来源加载（JSON / 环境 / 代码默认）
- [writer.py](file:///c:/Users/guang/config_manager/writer.py)：原子写入 + 版本号
- [validator.py](file:///c:/Users/guang/config_manager/validator.py)：JSON Schema 校验
- [registry.py](file:///c:/Users/guang/config_manager/registry.py)：运行时配置注册表
- [backup.py](file:///c:/Users/guang/config_manager/backup.py)：自动 rollback 备份

---

### 4.17 日志与监控

#### [logger.py](file:///c:/Users/guang/logger.py) → `Logger`

记录完整执行轨迹（JSON 数组，保存至 `logs/session_{session_id}.json`）：

| entry.type | 记录内容 |
|------------|----------|
| `user_input` | 用户原始消息 |
| `ai_response` | AI 回复消息 |
| `api_call` | Ollama 完整 prompt + request + response |
| `state_change` | module + key + old_value + new_value（memory / emotion / soul / unified_analyzer） |
| `error` | 异常详情 |

方法：`log_input()` / `log_response()` / `log_state_change()` / `log_error()` / `save_session(template_path)`。

#### 性能指标（performance/metrics.py） + 管理后台性能页

- 对话延迟 P50/P95/P99
- 每用户 / 每角色 QPS
- GPU 显存 / 利用率（pynvml）
- Token 生成速度（tok/s）
- 队列长度与等待时间

---

### 4.18 世界观

#### [worlds/](file:///c:/Users/guang/worlds/)

全局世界观 JSON，供 prompt 组装时可选注入：
- `cyber_station.json`：赛博朋克空间站设定
- `low_gravity.json`：低重力殖民站设定

---

## 5. 关键类与函数

### 5.1 核心调度

#### `HarnessEngine`（harness_core.py）

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(config_path, user_id?, user_data_root?, **overrides)` | 加载配置、创建全部子组件、加载 soul/memory/emotion |
| `process_message` | `(user_message, *, stream?, character_id?) → TurnResult` | 同步处理单条消息 |
| `process_message_stream` | `(user_message, *, cancel_event?, character_id?, timeout?)` yield `(event, payload)` | 流式处理，逐 token |
| `iter_turn` | `(user_message)` yield `StepProgress` | Web UI 分步进度流 |
| `iter_message` | `(user_message)` yield `(partial, done, TurnResult)` | 旧 API 兼容 |
| `build_prompt` | `(user_message) → str` | 拼装角色设定+情绪+记忆+历史的完整 prompt |
| `switch_character` | `(name) → str` | 保存当前 → 切角色 → 重载状态 |
| `get_status` | `() → dict` | 引擎状态快照（供 UI /status 用） |
| `reload_config` | `()` | 热重载 config.json |
| `chat_loop` | `()` | CLI 对话循环 |
| `shutdown` | `()` | 保存状态 + 存会话日志 |

#### 顶层函数（harness_core.py）

| 函数 | 说明 |
|------|------|
| `generate_response(user_id, character_id, user_input) → str` | FastAPI 同步入口，经 performance 排队 + 评分入库 |
| `generate_response_stream(user_id, character_id, user_input, cancel_event?)` | FastAPI 流式入口，结束时评分入库 |
| `init_database(db_path?)` | 初始化 SQLite schema |
| `_get_engine_for_user(user_id)` | 按 user_id 缓存 HarnessEngine 实例（避免重复加载） |
| `_stress_config_overrides()` | `HARNESS_STRESS_MODE=1` 时返回压测配置覆盖（关后处理、降 num_predict） |

### 5.2 数据类

#### `TurnResult`（harness_core.py）

单轮对话处理结果：`response: str`、`new_facts: list[str]`、`arc_changes: list[str]`、`error: str|None`。

#### `StepProgress`（harness_core.py）

Web UI 分步进度：`step`/`total`（共 3 步）、`label`、`partial`（已生成文本）、`done`、`result: TurnResult|None`。

### 5.3 角色灵魂

| 类/函数 | 文件 | 说明 |
|---------|------|------|
| `Soul` | soul/model.py | 角色灵魂模型，7 个核心字段 + 2 个状态字段 |
| `Soul.apply_narrative_update()` | soul/model.py | 弧光/目标变更验证与应用，只能前进 |
| `load_soul_from_paths()` | soul/loader.py | 分层加载，自动迁移旧版单文件 |
| `save_soul_state()` | soul/loader.py | 仅保存 state 部分 |
| `needs_migration()` + `migrate_legacy()` | soul/migration.py | 旧版 → 分层迁移 |
| `soul_paths(char_dir)` | soul/migration.py | 返回 `{legacy, core, state}` 三路径 |

### 5.4 情绪

| 类 | 文件 | 说明 |
|----|------|------|
| `PADEmotionManager` | emotion/manager.py | PAD 三维情绪管理器（主用） |
| `Emotion`（旧版） | emotion.py | 单维关键词情绪（兼容参考） |

### 5.5 记忆

| 类 | 文件 | 说明 |
|----|------|------|
| `Memory` | character_memory.py | 短期 FIFO + 长期向量/关键词检索 |
| `MemoryExtractor` | memory_extractor.py | LLM 提取新事实 + JSON 容错解析 |
| `EmbeddingClient` | embeddings.py | Ollama 向量嵌入 |
| `cosine_similarity()` | embeddings.py | 余弦相似度计算 |

### 5.6 叙事分析

| 类 | 文件 | 说明 |
|----|------|------|
| `ArcUpdater` | arc_updater.py | 弧光/目标评估 + 应用 |
| `UnifiedAnalyzer` | unified_analyzer.py | 一次 LLM 调用同时做事实提取 + 弧光评估（推荐开启） |

### 5.7 角色管理

| 类 | 文件 | 说明 |
|----|------|------|
| `CharacterManager` | character_manager.py | 注册表加载、目录创建、路径解析、旧文件迁移、切换 |

### 5.8 推理客户端

| 类 | 文件 | 说明 |
|----|------|------|
| `OllamaClient` | ollama_client.py | 流式/非流式/取消/重试，兼容 thinking 推理模型 |
| `cancel_ollama_request()`（模块函数） | ollama_client.py | best-effort 全局取消请求 |

### 5.9 评分与安全

| 函数 | 文件 | 说明 |
|------|------|------|
| `score_conversation()` | scoring/engine.py | 四维度评估（规则优先，LLM 兜底） |
| `score_and_persist()` | scoring/engine.py | 评分 + 写入 score_logs 表（DB 双适配） |
| `check_user_input()` | safety/gateway.py | 用户输入审核，返回拦截提示或 None |
| `sanitize_model_output()` | safety/gateway.py | 模型输出过滤，替换或原样返回 |

### 5.10 应用工厂与启动

| 函数 | 文件 | 说明 |
|------|------|------|
| `create_app(config_overrides?)` | app/__init__.py | Flask 应用工厂（DB 初始化 + Blueprint 注册 + CLI） |
| `create_flask_app()` | web_ui.py | 供 flask/gunicorn 调用的无参工厂 |
| `main()` | web_ui.py | argparse CLI：run / create-admin |
| `app: FastAPI` | api/main.py | FastAPI 实例（CORS + lifespan + 5 个 Router） |

---

## 6. 依赖关系图

### 6.1 模块依赖（Python import 方向）

```
harness_core.py  ←────────────────────────────────────────── 入口
  │
  ├── harness_config.py   (配置加载/校验)
  ├── soul/               (Soul 模型/加载/迁移)
  │     └── soul.model.Soul  ←  re-export by ./soul.py
  ├── character_memory.py (Memory 引擎)
  │     └── embeddings.py (cosine_similarity)
  ├── emotion.manager     (PADEmotionManager)
  ├── logger.py           (Logger)
  ├── ollama_client.py    (OllamaClient / OllamaError)
  ├── memory_extractor.py (MemoryExtractor → uses OllamaClient)
  ├── arc_updater.py      (ArcUpdater → uses OllamaClient + Soul)
  ├── unified_analyzer.py (UnifiedAnalyzer → uses OllamaClient + MemoryExtractor)
  ├── character_manager.py (CharacterManager → uses soul/)
  ├── embeddings.py       (EmbeddingClient)
  ├── safety.gateway      (check_user_input / sanitize_model_output)
  ├── performance.init    (run_inference)
  └── scoring.engine      (score_and_persist)

web_ui.py → app.__init__.create_app()
  ├── extensions.py       (db / login_manager / csrf)
  ├── config.py           (Config / SECRET_KEY / DB URI)
  ├── app.routes.*        (auth / data / memory / wizard)
  └── admin.blueprint     (admin_bp + views)

run_api.py → api.main.app
  ├── api.config (Pydantic Settings)
  ├── api.routes.* (auth/characters/chat/arc/memories)
  ├── api.dependencies + api.services.auth_service
  └── database.session + database.models
```

### 6.2 Python 外部依赖（requirements.txt）

| 库 | 用途 |
|----|------|
| `requests>=2.28.0` | Ollama HTTP 客户端 |
| `Flask>=3.0.0` | Web UI 框架 |
| `Flask-Login>=0.6.3` | 用户登录会话 |
| `Flask-SQLAlchemy>=3.1.0` | Flask ORM |
| `Flask-WTF>=1.2.0` + `WTForms>=3.1.0` | CSRF + 表单 |
| `python-dotenv>=1.0.0` | .env 加载 |
| `email-validator>=2.0.0` | 邮箱校验 |
| `click>=8.0.0` | CLI |
| `fastapi>=0.115.0` | REST API 框架 |
| `uvicorn[standard]>=0.32.0` | ASGI 服务器 |
| `python-jose[cryptography]>=3.3.0` | JWT 签发/验证（FastAPI 认证） |
| `passlib[bcrypt]>=1.7.4` + `bcrypt>=4.0.0` | 密码哈希 |
| `pydantic-settings>=2.0.0` | FastAPI 配置 |
| `sqlalchemy>=2.0.0` | 独立 ORM（database 模块） |
| `aiosqlite>=0.20.0` | 异步 SQLite（FastAPI 可选） |
| `httpx>=0.27.0` | 异步 HTTP（FastAPI 健康检查/内部调用） |
| `gunicorn>=22.0.0` | WSGI 生产服务器（Docker 用） |
| `pynvml>=11.5.0` | NVIDIA GPU 状态监控 |

---

## 7. 数据持久化结构

### 7.1 文件系统布局

```
项目根（C:\Users\guang\）
├── config.json                     # 引擎运行配置
├── harness.db                      # SQLite 数据库（用户/角色/评分流水等）
├── characters.json                 # 全局角色注册表（可被 DB 覆盖）
├── characters/                     # 角色数据目录（每个角色一个子文件夹）
│   ├── 幽灵/
│   │   ├── soul_core.json          # 静态身份（不变）
│   │   ├── soul_state.json         # 动态叙事状态（弧光/目标）
│   │   ├── memory_state.json       # 短期 + 长期记忆
│   │   └── emotion_state.json      # PAD 情绪状态
│   ├── 老K/
│   └── 喵小星/
├── users/                          # 用户级数据隔离（替代根目录角色）
│   ├── {user_id}/
│   │   ├── characters.json         # 该用户的角色注册表
│   │   └── characters/{key}/       # 该用户角色的 soul/memory/emotion 文件
├── logs/session_{session_id}.json  # 会话日志（由 Logger.save_session 写入）
└── worlds/                         # 全局世界观配置
    ├── cyber_station.json
    └── low_gravity.json
```

### 7.2 memory_state.json 格式

```json
{
  "max_messages": 20,
  "use_vector": true,
  "short_term": [
    {"role": "user", "content": "...", "timestamp": "2026-...Z"},
    {"role": "assistant", "content": "...", "timestamp": "2026-...Z"}
  ],
  "long_term": [
    {
      "fact": "用户委托追踪涅克瑟斯星区的走私犯",
      "importance": 4,
      "timestamp": "2026-...Z",
      "embedding": [0.12, -0.03, ...]
    }
  ]
}
```

### 7.3 soul_core.json 格式

```json
{
  "name": "幽灵",
  "role": "星际赏金猎人",
  "core_traits": ["坚韧", "多疑", "外冷内热"],
  "core_drive": "...",
  "fear": "被最信任的系统背叛。",
  "catchphrases": ["钱收了，事办妥。"],
  "vocabulary": ["信用点", "轨道", "契约"]
}
```

### 7.4 soul_state.json 格式

```json
{
  "arc_stage": "起点",
  "current_goal": "在涅克瑟斯星区获取下一份赏金契约。"
}
```

### 7.5 emotion_state.json 格式（PAD）

```json
{
  "pad": {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0},
  "stage": "stranger",
  "stats": {
    "total_rounds": 0,
    "positive_count": 0,
    "negative_count": 0
  },
  "legacy_score": 5.0
}
```

### 7.6 SQLite 表关系

```
users (1) ─────< (N) characters (1) ─────< (1) arcs
  │                                              │
  │                                              └──< arc_logs
  │
  ├──< conversations (按 user_id + character_key)
  ├──< session_logs
  └──< score_logs (每轮对话 1 条)
```

---

## 8. 项目运行方式

### 8.1 环境准备

#### 前置条件

1. **Python 3.12+**（Dockerfile 用 3.12-slim）
2. **本地 Ollama 服务**（默认 `http://localhost:11434`），并 pull 至少：
   - 对话模型：`qwen2.5:7b`（默认）
   - 分析模型：`deepseek-r1:8b`（默认）
   - 向量模型：`nomic-embed-text`（启用向量记忆时）
3. `.env` 文件（可从 `.env.example` 复制），至少设置：
   ```
   SECRET_KEY=你的随机密钥（如 python -c "import secrets;print(secrets.token_hex(32))"）
   DATABASE_URL=sqlite:///harness.db   # 或留空默认
   ```

#### 安装 Python 依赖

```bash
cd C:\Users\guang
pip install -r requirements.txt
```

### 8.2 CLI 对话（最快验证闭环）

```bash
python harness_core.py -c config.json
```

进入交互式对话：
- `/status`：查看引擎状态
- `/save`：手动保存状态
- `/stream`：切换 流式 / 非流式 输出
- `/exit`：退出并保存

### 8.3 CLI Demo 脚本

```bash
python cli_demo.py
```

### 8.4 Flask Web UI（多用户 + 管理后台）

#### 首次启动需创建管理员

```bash
python web_ui.py create-admin --username admin --password 你的密码
```

或交互式输入密码：
```bash
python web_ui.py create-admin
```

#### 启动 Web 服务

```bash
python web_ui.py run --host 127.0.0.1 --port 7860 --debug
```

打开浏览器：
| URL | 用途 |
|-----|------|
| http://127.0.0.1:7860/ | 用户端登录/对话 |
| http://127.0.0.1:7860/admin/ | **管理后台**（需 is_admin=True） |
| http://127.0.0.1:7860/memory | 用户角色记忆可视化 |
| http://127.0.0.1:7860/characters/create | 角色创建向导 |
| http://127.0.0.1:7860/health | 健康检查 |

### 8.5 FastAPI REST API（供 React/前端调用）

```bash
python run_api.py
```

文档地址：
| URL | 用途 |
|-----|------|
| http://127.0.0.1:8000/api/docs | **Swagger UI 交互式文档** |
| http://127.0.0.1:8000/api/openapi.json | OpenAPI 3.0 规范 |
| http://127.0.0.1:8000/api/health | 健康检查 |

主要 API 端点（需 JWT Bearer Token，先调 `/api/auth/login` 获取）：
```
POST /api/auth/register
POST /api/auth/login                  → {access_token, token_type}

GET  /api/characters                  # 角色列表
POST /api/characters                  # 创建角色
GET  /api/characters/{id}             # 角色详情
PUT  /api/characters/{id}             # 更新角色
DEL  /api/characters/{id}             # 删除角色

POST /api/chat/completions            # 同步对话
POST /api/chat/stream                 # SSE 流式对话

GET  /api/characters/{id}/arc         # 弧光状态
POST /api/characters/{id}/arc/progress

GET  /api/characters/{id}/memories    # 记忆列表
POST /api/characters/{id}/memories    # 新增记忆条
DEL  /api/characters/{id}/memories/{mid}
```

### 8.6 数据库初始化（单独调用）

```bash
python -c "from harness_core import init_database; init_database()"
```

或用 deploy 脚本：
```bash
python deploy/scripts/init_db.py
python deploy/scripts/init_admin.py   # 初始化管理员
```

### 8.7 压测模式

```bash
set HARNESS_STRESS_MODE=1
python harness_core.py
# 或设置环境变量后启动 API
```

压测模式自动：禁用合并分析 + 向量记忆，fact/arc 间隔设为 9999，关闭流式和热重载。

---

## 9. 配置说明

### 9.1 config.json（引擎层配置，9 个 section）

```json
{
  "paths": {
    "soul": "soul_state.json",
    "memory": "memory_state.json",
    "emotion": "emotion_state.json",
    "log_session": "logs/session_{session_id}.json"
  },
  "ollama": {
    "chat_model": "qwen2.5:7b",
    "analysis_model": "deepseek-r1:8b",
    "base_url": "http://localhost:11434/api/generate",
    "timeout": 300,
    "num_predict": 200,
    "max_retries": 2
  },
  "engine": {
    "stream": true,
    "fact_extract_interval": 3,
    "arc_update_interval": 3,
    "auto_save_interval": 5,
    "memory_max_rounds": 10,
    "recent_dialogue_rounds": 5,
    "relevant_facts_limit": 3,
    "hot_reload": true
  },
  "memory_extractor": {"num_predict": 150, "temperature": 0.3},
  "arc_updater":       {"num_predict": 120, "temperature": 0.2},
  "unified_analyzer":  {"enabled": true, "num_predict": 250, "temperature": 0.25},
  "emotion":           {"default_score": 5.0},
  "web":               {"host": "127.0.0.1", "port": 7860, "share": false},
  "embeddings": {
    "enabled": true,
    "model": "nomic-embed-text",
    "base_url": "http://localhost:11434/api/embeddings",
    "timeout": 60,
    "max_retries": 2
  },
  "characters": {"registry": "characters.json"}
}
```

### 9.2 关键配置调优建议

| 参数 | 默认 | 调优方向 |
|------|------|----------|
| `ollama.timeout` | 300s | 模型加载慢可加大 |
| `ollama.num_predict` | 200 | 长回复可加到 500–1000 |
| `engine.fact_extract_interval` | 3 | 高质量场景 1；省 CPU 场景 5–10 |
| `engine.arc_update_interval` | 3 | 剧情密集 1；日常闲聊 6–10 |
| `engine.recent_dialogue_rounds` | 5 | 长上下文感可设 8–10（注意 Token） |
| `engine.relevant_facts_limit` | 3 | 角色需要丰富背景可加至 5–8 |
| `unified_analyzer.enabled` | true | 关闭则 fact + arc 分开调用（多用一次 LLM） |
| `embeddings.enabled` | true | 关闭后长期记忆只有关键词匹配 |

### 9.3 Flask 配置（config.py + .env）

| 环境变量 | 必填 | 说明 |
|----------|------|------|
| `SECRET_KEY` | ✅ | Flask Session / CSRF 密钥，必须随机 |
| `DATABASE_URL` | ❌ | 默认 `sqlite:///harness.db`，可设 PostgreSQL |
| `HARNESS_DATA_DIR` | ❌ | 默认项目根目录，Docker 中为 `/app/data` |
| `HARNESS_STRESS_MODE` | ❌ | 设 1 启用压测模式 |
| `HARNESS_VERSION` | ❌ | 健康检查返回的版本号 |

### 9.4 FastAPI 配置（api/config.py + 环境变量）

Pydantic Settings：`API_SECRET_KEY`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`CORS_ORIGINS`、`DATABASE_URL`。

---

## 10. 部署方案

### 10.1 Docker Compose（三服务架构）

```
         ┌────────────────────────────────────────────┐
         │              nginx:alpine                   │
         │              :80 (可加 :443 SSL)            │
         │  / → Flask web  /api/* → FastAPI api       │
         └────────┬──────────────────────┬────────────┘
                  │                      │
         ┌────────▼──────┐    ┌─────────▼──────────┐
         │  web (Flask)  │    │   api (FastAPI)     │
         │  :7860        │    │   :8000             │
         │  gunicorn     │    │   uvicorn           │
         └────────┬──────┘    └─────────┬──────────┘
                  │                      │
                  └──────────┬───────────┘
                             │
                    harness-data 卷 (SQLite + JSON 角色数据)
```

#### 启动

```bash
# 1. 确认 .env 存在 SECRET_KEY
cp .env.example .env
# 编辑 SECRET_KEY

# 2. 构建并启动（注意：compose 默认 build context = .docker-build/）
#    如需使用项目根目录的 Dockerfile，请改 compose.yml 的 build.context
docker compose up -d --build

# 3. 查看健康
docker compose ps
docker compose logs web --tail=50

# 4. 进入容器初始化管理员
docker compose exec web python /app/deploy/scripts/init_admin.py

# 5. 访问
#   http://服务器IP/           → Web UI
#   http://服务器IP/api/docs   → FastAPI Swagger
```

#### compose.yml 服务说明

| 服务 | 端口暴露 | 命令 | 健康检查 |
|------|----------|------|----------|
| `web` | 内部 7860（nginx 反代） | `web`（entrypoint.sh 派发到 gunicorn） | /health 每 30s |
| `api` | 内部 8000（nginx 反代） | `api`（entrypoint.sh 派发到 uvicorn） | 依赖 web healthy |
| `nginx` | 宿主 80（可加 443） | 配置文件 deploy/nginx.http.conf | 无 |

额外可选服务（已在 compose.yml 注释）：
- `postgres:16-alpine`：替换 SQLite（高并发生产）
- `redis:7-alpine`：缓存 + 会话存储

### 10.2 多阶段 Dockerfile 解析

```
Stage 1: python:3.12-slim AS builder
  作用：安装 gcc/libffi 编译依赖 + pip install 到 /install 前缀
  产物：/install（纯 Python wheels + 编译扩展）

Stage 2: python:3.12-slim AS runtime
  作用：仅运行时，无编译器，体积小
  - COPY --from=builder /install /usr/local
  - 建立 uid=1000 的 harness 非 root 用户
  - 暴露 7860 + 8000
  - HEALTHCHECK：python deploy/healthcheck.py（请求 /health 端点）
  - ENTRYPOINT：deploy/entrypoint.sh
      CMD=web → gunicorn（多 worker WSGI）
      CMD=api → uvicorn（ASGI）
```

### 10.3 Nginx 配置

- `deploy/nginx.http.conf`：纯 HTTP 版本（开发 / 内网）
- `deploy/nginx.conf`：HTTPS 模板（需挂载证书目录，取消 compose.yml 注释启用）

反向代理规则：
- `/api/*` → `api:8000`（保留路径前缀，因为 FastAPI 本身有 /api）
- `/health` → `web:7860/health` 或 `api:8000/api/health`
- 其他 → `web:7860`
- SSE 长连接：`proxy_buffering off; proxy_cache off`（stream/chat 必设）

### 10.4 deploy/scripts

| 脚本 | 用途 |
|------|------|
| `init_db.py` | 容器启动时初始化数据库表 |
| `init_admin.py` | 交互式创建或提升管理员 |
| `backup_db.sh` | 备份 harness.db 到带时间戳的目录 |
| `restore_db.sh` | 从备份恢复 harness.db |

### 10.5 Supervisor（容器内可选，在 deploy/supervisor.conf）

可选：单个容器内用 supervisor 同时拉起 web + api，简化 compose（但不利于水平扩展）。

---

## 11. 测试与质量保证

### 11.1 测试套件（tests/，18 个文件）

| 测试文件 | 覆盖模块 |
|----------|----------|
| [test_e2e.py](file:///c:/Users/guang/tests/test_e2e.py) | 端到端：启动引擎 → 对话 → 后处理 |
| [test_api.py](file:///c:/Users/guang/tests/test_api.py) | FastAPI 路由（认证 / 角色 / 对话） |
| [test_auth.py](file:///c:/Users/guang/tests/test_auth.py) | 用户注册 / 登录 / JWT / 权限 |
| [test_admin.py](file:///c:/Users/guang/tests/test_admin.py) | 管理后台 CRUD / 权限 |
| [test_soul.py](file:///c:/Users/guang/tests/test_soul.py) | Soul 模型 / 加载 / 迁移 / 弧光应用 |
| [test_soul_layer.py](file:///c:/Users/guang/tests/test_soul_layer.py) | Soul core/state 分层读写 |
| [test_emotion.py](file:///c:/Users/guang/tests/test_emotion.py) | PAD 情绪分析 / 规则 / 衰减 / 阶段跃迁 |
| [test_memories.py](file:///c:/Users/guang/tests/test_memories.py) | Memory 读写 / FIFO / 事实入库 |
| [test_memory_viz.py](file:///c:/Users/guang/tests/test_memory_viz.py) | memory/ 可视化解析正确性 |
| [test_arc.py](file:///c:/Users/guang/tests/test_arc.py) | ArcUpdater / UnifiedAnalyzer 评估 |
| [test_scoring.py](file:///c:/Users/guang/tests/test_scoring.py) | 四维度规则评分 + 权重合计 |
| [test_safety.py](file:///c:/Users/guang/tests/test_safety.py) | 输入/输出过滤 + 审计日志 |
| [test_config.py](file:///c:/Users/guang/tests/test_config.py) | harness_config 默认/合并/校验 |
| [test_config_manager.py](file:///c:/Users/guang/tests/test_config_manager.py) | config_manager CRUD/备份 |
| [test_embeddings.py](file:///c:/Users/guang/tests/test_embeddings.py) | EmbeddingClient + cosine_similarity |
| [test_performance.py](file:///c:/Users/guang/tests/test_performance.py) | 性能排队 / 超时 / 拒绝 |
| [test_streaming.py](file:///c:/Users/guang/tests/test_streaming.py) | SSE 流格式 / 取消机制 |
| [test_deployment.py](file:///c:/Users/guang/tests/test_deployment.py) | Dockerfile 可构建、健康检查端点存活 |

### 11.2 运行测试

```bash
# 标准 unittest
python -m pytest tests/ -v

# 或单文件
python -m pytest tests/test_e2e.py -v
```

### 11.3 运行日志与诊断文件

| 文件 | 说明 |
|------|------|
| `logs/session_{id}.json` | 每次会话的完整执行轨迹（输入/回复/状态变更） |
| `scoring_error.log` | scoring 模块异常（LLM 评分失败等） |
| `memory_operations.log` | memory 模块操作日志 |
| `admin_actions.log` | 管理员后台操作审计 |
| `user_actions.log` | 用户端行为审计 |
| `migrate_characters.log` | 角色迁移日志 |
| `_diag_out.txt` / `_smoke_out.txt` / `_smoke_out2.txt` | 历史烟雾测试输出 |
| `harness-memory-flowchart.png` | 记忆架构图 |

### 11.4 质量内建机制

| 保障层 | 实现 |
|--------|------|
| **配置校验** | harness_config.validate_config() 在加载时强制校验数值范围 |
| **Fail-open 情绪** | PADEmotionManager 异常时回退默认值，不打断对话 |
| **Fallback 评分** | LLM 评分失败 → 规则评分；Flask DB 上下文缺失 → 独立 SQLite Session |
| **LLM JSON 容错** | 三段式解析（直接 JSON → ```json 包裹 → 兜底正则 + 验证） |
| **Arc 单向约束** | Soul.apply_narrative_update() 禁止弧光后退或跳阶段 |
| **去重记忆** | MemoryExtractor.filter_new_facts() 精确 + 子串双重过滤 |
| **取消生成** | threading.Event + 主动关闭 HTTP 连接 + best-effort `/api/cancel` |
| **性能排队** | performance.queue_manager 防止并发过载 |
| **安全网关** | 输入/输出双重审核 + 审计记录 |
| **数据隔离** | users/{uid}/ 独立目录 + DB 级 user_id FK + UNIQUE(user_id, character_key) |
| **自动化测试** | 18 个测试文件覆盖各模块 + e2e |

---

## 附录：快速索引表

| 我想找…… | 看哪个文件 |
|----------|------------|
| 引擎主循环 / 处理一条消息 | [harness_core.py](file:///c:/Users/guang/harness_core.py) → `process_message()` |
| 配置结构与默认值 | [harness_config.py](file:///c:/Users/guang/harness_config.py) → `DEFAULT_CONFIG` |
| 角色性格设定 | [soul/model.py](file:///c:/Users/guang/soul/model.py) |
| 记忆（短期 + 长期 + 向量） | [character_memory.py](file:///c:/Users/guang/character_memory.py) |
| 情绪（PAD 三维） | [emotion/manager.py](file:///c:/Users/guang/emotion/manager.py) |
| 弧光评估 | [arc_updater.py](file:///c:/Users/guang/arc_updater.py) + [unified_analyzer.py](file:///c:/Users/guang/unified_analyzer.py) |
| 对话模型调用（流式/取消） | [ollama_client.py](file:///c:/Users/guang/ollama_client.py) |
| 向量 embedding | [embeddings.py](file:///c:/Users/guang/embeddings.py) |
| 角色注册表与切换 | [character_manager.py](file:///c:/Users/guang/character_manager.py) |
| 对话质量评分 | [scoring/engine.py](file:///c:/Users/guang/scoring/engine.py) |
| 内容安全审核 | [safety/gateway.py](file:///c:/Users/guang/safety/gateway.py) |
| 性能排队与超时 | [performance/__init__.py](file:///c:/Users/guang/performance/__init__.py) → `run_inference()` |
| 数据库表结构 | [database/models.py](file:///c:/Users/guang/database/models.py) |
| Flask Web UI 入口 | [web_ui.py](file:///c:/Users/guang/web_ui.py) |
| Flask 应用工厂 + 路由注册 | [app/__init__.py](file:///c:/Users/guang/app/__init__.py) |
| 管理后台（角色/评分/记忆） | [admin/views/](file:///c:/Users/guang/admin/views/) |
| FastAPI 入口 + 路由 | [api/main.py](file:///c:/Users/guang/api/main.py) |
| FastAPI 认证/对话/角色/记忆路由 | [api/routes/](file:///c:/Users/guang/api/routes/) |
| Docker 构建 | [Dockerfile](file:///c:/Users/guang/Dockerfile) |
| Docker Compose 编排 | [docker-compose.yml](file:///c:/Users/guang/docker-compose.yml) |
| 部署操作步骤 | [DEPLOYMENT.md](file:///c:/Users/guang/DEPLOYMENT.md) |
| Python 依赖清单 | [requirements.txt](file:///c:/Users/guang/requirements.txt) |
| 架构汇报（含规划） | [Harness引擎进展与架构汇报.md](file:///c:/Users/guang/Harness%E5%BC%95%E6%93%8E%E8%BF%9B%E5%B1%95%E4%B8%8E%E6%9E%B6%E6%9E%84%E6%B1%87%E6%8A%A5.md) |

---

*文档结束。Code Wiki 由代码静态分析生成，所有链接指向 `C:\Users\guang\` 下的真实文件绝对路径，可直接 Ctrl+单击跳转。*
