# Google Cloud deployment

The hosted demo uses one same-origin Cloud Run service:

- Cloud Run serves the exported Expo web client and FastAPI API under one HTTPS `run.app` URL.
- Cloud Storage holds quarantined uploads and immutable original audio.
- Cloud SQL for PostgreSQL holds transcripts, intelligence, citations, sessions, jobs, and cost records.
- Secret Manager injects the database password, token-signing secret, and Gemini key.
- A dedicated service account uses Application Default Credentials. No service-account key file is created.

The root `Dockerfile` is intentionally independent of the checkout location. Runtime filesystem paths such as `/app`, `/fixtures`, `/cloudsql`, and `/tmp` are paths inside the container or Google-managed mounts, not paths on the operator's computer. The web build uses a same-origin API URL, so the generated JavaScript contains no deployment-specific hostname.

## Release order

1. Enable Cloud Run, Cloud Build, Artifact Registry, Cloud SQL Admin, Secret Manager, and Cloud Storage APIs.
2. Create a private regional Cloud Storage bucket with uniform access, public-access prevention, and CORS for resumable browser uploads.
3. Create the PostgreSQL Cloud SQL instance, application database/user, private secrets, and a least-privilege runtime service account.
4. Build one immutable container image in Artifact Registry.
5. Run `alembic upgrade head` as a Cloud Run Job attached to the Cloud SQL instance.
6. Deploy the same image as a public Cloud Run service, with the Cloud SQL attachment and secrets.
7. Verify `/healthz`, static routes, login, upload, processing, playback, transcript/intelligence retrieval, and object/database persistence.

Deployments default to `us-central1` so Cloud Run, Cloud Storage, Artifact Registry, and
Cloud SQL stay co-located. The initial database is a fixed-configuration 30-day Cloud
SQL trial instance; it does not support ordinary backups and must be migrated or
upgraded before the trial expires. Cloud SQL is billed continuously after an upgrade
and is not part of the ongoing free tier.

## Runtime configuration

The deployment supplies these non-secret variables:

```text
APP_ENV=production
DEMO_MODE=true
SEED_DEMO_RECORDINGS=false
COOKIE_SECURE=true
INLINE_WORKER=true
BLOB_STORE_BACKEND=gcs
GOOGLE_CLOUD_PROJECT=intelligent-audio-analysis
GCS_BUCKET=<project-specific-private-bucket>
GCS_KEY_PREFIX=app
INSTANCE_CONNECTION_NAME=<project:region:instance>
DB_USER=app
DB_NAME=audio_analysis
PROVIDER_MODE=gemini
ALLOW_REMOTE_PROVIDER_CALLS=true
PROVIDER_DATA_POLICY=synthetic-approved-only
PROVIDER_ALLOWED_LANGUAGES=en
WORKER_LEASE_SECONDS=1200
MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD=10.00
FIXTURE_ROOT=/fixtures
WEB_DIST_ROOT=/app/web
```

`DB_PASSWORD`, `TOKEN_SIGNING_SECRET`, and `GEMINI_API_KEY` are pinned Secret Manager
version references. The public demo accepts remote processing only after a per-file
approval in the upload UI and is restricted to the reviewed English,
`synthetic-approved-only` policy lane. Public access does not make private,
confidential, personal, or production recordings eligible for this deployment.
The single `Test Account` has owner rights to one shared workspace, so every visitor
using it can view, edit, export, or delete every retained recording in that workspace.

## Demo data reset

Pause new upload reservations before a hosted reset by temporarily setting
`WORKSPACE_RECORDING_QUOTA=0`. The guarded `app.reset_demo_data` command requires
`DEMO_MODE=true`, `SEED_DEMO_RECORDINGS=false`, PostgreSQL, and the exact
`CONFIRM_RESET_DEMO_DATA` value defined by the command. It deletes each live recording
through the normal tombstone and physical-purge lifecycle, preserves de-identified
cost history, revokes existing demo sessions and obsolete memberships, and leaves the
Test Account owner membership intact. Remove any one-time Cloud Run Job immediately
after a successful execution, verify the bucket and library are empty, and then restore
the recording quota.

## Rollback

Cloud Run retains older revisions. Route traffic back to the preceding revision if the application image regresses. Do not downgrade the database schema unless a separately reviewed downgrade exists. Cloud Storage originals are immutable and are not changed by an application rollback. The bucket retains Google's default seven-day soft-delete recovery window; an app-level delete removes the live object immediately, while final physical expiry follows that bucket policy.
