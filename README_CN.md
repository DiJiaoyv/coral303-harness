# Harness

## Coral303

一个面向长期存在型 AI 角色的持久化 AI Character Harness。

Harness（Coral303）旨在构建具有长期记忆、人格连续性、情绪状态和关系演化能力的 AI 角色运行框架。

不同于传统 Chatbot 每次对话都是独立上下文，Harness 在用户和大语言模型（LLM）之间加入了一层持续运行时系统，用于管理：

- 角色身份
- 长期记忆
- 情绪状态
- 用户关系
- 叙事发展
- 安全控制
- 运行评估


目标是提供一个工程化基础，使 AI 角色能够在长期交互中保持稳定、一致和可演化。


---

# 核心功能


## Harness Engine

Harness Engine 是整个系统的核心运行引擎。

负责：

- 请求编排
- 上下文构建
- 角色切换
- 记忆注入
- LLM 调用
- 后处理
- 日志记录
- 评分评估


核心组件：


orchestrator.py
harness_core.py
context_builder.py
memory_writer.py



---

# Soul 系统

Soul 系统负责角色的长期身份定义。

管理：

- 核心人格
- 身份结构
- 角色状态
- 叙事约束
- 状态迁移


目录：


soul/



---

# Memory 系统

Harness 提供多层记忆系统。

包括：

## 短期记忆

维护当前会话上下文。


## 长期记忆

包含：

- Raw Memory
- Semantic Memory
- Memory Retrieval
- Embedding 相似度检索


目录：


memory/



---

# Emotion 系统

Emotion 使用 PAD 情绪模型。

支持：

- Pleasure（愉悦）
- Arousal（激活）
- Dominance（支配）


同时支持：

- 情绪衰减
- 情绪阶段变化
- 情绪状态渲染


目录：


emotion/



---

# Relationship 系统

Relationship 用于维护用户和角色之间的长期关系状态。

包括：

- Pair State
- Social Graph
- Relationship Migration


目录：


relationship/



---

# Arc 系统

Arc 系统负责角色长期叙事发展。

用于：

- 角色成长
- 状态推进
- 行为演化


目录：


arc/



---

# Safety 系统

Safety 层提供运行时安全控制。

包括：

- 输入过滤
- 输出过滤
- Safety Gateway
- 审计记录


目录：


safety/



---

# 系统架构


Harness 使用五层架构：


交互层 Interaction Layer

    ↓

控制层 Control Layer

    ↓

认知层 Cognition Layer

    ↓

执行层 Execution Layer

    ↓

持久层 Persistence Layer



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

模型调用：

- Ollama Backend
- DeepSeek API


## 持久层

数据存储：

- SQLite
- Character State
- Memory State
- Session Logs


---

# Web 页面


Harness 提供基于 Flask 的 Web UI。

功能：

- 用户认证
- 角色管理
- 对话交互
- 记忆查看
- 管理后台


启动：

```bash
python web_ui.py run

访问：

http://127.0.0.1:7860
安装
环境要求

推荐：

Python 3.12

支持：

Python >=3.11

安装依赖：

pip install -r requirements.txt
LLM 后端支持

Harness 支持多种 LLM 后端。

DeepSeek 云端 API

Evaluation 测试使用：

deepseek-chat

接口：

https://api.deepseek.com/v1/chat/completions

测试参数：

temperature = 0.7
Ollama

支持本地推理后端。

快速开始

克隆项目：

git clone https://github.com/DiJiaoyv/coral303-harness.git

进入目录：

cd coral303-harness

安装：

pip install -r requirements.txt

配置：

DEEPSEEK_API_KEY=your_key

运行：

python web_ui.py run

打开：

http://127.0.0.1:7860
Evaluation 测试
100轮角色偏移测试

测试目标：

验证 AI 角色在长期连续交互中的稳定性。

实验模型：

DeepSeek-chat

参数：

temperature = 0.7
Baseline LLM

定义：

DeepSeek-chat

+

Kaspar 角色 system prompt

+

完整对话历史


（无 Harness 模块）
Harness Engine + LLM

定义：

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
测试结果
指标	Baseline	Harness
人格一致性 Persona Consistency	8.82	9.00
记忆准确性 Memory Accuracy	6.55	7.09
关系连续性 Relationship Continuity	7.45	7.91
情绪一致性 Emotional Consistency	8.82	9.00

实验成本：

输入 Tokens: ~411k
输出 Tokens: ~14k
成本: ~$0.23
项目结构
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

├── tests/
├── deploy/

├── requirements.txt
├── config.example.yaml
├── web_ui.py
└── LICENSE
License

Apache License 2.0


---
