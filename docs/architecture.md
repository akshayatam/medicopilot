# Architecture

## System overview

Medication Copilot is a local text-and-reviewed-voice prototype with three strict data layers: an imported source record, an explicitly reconciled medication plan, and an adherence ledger. The local model interprets approved text but never supplies medication facts. Pydantic schemas and deterministic services enforce boundaries before any patient-facing response or mutation.

## Repository structure

```text
app.py                 CLI entry point
config.py              environment-backed local settings
data/                  protected synthetic profiles, runtime patients, and evaluation data
evaluation/            live intent-routing evaluation runner
gemma/                 Ollama client, prompt, intent schema, parser, and orchestrator
medication/            conversion, reconciliation, schemas, repositories, safety, and services
scripts/               Synthea converter and deterministic demo tooling
tests/                 non-live unit and integration-style regression tests
ui/                    local Gradio application
voice/                 ephemeral audio validation, provider, capability probe, and confirmation workflow
```

## Runtime request flow

```mermaid
sequenceDiagram
    participant U as User
    participant S as Safety screen
    participant G as Local Gemma
    participant V as Pydantic validator
    participant O as Orchestrator
    participant R as Medication resolver
    participant M as Deterministic service
    participant P as Runtime repository

    U->>S: Text request
    alt unsafe request
        S-->>U: Deterministic refusal
    else allowed navigation request
        S->>G: Minimal text only
        G->>V: Structured intent JSON
        V->>O: Validated/normalized intent
        O->>R: User-provided medication phrase
        R->>P: Confirmed reconciled medicines only
        O->>M: At most one approved operation
        M->>P: Verified plan / adherence ledger
        M-->>U: Grounded deterministic response
    end
```

Invalid model output receives one bounded repair attempt. Failed repair produces a no-action routing result. Medication-specific phrases are preserved for the deterministic resolver, which alone returns `MATCHED`, `AMBIGUOUS`, or `NOT_FOUND`.

## Voice request flow

```text
microphone/upload → local ffmpeg normalization → Gemma transcription only
→ visible editable transcript → explicit transcript submission
→ existing safety/router/Pydantic/resolver/readiness path
→ read-only response OR session-bound exact-dose proposal
→ explicit confirmation → revalidation → existing runtime service
```

Audio is limited to 30 seconds and 10 MiB, normalized to mono 16 kHz PCM WAV in a non-identifying temporary directory, and deleted during unconditional cleanup. Neither raw audio nor transcript-review state is written to runtime patient JSON. The provider sends only the transcription instruction and audio—no patient record. Gradio state holds transcript and pending action per browser session; patient changes and cancellation replace that state. Pending mutations expire after five minutes and are revalidated against patient ID, readiness, deterministic resolution, and the exact scheduled ledger entry.

Ollama capability is established by a generated speech request whose returned content must match expected words. With Ollama 0.32.4 and `gemma4:e2b`, WAV audio works through the multimodal `images` compatibility field; a native `audios` field request was ignored. Thinking is disabled for transcription. No cloud provider or TTS is present.

## Source record and verified plan

`source_record.medications` preserves imported or curated source orders and provenance. FHIR `active` does not imply current use. These records are available only through the read-only review path.

`medication_plan.medications` is created by explicit reconciliation. Daily actions accept only confirmed, verified entries with verified schedules. PRN entries may be reconciled but cannot receive recurring reminders.

`dose_logs` contains only app events or explicitly seeded synthetic adherence events. Clinical `MedicationAdministration` records remain in `source_record.clinical_administrations` and are never merged automatically.

## Readiness enforcement

The deterministic readiness result requires a confirmed medication list, verified schedules, a valid timezone, and no blocking conflict affecting the plan. `RuntimeMedicationService.ensure_ready()` blocks schedule and adherence operations for an unready patient. Raw source orders cannot be used as a fallback.

## Safety boundaries

The deterministic safety screen runs before Gemma. Requests for diagnosis, interactions, medication changes, dose changes, missed-dose advice, or treatment receive a fixed refusal; emergency language receives escalation guidance. Gemma cannot override this result.

Gemma may classify a request, preserve a medication phrase, or request clarification. It may not resolve medications, create schedules, infer adherence, provide clinical advice, or mutate persistence directly.

## Persistence flow

Runtime patients are loaded through `PatientDataService`, which validates schema version 2.0 and cross-field invariants. Mark-taken updates are revalidated and written through a temporary file followed by atomic replacement. Duplicate marks update no additional ledger entry.

## Fixed clock

`SystemClock` uses each patient's IANA timezone. `FixedClock` accepts a timezone-aware ISO-8601 value supplied by `DEMO_NOW` or `--now`. The same clock controls today, next-dose, status, mutation timestamps, history filtering, CLI, and Gradio behavior.

## Demo-data generation and reset

`scripts/prepare_demo_data.py` builds the ready and unready patients from curated source objects and protected reconciliation profiles. It applies the existing reconciliation, plan, readiness, schedule-generation, and runtime-schema code.

`python app.py reset-demo` generates into a temporary sibling directory, validates the complete expected patient set, and atomically replaces the active runtime directory only after success. It never recreates raw Synthea output or the deleted converted-patient corpus.

## Verification and health

`python app.py verify-demo` validates protected assets, reconciliation profiles, expected patients, schemas, IDs, readiness states, schedules, dose references, timezones, and the active clock. It reports Ollama endpoint, reachability, configured model, model availability, and minimal generation separately. `--require-model` makes model failure fatal.

`python app.py health` is the lighter runtime health view used by the UI. It reports deterministic-data health independently from local-model health.

## Future insertion points

Image input is not implemented. A future image/document extractor must create an unverified candidate for human reconciliation; it must never write directly to the verified plan. Additional voice languages and local TTS remain future work. Neither modality may bypass safety, schemas, readiness, resolution, or deterministic services.
