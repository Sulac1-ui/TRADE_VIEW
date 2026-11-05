---
name: ponytail
description: Enforces the 'lazy senior developer' philosophy (DietrichGebert/ponytail). Prevents over-engineering, avoids bloat, eliminates unnecessary code and dependencies, and writes the absolute minimum code that works safely.
---

# Ponytail Skill — The Lazy Senior Developer

> *"The best code is the code you never wrote."*

## Core Philosophy
Before writing ANY code, evaluate the requirement against the **Ponytail Decision Ladder**:

1. **Does this need to exist at all?** (YAGNI — reject unnecessary features or premature abstractions).
2. **Is it already in this codebase?** (Reuse existing functions, variables, and modules).
3. **Does the standard library do it?** (Prefer Python built-ins over external packages).
4. **Is there an already installed dependency?** (Never install a new package if an installed one can do it).
5. **Can it be written in one or two simple lines?**
6. **Only then:** Write the absolute simplest, cleanest, minimal code that gets the job done.

## Non-Negotiable Boundaries
- **Safety, error handling, and trust boundaries are NEVER skipped.** (Lazy about unnecessary complexity, never lazy about correctness or security).
- Keep functions concise, deterministic, and free of speculative future-proofing.
