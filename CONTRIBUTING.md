# Contributing to OpenClaw Mission Control

Thanks for your interest in improving Mission Control.

This repo welcomes contributions in three broad categories:

- **Issues**: bug reports, feature requests, and design discussions
- **Documentation**: improvements to clarity, correctness, onboarding, and runbooks
- **Code**: fixes, features, tests, and refactors

## Where to start

- Docs landing page: [Docs landing](./docs/README.md)
- Development workflow: [Development workflow](./docs/03-development.md)
- Testing guide: [Testing guide](./docs/testing/README.md)

## Filing issues

When opening an issue, please include:

- What you expected vs what happened
- Steps to reproduce (commands, env vars, links)
- Logs and screenshots where helpful
- Your environment (OS, Docker version, Node/Python versions)

## Pull requests

### Branching hygiene (required)

Create feature branches from the latest `origin/master` to avoid unrelated commits in PRs:

```bash
git fetch origin
git checkout master
git reset --hard origin/master
git checkout -b <branch-name>
```

If you accidentally based your branch off another feature branch, fix it by cherry-picking the intended commits onto a clean branch and force-pushing the corrected branch (or opening a new PR).

### Expectations

- Keep PRs **small and focused** when possible.
- Include a clear description of the change and why it’s needed.
- Add/adjust tests when behavior changes.
- Update docs when contributor-facing or operator-facing behavior changes.

### Local checks

From repo root, the closest “CI parity” command is:

```bash
make check
```

If you’re iterating on a specific area, the Makefile also provides targeted commands (lint, typecheck, unit tests, etc.). See `make help`.

## Docs contribution guidelines

- The numbered pages under `docs/` are **entrypoints**. Prefer linking to deeper pages instead of duplicating large blocks of content.
- Use concise language and concrete examples.
- When documenting operational behavior, call out risk areas (secrets, data loss, migrations).

## Security and vulnerability reporting

If you believe you’ve found a security vulnerability:

- **Do not** open a public issue.
- Prefer GitHub’s private reporting flow:
  - https://github.com/abhi1693/openclaw-mission-control/security/advisories/new

If that’s not available in your environment, contact the maintainers privately.

## Code of conduct

If this repository adopts a Code of Conduct, we will link it here.

## License

By contributing, you agree that your contributions will be licensed under the MIT License. See [`LICENSE`](./LICENSE).
