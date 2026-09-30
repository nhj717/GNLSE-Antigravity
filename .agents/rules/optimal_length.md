---
description: Enforces optimal length guidelines, word budgets, and lean structure across workspace rules, subagent persona files, and YAML frontmatter descriptions to ensure fast context scanning and prevent bloat.
---

# Optimal Length Guidelines

All agent configuration, rule, and persona files must adhere to strict conciseness budgets:

## Length & Scope Budgets

| File Type | Ideal Length | Focus |
|---|---|---|
| `description:` (YAML Frontmatter) | 20–40 words | Trigger conditions and core domain keywords. |
| Rules (`.agents/rules/*.md`, `AGENTS.md`) | 100–300 words | Project invariants, typing standards, and forbidden actions. |
| Subagent Personas (`.agents/agents/*.md`, `.agent/*.md`) | 150–400 words | Role scope, tool restrictions, and pass/fail exit criteria. |

## Formatting Constraints
- **Lean Structure**: Organize content into a concise bulleted checklist under 2 to 3 headings maximum.
- **No Fluff**: Exclude narrative prose, tutorial explanations, and repetitive background context. Focus strictly on hard constraints.
- **One-Screen Rule**: If a file requires more than one screen of scrolling to read, trim it immediately to its operational requirements.
