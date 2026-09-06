# Pocket Evidence Lab

A cross-platform demo of the Pocket audio-intelligence architecture. One Expo/React
Native TypeScript client runs in a browser and builds for iOS and Android; one FastAPI
modular backend owns uploads, canonical artifacts, processing, retrieval, tasks,
budgets, costs, and deletion.

The point of the demo is architectural evidence, not a polished fiction: uploaded
bytes remain immutable, readiness is reported asset by asset, every material claim
links to source time, retrieval is workspace-scoped, retries are idempotent, deletion
fences late workers, and cost comparisons are labeled as modeled scenarios.

## What works without credentials

- Demo sign-in and workspace isolation.
- A checked-in synthetic fixture path through transcript, intelligence, Search, Ask,
  tasks, exports, and Cost Lab.
- Upload, checksum/content validation, original-media storage and byte-fidelity access.
- Honest partial processing for arbitrary valid audio while speech is unconfigured.
- Transcript corrections and speaker labels with downstream version regeneration.
- Cited deterministic retrieval and explicit Ask abstention.
- Local SQLite/filesystem mode plus a PostgreSQL/pgvector/MinIO Compose profile.

Mock provider results are labeled in provenance and cost records. They are not passed
off as real transcription or model output.

## Repository map

```text
apps/client/       Expo Router app shared by web, iOS, and Android
services/api/      FastAPI API, worker, domain modules, and tests
fixtures/          Approved synthetic fixture and canonical labels
infra/             Docker build definitions
scripts/           Reproducible setup, fixture, and verification commands
docs/              Architecture, safety contract, and implementation scope
compose.yaml       Production-shaped local topology
.env.example       Placeholder-only configuration inventory
```

Start with [the architecture](docs/ARCHITECTURE.md), [the configuration handoff](docs/CONFIGURATION.md), [the safety contract](docs/CHANGE_SAFETY_CONTRACT.md), and [the implementation scope](docs/IMPLEMENTATION_SCOPE.md).

## Prerequisites

- Node.js 22.13 or newer
- Python 3.12 or newer
- npm
- Optional: Docker Desktop for the PostgreSQL/pgvector + MinIO profile
- Optional: Xcode and/or Android Studio for native simulator builds

`ffmpeg`/`ffprobe` are included in the API container. A host installation is needed
only when validating non-WAV uploads in the lightweight host profile.

## Safe configuration

The repository deliberately does not load a dotenv file in application code. The
placeholder inventory is `.env.example`; it contains no credentials. Real `.env`
variants are ignored and excluded from Docker contexts.

After reviewed provider adapters are implemented, export their server values into the
API/worker process (or pass an explicit operator-owned environment file to Compose).
Never put a provider key in an `EXPO_PUBLIC_*` variable: those values are compiled into
the app.

The only client configuration needed for local development is:

```sh
EXPO_PUBLIC_API_URL=http://localhost:8000
```

The checked-in defaults already use that URL.

## Lightweight local run

The reproducible path installs both dependency sets, verifies the configuration
inventory and fixture corpus, then starts the API and browser app without loading a
dotenv file:

```sh
make setup
make run
```

Open `http://localhost:8081`. The API schema is at
`http://localhost:8000/docs`, and health is exposed at
`http://localhost:8000/healthz`.

For a manual backend setup, use the service-local isolated environment:

```sh
python3.12 -m venv services/api/.venv
services/api/.venv/bin/python -m pip install --requirement services/api/requirements.txt
```

Start the API with its inline demo worker:

```sh
cd services/api
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal, install and start the universal client. `EXPO_NO_DOTENV=1`
ensures Expo reads only the explicit process environment and compiled safe default:

```sh
cd apps/client
npm install
EXPO_NO_DOTENV=1 npm run web
```

## Production-shaped local run

The Compose profile starts PostgreSQL with pgvector, MinIO, the API, and a separate
worker. It is intentionally explicit about its environment source so Compose does not
implicitly inspect a real `.env` file:

```sh
make compose-up
```

This wrapper explicitly prevents Compose from reading `.env`. To use a private,
operator-owned configuration, pass an absolute path:

```sh
ENV_FILE=/absolute/path/to/pocket-demo.env make compose-up-configured
```

The placeholder values are a configuration inventory, not deployable credentials.
Replace the active credentials for the profile you run with strong, operator-managed
values before exposing any service beyond localhost. Reserved entries remain inert
until their adapters are implemented; the configuration guide lists the boundary.

## Verification

Backend:

```sh
services/api/.venv/bin/python -m pytest services/api/tests
services/api/.venv/bin/python -m ruff check services/api/app services/api/tests services/api/alembic
# after upgrading the selected DATABASE_URL
make migration-check
```

Client:

```sh
cd apps/client
EXPO_NO_DOTENV=1 npm run typecheck
EXPO_NO_DOTENV=1 npm test
EXPO_NO_DOTENV=1 npm run export
```

Native projects are generated from the same source rather than maintained as copies:

```sh
cd apps/client
EXPO_NO_DOTENV=1 npx expo prebuild --platform ios
EXPO_NO_DOTENV=1 npx expo prebuild --platform android
```

EAS build profiles live in `apps/client/eas.json`. Store-signed builds still require
your Apple/Google accounts, final bundle identifiers, signing credentials, and store
metadata.

## Moving from fixture to remote providers

1. Review every placeholder and policy in `.env.example`.
2. Accept the chosen providers' current retention, training, and regional terms.
3. Implement the remote speech/LLM/embedding ports behind the existing adapter
   contracts; this checkpoint intentionally ships fixture adapters only.
4. Supply exact, smoke-tested model IDs and keys to server processes only.
5. Run provider capability smoke tests and the governed fixture quality gate.
6. Enter a dated price catalog before treating costs as anything beyond estimates.

Supplying keys alone does not activate paid calls. Unsupported remote mode fails
closed; see [the configuration handoff](docs/CONFIGURATION.md) for the exact boundary.

Before a hosted demo claims the design's fixed-cost target, also record a dated bill
of materials for web hosting, API/worker compute, database, object storage,
requests/egress, logs, backups, and domain/TLS.

## Deliberate limitations

This build is implementation-ready for local fixture testing, not production-ready or
deployed. It does not claim Pocket-scale durability, compliance, provider quality, or
a universal savings percentage. The demo upload path buffers bytes and must become
direct resumable multipart transfer for production-size media. Alembic owns the
persistent schema, durable reservations protect the instrumented fixture call paths,
and worker/inline maintenance enforces recording and abandoned-upload expiry with
retryable physical purge. Real paid adapters still need nonzero cost estimation,
ambiguous-outcome reconciliation, atomic deletion-fenced dispatch, membership-policy
rechecks, and long-call lease heartbeats; live PostgreSQL/S3, real-browser, signed
native, and target-device runs remain to be verified. Deployment proxies must suppress
media capability URLs from access logs.
Live/device capture, automatic voice identity, translation, custom templates, shared
links, connectors, API/MCP/webhooks, enterprise identity, and multimodal ingestion
remain documented extension points.
