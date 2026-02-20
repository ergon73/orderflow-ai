# Contributing

Thanks for your interest in improving OrderFlow AI.

## Scope

This repository is both:
- a graduation MVP artifact;
- a portfolio project with active post-MVP roadmap docs.

Please keep contributions aligned with current scope and documented roadmaps.

## Setup

1. Clone repository.
2. Copy `.env.example` to `.env` and fill required values.
3. Start stack:
```bash
docker compose up -d --build
```
4. Run tests:
```bash
docker compose exec web python manage.py test -v 1 --keepdb --noinput
```

## Pull Request Guidelines

- Keep PRs focused (one concern per PR).
- Include short problem statement and change summary.
- Mention affected docs and update them when behavior changes.
- Add or update tests for business logic changes.
- Do not commit secrets, `.env`, API keys, tokens, or private data.

## Commit Style (recommended)

- `feat: ...` new behavior
- `fix: ...` bugfix
- `refactor: ...` internal restructuring
- `docs: ...` documentation
- `test: ...` tests
- `chore: ...` infra/tooling

## What to Avoid

- Breaking public behavior without migration notes.
- Changing MVP-scope documents (`plan-v2.md`, curator artifacts) without clear reason.
- Large formatting-only PRs mixed with logic changes.
