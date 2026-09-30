# Autonomous Scientific Research & Engineering Panel — Agent Architecture

## Directory Structure

```text
.agents/
├── README.md                      # Architecture & agent lifecycle guide
├── agents/                        # Persistent subagent personas
│   ├── phd-researcher.md          # Literature & empirical constants
│   ├── theoretician.md            # PDE & operator splitting formulation
│   ├── professor.md               # Physics Gate: conservation & Hult 2007 audit
│   ├── core-solver-dev.md         # Pure solver engine & C++ acceleration
│   ├── gui-layout-dev.md          # PyQt6 layouts & throttled QThread bridge
│   └── qa-critic.md               # Software Gate: headless pytest-qt & thread audit
└── rules/
    └── optimal_length.md          # Conciseness & context efficiency rule
```

---

## Agent Roster & Domain Separation

| File | Subagent / Persona | Domain / Scope | Primary Deliverables |
|------|--------------------|----------------|----------------------|
| [`phd-researcher.md`](agents/phd-researcher.md) | **PhD Researcher** | Literature retrieval, constants, benchmark test cases | Physical parameters table, unit conversions, benchmark JSON configs |
| [`theoretician.md`](agents/theoretician.md) | **Theoretician** | PDE discretization, operator splitting, conservation laws | Frequency-domain GNLSE, RK4IP algorithm, S-SSFM, grid sizing rules |
| [`professor.md`](agents/professor.md) | **Professor (Physics Gate)** | Adversarial physics review, Hult 2007 empirical audit | Soliton N=1 invariant audit, Hult simulation comparison, Physics Gate GO/NO-GO |
| [`core-solver-dev.md`](agents/core-solver-dev.md) | **Core Solver Dev** | Numerical engine (`src/solver/`), C++ acceleration | Typed dataclass configs, generator stepping, pybind11 kernel with NumPy fallback |
| [`gui-layout-dev.md`](agents/gui-layout-dev.md) | **GUI & Concurrency Dev** | PyQt6 UI (`src/gui/`), concurrency bridge (`src/bridge/`) | Dockable workstation, pyqtgraph canvas, throttled worker ($\le 60\text{ FPS}$) |
| [`qa-critic.md`](agents/qa-critic.md) | **QA Critic (Software Gate)** | Adversarial software review, headless testing, concurrency | `QT_QPA_PLATFORM=offscreen pytest`, QThread lifecycle audit, Software Gate GO/NO-GO |

---

## Two-Phase Multi-Agent Architecture

```
                                ┌────────────────────────────────────────────────────────┐
                                │                       BLACKBOARD                       │
                                │   (GNLSE_THEORETICAL_SPEC.md & GUI_BLUEPRINT.md)       │
                                └───────────────────────▲─┬──────────────────────────────┘
                                                        │ │
                   ┌────────────────────────────────────┴─┼────────────────────────────────────┐
                   │                                      │                                    │
        [Phase 1: Theory & Spec]             [Phase 2: Parallel Dev]               [Phase 2: Dual Gates]
    ┌──────────────┴──────────────┐        ┌──────────────┴──────────────┐        ┌──────────────┴──────────────┐
    │ phd-researcher              │        │ core-solver-dev             │        │ Physics Gate (professor)    │
    │ theoretician                │        │ gui-layout-dev              │        │ Software Gate (qa-critic)   │
    └─────────────────────────────┘        └─────────────────────────────┘        └─────────────────────────────┘
```

### Bi-Cameral Adversarial Release Gate
Every release candidate must secure unanimous sign-off:
1. **Physics Gate (`professor`)**: Verifies SI unit conversions, Soliton $N=1$ analytical invariant ($\max |\Delta |A|^2| < 10^{-4}, \Delta E < 10^{-10}$), anti-aliasing suppression, and feature-by-feature empirical replication of the Johan Hult 2007 supercontinuum benchmark (`reference_data/benchmark_parameters.json`).
2. **Software Gate (`qa-critic`)**: Verifies headless execution (`QT_QPA_PLATFORM=offscreen pytest`), clean QThread termination/abort without leaks or crashes, event loop signal throttling ($\le 60\text{ FPS}$), and memory stability.

---

## Invoking Subagents

Subagents can be addressed directly in your workflows:
- *"Act as `core-solver-dev` to implement the generator-based stepping loop in `src/solver/engine.py`..."*
- *"Act as `gui-layout-dev` to construct the pyqtgraph spectral waterfall dock in `src/gui/`..."*
- *"Act as `professor` to run the simulator against Johan Hult 2007 Table 1 parameters and verify against reference figures..."*
- *"Act as `qa-critic` to run headless pytest-qt concurrency stress tests on the worker bridge..."*
