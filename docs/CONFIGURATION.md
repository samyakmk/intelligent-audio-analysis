# Configuration and operator handoff

Pocket uses two deliberately separate configuration sources:

- `config/pocket.json` is checked in and contains every non-secret runtime/build
  choice: provider gates and policies, exact models, budgets, prices, timeouts,
  retries, quotas, ports, origins, logging policy, and Expo/native metadata.
- `.env` is operator-owned, ignored by Git and Docker build contexts, and contains
  only credentials or secret signing material. `.env.example` is its placeholder-only
  template.

The launchers never discover `.env` implicitly. A configured command accepts an
absolute private path, parses it as data rather than shell code, and rejects any
non-secret key with an instruction to move that key to `config/pocket.json`.

## Precedence and containment

The effective order is:

1. safe application fallbacks;
2. checked-in `config/pocket.json`;
3. explicit run-profile overrides that force fixture/Gemini and local topology safety;
4. allowlisted secrets from the explicitly selected `.env`.

Public settings therefore cannot be silently changed by a stale private file. The
local launcher forwards only the Gemini and session-related secrets needed by the API;
database/object-store secrets in the same file are not forwarded to the lightweight
SQLite profile. The Expo process receives only ordinary process metadata and
`EXPO_PUBLIC_*`/public app values. The Compose wrapper validates and injects the
secret allowlist itself, then gives Docker Compose `/dev/null` as its env file so
Compose cannot discover another dotenv file.

## Secret-only `.env`

For the lightweight Gemini profile, the only required value is:

```dotenv
GEMINI_API_KEY=replace-me-gemini-api-key
```

Independent `SESSION_SECRET`, `CSRF_SECRET`, and `TOKEN_SIGNING_SECRET` values are
recommended for reproducibility and required before sharing the app beyond an
isolated local session. PostgreSQL URLs/passwords and MinIO/S3 credentials are needed
only for the configured Compose profile. Future provider/callback/telemetry secrets
may remain blank until those integrations are implemented.

Copy `.env.example`, replace the needed placeholders, and keep the result outside
source control. Never use an `EXPO_PUBLIC_*` name for a secret.

## Public `config/pocket.json`

The JSON file is sectioned for readability but flattened to the uppercase setting
names already used by the API, worker, Compose, and Expo build. Values may be strings,
numbers, booleans, or arrays of strings. Arrays become comma-separated process values.
Duplicate names across sections, invalid types, and secret names fail closed.

The currently active Gemini choices live under `gemini`, `gemini_pricing`,
`provider_policy`, and `limits`. In particular, edit this file—not `.env`—to change:

- `GEMINI_BASE_URL`, `GEMINI_SPEECH_MODEL`, `LLM_CHEAP_MODEL`, or
  `LLM_STRONG_MODEL`;
- repair counts, context limits, provider timeouts, retries, and backoff;
- per-recording, per-Ask, and monthly workspace spend ceilings;
- data policy, allowed languages, retention, upload limits, and quotas;
- dated public-list-price inputs used by admission and the estimated cost ledger.

Startup still validates the official Gemini host, pinned reviewed model registry,
English-only evaluated lane, supported policy, positive price inputs, and bounded
retry/context settings regardless of which launcher supplies them.

Some public settings reserve future adapters or hosted policies and remain inert until
implemented. These include non-Gemini provider models, embeddings, invoice
reconciliation, most telemetry/rate-limit knobs, proxy trust, and configurable cookie
names/SameSite. Their presence documents the intended contract; it does not imply a
working integration.

## Local runs

The zero-account path reads public configuration but forces fixture mode, disables
remote calls, and uses SQLite/filesystem storage:

```sh
make setup
make run
```

For Gemini, nominate the secret file explicitly. The command forces the Gemini gate
while retaining the public model/budget/policy settings:

```sh
ENV_FILE=/absolute/path/to/.env make run-gemini
```

Use a different checked-in-compatible public file only when intentionally testing a
variant:

```sh
CONFIG_FILE=/absolute/path/to/pocket.json \
ENV_FILE=/absolute/path/to/.env \
make run-gemini
```

The launcher runs Alembic first, then starts the loopback FastAPI server, inline worker,
and Expo web client. It uses a 30-minute local worker lease for bounded provider waits;
shared remote workers still need active long-call heartbeats before production use.

## Browser and native builds

`make web`, `make export`, and `make prebuild` load `config/pocket.json` through the
secret-stripping build wrapper. Native projects remain generated output from the same
Expo source tree:

```sh
make web
make export
make prebuild
```

`EXPO_PUBLIC_*` values are compiled into web/native bundles and must be public.
`IOS_BUNDLE_IDENTIFIER`, `ANDROID_PACKAGE_NAME`, `EXPO_APP_*`, and `EAS_PROJECT_ID`
are public build metadata; signing credentials belong in Apple/Google/EAS credential
stores, never in either checked-in config or `.env`.

## Compose runs

The safe production-shaped local topology forces fixture mode and supplies isolated
development-only PostgreSQL/MinIO/session credentials:

```sh
make compose-up
```

The configured profile combines checked-in public configuration with the explicitly
selected secret file:

```sh
ENV_FILE=/absolute/path/to/.env make compose-config-configured
ENV_FILE=/absolute/path/to/.env make compose-up-configured
```

Before a shared deployment, replace all relevant database/object-store/session
placeholders, set real public origins/TLS policy in `config/pocket.json`, and verify
cookie behavior behind the intended same-site proxy. Hosted PostgreSQL/S3,
provider-invoice reconciliation, signed native builds, and target-device behavior are
not proven by the local demo.

## Provider and data boundary

The reviewed demo routes are Gemini 3.5 Transcribe for eligible timestamped speech,
Gemini 3.5 Flash-Lite for standard intelligence/Ask and long-audio fallback, and
Gemini 3.8 Flash for Deep or bounded validation escalation. Search remains authorized
lexical retrieval until an embedding adapter is implemented.

Every remote upload requires persisted per-file approval. With
`PROVIDER_DATA_POLICY=synthetic-approved-only`, do not submit private, personal,
confidential, or production recordings. Gemini Files are deleted immediately on a
best-effort basis, which is not a zero-retention guarantee. Review the current account
tier and provider terms before changing the policy or using new data.

Without Gemini activation, arbitrary valid audio remains immutable and byte-verified
but stops honestly at `PARTIAL / speech_unconfigured`; only the exact checked-in
fixture hash can publish scripted fixture artifacts.
