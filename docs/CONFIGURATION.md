# Configuration and operator handoff

The checked-in `.env.example` is the complete configuration inventory for this
demo. It contains conspicuous placeholders and safe fixture defaults only. The
application never searches for, opens, or loads a dotenv file; values enter through
the process environment or through the explicit Compose wrapper.

## Consumed now versus reserved inventory

The example is deliberately broader than the runnable fixture implementation. These
values are consumed today:

- Backend: `DATABASE_URL`, `BLOB_STORE_BACKEND`, `BLOB_ROOT`, `S3_ENDPOINT_URL`,
  `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`,
  `S3_KEY_PREFIX`, `FIXTURE_ROOT`, `DEMO_MODE`, `INLINE_WORKER`, `COOKIE_SECURE`,
  `CORS_ORIGINS`, `SESSION_SECRET`/`TOKEN_SIGNING_SECRET`, session/media TTLs,
  upload/duration limits, all three AI spend ceilings, worker lease duration,
  inline sweeper interval, workspace quotas, `RECORDING_RETENTION_DAYS`, `PROVIDER_MODE`, and
  `ALLOW_REMOTE_PROVIDER_CALLS`.
- Compose/launchers: PostgreSQL/MinIO credentials and ports,
  `COMPOSE_DATABASE_URL`, API/web ports, worker poll interval, and the backend values above.
- Universal client/build: `EXPO_PUBLIC_API_URL`, status polling, media-grant refresh,
  `EXPO_PUBLIC_DEMO_MODE`, app name/slug/scheme, iOS/Android identifiers, and optional
  EAS project ID.

All other entries—including provider keys/model IDs, price reconciliation, telemetry,
rate limits, failure injection, proxy trust, cookie-name/SameSite, and most tuning
knobs—are reserved contracts or operator checklists. Supplying them does nothing until
the corresponding adapter or policy is implemented and tested. `PROVIDER_MODE=remote`
and `ALLOW_REMOTE_PROVIDER_CALLS=true` fail startup.

## No-account fixture run

The default run deliberately strips ambient provider and object-store credentials,
forces `PROVIDER_MODE=fixture`, and disables remote calls:

```sh
make setup
make run
```

This uses SQLite, filesystem blobs, an inline worker, the exact checked-in fixture
hash, and the universal Expo web client. No value from `.env.example` needs to be
copied for this path.

The production-shaped local topology is also safe by default:

```sh
make compose-up
```

It uses PostgreSQL/pgvector, private MinIO, separate API and leased-worker
processes, and the statically exported web client. The wrapper passes `/dev/null`
as Compose's env file so Compose cannot implicitly inspect a local `.env`.

## Explicit configured run

Create and own a private configuration file outside source control, fill the
currently consumed values you need, and nominate its absolute path explicitly:

```sh
ENV_FILE=/absolute/path/to/pocket-demo.env make compose-config-configured
ENV_FILE=/absolute/path/to/pocket-demo.env make compose-up-configured
```

The wrapper rejects a bare `.env` path. Real environment variants are excluded by
both `.gitignore` and `.dockerignore`.

## Values to supply before a shared or hosted demo

- Public API/web origins, TLS termination, and `COOKIE_SECURE=true`; wire and test
  the reserved proxy-trust policy before trusting forwarded headers.
- Independent high-entropy session/capability-token, database, and object-storage
  secrets. The listed CSRF secret/cookie-name knobs are reserved, not consumed yet.
- Hosted PostgreSQL and S3-compatible endpoints, credentials, bucket policy,
  backups, lifecycle rules, and deletion expectations.
- Approved speech/LLM/embedding provider keys, exact pinned model identifiers,
  region, allowlisted languages, and accepted retention/training terms.
- A dated, reviewed price catalog and a fixed-infrastructure bill of materials.
- Apple/Google identifiers, developer accounts, signing credentials, store
  metadata, and production privacy disclosures.
- A human-labeled evaluation corpus and recorded quality-gate results for every
  language and provider route that the UI will advertise.

`EXPO_PUBLIC_*` values are compiled into browser and native bundles. They may
contain only public client configuration. Provider, database, object-store, session,
CSRF, callback, and capability secrets must remain server-only.

`IOS_BUNDLE_IDENTIFIER`, `ANDROID_PACKAGE_NAME`, `EXPO_APP_*`, and
`EAS_PROJECT_ID` are public build metadata consumed by `app.config.ts`. Replace their
example values before store builds; signing material belongs in Apple/Google/EAS
credential stores, never in this repository or a public client variable.

For a simulator, `localhost` may work depending on platform networking. A physical
device needs an API URL reachable from that device, normally a LAN or TLS hostname:

```sh
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=https://api.example.test npm --prefix apps/client run ios
```

## Provider status in this checkpoint

The checked-in remote provider entries are contracts and placeholders, not active
network adapters. The runnable implementation uses the approved fixture speech/LLM
adapters plus deterministic lexical retrieval. Supplying keys alone does not enable
paid calls. A remote adapter must still implement the existing provider ports,
capability checks, callback/idempotency rules, price resolution, nonzero reservation
estimates, billing reconciliation, atomic deletion-fenced dispatch, membership-policy
rechecks, lease heartbeats, and fixture quality gate. This is intentional: missing
external approval cannot silently cause media or transcript text to leave the machine.

Arbitrary valid audio is still accepted, byte-verified, retained as an immutable
original, and reported as `PARTIAL / speech_unconfigured`; no transcript or prose is
invented. The exact fixture hash is the only zero-key path that publishes scripted
canonical artifacts.

## Current operational boundaries

- The lightweight upload target is an authenticated API-issued capability URL and
  buffers bytes in the demo client/API. Production-sized uploads should replace
  that adapter with direct, resumable S3 multipart transfer and incremental hashing.
- Alembic owns persistent PostgreSQL schema evolution; Compose runs its one-shot
  migrator before API startup. Only disposable SQLite uses metadata `create_all`.
- Worker and throttled inline maintenance tombstone expired recordings, expire
  abandoned uploads, and retry physical purge. This does not prove provider/backups
  deletion or a production deletion SLA.
- Durable reservation/admission and settlement cover instrumented fixture paths.
  Paid adapters must supply conservative nonzero estimates and reconcile actual or
  ambiguous provider billing before those controls become financial guarantees.
- The included SSE endpoint replays persisted events and a snapshot; the client uses
  polling for active demo states. A hosted service should add a durable live event
  fan-out path.
- Native projects are generated from shared source and were prebuilt locally, but
  signed device builds and native cookie/media behavior still need target-device
  verification.
- The demo session cookie name and `SameSite=Lax` policy are fixed in code. Host the
  web client and API on the same site (often behind one reverse proxy) or redesign and
  test the cookie policy; CORS alone does not make cross-site cookie auth reliable.
- Official local and container API launchers disable Uvicorn access logs because media
  capabilities appear in URLs. Any ingress/reverse proxy must also redact or suppress
  those paths.

These boundaries are also summarized in `IMPLEMENTATION_SCOPE.md`; they are not
Pocket-scale durability, compliance, quality, or savings claims.
