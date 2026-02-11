# Documentation style guide

This repository aims for a NetBox-like style: clear, technical, and written for working engineers.

## Voice and tone

- **Direct and technical.** Prefer short sentences and specific nouns.
- **Narrative flow.** Describe how the system behaves, not how the doc was produced.
- **Calm, professional tone.** Avoid hype.
- **Assume competence, not context.** Define repo-specific terms once, then reuse them.

## Page structure (default)

Use a consistent, scan-friendly layout.

1. **Title**
2. **1–3 sentence intro**
   - What this page covers and who it’s for.
3. **Deep dives / Related docs** (optional but common)
   - Links to more detailed pages.
4. **Main content**
   - Prefer sections that match user intent: “Quickstart”, “How it works”, “Configuration”, “Common workflows”, “Troubleshooting”.
5. **Next steps** (optional)
   - Where to go next.

## Headings and conventions

- Prefer **verb-led** headings when describing procedures: “Run migrations”, “Regenerate the client”.
- Prefer **intent-led** headings when describing concepts: “How requests flow”, “Auth model”.
- Use numbered steps when order matters.
- Keep headings short; avoid long parentheticals.

## Cross-linking

- Treat the numbered IA pages in `docs/` as **entrypoints**.
- Link to deep dives instead of duplicating content.
- Use readable link text:
  - Good: “Deployment guide” → `docs/deployment/README.md`
  - Avoid: ``docs/deployment/README.md``

## Link formatting rules

- Use markdown links: `[Deployment guide](deployment/README.md)`.
- Use relative paths that work in GitHub and typical markdown renderers.
- Keep code formatting for:
  - commands (`make check`)
  - environment variables (`NEXT_PUBLIC_API_URL`)
  - literal file paths when you mean “this exact file on disk” (not as a navigational link)

## Avoided phrases (and what to use instead)

Avoid doc-meta language:

- Avoid: “evidence basis”, “evidence anchors”, “this page is intentionally…”
- Prefer:
  - “Source of truth: …” (only when it matters)
  - “See also: …”
  - Just link the file or section.

Avoid hedging:

- Avoid: “likely”, “probably”, “should” (unless it’s a policy decision)
- Prefer: state what the code does, and point to the file.

## Preferred patterns

- **Start here** blocks for role-based entry.
- **Common workflows** sections with copy/paste commands.
- **Troubleshooting** sections with symptoms → checks → fixes.
- **Footguns** called out explicitly when they can cause outages or confusing behavior.

## Example rewrites

### Example 1: remove doc-meta “evidence” language

Before:
> Evidence basis: consolidated from repo root `README.md`, `.github/workflows/ci.yml`, `Makefile`.

After:
> This page describes the development workflow that matches CI: setup, checks, and common local loops.

### Example 2: prefer readable links over code-formatted paths

Before:
- See `docs/deployment/README.md` for deployment.

After:
- See the [Deployment guide](deployment/README.md).

### Example 3: replace “first pass” filler with a clear scope boundary

Before:
- Non-goals (first pass)

After:
- Out of scope
