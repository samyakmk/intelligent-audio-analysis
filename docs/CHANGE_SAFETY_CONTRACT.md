# Change safety contract

This contract turns the design document's AC1–AC12 into implementation checks for the
initial demo build.

## Boundaries

- The code may create and mutate only demo-local data unless the operator explicitly
  configures a remote database, blob store, or model provider.
- Mock and fixture providers must be unmistakable in provenance, UI status, and costs.
- A missing credential, capability, binary, fixture, or provider agreement must stop
  at a visible boundary; it must not silently degrade grounding or authorization.
- No secret may be committed, logged, sent to a client bundle, or included in a
  fixture. Real `.env` files are outside the task's read boundary.

## Required state variants

- New, uploading, verifying, sealed, processing, ready, partial, retryable failure,
  final failure, cancelled, deleting, and deleted recordings.
- Each of original, transcript, intelligence, and index independently ready or absent.
- Empty, corrupt, unsupported, oversize, over-duration, checksum-mismatched, valid
  fixture, and valid-but-provider-unconfigured media.
- Sufficient evidence, irrelevant evidence, no evidence, and revoked evidence for Ask.
- Cache/reuse, estimated attempt, reconciled attempt, retry, and budget rejection.

## Failure containment

- Invalid media cannot enqueue paid work or publish transcript/intelligence.
- Optional intelligence/index failure cannot hide an already valid transcript.
- Duplicate completion/retry/delivery cannot publish duplicate logical artifacts.
- Correction cannot rerun ASR and must invalidate the older downstream projection.
- Cross-workspace requests return a non-revealing not-found response.
- Tombstoned or stale-generation work cannot publish or issue a new media grant.
- Unsupported Ask claims abstain before any response is revealed as an answer.

## Verification layers

1. Backend unit tests prove state, validation, citation, budget, and adapter invariants.
2. API integration tests prove upload fidelity, idempotency, isolation, correction,
   retrieval, export, cancellation, and deletion behavior.
3. Client checks prove TypeScript contracts, shared-platform compilation, and web export.
4. Browser E2E must prove the fixture-backed AC12 path through the actual UI before a
   hosted release; that real-interface gate was unavailable on this build host.
5. Native prebuild checks prove iOS and Android projects can be generated from the
   shared source. Signing and store submission remain operator-owned steps.

## Recovery and rollback

The lightweight profile is disposable: stop the processes and remove its explicitly
configured local data directory. The Compose profile uses named volumes and must be
backed up or removed only by an operator. Provider mode can be returned to `fixture`
without rewriting canonical assets; versions and provenance make mixed runs visible.
