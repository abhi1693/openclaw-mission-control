---
description: "Use when writing or editing Markdown documentation under docs. Covers sentence-case headings, concrete examples, procedure structure, and clear warnings for risky operations."
name: "Docs Writing"
applyTo: "docs/**/*.md, *.md"
---
# Docs Writing

- Keep docs concrete and scannable: prefer commands, examples, expected outcomes, short sections, and flat bullet lists over long narrative prose.
- Follow the repo docs style guide with sentence-case headings and fenced code blocks that include a language such as `bash`, `yaml`, or `json`.
- When documenting a procedure, structure it around prerequisites, steps, verification, and troubleshooting when that pattern fits the task.
- If behavior is uncertain, do not invent it. Link or point to the source of truth and mark the item for verification.
- Clearly label destructive, security-sensitive, or irreversible operations with a simple note or warning callout.
- Prefer placing new content in the most specific existing docs section under `docs/` instead of creating overlapping top-level guides.