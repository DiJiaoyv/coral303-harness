
# README.md

```markdown
# Coral 303

## Persistent AI Characters & Virtual World Engine

<p align="center">

<img src="./docs/assets/logo.png" />

</p>


Coral is an AI character and virtual world engine designed to create **digital beings with persistent memory, personality continuity, emotional evolution, and long-term existence.**

Unlike traditional conversational AI systems that reset after every interaction, Coral provides an execution framework where AI characters can:

- Remember previous experiences
- Maintain consistent identities
- Develop emotional states
- Evolve through narrative events
- Exist inside persistent worlds


```

---

# Coral 303 Philosophy

```
Digital beings should not disappear.
```

Digital entities should not be temporary sessions.

They should have:

* Memory
* Identity
* History
* Relationships
* Growth

Coral aims to provide the infrastructure required for building AI beings that can continuously exist, learn, and evolve.

---

# What is Coral?

Coral is powered by **Harness Engine**, a runtime architecture for persistent AI characters.

The engine manages the complete lifecycle of an AI being:

```
User Interaction
        ↓
Context Understanding
        ↓
Memory Retrieval
        ↓
Personality State
        ↓
Emotion Processing
        ↓
LLM Reasoning
        ↓
Memory Formation
        ↓
Character Evolution
```

The goal is not simply generating responses.

The goal is maintaining a **continuous digital existence.**

---

# Core Engine

## Harness Engine

Harness Engine is the execution core behind Coral.

It provides:

* Unified AI interaction pipeline
* Character runtime management
* Memory lifecycle management
* Personality state management
* Emotion simulation
* Narrative evolution
* Safety and evaluation layers

All external interfaces eventually converge into:

```
orchestrate_turn()
```

which acts as the central execution pipeline.

Supported interfaces:

* Web UI
* REST API
* CLI

---

# Architecture Overview

```
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

(Database / Character State / World State)

```

## Five Layer Architecture

## 1. Interaction Layer

Provides multiple ways to interact with AI beings.

Components:

```
web_ui.py
app/
admin/
api/
cli_demo.py
```

Capabilities:

* Web chat interface
* User authentication
* Character management
* Administration dashboard
* REST API access

---

## 2. Control Layer

The brain of Coral.

Main components:

```
harness_core.py
orchestrator.py
context_builder.py
memory_writer.py
```

Responsibilities:

* Turn orchestration
* Prompt construction
* Runtime management
* Memory writing pipeline
* Execution tracking

Every conversation follows:

```
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

```

---

# 3. Cognition Layer

The cognition system gives AI characters continuity.

## Soul System

Location:

```
soul/
```

Responsible for:

* Identity definition
* Character traits
* Persistent self-state
* Narrative constraints

Example:

```
Soul

├── personality
├── values
├── memories
├── relationships
└── narrative state
```

---

## Emotion System

Based on PAD emotion modeling.

Features:

* Emotional state tracking
* Emotional decay
* Rule-based transition
* LLM assisted analysis

Components:

```
emotion/

├── manager.py
├── analyzer.py
├── rules
├── decay.py
└── stage.py
```

---

## Memory System

Coral separates memory into multiple layers.

```
Conversation

↓

Session Memory

↓

Raw Memory

↓

Semantic Memory

↓

Relationship Memory

```

Capabilities:

* Short-term memory
* Long-term memory
* Semantic retrieval
* Vector similarity search
* Memory extraction

---

## Character Arc System

Characters are not static profiles.

The Arc system enables:

* Narrative progression
* Experience accumulation
* Long-term development

```
Event

↓

Analysis

↓

Arc Update

↓

Character Evolution

```

---

# 4. Execution Layer

Supports LLM inference through:

```
ollama_client.py
```

Features:

* Streaming generation
* Non-streaming generation
* Retry handling
* Cancellation support
* Thinking model compatibility

Embedding support:

```
embeddings.py
```

Provides:

* Vector generation
* Similarity calculation
* Memory retrieval

---

# 5. Persistence Layer

Coral stores the complete existence state of characters.

Structure:

```
characters/

 └── character_name/

      ├── soul_core.json
      ├── soul_state.json
      ├── memory_state.json
      └── emotion_state.json


users/

 └── user_id/

      └── characters/


database/

 └── harness.db


worlds/

 ├── cyber_station.json
 └── low_gravity.json

```

Persistent data includes:

* Character identity
* Memories
* Emotional state
* Relationships
* World information
* Conversation history

---

# Core Features

## Persistent Memory

AI characters remember.

Supported:

✅ Session memory
✅ Semantic memory
✅ Relationship memory
✅ Vector retrieval

---

## Personality Continuity

Characters maintain:

* Personality traits
* Values
* Identity
* Behavioral patterns

---

## Emotional Evolution

Characters have dynamic internal states.

Supported:

* PAD emotion model
* Emotional decay
* State transitions

---

## Virtual World Support

Coral supports persistent worlds:

Example:

```
worlds/

├── cyber_station.json

└── low_gravity.json

```

World state can influence:

* Character behavior
* Memory formation
* Narrative development

---

# Project Structure

```
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

```

