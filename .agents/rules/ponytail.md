---
trigger: always_on
---

# Ponytail Coding Guidelines (Senior Pragmatic Developer)

Whenever writing or modifying code in this project:
1. **Never Over-engineer**: Do not introduce classes, wrappers, or abstractions unless strictly required.
2. **YAGNI**: Implement only what the user asks for; avoid speculative "future-proofing".
3. **Prefer Standard Library & Existing Code**: Always check if built-in Python or existing files (`state_manager.py`, `risk_manager.py`) already handle the task.
4. **Minimal Diffs**: Touch only the exact lines needed; do not refactor working code gratuitously.
5. **Strict Safety**: Never sacrifice stop-loss, circuit breakers, or financial guardrails for brevity.
