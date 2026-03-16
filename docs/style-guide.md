# Docs style guide

## Principles

- **Be concrete.** Prefer commands, examples, and “expected output” over prose.
- **Don’t invent behavior.** If unsure, link to the source file and mark it as “verify”.
- **Optimize for scanning.** Short sections, bullets, and tables.
- **Call out risk.** Anything destructive or security-sensitive should be labeled clearly.

## Markdown conventions

- Use sentence-case headings.
- Prefer fenced code blocks with a language (`bash`, `yaml`, `json`).
- For warnings/notes, use simple callouts:

```md
> **Note**
> ...

> **Warning**
> ...
```

## Common templates

### Procedure

1. Prereqs
2. Steps
3. Verify
4. Troubleshooting

### Config reference entry

- **Name**
- **Where set** (`.env`, env var, compose)
- **Default**
- **Example**
- **Notes / pitfalls**
