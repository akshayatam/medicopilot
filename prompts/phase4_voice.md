# Phase 4 — Local Voice Interaction

## Required Reading

Before making changes, read completely:

1. `rules.md`
2. `README.md`
3. `docs/architecture.md`
4. `docs/demo_script.md`
5. `prompts/phase4_voice.md`
6. `ui/gradio_app.py`
7. `gemma/client.py`
8. `gemma/intent_router.py`
9. `gemma/orchestrator.py`
10. `medication/runtime_service.py`
11. `medication/resolver.py`
12. all relevant tests

Treat `rules.md` as the permanent safety specification.

Treat this file as the current implementation task.

Write a concise implementation plan before modifying files.

---

# Context

Medication Copilot currently provides:

- A local Gradio medication dashboard
- Text-based Gemma 4 E2B intent routing
- Deterministic safety screening
- Pydantic intent validation
- Deterministic medication resolution
- Readiness enforcement
- Verified medication plans
- Local dose-log persistence
- Accessible dashboard controls
- Ready and unready demo patients
- Fixed demo clock
- Demo reset and verification commands

The medication runtime is stable.

Voice must extend the existing interaction layer without becoming a new source
of medication facts or bypassing existing safety controls.

---

# Primary Objective

Add fully local voice input to Medication Copilot.

The intended flow is:

```text
Microphone recording
    → local audio validation
    → local transcription
    → visible editable transcript
    → existing deterministic safety screen
    → existing Gemma text intent router
    → Pydantic validation
    → readiness enforcement
    → deterministic medication resolver
    → existing runtime medication service
    → grounded response
```

Voice must use the same backend path as typed text after transcription.

The voice implementation must not duplicate medication logic.

---

# Core Invariant

Voice changes how the user communicates.

Voice must not change:

- Medication facts
- Medication-plan membership
- Readiness decisions
- Allergy meaning
- Schedule meaning
- Dose-log semantics
- Safety refusals
- Medication resolution
- Mutation rules
- Persistence behavior

The transcript becomes ordinary user text only after the user approves it.

---

# Scope

Implement:

- Local microphone recording through Gradio
- Audio-file input for testing
- Audio validation and normalization
- Runtime audio capability probe
- Gemma 4 audio transcription when supported
- Provider abstraction for transcription
- Visible transcript review
- Transcript editing
- Transcript cancellation
- Read-only voice questions
- Explicit confirmation for state-changing voice requests
- Voice-specific session state
- Graceful fallback when audio transcription is unavailable
- Debug metadata without audio content or chain-of-thought
- Automated and manual tests

Optional only after core input works:

- Local text-to-speech for deterministic responses

Do not implement:

- Always-listening mode
- Wake words
- Background recording
- Continuous microphone capture
- Streaming full-duplex conversation
- Automatic execution immediately after transcription
- Cloud speech APIs
- Audio retention by default
- Emotion detection
- Speaker identification
- Medical inference from vocal characteristics
- Voice biometrics

---

# Phase 4A — Runtime Capability Probe

Before implementing the UI flow, inspect the installed Ollama and Gemma runtime.

Add a structured capability probe.

It should report:

```json
{
  "ollama_reachable": true,
  "model_available": true,
  "model_name": "gemma4:e2b",
  "model_declares_audio": true,
  "runtime_accepts_audio": true,
  "transcription_succeeded": true,
  "audio_limit_seconds": 30,
  "fallback_required": false,
  "details": []
}
```

Possible unavailable result:

```json
{
  "ollama_reachable": true,
  "model_available": true,
  "model_declares_audio": true,
  "runtime_accepts_audio": false,
  "transcription_succeeded": false,
  "fallback_required": true,
  "details": [
    "The configured Ollama runtime did not accept audio input."
  ]
}
```

Requirements:

- Do not assume model capability implies runtime support.
- Do not claim transcription works unless a real local audio request succeeds.
- Do not use internet services.
- Do not send patient data during the capability probe.
- Use a harmless bundled or generated test audio sample.
- Keep probe output visible in health/debug tooling.
- Probe failure must not break the text application.

Add a CLI command such as:

```bash
python app.py voice-health
```

or extend:

```bash
python app.py verify-demo --voice
```

Use whichever fits the current CLI design best.

---

# Transcription Provider Abstraction

Create a provider interface.

Suggested design:

```python
from pathlib import Path
from typing import Protocol


class SpeechToTextProvider(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> "TranscriptionResult":
        ...
```

The application should depend on this abstraction rather than directly on
Ollama-specific request structures.

Suggested result model:

```python
class TranscriptionResult(BaseModel):
    text: str
    language: str | None = None
    provider: str
    duration_seconds: float
    processing_ms: float | None = None
    success: bool
    warning: str | None = None
    error_code: str | None = None
```

Required provider:

```text
GemmaAudioTranscriptionProvider
```

Optional fallback:

```text
LocalFallbackTranscriptionProvider
```

Do not add a cloud fallback.

If no local fallback is implemented, fail safely and preserve the text interface.

---

# Gemma Audio Transcription

Use Gemma audio only for transcription.

Do not ask the audio model to:

- Interpret medication intent
- Select medication tools
- Resolve medicines
- Assess safety
- Modify dose logs
- Generate treatment advice

The audio request should produce transcription text only.

Use an ASR-style instruction such as:

```text
Transcribe the following speech segment in {LANGUAGE} into {LANGUAGE} text.

Follow these formatting requirements:
- Output only the transcription.
- Do not add commentary.
- Do not answer the spoken request.
- Write numbers as digits where appropriate.
- Preserve medication names as closely as possible.
```

When the language is unknown:

- Use the configured patient language when available.
- Otherwise use an explicitly selected language.
- Do not silently guess between materially different languages for mutation.
- Return uncertainty when transcription is unreliable.

Do not enable thinking mode for transcription unless the installed runtime is
explicitly verified to support audio plus thinking correctly.

The transcription output must never contain model reasoning.

---

# Audio Input Requirements

Support:

- Microphone recording
- Local audio-file upload for tests

Accept common browser formats where Gradio supports them, then normalize to a
known internal format.

Preferred normalized format:

```text
WAV
mono
16 kHz or provider-required sample rate
PCM
```

Use a local tool or Python library for conversion.

Validate:

- File exists
- Supported format
- Duration is greater than zero
- Duration is no more than 30 seconds
- File size is within a configured limit
- Audio decodes successfully
- Audio is not entirely empty where detectable

Reject safely:

- Corrupt audio
- Unsupported codecs
- Zero-duration recordings
- Audio longer than the configured limit
- Missing file
- Conversion failure

Do not retain raw audio by default.

Temporary files must:

- Use a dedicated temporary directory
- Use non-patient-identifying filenames
- Be deleted after transcription
- Not be committed to Git
- Not be written into runtime patient JSON
- Not appear in debug output as raw bytes or base64

---

# Transcript Review Workflow

Voice input must not execute immediately.

Required sequence:

1. User records or uploads audio.
2. App validates the audio.
3. App transcribes locally.
4. App displays the transcript.
5. User may edit the transcript.
6. User chooses:
   - Submit
   - Record again
   - Cancel
7. Only submitted transcript enters the existing orchestrator.

The UI must show:

```text
I heard:

“Did I take my heart tablet this morning?”
```

Controls:

```text
[Submit transcript]
[Edit]
[Record again]
[Cancel]
```

The transcript must remain editable before submission.

A transcription failure must not call the intent router.

---

# Read-Only Voice Requests

Read-only requests may follow the existing text path after transcript approval.

Examples:

- “What medicine comes next?”
- “What medicines do I have today?”
- “Did I take my heart tablet this morning?”
- “Show my recent medication history.”
- “What do the saved instructions say?”

The final response must still come from deterministic application services.

---

# State-Changing Voice Requests

Voice-derived state-changing requests require an additional confirmation step.

Examples:

- Mark medicine taken
- Record a dose
- Mark the evening medicine as taken
- Record that a dose was skipped

Required flow:

```text
Audio
    → transcript review
    → transcript submitted
    → intent parsed
    → medicine resolved
    → exact proposed mutation displayed
    → explicit confirmation
    → existing runtime service executes
    → persisted result displayed
```

Example:

```text
I understood:

Record the 1:00 PM Vitamin D3 dose as taken.

[Confirm and record]
[Cancel]
```

Confirmation must identify:

- Exact medicine
- Strength where useful
- Scheduled time
- Date
- Proposed action

Do not accept vague confirmations such as:

```text
Record it
```

unless the pending action is session-bound, unexpired, uniquely identified, and
visible to the user.

No state mutation may occur when:

- Transcript is unapproved
- Intent parsing fails
- Medicine is ambiguous
- Medicine is not found
- Patient is unready
- Proposed dose is not uniquely identified
- Confirmation is missing
- Confirmation belongs to another patient
- Session state is stale
- Request is unsafe
- Audio transcription fails

---

# Pending Voice Action State

Store pending mutation state in Gradio session state.

Suggested fields:

```json
{
  "patient_id": "demo-ready-001",
  "action": "MARK_DOSE_TAKEN",
  "medication_id": "med_vitamin_d",
  "scheduled_at": "2026-08-01T13:00:00-04:00",
  "created_at": "2026-08-01T10:01:00-04:00",
  "transcript": "I took my vitamin D",
  "confirmation_required": true
}
```

Requirements:

- Never store pending action globally.
- Clear it when the patient changes.
- Clear it when cancelled.
- Clear it after successful execution.
- Clear it after a configured timeout.
- Validate it again before execution.
- Do not trust client-side state without server-side validation.
- Do not store raw audio in pending action state.

---

# Voice UI

Integrate voice into the existing dashboard without replacing the text interface.

Suggested area:

```text
ASK MEDICATION COPILOT

[Text input                         ] [Ask]

or

[Hold to record / Record message]

Recording limit: 30 seconds
Processed locally
```

After recording:

```text
TRANSCRIPT

“I took my vitamin D.”

[Submit transcript]
[Record again]
[Cancel]
```

For pending mutations:

```text
CONFIRM ACTION

Record Vitamin D3 1000 IU
Scheduled at 1:00 PM
as taken?

[Confirm and record]
[Cancel]
```

Accessibility requirements:

- Large recording button
- Clear recording state
- Visible timer
- Keyboard-accessible controls
- Status text in addition to icons/colors
- Screen-reader labels
- No automatic recording
- No auto-submit
- Clear “processed locally” label
- Error messages in plain language
- Text input remains available

Avoid a microphone icon without text.

Use:

```text
Record a voice question
```

rather than only:

```text
🎤
```

---

# Voice Session State

Session-specific state should include:

- Current transcript
- Transcript approval status
- Pending voice action
- Voice language
- Recording state metadata
- Last transcription result
- Last voice error
- Whether spoken output is enabled
- Last generated speech file if TTS is later enabled

Patient changes must clear:

- Current transcript
- Pending voice mutation
- Patient-specific voice confirmation
- Last answer where appropriate

No state may leak between browser sessions.

---

# Language Support

Start with:

- English
- Patient preferred language when tested
- Optional Hindi only if the configured model/runtime is validated with it

Do not claim multilingual voice support solely because the model is multilingual.

Add a language selector where needed.

Possible values:

```text
English
Hindi
Auto-detect
```

For state-changing actions, prefer an explicitly selected or verified language.

Test medication names, accents, and common older-adult phrasing.

Examples:

- “Did I take my BP medicine?”
- “What is next?”
- “I took my vitamin D.”
- “Mark my evening tablet.”
- “Maine apni dil ki dawai le li.”
- “Aaj kaunsi dawa baaki hai?”

Do not add a language to the advertised feature list until it has a documented
evaluation set and passes safety tests.

---

# Medication-Name Transcription Guardrails

Speech transcription may mishear medication names.

Therefore:

- Preserve the transcript as produced.
- Use the existing deterministic resolver.
- Never autocorrect medication names using unrestricted model knowledge.
- Do not silently convert one medication into another.
- When no verified-plan match exists, return not found.
- When multiple matches exist, ask for clarification.
- Show candidate medication names only from the verified plan.
- Never search raw source medications for patient-facing execution.

For state-changing actions, a fuzzy or phonetic match must not execute without
explicit medication confirmation.

---

# Optional Local Text-to-Speech

TTS is optional in this phase.

Gemma 4 provides text output, not spoken audio output.

If TTS is implemented, use a separate local provider abstraction:

```python
class TextToSpeechProvider(Protocol):
    def synthesize(
        self,
        text: str,
        language: str,
    ) -> "SpeechSynthesisResult":
        ...
```

TTS may speak only:

- Deterministic final responses
- Deterministic safety refusals
- Clarification questions
- Confirmation prompts
- Readiness blocks

TTS must not speak:

- Raw model JSON
- Debug data
- Chain-of-thought
- Internal prompts
- Raw FHIR records
- Sensitive source-record content
- Hidden identifiers

Spoken output controls:

- Play
- Stop
- Replay
- Enable/disable speech

Do not auto-play by default unless explicitly chosen by the user.

Temporary generated speech files must be deleted safely.

If no suitable local TTS is implemented, retain the existing “Repeat last
answer” text behavior and document spoken output as future work.

---

# Safety Screening

Deterministic safety screening must remain before medication execution.

Voice must not weaken handling of:

- Double-dose requests
- Stop-medication requests
- Interaction questions
- Dose-adjustment requests
- Treatment requests
- Symptom-driven medication selection
- Emergency and overdose language

Emergency or overdose requests must bypass ordinary medication actions.

No state mutation may occur.

The spoken or displayed response must preserve the full safety meaning.

---

# Privacy

Requirements:

- All audio processing remains local.
- No cloud API.
- No analytics containing raw transcript or audio by default.
- No audio retained by default.
- No audio embedded in logs.
- No raw transcript added to runtime patient JSON.
- No transcript sent to unrelated model calls.
- No source-record medical history added to the audio prompt.
- Debug output may include transcription metadata and approved text only when
  debug mode is enabled.
- Debug output must never include raw audio bytes or base64.

Show users:

```text
Voice is processed locally and is not saved by default.
```

Do not claim absolute privacy beyond what the implementation guarantees.

---

# Failure Handling

Handle:

- Microphone permission denied
- No microphone
- Empty recording
- Audio too long
- Unsupported codec
- Audio conversion failure
- Ollama unavailable
- Model unavailable
- Runtime does not support audio
- Transcription timeout
- Empty transcription
- Transcription longer than expected
- Invalid characters or malformed output
- Patient switched during transcription
- Pending confirmation expired
- Persistence failure
- UI disconnected during action

Every failure should:

- Produce a clear message
- Avoid traceback exposure
- Avoid mutation
- Preserve the text interface
- Record technical detail only in debug output

---

# Health and Demo Verification

Extend health output with:

```json
{
  "voice": {
    "configured": true,
    "provider": "gemma4_audio",
    "runtime_audio_supported": true,
    "microphone_ui_available": true,
    "transcription_probe": "passed",
    "tts_configured": false
  }
}
```

Extend `verify-demo` or add a voice verification command.

Recommended:

```bash
python app.py verify-demo --voice
```

Strict:

```bash
python app.py verify-demo --voice --require-model
```

Verify:

- Provider loads
- Test audio validates
- Transcription works
- Transcript is non-empty
- No raw audio remains after completion
- Existing text checks still pass
- Voice unavailability does not break text mode

---

# Evaluation Dataset

Create a local voice evaluation set.

Suggested structure:

```text
evaluation/voice/
├── manifest.jsonl
└── audio/
```

Each manifest row should contain:

```json
{
  "id": "voice_001",
  "audio_file": "audio/voice_001.wav",
  "language": "en-US",
  "expected_transcript_contains": ["heart tablet"],
  "expected_action": "CHECK_DOSE_STATUS",
  "expected_medication": "Metoprolol succinate ER",
  "state_changing": false,
  "unsafe": false
}
```

Do not include real patient recordings.

Use synthetic or developer-recorded non-sensitive test phrases.

Do not commit recordings containing personal health information.

Include cases for:

- Clear read-only request
- Quiet speech
- Faster speech
- Accent variation
- Medication aliases
- Ambiguous medicine
- Not-found medicine
- Unsafe dose request
- State-changing request
- Background noise
- Empty audio
- Audio over 30 seconds
- Hindi/Hinglish only if supported and tested

Track separately:

- Transcription accuracy
- Intent accuracy
- Resolver accuracy
- Unsafe-request recall
- Mutation-confirmation compliance
- Latency
- Failure rate

---

# Tests

Standard tests must not require a live microphone or live Ollama.

Mock:

- Audio provider
- Transcription result
- Model client
- Runtime clock
- Persistence where appropriate

Add tests for:

## Audio validation

- Valid WAV accepted
- Missing audio rejected
- Empty audio rejected
- Corrupt audio rejected
- Over-30-second audio rejected
- Temporary audio deleted
- Unsupported audio produces safe error

## Transcription

- Successful transcription
- Empty transcription
- Provider unavailable
- Timeout
- Malformed provider response
- Audio thinking mode disabled when required
- Raw audio not stored

## Transcript review

- Transcript not auto-submitted
- User can edit transcript
- Cancel clears transcript
- Record again clears previous pending state
- Patient switch clears transcript

## Read-only voice flow

- Approved transcript enters existing orchestrator
- Correct action
- Correct resolver result
- Grounded response
- No duplicated medication logic

## Mutation confirmation

- Voice mutation does not execute before confirmation
- Confirmed unique medication executes once
- Cancelled mutation does not execute
- Ambiguous medication cannot reach confirmation
- Expired confirmation cannot execute
- Patient switch invalidates confirmation
- Duplicate confirmation is idempotent
- Unready patient cannot mutate
- Unsafe request cannot mutate

## Privacy

- Audio bytes absent from logs
- Audio absent from runtime JSON
- Temporary recording deleted
- Full source record not sent to transcription provider
- Sensitive conditions not sent
- Debug output does not contain audio bytes

## Session isolation

- Two sessions do not share transcripts
- Two sessions do not share pending mutations
- Two sessions do not share language settings

## Regression

- All existing text interactions still work
- Existing UI quick actions still work
- Existing safety tests still pass
- Existing readiness tests still pass
- Existing reset and verify commands still pass

---

# Suggested File Structure

Adapt to the repository rather than forcing exact paths.

Possible additions:

```text
voice/
├── schemas.py
├── audio.py
├── providers.py
├── gemma_audio.py
├── service.py
└── safety.py

evaluation/
└── voice/

tests/
├── test_voice_audio.py
├── test_voice_transcription.py
├── test_voice_confirmation.py
├── test_voice_privacy.py
└── test_voice_integration.py
```

Do not move stable backend modules unnecessarily.

---

# UI Acceptance Criteria

The voice interface is acceptable only when:

1. Recording never starts automatically.
2. Recording has a visible active state.
3. Recording duration is visibly limited.
4. Audio is processed locally.
5. Audio is not saved by default.
6. Transcript appears before execution.
7. Transcript is editable.
8. User may cancel.
9. Read-only transcript uses the existing orchestrator.
10. Mutation requests require a second explicit confirmation.
11. Exact medicine and scheduled dose are shown before mutation.
12. Ambiguous medicine does not mutate.
13. Unready patient does not mutate.
14. Unsafe request does not mutate.
15. Text input remains available.
16. Voice failure does not break the dashboard.
17. No chain-of-thought is shown or spoken.
18. No raw audio appears in debug output.
19. Patient switching clears pending voice state.
20. Two browser sessions remain isolated.

---

# Backend Acceptance Criteria

1. Existing runtime schemas remain unchanged unless a separate ephemeral voice
   schema is added.
2. Voice-specific state is not written into the patient clinical record.
3. Existing medication services remain the only mutation path.
4. Existing deterministic resolver remains authoritative.
5. Existing safety screening remains authoritative.
6. Existing readiness enforcement remains authoritative.
7. Existing persistence remains idempotent.
8. Standard tests do not require Ollama.
9. Live audio behavior is reported honestly.
10. No cloud service is introduced.

---

# Implementation Order

## Phase 4A

- Audit Ollama/Gemma audio support
- Add capability probe
- Add audio schemas
- Add provider abstraction
- Add audio validation

## Phase 4B

- Implement Gemma audio transcription
- Add local normalization
- Add temporary-file cleanup
- Add transcription tests

## Phase 4C

- Add Gradio microphone and upload controls
- Add transcript review
- Add transcript edit/cancel/re-record flow
- Connect approved transcript to existing orchestrator

## Phase 4D

- Add pending mutation confirmation
- Add session-state expiry
- Add patient-switch invalidation
- Add mutation tests

## Phase 4E

- Extend health and verification
- Add voice evaluation cases
- Run live audio smoke tests
- Update README and architecture docs
- Update demo script

## Optional Phase 4F

- Add local TTS provider
- Add play/stop/replay controls
- Add TTS safety and privacy tests

Do not begin TTS until input, review, confirmation, and safety flows are stable.

---

# Required Verification

Run:

```bash
pytest -m "not integration"
python -m compileall -q app.py medication gemma ui scripts evaluation voice
python app.py reset-demo
python app.py verify-demo
git diff --check
```

When Ollama audio works:

```bash
python app.py verify-demo --voice --require-model
```

Perform live tests:

- “What medicine comes next?”
- “Did I take my heart tablet this morning?”
- “I took my vitamin D.”
- “Mark my tablet as taken.”
- “I missed yesterday. Should I take two today?”
- Unready-patient voice request
- Empty recording
- Audio longer than 30 seconds
- Ollama stopped during transcription

After state-changing tests, reset demo data.

---

# Documentation

Update:

- `README.md`
- `docs/architecture.md`
- `docs/demo_script.md`
- `docs/roadmap.md`
- `CONTRIBUTING.md`

Document:

- Local-only voice flow
- Provider used
- Supported languages actually tested
- Audio duration limit
- Transcript review
- Confirmation workflow
- Privacy behavior
- Runtime limitations
- Ollama compatibility
- TTS status
- Exact commands for voice verification

Do not claim real-time voice chat if the implementation is record–transcribe–
review–submit.

---

# Final Report

Report:

- Audio runtime audit
- Ollama version
- Model name
- Whether native Gemma audio worked
- Provider implementation
- Fallback implementation, if any
- UI flow
- Confirmation behavior
- Privacy behavior
- Temporary-file cleanup
- Files changed
- Tests added
- Full test totals
- Live audio tests
- Languages tested
- Latency measurements
- Whether TTS was implemented
- Known limitations
- Any runtime regressions

Do not claim voice support unless live audio was successfully tested.

Do not weaken any rule to make a voice demo pass.
