# Initial implementation scope

## Implemented now

- One Expo/React Native TypeScript client for web, iOS, and Android.
- A zero-account local profile and a production-shaped Compose profile.
- A portable same-origin Cloud Run image and native Google Cloud Storage adapter with
  origin-bound resumable browser uploads and workload identity.
- Demo authentication with one shared owner-level Test Account workspace and
  server-derived workspace scoping. The hosted library starts empty; local fixture
  profiles retain one deterministic seeded recording.
- Validated immutable upload flow, byte-fidelity media access, lifecycle/status, retry,
  cancellation, and deletion fencing.
- Fixture-backed transcript and intelligence artifacts with citations and provenance.
- Transcript edits and speaker labels with downstream version invalidation.
- Deterministic evidence search, cited/abstaining Ask, tasks, exports, mind maps, and
  Cost Lab.
- An explicit Gemini Files/Interactions route for timestamped audio transcription,
  schema- and exact-source-citation-validated intelligence, cited Ask, cheap repair/strong
  escalation, safety policy, and per-file data approval.
- Provider ports, capability discovery, durable budget reservations, metered dated-price
  cost records, and failure states.
- Automated backend, client, fixture-contract, migration, static web export, and
  iOS/Android bundle-generation checks to the extent supported by the local host.

## Requires operator input

- Gemini credentials and accepted provider retention/training terms. Embedding
  credentials remain optional because semantic Search is not implemented.
- Re-run the live Gemini smoke whenever the billing project, credentials, pinned model
  IDs, data policy, or dated public price catalog changes.
- A hosted PostgreSQL instance, database user, and Secret Manager values if not using
  local SQLite or Compose. Native Google Cloud Storage needs no static credential.
- A custom domain and a dated fixed-cost bill of materials before making the
  `$100/month` infrastructure claim. The public demo currently uses its managed TLS
  `run.app` origin.
- Apple and Google application identifiers, developer accounts, certificates, signing
  profiles, store metadata, and production privacy disclosures.
- An approved evaluation corpus beyond the included synthetic fixture, its human
  labels, supported-language gates, and real quality/cost results.

## Partially scaffolded, not production-complete

- Remote production execution: Gemini network adapters and capability discovery are
  implemented for explicit local use. Atomic deletion-fenced provider dispatch,
  mid-flight membership-policy rechecks, lease heartbeats, and an automated
  ambiguous-billing reconciler are still required before enabling a shared route.
- Budget enforcement: durable transactional reservations, workspace/recording/request
  admission, and token-usage settlement cover Gemini paths. Public-price results are
  estimates until provider-invoice reconciliation exists.
- Retention: worker and throttled inline maintenance tombstone expired recordings,
  expire abandoned uploads, and retry physical object purge. Provider copies, backups,
  legal hold, and production deletion-SLA evidence remain outside this demo.
- Large uploads: the Google Cloud profile uploads directly through an origin-bound GCS
  resumable session, avoiding the Cloud Run request-body limit. Completion still
  downloads the object for whole-file hashing and media validation; incremental
  hashing, chunked probing, and resume UI remain production extensions.
- Schema evolution and live status: Alembic owns PostgreSQL schema evolution and the
  Compose graph migrates before startup; disposable SQLite retains `create_all`
  compatibility. SSE provides persisted snapshots, while durable live event fan-out
  remains a hosted extension.
- Retrieval and structured projections: fixture search is authorized lexical
  retrieval; semantic embeddings are disabled and visibly gated. Most exact intents
  use structured rows, but decision counts still read the current validated canonical
  intelligence document rather than a dedicated normalized decision table.
- Runtime proof: deterministic coverage uses an injected fake HTTP transport. A
  temporary synthetic spoken TTS clip completed the public Cloud Run path through GCS
  direct upload, Cloud SQL persistence, live Gemini transcription and standard
  intelligence, transcript/intelligence retrieval, byte-identical playback, and
  deletion. The checked-in tone carrier is intentionally non-speech and is not an ASR
  quality sample. Hosted PostgreSQL concurrency, signed native builds, target-device
  cookies/media, and membership-revocation races have not been exercised on this host.

## Explicitly deferred

Live/device capture, automatic voice identity, translation, custom templates, shared
links, multimodal attachments, production connectors, API/MCP/webhooks, scheduled
memory, enterprise identity/administration, legal hold, regional resilience, owned
GPUs, and any production durability/compliance/savings claim.
