# Configuration and operator handoff

Intelligent Audio Analysis has two configuration sources with separate responsibilities:

- `config/intelligent-audio-analysis.json` is checked in and contains non-secret runtime and build choices:
  provider gates and policies, exact models, budgets, prices, timeouts, retries,
  quotas, ports, origins, logging policy, and Expo/native metadata.
- `.env` is operator-owned, ignored by Git and Docker build contexts, and contains
  only credentials or secret signing material. `.env.example` is its placeholder-only
  template.

The root `package.json` is the canonical command surface.

## Local precedence and automatic provider selection

For `npm start`, effective settings are applied in this order:

1. safe application fallbacks;
2. checked-in `config/intelligent-audio-analysis.json`;
3. local topology settings for SQLite, filesystem blobs, loopback hosting, and the
   inline worker;
4. allowlisted secrets from the repository-root `.env`, when it exists.

If `.env` contains a nonblank, non-template `GEMINI_API_KEY`, the launcher selects
Gemini and enables the remote-call gate. Otherwise it selects the fixture provider and
forces remote calls off. There is no separate Gemini run command:

```sh
npm start
```

Use `npm run start:fixture` to force deterministic fixture mode even when `.env` has
a key. Use an alternative secret file only by naming its absolute path:

```sh
npm start -- --env-file /absolute/private/path/intelligent-audio-analysis.env
```

An alternative public configuration can also be selected explicitly:

```sh
npm start -- \
  --config-file /absolute/path/intelligent-audio-analysis.json \
  --env-file /absolute/private/path/intelligent-audio-analysis.env
```

The launcher validates the entire private file before selecting a provider. Public
keys in that file fail closed with an instruction to move them to
`config/intelligent-audio-analysis.json`. The parser treats values as data and never sources the file as
shell code.

## Secret containment

For the lightweight Gemini profile, the only required private value is:

```dotenv
GEMINI_API_KEY=your-private-gemini-api-key
```

Independent `SESSION_SECRET`, `CSRF_SECRET`, and `TOKEN_SIGNING_SECRET` values are
recommended for reproducibility and are required before sharing the app beyond an
isolated local session. PostgreSQL URLs/passwords and MinIO/S3 credentials are needed
only for the configured Compose profile.

The lightweight launcher forwards only its allowlisted Gemini and session-related
secrets to the API. Database and object-store secrets in the same file are not sent to
the SQLite profile. The Expo process receives only ordinary process metadata and
`EXPO_PUBLIC_*` values. Never put a provider key in an `EXPO_PUBLIC_*` variable.

## Checked-in public configuration

`config/intelligent-audio-analysis.json` is sectioned for readability and flattened into the uppercase
setting names used by the API, worker, Compose, and Expo build. Values may be strings,
numbers, booleans, or arrays of strings. Arrays become comma-separated process values.
Duplicate names, invalid types, and secret-looking names fail closed.

Edit `config/intelligent-audio-analysis.json`, not `.env`, to change:

- Gemini base URL or model selection;
- repair counts, context limits, provider timeouts, retries, and backoff;
- per-recording, per-Ask, and monthly workspace spend ceilings;
- data policy, allowed languages, retention, upload limits, and quotas;
- dated list-price inputs used by admission and estimated costs;
- client URLs, origins, or native application metadata.

Startup validates the official Gemini host, pinned reviewed model registry,
English-only evaluated lane, supported data policy, positive price inputs, and bounded
retry/context values regardless of which launcher supplies them.

Some settings reserve future adapters or hosted policies and remain inert until
implemented. These include non-Gemini provider models, embeddings, invoice
reconciliation, most telemetry/rate-limit knobs, proxy trust, and configurable cookie
names/SameSite.

## Client and native builds

The root npm commands load `config/intelligent-audio-analysis.json` through a secret-stripping wrapper:

```sh
npm run web
npm run export:web
npm run prebuild
```

`EXPO_PUBLIC_*` values are compiled into web/native bundles and must be public.
`IOS_BUNDLE_IDENTIFIER`, `ANDROID_PACKAGE_NAME`, `EXPO_APP_*`, and `EAS_PROJECT_ID`
are public build metadata. Signing credentials belong in Apple, Google, or EAS
credential stores.

## Compose profiles

The safe production-shaped local topology forces fixture mode and supplies isolated,
development-only PostgreSQL, MinIO, and session credentials:

```sh
npm run compose:up
```

The configured profile combines checked-in public configuration with an explicitly
selected secret file:

```sh
ENV_FILE=/absolute/private/path/intelligent-audio-analysis.env npm run compose:config:configured
ENV_FILE=/absolute/private/path/intelligent-audio-analysis.env npm run compose:up:configured
```

The wrapper passes `/dev/null` to Docker Compose as its env file after validating and
injecting the allowlisted values itself. This prevents Compose from independently
discovering another dotenv file.

Before a shared deployment, replace all relevant database, object-store, and session
placeholders; set real origins and TLS policy in `config/intelligent-audio-analysis.json`; and verify cookie
behavior behind the intended same-site proxy.

## Google Cloud profile

The root `Dockerfile` produces a single same-origin Cloud Run image. An empty
`EXPO_PUBLIC_API_URL` is deliberate in that build: browser API calls resolve against
the current HTTPS origin, so a Cloud Run hostname is not compiled into JavaScript.

The hosted API selects native Cloud Storage with `BLOB_STORE_BACKEND=gcs`,
`GCS_BUCKET`, `GOOGLE_CLOUD_PROJECT`, and an optional `GCS_KEY_PREFIX`. Google client
libraries use Application Default Credentials: local development can use the
operator's ADC login, while Cloud Run uses its attached service account without a key
file. Direct browser uploads use origin-bound resumable session URLs; those bearer
URLs and local upload tokens are never persisted in idempotency records.

Cloud SQL can be selected without placing a composite connection URL in a secret.
When `DATABASE_URL` is absent, `INSTANCE_CONNECTION_NAME`, `DB_USER`, `DB_PASSWORD`,
and `DB_NAME` produce a percent-encoded PostgreSQL URL over the Google-managed
`/cloudsql` Unix socket. `DB_PASSWORD`, `TOKEN_SIGNING_SECRET`, and
`GEMINI_API_KEY` belong in Secret Manager and are injected only into the server
container. `WEB_DIST_ROOT` and `FIXTURE_ROOT` refer to container-owned paths, never
to the source checkout. `SEED_DEMO_RECORDINGS=false` keeps the hosted shared workspace
empty across restarts; local fixture profiles retain their canonical seeded recording
by default. See `infra/gcp/README.md` for the release and rollback order.

## Provider and data boundary

The reviewed demo routes are Gemini 3.5 Transcribe for eligible timestamped speech,
Gemini 3.5 Flash-Lite for standard intelligence, Ask, and long-audio fallback, and
Gemini 3.8 Flash for Deep or bounded validation escalation. Search remains authorized
lexical retrieval until an embedding adapter is implemented.

Every remote upload requires persisted, per-file approval. With
`PROVIDER_DATA_POLICY=synthetic-approved-only`, do not submit private, personal,
confidential, or production recordings. Gemini Files are deleted immediately on a
best-effort basis, which is not a zero-retention guarantee. Review the current account
tier and provider terms before changing the policy or data class.

Without Gemini activation, arbitrary valid audio remains immutable and byte-verified
but stops honestly at `PARTIAL / speech_unconfigured`; only the exact checked-in
fixture hash can publish scripted fixture artifacts.
