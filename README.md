# Harness

<p align="center">
<img src="https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/Coral%20logo.png" width="220">
</p>

<h2 align="center">Coral303</h2>

<p align="center">
A Persistent AI Character Harness for building long-lived AI characters with memory, personality continuity, emotional states, and evolving relationships.
</p>


[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)


---

# Overview

Harness (Coral303) is a persistent AI character runtime framework designed to create long-lived AI beings with continuous identity, memory, emotional states, and relationship evolution.

Unlike traditional chatbot systems that treat every conversation as an isolated interaction, Harness introduces a structured runtime layer between users and Large Language Models (LLMs).

The system maintains:

- Character identity
- Long-term memory
- Emotional state
- Relationship evolution
- Narrative progression
- Safety constraints
- Runtime evaluation


The goal is to provide an engineering foundation for persistent AI characters that can maintain consistency across extended interactions.


---

# Core Features


## Harness Engine

Harness Engine is the central runtime controller of the system.

It coordinates:

- Request orchestration
- Context construction
- Character switching
- Memory integration
- LLM generation
- Post-processing
- Logging
- Evaluation


Core components:

```
orchestrator.py
harness_core.py
context_builder.py
memory_writer.py
```


---

# Soul System

The Soul system defines persistent character identity.

It manages:

- Core personality
- Identity schema
- Character state
- Narrative constraints
- State migration


Directory:

```
soul/
```


---

# Memory System

Harness provides multi-layer memory management.


## Short-term Memory

Maintains current conversation context.


## Long-term Memory

Includes:

- Raw memory
- Semantic memory
- Retrieval system
- Embedding-based similarity search


Directory:

```
memory/
```


---

# Emotion System

The emotion engine uses a PAD-based emotional model.

Features:

- Pleasure
- Arousal
- Dominance
- Emotion decay
- Emotion stage transition


Directory:

```
emotion/
```


---

# Relationship System

The relationship layer models long-term interaction history between users and characters.

Includes:

- Pair state
- Social graph
- Relationship migration


Directory:

```
relationship/
```


---

# Arc System

The Arc system manages character narrative progression.

It tracks:

- Character development
- Narrative state
- Long-term behavioral evolution


Directory:

```
arc/
```


---

# Safety System

The safety layer provides runtime protection.

Includes:

- Input filtering
- Output filtering
- Safety gateway
- Auditing


Directory:

```
safety/
```


---

# Architecture

Harness follows a five-layer architecture:


![Harness Architecture](https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/architecture.png)

Figure: Five-layer architecture of Harness.

```
Interaction Layer

        ↓

Control Layer

        ↓

Cognition Layer

        ↓

Execution Layer

        ↓

Persistence Layer
```


## Interaction Layer

User-facing interfaces:

- Flask Web UI
- REST API
- CLI


## Control Layer

Runtime orchestration:

- Harness Engine
- Turn processing
- Context building


## Cognition Layer

Character intelligence:

- Soul
- Memory
- Emotion
- Relationship
- Arc


## Execution Layer

LLM execution:

- Ollama backend
- DeepSeek API backend


## Persistence Layer

Data storage:

- SQLite
- Character states
- Memory states
- Session logs


---

# Web Interface

Harness provides a Flask-based Web UI.

## Login Interface


![Harness Login](https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/web_login.png)

## Dashboard


![Harness Dashboard](https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/web_dashboard.png)

Features:

- User authentication
- Character management
- Chat interaction
- Memory visualization
- Administration dashboard


Run:

```bash
python web_ui.py run
```


Open:

```
http://127.0.0.1:7860
```


---

# Installation


## Requirements

Recommended:

```
Python 3.12
```

Supported:

```
Python >=3.11
```


Install dependencies:

```bash
pip install -r requirements.txt
```


---

# LLM Backend


Harness supports multiple LLM backends.


## DeepSeek Cloud API

The evaluation experiments use:

```
deepseek-chat
```


API endpoint:

```
https://api.deepseek.com/v1/chat/completions
```


Experiment configuration:

```
temperature = 0.7
```


## Ollama

## Ollama

Local inference backend is also supported.

The default development configuration uses Ollama, while evaluation experiments were conducted with DeepSeek Cloud API.
---

# Quick Start


Clone repository:

```bash
git clone https://github.com/DiJiaoyv/coral303-harness.git
```


Enter project:

```bash
cd coral303-harness
```


Install:

```bash
pip install -r requirements.txt
```


Configure environment variables:

```
DEEPSEEK_API_KEY=your_key
```


Run:

```bash
python web_ui.py run
```


Open:

```
http://127.0.0.1:7860
```


---

# Evaluation


## 100-Round Character Drift Test


The evaluation measures whether an AI character can maintain consistency during long-term interaction.

![Character Drift Evaluation](https://raw.githubusercontent.com/DiJiaoyv/coral303-harness/main/docs/Evaluation.png)
## Experimental Setup


Model:

```
DeepSeek-chat
```


Temperature:

```
0.7
```


---

## Baseline LLM


Definition:

```
DeepSeek-chat

+

Kaspar character system prompt

+

Full conversation history


(No Harness modules)
```


---

## Harness Engine + LLM


Definition:

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

# Results


| Metric | Baseline | Harness |
|---|---:|---:|
| Persona Consistency | 8.82 | 9.00 |
| Memory Accuracy | 6.55 | 7.09 |
| Relationship Continuity | 7.45 | 7.91 |
| Emotional Consistency | 8.82 | 9.00 |


Experiment cost:

```
Input tokens: ~411k

Output tokens: ~14k

Cost: ~$0.23
```


---

# Project Structure


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

├── tests/
├── deploy/

├── requirements.txt
├── config.example.yaml
├── web_ui.py
└── LICENSE
```


---

# License


This project is licensed under the Apache License 2.0.


See:

```
LICENSE
```

for details.
