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

## What works with Gemini configured

- Approved audio is uploaded to Gemini Files. Pocket prefers the dedicated Gemini
  3.5 Transcribe route for timestamped/diarized clips up to 30 minutes and falls
  back to Gemini 3.5 Flash-Lite structured audio for longer files, then deletes the
  provider file on a best-effort basis.
- Transcript-grounded summaries, facts, decisions, actions, topics, participants,
  open questions, and the deterministic mind-map projection.
- Cheap-first extraction and Ask, bounded validation repair, and at most one stable
  Gemini 3.8 Flash attempt when Deep is requested or cheap output remains invalid.
- Evidence-only Ask answers with exact retrieved-source citation validation and explicit
  abstention. This validates source identity/quote bounds, not independent claim entailment.
- Durable pre-dispatch budget reservations plus metered, dated-price cost estimates.

Lexical Search, SQL/extractive exact answers, tasks, recaps, mind-map export, and
other deterministic projections remain local and do not spend model tokens.

## Repository map

```text
apps/client/       Expo Router app shared by web, iOS, and Android
services/api/      FastAPI API, worker, domain modules, and tests
fixtures/          Approved synthetic fixture and canonical labels
infra/             Docker build definitions
scripts/           Reproducible setup, fixture, and verification commands
docs/              Architecture, safety contract, and implementation scope
compose.yaml       Production-shaped local topology
config/pocket.json Checked-in non-secret runtime and build configuration
.env.example       Secret-only private-file template
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

The checked-in `config/pocket.json` owns non-secret behavior: provider/model choices,
budgets, timeouts, retries, quotas, ports, origins, and browser/native settings.
`.env.example` is only a template for API keys, signing material, credential-bearing
database URLs, and other secrets. Real `.env` variants are ignored by Git and excluded
from Docker contexts. Launchers never search for dotenv implicitly: they read only an
absolute private path you nominate, reject public settings found there, and never pass
server secrets to Expo. Never put a provider key in an `EXPO_PUBLIC_*` variable.

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

For a local Gemini run, review the provider terms and the public policy in
`config/pocket.json`, then ensure every uploaded file fits that lane. Your private file
needs only `GEMINI_API_KEY` for this profile, though independent session/token secrets
are recommended. Pass it by absolute path:

```sh
make setup
ENV_FILE=/absolute/path/to/.env make run-gemini
```

The launcher forces SQLite, filesystem blobs, loopback API hosting, and an inline
worker. It also runs Alembic before startup. Model, budget, policy, timeout, retry, and
dated-price values come from `config/pocket.json`. The upload UI additionally requires
a per-file approval before any bytes can leave the machine.

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

This wrapper explicitly prevents Compose from discovering `.env`. To use a private,
operator-owned secret file, pass an absolute path; public Compose interpolation still
comes from `config/pocket.json`:

```sh
ENV_FILE=/absolute/path/to/pocket-demo.env make compose-up-configured
```

The placeholders in `.env.example` are not deployable credentials. Replace only the
secrets needed by the profile you run with strong, operator-managed values before
exposing any service beyond localhost. Reserved public entries remain inert until
their adapters are implemented; the configuration guide lists the boundary.

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

## Gemini provider boundary

Gemini speech, intelligence, and cited Ask adapters are implemented. Activation still
requires both the explicit `gemini` run mode and remote-call gate; the local launcher
sets those only for `make run-gemini`. Startup rejects missing/placeholder credentials,
unreviewed model IDs, an unofficial base URL, unsupported languages, and an unknown
price-catalog version. The checked-in default remains the no-account fixture path.

The configured `synthetic-approved-only` policy is not permission to send private,
personal, confidential, or production audio. The UI and API require a persisted
per-upload approval. Review Google's current paid/unpaid data terms before using any
recording. Provider quality and actual account/model availability still require an
operator-run smoke whenever credentials, model access, or policy settings change. One
local synthetic-spoken-audio smoke has verified the complete configured path through
Gemini 3.5 Transcribe, Flash-Lite intelligence, Gemini 3.8 Flash Deep regeneration,
and cited Flash-Lite Ask. The deterministic test suite still uses injected fake
transports and never needs private credentials.

Before a hosted demo claims the design's fixed-cost target, also record a dated bill
of materials for web hosting, API/worker compute, database, object storage,
requests/egress, logs, backups, and domain/TLS.

## Deliberate limitations

This build is implementation-ready for local fixture and explicitly approved Gemini
demo testing, not production-ready or deployed. It does not claim Pocket-scale
durability, compliance, provider quality, or a universal savings percentage. The demo
upload path buffers bytes and must become direct resumable multipart transfer for
production-size media. Alembic owns the persistent schema, durable reservations cover
Gemini dispatch and metered settlement, and worker/inline maintenance enforces
recording and abandoned-upload expiry with retryable physical purge. A shared paid
deployment still needs invoice reconciliation, atomic deletion-fenced dispatch,
membership-policy rechecks, and long-call lease heartbeats; PostgreSQL/S3 concurrency,
signed native, and target-device runs remain to be verified. Deployment proxies must
suppress media capability URLs from access logs.
Live/device capture, automatic voice identity, translation, custom templates, shared
links, connectors, API/MCP/webhooks, enterprise identity, and multimodal ingestion
remain documented extension points.
