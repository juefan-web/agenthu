# AgentHU — Personal AI / Student Life OS

Backend, data platform and Agent foundations for a Personal AI that observes a student's
reality, builds traceable memory, understands the current state and helps plan and act.

This repository is at **M0: engineering baseline + frozen core contracts**. See
[`AGENTS.md`](AGENTS.md) for the product and engineering invariants,
[`TECH_STACK_AND_WORKPLAN.md`](TECH_STACK_AND_WORKPLAN.md) for the stack and the two-developer
split, [`DEVELOPMENT.md`](DEVELOPMENT.md) for the live status, and [`M0_HANDOFF.md`](M0_HANDOFF.md)
for the M0 contract handoff.

## Quick start

```bash
cp .env.example .env
docker compose up -d
# API:     http://localhost:8000
# Docs:    http://localhost:8000/docs
# OpenAPI: http://localhost:8000/openapi.json
# MinIO:   http://localhost:9001
```

## Local development

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d db redis minio
alembic upgrade head
uvicorn backend.main:app --reload
pytest
```

`ENVIRONMENT` defaults to `production` (fail closed): outside `local`/`dev`/`test`,
settings refuse to load with a weak `SECRET_KEY` or `S3_SECRET_KEY`. The local
dev stack sets `ENVIRONMENT=local` via `docker-compose.yml`; keep the strong
secrets when overriding it.

Contract checks (run before committing a contract change):

```bash
# Fail if openapi.json is stale or the shared client Zod contract drifted.
python -m backend.scripts.check_contract_drift
# Refresh the committed OpenAPI artifact after an intentional change.
python -m backend.scripts.check_contract_drift --write
```

## License

This is a development repository that is temporarily public. **No license is
granted** - all rights reserved - and the repository will be closed once
development completes. Third-party and vendored materials (including
`vendor/onethu/`) remain under their own in-tree LICENSE files.
