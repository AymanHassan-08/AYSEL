# Alembic Migrations

Migrations are initialized and ready to use.

- Config: `alembic.ini` (project root)
- Environment: `models/migrations/env.py` — reads `DATABASE_URL` and converts
  async drivers to sync for migrations (`sqlite+aiosqlite://` -> `sqlite://`,
  `postgresql+asyncpg://` -> `postgresql+psycopg://`)
- Initial revision: `models/migrations/versions/*_initial_a2a_schema.py`

## Commands

```bash
# create/upgrade to latest
alembic upgrade head

# generate a new revision after model changes
alembic revision --autogenerate -m "describe change"

# verify against the ORM models
alembic check
```

In dev, `db.connection.init_db()` also creates tables directly, but prefer
migrations for any schema evolution after the first deploy.
