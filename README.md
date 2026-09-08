# Intelligent Audio Analysis

Intelligent Audio Analysis is a cross-platform audio-intelligence demo. An Expo/React
Native client targets web, iOS, and Android, while a FastAPI backend owns uploads,
processing, cited intelligence, retrieval, tasks, budgets, costs, and deletion.

The repository uses npm as its task interface. There is no Makefile and Gemini does
not need a separate run command.

## Hosted demo

The public Google Cloud demo is available at
<https://intelligent-audio-analysis-119822447991.us-central1.run.app>. It uses Cloud
Run, Cloud SQL, private Cloud Storage, Secret Manager, and server-side Gemini. Demo
access uses one shared owner-level `Test Account` workspace. Recordings uploaded by
one visitor are visible and mutable to every other visitor using that account. Use
only synthetic or explicitly approved, non-private audio, as required by the upload
confirmation.

## Quick start

### Prerequisites

- Node.js 22.13 or newer
- npm 10 or newer
- Python 3.12
- Optional: `ffmpeg` and `ffprobe` for non-WAV uploads
- Optional: Docker Desktop for the PostgreSQL/pgvector and MinIO profile

Install the locked backend and client dependencies:

```sh
npm run setup
```

Start the API, inline worker, database migrations, and Expo web app:

```sh
npm start
```

Then open:

- App: `http://localhost:8081`
- API documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/healthz`

With no configured Gemini key, `npm start` uses the deterministic, zero-account
fixture provider and disables all remote provider calls.

## Run with Gemini

Copy the secret template to the ignored repository-root `.env`:

```sh
cp .env.example .env
```

Set a real key in `.env`:

```dotenv
GEMINI_API_KEY=your-private-gemini-api-key
```

Now use the same command:

```sh
npm start
```

The launcher detects the key, enables the reviewed Gemini route, and gives private
settings only to the API process. Expo never receives the Gemini key. Blank values and
the `replace-me-...` template value do not enable Gemini.

You can also keep secrets in another file and select it explicitly:

```sh
npm start -- --env-file /absolute/private/path/intelligent-audio-analysis.env
```

Use a different public configuration when intentionally testing a variant:

```sh
npm start -- \
  --config-file /absolute/path/intelligent-audio-analysis.json \
  --env-file /absolute/private/path/intelligent-audio-analysis.env
```

To force the local fixture provider even when `.env` contains a key:

```sh
npm run start:fixture
```

Gemini uploads are not automatic. Each file still requires explicit approval in the
upload UI before any bytes can leave the machine. The checked-in
`synthetic-approved-only` policy is not permission to submit personal, confidential,
or production recordings.

## Common commands

Run these from the repository root:

| Command | Purpose |
| --- | --- |
| `npm run setup` | Create the Python virtual environment, install locked dependencies, and verify fixtures |
| `npm start` | Start the local API and web app; enable Gemini automatically when `.env` has a key |
| `npm run start:fixture` | Start locally with remote provider calls forced off |
| `npm test` | Run fixture validation plus all backend and client tests |
| `npm run lint` | Run backend lint, client lint, and TypeScript checks |
| `npm run check` | Run tests, lint, type checking, and a production web export |
| `npm run web` | Start only the Expo web client with checked-in public configuration |
| `npm run export:web` | Build the static web export |
| `npm run prebuild` | Generate clean iOS and Android native projects |
| `npm run migrate` | Upgrade the service database to the latest Alembic revision |
| `npm run migration:current` | Show the current Alembic revision |
| `npm run migration:check` | Check whether ORM metadata needs a migration |

`npm run dev` is an alias for `npm start`.

## Configuration model

Configuration is deliberately split:

- `config/intelligent-audio-analysis.json` contains checked-in, non-secret behavior such as model IDs,
  provider policy, budgets, prices, retries, timeouts, ports, origins, and app metadata.
- `.env` contains only private credentials and signing material. It is ignored by Git
  and Docker build contexts.
- `.env.example` is a placeholder-only template and is safe to commit.

The launcher parses `.env` as data rather than executing it as shell code. It rejects
public settings in `.env`; put those in `config/intelligent-audio-analysis.json`. Never use an
`EXPO_PUBLIC_*` name for a secret because Expo embeds those values in client bundles.

The lightweight run always uses local SQLite, filesystem blobs, loopback API hosting,
and an inline worker. It runs Alembic before startup. See
[docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete precedence and
operator contract.

## Production-shaped local profile

Start PostgreSQL with pgvector, MinIO, the API, a separate worker, and the web client
with safe fixture-only defaults:

```sh
npm run compose:up
```

Useful Compose commands:

```sh
npm run compose:config
npm run compose:logs
npm run compose:down
```

To validate or start the configured Compose profile with an operator-owned secret
file, provide an absolute path:

```sh
ENV_FILE=/absolute/private/path/intelligent-audio-analysis.env npm run compose:config:configured
ENV_FILE=/absolute/private/path/intelligent-audio-analysis.env npm run compose:up:configured
```

The values in `.env.example` are not deployable credentials. Replace the relevant
database, object-store, and session secrets before exposing any service beyond an
isolated local machine.

## Verification

Run the complete local verification suite after setup:

```sh
npm run check
```

Or run layers independently:

```sh
npm run fixtures
npm run test:backend
npm run test:client
npm run lint:backend
npm run lint:client
npm run typecheck
npm run export:web
```

Provider tests use injected fake transports and never need a private API key. Actual
Gemini account access, current model availability, and provider quality still require
an operator-run smoke with approved synthetic audio.

## Repository map

```text
apps/client/       Expo Router application shared by web, iOS, and Android
services/api/      FastAPI API, inline/standalone worker, migrations, and tests
fixtures/          Approved synthetic audio, canonical sidecars, and quality gates
infra/             Docker definitions and example price catalog
scripts/           Setup, launch, configuration, fixture, and Compose helpers
docs/              Architecture, configuration, safety contract, and scope
compose.yaml       Production-shaped local topology
config/intelligent-audio-analysis.json Checked-in non-secret runtime and build configuration
.env.example       Secret-only template
package.json       Canonical developer command surface
```

Start with [the architecture](docs/ARCHITECTURE.md),
[the change-safety contract](docs/CHANGE_SAFETY_CONTRACT.md), and
[the implementation scope](docs/IMPLEMENTATION_SCOPE.md).

## What the demo proves

- Uploaded bytes remain immutable and byte-verifiable.
- Transcript, intelligence, and index readiness are reported independently.
- Material claims link back to recording time ranges.
- Retrieval is workspace-scoped and Ask validates exact source citations.
- Retries are idempotent, deletion fences late workers, and paid calls use durable
  budget reservations.
- Fixture output is visibly labeled and is never presented as real model output.
- Gemini Files are deleted on a best-effort basis after processing.

Lexical Search, extractive exact answers, tasks, recaps, mind-map export, and other
deterministic projections remain local and do not spend model tokens.

## Current limits

This project is deployed as a public, explicitly non-production Google Cloud demo.
Browser uploads use origin-bound GCS resumable sessions and the API reconciles and
validates the object before processing. A production or private-data release still
needs real identity/onboarding, isolated user workspaces, provider invoice
reconciliation, atomic deletion-fenced dispatch, membership-policy rechecks, long-call
lease heartbeats, production PostgreSQL concurrency tests, signed native builds,
target-device verification, and a database backup/restore plan.

Without Gemini, arbitrary valid audio is stored and verified but stops visibly at
`PARTIAL / speech_unconfigured`; only the exact checked-in fixture can publish scripted
fixture artifacts.
