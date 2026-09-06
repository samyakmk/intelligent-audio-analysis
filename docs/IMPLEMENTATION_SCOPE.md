# Initial implementation scope

## Implemented now

- One Expo/React Native TypeScript client for web, iOS, and Android.
- A zero-account local profile and a production-shaped Compose profile.
- Demo authentication, two seeded workspaces, and server-derived workspace scoping.
- Validated immutable upload flow, byte-fidelity media access, lifecycle/status, retry,
  cancellation, and deletion fencing.
- Fixture-backed transcript and intelligence artifacts with citations and provenance.
- Transcript edits and speaker labels with downstream version invalidation.
- Deterministic evidence search, cited/abstaining Ask, tasks, exports, and Cost Lab.
- Provider ports, configuration placeholders, attempt-cost records, and failure states.
- Automated backend, client, fixture-contract, migration, static web export, and
  iOS/Android bundle-generation checks to the extent supported by the local host.

## Requires operator input

- Speech/LLM/embedding credentials and accepted provider retention/training terms.
- Exact remote model IDs and a dated provider price catalog smoke-tested in the target
  region.
- Hosted PostgreSQL/object-store endpoints and credentials if not using local Compose.
- Public API/app origins, TLS/domain configuration, and a dated fixed-cost bill of
  materials before making the `$100/month` infrastructure claim.
- Apple and Google application identifiers, developer accounts, certificates, signing
  profiles, store metadata, and production privacy disclosures.
- An approved evaluation corpus beyond the included synthetic fixture, its human
  labels, supported-language gates, and real quality/cost results.

## Partially scaffolded, not production-complete

- Remote provider execution: ports and fail-closed configuration exist, but network
  adapters, capability probes, callbacks, and paid calls are intentionally absent.
  Atomic deletion-fenced provider dispatch, mid-flight membership-policy rechecks,
  lease heartbeats, and an ambiguous-billing reconciler are required before enabling
  a shared remote route.
- Budget enforcement: durable transactional reservations, workspace admission, and
  attempt settlement cover the instrumented fixture paths. Paid adapters still need
  honest nonzero estimates plus provider-invoice reconciliation, including ambiguous
  outcomes.
- Retention: worker and throttled inline maintenance tombstone expired recordings,
  expire abandoned uploads, and retry physical object purge. Provider copies, backups,
  legal hold, and production deletion-SLA evidence remain outside this demo.
- Large uploads: the demo uses an API capability URL and whole-file buffering. Direct
  resumable multipart upload and incremental hashing remain the production extension.
- Schema evolution and live status: Alembic owns PostgreSQL schema evolution and the
  Compose graph migrates before startup; disposable SQLite retains `create_all`
  compatibility. SSE provides persisted snapshots, while durable live event fan-out
  remains a hosted extension.
- Retrieval and structured projections: fixture search is authorized lexical
  retrieval; semantic embeddings are disabled and visibly gated. Most exact intents
  use structured rows, but decision counts still read the current validated canonical
  intelligence document rather than a dedicated normalized decision table.
- Runtime proof: live PostgreSQL/MinIO concurrency, real-browser interaction, signed
  native builds, target-device cookies/media, and membership-revocation races have not
  been exercised on this host.

## Explicitly deferred

Live/device capture, automatic voice identity, translation, custom templates, shared
links, multimodal attachments, production connectors, API/MCP/webhooks, scheduled
memory, enterprise identity/administration, legal hold, regional resilience, owned
GPUs, and any production durability/compliance/savings claim.
