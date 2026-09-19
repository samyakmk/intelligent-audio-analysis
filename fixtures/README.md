# Intelligent Audio Analysis fixtures

`media/intelligent-audio-analysis-fixture.wav` is a deterministic 18-second, 16 kHz mono PCM
tone carrier. The fixture provider maps its exact SHA-256 to the scripted canonical
data in `sidecars/intelligent-audio-analysis-fixture.json`. This gives upload, lifecycle, citation,
Search, Ask, task, export, deletion, and cost tests stable input without pretending
that tones were transcribed by ASR.

The fixture is approved only for functional demo and contract testing. It is not
eligible for ASR, diarization, model, language-support, or savings claims. The route
quality gate remains blocked until an operator supplies the approved human-labeled
24-recording corpus described in `quality/quality-gate.json`.

Regenerate and verify the media without reading any environment file:

```sh
python3.12 scripts/generate_fixture_wav.py
python3.12 scripts/generate_fixture_wav.py --check --print-sha256
python3.12 scripts/verify_fixture_corpus.py
```

Any intentional media change must update the manifest hash, byte count, duration,
sidecar bounds, backend fixture identity, and the related tests in one change.

## Continuous-day demo fixtures

`day-demo/` contains two 112-second deterministic tone carriers with scripted
transcripts and versioned memory operations. They are intentionally long enough to
split into 3–8 meaningful batches. Both include decisions that later batches
supersede, ownership changes, and open items that later resolve. The matching client
copies are generated into `apps/client/assets/day-demo-audio/`.

These remain functional mocks: the audio is a timing carrier and the transcript is
not an ASR result. Regenerate and verify them with:

```sh
python3.12 scripts/generate_day_demo_fixtures.py
python3.12 scripts/verify_day_demo_fixtures.py
```
