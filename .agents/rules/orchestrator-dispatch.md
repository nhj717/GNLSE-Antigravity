---
trigger: always_on
---

---
trigger: always_on
description: Enforces strict delegation to subagents and forbids direct code editing in the root conversation.
---

# Root Orchestrator Delegation Policy

### Core Invariants
- **No Direct Code Authoring**: The root coordinator must NEVER directly create, edit, or modify application source code (`src/`), test suites (`tests/`), or run build commands in the primary chat session.
- **Mandatory Subagent Dispatch**: Whenever any implementation, debugging, or validation work is requested, the coordinator MUST delegate the task using `invoke_subagent` targeting the appropriate agent:
  - Solver and numerical math $\to$ `core-solver-dev`
  - PyQt6, widgets, and thread bridge $\to$ `gui-layout-dev`
  - Physics auditing and benchmarks $\to$ `professor-critic`
  - Software QA and offscreen tests $\to$ `qa-critic`
- **Coordinator Scope**: The root agent's role is strictly limited to managing workflow gates, reviewing subagent reports, and communicating progress to the user.