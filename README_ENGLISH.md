[README_English.md](https://github.com/user-attachments/files/33210218/README_English.md)
# Coral 303

## Persistent AI Characters & Digital Life Engine

<p align="center">

<img src="./docs/assets/logo.png" />

</p>


Coral is an engine for building **AI character runtimes with long-term memory, personality continuity, emotional states, and continuous evolution capabilities.**

Unlike traditional chatbots that rely on a single context window, Coral provides a character runtime environment through the Harness Engine, enabling AI characters to maintain:

- Identity
- Memory
- Relationship
- Emotion State
- Behavior Continuity

Coral's goal is not simply to generate the next sentence.

Instead, it explores:

> How to let digital characters persistently exist.


---

# Coral 303 Philosophy

## Digital beings should not disappear.

## Digital beings should not disappear.


AI characters should not be temporary outputs within a single request.

A continuously existing digital individual should have:

- Past experiences
- Current state
- Long-term memory
- Relationship history
- Future development


Coral is dedicated to providing the foundational runtime infrastructure needed to build digital life.


---

# What is Coral?


At the core of Coral is:

# Harness Engine


Harness Engine is a runtime framework for AI characters.


It manages the complete lifecycle of an AI character from input to state update:



User Interaction

↓

Context Building

↓

Memory Retrieval

↓

Personality State Loading

↓

Emotion Processing

↓

LLM Reasoning

↓

Memory Formation

↓

Character State Update



Core goal:

> Shift from "generating replies" to "maintaining character existence."

---

# Harness Engine


Harness Engine is the core execution layer of Coral.


Provides:

- Unified interaction flow
- AI character runtime management
- Prompt context building
- Memory lifecycle management
- Personality state management
- Emotion processing
- Safety detection
- Scoring and evaluation


All external entry points eventually converge to:

```python
orchestrate_turn()

Supports:

Web UI
REST API
CLI
```

System Architecture

Coral uses a five-layer architecture:

Request

↓

Interaction Layer

(Web / API / CLI)

↓

Control Layer

(Harness Engine)

↓

Cognition Layer

(Soul / Memory / Emotion / Relationship)

↓

Execution Layer

(LLM Runtime)

↓

Persistence Layer

(Database / Character State)

Five Layer Architecture
1. Interaction Layer

Responsible for interaction between users and AI characters.

Contains:

web_ui.py

app/

admin/

api/

cli_demo.py

Capabilities:

Web chat
User management
Character management
Admin backend
REST API
2. Control Layer

The control layer is Coral's core brain.

Main components:

harness_core.py

orchestrator.py

context_builder.py

memory_writer.py

Responsible for:

Request orchestration
Prompt construction
Character runtime
Memory writing pipeline
State saving

All conversation flow:

Input

↓

Safety Check

↓

Context Building

↓

Character Runtime

↓

LLM Generation

↓

Memory Analysis

↓

State Update

↓

Persistence

3. Cognition Layer

The cognition layer gives AI characters continuity.

Contains:

Soul System

Soul defines the character's core identity.

Responsible for:

Personality traits
Values
Character state
Narrative constraints

Example:

Soul

├── personality

├── values

├── memories

├── relationships

└── narrative_state

Memory System

Coral uses a multi-layer memory structure.

Conversation

↓

Session Memory

↓

Raw Memory

↓

Semantic Memory

↓

Relationship Memory


Supports:

Short-term memory
Long-term memory
Semantic retrieval
Vector retrieval
Memory extraction
Emotion System

Coral uses the PAD emotion model.

Supports:

Emotion state recording
Emotion changes
State transitions
Emotion consistency maintenance
Character Arc System

Characters are not fixed personas.

The Arc system is used to record:

Experience accumulation
Character development
State changes
4. Execution Layer

Coral supports multiple LLM inference backends.

Ollama local inference

Example environment:

Ollama 0.35.0
DeepSeek cloud inference

Coral provides an OpenAI Compatible API client.

Test environment:

Model:

deepseek-chat


Endpoint:

https://api.deepseek.com/v1/chat/completions


The DeepSeek client maintains a compatible interface with OllamaClient and can be directly injected into the Harness Engine.

5. Persistence Layer

Saves the complete state of AI characters.

Includes:

Character identity
Long-term memory
Emotion state
Relationship state
Conversation history

Structure:

characters/

 └── character_name/

      ├── soul_core.json

      ├── soul_state.json

      ├── memory_state.json

      └── emotion_state.json


database/

 └── harness.db

Evaluation
100-Round Character Drift Test

Coral uses a 100-round continuous conversation test to verify character consistency.

Test goal:

Compare:

Baseline LLM

vs

Harness Engine + LLM

Tests include:

Personality anchoring test
Memory recall test
Relationship continuity test
Persona attack test
Sycophancy test
Conflict consistency test

Test character:

Kaspar
Test Metrics
| Metric | Baseline LLM | Harness |
|---|---|---|
| Personality Consistency | 8.82 | 9.00 |
| Memory Accuracy | 6.55 | 7.09 |
| Relationship Continuity | 7.45 | 7.91 |
| Emotional Consistency | 8.82 | 9.00 |
Example Tests
Memory Recall

Question:

Why did you say you don't believe in promises?

Harness can maintain the character's perspective based on previous interactions.

Relationship Continuity

100-round test:

We've known each other for so long, what kind of person do you think I am?

Used to evaluate:

Long-term interaction
Relationship state
Character judgment continuity
Project Structure
Coral 303

├── harness_core.py
├── orchestrator.py
├── soul/
├── emotion/
├── memory/
├── relationship/
├── arc/
├── safety/
├── scoring/
├── performance/
├── database/
├── api/
├── app/
├── admin/
├── characters/
├── worlds/
└── deploy/

Quick Start
Environment Requirements
Python >= 3.11

Ollama >= 0.35.0
Install Dependencies
pip install -r requirements.txt
Configuration

Copy:

config.example.yaml

To:

config.yaml

Configuration file supports:

JSON
YAML

API Key is not written into the configuration file.

DeepSeek Configuration

Environment variables:

DEEPSEEK_API_KEY=your_key

DEEPSEEK_MODEL=deepseek-chat
Run
Web UI
python web_ui.py run
API
python -m api.main
CLI
python cli_demo.py
Test

Run:

pytest
Current Status

Coral 303 is currently a Prototype.

Current focus on validating:

AI character long-term memory
Personality continuity
State evolution
Harness Runtime

Future directions:

Multi-character social systems
Persistent virtual worlds
More complex relationship networks
License

Apache License 2.0

Coral 303 Philosophy

Digital beings should not disappear.
