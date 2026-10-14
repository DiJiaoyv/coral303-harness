# Harness

<p align="center">
<img src="https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/Coral%20logo.png" width="220">
</p>

<h2 align="center">Coral303</h2>

<p align="center">
一个用于构建长期存在型 AI 角色的持久化 AI Character Harness 框架，支持记忆连续性、人格一致性、情绪状态以及关系演化。
</p>


[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)


---

# 项目介绍

Harness（Coral303）是一个面向长期存在型 AI 角色的运行框架。

它旨在解决传统聊天机器人系统中的核心问题：

- 对话之间缺乏连续身份
- 长期记忆无法保持
- 角色人格容易漂移
- 情绪状态无法持续
- 关系发展无法累积


不同于传统 Chatbot 将每次对话视为独立请求，Harness 在用户与大型语言模型（LLM）之间加入了一套结构化运行层。

系统维护：

- 角色身份（Character Identity）
- 长期记忆（Long-term Memory）
- 情绪状态（Emotional State）
- 关系演化（Relationship Evolution）
- 叙事发展（Narrative Progression）
- 安全约束（Safety Constraints）
- 运行时评估（Runtime Evaluation）


目标是提供一个工程化基础，使 AI 角色能够在长期交互中保持稳定、一致和持续发展的行为。


---

# 核心功能


# Harness Engine

Harness Engine 是整个系统的核心运行控制器。

负责协调：

- 请求编排
- 上下文构建
- 角色切换
- 记忆整合
- LLM 生成
- 后处理
- 日志记录
- 质量评估


核心组件：

```
orchestrator.py
harness_core.py
context_builder.py
memory_writer.py
```


---

# Soul 系统

Soul 系统用于定义角色长期身份。

管理：

- 核心人格
- 身份结构
- 角色状态
- 叙事约束
- 状态迁移


目录：

```
soul/
```


---

# Memory 系统

Harness 提供多层记忆管理。


## 短期记忆

维护当前会话上下文。


## 长期记忆

包括：

- 原始记忆（Raw Memory）
- 语义记忆（Semantic Memory）
- 检索系统
- 基于 Embedding 的相似度搜索


目录：

```
memory/
```


---

# Emotion 情绪系统

情绪引擎采用 PAD 情绪模型。

支持：

- Pleasure（愉悦）
- Arousal（唤醒）
- Dominance（支配）
- 情绪衰减
- 情绪阶段变化


目录：

```
emotion/
```


---

# Relationship 关系系统

关系层用于模拟用户与角色之间的长期互动历史。


包括：

- Pair State
- Social Graph
- Relationship Migration


目录：

```
relationship/
```


---

# Arc 角色成长系统

Arc 系统用于管理角色长期叙事发展。


跟踪：

- 角色成长
- 叙事状态
- 长期行为变化


目录：

```
arc/
```


---

# Safety 安全系统

安全层提供运行时保护。


包括：

- 输入过滤
- 输出过滤
- Safety Gateway
- 审计记录


目录：

```
safety/
```


---

# 系统架构

Harness 使用五层架构设计：


<img src="https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/architecture.png" width="900">


```
交互层（Interaction Layer）

        ↓

控制层（Control Layer）

        ↓

认知层（Cognition Layer）

        ↓

执行层（Execution Layer）

        ↓

持久层（Persistence Layer）
```


## 交互层

用户入口：

- Flask Web UI
- REST API
- CLI


## 控制层

运行编排：

- Harness Engine
- Turn Processing
- Context Builder


## 认知层

角色智能：

- Soul
- Memory
- Emotion
- Relationship
- Arc


## 执行层

模型执行：

- Ollama 后端
- DeepSeek API 后端


## 持久层

数据存储：

- SQLite
- 角色状态
- 记忆状态
- 会话日志


---

# Web 界面

Harness 提供基于 Flask 的 Web UI。


## 登录页面


<img src="https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/web_login.png" width="900">


## 管理面板


<img src="https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/web_dashboard.png" width="900">


功能：

- 用户认证
- 角色管理
- 对话交互
- 记忆可视化
- 管理后台


运行：

```bash
python web_ui.py run
```


访问：

```
http://127.0.0.1:7860
```


---

# 安装


## 环境要求

推荐：

```
Python 3.12
```

支持：

```
Python >=3.11
```


安装依赖：

```bash
pip install -r requirements.txt
```


---

# LLM 后端


Harness 支持多种语言模型后端。


## DeepSeek 云端 API


评估实验使用：

```
deepseek-chat
```


API 地址：

```
https://api.deepseek.com/v1/chat/completions
```


实验参数：

```
temperature = 0.7
```


## Ollama

同时支持本地推理后端。

默认开发环境可使用 Ollama。

评估实验使用 DeepSeek 云端 API。


---

# 快速开始


克隆项目：

```bash
git clone https://github.com/DiJiaoyv/coral303-harness.git
```


进入目录：

```bash
cd coral303-harness
```


安装依赖：

```bash
pip install -r requirements.txt
```


配置环境变量：

```
DEEPSEEK_API_KEY=your_key
```


启动：

```bash
python web_ui.py run
```


打开：

```
http://127.0.0.1:7860
```


---

# Evaluation 评估


## 100 轮角色偏移测试


该测试用于评估 AI 角色在长期持续交互中的一致性。


<img src="https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/Evaluation.png" width="900">


## 实验设置


模型：

```
DeepSeek-chat
```


温度：

```
0.7
```


---

## Baseline LLM


定义：

```
DeepSeek-chat

+

Kaspar 角色 System Prompt

+

完整对话历史


（无 Harness 模块介入）
```


---

## Harness Engine + LLM


定义：

```
DeepSeek-chat

+

Harness Engine

+

Memory

+

Soul

+

Emotion

+

Arc

+

Safety

+

Scoring
```


---

# 实验结果


| 指标 | Baseline | Harness |
|---|---:|---:|
| 人格一致性 Persona Consistency | 8.82 | 9.00 |
| 记忆准确性 Memory Accuracy | 6.55 | 7.09 |
| 关系连续性 Relationship Continuity | 7.45 | 7.91 |
| 情绪一致性 Emotional Consistency | 8.82 | 9.00 |


实验成本：

```
输入 Token: ~411k

输出 Token: ~14k

成本: ~$0.23
```


---

# 项目结构


```
coral303-harness/

├── app/
├── admin/
├── api/

├── harness_core.py
├── orchestrator.py

├── soul/
├── memory/
├── emotion/
├── relationship/
├── arc/

├── database/
├── safety/
├── scoring/

├── docs/
├── tests/
├── deploy/

├── requirements.txt
├── config.example.yaml
├── web_ui.py
└── LICENSE
```


---

# License


本项目采用 Apache License 2.0 开源协议。


详细信息请查看：

```
LICENSE
```
