# Aysel A2A Protocol Endpoint

Python backend that exposes the Aysel multi-agent research system (market gap
analysis + global financing systems, with Google Search and URL-context
sub-agents built on Google ADK / Vertex AI Gemini) via the Google A2A protocol.

## Quick start (dev)

```bash
cp .env.example .env            # fill in GCP credentials
pip install -e ".[dev]"
uvicorn api.boot:app --reload   # http://localhost:8000
```

Run tests (no GCP credentials needed; a scripted agent runner is used):

```bash
python -m pytest
```

Full stack with Redis + Celery worker:

```bash
docker compose up --build
```

## Layout

- `api/` — FastAPI app, JSON-RPC dispatcher, auth, config
- `services/` — A2A handler, task state machine, event bus (SSE), agent runner
- `agents/` — ADK agent definitions (lazy imports; see docs/a2a-protocol.md)
- `models/`, `db/`, `schemas/` — ORM, async DB layer, Pydantic protocol models
- `celery_worker/` — background execution (USE_CELERY=true)
- `tests/`, `docs/a2a-protocol.md`

## Key design decisions

See `docs/a2a-protocol.md` for the full list of protocol fixes applied vs. the
original design doc (HTTP 200 JSON-RPC errors, Redis-backed event bus,
subscribe-before-run SSE, cancel from input-required, tz-aware timestamps).
