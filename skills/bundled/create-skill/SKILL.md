---
name: create-skill
description: "Use after a multi-step procedure that will recur: capture it as a skill."
version: 1.0.0
tags: [learning, skills]
---

# Create a skill from experience

When you finish a non-trivial procedure the user may repeat:

1. Distill the steps into a short playbook (trigger, steps, pitfalls).
2. Call `create_skill` with a kebab-case name and clear description.
3. Keep the body under ~80 lines; link tools by name, not prose fluff.
4. Prefer updating an existing skill over duplicating one.
