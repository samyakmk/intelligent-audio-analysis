# Database migrations

Alembic owns the persistent database schema. The baseline revision represents the
complete current SQLAlchemy model, including durable budget reservations.

Run commands from `services/api` with the service virtual environment:

```sh
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic current
.venv/bin/python -m alembic check
```

From the repository root, the equivalent shortcuts are `make migrate`,
`make migration-current`, and `make migration-check`.

The migration environment reads `DATABASE_URL` from the process environment only.
It never searches for or loads dotenv files. If `DATABASE_URL` is absent, the local
SQLite URL in `alembic.ini` is used.

For a disposable SQLite database:

```sh
DATABASE_URL=sqlite:////absolute/path/pocket-demo.db \
  .venv/bin/python -m alembic upgrade head
```

For PostgreSQL, use the SQLAlchemy psycopg URL form:

```sh
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB \
  .venv/bin/python -m alembic upgrade head
```

The baseline issues `CREATE EXTENSION IF NOT EXISTS vector` only on PostgreSQL.
The Compose pgvector image supports it. A hosted database must have pgvector
installed and the migration role must be allowed to create the extension. Downgrade
does not drop `vector`, because extensions can be shared with other schemas/apps.

## Existing demo databases

Do not run the baseline upgrade directly over a database whose tables were already
created by the earlier `create_all` startup path: the create operations will correctly
fail rather than guess that an unknown schema is equivalent. Back up the database,
compare it against the baseline, and only then adopt it with:

```sh
.venv/bin/python -m alembic stamp c14c172f08b5
```

Fresh shared/deployed databases should always run `upgrade head` before API or worker
startup. Schema upgrades should be a distinct deployment step; do not run concurrent
migrators. Generate future revisions with `alembic revision --autogenerate`, inspect
every operation, test both SQLite and PostgreSQL SQL rendering, then commit the frozen
revision.

The production-shaped Compose graph enforces this order with a one-shot `migrate`
service. Both API and worker start only after that service succeeds (the worker depends
on the healthy API). The API image copies `alembic.ini` and the complete `alembic/`
revision tree. The zero-account local runner retains the existing `create_all`
compatibility path for its disposable SQLite database; it is not the deployment
migration mechanism.

`alembic downgrade base` drops every application table and all application data. Use
it only for disposable databases or after a verified backup/restore plan.
